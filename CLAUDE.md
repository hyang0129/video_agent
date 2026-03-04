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

### Don't
- Don't use cloud rendering services (Shotstack, etc.) — avoids cost and vendor lock-in.
- Don't upgrade LangChain beyond `0.1.x` without a dedicated migration branch (Tier 2 item).
- Don't commit `results/` directory contents (generated artifacts are gitignored).
- Don't over-engineer for hypothetical future requirements — minimum viable for current task.
- Don't add docstrings, comments, or type annotations to code you didn't change.
- Don't add features or refactor code beyond what is directly requested.
- Don't introduce error handling for scenarios that can't happen; validate at system boundaries only.
- Don't merge a media-affecting change without human sign-off on the relevant artifact.

---

## Content Guidelines

All generated content must comply with:
- YouTube Community Guidelines (no hate speech, harassment, dangerous content, misinformation)
- YouTube monetization eligibility (advertiser-friendly standards)
- No unauthorized copyrighted music, footage, or images
- Family-safe, all-audience content

Target format: faceless, caption-first, voiceover-narrated, 9:16 vertical, 15–60 seconds.

---

## Key File Locations

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point for all pipeline stages |
| `src/agent.py` | Market research agent |
| `src/script_agent.py` | Script generation agent |
| `src/video_planner.py` | Video planning agent |
| `src/audio_agent.py` | Audio/TTS generation agent |
| `src/render_agent.py` | FFmpeg render agent |
| `src/config.py` | All configuration and thresholds |
| `src/tools/` | Tool implementations (YouTube API, TTS, image search) |
| `results/` | Per-run output artifacts (gitignored) |
| `results/metrics_summary.json` | Rolling pipeline metrics (output count, runtimes) |
| `ROADMAP.md` | Canonical priority and task tracking — check before starting any work |
| `docs/` | Architecture and design documentation |

---

## Human Review Protocol

Human review is a **pre-merge gate**, not a step after every edit. Review the artifact
closest to what changed — not the final video unless the final video stage itself changed:

| Changed component | Artifact to review |
|-------------------|--------------------|
| Image fetching | fetched images |
| Audio/TTS | MP3 segments |
| Compositor / render | final video |

When a change is ready for review:
1. **Provide a single test command** scoped to the affected stage (not the full pipeline).
2. **Preserve the previous output** in `results/baseline/` before regenerating, so old and new exist side by side. If none exists, note it.
3. **Narrate the diff** — which files changed and what to look/listen for.
4. **Wait for explicit sign-off** before marking done.

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
