collect_ignore_glob = ["deprecated/*"]

import os
import subprocess
import shutil
import time

import pytest
import requests


CHATTERBOX_PORT = int(os.getenv("CHATTERBOX_PORT", "8000"))
CHATTERBOX_URL = os.getenv("CHATTERBOX_SERVER_URL", f"http://localhost:{CHATTERBOX_PORT}")
CHATTERBOX_UVICORN = "/opt/chatterbox-venv/bin/uvicorn"
CHATTERBOX_APP_DIR = os.path.join(os.path.dirname(__file__), "..", "vendor", "chatterbox")
CHATTERBOX_STARTUP_TIMEOUT = 120  # seconds; model loading can be slow


def _chatterbox_healthy(url: str = CHATTERBOX_URL) -> bool:
    """Return True if the Chatterbox server responds on its docs endpoint."""
    try:
        r = requests.get(f"{url}/docs", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _chatterbox_server():
    """Auto-start the Chatterbox TTS server for the test session if needed.

    Skips silently when:
      - The server is already running (external management).
      - TTS_BACKEND is not chatterbox_server.
      - The uvicorn binary or app directory is missing.
      - No GPU is available (CUDA required for model loading).
    """
    backend = os.getenv("TTS_BACKEND", "chatterbox_server")
    if backend != "chatterbox_server":
        yield
        return

    if _chatterbox_healthy():
        print(f"[INFO] Chatterbox server already running at {CHATTERBOX_URL}")
        yield
        return

    if not os.path.isfile(CHATTERBOX_UVICORN):
        print(f"[WARN] Chatterbox uvicorn not found at {CHATTERBOX_UVICORN}, skipping auto-start")
        yield
        return

    if not os.path.isdir(CHATTERBOX_APP_DIR):
        print(f"[WARN] Chatterbox app dir not found at {CHATTERBOX_APP_DIR}, skipping auto-start")
        yield
        return

    if not shutil.which("nvidia-smi"):
        print("[WARN] nvidia-smi not found, skipping Chatterbox auto-start (GPU required)")
        yield
        return

    print(f"[INFO] Starting Chatterbox TTS server on port {CHATTERBOX_PORT}...")
    env = os.environ.copy()
    # Use cached model weights without requiring a real HuggingFace token.
    # The chatterbox library passes token=os.getenv("HF_TOKEN") or True to
    # snapshot_download; setting HF_TOKEN to a dummy value plus HF_HUB_OFFLINE=1
    # forces it to load from the local cache without hitting the HF API.
    env.setdefault("HF_TOKEN", "offline")
    env.setdefault("HF_HUB_OFFLINE", "1")
    proc = subprocess.Popen(
        [
            CHATTERBOX_UVICORN, "app.main:app",
            "--host", "0.0.0.0",
            "--port", str(CHATTERBOX_PORT),
        ],
        cwd=CHATTERBOX_APP_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    deadline = time.monotonic() + CHATTERBOX_STARTUP_TIMEOUT
    started = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            print(f"[ERROR] Chatterbox server exited early (code {proc.returncode})")
            if output:
                print(output[-2000:])
            break
        if _chatterbox_healthy():
            started = True
            print(f"[OK] Chatterbox TTS server ready at {CHATTERBOX_URL}")
            break
        time.sleep(2)

    if not started:
        print("[WARN] Chatterbox server did not become healthy, tests will use silent fallback")
        proc.terminate()
        proc.wait(timeout=10)
        yield
        return

    yield

    print("[INFO] Shutting down Chatterbox TTS server...")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
