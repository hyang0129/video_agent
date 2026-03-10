# MCP Producer Server — Implementation Plan

**Date:** March 2026
**Prerequisite reading:** [mcp-architecture-upgrade.md](mcp-architecture-upgrade.md), [mcp-implementation-plan.md](mcp-implementation-plan.md)
**Goal:** Concrete, sequenced steps to implement the `producer-server` MCP server and the Phase 2 prerequisites it depends on.

---

## Current State

Phase 1 (screenwriting split) is complete:

- `src/screenwriting/concept_agent.py` — generates N concepts from a TopicBrief
- `src/screenwriting/screenplay_agent.py` — writes Screenplay + `revise_scene()`
- `src/screenwriting/screenplay_reviewer.py` — heuristic feasibility validator (no API calls)
- `src/artifacts/screenplay.py` — artifact schemas + `screenplay_to_script_package()` bridge
- `src/screenwriting/format_library/` — `facts`, `storytime`, `tutorial`, `debate` templates
- `main.py screenplay` command — end-to-end: concept → screenplay → review → revision → production

**Not yet built:**
- `ProductionReport` emission from `ScriptImageAgent` and `AudioAgent` (P1-6, still open)
- `src/orchestrator.py` (Phase 2)
- `src/mcp/producer_server.py` (Phase 3)
- `src/mcp/screenwriting_server.py` (Phase 3)

---

## Phase 2 Prerequisites (Before the MCP Server)

The producer server wraps agents that need small additions before they can be called as MCP tools. These are also the remaining Phase 1 item (P1-6) and Phase 2 items.

### P2-0: ProductionReport emission (remaining P1-6)

**Files:** `src/script_image_agent.py`, `src/audio_agent.py`

Both agents currently fail silently. They need to accumulate issues and write `production_report.json` so the orchestrator and (later) the MCP server can surface structured failures.

#### ScriptImageAgent changes

Find the fallback-to-placeholder path and accumulate an issue dict:

```python
# At the point where a BMP placeholder is used:
production_issues.append({
    "agent": "ScriptImageAgent",
    "scene_id": scene_id,           # the beat ID or scene index as string
    "status": "degraded",
    "issue": "no_relevant_image",
    "detail": f"Best result relevance {best_score:.2f}, threshold {RELEVANCE_THRESHOLD:.2f}",
    "suggestion": "Rephrase visual.description to be more concrete and specific",
    "revision_field": "visual",
    "revision_possible": True,
})
```

At end of `generate()`, write:

```python
write_json(run_dir / "production_report.json", {
    "schema_version": "1.0.0",
    "run_id": run_id,
    "issues": production_issues,
    "degraded_scene_count": sum(1 for i in production_issues if i["status"] == "degraded"),
})
```

#### AudioAgent changes

Same pattern. Two issue types:

```python
# TTS API failure:
production_issues.append({
    "agent": "AudioAgent",
    "scene_id": scene_id,
    "status": "degraded",
    "issue": "tts_failed",
    "detail": str(e),
    "suggestion": "Simplify vo_line: remove special characters, shorten to under 20 words",
    "revision_field": "vo_line",
    "revision_possible": True,
})

# Duration overshoot (actual > target * 1.2):
production_issues.append({
    "agent": "AudioAgent",
    "scene_id": scene_id,
    "status": "degraded",
    "issue": "vo_too_long",
    "detail": f"TTS duration {actual:.1f}s, target {target:.1f}s",
    "suggestion": f"Shorten vo_line from {word_count} words to ~{target_words} words",
    "revision_field": "vo_line",
    "revision_possible": True,
})
```

Both agents share the same output schema. If both run in the same pipeline pass, their issues are written to the same `production_report.json` (merge at write time, not per-agent).

**Exit criterion:** `results/<run>/production_report.json` exists after every pipeline run; degraded scenes are identifiable by `scene_id` and `revision_field`.

---

### P2-1: scene_ids filter param on AudioAgent and ScriptImageAgent

**Why:** The orchestrator's revision loop re-runs only degraded scenes. Agents need to accept a list of scene IDs to process instead of always processing all scenes.

**Change:** Add an optional `scene_ids: list[str] | None = None` parameter to each agent's main generation method. When provided, skip all scenes not in the list. When `None`, process all (existing behavior, no regression).

```python
# AudioAgent example
def generate(self, video_plan: dict, run_dir: Path, scene_ids: list[str] | None = None) -> dict:
    beats = video_plan.get("script", {}).get("beats") or []
    for beat in beats:
        sid = str(beat.get("scene_id") or beat.get("t_start_s"))
        if scene_ids is not None and sid not in scene_ids:
            continue   # skip, carry forward cached result
        ...
```

**Exit criterion:** Passing `scene_ids=["scene_03"]` causes the agent to process only that scene; all other scenes return their previously cached results.

---

### P2-2: Orchestrator with scene_results ledger

**File:** `src/orchestrator.py`

The orchestrator owns the central `scene_results` dict and runs the revision loop. It is the only component that merges multi-round production results before handing off to the compositor.

```python
# scene_results: scene_id -> production result
scene_results: dict[str, dict] = {}
# {
#   "scene_01": {"audio_path": "...", "image_paths": [...], "status": "ok"},
#   "scene_03": {"audio_path": None, "image_paths": [], "status": "degraded",
#                "issue": "no_relevant_image", "revision_field": "visual",
#                "revision_possible": True},
# }
```

**Revision loop (sequential, Phase 2 baseline):**

```python
MAX_REVISION_ROUNDS = 2

# Round 0: full production
audio_results = audio_agent.generate(screenplay_as_video_plan, run_dir)
image_results = image_agent.generate(script_package, run_dir)
scene_results = merge_results(audio_results, image_results, screenplay)

for round_num in range(1, MAX_REVISION_ROUNDS + 1):
    degraded = {
        sid: r for sid, r in scene_results.items()
        if r["status"] == "degraded" and r.get("revision_possible")
    }
    if not degraded:
        break

    print(f"[INFO] Revision round {round_num}: {len(degraded)} degraded scenes")

    for scene_id, result in degraded.items():
        screenplay = screenplay_agent.revise_scene(
            screenplay, scene_id,
            issue=result["issue"],
            suggestion=result["suggestion"],
            revision_field=result["revision_field"],
        )
        del scene_results[scene_id]

    revised_ids = list(degraded.keys())

    # Re-run only revised scenes
    skip_audio = {sid for sid, r in degraded.items() if r["revision_field"] == "visual"}
    skip_images = {sid for sid, r in degraded.items() if r["revision_field"] == "vo_line"}

    if revised_ids != list(skip_audio):  # some scenes need new audio
        re_audio = audio_agent.generate(..., scene_ids=[s for s in revised_ids if s not in skip_audio])
    if revised_ids != list(skip_images):  # some scenes need new images
        re_images = image_agent.generate(..., scene_ids=[s for s in revised_ids if s not in skip_images])

    scene_results.update(merge_results(re_audio, re_images, screenplay, scene_ids=revised_ids))

# Compose from final scene_results
full_manifest = assemble_manifest(screenplay, scene_results)
compositor.compose(full_manifest)
```

`assemble_manifest()` constructs the VisualManifest from `scene_results`, hiding the multi-round history from the compositor.

**Exit criterion:** `python main.py screenplay ... ` runs the orchestrator, degraded scenes trigger revision, `production_report.json` and `scene_results.json` are both written to the run dir.

---

### P2-3: Parallel audio + image fetch (asyncio + ThreadPoolExecutor)

Parallel execution makes sense only after the sequential loop works correctly. Add after P2-2 is verified:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def produce_scenes_parallel(screenplay, scenes, skip_audio=None, skip_images=None):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as pool:
        audio_fut = loop.run_in_executor(pool, audio_agent.generate, ..., skip_audio)
        image_fut = loop.run_in_executor(pool, image_agent.generate, ..., skip_images)
        audio_results, image_results = await asyncio.gather(audio_fut, image_fut)
    return audio_results, image_results
```

Expected wall-clock improvement: audio (~20-30s) and image fetch (~10-15s) overlap instead of stacking.

---

## Phase 3: Producer Server MCP Tools

**File:** `src/mcp/producer_server.py`

**Install:** `pip install mcp` (add to `requirements.txt`)

The server exposes six tools. Two are lightweight pre-flight probes; four wrap existing agents.

---

### Tool 1: `check_asset_availability`

**Purpose:** Pre-flight check — given a visual description, how available are Pexels results?
Called by `ScreenplayReviewer` during the writing phase before committing to production.
**Cost:** One Pexels API call per invocation (free tier allows 200 req/hr).
**Does NOT download images.** Returns metadata only.

**Input schema:**
```json
{
    "query": "string — the visual.description or a Pexels search query",
    "n_results": "integer, default 5 — how many results to probe"
}
```

**Output schema:**
```json
{
    "query": "...",
    "result_count": 5,
    "top_relevance_score": 0.72,
    "availability": "good",
    "top_results": [
        {"url": "...", "resolution": [3000, 4500], "relevance_score": 0.72}
    ],
    "recommendation": "ok"
}
```

`availability` values: `"good"` (top score >= 0.6), `"marginal"` (0.35-0.6), `"poor"` (< 0.35).
`recommendation` values: `"ok"` | `"rephrase"` | `"reject"`.

**Implementation:**

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "check_asset_availability":
        query = arguments["query"]
        n = int(arguments.get("n_results", 5))

        try:
            results = search_pexels_images(query, per_page=n, orientation="portrait")
        except ImageSearchError as e:
            return [TextContent(type="text", text=json.dumps({
                "query": query, "error": str(e), "availability": "unknown",
                "recommendation": "rephrase",
            }))]

        if not results:
            return [TextContent(type="text", text=json.dumps({
                "query": query, "result_count": 0,
                "top_relevance_score": 0.0, "availability": "poor",
                "recommendation": "reject",
            }))]

        # Reuse the existing relevance scoring from ScriptImageAgent
        scores = [_score_result(r, query) for r in results]
        top_score = max(scores)
        availability = "good" if top_score >= 0.6 else ("marginal" if top_score >= 0.35 else "poor")
        recommendation = "ok" if top_score >= 0.6 else ("rephrase" if top_score >= 0.35 else "reject")

        return [TextContent(type="text", text=json.dumps({
            "query": query,
            "result_count": len(results),
            "top_relevance_score": round(top_score, 3),
            "availability": availability,
            "recommendation": recommendation,
            "top_results": [
                {"url": r["url"], "resolution": r.get("resolution", []), "relevance_score": round(s, 3)}
                for r, s in sorted(zip(results, scores), key=lambda x: -x[1])[:3]
            ],
        }))]
```

**Where to source `_score_result`:** The relevance scoring logic lives inside `ScriptImageAgent`. Extract it to a module-level function in `src/tools/image_search_tools.py` so both the agent and the MCP tool share it without duplication.

---

### Tool 2: `estimate_tts_duration`

**Purpose:** Pre-flight check — how long will this line take to speak?
No API call. Pure heuristic based on character and word count.
Called by `ScreenplayReviewer` to catch obvious timing violations before production.

**Input schema:**
```json
{
    "text": "string — the vo_line to estimate",
    "voice_preset": "string — calm | narrator | energetic | authoritative"
}
```

**Output schema:**
```json
{
    "text_length_chars": 142,
    "word_count": 28,
    "estimated_duration_s": 11.2,
    "voice_preset": "calm",
    "wpm_used": 150,
    "confidence": "heuristic"
}
```

**Voice preset WPM table** (calibrated against ElevenLabs output observed in existing runs):

| Preset | WPM |
|--------|-----|
| `calm` | 130 |
| `narrator` | 150 |
| `energetic` | 170 |
| `authoritative` | 140 |

No API call. Formula: `duration_s = (word_count / wpm) * 60`. This is the same heuristic used in `ScreenplayReviewer._estimated_speech_seconds()` — make both call a shared function in `src/utils/tts_utils.py`.

**Implementation:**

```python
_WPM_BY_PRESET = {
    "calm": 130,
    "narrator": 150,
    "energetic": 170,
    "authoritative": 140,
}

if name == "estimate_tts_duration":
    text = str(arguments.get("text", ""))
    preset = str(arguments.get("voice_preset", "narrator"))
    wpm = _WPM_BY_PRESET.get(preset, 150)
    words = len(text.split())
    duration = (words / wpm) * 60.0
    return [TextContent(type="text", text=json.dumps({
        "text_length_chars": len(text),
        "word_count": words,
        "estimated_duration_s": round(duration, 2),
        "voice_preset": preset,
        "wpm_used": wpm,
        "confidence": "heuristic",
    }))]
```

---

### Tool 3: `generate_audio`

**Purpose:** Run TTS voiceover for one or more scenes. Wraps `AudioAgent`.
Heavy tool — makes ElevenLabs API calls. Called by the orchestrator in the producing phase, not during the writing phase.

**Input schema:**
```json
{
    "screenplay": { "...": "Screenplay dict" },
    "scene_ids": ["scene_01", "scene_02"],
    "run_dir": "string — path to the run results directory",
    "voice_preset": "calm"
}
```

`scene_ids` is optional. If omitted, generate audio for all scenes.

**Output schema:**
```json
{
    "status": "ok",
    "audio_timeline": { "...": "AudioTimeline dict" },
    "segments": [
        {
            "scene_id": "scene_01",
            "audio_path": "results/run_id/audio_segments/scene_01.mp3",
            "duration_s": 6.3,
            "status": "ok"
        }
    ],
    "production_issues": []
}
```

**Implementation:** Instantiate `AudioGenerationAgent`, call `generate()` with the scene_ids filter (from P2-1), return the audio timeline + any accumulated production issues.

The tool does not translate the Screenplay to a VideoPlan itself — the orchestrator does that conversion upstream via `screenplay_to_script_package()` before calling this tool.

---

### Tool 4: `fetch_assets`

**Purpose:** Retrieve and download images for one or more scenes. Wraps `ScriptImageAgent`.
Heavy tool — makes Pexels API calls and downloads images. Called by the orchestrator, not during writing.

**Input schema:**
```json
{
    "script_package": { "...": "ScriptPackage dict" },
    "scene_ids": ["scene_01"],
    "run_dir": "string"
}
```

**Output schema:**
```json
{
    "status": "ok",
    "visual_manifest": { "...": "ScriptImageManifest dict" },
    "scene_assets": [
        {
            "scene_id": "scene_01",
            "image_paths": ["results/run_id/images/scene_01_0.jpg"],
            "relevance_score": 0.74,
            "status": "ok"
        }
    ],
    "production_issues": []
}
```

Production issues here are the same structs written to `production_report.json` (from P2-0). The MCP tool surfaces them in the response so the orchestrator can act on them immediately without reading a file.

---

### Tool 5: `render_video`

**Purpose:** Run the full compositor + FFmpeg render from a completed manifest. Wraps `CompositorAgent` and `RenderAgent`.
Called by the orchestrator only after all scenes have `status: ok` or accepted-degraded.

**Input schema:**
```json
{
    "visual_manifest": { "...": "VisualManifest or ScriptImageManifest dict" },
    "audio_timeline": { "...": "AudioTimeline dict" },
    "run_dir": "string",
    "engine": "ffmpeg"
}
```

**Output schema:**
```json
{
    "status": "ok",
    "mp4_path": "results/run_id/final_video.mp4",
    "render_spec_path": "results/run_id/render_spec.json",
    "duration_s": 47.2
}
```

On failure: `"status": "failed"`, `"error": "..."`.

---

### Tool 6: `validate_output`

**Purpose:** Run `ffprobe` on the final MP4 and emit `evaluation.json`. Wraps the existing validation logic in `main.py:validate_final_video()`.

**Input schema:**
```json
{
    "mp4_path": "string",
    "audio_timeline": { "...": "AudioTimeline dict" },
    "run_dir": "string"
}
```

**Output schema:**
```json
{
    "mp4_exists": true,
    "has_audio_stream": true,
    "video_duration_s": 47.2,
    "audio_duration_s": 46.9,
    "duration_parity_s": 0.3,
    "duration_parity_ok": true,
    "evaluation_path": "results/run_id/evaluation.json",
    "passed": true,
    "failures": []
}
```

`duration_parity_ok` is `true` if `|video_duration - audio_duration| <= 0.25s` (the quality gate from CLAUDE.md).

The existing `validate_final_video()` function in `main.py` should be extracted to `src/utils/ffprobe_utils.py` so both main.py and the MCP tool share it.

---

## Server Wiring

**File:** `src/mcp/producer_server.py`

```python
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent
import mcp.server.stdio

app = Server("producer-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="check_asset_availability",
            description="Probe Pexels for a visual description. Returns relevance score. No image download.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "n_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="estimate_tts_duration",
            description="Estimate TTS duration for a voice line. Heuristic — no API call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "voice_preset": {"type": "string", "enum": ["calm", "narrator", "energetic", "authoritative"]},
                },
                "required": ["text"],
            },
        ),
        Tool(name="generate_audio", description="Run TTS for one or more scenes.", inputSchema={...}),
        Tool(name="fetch_assets", description="Retrieve and download images for one or more scenes.", inputSchema={...}),
        Tool(name="render_video", description="Compositor + FFmpeg render.", inputSchema={...}),
        Tool(name="validate_output", description="ffprobe validation and evaluation.json emission.", inputSchema={...}),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ...

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="producer-server",
                server_version="0.1.0",
                capabilities=app.get_capabilities(notification_options=None, experimental_capabilities={}),
            ),
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

Run as: `venv/Scripts/python.exe -m src.mcp.producer_server`

---

## Orchestrator as MCP Client (Phase 3 upgrade)

**File:** `src/orchestrator.py` (upgraded from Phase 2 sequential version)

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run_pipeline(screenplay: dict, run_dir: Path):
    server_params = StdioServerParameters(
        command="venv/Scripts/python.exe",
        args=["-m", "src.mcp.producer_server"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Parallel audio + image fetch
            audio_task = session.call_tool("generate_audio", {
                "screenplay": screenplay, "run_dir": str(run_dir),
            })
            image_task = session.call_tool("fetch_assets", {
                "script_package": screenplay_to_script_package(screenplay),
                "run_dir": str(run_dir),
            })
            audio_result, image_result = await asyncio.gather(audio_task, image_task)

            # ... revision loop, then:
            render_result = await session.call_tool("render_video", {...})
            validation = await session.call_tool("validate_output", {...})
```

**Transport:** `stdio` for local dev. Switch to `sse` for multi-machine without changing tool interfaces.

---

## Shared Utilities to Extract (Refactoring Prerequisites)

These extractions are required before the MCP server can call shared logic without circular imports:

| Current location | Extract to | Used by |
|-----------------|------------|---------|
| `ScriptImageAgent._score_result()` | `src/tools/image_search_tools.py` | `ScriptImageAgent`, `producer_server.check_asset_availability` |
| `ScreenplayReviewer._estimated_speech_seconds()` | `src/utils/tts_utils.py` | `ScreenplayReviewer`, `producer_server.estimate_tts_duration` |
| `main.py:validate_final_video()` | `src/utils/ffprobe_utils.py` | `main.py`, `producer_server.validate_output` |

Each extraction is a move, not a rewrite. Existing callers import from the new location.

---

## Directory Structure After Phase 3

```
src/
  mcp/
    __init__.py
    producer_server.py          (new)
    screenwriting_server.py     (new — see mcp-implementation-plan.md §3.1)
  screenwriting/
    concept_agent.py            (Phase 1, done)
    screenplay_agent.py         (Phase 1, done)
    screenplay_reviewer.py      (Phase 1, done)
    format_library/             (Phase 1, done)
  utils/
    __init__.py
    json_utils.py               (existing)
    tts_utils.py                (new — estimate_tts_duration shared logic)
    ffprobe_utils.py            (new — validate_final_video extracted from main.py)
  tools/
    image_search_tools.py       (existing + _score_result extracted to module level)
    tts_tools.py                (existing, unchanged)
  orchestrator.py               (Phase 2: sequential; Phase 3: MCP client)
  audio_agent.py                (+ scene_ids filter, + ProductionReport emission)
  script_image_agent.py         (+ scene_ids filter, + ProductionReport emission)
  artifacts/
    screenplay.py               (Phase 1, done)
    io.py                       (existing)
```

---

## Sequenced Work Items

### Phase 2 (plain Python, no MCP infrastructure)

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| P2-0 | ProductionReport emission from ScriptImageAgent + AudioAgent | `src/script_image_agent.py`, `src/audio_agent.py` | 2h |
| P2-1 | `scene_ids` filter param on both agents | same files | 1h |
| P2-2 | `src/orchestrator.py` — scene_results ledger + sequential revision loop | `src/orchestrator.py` | 4h |
| P2-3 | Wire orchestrator into `main.py screenplay` command | `main.py` | 1h |
| P2-4 | Parallel audio + image fetch (asyncio) | `src/orchestrator.py` | 2h |
| P2-5 | Tests: ProductionReport schema, orchestrator revision loop | `tests/` | 2h |

**Total Phase 2:** ~12h

**Exit criterion:** `python main.py screenplay ...` runs the orchestrator; degraded scenes trigger targeted revision; audio and image fetch run concurrently; `production_report.json` and `scene_results.json` written to run dir.

---

### Phase 3 (MCP server)

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| P3-0 | Extract shared utilities (relevance scorer, TTS duration, ffprobe) | `src/tools/`, `src/utils/` | 1h |
| P3-1 | `pip install mcp`, add to `requirements.txt` | `requirements.txt` | 0.25h |
| P3-2 | `producer_server.py`: server skeleton + `list_tools()` | `src/mcp/producer_server.py` | 1h |
| P3-3 | `check_asset_availability` tool | same | 1h |
| P3-4 | `estimate_tts_duration` tool | same | 0.5h |
| P3-5 | `generate_audio` tool (wraps AudioAgent) | same | 2h |
| P3-6 | `fetch_assets` tool (wraps ScriptImageAgent) | same | 2h |
| P3-7 | `render_video` tool (wraps CompositorAgent + RenderAgent) | same | 2h |
| P3-8 | `validate_output` tool (wraps ffprobe_utils) | same | 1h |
| P3-9 | `screenwriting_server.py` (see mcp-implementation-plan.md §3.1) | `src/mcp/screenwriting_server.py` | 3h |
| P3-10 | Orchestrator upgraded to MCP client (stdio transport) | `src/orchestrator.py` | 3h |
| P3-11 | Integration tests over MCP transport | `tests/integration/` | 3h |

**Total Phase 3:** ~20h

**Exit criterion:** `python -m src.mcp.producer_server` starts cleanly; orchestrator calls `check_asset_availability` and `estimate_tts_duration` during screenplay review; full pipeline runs end-to-end through the MCP client; integration tests pass offline using fixture data.

---

## What This Is NOT

- Not a rewrite of any existing agent. All agent logic stays in `src/`.
- Not a blocking dependency on Phase 3. Phase 2 delivers the revision loop; MCP is additive.
- Not a change to the `mvp` command. All existing commands run unchanged throughout.
- Not a cloud deployment. `stdio` transport runs producer-server as a local subprocess.
