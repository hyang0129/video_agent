# Implementation Plan: Roadmap 0.5 + 0.6

**Branch:** `feat/metrics-and-parallel-benchmark`
**Scope:** End-to-end metrics instrumentation (0.5) + parallel execution benchmark (0.6)

---

## Design Constraint: MCP-Only Future

Roadmap 1.0 deletes `run_pipeline.py` and consolidates onto a single MCP execution
path: `main.py` (thin CLI) -> `orchestrator.py` -> MCP tool handlers. All timing
and metrics work targets the **surviving code path** to avoid throwaway investment.

| Component | Survives 1.0? | Our investment |
|-----------|---------------|----------------|
| `orchestrator.py` | Yes (MCP-only, `use_mcp` flag removed) | **Primary timing + metrics collection point** |
| `src/mcp/video_agent_server.py` | Yes | **Per-tool `elapsed_seconds`** |
| `src/metrics.py` (new) | Yes | **Rolling metrics writer** |
| `run_pipeline.py` | **No -- deleted in 1.0** | Zero changes |
| `scripts/benchmark_parallel.py` (new) | Yes | **Invokes orchestrator directly** |

---

## Current State

| Component | Timing Today | Parallel Support |
|-----------|-------------|------------------|
| `orchestrator.py` | Log timestamps only (no structured timing) | Yes: `asyncio.gather` + `ThreadPoolExecutor` for audio+image via `serial` flag |
| `video_agent_server.py` | None | Stateless tools, no timing metadata |
| `render_agent.py` | `render_time_seconds` in `final_video.json` | N/A |
| `results/metrics_summary.json` | **Does not exist** | N/A |

---

## 0.5: End-to-End Metrics + Evidence Counters

### Change 1: MCP tool-handler timing in `video_agent_server.py`

**File:** `src/mcp/video_agent_server.py`

Add a timing wrapper in the `call_tool()` dispatch function. Before returning the
tool result, measure elapsed time and inject `"elapsed_seconds"` into the JSON
result:

```python
import time

async def call_tool(name, arguments):
    t0 = time.time()
    # ... existing dispatch logic ...
    elapsed = round(time.time() - t0, 3)
    # inject elapsed_seconds into the result TextContent JSON
```

The orchestrator already parses tool results via `_call_tool_inprocess()` -- the
new field is available immediately without orchestrator changes.

**Impact:** ~10 lines in `call_tool()`. All 10 tool results gain an
`elapsed_seconds` field. Backward-compatible (additive field).

---

### Change 2: Orchestrator end-to-end + stage timing in `orchestrator.py`

**File:** `src/orchestrator.py`

Add `time.time()` instrumentation in `ProductionOrchestrator.run()`:

1. **Total run elapsed** -- wrap the entire `run()` method
2. **Production pass elapsed** -- wrap the audio+image production call (round 0)
3. **Per-revision-round elapsed** -- wrap each revision loop iteration
4. **Collect MCP tool timings** -- read `elapsed_seconds` from MCP tool results
   returned by `_produce_*_mcp()` functions (they already parse the JSON)

Return timing data in the existing `production_report.json`:

```python
production_report = {
    "schema_version": "1.1.0",
    "run_id": run_id,
    "mode": mode,                          # "mcp-parallel", "mcp-serial", etc.
    "total_elapsed_s": 185.3,              # NEW
    "production_elapsed_s": 140.2,         # NEW: round 0 audio+image
    "tool_timings": {                      # NEW: from MCP elapsed_seconds
        "generate_audio": 95.1,
        "fetch_assets": 82.4,
    },
    "revision_rounds": [                   # NEW
        {"round": 1, "elapsed_s": 22.1, "scenes_revised": 2}
    ],
    "issues": [...],
    "degraded_scene_count": 0,
}
```

To surface tool timings, update the `_produce_parallel_mcp()` and
`_produce_serial_mcp()` helpers to return timing alongside the artifact dicts:

```python
# Returns (audio_timeline, image_manifest, tool_timings)
async def _produce_parallel_mcp(...) -> tuple[dict, dict, dict]:
    ...
    tool_timings = {
        "generate_audio": audio_result.get("elapsed_seconds", 0),
        "fetch_assets": image_result.get("elapsed_seconds", 0),
    }
    return audio_timeline, image_manifest, tool_timings
```

**Impact:** ~35 lines across `run()` and the `_produce_*_mcp` helpers.

---

### Change 3: `update_metrics_summary()` and `results/metrics_summary.json`

**File:** `src/metrics.py` (new file, ~60 lines)

A single function that appends run data to the rolling metrics file:

```python
def update_metrics_summary(
    metrics_path: Path,
    run_id: str,
    run_duration_s: float,
    stage_timings: dict,
    passed: bool,
    mode: str = "mcp-parallel",
) -> dict:
```

Schema for `results/metrics_summary.json`:

```json
{
  "schema_version": "1.0.0",
  "total_runs": 5,
  "successful_runs": 4,
  "avg_pipeline_duration_s": 312.5,
  "runs": [
    {
      "run_id": "sample_2026-03-12_cheese_facts_abc123",
      "timestamp": "2026-03-12T14:30:00Z",
      "duration_s": 280.3,
      "passed": true,
      "mode": "mcp-parallel",
      "stage_timings": {
        "generate_audio": 95.1,
        "fetch_assets": 82.4,
        "production_total": 140.2,
        "render": 49.4
      }
    }
  ]
}
```

**Caller:** `ProductionOrchestrator.run()` calls `update_metrics_summary()` at the
end of a successful run, using the timing data it collected. This keeps all metrics
logic on the surviving MCP path.

**Impact:** 1 new file (~60 lines), ~5 lines added to `orchestrator.py` to call it.

---

### Change 4: Tests for metrics

**File:** `tests/test_metrics.py` (new file, ~40 lines)

- Unit test: `update_metrics_summary()` creates file if missing, appends runs,
  computes aggregates correctly.
- Unit test: handles corrupt/missing file gracefully.
- Unit test: concurrent writes don't corrupt the file (file-lock or atomic write).

---

## 0.6: Async/Parallel Agent Execution Benchmark

### Change 5: Benchmark script using orchestrator

**File:** `scripts/benchmark_parallel.py` (new file, ~80 lines)

Directly imports and invokes `ProductionOrchestrator.run()` twice on the same
input fixtures -- once with `serial=True`, once with `serial=False`. This avoids
depending on `run_pipeline.py` and exercises the exact code path that survives 1.0.

**Input:** Uses `tests/fixtures/script_package_ww2_tanks.json` (canonical test
fixture) to skip stages 0-3 and focus timing on the parallelizable stages
(audio + image).

```
$ python scripts/benchmark_parallel.py

Mode          | Total (s) | Audio (s) | Image (s) | Speedup
mcp-serial    |    185.3  |     95.1  |     82.4  |    1.0x
mcp-parallel  |    120.8  |     94.2  |     81.9  |    1.53x
```

Reads timing from the `production_report.json` written by each run.

**Requires:** MCP server running (in-process mode) + TTS backend available.

**Impact:** 1 new file (~80 lines). No production code changes.

---

### Change 6: Document benchmark in README

**File:** `README.md`

Add a "Performance" section with:
- Table of serial vs parallel wall-clock times
- Which stages benefit from parallelism (audio + image are independent)
- How to reproduce: `python scripts/benchmark_parallel.py`

**Impact:** ~15 lines in README.

---

## Summary of Changes

| # | File | Type | Lines (est.) | Purpose |
|---|------|------|-------------|---------|
| 1 | `src/mcp/video_agent_server.py` | Edit | +10 | Tool-handler `elapsed_seconds` |
| 2 | `src/orchestrator.py` | Edit | +35 | End-to-end + stage timing, metrics call |
| 3 | `src/metrics.py` | New | ~60 | Rolling `metrics_summary.json` writer |
| 4 | `tests/test_metrics.py` | New | ~40 | Unit tests for metrics |
| 5 | `scripts/benchmark_parallel.py` | New | ~80 | Serial vs parallel benchmark |
| 6 | `README.md` | Edit | +15 | Performance section |

**Total estimated:** ~240 lines of new/changed code across 6 files.
**Zero changes to `run_pipeline.py`** -- all investment is on the MCP path.

---

## Execution Order

1. **Changes 1 + 3 + 4** first -- MCP timing + metrics infrastructure (unit-testable immediately)
2. **Change 2** -- orchestrator collects MCP timings and writes metrics_summary.json
3. **Change 5** -- benchmark script (depends on 1+2 producing timing data)
4. **Change 6** -- README docs (depends on having benchmark numbers)

---

## What This Does NOT Change

- No changes to agent logic, LLM calls, or artifact schemas (other than adding fields)
- No changes to the orchestrator's revision loop logic
- No new dependencies
- No changes to `run_pipeline.py` (doomed for deletion in 1.0)
- `production_report.json` schema is backward-compatible (additive fields, version bump)
- `evaluation.json` is untouched (orchestrator writes `production_report.json` instead)

---

## ROADMAP Updates After Completion

- 0.5 status: Open -> Done
- 0.6 status: Partially Done -> Done
- Tier 0 success checklist: mark metrics_summary + parallel benchmark as complete
