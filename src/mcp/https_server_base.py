"""Shared HTTPS server base for the video-agent MCP server.

Provides:
- build_fastapi_app()  -- FastAPI app with Bearer auth middleware,
                          /health endpoint, and Streamable HTTP MCP mount.
- run_https_server()   -- Blocking uvicorn launcher with TLS.

The /health endpoint is unauthenticated (liveness probe).
All other paths require:  Authorization: Bearer <MCP_SERVER_TOKEN>
"""

from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from .cert_utils import generate_dev_cert

DEFAULT_CERT = Path("certs/server.crt")
DEFAULT_KEY = Path("certs/server.key")


def build_fastapi_app(mcp_app, server_name: str, token: str) -> FastAPI:
    session_manager = StreamableHTTPSessionManager(
        app=mcp_app,
        event_store=None,
        json_response=False,
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

    app.mount("/mcp/", app=session_manager.handle_request)
    return app


def run_https_server(
    mcp_app,
    server_name: str,
    host: str,
    port: int,
    cert: Path,
    key: Path,
) -> None:
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
    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
    )


if __name__ == "__main__":
    import argparse
    from mcp.server import Server

    parser = argparse.ArgumentParser(description="HTTPS base server (health + auth test)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert", type=Path, default=DEFAULT_CERT)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    args = parser.parse_args()

    _stub = Server("https-base-stub")
    run_https_server(_stub, "https-base-stub", args.host, args.port, args.cert, args.key)
