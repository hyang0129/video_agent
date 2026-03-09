# MCP Implementation Plan

**Date:** March 2026
**Prerequisite reading:** [mcp-architecture-upgrade.md](mcp-architecture-upgrade.md)
**Goal:** Concrete, sequenced steps to migrate toward the MCP architecture — no hand-waving, no "TBD".

---

## Reality Check: What We're Actually Doing

The design doc describes the end state. This doc describes how to get there from the current codebase without breaking the existing pipeline.

The existing pipeline is:

```
main.py
  → MarketResearchAgent (src/agent.py)         → TopicBrief JSON
  → ScriptGenerationAgent (src/script_agent.py) → ScriptPackage JSON
  → script_package_to_video_plan (src/video_planner.py) → VideoPlan JSON
  → AudioGenerationAgent (src/audio_agent.py)   → AudioTimeline JSON + MP3s
  → ScriptImageAgent (src/script_image_agent.py) → VisualManifest JSON
  → CompositionAgent (src/composition_agent.py)  → RenderSpec JSON
  → RenderAgent (src/render_agent.py)            → final_video.mp4
```

All of these are Python class instantiations called in sequence in `main.py`. There is no MCP server, no message passing, no parallelism.

**The migration strategy is additive.** We add new agents alongside existing ones. The existing `mvp` command in `main.py` stays intact. New commands tap new agents. We do not refactor the working pipeline until the new agents are proven.

---

## Phase 1: Screenwriting Split + Multi-Format (No MCP Infrastructure)

**Goal:** Run `python main.py screenplay "history of feta cheese" --format storytime` and get a reviewed Screenplay artifact.

**What Phase 1 does NOT include:** MCP servers, parallel execution, production feedback loop.

### 1.1 New artifact types

**File:** `src/artifacts/screenplay.py`

Three new typed dicts. We use plain dicts (not Pydantic) to match existing code style.

```python
# Concept: one framing of a topic
{
    "schema_version": "1.0.0",
    "concept_id": "c_<hex>",
    "topic_brief_ref": "tb_...",
    "format": "storytime",          # facts | storytime | tutorial | debate | listicle
    "hook": "...",                  # <= 15 words, opens the video
    "angle": "...",                 # one sentence: what's the specific lens
    "hook_strength_estimate": 0.0,  # 0.0-1.0, heuristic from ConceptAgent
    "feasibility_score": None,      # filled in by ScreenplayReviewer
}

# Screenplay: full scene-by-scene script with visual intent
{
    "schema_version": "1.0.0",
    "screenplay_id": "sp_<hex>",
    "concept_ref": "c_<hex>",
    "format": "storytime",
    "target_duration_s": 45,
    "narrator_character": {
        "type": "voice_only",       # voice_only | vtuber
        "voice_preset": "calm",     # narrator | energetic | calm | authoritative
    },
    "music_tone": "tense, cinematic",
    "scenes": [
        {
            "scene_id": "scene_01",
            "vo_line": "...",
            "target_duration_s": 6.0,
            "visual": {
                "description": "...",   # specific: what the camera sees
                "mood": "ominous",      # guides music + color grade
                "search_queries": ["dark calm ocean at night 1912"],  # Pexels queries
            },
            "on_screen_text": "...",
            "music_energy": "low",      # low | medium | high
        }
    ],
    "feasibility_report": None,     # filled in by ScreenplayReviewer
}

# FeasibilityReport: heuristic pre-flight check results
{
    "screenplay_ref": "sp_<hex>",
    "overall_score": 0.0,           # 0.0-1.0
    "scene_issues": [
        {
            "scene_id": "scene_01",
            "issue": "vo_too_long",  # vo_too_long | visual_too_generic | timing_mismatch
            "detail": "...",
            "suggestion": "...",
            "severity": "warn",      # warn | error
        }
    ],
    "recommended_action": "approve", # approve | revise_scenes | reject
}
```

**Note:** `ProductionReport` is not a new artifact file — it is emitted by `ScriptImageAgent` when an asset fetch degrades. See §1.5.

---

### 1.2 Format templates

**Directory:** `src/screenwriting/format_library/`

Each template is a JSON file that tells the ScreenplayAgent:
- What sections/beats the format requires
- What tone and pacing characteristics to use
- What visual patterns work well for this format

**`facts.json`:**
```json
{
    "format": "facts",
    "beat_structure": ["hook", "fact_1", "fact_2", "fact_3", "fact_4", "fact_5", "cta"],
    "hook_pattern": "Did you know [surprising claim]?",
    "pacing": "fast",
    "visual_guidance": "Each fact beat: concrete subject matter image, not abstract. Avoid 'people talking'.",
    "music_tone": "energetic, upbeat",
    "cta_pattern": "Which fact surprised you most? Follow for more [topic].",
    "target_duration_s": 45,
    "min_beats": 5,
    "max_beats": 9
}
```

**`storytime.json`:**
```json
{
    "format": "storytime",
    "beat_structure": ["hook", "setup", "rising_action", "turning_point", "resolution", "reflection", "cta"],
    "hook_pattern": "Most people think [X]. They're wrong.",
    "pacing": "medium",
    "visual_guidance": "Follow the narrative arc. Hook: tension image. Setup: context. Resolution: outcome.",
    "music_tone": "tense then resolved, cinematic",
    "cta_pattern": "Would you have done the same? Follow to find out more.",
    "target_duration_s": 55,
    "min_beats": 5,
    "max_beats": 8
}
```

**`tutorial.json`** and **`debate.json`** can be stubs initially (just the JSON structure, minimal content). Add full content when those formats are actually used.

---

### 1.3 ConceptAgent

**File:** `src/screenwriting/concept_agent.py`

**Responsibility:** Given a `TopicBrief`, produce N `Concept` dicts with distinct hooks, angles, and format tags.

**Key design decisions:**
- Takes `n_concepts` param (default 3). Each concept gets a different format from the library.
- Uses a single LLM call with a structured prompt requesting N variants.
- Hook strength is estimated heuristically (word count, question mark, number presence) — no extra LLM call.
- Saves each concept as `concept_<i>.json` under the run dir.

**Prompt skeleton:**
```
You are a short-form video concept writer. Given a TopicBrief, generate {n} distinct concepts.
Each concept must have a different hook style and emotional angle.
Available formats: {formats}.
For each concept output: format, hook (<= 15 words), angle (1 sentence).
Return a JSON array of concept objects.
```

**Class interface:**
```python
class ConceptAgent:
    def generate_concepts(
        self,
        topic_brief: dict,
        n_concepts: int = 3,
        formats: list[str] | None = None,
    ) -> list[dict]:
        """Returns list of Concept dicts, ordered by hook_strength_estimate descending."""
```

**Hook strength heuristic** (no LLM needed):
```python
def _estimate_hook_strength(hook: str) -> float:
    score = 0.5
    if hook.strip().endswith("?"):
        score += 0.15   # question hooks engage
    if any(c.isdigit() for c in hook):
        score += 0.1    # numbers are specific
    words = hook.split()
    if 6 <= len(words) <= 12:
        score += 0.1    # sweet spot length
    if any(w.lower() in ("never", "always", "secret", "wrong", "real", "truth") for w in words):
        score += 0.15   # high-valence words
    return min(1.0, score)
```

---

### 1.4 ScreenplayAgent

**File:** `src/screenwriting/screenplay_agent.py`

**Responsibility:** Given a `Concept` + format template JSON, produce a full `Screenplay`.

**Key design decisions:**
- Loads the format template from `format_library/<format>.json` to include in prompt.
- Generates `search_queries` for each scene's visual as part of the LLM output (not post-processed). The LLM writes Pexels-friendly queries because it knows the topic.
- The `Screenplay.scenes` list maps 1:1 to beats. It is more expressive than `ScriptPackage.script.beats` because it carries explicit `visual.description` and `visual.search_queries`.
- For backwards compatibility: after generating a Screenplay, calling `screenplay_to_script_package()` converts it to the existing `ScriptPackage` format so it can enter the current production pipeline unchanged.

**Class interface:**
```python
class ScreenplayAgent:
    def write_screenplay(
        self,
        concept: dict,
        topic_brief: dict,
        format_template: dict | None = None,
    ) -> dict:
        """Returns a Screenplay dict."""
```

**`screenplay_to_script_package(screenplay: dict) -> dict`** (module-level function):

This is the bridge to the existing pipeline. It maps `Screenplay.scenes` → `ScriptPackage.script.beats`, carries over the hook from the concept, and populates `asset_prompts` from `scene.visual.search_queries`. This function lives in `src/screenwriting/screenplay_agent.py` and lets the existing audio/image/render agents run unchanged.

---

### 1.5 ScreenplayReviewer (intent validator — no production API calls)

**File:** `src/screenwriting/screenplay_reviewer.py`

**Responsibility:** Check that a `Screenplay` is internally consistent and plausible — not whether production will succeed. Production handles its own failures and reports them back.

**Design principle:** The screenplay declares *intent*. The reviewer validates that the intent is coherent. It does NOT call Pexels, ElevenLabs, or any external API. If an image search fails in production, that's production's job to report and request a revision.

**Checks (all heuristic, no API calls):**
1. **VO timing fit** — word count / 150 WPM estimate. Flag if estimated > `scene.target_duration_s * 1.15`. This catches obvious 3x overruns early without any API call.
2. **Visual specificity** — flag `visual.description` containing obviously generic phrases: `"people talking"`, `"person thinking"`, `"group of people"`, `"background"` alone. These are reliable Pexels failure predictors and are detectable with a keyword check.
3. **Total duration** — sum of scene `target_duration_s` vs screenplay `target_duration_s`. Flag if > 15% off.
4. **Empty fields** — any scene missing `vo_line`, `visual.description`, or `on_screen_text`.

**What it does NOT check:**
- Whether images actually exist on Pexels (production's job)
- Whether TTS will succeed (production's job)
- Whether the content is engaging (human's judgment)

**Output:** `FeasibilityReport` dict. `recommended_action` is:
- `"approve"` — no errors, fewer than 2 warnings
- `"revise_scenes"` — errors or 2+ warnings (orchestrator re-runs ScreenplayAgent targeted at flagged scenes before proceeding to production)
- `"reject"` — more than half the scenes have errors (start over with a new concept)

**Class interface:**
```python
class ScreenplayReviewer:
    def review(self, screenplay: dict) -> dict:
        """Returns a FeasibilityReport dict. No external API calls."""
```

In Phase 1, a `"revise_scenes"` result causes `main.py` to call `ScreenplayAgent.revise_scene()` before proceeding. In Phase 2, the orchestrator handles this loop automatically.

---

### 1.6 ProductionReport from production agents

Production agents emit a `ProductionReport` when they encounter an issue that could be fixed by revising the screenplay. This is the **only feedback channel** from production back to screenwriting.

**Files to modify:** `src/script_image_agent.py`, `src/audio_agent.py`

#### ScriptImageAgent — image degradation

Currently, failed/low-relevance Pexels results silently fall back to a BMP placeholder. Change: accumulate issues and write `production_report.json` at end of run.

```python
# When falling back to placeholder (no relevant image found):
production_issues.append({
    "agent": "ScriptImageAgent",
    "scene_id": scene_id,
    "status": "degraded",
    "issue": "no_relevant_image",
    "detail": f"Best result relevance {score:.2f}, threshold {RELEVANCE_THRESHOLD:.2f}",
    "suggestion": "Rephrase visual.description to be more concrete and specific",
    "revision_field": "visual",   # only visual needs rewriting — vo_line unchanged
    "revision_possible": True,
})
```

#### AudioAgent — TTS failure or duration overshoot

```python
# On TTS API failure:
production_issues.append({
    "agent": "AudioAgent",
    "scene_id": scene_id,
    "status": "degraded",
    "issue": "tts_failed",
    "detail": str(e),
    "suggestion": "Simplify vo_line: remove special characters, shorten to under 20 words",
    "revision_field": "vo_line",  # only vo_line needs rewriting
    "revision_possible": True,
})

# On duration overshoot (actual_duration > target * 1.2):
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

#### ProductionReport schema

Both agents append to a shared list and write one file at end of run:

```python
write_json(run_dir / "production_report.json", {
    "schema_version": "1.0.0",
    "run_id": run_id,
    "issues": production_issues,
    "degraded_scene_count": len([i for i in production_issues if i["status"] == "degraded"]),
})
```

The `revision_field` key is new and important: it tells the orchestrator whether to revise `visual` (free, no re-TTS) or `vo_line` (requires re-TTS). This avoids unnecessary ElevenLabs API calls when only the image failed.

These changes are additive to both agent files. Existing logic is untouched.

---

### 1.7 New `screenplay` command in main.py

Add alongside the existing `mvp` command:

```
python main.py screenplay <topic_brief.json> [--format facts|storytime] [--n-concepts 3] [--auto-select]
```

**Flow:**
1. Load TopicBrief from file
2. `ConceptAgent.generate_concepts(topic_brief, n_concepts)` → list of Concept dicts
3. For each concept: `ScreenplayAgent.write_screenplay(concept, topic_brief)` → Screenplay dict
4. For each screenplay: `ScreenplayReviewer.review(screenplay)` → FeasibilityReport
5. Print a summary table: concept hook | format | feasibility score | recommended action
6. If `--auto-select`: pick the highest-scoring approved screenplay
7. If not `--auto-select`: prompt user to pick one (or press Enter to accept auto-pick)
8. Convert selected screenplay → ScriptPackage via `screenplay_to_script_package()`
9. Continue existing production pipeline from `script_package_to_video_plan()` onward

This reuses all existing production agents (audio, image, compositor, render) unchanged.

---

### 1.8 Directory structure after Phase 1

```
src/
  screenwriting/
    __init__.py
    concept_agent.py
    screenplay_agent.py
    screenplay_reviewer.py
    format_library/
      facts.json
      storytime.json
      tutorial.json       (stub)
      debate.json         (stub)
  artifacts/
    io.py                 (existing)
    screenplay.py         (new - schema constants + helper functions)
  agent.py                (unchanged)
  script_agent.py         (unchanged)
  video_planner.py        (unchanged)
  audio_agent.py          (unchanged)
  script_image_agent.py   (minor: add ProductionReport emission)
  composition_agent.py    (unchanged)
  render_agent.py         (unchanged)
```

`main.py` gets one new command block. All existing commands are untouched.

---

## Phase 2: Feedback Loop + Parallel Execution (Still No MCP Servers)

**Goal:** Production reports from Phase 1 feed back automatically to targeted screenplay revision. Audio + image fetch run in parallel. Three screenplay variants are scored and ranked before production starts.

**What Phase 2 does NOT include:** Standalone MCP server processes (those are Phase 3). Human gates on automatic revisions.

### 2.1 Orchestrator with scene_results ledger

**File:** `src/orchestrator.py`

The orchestrator owns a `scene_results` dict — the central state object across all revision rounds. It is the only place that merges results from multiple production rounds before handing off to the Compositor.

```python
# scene_results: scene_id -> production result for that scene
scene_results: dict[str, dict] = {}
# {
#   "scene_01": {"audio_path": "...", "image_paths": [...], "status": "ok"},
#   "scene_03": {"audio_path": None, "image_paths": [], "status": "degraded", "issue": "..."},
# }
```

The Compositor is called once at the end, with the fully merged manifest assembled from `scene_results`. It never knows that some scenes came from round 0 and others from round 1.

### 2.2 Automatic revision loop

No human gate. Runs entirely automatically. The `revision_field` key in each issue determines what gets re-produced:

```
revision_field == "visual"  → revise visual.description + visual.search_queries only
                               → re-run image fetch for that scene
                               → vo_line unchanged, no re-TTS

revision_field == "vo_line" → revise vo_line only
                               → re-run TTS for that scene
                               → visual unchanged, no new image fetch

revision_field == "both"    → revise both fields
                               → re-run both TTS and image fetch
```

**Orchestrator loop:**

```python
MAX_REVISION_ROUNDS = 2   # config: MAX_REVISION_ROUNDS

scene_results = {}

# Round 0: full production (all scenes)
audio_results, image_results = await produce_scenes_parallel(screenplay, screenplay.scenes)
for scene in screenplay.scenes:
    scene_results[scene["scene_id"]] = merge(audio_results, image_results, scene["scene_id"])

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
        del scene_results[scene_id]  # invalidate stale result

    # Re-produce only revised scenes
    revised_scenes = [s for s in screenplay.scenes if s["scene_id"] in degraded]
    re_audio, re_images = await produce_scenes_parallel(
        screenplay, revised_scenes,
        skip_audio={sid for sid, r in degraded.items() if r["revision_field"] == "visual"},
        skip_images={sid for sid, r in degraded.items() if r["revision_field"] == "vo_line"},
    )
    for scene in revised_scenes:
        scene_results[scene["scene_id"]] = merge(re_audio, re_images, scene["scene_id"])

# All scene_results are now populated. Compose.
full_manifest = assemble_manifest(screenplay, scene_results)
compositor.compose(full_manifest)
```

**New method on ScreenplayAgent:**

```python
def revise_scene(
    self,
    screenplay: dict,
    scene_id: str,
    issue: str,
    suggestion: str,
    revision_field: str,   # "visual" | "vo_line" | "both"
) -> dict:
    """
    Rewrites only the specified field(s) for scene_id.
    Returns updated Screenplay dict (all other scenes unchanged).
    One LLM call. Narrow prompt — do not rewrite other scenes.
    """
```

The prompt for `revision_field == "visual"`:
> "Rewrite only the visual.description and visual.search_queries for scene_03. The issue is: [issue]. Suggestion: [suggestion]. Do not change vo_line or any other scene."

The prompt for `revision_field == "vo_line"`:
> "Rewrite only the vo_line for scene_03. The issue is: [issue]. Suggestion: [suggestion]. Keep the same meaning, shorten to fit [target_duration_s]s. Do not change visual or any other scene."

### 2.3 Parallel audio + asset fetch per scene

Using `asyncio` + `ThreadPoolExecutor` (agents are not async-native):

```python
async def produce_scenes_parallel(
    screenplay: dict,
    scenes: list[dict],
    skip_audio: set[str] | None = None,
    skip_images: set[str] | None = None,
) -> tuple[dict, dict]:
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        audio_future = loop.run_in_executor(
            pool, audio_agent.generate_for_scenes, screenplay, scenes, skip_audio
        )
        image_future = loop.run_in_executor(
            pool, image_agent.fetch_for_scenes, screenplay, scenes, skip_images
        )
        audio_results, image_results = await asyncio.gather(audio_future, image_future)
    return audio_results, image_results
```

Audio and image agents each need a `scene_ids` parameter (list of scene dicts to process). Existing agents process all scenes when `scene_ids=None`. This is the minimal change needed for partial re-runs.

### 2.4 Multi-variant screenplay generation (parallel)

Three concepts → three screenplays written in parallel → all reviewed → top-ranked wins. Fully automatic; no human gate during the writing phase.

```python
async def generate_and_rank_screenplays(topic_brief: dict, n: int = 3) -> list[tuple]:
    concepts = concept_agent.generate_concepts(topic_brief, n_concepts=n)

    with ThreadPoolExecutor() as pool:
        # Write all screenplays in parallel
        sp_futures = [
            loop.run_in_executor(pool, screenplay_agent.write_screenplay, c, topic_brief)
            for c in concepts
        ]
        screenplays = await asyncio.gather(*sp_futures)

        # Review all in parallel (no API calls — pure heuristic)
        review_futures = [
            loop.run_in_executor(pool, reviewer.review, sp)
            for sp in screenplays
        ]
        reports = await asyncio.gather(*review_futures)

    # Rank: approved first, then by feasibility score
    ranked = sorted(
        zip(screenplays, reports),
        key=lambda pair: (
            pair[1]["recommended_action"] == "approve",
            pair[1]["overall_score"],
        ),
        reverse=True,
    )
    return ranked  # [(screenplay, feasibility_report), ...]
```

Sequential wall-clock: `concept_gen + (N * screenplay_gen) + (N * review)`
Parallel wall-clock: `concept_gen + max(screenplay_gen) + max(review)`
Expected speedup for N=3: ~2.5-3x on the screenwriting phase.

---

## Phase 3: MCP Server Deployment

**Goal:** `screenwriting-server` and `production-server` run as standalone MCP server processes. The orchestrator uses the MCP client protocol to discover and call tools.

**Technology:** The `mcp` Python library (`pip install mcp`).

### 3.1 MCP server for screenwriting

**File:** `src/mcp/screenwriting_server.py`

```python
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

app = Server("screenwriting-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="generate_concepts", description="...", inputSchema={...}),
        Tool(name="write_screenplay", description="...", inputSchema={...}),
        Tool(name="review_feasibility", description="...", inputSchema={...}),
        Tool(name="revise_scene", description="...", inputSchema={...}),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "generate_concepts":
        result = concept_agent.generate_concepts(**arguments)
        return [TextContent(type="text", text=json.dumps(result))]
    # ... etc
```

Run as: `python -m src.mcp.screenwriting_server`

### 3.2 MCP server for production

**File:** `src/mcp/production_server.py`

Same pattern, exposes:
- `check_asset_availability`
- `estimate_tts_duration`
- `generate_audio` (wraps AudioAgent)
- `fetch_assets` (wraps ScriptImageAgent)
- `render_video` (wraps CompositorAgent + RenderAgent)
- `validate_output` (wraps QualityAgent/ffprobe check)

### 3.3 Orchestrator as MCP client

**File:** `src/orchestrator.py` (upgraded from Phase 2)

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run_pipeline(topic_brief: dict, config: OrchestratorConfig):
    async with stdio_client(StdioServerParameters(
        command="python", args=["-m", "src.mcp.screenwriting_server"]
    )) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Generate and rank screenplays
            concepts_result = await session.call_tool("generate_concepts", {
                "topic_brief": topic_brief, "n_concepts": 3
            })
            # ... etc
```

### 3.4 Transport choice

| Scenario | Transport |
|----------|-----------|
| Local single-machine dev | `stdio` (default, simplest) |
| Multiple machines / cloud | `sse` (HTTP Server-Sent Events) |
| Same-process embedding | Direct Python import (skip MCP overhead) |

Start with `stdio`. The tool interface is identical regardless of transport, so switching later requires only config changes.

---

## Sequenced Work Items

### Now (Phase 1 — no infra changes)

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| P1-1 | `Concept`, `Screenplay`, `FeasibilityReport` schemas | `src/artifacts/screenplay.py` | 1h |
| P1-2 | Format templates: `facts.json`, `storytime.json` | `src/screenwriting/format_library/` | 1h |
| P1-3 | `ConceptAgent` + hook strength heuristic | `src/screenwriting/concept_agent.py` | 3h |
| P1-4 | `ScreenplayAgent` + `screenplay_to_script_package()` bridge + `revise_scene()` | `src/screenwriting/screenplay_agent.py` | 5h |
| P1-5 | `ScreenplayReviewer` (intent validator — no API calls) | `src/screenwriting/screenplay_reviewer.py` | 2h |
| P1-6 | `ProductionReport` emission in `ScriptImageAgent` + `AudioAgent` | `src/script_image_agent.py`, `src/audio_agent.py` | 2h |
| P1-7 | `screenplay` CLI command in `main.py` (sequential, single variant) | `main.py` | 2h |
| P1-8 | Tests for ConceptAgent, ScreenplayReviewer, ProductionReport schema | `tests/` | 2h |

**Total Phase 1:** ~18h

**Exit criterion:** `python main.py screenplay tests/fixtures/topicbrief_ww2_tanks.json --format storytime` produces a Screenplay, runs production, reads any `production_report.json` issues, revises affected scenes automatically, and continues through to `final_video.mp4`. Production issues are logged with revision round count.

### Next (Phase 2 — orchestrator + asyncio)

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| P2-1 | `src/orchestrator.py`: scene_results ledger + revision loop | `src/orchestrator.py` | 5h |
| P2-2 | Parallel audio + image fetch via ThreadPoolExecutor | `src/orchestrator.py` | 2h |
| P2-3 | `scene_ids` filter param on AudioAgent + ScriptImageAgent | `src/audio_agent.py`, `src/script_image_agent.py` | 2h |
| P2-4 | Multi-variant parallel screenplay generation + ranking | `src/orchestrator.py` | 3h |
| P2-5 | Sequential vs parallel benchmark + docs | `results/benchmarks/` | 2h |

**Total Phase 2:** ~14h

**Exit criterion:** Three screenplay variants generated/reviewed in parallel; top-ranked enters production; audio and image fetch run concurrently; revision loop runs automatically on degraded scenes with correct `revision_field` targeting; benchmark JSON documents wall-clock speedup.

### Later (Phase 3 — MCP servers)

| # | Item | Effort |
|---|------|--------|
| P3-1 | `mcp` library + `screenwriting_server.py` | 4h |
| P3-2 | `production_server.py` | 4h |
| P3-3 | Orchestrator as MCP client (stdio transport) | 3h |
| P3-4 | Integration tests over MCP transport | 3h |

**Total Phase 3:** ~14h

---

## Key Interfaces (Lock These Down Early)

These are the contracts that everything else depends on. Define them before writing agent logic.

### Screenplay scene (canonical form)

```python
SCENE_SCHEMA = {
    "scene_id": str,              # "scene_01"
    "vo_line": str,               # full narration text
    "target_duration_s": float,   # expected duration
    "visual": {
        "description": str,       # specific, concrete visual description
        "mood": str,              # "ominous" | "energetic" | "calm" etc
        "search_queries": list,   # 1-3 Pexels search queries, ordered by preference
    },
    "on_screen_text": str,        # caption text displayed on screen
    "music_energy": str,          # "low" | "medium" | "high"
}
```

### screenplay_to_script_package (bridge contract)

```python
def screenplay_to_script_package(screenplay: dict) -> dict:
    """
    Converts Screenplay → ScriptPackage for existing production pipeline.

    Mapping:
    - screenplay.scenes[i].vo_line        → script.beats[i].vo_line
    - screenplay.scenes[i].on_screen_text → script.beats[i].on_screen_text
    - screenplay.scenes[i].target_duration_s → used to compute t_start_s/t_end_s
    - screenplay.scenes[i].visual.search_queries → asset_prompts
    - screenplay.narrator_character.voice_preset → audio.tts.voice

    The returned ScriptPackage is valid input for video_planner.script_package_to_video_plan().
    """
```

### ProductionReport (canonical form)

```python
PRODUCTION_REPORT_SCHEMA = {
    "schema_version": "1.0.0",
    "run_id": str,
    "issues": [
        {
            "agent": str,                    # "AudioAgent" | "ScriptImageAgent"
            "scene_id": str,
            "status": "degraded" | "failed" | "ok",
            "issue": str,                    # "no_relevant_image" | "tts_failed" | "vo_too_long"
            "detail": str,                   # human-readable explanation
            "suggestion": str,               # what to change in the screenplay
            "revision_field": str,           # "visual" | "vo_line" | "both" — drives partial re-run
            "revision_possible": bool,
        }
    ],
    "degraded_scene_count": int,
}
```

`revision_field` is the key that determines what the orchestrator re-produces after a screenplay revision:
- `"visual"` — only image fetch re-runs for that scene; TTS is reused
- `"vo_line"` — only TTS re-runs for that scene; images are reused
- `"both"` — both re-run (e.g. VO change cascades to timing change which invalidates image timing)
```

---

## What This Is NOT

- Not a rewrite of the existing pipeline. All existing agents stay in place.
- Not a microservices architecture today. Phase 1 and 2 are plain Python.
- Not dependent on a running MCP server until Phase 3.
- Not blocking Tier 0 recruiter work. Phase 1 can run in parallel with Tier 0.1-0.3.

The existing `mvp` command continues to work throughout all phases.
