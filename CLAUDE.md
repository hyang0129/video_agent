# CLAUDE.md — Video Agent Project

## Project Identity

**Vibe Insta** is an AI-powered, multi-agent content creation pipeline.

**Primary goal:** Demonstrate multi-agent system design for job search purposes.
A recruiter reviewing this repo should be able to understand the architecture and
run the pipeline end-to-end in under 10 minutes.

**Secondary goal:** Operate a YouTube Shorts channel accumulating 100k views.
Content is faceless, caption-first, voiceover-narrated shorts (15–60s, 9:16 vertical).

---

## Architecture

The system is a sequential artifact pipeline. Each agent consumes a typed JSON
artifact from the previous stage and emits one for the next:

```
MarketResearchAgent → TopicBrief
    → ScriptAgent → ScriptPackage
        → VideoPlanner → VideoPlan
            → AudioAgent → AudioTimeline + MP3 segments
                → ScriptImageAgent → VisualManifest
                    → CompositorAgent → RenderSpecification
                        → RenderAgent → final_video.mp4
```

**Design rules:**
- Each agent is independently invokable with its own input artifact.
- Agents communicate only through typed JSON artifacts — no shared mutable state.
- Artifact files are persisted under `results/<run_id>/`.
- ROADMAP.md is the canonical source of truth for priorities and sequencing.

---

## Current Execution Priority

Follow the tier system in ROADMAP.md. As of March 2026, **Tier 0 is active**:
recruiter appeal — public repo, architecture diagram, working demo output, audio
continuity, evaluation artifacts, metrics summary, parallel execution benchmark.

Do not start Tier 1+ work until Tier 0 success criteria are met.

---

## Coding Principles

### Do
- Keep each agent in its own file under `src/`.
- Emit `evaluation.json` on every pipeline run (alignment drift, duration, API cost).
- Validate post-render output with `ffprobe`: audio stream present, duration parity ≤0.25s.
- Write `pytest` tests for new agent logic; target 80%+ coverage.
- Use FFmpeg for rendering — local-first, zero cloud rendering cost.
- Choose the best LLM for each task at implementation time; no project-wide LLM preference.
- Use ElevenLabs TTS for voiceover; respect free-tier limits (10k chars/month).
- Use Pexels for image retrieval; placeholder BMPs when Pexels is unavailable.
- Follow the Human Review Protocol for every change that affects media output — see below.
- Follow the Integration Testing Guide when writing or running tests — see `docs/integration-testing.md`.

### Don't
- Don't use cloud rendering services (Shotstack, etc.) — avoids cost and vendor lock-in.
- Don't upgrade LangChain beyond `0.3.x` without a dedicated migration branch (already done for 0.3.x; next major bump is a Tier 2 item).
- Don't commit `results/` directory contents (generated artifacts are gitignored).
- Don't over-engineer for hypothetical future requirements — minimum viable for current task.
- Don't add docstrings, comments, or type annotations to code you didn't change.
- Don't add features or refactor code beyond what is directly requested.
- Don't introduce error handling for scenarios that can't happen; validate at system boundaries only.
- Don't merge a media-affecting change without human sign-off on the relevant artifact.
- **Don't use emoji or non-ASCII characters in `print()` or `logging` calls.** Use ASCII tags instead: `[OK]`, `[ERROR]`, `[WARN]`, `[INFO]`, `[SKIP]`, `[WAIT]`, `[LLM]`, `[debug]`. This prevents `UnicodeEncodeError` on Windows (CP1252 terminals). Non-ASCII is fine in comments, docstrings, and data strings (e.g., voiceover content).
- Don't perform git actions unless the user specifically asks.

---

## Content Guidelines

All generated content must comply with:
- YouTube Community Guidelines (no hate speech, harassment, dangerous content, misinformation)
- YouTube monetization eligibility (advertiser-friendly standards)
- No unauthorized copyrighted music, footage, or images
- Family-safe, all-audience content

Target format: faceless, caption-first, voiceover-narrated, 9:16 vertical, 15–60 seconds.

---

## Development Environment

**Python:** 3.10.11 — venv is at `/workspaces/.venvs/video_agent/`.

Activate: `source /workspaces/.venvs/video_agent/bin/activate`

This repo is also installable as a package: `pip install -e .`

**Installed LangChain versions (as of 2026-03-06):**

| Package | Version |
|---------|---------|
| `langchain` | 0.3.27 |
| `langchain-core` | 0.3.83 |
| `langchain-community` | 0.3.31 |
| `langchain-anthropic` | 0.3.22 |
| `langchain-google-genai` | 2.1.12 |

Install / sync dependencies: `pip install -r requirements.txt --upgrade`

---

## Key File Locations

| File | Purpose |
|------|---------|
| `main.py` | Backward-compat shim; delegates to `video_agent/main.py` |
| `video_agent/main.py` | CLI entry point (preflight, screenplay, pipeline modes) |
| `video_agent/agent.py` | Market research agent |
| `video_agent/script_agent.py` | Script generation agent |
| `video_agent/video_planner.py` | Video planning agent |
| `video_agent/audio_agent.py` | Audio/TTS generation agent |
| `video_agent/render_agent.py` | FFmpeg render agent |
| `video_agent/config.py` | All configuration and thresholds |
| `video_agent/tools/` | Tool implementations (YouTube API, TTS, image search) |
| `video_agent/mcp/video_agent_server.py` | MCP server exposing all 15 tools |
| `results/` | Per-run output artifacts (gitignored) |
| `results/metrics_summary.json` | Rolling pipeline metrics (output count, runtimes) |
| `ROADMAP.md` | Canonical priority and task tracking — check before starting any work |
| `docs/` | Architecture and design documentation |
| `pyproject.toml` | Package metadata and build config (hatchling) |

Import example: `from video_agent.orchestrator import ProductionOrchestrator`

---

## Integration Testing

The pipeline has 9 independently-testable stages. See **[docs/integration-testing.md](docs/integration-testing.md)** for the full guide including:
- Which test command to run for each changed component
- API key requirements per stage
- Fixture files and when to update them
- Test isolation guarantees

**Key rules:**
- Run only the stage(s) affected by your change, not the full suite (unless the full suite is warranted).
- Stages 4–9 can run offline using cached fixtures in `tests/fixtures/`.
- Canonical test fixture: WW2 Tanks setting (`tests/fixtures/script_package_ww2_tanks.json`).
- Output lands in `results/test/stages/<stage>_<timestamp>/` for human review.

---

## Human Review Protocol

Human review is a **pre-merge gate**, not a step after every edit. Review the artifact
closest to what changed — not the final video unless the final video stage itself changed:

| Changed component | Artifact to review |
|-------------------|--------------------|
| Image fetching | fetched images |
| Audio/TTS | MP3 segments |
| Compositor / render | final video |

**API keys are available in the environment.** The agent must run integration tests
autonomously using the existing keys — do not ask the human to run tests. The human's
role is to review the generated artifacts (images, audio, video), not to trigger runs.

When a change is ready for review:
1. **Run the test** scoped to the affected stage (not the full pipeline) using the available API keys.
2. **Preserve the previous output** in `results/baseline/` before regenerating, so old and new exist side by side. If none exists, note it.
3. **Narrate the diff** — which files changed and what to look/listen for in the output artifacts.
4. **Wait for explicit sign-off** on the artifact before marking done.

---

## Full Pipeline Test Reporting

When running the full MCP pipeline test (`scripts/run_full_mcp_pipeline.py`) or
any multi-stage pipeline run, **always report the outcome of every step** to the
user, including:

1. **Degradations:** Steps that completed but used a fallback (e.g., TTS returned
   silence because Chatterbox server was unavailable, placeholder images used
   because Pexels API key was missing). Report as `DEGRADED` with the reason.
2. **Warnings:** Non-fatal issues (e.g., audio segment duration mismatch,
   feasibility score below threshold, voiceover too long for scene timing).
3. **Partial completions:** Steps that produced output but not full expected output
   (e.g., 5 of 7 scenes got real TTS, 2 fell back to silence).
4. **Errors:** Steps that failed entirely and what downstream impact that had.
5. **Skips:** Steps that were skipped due to upstream failure or missing input.

Format the report as a summary table after the run completes:

```
| Step | Tool              | Status   | Notes                              |
|------|-------------------|----------|------------------------------------|
| 1    | research_topic    | OK       |                                    |
| 7    | generate_audio    | DEGRADED | 3/5 scenes silent (no TTS server)  |
| 10   | validate_output   | WARN     | duration parity 0.4s (> 0.25s)     |
```

Do not silently swallow fallbacks or degradations — the user needs to know which
parts of the output are placeholder/degraded to evaluate quality accurately.

---

## Quality Gates

A pipeline run is considered successful only if:
1. `final_video.mp4` exists and is playable.
2. `|audio_duration - video_duration| <= 0.25s` verified via `ffprobe`.
3. `evaluation.json` is written under the run folder.
4. No P0 regressions introduced.

---

## Tier 0 Success Checklist (Recruiter Appeal)

- [ ] Public GitHub repo with architecture diagram + quickstart in README
- [ ] At least one generated video artifact linked publicly (YouTube unlisted or GDrive)
- [ ] Audio continuity passes duration parity in all validation runs
- [ ] `evaluation.json` generated per run with alignment drift, duration, API cost
- [ ] `results/metrics_summary.json` with pipeline runtime + output count evidence
- [ ] Parallel vs sequential execution benchmark documented
