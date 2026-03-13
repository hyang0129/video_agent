# External Tool Setup

Three optional tools extend the pipeline with real TTS audio, lip-sync animation,
and avatar rendering. The pipeline degrades gracefully without them, but full output
requires all three.

---

## 1. Chatterbox TTS (local GPU voiceover)

**Repo:** `repos/chatterbox` (already cloned in this workspace)

**Requires:** NVIDIA GPU, CUDA 12.8, Python 3.11 venv at `/workspaces/.venvs/chatterbox`

### One-time setup

```bash
# Install dependencies (already done if post-create.sh ran)
source /workspaces/.venvs/chatterbox/bin/activate
cd /workspaces/hub2/repos/chatterbox
pip install -r requirements.txt
```

Model weights are downloaded from HuggingFace on first run and cached in
`~/.cache/huggingface/hub/`.

### Start the server

```bash
cd /workspaces/hub2/repos/chatterbox
source /workspaces/.venvs/chatterbox/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/chatterbox.log 2>&1 &
# Wait ~5s for model to load, then verify:
curl http://localhost:8000/health
```

The pipeline auto-detects a running server via pre-flight check. If it is not
running, it will attempt to auto-start it using `CHATTERBOX_UVICORN`.

### `.env` variables

```
CHATTERBOX_APP_DIR=/workspaces/hub2/repos/chatterbox
CHATTERBOX_UVICORN=/workspaces/.venvs/chatterbox/bin/uvicorn
```

---

## 2. Rhubarb Lip Sync

**Repo:** `/workspaces/rhubarb-lip-sync` (clone separately — see below)

**Requires:** CMake, C++17 compiler, Boost

### Clone and build

```bash
cd /workspaces
git clone https://github.com/DanielSWolf/rhubarb-lip-sync.git
cd rhubarb-lip-sync
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel $(nproc)
```

Binary ends up at `/workspaces/rhubarb-lip-sync/build/rhubarb/rhubarb`.

### `.env` variable

```
RHUBARB_PATH=/workspaces/rhubarb-lip-sync/build/rhubarb/rhubarb
```

**Without this:** `generate_lipsync` returns `status: degraded` and the avatar
uses a silent neutral pose (`X` cue) throughout. The rest of the pipeline still
completes.

---

## 3. Live2D Renderer (`live2d-render`)

**Repo:** `repos/live2d` (already cloned in this workspace)

**Requires:** CMake 3.28+, Ninja, OpenGL/EGL (Mesa or GPU driver)

### Build

```bash
cd /workspaces/hub2/repos/live2d
mkdir -p build && cd build
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja
```

Binary ends up at `/workspaces/hub2/repos/live2d/build/live2d-render`.

The pre-flight check (`run_full_mcp_pipeline.py`) will attempt to run this cmake
build automatically if the repo exists but the binary is missing.

### `.env` variables

```
LIVE2D_RENDER_PATH=/workspaces/hub2/repos/live2d/build/live2d-render
LIVE2D_REPO_ROOT=/workspaces/hub2/repos/live2d
LIVE2D_MODEL_PATH=/workspaces/hub2/repos/live2d/assets/models/majo/majo.model3.json
```

---

## Verify all three

Run the pre-flight check:

```bash
source /workspaces/.venvs/video_agent/bin/activate
cd /workspaces/hub2/repos/video_agent
python scripts/run_full_mcp_pipeline.py 2>&1 | grep -E "^\[OK\]|^\[WARN\]|^\[FATAL\]|Pre-flight"
```

Expected output when all tools are available:

```
[OK] Chatterbox server healthy at http://localhost:8000
[OK] live2d-render binary found: /workspaces/hub2/repos/live2d/build/live2d-render
-- Pre-flight: tool availability --
  (no warnings)
```
