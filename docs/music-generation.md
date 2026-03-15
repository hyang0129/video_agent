# Music Generation — ACE-Step Integration

Background music is generated locally via the **ACE-Step v1.5** music model.
The pipeline generates a unique instrumental track per video using an LLM-crafted
description derived from the script package.

---

## Architecture

```
FullPipelineRunner
  └── GpuServerManager          # serial GPU lifecycle (video_agent/tools/gpu_server_manager.py)
       ├── mgr.chatterbox()     # start Chatterbox TTS → run AudioAgent → stop
       └── mgr.acestep()        # start ACE-Step → run MusicAgent → stop (or reuse)

MusicAgent (video_agent/music_agent.py)
  └── _describe_music()         # LLM crafts ACE-Step caption from script
  └── AceStepClient.generate_sync()  # submits task, polls, downloads MP3
```

The two GPU servers run **serially** — Chatterbox is stopped before ACE-Step starts —
so a 12 GB GPU can handle both without OOM.

---

## Prerequisites

### 1. ACE-Step server (`ace_step_server`)

The inference server must be installed in the workspace at
`/workspaces/hub/repos/ace_step_server/` with its own `uv`-managed venv.

```bash
cd /workspaces/hub/repos/ace_step_server
uv sync          # installs deps + creates .venv/
uv run acestep-api --help   # verify install
```

The `acestep-api` binary must exist at:
```
/workspaces/hub/repos/ace_step_server/.venv/bin/acestep-api
```

### 2. ACE-Step client library (`ace_step`)

The client library lives at `repos/ace_step/` and must be installed into
video_agent's venv:

```bash
source /workspaces/.venvs/video_agent/bin/activate
pip install -e /workspaces/hub/repos/ace_step/
```

Verify with:
```bash
python -c "from ace_step.client import AceStepClient; print('ok')"
```

### 3. GPU + CUDA

ACE-Step requires a CUDA GPU with at least **6 GB VRAM** free when the
model loads. The full pipeline needs ~2–3 GB for Chatterbox + ~6 GB for
ACE-Step, but they run serially so peak VRAM is ~6 GB.

---

## Cold-Start Warning

ACE-Step takes **~2–3 minutes** to start from scratch (model weights load into
GPU). `GpuServerManager` will wait up to 5 minutes (`ACESTEP_STARTUP_TIMEOUT=300`).

**If ACE-Step is already running** on port 8001 when the pipeline starts,
`GpuServerManager` detects this via a health check and reuses it, skipping
the cold start entirely. This saves 2–3 minutes on repeat runs.

To pre-warm ACE-Step before running the pipeline:
```bash
cd /workspaces/hub/repos/ace_step_server
ACESTEP_INIT_LLM=false .venv/bin/acestep-api --host 0.0.0.0 --port 8001 &
# wait ~3 minutes for model to load, then run the pipeline
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MUSIC_BACKEND` | `default` | `acestep` or `default` (uses `assets/default_music.mp3`) |
| `ACESTEP_BASE_URL` | `http://localhost:8001` | ACE-Step server URL |
| `ACESTEP_PORT` | `8001` | Port for GpuServerManager to start the server on |
| `ACESTEP_APP_DIR` | `/workspaces/hub/repos/ace_step_server` | Path to ace_step_server repo |
| `ACESTEP_POLL_INTERVAL` | `1.0` | Seconds between generation status polls |
| `ACESTEP_POLL_TIMEOUT` | `300` | Max seconds to wait for a generation task |

Set in `.env` to override defaults.

---

## How Music Is Generated

1. `MusicAgent._describe_music()` calls the LLM with the script's voiceover
   lines and tone, producing a structured spec:
   ```json
   { "description": "orchestral, epic, ...", "bpm": 100, "key": null, "guidance_scale": 7.5 }
   ```

2. `AceStepClient.generate_sync()` posts to `/release_task` on the ACE-Step
   server, polls `/query_result` until `status=1` (succeeded), then downloads
   the audio from `/v1/audio`.

3. The MP3 is saved to `<run_dir>/music_generated.mp3` and a
   `music_selection.json` artifact is written with metadata (duration, BPM,
   description, task ID).

4. The compositor mixes the music at **-18 dB** under the voiceover.

---

## Disabling Music

To skip music generation (e.g. on a CPU-only machine):

```bash
MUSIC_BACKEND=default python scripts/run_full_pipeline.py ...
```

Or set `enable_music=False` in `FullPipelineConfig` when calling
`FullPipelineRunner` programmatically.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `[WARN] ACE-Step auto-start skipped: acestep-api binary not found` | Client library or server not installed | Run `uv sync` in `ace_step_server/`, then `pip install -e repos/ace_step/` |
| `[WARN] ACE-Step did not become healthy within 300s` | Model download or VRAM OOM during load | Check `run_dir/acestep.log`; ensure ≥6 GB VRAM free |
| `[WARN] Music generation failed: ACE-Step server unreachable` | Server crashed after health check | Check `run_dir/acestep.log` for the crash reason |
| Music generated but sounds wrong for the content | LLM music description not calibrated for short-form | See [GitHub issue #10](https://github.com/hyang0129/video_agent/issues/10) — pending human review |

### Reading server logs

When the pipeline runs, ACE-Step and Chatterbox write logs to the run directory:

```
results/test/<run_id>/
  chatterbox.log   # Chatterbox TTS server stdout+stderr
  acestep.log      # ACE-Step server stdout+stderr
```

Check these first on any server startup failure.

---

## Known Limitations

- Music prompt quality for short-form content is not yet calibrated — see
  [issue #10](https://github.com/hyang0129/video_agent/issues/10).
- ACE-Step `--init-llm` is disabled (`ACESTEP_INIT_LLM=false`) to save VRAM;
  lyric/vocal generation is not available.
- The pipeline does not yet trim or loop the generated music to match video
  duration exactly — the compositor uses the raw output.
