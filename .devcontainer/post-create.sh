#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Clone live2d renderer (main branch, read-only reference copy)
# ------------------------------------------------------------------
LIVE2D_DIR="/workspace/live2d"

if [ ! -d "$LIVE2D_DIR" ]; then
    echo "[INFO] Cloning live2d main branch into $LIVE2D_DIR ..."
    git clone --branch main --single-branch --depth 1 \
        https://github.com/hyang0129/live2d.git "$LIVE2D_DIR"

    # Make the checkout read-only so it stays pristine
    chmod -R a-w "$LIVE2D_DIR"
    echo "[OK] live2d repo cloned and set to read-only"
else
    echo "[SKIP] live2d repo already present at $LIVE2D_DIR"
fi

# ------------------------------------------------------------------
# Verify key tools
# ------------------------------------------------------------------
echo "[INFO] Python: $(python --version)"
echo "[INFO] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
echo "[OK] Dev container ready"
