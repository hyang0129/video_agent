# MCP HTTPS Server Design — Vibe Insta

**Date:** March 2026
**Prerequisite reading:** [mcp-production-server-plan.md](mcp-production-server-plan.md), [mcp-implementation-plan.md](mcp-implementation-plan.md)
**Goal:** Extend the Phase 3 MCP server design to serve over HTTPS using the **Streamable HTTP transport**, enabling multi-machine use, external tool access, and recruiter-accessible live demos. This design also deprecates the `stdio` subprocess transport and **merges the two Phase 3 servers (producer + screenwriting) into a single `video_agent_server.py`**.

---

## Transport Model

The transport is always **HTTPS (Streamable HTTP over TLS)**. The only thing that changes between local dev and production is **whether the client verifies the server's certificate**, controlled by the `MCP_VERIFY_SSL` env var.

```
                   Local dev                    Production
                   ─────────────────────────    ─────────────────────────
Server cert:       auto-generated self-signed    Let's Encrypt / trusted CA
Client verify:     MCP_VERIFY_SSL=false          MCP_VERIFY_SSL=true
Token auth:        required (same)               required (same)
Code path:         identical                     identical
```

One implementation, no transport switch logic, tests exercise the same stack as production.

### Why Streamable HTTP, not SSE?

The MCP spec originally used an SSE-based transport (persistent `GET /sse` + separate `POST /messages`). This was deprecated in favour of **Streamable HTTP** because the two-connection SSE model has hard production problems:

- **Load balancers:** the `GET /sse` and `POST /messages` must hit the same backend instance — breaks round-robin and stateless LBs
- **API gateways / reverse proxies:** persistent SSE streams are frequently killed by gateway timeouts; nginx/Caddy require `proxy_buffering off` workarounds
- **Testing:** `TestClient` cannot hold a persistent SSE stream open while simultaneously firing POST requests — requires a real running server for any MCP-level test

Streamable HTTP uses a **single `POST /mcp` endpoint**. The server returns a streaming response (chunked JSON) when the tool call warrants it, or plain JSON for simple responses. Standard HTTP infrastructure handles it without special config.

### Why not a direct-import local mode?

The previous design had a `local` mode that bypassed the network entirely. The **orchestrator** should always go through the HTTP stack — skipping the transport means connection handling, auth middleware, and protocol framing are never exercised locally. Existing stage tests (01–09) test agent classes directly and don't involve the server at all; that continues unchanged.

### Deprecated: stdio

The `stdio` subprocess transport is removed. It offered nothing over a direct import for local use and nothing over HTTPS for networked use. The `sys.stdout = sys.stderr` redirect (a stdio framing workaround in both current servers) is also removed.

### Why one server, not two?

Phase 3 split tools across `producer_server.py` (asset/render tools) and `screenwriting_server.py` (concept/screenplay tools). That split matched the sequential pipeline but works against the MCP pattern.

In an MCP workflow, post-production feedback causes screenplay revisions. When `validate_output` or `generate_audio` returns a failure, the orchestrator needs to call `revise_scene` in the same turn. With two servers the orchestrator must hold two live connections and route between them; the LLM's tool context is fragmented. With one server:

- All 10 tools are visible in a single `list_tools` response — the LLM can plan revision loops without context switching
- The orchestrator manages one connection, one auth token, one cert
- The feedback loop `write_screenplay → generate_audio → [tts_failed] → revise_scene → generate_audio → validate_output` is expressed naturally

The merged server is `src/mcp/video_agent_server.py`. The two existing server files are removed.

---

### Comparison: what changed

| Criterion | ~~stdio~~ | ~~SSE (legacy HTTP transport)~~ | Streamable HTTP local (`verify=False`) | Streamable HTTP production (`verify=True`) |
|-----------|-----------|----------------------------------|----------------------------------------|--------------------------------------------|
| Same code path as prod | No | Partial | **Yes** | Yes |
| Standard HTTP infra compatible | No | No (persistent conn) | **Yes** | Yes |
| Load balancer safe | No | No | **Yes** | Yes |
| Wire encryption | No | No | Yes | Yes |
| Token auth | No | Optional | Required | Required |
| TestClient-testable | No | No | **Yes (non-streaming)** | Yes |
| External clients (Claude Desktop) | No | Yes | Yes | Yes |

### Decision guide

```
Is this a stage test (01-09) or unit test?
  Yes → call agent classes directly (no server needed)
  No  →
    Always use HTTPS + Streamable HTTP.
    MCP_VERIFY_SSL=false  (local dev, self-signed cert auto-generated)
    MCP_VERIFY_SSL=true   (production, trusted CA cert)
```

---

## Why HTTPS?

The Phase 3 design ran two MCP servers as local subprocesses over `stdio`. This was sufficient for single-machine dev but created three hard limits:

1. **Single-machine only.** All server processes had to run on the same host. No cloud offload, no distributed render farm.
2. **No external tool access.** Claude Desktop, third-party MCP clients, or a recruiter's local Claude instance cannot connect to a server running only over `stdio`.
3. **No demo endpoint.** Recruiter appeal (Tier 0) benefits from a live MCP endpoint that anyone can point a compatible client at and call `check_asset_availability` or `estimate_tts_duration` without cloning the repo.

HTTPS resolves all three. Tool interfaces are **unchanged** — the same `list_tools`/`call_tool` handlers work identically over any transport.

---

## Transport Layer: MCP Streamable HTTP over HTTPS

The MCP SDK's Streamable HTTP transport integrates directly with FastAPI/Starlette via a single route handler. Running the FastAPI app with **uvicorn** and a TLS certificate gives HTTPS.

```
Client (orchestrator / Claude Desktop)
    │  HTTPS (TLS 1.3)
    │  POST /mcp    ← all MCP requests (initialize, list_tools, call_tool)
    │  GET  /health ← liveness probe (no auth)
    ▼
uvicorn (TLS termination)
    ▼
FastAPI app (auth middleware + routing)
    ▼
mcp.server.streamable_http (single endpoint handler)
    ▼
MCP tool handlers (@app.list_tools / @app.call_tool — unchanged from Phase 3)
```

Compare to the legacy SSE topology, which required two persistent connections per client session. Streamable HTTP collapses this to one standard POST.

---

## Certificate Strategy

| Environment | Certificate source | Tooling |
|-------------|-------------------|---------|
| Local dev | Self-signed, auto-generated | `trustme` (Python lib) or `mkcert` |
| LAN / team | Self-signed CA, distributed via `ca-bundle.crt` | `mkcert -install` |
| Cloud / public | Let's Encrypt | `certbot` or `caddy` reverse proxy |

For local dev, generate a self-signed cert at server startup if no cert path is configured:

```python
# src/mcp/cert_utils.py
import trustme

def generate_dev_cert(cert_path: Path, key_path: Path) -> None:
    ca = trustme.CA()
    server_cert = ca.issue_cert("localhost", "127.0.0.1")
    ca.cert_pem.write_to_path(str(cert_path.parent / "ca.pem"))
    server_cert.private_key_pem.write_to_path(str(key_path))
    server_cert.cert_chain_pems[0].write_to_path(str(cert_path))
```

For production, point config to cert files issued by Let's Encrypt or a trusted CA (see [Configuration](#configuration) below).

---

## Authentication

Each request must carry a **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are 32-byte random hex strings stored in `.env` (not committed). FastAPI middleware validates the token before any request reaches the MCP transport. The `/health` endpoint is explicitly exempted so liveness probes do not need a token.

Token is read from env var `MCP_SERVER_TOKEN`.

---

## Server Implementation

### Shared HTTPS server base

**File:** `src/mcp/https_server_base.py`

```python
import hmac, os
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from .cert_utils import generate_dev_cert

DEFAULT_CERT = Path("certs/server.crt")
DEFAULT_KEY  = Path("certs/server.key")

def build_fastapi_app(mcp_app, server_name: str, token: str) -> FastAPI:
    # StreamableHTTPSessionManager is the high-level FastAPI integration class.
    # It owns the session lifecycle and exposes handle_request() as an ASGI callable.
    session_manager = StreamableHTTPSessionManager(
        app=mcp_app,
        event_store=None,       # stateless — no resumability needed
        json_response=False,    # streaming responses
        stateless=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with session_manager.run():
            yield
        print(f"[INFO] {server_name} shutting down")

    app = FastAPI(title=server_name, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def verify_bearer(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], token):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "server": server_name}

    # handle_request is an ASGI callable (scope, receive, send) — mount directly
    app.mount("/mcp", app=session_manager.handle_request)
    return app

def run_https_server(mcp_app, server_name: str, host: str, port: int, cert: Path, key: Path) -> None:
    token = os.environ.get("MCP_SERVER_TOKEN")
    if not token:
        raise RuntimeError("[ERROR] MCP_SERVER_TOKEN env var not set")

    if not cert.exists() or not key.exists():
        print(f"[WARN] No cert at {cert}. Generating dev self-signed cert.")
        cert.parent.mkdir(parents=True, exist_ok=True)
        generate_dev_cert(cert, key)
        print("[WARN] Self-signed cert written. Trust certs/ca.pem for local dev.")

    fastapi_app = build_fastapi_app(mcp_app, server_name, token)
    print(f"[INFO] {server_name} starting on https://{host}:{port}")
    # uvicorn takes ssl_certfile/ssl_keyfile directly — no ssl.SSLContext needed
    uvicorn.run(fastapi_app, host=host, port=port,
                ssl_certfile=str(cert), ssl_keyfile=str(key))
```

### Merged server

**File:** `src/mcp/video_agent_server.py`

All 10 tools are registered on a single `Server("video-agent-server")` instance. The `@app.list_tools()` handler returns the combined tool list from both former servers. The `@app.call_tool()` handler dispatches all 10 tool names.

The `main()` stdio entrypoint from both former servers is replaced with a single HTTPS entrypoint. The `sys.stdout = sys.stderr` redirect (stdio framing workaround) is removed from both.

**Tools registered:**

| Source | Tool |
|--------|------|
| (former screenwriting_server) | `generate_concepts` |
| | `write_screenplay` |
| | `review_feasibility` |
| | `revise_scene` |
| (former producer_server) | `check_asset_availability` |
| | `estimate_tts_duration` |
| | `generate_audio` |
| | `fetch_assets` |
| | `render_video` |
| | `validate_output` |

```python
# src/mcp/video_agent_server.py
from mcp.server import Server
from .https_server_base import run_https_server, DEFAULT_CERT, DEFAULT_KEY
from ..screenwriting.concept_agent import ConceptAgent
from ..screenwriting.screenplay_agent import ScreenplayAgent
from ..screenwriting.screenplay_reviewer import ScreenplayReviewer
# ... producer imports ...

app = Server("video-agent-server")

@app.list_tools()
async def list_tools() -> List[Tool]:
    return [
        # screenwriting tools (4)
        Tool(name="generate_concepts", ...),
        Tool(name="write_screenplay", ...),
        Tool(name="review_feasibility", ...),
        Tool(name="revise_scene", ...),
        # production tools (6)
        Tool(name="check_asset_availability", ...),
        Tool(name="estimate_tts_duration", ...),
        Tool(name="generate_audio", ...),
        Tool(name="fetch_assets", ...),
        Tool(name="render_video", ...),
        Tool(name="validate_output", ...),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    # ... dispatch all 10 tools ...

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert", type=Path, default=DEFAULT_CERT)
    parser.add_argument("--key",  type=Path, default=DEFAULT_KEY)
    args = parser.parse_args()
    run_https_server(app, "video-agent-server", args.host, args.port, args.cert, args.key)

if __name__ == "__main__":
    main()
```

---

## Client Setup: Orchestrator

**File:** `src/orchestrator.py`

```python
import os, json
from contextlib import asynccontextmanager
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession

_VERIFY_SSL = os.environ.get("MCP_VERIFY_SSL", "false").lower() == "true"
_CA_BUNDLE  = os.environ.get("MCP_CA_BUNDLE") or _VERIFY_SSL
# False → self-signed cert accepted (local dev)
# True  → system CA store (production)
# path  → private CA bundle

@asynccontextmanager
async def _mcp_session():
    """Hold one TLS connection + MCP session for the duration of a pipeline run.
    Opening a new session per tool call wastes a TLS handshake + MCP initialize
    round-trip on every call — avoid that pattern."""
    base_url = os.environ["VIDEO_AGENT_SERVER_URL"]
    token    = os.environ["MCP_SERVER_TOKEN"]
    headers  = {"Authorization": f"Bearer {token}"}
    async with streamable_http_client(f"{base_url}/mcp", headers=headers, verify=_CA_BUNDLE) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield session

async def run_pipeline(screenplay: dict, run_dir: Path):
    async with _mcp_session() as session:
        # All tools — screenwriting and production — visible on one session.
        # Revision loops need no connection switching:
        audio_result, image_result = await asyncio.gather(
            session.call_tool("generate_audio", {...}),
            session.call_tool("fetch_assets",   {...}),
        )
        if audio_result.content[0].text and json.loads(audio_result.content[0].text).get("error") == "tts_failed":
            screenplay = await session.call_tool("revise_scene", {...})
            audio_result = await session.call_tool("generate_audio", {...})
        ...
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VIDEO_AGENT_SERVER_URL` | — | e.g. `https://localhost:8443` |
| `MCP_SERVER_TOKEN` | — | Shared Bearer token (required) |
| `MCP_VERIFY_SSL` | `false` | `false` = skip cert verification (local/self-signed); `true` = enforce (production) |
| `MCP_CA_BUNDLE` | — | Path to CA bundle for a private CA; overrides `MCP_VERIFY_SSL` |
| `MCP_PORT` | `8443` | Port for the merged server |
| `MCP_HOST` | `0.0.0.0` | Bind address |

`.env` for local dev:

```
VIDEO_AGENT_SERVER_URL=https://localhost:8443
MCP_SERVER_TOKEN=<generate: python -c "import secrets; print(secrets.token_hex(32))">
MCP_VERIFY_SSL=false
```

`.env` for production:

```
VIDEO_AGENT_SERVER_URL=https://your-host:8443
MCP_SERVER_TOKEN=<token>
MCP_VERIFY_SSL=true
# MCP_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt  # only if using a private CA
```

---

## Claude Desktop / External Client Integration

**`~/.config/claude/claude_desktop_config.json`:**
```json
{
  "mcpServers": {
    "vibe-insta": {
      "url": "https://your-host:8443/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_SERVER_TOKEN>"
      }
    }
  }
}
```

One server entry exposes all 10 tools. Note the endpoint is `/mcp` (Streamable HTTP), not `/sse` (legacy SSE). Claude Desktop supports the Streamable HTTP transport as of late 2024.

---

## Startup Script

**File:** `scripts/start_mcp_server.py`

```python
"""
Start the video agent MCP server over HTTPS.
Requires MCP_SERVER_TOKEN env var. Certs are auto-generated if absent.

Usage:
    python scripts/start_mcp_server.py
"""
import subprocess, sys, os
from pathlib import Path

PYTHON = str(Path("venv/Scripts/python.exe"))

def main():
    token = os.environ.get("MCP_SERVER_TOKEN")
    if not token:
        print("[ERROR] Set MCP_SERVER_TOKEN before starting server")
        sys.exit(1)

    port = os.environ.get("MCP_PORT", "8443")
    server = subprocess.Popen([
        PYTHON, "-m", "src.mcp.video_agent_server",
        "--port", port,
    ])
    print(f"[INFO] video-agent-server PID {server.pid} -> https://localhost:{port}/mcp")
    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()

if __name__ == "__main__":
    main()
```

---

## Testing Strategy

### Stage tests (01–09) — unchanged

Existing integration tests call agent classes directly (`AudioAgent`, `ScriptImageRetrievalAgent`, etc.) and are unaffected by the transport change. No server process is needed for these.

### MCP transport tests — session-scoped server fixture

Testing the full MCP stack (auth, protocol framing, tool dispatch over HTTP) requires a running server. Use a **session-scoped** pytest fixture — server startup (~1s) is too expensive to repeat per test, and each tool call creates fresh agent instances so there is no shared mutable state to worry about.

```python
# tests/integration/conftest.py
import threading, time, pytest, uvicorn

@pytest.fixture(scope="session")
def mcp_server_url(tmp_path_factory):
    from src.mcp.https_server_base import build_fastapi_app, generate_dev_cert
    from src.mcp.video_agent_server import app as mcp_app

    cert_dir = tmp_path_factory.mktemp("certs")
    cert, key = cert_dir / "server.crt", cert_dir / "server.key"
    generate_dev_cert(cert, key)

    fastapi_app = build_fastapi_app(mcp_app, "video-agent-server-test", token="test-token")
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=0,
                            ssl_certfile=str(cert), ssl_keyfile=str(key))
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)    # avoid CPU spin while uvicorn binds
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"https://127.0.0.1:{port}"
    server.should_exit = True
```

The test itself uses `streamable_http_client(..., verify=False)` — matching `MCP_VERIFY_SSL=false` exactly.

For `/health` and auth rejection tests, `httpx.AsyncClient(verify=False)` is sufficient without the MCP SDK.

---

## New Dependencies

Add to `requirements.txt`:

```
fastapi>=0.111.0        # web framework — session manager mounts directly as ASGI
uvicorn>=0.29.0         # ASGI server — ssl_certfile/ssl_keyfile for TLS
trustme>=0.9.0          # dev self-signed cert generation
httpx>=0.27.0           # used in MCP transport tests (AsyncClient for /health, auth checks)
```

`starlette` is already a transitive dependency of both `mcp` and `fastapi`. `mcp>=1.0.0` is already in `requirements.txt`.

---

## Security Checklist

- [ ] `MCP_SERVER_TOKEN` is never committed (`.env` is gitignored)
- [ ] `certs/` directory is gitignored
- [ ] Self-signed CA (`ca.pem`) distributed out-of-band to clients that need it
- [ ] `/health` is the only unauthenticated endpoint — verify no other path bypasses `verify_bearer`
- [ ] TLS 1.2 minimum enforced via uvicorn (`ssl_version` param or reverse proxy config; TLS 1.3 preferred)
- [ ] Auth middleware applied before routing (first in stack)
- [ ] For public-facing deployments: use Let's Encrypt via `caddy` reverse proxy
- [ ] Rate limiting: add `slowapi` middleware if public endpoint is exposed (Pexels free tier: 200 req/hr)

---

## File Layout After HTTPS Integration

```
src/
  mcp/
    __init__.py
    https_server_base.py      (new — FastAPI app factory + TLS + auth middleware)
    cert_utils.py             (new — dev self-signed cert generation)
    video_agent_server.py     (new — merged server: all 10 tools + HTTPS main())
    producer_server.py        (removed — tools migrated to video_agent_server.py)
    screenwriting_server.py   (removed — tools migrated to video_agent_server.py)
certs/                        (gitignored — generated at runtime)
  server.crt
  server.key
  ca.pem
scripts/
  start_mcp_server.py         (new — single server start)
tests/
  integration/
    conftest.py               (session-scoped server fixture)
    test_mcp_https.py         (new — transport + auth + tool call tests)
docs/
  mcp-https-server-design.md  (this file)
```

---

## Sequenced Work Items

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| H-1 | `cert_utils.py` — dev cert generation with `trustme` | `src/mcp/cert_utils.py` | 0.5h |
| H-2 | `https_server_base.py` — FastAPI app factory, `verify_bearer` middleware, `/health`, Streamable HTTP wiring | `src/mcp/https_server_base.py` | 1h |
| H-3 | `video_agent_server.py` — merge all 10 tools from both former servers; replace stdio `main()` with HTTPS entrypoint; remove `sys.stdout` redirect from both; delete `producer_server.py` and `screenwriting_server.py` | `src/mcp/video_agent_server.py` | 1h |
| H-4 | `orchestrator.py` — `streamable_http_client` replacing `sse_client`; single `VIDEO_AGENT_SERVER_URL`; session-scoped `_mcp_session()` context manager (one TLS conn per pipeline run) | `src/orchestrator.py` | 0.5h |
| H-5 | `scripts/start_mcp_server.py` — single server start | `scripts/` | 0.25h |
| H-6 | `.env.example` with HTTPS vars (single URL); add `certs/` to `.gitignore` | `.env.example`, `.gitignore` | 0.25h |
| H-7 | Integration test: session-scoped uvicorn fixture, `/health` check, auth rejection, tool call via `streamable_http_client`, cross-domain tool call (e.g. `revise_scene` after `generate_audio` failure) | `tests/integration/test_mcp_https.py`, `conftest.py` | 1.5h |

**Total:** ~5h

**Exit criterion:** `python scripts/start_mcp_server.py` starts the server; `curl -k -H "Authorization: Bearer <token>" https://localhost:8443/health` returns `{"status":"ok","server":"video-agent-server"}`; `curl -k -X POST https://localhost:8443/mcp` without token returns `401`; `list_tools` returns all 10 tools; orchestrator with `MCP_VERIFY_SSL=false` runs the full pipeline end-to-end including a revision loop; Claude Desktop config connects to `/mcp` and lists all tools.

---

## What This Is NOT

- Not a change to any tool handler logic. All `@app.list_tools` / `@app.call_tool` implementations are transport-agnostic.
- Not a cloud deployment plan. This design covers the server itself; cloud VM provisioning is outside scope.
- Not blocking Phase 3. HTTPS is additive — Phase 3 servers are the prerequisite.
