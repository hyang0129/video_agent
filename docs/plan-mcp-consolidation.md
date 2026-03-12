# Implementation Plan: Consolidate onto MCP-Only Pipeline (Roadmap 1.0)

**Branch:** `feat/mcp-consolidation`
**Goal:** Single execution path (MCP) for all pipeline modes. Remove all legacy
direct-agent orchestration code.

---

## Design Principle

After consolidation, every pipeline invocation follows one path:

```
CLI (main.py) -> orchestrator.py -> MCP tool handlers (video_agent_server.py) -> agents
```

Agent code (`src/*_agent.py`) is **untouched**. Only the wiring above the agents changes.

---

## MCP Tool Coverage Gaps

Before deleting legacy paths, the MCP server must cover all pipeline stages.
Currently missing:

| Gap | Current state | Action |
|-----|--------------|--------|
| Market research (stage 0) | Only in `main.py` direct calls | Add `research_topic` tool to MCP server |
| Fact mining (stage 1) | Only in `run_pipeline.py` | Add `mine_facts` tool to MCP server |
| Music selection (stage 5) | Only in `main.py`/`run_pipeline.py` | Add `select_music` tool to MCP server |
| Video planning (stage 3) | Derived inline inside tools | Add `create_video_plan` tool to MCP server |
| Script generation (stage 2) | Partially covered (screenplay path only) | Add `generate_script` tool for direct topic->script |

These are thin wrappers (~15-25 lines each) around existing agent factories -- the
same pattern as the 10 tools already implemented.

---

## Phase 1: Fill MCP Tool Gaps (~5 new tools)

**File:** `src/mcp/video_agent_server.py`

Add tools:

### 1. `research_topic`
```python
# Wraps create_agent().research_category_artifacts(setting)
# Input: {"setting": "cheese facts"}
# Output: {"status": "ok", "topic_brief": {...}, "topic_brief_path": "..."}
```

### 2. `mine_facts`
```python
# Wraps FactMiner().mine_top_videos(...)
# Input: {"topic_query": "...", "topic_id": "...", "subtopic_id": "...", "max_videos": 5}
# Output: {"status": "ok", "total_facts": 42}
```

### 3. `generate_script`
```python
# Wraps create_script_agent().generate_script_package(topic_brief, creative_spec)
# Input: {"topic_brief": {...}, "creative_spec": {...}}
# Output: {"status": "ok", "script_package": {...}}
```

### 4. `create_video_plan`
```python
# Wraps create_video_agent().create_video_plan(script_package, creative_spec)
# Input: {"script_package": {...}, "creative_spec": {...}}
# Output: {"status": "ok", "video_plan": {...}}
```

### 5. `select_music`
```python
# Wraps create_music_agent().select_music(audio_timeline)
# Input: {"audio_timeline": {...}}
# Output: {"status": "ok", "music_selection": {...}}
```

All 5 tools follow the existing pattern: parse args, call agent factory, return
JSON result with `elapsed_seconds` (already injected by the `_json()` wrapper).

**Estimated:** ~120 lines total (5 tools x ~24 lines avg).

**Test:** Add tool-level unit tests for each new tool in `tests/test_mcp_tools.py`.

---

## Phase 2: Refactor `orchestrator.py` -- Remove Direct-Agent Paths

**File:** `src/orchestrator.py` (578 lines -> ~440 lines)

### Delete:
- `_produce_parallel()` (lines 192-221) -- direct agent parallel execution
- `_produce_serial()` (lines 224-257) -- direct agent serial execution
- `use_mcp` parameter and all `if use_mcp: ... else:` branching in `run()`
- Direct-agent instantiation (`create_audio_agent`, `ScriptImageRetrievalAgent`)
  inside `run()`
- `TTS_BACKEND` import and `chatterbox_direct` guard (MCP server handles backend
  selection internally)

### Keep:
- `_produce_parallel_mcp()` -- rename to `_produce_parallel()`
- `_produce_serial_mcp()` -- rename to `_produce_serial()`
- `_call_tool_inprocess()` -- MCP in-process dispatch
- `_mcp_session()` -- MCP HTTPS session (for remote server mode)
- `ProductionOrchestrator.run()` -- simplified, always MCP
- Revision loop logic (unchanged)
- Metrics/timing instrumentation (just landed)

### Resulting `run()` signature:
```python
def run(
    self,
    screenplay: Dict[str, Any],
    script_package: Dict[str, Any],
    video_plan: Dict[str, Any],
    run_dir: Path,
    screenplay_agent: Any,
    voice: str = "narrator",
    serial: bool = False,          # kept (debug/deterministic mode)
    # use_mcp: REMOVED -- always MCP
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
```

**Estimated removal:** ~135 lines (direct-agent functions + branching).

---

## Phase 3: Rewrite `main.py` as Thin MCP Client CLI

**File:** `main.py` (797 lines -> ~250 lines)

### Delete all modes except:
- `preflight` -- keep (env check utility)
- `screenplay` -- keep but refactor to use MCP tools instead of direct agent calls

### Delete these modes entirely:
- `example1`, `example2`, `example3` (~30 lines) -- interactive demos, not pipeline
- `interactive` (~1 line dispatcher) -- unused interactive chat mode
- `script` (lines 203-229) -- superseded by `generate_script` MCP tool
- `videoplan` (lines 230-253) -- superseded by `create_video_plan` MCP tool
- `visualmanifest` (lines 254-272) -- superseded by `fetch_assets` MCP tool
- `scriptimages` (lines 273-301) -- superseded by `fetch_assets` MCP tool
- `audio` (lines 302-329) -- superseded by `generate_audio` MCP tool
- `mvp` (lines 330-404) -- superseded by screenplay mode
- `mvp_offline` (lines 405-472) -- superseded by screenplay mode
- `music` (lines 473-497) -- superseded by `select_music` MCP tool
- `renderspec` (lines 498-527) -- superseded by `render_video` MCP tool
- `render` (lines 528-579) -- superseded by `render_video` MCP tool

### Refactored `screenplay` mode (the one surviving pipeline mode):
Replace direct-agent calls (lines 715-756) with MCP tool calls:

```python
# Before (direct):
video_agent = create_video_agent()
video_plan = video_agent.create_video_plan(script_package)

# After (MCP):
result = await _call_tool_inprocess("create_video_plan", {"script_package": script_package})
video_plan = result["video_plan"]
```

The screenplay's concept generation + review + selection logic (lines 630-703)
stays -- it's user-interactive and doesn't need MCP wrapping.

### New: add `pipeline` mode as the primary CLI entry point:
```
python main.py pipeline <topicbrief.json> [--engine ffmpeg|dry_run] [--serial]
```

Runs: research -> facts -> script -> videoplan -> audio+image (orchestrator) ->
music -> render -> validate. All via MCP tools.

### Use `argparse` instead of manual `sys.argv` parsing.

**Estimated:** ~250 lines (down from 797).

---

## Phase 4: Delete Legacy Files

| File | Lines | Reason |
|------|-------|--------|
| `run_pipeline.py` | 375 | Fully superseded by MCP pipeline mode |
| `src/full_pipeline_runner.py` | 238 | Configuration-driven runner, never used by MCP |
| `run_star_wars_auto.py` | 261 | Research demo script, no MCP |
| `run_star_wars_pipeline.py` | 561 | Hybrid research+production, superseded |
| `scripts/run_full_pipeline.py` | 79 | Wrapper around FullPipelineRunner |
| `examples/audio_agent_example.py` | ~20 | Direct-agent example |
| `examples/fact_mining_example.py` | ~20 | Direct-agent example |
| `examples/generate_sample_video.py` | ~20 | Direct-agent example |
| `tests/deprecated/*` (7 files) | ~500 | Already marked deprecated |

**Total deletion:** ~2,074 lines.

---

## Phase 5: Update Tests

### Keep as-is (test agent logic, not execution path):
- `tests/test_*_agent.py` (13 files) -- agent unit tests are independent of
  execution path
- `tests/test_orchestrator.py` -- update to remove `use_mcp=False` test paths
- `tests/test_mcp_server_full_pipeline.py` -- already tests the MCP path

### Update:
- `tests/test_orchestrator.py` -- remove direct-mode tests, add MCP-only mode tests
- Any test that passes `use_mcp=False` to the orchestrator

### Delete:
- `tests/deprecated/` -- 7 already-deprecated test files

---

## Phase 6: Cleanup Imports and Dead Code

After phases 1-5, sweep for:
- Unused imports in `main.py` (direct agent factories no longer needed)
- `use_mcp` references anywhere in the codebase
- `full_pipeline_runner` references
- `run_pipeline` references in docs or scripts

---

## Execution Order

```
Phase 1 (fill gaps)    -- lowest risk, additive only, unblocks everything
Phase 2 (orchestrator) -- medium risk, has test coverage
Phase 3 (main.py)      -- medium risk, careful CLI migration
Phase 4 (delete files) -- zero risk after phases 1-3 pass tests
Phase 5 (tests)        -- cleanup
Phase 6 (imports)      -- cleanup
```

Phases 1+2 can be done together in one commit. Phase 3 is a separate commit
(biggest behavior change). Phase 4+5+6 are one final cleanup commit.

---

## What Does NOT Change

- **Agent code:** All `src/*_agent.py` files are untouched. Agents are invoked
  by MCP tool handlers exactly as they are today.
- **MCP server:** Existing 10 tools unchanged. 5 new tools added.
- **Artifact schemas:** All JSON artifacts remain identical.
- **Test fixtures:** `tests/fixtures/` unchanged.
- **Metrics:** `src/metrics.py` and timing instrumentation (just landed) stay.
- **Vendor submodules:** `vendor/chatterbox`, `vendor/live2d` untouched.

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Missing MCP tool coverage for edge case | Medium | Phase 1 adds all missing tools before any deletion |
| `screenplay` mode breaks during refactor | Medium | Keep old `main.py` on a backup branch until E2E passes |
| Orchestrator tests fail after removing direct paths | Low | Tests already cover MCP path; direct-path tests are removed, not broken |
| External scripts depend on deleted files | Low | Search for imports/references before deletion |

---

## Success Criteria

- [ ] Zero `use_mcp` branching remains in codebase
- [ ] `main.py` is a CLI client, not an agent orchestrator (~250 lines)
- [ ] All 15 MCP tools (10 existing + 5 new) have test coverage
- [ ] `python main.py pipeline <topic_brief.json> --engine ffmpeg` works end-to-end
- [ ] `python main.py screenplay <topic_brief.json> --auto-select ffmpeg` works
- [ ] `tests/test_orchestrator.py` and `tests/test_mcp_server_full_pipeline.py` pass
- [ ] Net LOC reduction: ~1,500+ lines removed

---

## Line Count Summary

| Category | Before | After | Delta |
|----------|--------|-------|-------|
| `main.py` | 797 | ~250 | -547 |
| `src/orchestrator.py` | 578 | ~440 | -138 |
| `src/mcp/video_agent_server.py` | 760 | ~880 | +120 |
| Deleted files (8) | 1,574 | 0 | -1,574 |
| Deprecated tests (7) | ~500 | 0 | -500 |
| **Net** | | | **~-2,639** |
