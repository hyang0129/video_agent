# MCP Architecture Upgrade — Vibe Insta

**Status:** Design Proposal
**Date:** March 2026
**Purpose:** Evaluate how the Model Context Protocol (MCP) pattern can restructure the pipeline to support diverse content formats, bidirectional feedback, parallel execution, and multi-variant generation.

---

## Why MCP?

The current pipeline is a **linear artifact chain**: each agent runs sequentially, passes a JSON blob to the next, and has no ability to communicate back upstream. This creates two hard problems as the system grows:

1. **Production failures are discovered too late.** If the compositor can't find good images for a scene, the video is already committed to that script. There is no way to reroute.
2. **Content type is hardcoded.** The pipeline only knows how to write "facts about X" shorts. Supporting different formats — reaction videos, tutorials, listicles, debates, storytime — requires duplicating or forking the entire chain.

MCP (Model Context Protocol) solves both by exposing agents and tools as **discoverable, callable services** rather than hardcoded function imports. An orchestrator or any upstream agent can call downstream tools as needed, enabling:

- Feedback from production back to screenwriting
- Parallel execution of independent branches
- Multiple screenplay variants generated and evaluated simultaneously
- Plug-in content types without rewiring the whole pipeline

---

## Domain Split: Screenwriting vs. Producing

The pipeline maps cleanly onto two functional domains.

### Domain 1: Screenwriting

Agents in this domain answer: **"What should the video contain?"**

| Agent | Responsibility | Output |
|-------|---------------|--------|
| `MarketResearchAgent` | Identify trending topics, audience signals | `TopicBrief` |
| `ConceptAgent` | Generate N distinct video concepts for a topic | `ConceptSet` (array of `Concept`) |
| `ScreenplayAgent` | Expand a concept into a full screenplay | `Screenplay` |
| `ScreenplayReviewer` | Check screenplay for production feasibility (calls production MCP tools) | `FeasibilityReport` |

A **Screenplay** declares everything the video should contain:
- Narration lines with timing targets
- Desired background visuals per scene (description, mood, not a URL)
- On-screen text / caption style
- Narrating character (voice preset, optional VTuber model)
- Music tone and energy
- Content format tag (`facts`, `storytime`, `tutorial`, `reaction`, etc.)

The screenplay does **not** contain asset URLs or file paths — those are the producer's job.

### Domain 2: Producing

Agents in this domain answer: **"How do we make it real?"**

| Agent | Responsibility | Output |
|-------|---------------|--------|
| `AudioAgent` | TTS voiceover per scene | `AudioTimeline` + MP3 segments |
| `AssetAgent` | Image/video retrieval from Pexels, fallback to BMP | `AssetManifest` |
| `MusicAgent` | Background music selection and mixing | `MusicTrack` |
| `CompositorAgent` | Assemble visual + audio specs | `RenderSpec` |
| `RenderAgent` | FFmpeg render to final MP4 | `final_video.mp4` |
| `QualityAgent` | `ffprobe` validation, duration parity, LUFS check | `EvaluationReport` |

Producing agents **report structured failures** rather than silently degrading:

```json
{
  "agent": "AssetAgent",
  "scene_id": "scene_03",
  "status": "degraded",
  "issue": "no_relevant_image",
  "detail": "Top Pexels result CLIP score 0.21, threshold 0.55",
  "suggestion": "rephrase visual to 'ancient Roman aqueduct stone arch'"
}
```

These production reports feed back to the Screenplay Reviewer, which can trigger a targeted script revision without rerunning the whole pipeline.

---

## MCP Server Layout

Each domain exposes an MCP server. Agents within a domain call their own server's tools; cross-domain calls are also permitted (this is the key enabling mechanism for the feedback loop).

```
┌─────────────────────────────────────────────────────┐
│                 MCP Server Registry                 │
├───────────────────────┬─────────────────────────────┤
│  screenwriting-server │  production-server          │
│                       │                             │
│  Tools:               │  Tools:                     │
│  - research_topic     │  - check_asset_availability │
│  - generate_concepts  │  - estimate_tts_duration    │
│  - write_screenplay   │  - render_preview_frame     │
│  - review_feasibility │  - validate_output          │
│  - revise_scene       │  - get_production_report    │
└───────────────────────┴─────────────────────────────┘
```

### Why cross-domain tool calls matter

The `ScreenplayAgent` and `ScreenplayReviewer` can call `production-server` tools **without triggering a full production run**. For example:

- Call `check_asset_availability("World War I trench warfare soldiers")` before committing a visual description — if Pexels yields poor results, the writer can adjust the description now.
- Call `estimate_tts_duration("In 1943, the tide began to turn...", voice="narrator")` to verify scene line length fits the timing window.

This converts the feedback loop from a post-hoc fix into a **pre-flight check built into the writing process**.

---

## Orchestrator

A top-level `OrchestratorAgent` manages both domains. It does not implement logic itself — it calls MCP tools and routes artifacts.

```
OrchestratorAgent
  │
  ├── [Screenwriting Phase]
  │     ├── call screenwriting-server/research_topic
  │     ├── call screenwriting-server/generate_concepts  (parallel, N concepts)
  │     ├── for each concept → call screenwriting-server/write_screenplay  (parallel)
  │     └── for each screenplay → call screenwriting-server/review_feasibility
  │           └── [if feasibility issues] → call screenwriting-server/revise_scene (loop, max 2 rounds)
  │
  ├── [Human Selection Gate — optional]
  │     └── present ranked screenplays, await approval or auto-select top-scored
  │
  └── [Producing Phase]
        ├── call production-server/generate_audio  (parallel per scene)
        ├── call production-server/fetch_assets    (parallel per scene)
        ├── call production-server/select_music
        ├── [wait for all parallel tasks]
        ├── call production-server/compose
        ├── call production-server/render
        └── call production-server/validate_output
              └── [if validation fails] → emit failure report, optionally loop back
```

---

## Key Architectural Patterns

### 1. Parallel Screenplay Generation (Multi-Variant)

Rather than producing one script, the orchestrator can fan out:

```
TopicBrief
    │
    ├── ConceptAgent → Concept A (hook: "shocking statistic")
    ├── ConceptAgent → Concept B (hook: "historical question")
    └── ConceptAgent → Concept C (hook: "common misconception")
         │
         ↓ (all 3 in parallel)
    ScreenplayAgent × 3
         │
         ↓ (all 3 in parallel)
    FeasibilityReviewer × 3
         │
         ↓
    RankingAgent → selects highest-scoring screenplay
         │
         ↓
    Producing Phase (single winner)
```

A `RankingAgent` scores screenplays on:
- Feasibility score (from reviewer)
- Estimated engagement (hook strength, pacing)
- Production cost estimate (fewer rare assets = lower risk)

Alternatively, all 3 screenplays can enter production simultaneously and the human selects from 3 rendered videos.

### 2. Feedback Loop (Production-to-Screenwriting)

When a producer reports a degraded scene, the orchestrator invokes a targeted revision:

```
AssetAgent → { scene_03: "no_relevant_image", suggestion: "rephrase visual" }
    │
    ↓
OrchestratorAgent
    │
    └── call screenwriting-server/revise_scene(
            scene_id="scene_03",
            issue="no_relevant_image",
            suggestion="rephrase visual to 'ancient Roman aqueduct stone arch'",
            screenplay=<current_screenplay>
        )
        │
        └── Revised scene_03 → re-enter asset fetch only for scene_03
```

This is a **targeted re-run**, not a full pipeline restart. Only the affected scene is revised and re-produced.

### 3. Content Format as a First-Class Concept

The `ConceptAgent` receives a **format tag** alongside the topic. Each format maps to a different screenplay template:

| Format Tag | Description | Script Pattern |
|------------|-------------|----------------|
| `facts` | "5 facts about X" | Hook → facts 1-5 → CTA |
| `storytime` | Narrative arc | Setup → conflict → resolution |
| `tutorial` | How-to walkthrough | Problem → steps → result |
| `reaction` | Commentary over clips | Context → reaction beats |
| `debate` | Two-sided argument | Position A → Position B → verdict |
| `listicle` | Ranked list | Intro → items → #1 reveal |

The `ScreenplayAgent` selects the correct template from a `format_library/` directory and fills it using the topic and concept. Adding a new format requires only a new template file — no agent code changes.

### 4. VTuber / Narrating Character Support

The `Screenplay` artifact declares an optional `narrator_character`:

```json
{
  "narrator_character": {
    "type": "vtuber",
    "model_id": "hololive_korone_v2",
    "voice_preset": "energetic",
    "lip_sync": true
  }
}
```

The `CompositorAgent` reads this and routes to a VTuber render path instead of the standard image slideshow path. This is additive — the screenplay is the same; only the compositor behavior differs.

---

## Alternative Approaches Considered

### Alt A: Critic-in-the-Loop (Simpler, No MCP)

A single `CriticAgent` sits between Screenwriting and Producing. It reads the screenplay, runs heuristic checks (line length, visual description specificity, pacing), and returns a structured critique. The `ScreenplayAgent` revises and the critic re-checks (max 3 loops).

**Pros:** No MCP server overhead, simpler to implement now.
**Cons:** Critic uses heuristics, not real production data. A line can pass the critic but still fail at asset fetch.
**Verdict:** Good interim step. Implement as Tier 1, replace with real MCP feedback in Tier 2.

### Alt B: Async Message Queue (No MCP)

Agents communicate via a message queue (Redis Streams or in-process `asyncio.Queue`). Each agent publishes events; others subscribe.

**Pros:** True decoupling, agents don't need to know about each other.
**Cons:** Event ordering is complex, harder to debug, overkill for current scale.
**Verdict:** Valid at scale (100+ concurrent runs). Premature now.

### Alt C: Unified Orchestrator with Tool Calls (Claude API)

A single Claude model instance acts as orchestrator and calls all agents as tools directly via the Anthropic API tool-use interface. No separate MCP server process needed — tools are registered as JSON schemas in the model's context.

**Pros:** Lowest infrastructure overhead, Claude handles routing and retry logic in natural language. Already compatible with the Anthropic SDK used in this project.
**Cons:** Single model = single point of failure; context window limits how many parallel results it can reason over.
**Verdict:** Strong option for Tier 0/1 implementation. MCP server split remains the Tier 2 target.

### Alt D: Separate Microservices (Full MCP)

Each agent becomes a standalone MCP server running as its own process (or Docker container). The orchestrator discovers them via a service registry.

**Pros:** True horizontal scalability, independent deployment.
**Cons:** Significant DevOps overhead, not warranted until content volume justifies it.
**Verdict:** Tier 3+ consideration. Document the interface contracts now so migration is straightforward later.

---

## Recommended Implementation Sequence

### Tier 1 — Screenwriting/Producing Split (No MCP infrastructure yet)

1. Introduce `Screenplay` as a typed artifact sitting between `ScriptPackage` and `VideoPlan`.
2. Add `ConceptAgent` that proposes 3 concepts; human selects one (or auto-select highest hook score).
3. Add format tags to `Screenplay`; implement `facts` and `storytime` templates.
4. Add `CriticAgent` (heuristic) between screenplay and production.
5. Producers emit structured `ProductionReport` on failure; log but don't yet loop back.

**Deliverable:** The pipeline can produce two content formats; failures are logged with suggestions.

### Tier 2 — Real Feedback Loop + Parallel Execution

1. Implement `production-server` MCP tools (`check_asset_availability`, `estimate_tts_duration`).
2. `ScreenplayReviewer` calls these tools during write phase as pre-flight checks.
3. `OrchestratorAgent` handles targeted scene revision when `ProductionReport` flags degraded output.
4. Fan out 3 screenplay variants in parallel; auto-rank by feasibility score.
5. Audio and asset fetch parallelized per scene (already planned in ROADMAP 0.6).

**Deliverable:** Feedback loop closes; parallel screenplay variants; measurable wall-clock speedup.

### Tier 3 — Full MCP Server Deployment

1. `screenwriting-server` and `production-server` run as standalone MCP server processes.
2. Orchestrator uses standard MCP client to discover and call tools.
3. Add VTuber compositor path.
4. Add `debate` and `tutorial` format templates.

**Deliverable:** Plug-in content formats; VTuber support; production-grade agent isolation.

---

## Artifact Schema Changes

### New: `Concept`

```json
{
  "concept_id": "c_abc123",
  "topic_brief_ref": "tb_xyz",
  "format": "storytime",
  "hook": "Most people think the Titanic sank in minutes. It didn't.",
  "angle": "survivor perspective",
  "estimated_engagement": 0.82,
  "feasibility_score": null
}
```

### New: `Screenplay`

```json
{
  "schema_version": "1.0.0",
  "screenplay_id": "sp_abc123",
  "concept_ref": "c_abc123",
  "format": "storytime",
  "narrator_character": { "type": "voice_only", "voice_preset": "calm" },
  "target_duration_s": 45,
  "scenes": [
    {
      "scene_id": "scene_01",
      "vo_line": "April 14th, 1912. The ocean was perfectly still.",
      "target_duration_s": 6.0,
      "visual": { "description": "dark calm ocean at night, stars reflecting", "mood": "ominous" },
      "on_screen_text": "April 14, 1912",
      "music_energy": "low"
    }
  ],
  "music_tone": "tense, cinematic",
  "feasibility_report": null
}
```

### New: `FeasibilityReport`

```json
{
  "screenplay_ref": "sp_abc123",
  "overall_score": 0.78,
  "scene_issues": [
    {
      "scene_id": "scene_03",
      "issue": "visual_too_generic",
      "detail": "Description 'people talking' will yield low-relevance stock images",
      "suggestion": "Rephrase to 'passengers in formal 1912 evening attire on ocean liner deck'",
      "severity": "warn"
    }
  ],
  "timing_issues": [],
  "recommended_action": "revise_scenes"
}
```

### Updated: `ProductionReport` (replaces silent failure)

```json
{
  "run_id": "run_abc",
  "stage": "AssetAgent",
  "scene_id": "scene_03",
  "status": "degraded",
  "issue": "no_relevant_image",
  "detail": "Best Pexels result CLIP score 0.21 (threshold 0.55); using BMP placeholder",
  "suggestion": "rephrase visual to 'ancient Roman aqueduct stone arch'",
  "revision_possible": true
}
```

---

## File Layout (Target State)

```
src/
  screenwriting/
    concept_agent.py          # generates N concepts from TopicBrief
    screenplay_agent.py       # writes Screenplay from Concept
    screenplay_reviewer.py    # feasibility pre-flight (calls production MCP tools)
    format_library/
      facts.json              # scene template: hook + N facts + CTA
      storytime.json          # scene template: setup + conflict + resolution
      tutorial.json
      debate.json
  producing/
    audio_agent.py
    asset_agent.py            # renamed from script_image_agent
    music_agent.py
    compositor_agent.py
    render_agent.py
    quality_agent.py          # ffprobe validation, evaluation.json output
  mcp/
    screenwriting_server.py   # MCP server exposing screenwriting tools
    production_server.py      # MCP server exposing production tools
  orchestrator.py             # top-level coordinator
  artifacts/                  # Pydantic models for all artifact schemas
    concept.py
    screenplay.py
    feasibility_report.py
    production_report.py
```

---

## Open Questions

1. **Human selection gate:** Should the orchestrator always auto-select the top-ranked screenplay, or pause and present variants to the human? A config flag `AUTO_SELECT_SCREENPLAY=true/false` handles both.

2. **Revision loop depth:** How many rounds of screenplay revision before we accept degraded output and continue? Recommend max 2 targeted revisions per scene to avoid infinite loops.

3. **Parallel production cost:** Running 3 screenplays through TTS simultaneously triples ElevenLabs character usage. On the free tier (10k chars/month) this is a hard constraint. Feasibility scoring should rank-filter to 1 winner before production unless the user explicitly opts into multi-variant rendering.

4. **VTuber licensing:** VTuber model usage requires licensing from the respective IP holder. This should be gated behind a config flag and documented as requiring manual license verification before enabling.

5. **MCP server transport:** For local-only use, `stdio` transport is sufficient. For multi-machine or cloud use, switch to `SSE` (Server-Sent Events) transport. Design the server interface to be transport-agnostic from the start.
