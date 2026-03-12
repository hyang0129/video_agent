# Integration Testing Guide

## Test Tiers

The project uses a two-tier testing strategy:

| Tier | Purpose | Location | Speed | API keys? |
|------|---------|----------|-------|-----------|
| **Unit tests** | Per-agent logic, mocked dependencies | `tests/test_*.py` | Fast (seconds) | None |
| **Full-pipeline E2E** | MCP server integration, video output for human review | `tests/test_mcp_server_full_pipeline.py` | Slow (minutes) | Yes |

**Run unit tests (fast, offline):**
```bash
pytest tests/test_*.py -v -k "not integration"
```

**Run full-pipeline E2E (MCP server, outputs video):**
```bash
pytest tests/test_mcp_server_full_pipeline.py -v -s
```

Stage-based integration tests (`tests/integration/test_stage_*.py`) remain available
for targeted validation of individual pipeline stages.

> **Deprecated tests** live in `tests/deprecated/`. They are excluded from collection
> via `collect_ignore_glob` in `pytest.ini`. See `tests/deprecated/README.md` for details.

---

## Overview

The pipeline has 9 independently-testable stages. Each stage has a dedicated test
that loads a known-good input artifact (fixture), runs exactly one stage, and
copies output to `results/test/stages/<stage>_<timestamp>/` for human review.

```
Stage 1  market_research    MarketResearchAgent   → TopicBrief
Stage 2  fact_mining        FactMiner             → FactStore (SQLite)
Stage 3  script_writing     ScriptGenerationAgent → ScriptPackage
Stage 4  video_planning     script_package_to_video_plan → VideoPlan
Stage 5  audio_generation   AudioAgent            → AudioTimeline + MP3 segments
Stage 6  image_retrieval    VisualAgent           → VisualManifest + images
Stage 7  music_selection    MusicAgent            → MusicSelection
Stage 8  composition        CompositionAgent      → RenderSpecification
Stage 9  render             RenderAgent           → final_video.mp4
```

The canonical test fixture is the **WW2 Tanks** setting (`tests/fixtures/`).
Stages 1–3 are the expensive ones (YouTube API + LLM + ElevenLabs).
Stages 4–9 run on deterministic or near-free operations from a cached ScriptPackage.

---

## Running Tests

### Full suite (all 9 stages)
```bash
pytest tests/integration/ -v -s -m integration
```

### Single stage
```bash
pytest tests/integration/test_stage_05_audio_generation.py -v -s -m integration
```

### Range of stages (e.g. after changing composition or render)
```bash
pytest tests/integration/test_stage_08_composition.py \
       tests/integration/test_stage_09_render.py -v -s -m integration
```

### Full-pipeline E2E (MCP server integration)
```bash
pytest tests/test_mcp_server_full_pipeline.py -v -s
```

---

## API Key Requirements Per Stage

| Stage | YOUTUBE_API_KEY | GOOGLE_API_KEY | ELEVENLABS_API_KEY | PEXELS_API_KEY | ffmpeg/ffprobe |
|-------|:-:|:-:|:-:|:-:|:-:|
| 1 market_research  | ✓ | ✓ |   |   |   |
| 2 fact_mining      | ✓ | ✓ |   |   |   |
| 3 script_writing   |   | ✓ |   |   |   |
| 4 video_planning   |   |   |   |   |   |
| 5 audio_generation |   |   | ✓ (or silent) |   |   |
| 6 image_retrieval  |   |   |   | ✓ (or placeholder) |   |
| 7 music_selection  |   |   |   |   | ffprobe |
| 8 composition      |   |   |   |   | ffprobe |
| 9 render           |   |   |   |   | ffmpeg + ffprobe |

Stages 4–9 can all run offline with placeholders. Stages 1–3 always need live APIs.

---

## Artifact Cache: What to Cache for Partial Testing

The key insight: **each stage's output is the next stage's input**. Saving
intermediate artifacts lets you re-run only the stages affected by a code change.

### Cached fixture files (committed to repo)

| File | Feeds into stages | How to regenerate |
|------|:-:|---|
| `tests/fixtures/topic_brief_ww2_tanks.json` | 2, 3 | Run stage 1 and copy preferred output |
| `tests/fixtures/script_package_ww2_tanks.json` | 4–9 | Run stage 3 and copy preferred output |

These two fixtures are the stable anchors. Everything downstream of stage 3 can
be re-run deterministically from `script_package_ww2_tanks.json` without any API calls
(except ElevenLabs and Pexels, which have silent/placeholder fallbacks).

### Transient artifacts (generated during test runs, not committed)

These live under `results/test/stages/<stage>_<timestamp>/` after each run.
They are gitignored. To reuse a specific run's output as the next stage's input,
copy the artifact manually or use the re-render command printed at the end of each test.

| Artifact | Produced by stage | Consumed by stages |
|---|:-:|:-:|
| `topic_brief.json` | 1 | 2, 3 |
| `facts.db` / `extracted_facts.json` | 2 | 3 |
| `script_package.json` | 3 | 4–9 |
| `video_plan.json` | 4 | 5, 6, 8 |
| `audio_timeline.json` + `audio_segments/` | 5 | 7, 8 |
| `visual_manifest.json` + images | 6 | 8 |
| `music_selection.json` | 7 | 8 |
| `render_spec.json` | 8 | 9 |
| `final_video.mp4` | 9 | — (human review) |

---

## What to Run for Each Type of Code Change

### Changed `render_agent.py`
Only the final render step is affected.
```bash
pytest tests/integration/test_stage_09_render.py -v -s -m integration
```
Human review: watch `final_video.mp4` — visual quality, timing, text overlays.

---

### Changed `composition_agent.py`
RenderSpecification assembly changed; render output may differ.
```bash
pytest tests/integration/test_stage_08_composition.py \
       tests/integration/test_stage_09_render.py -v -s -m integration
```
Human review: `render_spec.json` (scene list, text specs) + `final_video.mp4`.

---

### Changed `visual_agent.py` or `image_search_tools.py`
Image retrieval or selection logic changed.
```bash
pytest tests/integration/test_stage_06_image_retrieval.py \
       tests/integration/test_stage_08_composition.py \
       tests/integration/test_stage_09_render.py -v -s -m integration
```
Human review: fetched images in `visual_manifest.json` + rendered video.

---

### Changed `audio_agent.py` or `tts_tools.py`
Audio generation or TTS changed.
```bash
pytest tests/integration/test_stage_05_audio_generation.py \
       tests/integration/test_stage_08_composition.py \
       tests/integration/test_stage_09_render.py -v -s -m integration
```
Human review: listen to `audio_segments/*.mp3` + watch rendered video for sync.

---

### Changed `music_agent.py`
Music selection logic changed.
```bash
pytest tests/integration/test_stage_07_music_selection.py \
       tests/integration/test_stage_08_composition.py \
       tests/integration/test_stage_09_render.py -v -s -m integration
```
Human review: listen to music track + watch rendered video.

---

### Changed `video_planner.py`
VideoPlan schema or timing logic changed — affects all downstream stages.
```bash
pytest tests/integration/test_stage_04_video_planning.py \
       tests/integration/test_stage_05_audio_generation.py \
       tests/integration/test_stage_06_image_retrieval.py \
       tests/integration/test_stage_08_composition.py \
       tests/integration/test_stage_09_render.py -v -s -m integration
```
Human review: `video_plan.json` scene structure + full rendered video.

---

### Changed `script_agent.py`
Script generation logic changed — all stages must re-run.
Update the `script_package_ww2_tanks.json` fixture if the output schema changes.
```bash
pytest tests/integration/test_stage_03_script_writing.py -v -s -m integration
# Review output, then run full downstream if script quality looks good:
pytest tests/integration/ -v -s -m integration -k "not market_research and not fact_mining"
```
Human review: `script_package.json` — grounding, voiceover quality, beat timing.

---

### Changed `fact_miner.py` or `fact_store.py`
Fact extraction or storage logic changed.
```bash
pytest tests/integration/test_stage_02_fact_mining.py -v -s -m integration
```
Human review: `extracted_facts.json` — accuracy, specificity, no meta-facts.
Note: stages 3–9 use seeded/fixture facts, so they are not affected unless
`fact_store.query()` behavior changed (in which case also run stage 3).

---

### Changed `agent.py` (market research)
Topic discovery logic changed.
```bash
pytest tests/integration/test_stage_01_market_research.py -v -s -m integration
```
Human review: topic briefs — relevance, scoring, angle quality.

> **Note — stale cookies:** Stages 1 and 2 use `youtube-transcript-api` for caption
> fetching. If `youtube_cookies.txt` is missing or expired you may see `IpBlocked`
> errors on transcript calls. The test does not fail hard on these (transcripts are
> best-effort), but fact quality will drop. To refresh: export a fresh Netscape-format
> cookie file from your browser while logged into YouTube and save it as
> `youtube_cookies.txt` in the project root. Never commit this file.

---

## Updating Fixtures

Fixtures should be updated when:
- The schema of a stage's output changes (new required fields, renamed keys)
- A better example is found that exercises edge cases more thoroughly
- A bug was fixed and the old fixture encodes the broken behaviour

**To update `script_package_ww2_tanks.json`:**
1. Run stage 3: `pytest tests/integration/test_stage_03_script_writing.py -v -s -m integration`
2. Review the output in `results/test/stages/03_script_writing_*/script_package.json`
3. If satisfied, copy it: `cp results/test/stages/03_script_writing_.../script_package.json tests/fixtures/script_package_ww2_tanks.json`
4. Commit the updated fixture with a note on what changed

**To update `topic_brief_ww2_tanks.json`:**
Same process using stage 1 output.

---

## Human Review Protocol

Every stage test prints a review checklist when it runs. The review dir is:
```
results/test/stages/<stage>_<timestamp>/
```

**Before merging any change that affects media output:**
1. Run the stage test(s) for the changed component
2. Open the review dir and inspect the relevant artifact (see checklist in each test file)
3. For audio: listen to MP3 segments
4. For images: open the manifest and inspect fetched images
5. For video: watch `final_video.mp4`
6. Sign off in the PR description with the review dir path and what was checked

To re-render from a saved spec without re-running the full pipeline:
```bash
python main.py render results/test/stages/08_composition_.../render_spec.json ffmpeg
```

---

## Test Isolation Guarantees

Each stage test:
- Uses `tmp_path` (pytest's isolated temp dir) for all generated files
- Loads only from committed fixtures in `tests/fixtures/`
- Does not read from or write to `results/` during the test itself
- Copies output to `results/test/stages/` only after the test passes
- Does not share state with other tests (no global FactStore, no shared dirs)

This means tests can be run in any order and in parallel without interference.
