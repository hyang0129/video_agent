# Test Standardization Plan

## Goal

Standardize testing around two tiers:

1. **Unit tests** -- one per agent, mocked dependencies, fast, offline, no API keys
2. **Full-pipeline E2E** -- single canonical test via MCP server (`test_mcp_server_full_pipeline.py`), outputs video for human review

## Part 1: Deprecate Legacy Full-Pipeline Tests

Move to `tests/deprecated/`:

| File | Reason |
|------|--------|
| `test_screenwriting_full_pipeline.py` | Full pipeline without MCP |
| `test_settings_pipeline.py` | Multi-setting pipeline without MCP |
| `test_star_wars_full_pipeline_integration.py` | Full pipeline without MCP |
| `test_mcp_serverless_full_pipeline.py` | MCP in-process, not server |
| `test_audio_generation_demo.py` | Overlaps with unit tests |
| `test_audio_generation_integration.py` | Overlaps with unit tests |

**Canonical E2E (kept):** `tests/test_mcp_server_full_pipeline.py`

**Untouched:** Stage-based integration tests (`tests/integration/test_stage_*.py`) and MCP tool tests serve a different purpose (isolated stage validation with fixtures).

## Part 2: New Unit Tests

| File to create | Agent under test | Key coverage |
|---------------|-----------------|-------------|
| `test_market_research_agent.py` | `src/agent.py` | Agent creation, topic scoring, artifact export |
| `test_script_agent.py` | `src/script_agent.py` | Script generation (mocked LLM), beat validation, fact grounding |
| `test_video_planner.py` | `src/video_planner.py` | Input validation, scene generation, timestamp contiguity |
| `test_music_agent.py` | `src/music_agent.py` | Default selection, duration probing, volume normalization |
| `test_fact_miner.py` | `src/facts/fact_miner.py` | Fact extraction (mocked LLM), dedup, scoring |
| `test_concept_agent.py` | `src/screenwriting/concept_agent.py` | Concept generation (mocked LLM), hook strength scoring |
| `test_screenplay_agent.py` | `src/screenwriting/screenplay_agent.py` | Screenplay generation (mocked LLM) |
| `test_screenplay_reviewer.py` | `src/screenwriting/screenplay_reviewer.py` | Review logic (mocked LLM) |

## Part 3: Beef Up Thin Unit Tests

| File | Current | Add |
|------|---------|-----|
| `test_composition_agent.py` | 1 test | Error handling, multi-scene specs, music integration |
| `test_visual_agent.py` | 1 test | Manifest structure, placeholder fallback, multi-scene |

## Part 4: Config and Docs

- Update `pytest.ini` with `deprecated` marker
- Update `docs/integration-testing.md` to reflect two-tier strategy
- Add `tests/deprecated/README.md`

## Running Tests

```bash
# Unit tests (fast, offline)
pytest tests/test_*.py -v --ignore=tests/deprecated/ -k "not integration"

# Full pipeline E2E (requires API keys + MCP server)
pytest tests/test_mcp_server_full_pipeline.py -v -s

# Verify collection excludes deprecated
pytest tests/ -v --ignore=tests/deprecated/ --collect-only
```
