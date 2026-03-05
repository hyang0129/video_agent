# LangChain Upgrade Plan: 0.1.20 → 1.x (current stable)

**Status:** Executed (March 2026)
**Branch:** `feat/langchain-upgrade`
**ROADMAP item:** Tier 2.1 (updated from 0.3.x target to 1.x actual current stable)

---

## Context

The project was pinned to `langchain==0.1.20` (released ~2024) to avoid breaking changes.
As of March 2026 the current stable series is **1.x** (~1.2.x). This plan documents the
migration to that series along with updated integration packages.

CLAUDE.md designates this as a Tier 2 item requiring a dedicated migration branch — this
branch is that dedicated branch.

---

## Package Version Changes

| Package | Before | After |
|---|---|---|
| `langchain` | `==0.1.20` | `>=0.3.0,<2.0` |
| `langchain-core` | `==0.1.52` | `>=0.3.0,<1.0` |
| `langchain-community` | `==0.0.38` | `>=0.3.0,<1.0` |
| `langchain-google-genai` | `==1.0.3` | `>=2.0.0` |
| `langchain-anthropic` | `>=0.1.0` | `>=0.3.0` |

---

## Affected Files (Import Changes Only)

All changes are **import-path updates only** — no logic was modified.

### src/agent.py

```python
# BEFORE
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, SystemMessage

# AFTER
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
```

`langchain.agents` (AgentExecutor, create_tool_calling_agent) remains unchanged — still
lives in the `langchain` package in 0.3.x/1.x.

### src/script_agent.py

```python
# BEFORE
from langchain.schema import HumanMessage, SystemMessage

# AFTER
from langchain_core.messages import HumanMessage, SystemMessage
```

### src/facts/fact_miner.py

```python
# BEFORE
from langchain.schema import HumanMessage, SystemMessage

# AFTER
from langchain_core.messages import HumanMessage, SystemMessage
```

### src/tools/youtube_tools.py

```python
# BEFORE
from langchain.tools import tool

# AFTER
from langchain_core.tools import tool
```

---

## Known Risk: langchain-google-genai 2.x constructor change

`langchain-google-genai>=2.0.0` may rename the `google_api_key=` kwarg to `api_key=`
in `ChatGoogleGenerativeAI`. Check `src/config.py:41-46` if the Google provider raises
a `TypeError` on startup. Update the kwarg name there if needed.

---

## Testing

Run only the affected stages (1-3) per the integration testing guide:

```bash
pytest tests/integration/test_stage_01_market_research.py -v
pytest tests/integration/test_stage_02_fact_mining.py -v
pytest tests/integration/test_stage_03_script_writing.py -v
```

Smoke test with real providers:
```bash
python main.py research "WW2 Tanks"
```

Human review of any artifact output that changed is required before merging per the
Human Review Protocol in CLAUDE.md.

---

## Rollback

```bash
git checkout master
```

All changes are isolated to the `feat/langchain-upgrade` branch.
