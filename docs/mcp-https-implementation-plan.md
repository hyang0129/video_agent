# MCP HTTPS Implementation Plan

**Design doc:** [mcp-https-server-design.md](mcp-https-server-design.md)
**Total effort:** ~5h across 5 stages

Each stage ends with a concrete verification step. Do not start the next stage until the current one passes its go/no-go check.

---

## Stage 1 — TLS foundation + health endpoint

**Goal:** HTTPS server starts, `/health` responds over TLS. No MCP protocol yet.

**Files:**
- `src/mcp/cert_utils.py` — new (`trustme` dev cert generation)
- `src/mcp/https_server_base.py` — new (FastAPI app factory, auth middleware, `/health`, `StreamableHTTPSessionManager` wiring, uvicorn entrypoint)
- `certs/` added to `.gitignore`

**Verify:**
```bash
python -c "from src.mcp.https_server_base import run_https_server; print('import ok')"
MCP_SERVER_TOKEN=testtoken python -m src.mcp.https_server_base --port 8443
# in another terminal:
curl -k https://localhost:8443/health
# → {"status":"ok","server":"..."}
curl -k -X POST https://localhost:8443/mcp
# → 401 (no token)
```

**Go/no-go:** `/health` returns 200, unauthenticated POST to `/mcp` returns 401.

---

## Stage 2 — Merged tool server

**Goal:** All 10 tools register correctly on one MCP server; `list_tools` works over HTTPS.

**Files:**
- `src/mcp/video_agent_server.py` — new (merge tools from both former servers, HTTPS `main()`)
- `src/mcp/producer_server.py` — deleted
- `src/mcp/screenwriting_server.py` — deleted
- Update any import paths in non-MCP code that referenced the old servers

**Verify:**
```bash
MCP_SERVER_TOKEN=testtoken python -m src.mcp.video_agent_server --port 8443
```
Use the MCP inspector or a quick client script to call `list_tools` and confirm all 10 names appear. No tool execution needed yet — registration only.

**Go/no-go:** `list_tools` returns exactly 10 tools with correct names and input schemas. Old server files are gone with no import errors elsewhere.

**Tools expected:**

| # | Tool | Former server |
|---|------|--------------|
| 1 | `generate_concepts` | screenwriting_server |
| 2 | `write_screenplay` | screenwriting_server |
| 3 | `review_feasibility` | screenwriting_server |
| 4 | `revise_scene` | screenwriting_server |
| 5 | `check_asset_availability` | producer_server |
| 6 | `estimate_tts_duration` | producer_server |
| 7 | `generate_audio` | producer_server |
| 8 | `fetch_assets` | producer_server |
| 9 | `render_video` | producer_server |
| 10 | `validate_output` | producer_server |

---

## Stage 3 — Orchestrator client

**Goal:** Existing pipeline runs end-to-end through the HTTPS server rather than direct imports.

**Files:**
- `src/orchestrator.py` — update to `streamable_http_client`, `VIDEO_AGENT_SERVER_URL`, `_mcp_session()` context manager

**Key pattern — one TLS connection per pipeline run:**
```python
@asynccontextmanager
async def _mcp_session():
    async with streamable_http_client(f"{base_url}/mcp", headers=headers, verify=_CA_BUNDLE) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield session

async def run_pipeline(...):
    async with _mcp_session() as session:
        # all tool calls go through this one session
```

**Verify:**
```bash
MCP_SERVER_TOKEN=testtoken MCP_VERIFY_SSL=false \
VIDEO_AGENT_SERVER_URL=https://localhost:8443 \
python main.py run --topic "ww2 tanks" --stages script_writing
```
Run the pipeline through at least one real tool call (e.g. `write_screenplay`) and confirm the artifact is written correctly. Optionally add a temporary log line in `_mcp_session` to confirm only one TLS connection is opened per run.

**Go/no-go:** Pipeline stage completes, output artifact written, no `ConnectionError` or TLS error. Human reviews the output artifact for correctness.

---

## Stage 4 — Ops and configuration

**Goal:** Clean startup experience, documented env vars, secrets gitignored, deps pinned.

**Files:**
- `scripts/start_mcp_server.py` — new (single-process launcher)
- `.env.example` — add `VIDEO_AGENT_SERVER_URL`, `MCP_SERVER_TOKEN`, `MCP_VERIFY_SSL`, `MCP_PORT`
- `.gitignore` — add `certs/`, `.env`
- `requirements.txt` — add `fastapi>=0.111.0`, `uvicorn>=0.29.0`, `trustme>=0.9.0`, `httpx>=0.27.0`

**Verify:**
```bash
cp .env.example .env        # fill in a token
python scripts/start_mcp_server.py
# confirm [INFO] line prints and server is reachable

pip install -r requirements.txt   # confirm clean install, no conflicts

git status                  # confirm certs/ and .env do not appear
```

**Go/no-go:** Server starts from the script, deps install cleanly, secrets do not appear in `git status`.

---

## Stage 5 — Integration tests

**Goal:** Automated verification of auth, transport, tool dispatch, and the revision loop.

**Files:**
- `tests/integration/conftest.py` — add session-scoped `mcp_server_url` fixture
- `tests/integration/test_mcp_https.py` — new

**Test cases:**

| # | Test | API keys needed |
|---|------|----------------|
| 1 | `GET /health` → 200, no token required | none |
| 2 | `POST /mcp` without token → 401 | none |
| 3 | `POST /mcp` with wrong token → 401 | none |
| 4 | `list_tools` over HTTPS → 10 tools returned | none |
| 5 | `review_feasibility` with fixture screenplay → valid report | none |
| 6 | Simulated revision loop: mock `tts_failed` → `revise_scene` called | none |

Cases 1–6 must pass without any external API keys (use fixture screenplay from `tests/fixtures/`).

**Verify:**
```bash
pytest tests/integration/test_mcp_https.py -v -s -m integration
```

**Go/no-go:** All 6 test cases green.

---

## Review gates summary

| Stage | What the human reviews | Blocking? |
|-------|----------------------|-----------|
| 1 | curl output — 200 on health, 401 on unauthenticated MCP | Yes |
| 2 | `list_tools` response — all 10 tool names present | Yes |
| 3 | Pipeline output artifact — correctness of generated content | Yes |
| 4 | `git status` + pip install smoke test | Yes |
| 5 | pytest output — all tests green | Yes |

---

## Rollback notes

- **Stages 1–2** are purely additive (new files). Rollback = delete the new files; existing pipeline is untouched.
- **Stage 3** modifies `orchestrator.py`. Keep a copy of the original before editing, or work on a branch. This is the highest-risk change.
- **Stage 4** is configuration-only. Rollback = revert `.env.example`, `.gitignore`, `requirements.txt`.
- **Stage 5** is tests-only. Always safe to revert or skip.
