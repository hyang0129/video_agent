# Implementation Plan: 1.0a Complete MCP Tool Coverage

**Branch:** `feat/mcp-full-tool-coverage`
**Goal:** Add 5 missing MCP tools so every pipeline stage is callable via the MCP server.

---

## Current State

The MCP server (`src/mcp/video_agent_server.py`) exposes 10 tools:

| # | Tool | Stage | Category |
|---|------|-------|----------|
| 1 | `generate_concepts` | 2 | Screenwriting |
| 2 | `write_screenplay` | 2 | Screenwriting |
| 3 | `review_feasibility` | 2 | Screenwriting |
| 4 | `revise_scene` | 2 | Screenwriting |
| 5 | `check_asset_availability` | 6 | Production |
| 6 | `estimate_tts_duration` | 4 | Production |
| 7 | `generate_audio` | 4 | Production |
| 8 | `fetch_assets` | 6 | Production |
| 9 | `render_video` | 7+8 | Production |
| 10 | `validate_output` | 9 | Production |

**Missing:** Stages 0 (market research), 1 (fact mining), 2 (direct script generation),
3 (video planning), 5 (music selection).

---

## 5 Tools to Add

### Tool 11: `research_topic`

**Wraps:** `create_agent().research_category_artifacts(category)`

```python
# Input
{"setting": "cheese facts", "max_results": 50}

# Output
{
  "status": "ok",
  "run_id": "mr_2026-03-12_cheese_facts_abc123",
  "topic_brief": {...},
  "topic_brief_path": "results/mr_.../topic_brief_0.json",
  "report_path": "results/mr_.../market_research_report.json"
}
```

**Notes:** This is the heaviest tool -- it calls YouTube API + LLM analysis. The
agent writes its own artifacts to `results/` (its own run_dir, separate from the
production run_dir). The tool returns the top-scored topic brief for downstream use.

**Implementation (~25 lines):**
```python
elif name == "research_topic":
    setting = str(arguments["setting"])
    max_results = int(arguments.get("max_results", 50))

    from ..agent import create_agent
    agent = create_agent()
    result = agent.research_category_artifacts(setting, max_results=max_results)

    topic_brief_paths = result.get("topic_brief_paths") or []
    topic_brief = None
    if topic_brief_paths:
        topic_brief = json.loads(Path(topic_brief_paths[0]).read_text(encoding="utf-8"))

    return _json({
        "status": "ok" if topic_brief else "no_results",
        "run_id": result.get("run_id", ""),
        "topic_brief": topic_brief,
        "topic_brief_path": topic_brief_paths[0] if topic_brief_paths else None,
        "report_path": result.get("report_path", ""),
        "topic_brief_count": len(topic_brief_paths),
    })
```

---

### Tool 12: `mine_facts`

**Wraps:** `FactMiner().mine_top_videos(topic_query, topic_id, subtopic_id, ...)`

```python
# Input
{"topic_query": "cheese facts", "topic_id": "cheese", "subtopic_id": "history", "max_videos": 5}

# Output
{
  "status": "ok",
  "total_facts": 42,
  "videos_found": 5,
  "videos_mined": 4
}
```

**Notes:** Calls YouTube API + caption extraction. Writes to `facts.db`. No run_dir
needed (uses shared DB). The `use_captions` flag defaults to `True`.

**Implementation (~18 lines):**
```python
elif name == "mine_facts":
    topic_query = str(arguments["topic_query"])
    topic_id = str(arguments.get("topic_id", ""))
    subtopic_id = str(arguments.get("subtopic_id", ""))
    max_videos = int(arguments.get("max_videos", 5))
    use_captions = bool(arguments.get("use_captions", True))

    from ..facts.fact_miner import FactMiner
    miner = FactMiner()
    result = miner.mine_top_videos(
        topic_query=topic_query,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        max_videos=max_videos,
        use_captions=use_captions,
    )
    return _json({"status": "ok", **result})
```

---

### Tool 13: `generate_script`

**Wraps:** `create_script_agent().generate_script_package(topic_brief, creative_spec)`

```python
# Input
{"topic_brief": {...}, "creative_spec": {...}}

# Output
{
  "status": "ok",
  "script_package": {...}
}
```

**Notes:** This is the non-screenplay path (direct topic->script). The screenplay
path already exists via `generate_concepts` + `write_screenplay`. This tool covers
the `run_pipeline.py` / `mvp` mode path where `ScriptAgent` generates a script
package directly from a topic brief without the concept/screenplay/review flow.

**Implementation (~14 lines):**
```python
elif name == "generate_script":
    topic_brief = arguments["topic_brief"]
    creative_spec = arguments.get("creative_spec")

    from ..script_agent import create_script_agent
    agent = create_script_agent()
    script_package = agent.generate_script_package(
        topic_brief=topic_brief,
        creative_spec=creative_spec,
    )
    return _json({"status": "ok", "script_package": script_package})
```

---

### Tool 14: `create_video_plan`

**Wraps:** `create_video_agent().create_video_plan(script_package, creative_spec)`

```python
# Input
{"script_package": {...}, "creative_spec": {...}}

# Output
{
  "status": "ok",
  "video_plan": {...}
}
```

**Notes:** Deterministic conversion (no LLM call). Currently called inline by the
`generate_audio` tool when given a screenplay, but not exposed as a standalone tool.
Making it explicit allows the CLI to use it as a discrete pipeline step.

**Implementation (~14 lines):**
```python
elif name == "create_video_plan":
    script_package = arguments["script_package"]
    creative_spec = arguments.get("creative_spec")

    from ..video_agent import create_video_agent
    agent = create_video_agent()
    video_plan = agent.create_video_plan(
        script_package=script_package,
        creative_spec=creative_spec,
    )
    return _json({"status": "ok", "video_plan": video_plan})
```

---

### Tool 15: `select_music`

**Wraps:** `create_music_agent().select_music(audio_timeline)`

```python
# Input
{"audio_timeline": {...}}

# Output
{
  "status": "ok",
  "music_selection": {...}
}
```

**Notes:** Currently a stub (default music file selection, no smart matching).
But the tool interface should be complete so it's ready when smart selection lands.

**Implementation (~10 lines):**
```python
elif name == "select_music":
    audio_timeline = arguments["audio_timeline"]

    from ..music_agent import create_music_agent
    agent = create_music_agent()
    music_selection = agent.select_music(audio_timeline)
    return _json({"status": "ok", "music_selection": music_selection})
```

---

## Changes Summary

### Change 1: Add 5 tool schemas to `list_tools()`

**File:** `src/mcp/video_agent_server.py`

Add 5 `Tool(...)` entries to the `list_tools()` return list, between the existing
screenwriting and production tool groups. Follow the exact pattern of the existing
10 tools.

**Estimated:** ~80 lines (schemas).

---

### Change 2: Add 5 tool handlers to `call_tool()`

**File:** `src/mcp/video_agent_server.py`

Add 5 `elif name == "..."` branches in `call_tool()`. All use lazy imports
(`from ..agent import create_agent`) to avoid import-time side effects.

**Estimated:** ~80 lines (handlers).

Note: `elapsed_seconds` is automatically injected by the existing `_json()` wrapper.

---

### Change 3: Unit tests for new tools

**File:** `tests/test_mcp_new_tools.py` (new, ~120 lines)

Test each tool via `call_tool()` directly (in-process, no server needed):
- `research_topic`: mock `create_agent` to avoid real YouTube API calls
- `mine_facts`: mock `FactMiner` to avoid real YouTube API calls
- `generate_script`: mock `create_script_agent` to avoid LLM calls
- `create_video_plan`: use WW2 tanks fixture (deterministic, no mocking needed)
- `select_music`: use sample audio_timeline fixture (no mocking needed)

Each test verifies: `status == "ok"`, expected output keys present,
`elapsed_seconds` field present.

---

### Change 4: Update E2E test to route all stages through MCP

**File:** `tests/test_mcp_server_full_pipeline.py`

Replace direct Python calls with MCP tool calls for the stages that currently
bypass MCP:
- Lines 145-146: `ConceptAgent()` -> already exists as `generate_concepts` tool (no change needed, this one is already a tool)
- Lines 154-155: `ScreenplayAgent()` -> already exists as `write_screenplay` tool
- Lines 163-164: `ScreenplayReviewer()` -> already exists as `review_feasibility` tool
- Line 178: `script_package_to_video_plan()` -> new `create_video_plan` tool

The E2E test currently calls these as direct Python imports even though 3 of them
already have MCP tools. After this change, every stage goes through `call_tool()`.

**Note:** `research_topic` and `mine_facts` are NOT added to the E2E test -- the
test starts from a fixture topic brief, not from scratch. These tools are tested
in the unit tests (Change 3).

---

## File Impact

| # | File | Type | Lines (est.) |
|---|------|------|-------------|
| 1 | `src/mcp/video_agent_server.py` | Edit | +160 (schemas + handlers) |
| 2 | `tests/test_mcp_new_tools.py` | New | ~120 |
| 3 | `tests/test_mcp_server_full_pipeline.py` | Edit | ~30 lines changed |

**Total:** ~310 lines added/changed. No deletions. No behavioral changes to
existing tools.

---

## Execution Order

1. **Change 1+2** together -- add schemas and handlers (one commit)
2. **Change 3** -- unit tests (same commit or immediately after)
3. **Change 4** -- E2E test update (separate commit, depends on server having the tools)

---

## What Does NOT Change

- Existing 10 tool schemas and handlers (untouched)
- Agent code (`src/*_agent.py`) -- tools wrap, not modify
- Orchestrator -- still only uses `generate_audio` + `fetch_assets` for parallel dispatch
- `main.py` -- still calls some stages directly (cleanup is 1.0b)
- Artifact schemas -- tools return the same dicts the agents already produce
