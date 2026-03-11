# MCP HTTPS Server Design — Vibe Insta

**Date:** March 2026
**Prerequisite reading:** [mcp-production-server-plan.md](mcp-production-server-plan.md), [mcp-implementation-plan.md](mcp-implementation-plan.md)
**Goal:** Extend the Phase 3 MCP server design to serve over HTTPS (SSE transport), enabling multi-machine use, external tool access, and recruiter-accessible live demos. This design also deprecates the `stdio` subprocess transport in favour of direct Python imports for local execution.

---

## Transport Comparison: stdio (deprecated) vs SSE vs HTTPS

MCP nominally supports three transport configurations. Two of them are useful here; one is being deprecated.

### stdio — DEPRECATED

The orchestrator spawns each MCP server as a child subprocess. Communication is over stdin/stdout pipes.

```
Orchestrator process
    │  stdin/stdout pipes
    ▼
python -m src.mcp.producer_server   (child process)
```

| Attribute | Details |
|-----------|---------|
| Setup complexity | None — no sockets, no ports, no certs |
| Authentication | None needed — OS process isolation is the security boundary |
| Network required | No — all local |
| Multi-machine | No — orchestrator and server must share a filesystem |
| External clients | No — only the spawning orchestrator can connect |
| Latency | Lowest — IPC, no TCP overhead |
| Server lifetime | Tied to orchestrator — starts and stops with the parent |
| Debugging | Hard — stdout is consumed by the MCP framing; `stderr` only |

**Why deprecated:** The serial debug run and all integration tests already call the MCP tool handlers as direct Python functions (`from src.mcp.producer_server import call_tool`). The `stdio` subprocess wrapper adds a process spawn, an IPC round-trip, and JSON serialization overhead without providing anything that a direct import does not. It is the worst of both worlds: slower than a direct call, less capable than HTTPS. It is removed from the recommended architecture. If a future use case genuinely requires subprocess isolation, `stdio` can be reintroduced on a dedicated branch.

---

### Direct import (replaces stdio for local use)

The orchestrator imports tool handler functions directly. No subprocess, no transport layer.

```python
from src.mcp.producer_server import call_tool   # same handler the HTTPS server uses

result = await call_tool("generate_audio", {...})
```

| Attribute | Details |
|-----------|---------|
| Setup complexity | None |
| Authentication | None — same process |
| Multi-machine | No |
| External clients | No |
| Latency | None — in-process function call |
| Debugging | Full Python debugger / pytest support |
| Best for | Local dev, CI, integration tests, serial debug runs |

This is what the test suite already does. The orchestrator uses this mode when `MCP_TRANSPORT` is not set (or `=local`). No code generation needed — the tool handlers are plain async functions.

---

### SSE (HTTP, no TLS)

The MCP server runs as a long-lived HTTP process. The client connects over plain HTTP using Server-Sent Events for the response stream.

```
Orchestrator / external client
    │  HTTP  POST /messages  (tool call)
    │  HTTP  GET  /sse       (response stream)
    ▼
Starlette app on http://host:port
    ▼
MCP tool handlers
```

| Attribute | Details |
|-----------|---------|
| Setup complexity | Low — run uvicorn, no certs |
| Authentication | Optional — Bearer token if desired; network ACL is common alternative |
| Network required | Yes — TCP socket |
| Multi-machine | Yes — any host that can reach the server IP/port |
| External clients | Yes — Claude Desktop, curl, any HTTP client |
| Latency | Low — TCP overhead only (~1ms local) |
| Server lifetime | Independent — survives orchestrator restart |
| Debugging | Easy — use curl, browser DevTools, Wireshark |
| Best for | LAN-only deployments, dev environment shared between teammates, local demo where HTTPS cert overhead is not worth it |

**Caution:** Plain HTTP means tokens and tool results are unencrypted on the wire. Acceptable on a trusted LAN; not acceptable over the internet or on shared networks.

---

### HTTPS (SSE over TLS)

Same SSE transport, with TLS encryption terminating at the server (or at a reverse proxy like Caddy/nginx in front of it).

```
Orchestrator / external client
    │  HTTPS (TLS 1.2+)  POST /messages
    │  HTTPS              GET  /sse
    ▼
uvicorn with ssl_context  (or Caddy reverse proxy)
    ▼
Starlette app
    ▼
MCP tool handlers
```

| Attribute | Details |
|-----------|---------|
| Setup complexity | Medium — need a cert (self-signed or Let's Encrypt) |
| Authentication | Bearer token required (no network-level isolation) |
| Network required | Yes |
| Multi-machine | Yes |
| External clients | Yes — and safe over the public internet |
| Latency | Low — TLS handshake adds ~1-3ms per new connection; subsequent calls are fast |
| Server lifetime | Independent |
| Debugging | Requires TLS-aware tools (curl `-k`, Wireshark with key log) |
| Best for | Public demo endpoint, cloud deployment, recruiter access, multi-team environments |

---

### Comparison Matrix

| Criterion | ~~stdio~~ (deprecated) | Direct import | SSE (HTTP) | HTTPS |
|-----------|------------------------|---------------|------------|-------|
| Local dev simplicity | — | Best | Good | Acceptable |
| Multi-machine | No | No | Yes | Yes |
| External client access | No | No | LAN only | Yes |
| Wire encryption | N/A (IPC) | N/A (in-process) | None | TLS 1.2+ |
| Auth required | No | No | Recommended | Required |
| Cert management | None | None | None | Required |
| Recruiter demo endpoint | No | No | Risky | Yes |
| CI/CD pipeline use | Yes | Yes | Yes | Yes |
| Debug with breakpoints | No | Yes | Yes | Yes |
| ElevenLabs/Pexels exposure | Local only | Local only | Anyone on LAN | Anyone with token |

### Decision guide

```
Does anything outside this process need to call a tool?
  No  → Direct import (MCP_TRANSPORT=local, default)
  Yes →
    Is this LAN-only with trusted users?
      Yes → SSE (HTTP) — zero cert overhead
      No  → HTTPS — required for internet, external Claude Desktop, recruiter demo
```

For Vibe Insta:
- **Local dev / CI / tests:** Direct import (no transport layer)
- **Recruiter demo / external Claude Desktop access:** HTTPS
- **Trusted LAN team use:** SSE (HTTP) acceptable; HTTPS preferred

---

## Why HTTPS?

The Phase 3 design runs both MCP servers as local subprocesses over `stdio`. This is sufficient for single-machine dev but creates three hard limits:

1. **Single-machine only.** The orchestrator and both servers must run on the same host. No cloud offload, no distributed render farm.
2. **No external tool access.** Claude Desktop, third-party MCP clients, or a recruiter's local Claude instance cannot connect to a server running only over `stdio`.
3. **No demo endpoint.** Recruiter appeal (Tier 0) benefits from a live MCP endpoint that anyone can point a compatible client at and call `check_asset_availability` or `estimate_tts_duration` without cloning the repo.

HTTPS resolves all three. The MCP SDK's SSE transport runs over HTTP; layering TLS on top gives HTTPS. Tool interfaces are **unchanged** — the same `list_tools`/`call_tool` handlers work identically over `stdio` or HTTPS.

---

## Transport Layer: MCP over SSE over HTTPS

MCP supports two standard transports:

| Transport | When to use |
|-----------|-------------|
| `stdio` | Local dev: orchestrator spawns server as subprocess |
| `SSE` (Server-Sent Events) | Network access: server is a long-running HTTP process |

The MCP SDK's SSE server is built on **Starlette**. **FastAPI** extends Starlette, so the MCP SSE transport mounts directly inside a FastAPI app. Running the FastAPI app with **uvicorn** and a TLS certificate adds HTTPS. No custom protocol work required.

```
Client (orchestrator / Claude Desktop)
    │  HTTPS (TLS 1.3)
    │  POST /messages   ← tool call request
    │  GET  /sse        ← streaming response channel
    │  GET  /health     ← liveness probe
    ▼
uvicorn (TLS termination)
    ▼
FastAPI app (extends Starlette — auth middleware + routing)
    ▼
mcp.server.sse.SseServerTransport (mounted sub-app)
    ▼
MCP tool handlers (same async functions the local transport imports directly)
```

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

HTTPS alone does not prevent unauthorized tool calls. Each request must carry a **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <token>
```

Tokens are 32-byte random hex strings stored in `.env` (not committed). FastAPI's `@app.middleware("http")` decorator validates the token before any request reaches the MCP transport. The `/health` endpoint is explicitly exempted so liveness probes do not need a token.

Token is read from env var `MCP_SERVER_TOKEN`. Auth is inlined in `https_server_base.py` — no separate middleware file needed.

---

## Server Implementation

### Shared HTTPS server base

Extract common HTTPS setup to avoid duplication between `producer_server.py` and `screenwriting_server.py`. FastAPI is used instead of raw Starlette — it provides `@app.middleware("http")` for auth, a `/health` endpoint for liveness probes, and `lifespan` for startup/shutdown logging, all with less boilerplate.

**File:** `src/mcp/https_server_base.py`

```python
import ssl
import os
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.sse import SseServerTransport
from .cert_utils import generate_dev_cert

DEFAULT_CERT = Path("certs/server.crt")
DEFAULT_KEY  = Path("certs/server.key")

def build_ssl_context(cert: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx

def build_fastapi_app(mcp_app, server_name: str, token: str) -> FastAPI:
    sse = SseServerTransport("/messages")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print(f"[INFO] {server_name} ready")
        yield
        print(f"[INFO] {server_name} shutting down")

    # docs_url/redoc_url disabled — no public OpenAPI UI on an MCP server.
    app = FastAPI(title=server_name, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def verify_bearer(request: Request, call_next):
        if request.url.path == "/health":           # liveness probe: no auth required
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != token:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "server": server_name}

    @app.get("/sse")
    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_app.run(streams[0], streams[1], mcp_app.create_initialization_options())

    app.mount("/messages", sse.handle_post_message)
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
    ssl_ctx = build_ssl_context(cert, key)
    print(f"[INFO] {server_name} starting on https://{host}:{port}")
    uvicorn.run(fastapi_app, host=host, port=port, ssl=ssl_ctx)
```

### Producer server (HTTPS only)

**File:** `src/mcp/producer_server.py` (extended from Phase 3)

The `stdio` entrypoint (`main_stdio`) is removed. The only entrypoint is HTTPS. Tool handlers remain plain async functions importable directly — this is intentional (supports both the `local` transport mode and tests without any server process).

```python
# No stdio entrypoint. Tool handlers are importable directly for local use.

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert", type=Path, default=DEFAULT_CERT)
    parser.add_argument("--key",  type=Path, default=DEFAULT_KEY)
    args = parser.parse_args()
    run_https_server(app, "producer-server", args.host, args.port, args.cert, args.key)

if __name__ == "__main__":
    main()
```

Run producer server:
```
venv/Scripts/python.exe -m src.mcp.producer_server --port 8443
```

Run screenwriting server:
```
venv/Scripts/python.exe -m src.mcp.screenwriting_server --port 8444
```

---

## Client Setup: Orchestrator Transport Modes

Two modes, selected by `MCP_TRANSPORT` env var:

**File:** `src/orchestrator.py`

```python
import os
from mcp.client.sse import sse_client
from mcp import ClientSession

_TRANSPORT = os.environ.get("MCP_TRANSPORT", "local")  # local | https

async def _call_producer_tool(name: str, arguments: dict) -> dict:
    """Single entry point for all producer tool calls. Transport-agnostic."""
    if _TRANSPORT == "local":
        # Direct import — no subprocess, no network, full debugger support.
        # This is what the test suite already does.
        from src.mcp.producer_server import call_tool
        result = await call_tool(name, arguments)
        return json.loads(result[0].text)

    # HTTPS path — used for external clients and multi-machine deploys.
    base_url  = os.environ["PRODUCER_SERVER_URL"]
    token     = os.environ["MCP_SERVER_TOKEN"]
    ca_bundle = os.environ.get("MCP_CA_BUNDLE")
    headers   = {"Authorization": f"Bearer {token}"}
    async with sse_client(f"{base_url}/sse", headers=headers, verify=ca_bundle or True) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return json.loads(result.content[0].text)

async def run_pipeline(screenplay: dict, run_dir: Path):
    audio_result, image_result = await asyncio.gather(
        _call_producer_tool("generate_audio", {...}),
        _call_producer_tool("fetch_assets",   {...}),
    )
    ...
```

The `stdio_client` import is removed entirely. The `local` path is a direct function call with zero overhead and full debugger support — equivalent to what the integration tests already do.

---

## Configuration

All transport and TLS settings come from environment variables so no code changes are needed to switch modes:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `local` | `local` (direct import) or `https` |
| `PRODUCER_SERVER_URL` | — | Base URL when `MCP_TRANSPORT=https` (e.g. `https://localhost:8443`) |
| `SCREENWRITING_SERVER_URL` | — | Base URL for screenwriting server |
| `MCP_SERVER_TOKEN` | — | Shared Bearer token (required for HTTPS mode) |
| `MCP_CA_BUNDLE` | — | Path to `ca.pem` for self-signed certs; omit for trusted CA |
| `MCP_PRODUCER_PORT` | `8443` | Port for producer server |
| `MCP_SCREENWRITING_PORT` | `8444` | Port for screenwriting server |
| `MCP_HOST` | `0.0.0.0` | Bind address for server processes |

`.env` defaults (no file needed for local dev — `local` transport requires no env vars):

```
# Local dev default — no .env required. Direct import, no server process.
# MCP_TRANSPORT=local

# Set these only when running the HTTPS server:
MCP_TRANSPORT=https
PRODUCER_SERVER_URL=https://localhost:8443
SCREENWRITING_SERVER_URL=https://localhost:8444
MCP_SERVER_TOKEN=<32-byte hex — generate: python -c "import secrets; print(secrets.token_hex(32))">
MCP_CA_BUNDLE=certs/ca.pem   # omit when using a trusted CA cert
```

---

## Claude Desktop / External Client Integration

Once the server runs over HTTPS, any MCP-compatible client can connect. For Claude Desktop:

**`~/.config/claude/claude_desktop_config.json`:**
```json
{
  "mcpServers": {
    "vibe-insta-producer": {
      "url": "https://your-host:8443/sse",
      "headers": {
        "Authorization": "Bearer <MCP_SERVER_TOKEN>"
      }
    },
    "vibe-insta-screenwriting": {
      "url": "https://your-host:8444/sse",
      "headers": {
        "Authorization": "Bearer <MCP_SERVER_TOKEN>"
      }
    }
  }
}
```

This is what enables recruiter demo use: a reviewer with Claude Desktop can call `check_asset_availability` or `estimate_tts_duration` against a live running server without touching the codebase.

---

## Startup Script

**File:** `scripts/start_mcp_servers.py`

Servers always start in HTTPS mode — there is no other networked mode. For local dev, no server process is needed (orchestrator uses direct import).

```python
"""
Start both MCP servers over HTTPS.
Requires MCP_SERVER_TOKEN env var. Certs are auto-generated if absent.

Usage:
    python scripts/start_mcp_servers.py
"""
import subprocess, sys, os
from pathlib import Path

PYTHON = str(Path("venv/Scripts/python.exe"))

def main():
    token = os.environ.get("MCP_SERVER_TOKEN")
    if not token:
        print("[ERROR] Set MCP_SERVER_TOKEN before starting servers")
        sys.exit(1)

    producer = subprocess.Popen([
        PYTHON, "-m", "src.mcp.producer_server",
        "--port", os.environ.get("MCP_PRODUCER_PORT", "8443"),
    ])
    screenwriting = subprocess.Popen([
        PYTHON, "-m", "src.mcp.screenwriting_server",
        "--port", os.environ.get("MCP_SCREENWRITING_PORT", "8444"),
    ])
    print(f"[INFO] Producer server      PID {producer.pid} -> https://localhost:{os.environ.get('MCP_PRODUCER_PORT', '8443')}")
    print(f"[INFO] Screenwriting server PID {screenwriting.pid} -> https://localhost:{os.environ.get('MCP_SCREENWRITING_PORT', '8444')}")
    try:
        producer.wait()
    except KeyboardInterrupt:
        producer.terminate()
        screenwriting.terminate()

if __name__ == "__main__":
    main()
```

---

## New Dependencies

Add to `requirements.txt`:

```
fastapi>=0.111.0        # web framework — extends Starlette; MCP SSE transport mounts directly
uvicorn>=0.29.0         # ASGI server — native TLS ssl_context arg, pairs naturally with FastAPI
trustme>=0.9.0          # dev self-signed cert generation
```

`starlette` is already a transitive dependency of both `mcp` and `fastapi`. `uvicorn[standard]` (C extensions) is not needed — traffic volume does not justify the build dependency.

---

## Security Checklist

- [ ] `MCP_SERVER_TOKEN` is never committed (`.env` is gitignored)
- [ ] `certs/` directory is gitignored (add `certs/` to `.gitignore`)
- [ ] Self-signed CA (`ca.pem`) distributed out-of-band to clients that need it
- [ ] `/health` is the only unauthenticated endpoint — verify no other path bypasses `verify_bearer`
- [ ] TLS 1.2 minimum enforced in `build_ssl_context()` (TLS 1.3 preferred)
- [ ] `BearerTokenMiddleware` is the first middleware in the stack (applied before routing)
- [ ] For public-facing deployments: use Let's Encrypt via `caddy` reverse proxy (no cert management code needed — Caddy handles it)
- [ ] Rate limiting: add `slowapi` middleware if the public endpoint is exposed (Pexels free tier: 200 req/hr)

---

## File Layout After HTTPS Integration

```
src/
  mcp/
    __init__.py
    https_server_base.py      (new — FastAPI app factory + TLS + auth middleware)
    cert_utils.py              (new — dev self-signed cert generation)
    producer_server.py         (Phase 3 + https entrypoint)
    screenwriting_server.py    (Phase 3 + https entrypoint)
certs/                         (gitignored — generated at runtime)
  server.crt
  server.key
  ca.pem
scripts/
  start_mcp_servers.py         (new — dual-mode startup)
docs/
  mcp-https-server-design.md   (this file)
```

---

## Sequenced Work Items

These items layer on top of Phase 3 (MCP server skeleton in `stdio` mode already done):

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| H-1 | `cert_utils.py` — dev cert generation with `trustme` | `src/mcp/cert_utils.py` | 0.5h |
| H-2 | `https_server_base.py` — FastAPI app factory, `verify_bearer` middleware, `/health`, TLS wiring | `src/mcp/https_server_base.py` | 1h |
| H-3 | `producer_server.py` — replace stdio entrypoint with HTTPS `main()` | `src/mcp/producer_server.py` | 0.5h |
| H-4 | `screenwriting_server.py` — same | `src/mcp/screenwriting_server.py` | 0.5h |
| H-5 | `orchestrator.py` — `MCP_TRANSPORT` env switch (`local` / `https`) | `src/orchestrator.py` | 1h |
| H-6 | `scripts/start_mcp_servers.py` | `scripts/` | 0.25h |
| H-7 | `.env.example` with HTTPS vars; add `certs/` to `.gitignore` | `.env.example`, `.gitignore` | 0.25h |
| H-8 | Integration test: start FastAPI app with `TestClient`, call `/health`, call tool via SSE | `tests/integration/test_mcp_https.py` | 2h |

**Total:** ~6h

**Exit criterion:** `python scripts/start_mcp_servers.py --https` starts both servers; `curl -k -H "Authorization: Bearer <token>" https://localhost:8443/sse` returns a valid SSE stream; orchestrator with `MCP_TRANSPORT=https` runs the full pipeline end-to-end; Claude Desktop config connects and lists tools.

---

## What This Is NOT

- Not a change to any tool handler logic. All `call_tool` implementations are transport-agnostic.
- Not a replacement for `stdio` mode. Both modes coexist; `stdio` remains the default for local dev.
- Not a cloud deployment plan. This design covers the server itself; cloud VM provisioning is outside scope.
- Not blocking Phase 3. HTTPS is additive — Phase 3 `stdio` servers are the prerequisite.
