# Plan: Issue 2.6 — Image-Script Alignment Evaluation Loop

**Status:** Open
**Depends on:** 1.7 (tiered queries + passthrough evaluator interface)
**Branch:** `feat/image-alignment-evaluator` (from `feat/image-alignment-and-search-queries`)

## Problem

The pipeline retrieves stock images for video scenes but has no way to judge whether an image actually matches its scene. The passthrough `ImageAlignmentEvaluator` from issue 1.7 returns the first candidate without scoring. This means:
- Semantically mismatched images slip through (e.g., modern cheese factory for 18th-century scene)
- No data on image quality across runs
- No automatic revision when all candidates are poor

## Solution

Replace the passthrough with a rubric-based vision-model scorer that evaluates candidate images against scene descriptions. The evaluator uses a multimodal LLM to score each image on 5 axes, applies a two-threshold system for accept/reject, and emits revision requests for poor matches.

---

## Implementation Steps

### 1. Config (`video_agent/config.py`)

Add after the TTS config block:
```python
IMAGE_EVAL_BACKEND = os.getenv("IMAGE_EVAL_BACKEND", "online")      # "online" | "local"
IMAGE_EVAL_MODE = os.getenv("IMAGE_EVAL_MODE", "streaming")         # "streaming" | "batch"
IMAGE_EVAL_ACCEPT_THRESHOLD = float(os.getenv("IMAGE_EVAL_ACCEPT_THRESHOLD", "4.0"))
IMAGE_EVAL_MIN_THRESHOLD = float(os.getenv("IMAGE_EVAL_MIN_THRESHOLD", "2.5"))
```

### 2. Core evaluator (`video_agent/tools/image_alignment_tools.py`)

Full rewrite (~200 lines). Replace the passthrough with:

**Data structures:**
- `AlignmentScore` (frozen dataclass) — per-candidate: weighted_score, axis_scores dict, rationale
- `SceneAlignmentResult` (dataclass) — per-scene: best_score, best_candidate, candidates_evaluated, early_exit, revision_requested, all_scores list

**Rubric (5 axes, weighted average, each 1-5):**

| Axis | Weight | Question |
|------|--------|----------|
| subject | 0.35 | Does the image contain the primary subject? |
| setting | 0.25 | Does the era/location/environment match? |
| mood | 0.15 | Does the image mood match the scene? |
| composition | 0.15 | Is the framing usable for 9:16 vertical? |
| artifacts | 0.10 | Clean of watermarks/text/distractions? (5=clean) |

**Backend abstraction:**
- `ImageEvalBackend` protocol: `score_image(image_url, visual_description, vo_line, scene_mood) -> AlignmentScore`
- `OnlineImageEvalBackend`:
  - Fetches image bytes from candidate URL via `requests.get`
  - Base64-encodes and sends as `image_url` content block in a LangChain `HumanMessage`
  - Uses existing `make_llm(temperature=0.0)` — reuses the project's LLM provider (Claude or Gemini)
  - Structured prompt asks for JSON: `{"subject": N, "setting": N, "mood": N, "composition": N, "artifacts": N}`
  - Parses with regex fallback; on parse failure returns neutral 3.0 on all axes
- `IMAGE_EVAL_BACKEND=local` raises `NotImplementedError` (deferred to separate PR)

**ImageAlignmentEvaluator:**
- `__init__(backend, accept_threshold, min_threshold, mode)` — defaults from config
- `select_best(candidates, scene_context=None) -> Tuple[candidate | None, SceneAlignmentResult | None]`
  - When `scene_context is None`: passthrough (returns first candidate, `None`) for backward compat
  - **Streaming mode:** score candidates sequentially via URL fetch, stop when score >= accept_threshold
  - **Batch mode:** score all, pick highest
  - Set `revision_requested=True` when best_score < min_threshold

**Important:** The evaluator fetches image bytes from candidate URLs (not file paths). Images aren't downloaded to disk at this point in the pipeline — they're URL references. The evaluator makes its own HTTP request to get bytes for the vision API.

### 3. Visual agent wiring (`video_agent/visual_agent.py`)

Changes to `_select_and_prepare_asset()`:

- **Build scene_context dict** from existing `text_context` (vo_line), `topic_context`, and mood (default "neutral" — mood lives in screenplay but doesn't flow to video_plan scenes yet)
- **Unpack tuple return** from `select_best()` at both call sites (lines ~477 and ~506)
- **Replace `_llm_is_relevant` with threshold check:** Currently `_llm_is_relevant` is a text-only YES/NO check that runs AFTER `select_best`. With real vision scoring, it's redundant — the accept threshold serves the same purpose. Replace the `_llm_is_relevant` call with: if `alignment_result.best_score >= accept_threshold`, accept; else broaden query. This removes one LLM call per iteration.
- **Keep `_llm_broaden_query`** — still needed when the evaluator doesn't find a good match
- **Store alignment metadata** in the returned asset dict under `"alignment"` key
- **Collect alignment results** in `generate_visual_manifest()` and write `image_alignment_scores.json` alongside `visual_manifest.json`
- **Write production issue** when `alignment_result.revision_requested` is True — import `_write_production_report` from `script_image_agent.py`

### 4. Evaluation.json merge (`video_agent/mcp/video_agent_server.py`)

In the `validate_output` handler, merge alignment data into evaluation.json:
```python
alignment_path = run_dir / "image_alignment_scores.json"
if alignment_path.exists():
    evaluation["image_alignment"] = json.loads(alignment_path.read_text(encoding="utf-8"))
```

### 5. Integration test with human review

Create `tests/test_image_alignment_integration.py`:
- Run the evaluator against the WW2 tanks fixture with real API calls
- Score 2-3 scenes worth of candidates
- Write scores to `results/test/alignment_eval_<timestamp>/`
- Print a human-readable report: scene_id, candidate URL, per-axis scores, weighted score, accept/reject
- Human reviews the scores against the actual images to validate rubric calibration
- Marked with `@pytest.mark.integration` so it doesn't run in CI

### 6. (Deferred) MCP tool `evaluate_image_alignment`

Optional debugging tool. Not required for pipeline operation.

### 7. (Deferred) Local evaluation backend

LLaVA/CogVLM integration. Requires model download, CUDA memory management. Separate PR.

---

## Key Design Decisions

1. **Online backend only for now.** Reuses existing `make_llm()` + LangChain multimodal messages. No new dependencies.
2. **Evaluator fetches image bytes from URL internally.** Candidates at scoring time are URL references, not downloaded files. The evaluator does its own `requests.get` to fetch bytes for the vision API.
3. **Replace `_llm_is_relevant` with threshold check.** The text-only binary relevance check is subsumed by vision-model scoring. Removing it saves one LLM call per query iteration.
4. **Revision flows through existing mechanism.** Production issues written to `production_report.json` are picked up by the orchestrator's existing revision loop. No orchestrator changes needed.
5. **Mood defaults to "neutral".** The screenplay has mood per scene but it doesn't flow through to video_plan. Pass "neutral" for now; can thread mood through in a follow-up.
6. **Alignment scores in separate file.** Written to `image_alignment_scores.json`, merged into `evaluation.json` by `validate_output`. Keeps the evaluator side-effect-free.

---

## Files to Modify

| File | Change scope |
|------|-------------|
| `video_agent/config.py` | 4 new env-var config constants |
| `video_agent/tools/image_alignment_tools.py` | Full rewrite (~200 lines): dataclasses, backend protocol, online backend, evaluator |
| `video_agent/visual_agent.py` | Wire new evaluator, replace `_llm_is_relevant` with threshold, write alignment scores + production issues |
| `video_agent/mcp/video_agent_server.py` | Merge alignment data into evaluation.json in `validate_output` |
| `tests/test_image_alignment_integration.py` | New: integration test with human review of scores |

---

## Verification

1. **Integration test:** `pytest tests/test_image_alignment_integration.py -v -s` — runs evaluator against real images, prints score report for human review
2. **Human review:** Inspect printed scores alongside candidate images — validate rubric produces sensible scores
3. **Full pipeline:** `scripts/run_full_mcp_pipeline.py` — verify `evaluation.json` contains `image_alignment` section, revision loop triggers on low-scoring scenes

---

## Output Schema

Per-scene entry in `image_alignment_scores.json`:
```json
{
  "scene_id": "scene_03",
  "best_score": 3.8,
  "best_candidate_id": "pexels_12345",
  "scores_by_axis": {"subject": 4, "setting": 3, "mood": 4, "composition": 4, "artifacts": 5},
  "candidates_evaluated": 6,
  "early_exit": false,
  "revision_requested": false
}
```
