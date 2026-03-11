#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Apply git identity captured by initialize.cmd
# ------------------------------------------------------------------
GITUSER_TMP="$(dirname "$0")/.gituser.tmp"
if [ -f "$GITUSER_TMP" ]; then
  GIT_NAME=$(sed -n '1p' "$GITUSER_TMP")
  GIT_EMAIL=$(sed -n '2p' "$GITUSER_TMP")
  [ -n "$GIT_NAME" ]  && git config --global user.name  "$GIT_NAME"
  [ -n "$GIT_EMAIL" ] && git config --global user.email "$GIT_EMAIL"
  rm -f "$GITUSER_TMP"
fi

# ------------------------------------------------------------------
# Claude Code bypass permissions (container-only, not committed)
# ------------------------------------------------------------------
mkdir -p ~/.claude
if [ ! -f ~/.claude/settings.json ]; then
  echo '{"permissions":{"defaultMode":"bypassPermissions"}}' > ~/.claude/settings.json
fi

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
