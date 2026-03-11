#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Install Python dependencies from the repo
# ------------------------------------------------------------------
pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------
# Verify key tools
# ------------------------------------------------------------------
echo "[INFO] Python: $(python --version)"
echo "[INFO] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "[OK] Dev container ready"
