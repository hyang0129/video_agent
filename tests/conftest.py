collect_ignore_glob = ["deprecated/*"]

import pytest

from video_agent.tools.chatterbox_server_manager import (
    start_chatterbox_server,
    stop_chatterbox_server,
)


@pytest.fixture(scope="session", autouse=True)
def _chatterbox_server():
    """Auto-start the Chatterbox TTS server for the test session if needed.

    Skips silently when:
      - The server is already running (external management).
      - TTS_BACKEND is not chatterbox_server.
      - The uvicorn binary or app directory is missing.
      - No GPU is available (CUDA required for model loading).
    """
    proc = start_chatterbox_server()
    yield
    stop_chatterbox_server(proc)
