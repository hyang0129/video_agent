# Video Agent Pipeline - Development Roadmap

**Last Updated:** March 12, 2026

## Planning Source of Truth

This file is the canonical source for roadmap, priorities, and next steps.

To reduce drift, other docs should summarize local context only and link back to this roadmap for planning decisions.

## Current Status

### ✅ MVP Pipeline Functional (Not Yet Fully Production-Ready)
The pipeline can produce end-to-end vertical short-form videos (9:16, 30-60s) with:
- Market research → Topic identification
- Script generation with timing
- Video planning with scene structure
- Audio generation (Chatterbox TTS local GPU default, ElevenLabs fallback)
- Visual assets (Wikimedia + Pexels multi-source search with fallback)
- Composition (Ken Burns effects, text overlay specs)
- Rendering (FFmpeg slideshow: images + voiceover, with caveats)

### ✅ Completed Recently
- Text overlay rendering is now implemented in FFmpeg (`drawtext`) and validated on sample outputs.
- Subtitle robustness improved (line wrapping + newline/glyph handling fixes).
- Added operational render helpers: `scripts/run_render.py` and `scripts/run_starwars_render_with_logs.py`.
- Began Phase 1 audio-track integration: AudioTimeline now emits optional `audio_master.*`, composition forwards a `master` track, and render prefers master audio with segment fallback.
- Verified at least one recent output MP4 has a valid AAC audio stream via `ffprobe`.
- **MCP HTTPS server (phases 1-3):** Unified `src/mcp/video_agent_server.py` with TLS support, streamable-http transport, health endpoint, and all tool handlers (concept, screenplay, audio, image, render, validate). Orchestrator connects via real HTTPS MCP client or in-process dispatch. Both server and serverless full-pipeline integration tests passing.
- **Chatterbox TTS integration:** `vendor/chatterbox` submodule with `ChatterboxServerBackend` (HTTP) and `ChatterboxDirectBackend` (in-process GPU) as default TTS, replacing ElevenLabs dependency. Configurable via `TTS_BACKEND` env var.
- **Image search resilience:** Wikimedia rate limiter, multi-candidate download fallback, Pexels retry for failed Wikimedia scenes, partial re-run merge for visual manifests.
- **Pipeline merge fixes:** Audio tracks and visual assets merge by `scene_id` on partial re-runs instead of wholesale replacement. Composition falls back to available assets instead of hard error.

**Working Command:**
```powershell
python main.py mvp <topicbrief.json> [creative_spec.json] ffmpeg
```

**Output:** MP4 video in `results/<run_id>/final_video.mp4`

---

## Known Limitations

### 🚧 Phase 1 Gaps (MVP is functional but incomplete)

1. **Audio Continuity / Duration Mismatch** 🔥
  - Audio stream presence is now verified in at least one recent render (`ffprobe` shows AAC track).
  - Remaining issue: audio can end before video duration in some outputs (voiceover coverage only, no bed fill).
  - **Status:** In Progress (stream presence improved; full-duration continuity still open)
  - **Next Fix:** pad/extend timeline with music bed or silence and enforce post-render duration checks.

2. **Relevant Photo Coverage in Rendered Video**
  - Multi-source retrieval (Wikimedia + Pexels) with per-scene `visual_queries` from screenplay now implemented.
  - Fallback chain: Wikimedia -> Pexels -> placeholder BMP.
  - **Status:** Substantially improved (March 2026). Remaining gap: no CLIP relevance scoring.
  - **Implementation Plan:** [script-image-video-integration-plan.md](docs/script-image-video-integration-plan.md)

3. **No Background Music Mixing**
   - Audio timeline references music tracks but doesn't mix
   - Placeholder track metadata only
   - `apply_background_music()`, `mix_audio_tracks()` are stubs

4. **No LUFS Normalization**
   - Voiceover volume can be inconsistent across videos
   - `normalize_audio()` is stubbed

5. **No Advanced Video Effects**
   - Ken Burns defined in spec but not applied
   - Transitions stubbed (fade metadata present, not rendered)

6. **No Content Moderation**
   - Visual safety validation is passthrough (`provider="none"`)
   - No CLIP relevance scoring

---

## Prioritized Action Items

### 🧲 Tier 0: Recruiter Appeal (Immediate: next 3-7 days)

**Goal:** Maximize hiring credibility with verifiable outputs, production-signal metrics, and a public proof surface.

This tier is the current execution priority and supersedes older sequencing below where conflicts exist.

#### 0.1 Publish on GitHub + Portfolio-Grade README 🔥 HIGHEST ROI
- **Priority:** P0
- **Status:** ✅ Done (March 2026)
- **Deliverables:**
  - Public GitHub repo at `https://github.com/hyang0129/video_agent`
  - README quickstart (`python run_pipeline.py "cheese facts" --engine ffmpeg`) from clean setup to output
  - Mermaid architecture diagram (multi-agent pipeline with parallel branch callout)
  - Example output section with `docs/sample_video_thumbnail.jpg` + GitHub release MP4 link
  - Stage-by-stage CLI table, API key table, project structure, tech stack, known limitations
- **Success Metric:** A reviewer can understand architecture and run first output in under 10 minutes.

#### 0.2 Close Audio Continuity Gap (Full-Duration Audio-Synced Output) 🔥
- **Priority:** P0
- **Status:** In Progress
- **Problem:** Some outputs have audio ending early vs video duration.
- **Progress:**
  - `validate_output` tool in `producer_server.py` checks duration parity and writes `evaluation.json` ✅
  - `run_pipeline.py` only validates video stream presence — no audio duration parity check ❌
  - No hard fail on mismatch in the main pipeline runner ❌
- **Remaining work:**
  - Wire duration-parity check (<=0.25s) into `run_pipeline.py` post-render step
  - Fail run and write actionable error if parity check fails
  - Enforce audio fill (silence or music bed) when voiceover ends before video duration
- **Success Metric:** `|audio_duration - video_duration| <= 0.25s` for all validation runs.

#### 0.3 Show One Real Output Example (Public Artifact)
- **Priority:** P0
- **Status:** ✅ Done (March 2026)
- **Deliverables:**
  - GitHub release `v0.1.0-demo` hosts `final_video.mp4` (cheese history facts, ElevenLabs + Pexels + FFmpeg)
  - Thumbnail linked in README under "Example Output" (`docs/sample_video_thumbnail.jpg`)
- **Success Metric:** Recruiters can watch a concrete output without running code.

#### 0.4 Add Lightweight Evaluation Layer
- **Priority:** P1
- **Status:** Open
- **Track Per Run:**
  - Subtitle/audio alignment drift (ms)
  - Output duration vs target duration
  - API usage and estimated per-run cost
- **Progress:** `evaluation.json` written by `validate_output` in `producer_server.py` (MCP path only). Not yet wired into `run_pipeline.py` or `full_pipeline_runner.py`.
- **Remaining work:** Call `probe_video_info` + write `evaluation.json` at the end of `run_pipeline.py`.

#### 0.5 Add End-to-End Metrics + Evidence Counters
- **Priority:** P1
- **Status:** Open
- **Track:**
  - End-to-end pipeline runtime
  - Stage-level runtime breakdown
  - Total runs and successful rendered videos
- **Progress:** None — `results/metrics_summary.json` does not yet exist; no pipeline runner writes runtime metrics.
- **Deliverable:** Keep rolling summary in `results/metrics_summary.json` and surface snapshot in README (e.g., "generated 20+ test videos").

#### 0.6 Async/Parallel Agent Execution (Systems Credibility Upgrade)
- **Priority:** P2
- **Status:** Partially Done
- **Progress:** `ProductionOrchestrator` in `src/orchestrator.py` runs audio + image fetch in parallel via `asyncio.gather` + `ThreadPoolExecutor`. Both MCP and direct modes support parallel and serial execution. `run_pipeline.py` remains fully sequential.
- **Remaining work:** Document a sequential vs parallel benchmark on identical topic input. Add timing output to orchestrator run summary.
- **Success Metric:** Documented wall-clock improvement with no quality regression.

#### 0.7 MCP Full Server Mode (Architecture Showcase) 🔥
- **Priority:** P0
- **Status:** ✅ Done (March 2026)
- **Delivered:**
  - Unified `src/mcp/video_agent_server.py` with HTTPS/TLS support (streamable-http transport).
  - Orchestrator connects via real MCP HTTPS client (`streamable_http_client`) or in-process dispatch.
  - TLS foundation with `src/mcp/cert_utils.py` and `src/mcp/https_server_base.py`.
  - Health endpoint for server readiness checks.
  - Full-pipeline integration tests for both MCP HTTPS server (`tests/test_mcp_server_full_pipeline.py`) and serverless (`tests/test_mcp_serverless_full_pipeline.py`) modes.
- **Success Metric:** ✅ `use_mcp=True` calls traverse real HTTPS wire; tool handlers serve over TLS with health checks.

#### 0.8 Integrate chatterbox as Vendor Submodule (TTS Upgrade) 🔥
- **Priority:** P0
- **Status:** ✅ Done (March 2026)
- **Delivered:**
  - `vendor/chatterbox` submodule added and pinned.
  - `src/tools/chatterbox_backend.py` with two backends: `ChatterboxServerBackend` (HTTP to FastAPI server) and `ChatterboxDirectBackend` (in-process GPU).
  - `TTS_BACKEND` config switch (default: `chatterbox_server`). ElevenLabs available via `TTS_BACKEND=elevenlabs`.
  - `AudioGenerationAgent` and `create_audio_agent()` factory wired to backend selection.
  - Devcontainer GPU passthrough and isolated Python 3.11 venv for chatterbox.
  - `Makefile` targets: `submodules-init`, `submodules-update`.
- **Success Metric:** ✅ Chatterbox TTS is the default backend; local GPU inference with zero API cost.
- **Design doc:** [docs/chatterbox-integration-plan.md](docs/chatterbox-integration-plan.md)

---

### 🎯 Tier 1: Production Readiness (1-2 weeks)

**Goal:** Make the MVP fully production-complete with high-quality output

#### 1.1 Text Overlay Rendering 🔥 CRITICAL
- **Priority:** P0 (blocks production use)
- **Status:** ✅ Completed (February 18, 2026)
- **Problem:** Videos missing on-screen text captions
- **Solution Options:**
  - **Option A (Fast):** Add FFmpeg `drawtext` filter to [render_agent.py](src/render_agent.py)
    - Parse text elements from `RenderSpecification`
    - Build filter_complex with drawtext for each subtitle
    - Handle font, color, stroke, positioning, timing
    - **Effort:** 4-6 hours
    - **Pros:** Minimal code change, keeps existing pipeline
    - **Cons:** FFmpeg text rendering has limited styling
  
  - **Option B (Better):** Switch to `moviepy` for render engine
    - Replace FFmpeg engine with `moviepy.editor`
    - Get text, transitions, effects "for free"
    - Cleaner Python API
    - **Effort:** 2-3 days
    - **Pros:** Better text control, easier debugging, pure Python
    - **Cons:** Slower rendering, heavier dependency

- **Recommended:** Option A first (unblock production), then Option B (quality improvement)
- **Owner:** TBD
- **Timeline:** Week 1

#### 1.2 Background Music Mixing
- **Priority:** P1 (quality improvement)
- **Implementation:**
  - Install `pydub` (`pip install pydub`)
  - Implement `apply_background_music()` in [tts_tools.py](src/tools/tts_tools.py)
  - Load voiceover + music tracks
  - Apply volume_db adjustments
  - Mix and export
- **Dependencies:** Requires FFmpeg audio codecs
- **Testing:** Integration test with sample music track
- **Owner:** TBD
- **Timeline:** Week 1-2
- **Effort:** 2-3 days

#### 1.2b Final Audio Track Reliability (Voiceover Present in MP4)
- **Priority:** P0/P1 (blocking quality gate)
- **Problem:** Some FFmpeg outputs are playable but contain no audible voiceover.
- **Status:** In Progress
- **Progress (Feb 19):**
  - Audio master integration path added (`audio_master` → `track_master` → render preference).
  - Verified MP4 output with AAC audio stream via `ffprobe`.
- **Implementation:**
  - Validate stream mapping in `src/render_agent.py` (`-map [vout]` + `-map [aout]`).
  - Ensure input voiceover segments are resolvable and non-empty before render.
  - Add post-render check: fail run if output has no audio stream or duration mismatch.
  - Enforce full-length audio continuity (audio duration ~= video duration).
  - Add integration test that probes output MP4 audio stream with `ffprobe`.
- **Owner:** TBD
- **Timeline:** Immediate
- **Effort:** 0.5-1 day

#### 1.3 LUFS Audio Normalization
- **Priority:** P1 (quality improvement)
- **Implementation:**
  - Install `pyloudnorm` (`pip install pyloudnorm`)
  - Implement `normalize_audio()` in [tts_tools.py](src/tools/tts_tools.py)
  - Measure input LUFS
  - Apply gain to reach target (-16.0 LUFS)
  - Validate output
- **Testing:** Unit test with various audio samples
- **Owner:** TBD
- **Timeline:** Week 2
- **Effort:** 1 day

#### 1.4 GitHub Actions CI/CD
- **Priority:** P1 (infrastructure)
- **Implementation:**
  - Create `.github/workflows/test.yml`
  - Run `pytest` on every PR
  - Add preflight check (validate env vars)
  - Add linting (`ruff` or `black`)
  - Cache dependencies
- **Benefits:** Catch regressions early, enforce code quality
- **Owner:** TBD
- **Timeline:** Week 2
- **Effort:** 1 day

#### 1.4b Align Screenwriting Avatar Emotes with Available Emotes
- **Priority:** P1 (content quality)
- **Status:** Open
- **Problem:** The screenwriting agent assigns avatar emotes that may not exist in the actual emote set, causing mismatches or silent fallbacks at render time.
- **Implementation:**
  - Audit the emote vocabulary used in [src/screenwriting/](src/screenwriting/) against the emotes actually available from the avatar system
  - Update the screenplay prompt/schema to enumerate only valid emote identifiers
  - Add validation in the screenplay reviewer to reject or flag unrecognized emotes
- **Owner:** TBD
- **Timeline:** Week 1-2

#### 1.5 Script Image → Video Integration
- **Priority:** P0/P1 (visual quality gate)
- **Status:** ✅ Done (March 2026)
- **Delivered:**
  - Per-scene `visual_queries` from screenplay flow through `script_package` beats into image search.
  - Multi-source retrieval: Wikimedia (primary) + Pexels (fallback) with candidate-list download retry.
  - Wikimedia rate limiter prevents 429 errors.
  - Partial re-run merge: new visual assets merge by `scene_id` into existing manifest.
  - Composition agent falls back to available assets instead of hard error on missing scenes.
- **Plan:** [script-image-video-integration-plan.md](docs/script-image-video-integration-plan.md)

#### 1.6 Integrate live2d as Vendor Submodule (Avatar Renderer)
- **Priority:** P1
- **Status:** ✅ Done (March 2026)
- **Delivered:**
  - `vendor/live2d` submodule added with Linux build passing.
  - `Makefile` target: `make live2d-build` (CMake build -> `vendor/live2d/build/bin/`).
  - `vendor/live2d/build/` in `.gitignore`.
- **CLI:** `live2d-render --scene scene.json`, `live2d-inspect --model <name>`
- **Design doc:** [docs/submodule-integration-plan.md](docs/submodule-integration-plan.md)

---

### 🚀 Tier 2: Scale & Reliability (2-4 weeks)

**Goal:** Improve stability, maintainability, and performance

#### 2.1 Upgrade LangChain to 1.x (current stable)
- **Priority:** P2 (technical debt + security)
- **Status:** ✅ Completed (March 2026) on branch `feat/langchain-upgrade`
- **Was:** `langchain==0.1.20`
- **Now:** `langchain>=0.3.0,<2.0` (1.x stable series)
- **Plan:** [docs/langchain-upgrade-plan.md](docs/langchain-upgrade-plan.md)
- **Changes made:**
  - `langchain.prompts` → `langchain_core.prompts` in [agent.py](src/agent.py)
  - `langchain.schema` → `langchain_core.messages` in [agent.py](src/agent.py), [script_agent.py](src/script_agent.py), [fact_miner.py](src/facts/fact_miner.py)
  - `langchain.tools` → `langchain_core.tools` in [youtube_tools.py](src/tools/youtube_tools.py)
  - `langchain-google-genai` bumped to `>=2.0.0`
  - `langchain-anthropic` bumped to `>=0.3.0`
- **Human review gate:** Run Stage 1-3 integration tests and sign off before merging


#### 2.2 Results Directory Cleanup Job
- **Priority:** P2 (maintenance)
- **Problem:** `results/` dir has 19+ run folders, growing unbounded
- **Implementation:**
  - Create `scripts/cleanup_results.py`
  - Configurable retention policy (default: 7 days)
  - Dry-run mode for safety
  - Can run as cron job or manually
- **Example:**
  ```python
  python scripts/cleanup_results.py --days 7 --dry-run
  ```
- **Owner:** TBD
- **Timeline:** Week 3
- **Effort:** 1 day

#### 2.3 YouTube Quota Persistence
- **Priority:** P2 (reliability)
- **Problem:** Quota counter resets on restart, can exceed daily limit (10K units)
- **Implementation:**
  - Create `cache/quota_tracker.json`
  - Persist `quota_used` after each API call
  - Reset daily at midnight UTC
  - Warn when approaching 80% of limit
  - Hard stop at 95% to prevent overage
- **Testing:** Unit test with fixture dates
- **Owner:** TBD
- **Timeline:** Week 3-4
- **Effort:** 1-2 days

#### 2.4 Enhanced Error Recovery
- **Priority:** P2 (reliability)
- **Implementation:**
  - Add exponential backoff to ElevenLabs TTS retries
  - Graceful degradation (skip scene if asset download fails)
  - Partial run recovery (resume from last successful agent)
  - Better error messages with actionable guidance
- **Example:**
  ```
  ❌ Failed to download asset for scene_03: HTTPError 503
  ↪ Retrying in 2s... (attempt 2/3)
  ```
- **Owner:** TBD
- **Timeline:** Week 4
- **Effort:** 2 days

---

### 🔮 Tier 3: Features & Quality (4-8 weeks)

**Goal:** Add advanced capabilities and polish

#### 3.1 Content Moderation Integration
- **Priority:** P3 (safety)
- **Implementation:**
  - Integrate Google Vision API for NSFW detection
  - Add CLIP relevance scoring (image-text matching)
  - Update [content_validation_tools.py](src/tools/content_validation_tools.py)
  - Configurable safety thresholds
- **Dependencies:**
  - `google-cloud-vision` SDK
  - `transformers` + `torch` for CLIP (optional)
- **Owner:** TBD
- **Timeline:** Weeks 5-6
- **Effort:** 1 week

#### 3.2 Stock Video Clips Support
- **Priority:** P3 (feature)
- **Implementation:**
  - Add Pexels Video API to [image_search_tools.py](src/tools/image_search_tools.py)
  - Video trimming/cropping to fit scene duration
  - FFmpeg video concatenation (not just images)
  - Update VisualManifest schema for video clips
- **Challenges:**
  - Larger file sizes (caching strategy)
  - Preview/selection UI needed
- **Owner:** TBD
- **Timeline:** Weeks 6-7
- **Effort:** 1-2 weeks

#### 3.3 Advanced Video Effects
- **Priority:** P3 (polish)
- **Implementation:**
  - Ken Burns (zoom/pan) via FFmpeg `zoompan` filter
  - Crossfade transitions via `xfade` filter
  - Color grading presets (LUTs)
  - Vignette overlays
- **References:**
  - [FFmpeg Zoompan Wiki](https://trac.ffmpeg.org/wiki/Zoompan)
  - [visual-composition-agents.md](docs/visual-composition-agents.md#phase-2-advanced-features)
- **Owner:** TBD
- **Timeline:** Week 7
- **Effort:** 1 week

#### 3.4 Thumbnail Generation
- **Priority:** P3 (feature)
- **Implementation:**
  - Extract frame at t=2s or t=25% using FFmpeg
  - Add text overlay for thumbnail (larger font)
  - Export as JPEG to `results/<run_id>/thumbnail.jpg`
  - Update [render_agent.py](src/render_agent.py) `generate_thumbnail()` stub
- **Owner:** TBD
- **Timeline:** Week 8
- **Effort:** 2-3 days

#### 3.5 Web Dashboard (Optional)
- **Priority:** P4 (nice-to-have)
- **Scope:**
  - Browse market research reports
  - View generated videos
  - Trigger video generation jobs
  - Download final MP4s
- **Stack Options:**
  - FastAPI + React (full-featured)
  - Streamlit (rapid prototype)
  - Gradio (minimal UI)
- **Owner:** TBD
- **Timeline:** Weeks 9-12
- **Effort:** 3-4 weeks

---

## Quick Wins (Can Do This Week)

### QW1: Add .gitignore for results/
```gitignore
# results/
results/*/
!results/README.md
```
- **Effort:** 2 minutes
- **Benefit:** Stop tracking generated output files

### QW2: Add requirements.txt comments
```python
# Core LangChain (pinned due to API stability)
langchain==0.1.20  # TODO: Upgrade to 0.3.x in Q1 2026
```
- **Effort:** 5 minutes
- **Benefit:** Document why versions are pinned

### QW3: Create CONTRIBUTING.md
- Development setup instructions
- How to run tests
- Code style guidelines
- PR checklist
- **Effort:** 30 minutes
- **Benefit:** Easier onboarding for contributors

### QW4: Update README.md with limitations
Add "Known Limitations" section:
- Text overlays not rendered (Phase 1)
- No background music mixing (Phase 1)
- No LUFS normalization (Phase 1)
- **Effort:** 10 minutes
- **Benefit:** Set correct expectations

---

## Dependencies & Prerequisites

### Required for Tier 1
```bash
# Audio mixing
pip install pydub>=0.25.0

# Audio normalization
pip install pyloudnorm>=0.1.0

# Text rendering (Option B)
pip install moviepy>=1.0.3
```

### Required for Tier 3
```bash
# Content moderation
pip install google-cloud-vision>=3.0.0

# CLIP relevance (optional)
pip install transformers>=4.30.0 torch>=2.0.0
```

### System Dependencies
```powershell
# FFmpeg (already required)
winget install Gyan.FFmpeg

# ImageMagick (optional, for advanced image processing)
winget install ImageMagick.ImageMagick
```

---

## Decision Log

### Why prioritize text rendering over music mixing?
- **Text is content**, music is polish
- Current videos are **incomplete** without text
- Music can be added post-production, text cannot
- User feedback: "Where are the captions?"

### Why FFmpeg drawtext first, then MoviePy?
- **Minimize risk:** Small change to existing working pipeline
- **Learn fast:** Test with real users, iterate
- **Option value:** Can still switch to MoviePy later if needed

### Why not use cloud rendering (Shotstack)?
- **Cost:** $9/month + per-minute fees
- **Latency:** Network round-trip
- **Vendor lock-in:** Hard to switch later
- **Local is free:** FFmpeg is zero cost, proven reliable

---

## Success Criteria

### Tier 0 (Recruiter Appeal) Complete When:
- [x] Repo is publicly shareable with strong README (diagram + quickstart + output visuals)
- [x] At least one real generated video artifact link is live in README
- [ ] Audio continuity passes duration parity checks in validation runs (`run_pipeline.py` hard-fail wired)
- [ ] Per-run evaluation artifacts are generated (`evaluation.json`) from `run_pipeline.py`
- [ ] Metrics summary exists with runtime + output-count evidence (`results/metrics_summary.json`)
- [ ] Parallel execution benchmark is documented (wall-clock comparison logged)
- [x] MCP HTTPS server with TLS, health checks, and full-pipeline integration tests
- [x] chatterbox submodule integrated as default TTS backend (`vendor/chatterbox/`)

### Tier 1 Complete When:
- [x] Videos have on-screen text overlays rendered
- [x] Final MP4 has audible voiceover track in validation runs
- [ ] Audio has background music mixed in
- [ ] Voiceover is LUFS normalized (-16.0 ±1.0)
- [ ] CI/CD runs tests on every PR
- [ ] No P0/P1 bugs in issue tracker
- [x] live2d submodule integrated and buildable (`make live2d-build`)

### Tier 2 Complete When:
- [ ] LangChain upgraded to 1.x (branch ready, pending human review + merge)
- [ ] Results cleanup job runs weekly
- [ ] YouTube quota never exceeds limit
- [ ] 95%+ render success rate (no crashes)

### Tier 3 Complete When:
- [ ] Content moderation active (0 unsafe assets shipped)
- [ ] Stock video clips supported
- [ ] Ken Burns + crossfade effects working
- [ ] Thumbnails auto-generated

---

## Metrics to Track

### Recruiter Evidence
- **Public output artifacts:** >=1 linked playable video
- **Documented sample volume:** >=20 generated test videos (or current count)
- **Quickstart reproducibility:** first successful run from README in <10 minutes

### Quality
- **Text rendering accuracy:** 100% (all text visible, readable)
- **Audio sync drift:** <50ms (imperceptible)
- **Content safety:** 0 violations shipped
- **Visual relevance:** 80%+ CLIP similarity

### Performance
- **Render time:** <60s for 45s video (CPU), <20s (GPU)
- **End-to-end pipeline time:** Track p50/p95 per run
- **API success rate:** 95%+ (YouTube, ElevenLabs, Pexels)
- **Per-run API cost:** Track estimated dollars per pipeline run
- **Quota usage:** <80% of daily limits

### Reliability
- **Render success rate:** 95%+ first attempt
- **Uptime:** 99.9% (no blocking bugs)
- **Test coverage:** 80%+ (pytest)
- **Integration tests:** follow [docs/integration-testing.md](docs/integration-testing.md) — run only the affected stage(s), not the full suite, unless a cross-stage change warrants it

---

## Getting Started

### Immediate Execution Order (March 2026)
1. **Tier 0.1:** Publish GitHub + upgrade README with architecture diagram, quickstart, and output visuals
2. **Tier 0.2:** Close audio continuity gap with hard duration validation gates
3. **Tier 0.3:** Publish one real generated-video artifact and link in README

### Next Execution Window (Following 1-2 weeks)
1. **Tier 0.4:** Add lightweight evaluation outputs (`evaluation.json`)
2. **Tier 0.5:** Add runtime/output counters and README evidence snapshot
3. **Tier 0.6:** Implement and benchmark parallel agent execution path

### After Tier 0
- Resume Tier 1 quality items not yet complete (music mixing, LUFS, CI)
- Continue Tier 2 reliability/scalability upgrades

---

## References

- [integration-testing.md](docs/integration-testing.md) - **Integration testing guide** — which tests to run per changed component, fixture management, API key requirements
- [visual-composition-agents.md](docs/visual-composition-agents.md) - Detailed agent specs
- [audio-agent.md](docs/audio-agent.md) - Audio pipeline architecture
- [pipeline-integration.md](docs/pipeline-integration.md) - End-to-end flow
- [market-research-agent-architecture.md](docs/market-research-agent-architecture.md) - Research stage
- [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
- [MoviePy Documentation](https://zulko.github.io/moviepy/)

---

## Questions or Feedback?

Open an issue or start a discussion in the repo to:
- Propose new features
- Report bugs or limitations
- Suggest priority changes
- Share use cases

**Maintainer:** TBD  
**Last Review:** March 12, 2026
