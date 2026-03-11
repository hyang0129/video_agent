# Chatterbox TTS Integration Plan

**Status:** Draft — pre-implementation
**Branch:** feat/live2d-submodule
**Replaces:** ElevenLabs (`src/tools/tts_tools.py::generate_voiceover`)

---

## 1. Goal

Replace ElevenLabs TTS with the local Chatterbox Turbo model to eliminate the
10k char/month free-tier cap and cloud dependency. Both a **direct** (in-process
GPU) and a **server** (FastAPI HTTP) mode must be supported behind an identical
API contract so the `AudioAgent` is unaware of which backend it uses.

---

## 2. Shared API Contract

Both modes accept the same request shape and return raw WAV bytes (PCM_16,
24 kHz mono). The server already implements this; the direct wrapper mirrors it.

**Request (JSON-serialisable dict):**

```python
{
    "text": str,                    # required, 1–5000 chars
    "temperature":        float,    # default 0.8,  range [0.1, 2.0]
    "top_p":              float,    # default 0.95, range [0.0, 1.0]
    "top_k":              int,      # default 1000, range [1, 5000]
    "repetition_penalty": float,    # default 1.2,  range [1.0, 3.0]
}
```

**Response:**  `bytes` — PCM_16 WAV, 24 kHz, mono, standard RIFF header.

The `AudioAgent` writes the bytes to `{run_dir}/audio_segments/{slug}.wav`
and continues exactly as it does today, replacing only the ElevenLabs HTTP call.

---

## 3. Two Backend Modes

### 3a. Direct mode (`backend="chatterbox_direct"`)

The model is loaded once into the calling process and GPU, then segments are
synthesised **serially** — one at a time.

```
AudioAgent
  └── ChatterboxDirectBackend
        ├── __init__: ChatterboxTurboTTS.from_pretrained(device="cuda")
        ├── synthesize(request_dict) -> bytes   # one at a time, no queue needed
        └── close()                             # no-op; GC releases GPU mem
```

**Why serial-only:**
The Turbo model occupies ~3–4 GB VRAM. A single RTX 5070 Ti Laptop (12 GB) can
hold one model instance. Running two `generate()` calls concurrently on the same
instance is not thread-safe and risks CUDA OOM. The audio agent must therefore
await each segment before starting the next.

**Orchestrator implication:**
The orchestrator's `serial=True` flag already exists for this scenario. When
`backend="chatterbox_direct"` is selected, the orchestrator **must not** pass
the audio stage to a `ThreadPoolExecutor`. The existing serial path handles this
correctly; add a guard asserting `serial=True` when the direct backend is
detected at startup.

### 3b. Server mode (`backend="chatterbox_server"`)

A long-running `uvicorn` process hosts the FastAPI app from
`vendor/chatterbox/app/main.py`. The `AudioAgent` sends HTTP POST requests to
`CHATTERBOX_SERVER_URL` (e.g. `http://localhost:8000`).

```
AudioAgent
  └── ChatterboxServerBackend
        └── synthesize(request_dict) -> bytes
              POST /tts  →  audio/wav bytes
```

**Server-side concurrency:**
FastAPI + uvicorn is async but `model.generate()` is CPU/GPU-bound and blocks
the event loop. The server must serialise inference with an `asyncio.Lock` held
for the duration of each generate call. Concurrent HTTP requests queue behind
the lock; they do not fail or timeout unless the queue grows unbounded.

Recommended server-side pattern (add to `app/main.py`):

```python
# In lifespan:
app.state.lock = asyncio.Lock()

# In synthesize():
async with app.state.lock:
    wav = await asyncio.get_event_loop().run_in_executor(
        None, lambda: model.generate(req.text, ...)
    )
```

`run_in_executor` moves blocking inference off the event loop thread so uvicorn
can still accept new connections while inference runs. The `asyncio.Lock` ensures
only one inference is active at a time.

**Client-side retry on server failure:**
`ChatterboxServerBackend` reuses `tts_tools._get_retry_session()` directly — the same
`requests.Session` + `HTTPAdapter` + `urllib3.Retry(total=3, backoff_factor=1,
status_forcelist=[429,500,502,503,504])` already used by the ElevenLabs backend. No
new retry logic is needed. After exhausting retries, `requests` raises
`requests.exceptions.RequestException`; the backend catches this, marks the segment
`degraded` in `production_report.json`, and writes a silent placeholder WAV so
downstream stages are not blocked. This mirrors the existing ElevenLabs degraded-scene
logic.

---

## 4. Backend Selection

Add `TTS_BACKEND` to `src/config.py`:

```python
TTS_BACKEND = os.getenv("TTS_BACKEND", "elevenlabs")
# Values: "elevenlabs" | "chatterbox_direct" | "chatterbox_server"

CHATTERBOX_SERVER_URL = os.getenv("CHATTERBOX_SERVER_URL", "http://localhost:8000")
```

`create_audio_agent()` (or a new `create_tts_backend()` factory) reads
`TTS_BACKEND` and returns the appropriate backend instance. The `AudioAgent` is
passed the backend at construction; it calls `backend.synthesize(request_dict)`
without knowing which backend is active.

---

## 5. File Layout

```
src/tools/
  tts_tools.py               # existing ElevenLabs backend (unchanged)
  chatterbox_backend.py      # NEW — ChatterboxDirectBackend + ChatterboxServerBackend
src/
  audio_agent.py             # modify: accept backend kwarg; call backend.synthesize()
  config.py                  # add: TTS_BACKEND, CHATTERBOX_SERVER_URL
```

No new directories. No changes to artifact schemas or downstream agents.

### `chatterbox_backend.py` sketch

```python
class TTSRequest:
    text: str
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int = 1000
    repetition_penalty: float = 1.2

    def as_dict(self) -> dict: ...


class ChatterboxDirectBackend:
    def __init__(self): ...            # loads model onto CUDA
    def synthesize(self, req: TTSRequest) -> bytes: ...  # serial; returns WAV bytes
    def close(self): ...


class ChatterboxServerBackend:
    def __init__(self, base_url: str): ...   # stores base_url; calls _get_retry_session()
    def synthesize(self, req: TTSRequest) -> bytes: ...  # HTTP POST /tts; retries via session
    def close(self): ...                     # calls self._session.close() — releases socket pool
```

Both implement the same two-method duck-type interface: `synthesize(req)` and
`close()`.

---

## 6. AudioAgent Changes

Current call site in `audio_agent.py` (approximate):

```python
path, meta = generate_voiceover(text, voice_id=..., output_path=...)
```

New call site:

```python
wav_bytes = self._tts.synthesize(TTSRequest(text=segment_text))
output_path.write_bytes(wav_bytes)
```

Duration is measured via `ffprobe` on the written WAV (already done for MP3
segments today). No metadata dict is needed from the backend — duration comes
from the file.

---

## 7. Failure Handling Summary

| Failure | Direct mode | Server mode |
|---------|-------------|-------------|
| CUDA OOM | Exception → mark segment degraded, skip | N/A (server-side) |
| Model not loaded | Raise at startup, abort pipeline | HTTP 503 → retry 3x → degraded |
| Inference error | Exception → degraded | HTTP 5xx → retry 3x → degraded |
| Server unreachable | N/A | `ConnectionError` → retry 3x → degraded |
| Empty text | Validate before calling backend | HTTP 422 → raise immediately, no retry |

Degraded segments use a silent placeholder WAV of the same estimated duration.
The `production_report.json` records `status: "degraded"` with the error message.
The pipeline continues; the renderer will produce a video with silent gaps, which
is still reviewable by a human.

---

## 8. Orchestrator: Direct Mode Constraint

Add a startup check in `orchestrator.py`:

```python
if cfg.tts_backend == "chatterbox_direct" and not cfg.serial:
    raise RuntimeError(
        "[ERROR] chatterbox_direct backend requires serial=True "
        "(GPU model is not safe for concurrent inference)"
    )
```

This prevents silent correctness bugs where two threads race on the same model
instance.

---

## 9. Implementation Order

1. `src/config.py` — add `TTS_BACKEND`, `CHATTERBOX_SERVER_URL`
2. `src/tools/chatterbox_backend.py` — `TTSRequest`, `ChatterboxDirectBackend`, `ChatterboxServerBackend`
3. `app/main.py` in chatterbox submodule — add `asyncio.Lock` + `run_in_executor` for concurrency safety
4. `src/audio_agent.py` — accept backend kwarg; replace `generate_voiceover` call
5. `src/orchestrator.py` — add direct-mode serial guard
6. Tests — unit tests with mocked backend; integration test using `chatterbox_server` against a running server

---

## 10. Not In Scope

- Voice cloning (`/tts/clone`) — deferred; pipeline uses a single narrator voice
- Gradio UI / `gradio==5.44.1` dependency — not installed, not needed
- Multi-GPU sharding — single GPU sufficient for the target use case
- ElevenLabs removal — keep as fallback; selected by `TTS_BACKEND=elevenlabs`
