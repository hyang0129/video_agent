"""Chatterbox TTS server lifecycle manager.

Provides start/stop/health-check helpers for the Chatterbox TTS server.
Used by tests/conftest.py (pytest auto-start) and scripts that need TTS.

Usage as a context manager:

    with chatterbox_server_context() as url:
        # url is the healthy server URL, or None if launch was skipped/failed
        ...

Usage as explicit start/stop:

    proc = start_chatterbox_server()
    ...
    stop_chatterbox_server(proc)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

CHATTERBOX_PORT = int(os.getenv("CHATTERBOX_PORT", "8000"))
CHATTERBOX_URL = os.getenv("CHATTERBOX_SERVER_URL", f"http://localhost:{CHATTERBOX_PORT}")
CHATTERBOX_UVICORN = os.getenv(
    "CHATTERBOX_UVICORN", ""
)
CHATTERBOX_APP_DIR = os.getenv(
    "CHATTERBOX_APP_DIR", ""
)
CHATTERBOX_STARTUP_TIMEOUT = 120  # seconds; model loading can be slow


def is_healthy(url: str = CHATTERBOX_URL) -> bool:
    """Return True if the Chatterbox server responds."""
    try:
        r = requests.get(f"{url}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def can_autostart() -> dict:
    """Check whether auto-start prerequisites are met.

    Returns a dict with 'ok' (bool) and 'reason' (str) if not ok.
    """
    backend = os.getenv("TTS_BACKEND", "chatterbox_server")
    if backend != "chatterbox_server":
        return {"ok": False, "reason": f"TTS_BACKEND={backend}, not chatterbox_server"}

    if not os.path.isfile(CHATTERBOX_UVICORN):
        return {"ok": False, "reason": f"uvicorn not found at {CHATTERBOX_UVICORN}"}

    if not os.path.isdir(CHATTERBOX_APP_DIR):
        return {"ok": False, "reason": f"app dir not found at {CHATTERBOX_APP_DIR}"}

    if not shutil.which("nvidia-smi"):
        return {"ok": False, "reason": "nvidia-smi not found (GPU required)"}

    return {"ok": True, "reason": ""}


def start_chatterbox_server(
    port: int = CHATTERBOX_PORT,
    timeout_s: int = CHATTERBOX_STARTUP_TIMEOUT,
    url: str = CHATTERBOX_URL,
) -> Optional[subprocess.Popen]:
    """Start the Chatterbox TTS server subprocess.

    Returns the Popen object if started successfully, None if launch was
    skipped (already running, prerequisites missing) or failed.
    """
    if is_healthy(url):
        print(f"[INFO] Chatterbox server already running at {url}")
        return None  # None means "we didn't start it, don't stop it"

    check = can_autostart()
    if not check["ok"]:
        print(f"[WARN] Chatterbox auto-start skipped: {check['reason']}")
        return None

    print(f"[INFO] Starting Chatterbox TTS server on port {port}...")
    env = os.environ.copy()
    env.setdefault("HF_TOKEN", "offline")
    env.setdefault("HF_HUB_OFFLINE", "1")

    proc = subprocess.Popen(
        [
            CHATTERBOX_UVICORN, "app.main:app",
            "--host", "0.0.0.0",
            "--port", str(port),
        ],
        cwd=CHATTERBOX_APP_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    deadline = time.monotonic() + timeout_s
    started = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            print(f"[ERROR] Chatterbox server exited early (code {proc.returncode})")
            if output:
                print(output[-2000:])
            return None
        if is_healthy(url):
            started = True
            print(f"[OK] Chatterbox TTS server ready at {url}")
            break
        time.sleep(2)

    if not started:
        print("[WARN] Chatterbox server did not become healthy, will use silent fallback")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return None

    return proc


def stop_chatterbox_server(proc: Optional[subprocess.Popen]) -> None:
    """Stop a Chatterbox server subprocess (if we started one)."""
    if proc is None:
        return
    print("[INFO] Shutting down Chatterbox TTS server...")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
