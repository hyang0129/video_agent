"""GPU server lifecycle manager for serial execution.

On GPUs with limited VRAM (e.g. 12 GB), the Chatterbox TTS server and
ACE-Step music server cannot run concurrently. This module provides
helpers to start one, use it, stop it, then start the other.

Usage in pipeline:

    mgr = GpuServerManager()
    with mgr.chatterbox():
        # Chatterbox on port 8000, ACE-Step stopped
        audio_timeline = audio_agent.generate_audio_timeline(...)

    with mgr.acestep():
        # ACE-Step on port 8001, Chatterbox stopped
        music = music_agent.select_music(...)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Chatterbox config
# ---------------------------------------------------------------------------
CHATTERBOX_PORT = int(os.getenv("CHATTERBOX_PORT", "8000"))
CHATTERBOX_URL = os.getenv("CHATTERBOX_SERVER_URL", f"http://localhost:{CHATTERBOX_PORT}")
CHATTERBOX_UVICORN = os.getenv(
    "CHATTERBOX_UVICORN", "/workspaces/.venvs/chatterbox/bin/uvicorn"
)
CHATTERBOX_APP_DIR = os.getenv(
    "CHATTERBOX_APP_DIR", "/workspaces/hub/repos/chatterbox"
)
CHATTERBOX_STARTUP_TIMEOUT = 120

# ---------------------------------------------------------------------------
# ACE-Step config
# ---------------------------------------------------------------------------
ACESTEP_PORT = int(os.getenv("ACESTEP_PORT", "8001"))
ACESTEP_URL = os.getenv("ACESTEP_BASE_URL", f"http://localhost:{ACESTEP_PORT}")
ACESTEP_APP_DIR = os.getenv(
    "ACESTEP_APP_DIR", "/workspaces/hub/repos/ace_step_server"
)
# Prefer the venv binary directly; fall back to uv run if the binary is absent.
_ACESTEP_VENV_BIN = os.path.join(ACESTEP_APP_DIR, ".venv", "bin", "acestep-api")
ACESTEP_STARTUP_TIMEOUT = 300  # model download + load can be slow


def _is_healthy(url: str, path: str = "/health") -> bool:
    try:
        r = requests.get(f"{url}{path}", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _wait_healthy(url: str, timeout: int, label: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_healthy(url):
            return True
        time.sleep(2)
    print(f"[WARN] {label} did not become healthy within {timeout}s")
    return False


def _kill_port(port: int) -> None:
    """Kill any process still listening on *port* (catches externally-started servers)."""
    try:
        subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
    except Exception:
        pass


def _stop_proc(proc: Optional[subprocess.Popen], label: str) -> None:
    if proc is None:
        return
    print(f"[INFO] Stopping {label} (pid {proc.pid})...")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    print(f"[OK] {label} stopped")


class GpuServerManager:
    """Manages mutually-exclusive GPU server lifecycles."""

    def __init__(self, log_dir: Optional[str] = None) -> None:
        self._chatterbox_proc: Optional[subprocess.Popen] = None
        self._acestep_proc: Optional[subprocess.Popen] = None
        self._chatterbox_owned: bool = False  # True if we started it
        self._acestep_owned: bool = False
        self._log_dir = log_dir or "/tmp"

    def _open_log(self, name: str):
        path = os.path.join(self._log_dir, f"{name}.log")
        print(f"[INFO] {name} server log: {path}")
        return open(path, "w")

    # ----- Chatterbox -----

    def _can_start_chatterbox(self) -> tuple[bool, str]:
        if not os.path.isfile(CHATTERBOX_UVICORN):
            return False, f"uvicorn not found at {CHATTERBOX_UVICORN}"
        if not os.path.isdir(CHATTERBOX_APP_DIR):
            return False, f"app dir not found at {CHATTERBOX_APP_DIR}"
        if not shutil.which("nvidia-smi"):
            return False, "nvidia-smi not found (GPU required)"
        return True, ""

    def start_chatterbox(self) -> bool:
        ok, reason = self._can_start_chatterbox()
        if not ok:
            print(f"[WARN] Chatterbox auto-start skipped: {reason}")
            return False

        _kill_port(CHATTERBOX_PORT)
        print(f"[INFO] Starting Chatterbox TTS server on port {CHATTERBOX_PORT}...")
        env = os.environ.copy()
        env.setdefault("HF_TOKEN", "offline")
        env.setdefault("HF_HUB_OFFLINE", "1")

        log = self._open_log("chatterbox")
        self._chatterbox_proc = subprocess.Popen(
            [
                CHATTERBOX_UVICORN, "app.main:app",
                "--host", "0.0.0.0",
                "--port", str(CHATTERBOX_PORT),
            ],
            cwd=CHATTERBOX_APP_DIR,
            env=env,
            stdout=log,
            stderr=log,
        )

        if _wait_healthy(CHATTERBOX_URL, CHATTERBOX_STARTUP_TIMEOUT, "Chatterbox"):
            self._chatterbox_owned = True
            time.sleep(15)  # Chatterbox loads model lazily; wait for first-request warmup
            print(f"[OK] Chatterbox TTS server ready at {CHATTERBOX_URL}")
            return True

        _stop_proc(self._chatterbox_proc, "Chatterbox")
        self._chatterbox_proc = None
        return False

    def stop_chatterbox(self) -> None:
        if not self._chatterbox_owned:
            return  # reused external server — don't kill it
        _stop_proc(self._chatterbox_proc, "Chatterbox TTS server")
        self._chatterbox_proc = None
        self._chatterbox_owned = False
        _kill_port(CHATTERBOX_PORT)

    # ----- ACE-Step -----

    def _can_start_acestep(self) -> tuple[bool, str]:
        if not os.path.isdir(ACESTEP_APP_DIR):
            return False, f"app dir not found at {ACESTEP_APP_DIR}"
        if not os.path.isfile(_ACESTEP_VENV_BIN):
            return False, (
                f"acestep-api binary not found at {_ACESTEP_VENV_BIN} "
                f"(run 'uv sync' or 'pip install -e .' in {ACESTEP_APP_DIR})"
            )
        return True, ""

    def start_acestep(self) -> bool:
        ok, reason = self._can_start_acestep()
        if not ok:
            print(f"[WARN] ACE-Step auto-start skipped: {reason}")
            return False

        if _is_healthy(ACESTEP_URL):
            print(f"[INFO] ACE-Step already healthy at {ACESTEP_URL}, reusing")
            self._acestep_proc = None
            self._acestep_owned = False
            return True

        _kill_port(ACESTEP_PORT)
        print(f"[INFO] Starting ACE-Step music server on port {ACESTEP_PORT}...")
        env = os.environ.copy()
        env["ACESTEP_INIT_LLM"] = "false"
        env.pop("VIRTUAL_ENV", None)

        log = self._open_log("acestep")
        self._acestep_proc = subprocess.Popen(
            [
                _ACESTEP_VENV_BIN,
                "--host", "0.0.0.0",
                "--port", str(ACESTEP_PORT),
            ],
            cwd=ACESTEP_APP_DIR,
            env=env,
            stdout=log,
            stderr=log,
        )

        if _wait_healthy(ACESTEP_URL, ACESTEP_STARTUP_TIMEOUT, "ACE-Step"):
            self._acestep_owned = True
            time.sleep(5)  # let model settle after health check passes
            print(f"[OK] ACE-Step music server ready at {ACESTEP_URL}")
            return True

        _stop_proc(self._acestep_proc, "ACE-Step")
        self._acestep_proc = None
        self._acestep_owned = False
        return False

    def stop_acestep(self) -> None:
        # Always free the port/VRAM on teardown — ACE-Step holds ~6 GB even when idle.
        # If we reused an externally-started server (_acestep_owned=False), we still
        # kill it so the GPU is free for the next pipeline stage (e.g. Chatterbox on
        # a second run). The pre-warm benefit is startup time, not perpetual ownership.
        _stop_proc(self._acestep_proc, "ACE-Step music server")
        self._acestep_proc = None
        self._acestep_owned = False
        _kill_port(ACESTEP_PORT)

    # ----- Context managers -----

    @contextmanager
    def chatterbox(self):
        """Context manager: start Chatterbox, yield, stop on exit."""
        started = self.start_chatterbox()
        try:
            yield started
        finally:
            self.stop_chatterbox()

    @contextmanager
    def acestep(self):
        """Context manager: start ACE-Step, yield, stop on exit."""
        started = self.start_acestep()
        try:
            yield started
        finally:
            self.stop_acestep()

    def stop_all(self) -> None:
        """Stop all managed servers."""
        self.stop_chatterbox()
        self.stop_acestep()
