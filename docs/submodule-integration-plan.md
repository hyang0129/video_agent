# Vendor Integration Plan: chatterbox + live2d

## Context
Two external repos are consumed as dependencies without active development:
- **chatterbox** (https://github.com/hyang0129/chatterbox) — Python TTS package; exposes `ChatterboxTurboTTS` API
- **live2d** (https://github.com/hyang0129/live2d) — C++ binary renderer; exposes `live2d-render` and `live2d-inspect` CLI commands

Goal: keep both pinned/accessible, updatable on demand, and runnable from within the video_agent project.

## Directory layout
```
vendor/
  chatterbox/   <- bind-mounted from host (NOT a submodule)
  live2d/       <- git submodule (C++ binary, built via CMake)
```

---

## live2d — Git Submodule (already done)

live2d is a git submodule under `vendor/live2d/`. Already configured in `.gitmodules`.

```bash
# Init after fresh clone:
git submodule update --init --recursive

# Update to latest upstream:
git submodule update --remote --merge

# Build:
make live2d-build
```

---

## chatterbox — Bind Mount (separate venv)

### Why not a submodule?
Chatterbox already exists as a standalone repo on the dev machine at
`C:\Users\HongM\Code Projects\chatterbox\`. A bind mount avoids duplicating the clone
and lets edits on the host reflect immediately in the container.

### Why a separate venv?
Chatterbox requires PyTorch+CUDA (~2GB+). Video_agent uses LangChain. Installing both
in one venv risks dependency conflicts and bloats the base environment. A dedicated venv
at `/opt/chatterbox-venv` keeps them isolated.

### Implementation

#### 1. `.devcontainer/devcontainer.json` — Add bind mount

```json
"mounts": [
  "source=${localEnv:USERPROFILE}/Code Projects/chatterbox,target=/workspaces/video_agent/vendor/chatterbox,type=bind,consistency=cached"
]
```

`${localEnv:USERPROFILE}` resolves to the Windows user home (e.g. `C:\Users\HongM`).

#### 2. `.devcontainer/post-create.sh` — Create chatterbox venv

After the video_agent pip install block, add:

```bash
# ------------------------------------------------------------------
# Chatterbox: separate venv to isolate PyTorch deps
# ------------------------------------------------------------------
CHATTERBOX_DIR="/workspaces/video_agent/vendor/chatterbox"
CHATTERBOX_VENV="/opt/chatterbox-venv"
if [ -d "$CHATTERBOX_DIR" ]; then
  python -m venv "$CHATTERBOX_VENV"
  "$CHATTERBOX_VENV/bin/pip" install --no-cache-dir -r "$CHATTERBOX_DIR/requirements.txt"
  "$CHATTERBOX_VENV/bin/pip" install --no-cache-dir -e "$CHATTERBOX_DIR"
  echo "[OK] Chatterbox venv ready at $CHATTERBOX_VENV"
else
  echo "[WARN] Chatterbox not mounted at $CHATTERBOX_DIR -- skipping"
fi
```

#### 3. `.gitignore` — Exclude bind-mounted directory

```
vendor/chatterbox/
```

Since chatterbox is a bind mount (not a submodule), git must not track it.

### Usage

Start the chatterbox FastAPI server (run from `vendor/chatterbox/`):
```bash
cd /workspaces/video_agent/vendor/chatterbox
/opt/chatterbox-venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Import in a script using the chatterbox venv:
```bash
/opt/chatterbox-venv/bin/python -c "from chatterbox.tts_turbo import ChatterboxTurboTTS; print('OK')"
```

---

## Files Modified
- `.devcontainer/devcontainer.json` — add `mounts` array
- `.devcontainer/post-create.sh` — add chatterbox venv setup block
- `.gitignore` — add `vendor/chatterbox/`

## Verification
1. Rebuild devcontainer (`Dev Containers: Rebuild Container`)
2. Confirm mount: `ls /workspaces/video_agent/vendor/chatterbox/`
3. Confirm chatterbox venv: `/opt/chatterbox-venv/bin/python -c "import chatterbox; print('OK')"`
4. Confirm video_agent venv unaffected: `python -c "import langchain; print('OK')"`
5. Confirm `git status` doesn't show `vendor/chatterbox` as untracked
