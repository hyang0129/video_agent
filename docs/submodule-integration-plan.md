# Submodule Integration Plan: chatterbox + live2d

## Context
Two external repos are consumed as dependencies without active development:
- **chatterbox** (https://github.com/hyang0129/chatterbox) — Python TTS package with pyproject.toml; exposes `ChatterboxTurboTTS` API
- **live2d** (https://github.com/hyang0129/live2d) — C++ binary renderer; exposes `live2d-render` and `live2d-inspect` CLI commands

Goal: keep both pinned to upstream commits, updatable on demand, and runnable from within the video_agent project.

## Approach: Git Submodules under `vendor/`

Both repos are added as submodules. Git tracks the exact commit for reproducibility. Updates are explicit and intentional.

### Directory layout after implementation
```
vendor/
  chatterbox/   <- git submodule (python package, pip install from here)
  live2d/       <- git submodule (C++ binary, built via CMake)
```

## Implementation Steps

### 1. Add submodules
```bash
mkdir -p vendor
git submodule add https://github.com/hyang0129/chatterbox vendor/chatterbox
git submodule add https://github.com/hyang0129/live2d vendor/live2d
```
This creates `.gitmodules` and pins each to the current HEAD commit.

### 2. Update requirements.txt
Add chatterbox as a local editable install so it can be imported by the pipeline:
```
# External submodule packages
-e vendor/chatterbox
```
Place this near the top of requirements.txt, above the langchain block.

### 3. Add a Makefile for setup and updates

Create `Makefile` at the project root with targets:
- `make submodules-init` — init and fetch all submodules after a fresh clone
- `make submodules-update` — pull latest from upstream for both
- `make live2d-build` — CMake build of live2d binary (puts `live2d-render`, `live2d-inspect` in `vendor/live2d/build/bin/`)

```makefile
.PHONY: submodules-init submodules-update live2d-build

submodules-init:
	git submodule update --init --recursive

submodules-update:
	git submodule update --remote --merge

live2d-build:
	cmake -S vendor/live2d -B vendor/live2d/build -DCMAKE_BUILD_TYPE=Release
	cmake --build vendor/live2d/build --parallel
```

### 4. Update .gitignore
Add `vendor/live2d/build/` to .gitignore to exclude compiled artifacts:
```
vendor/live2d/build/
```
Do NOT ignore vendor/chatterbox or vendor/live2d themselves — submodule directories must remain tracked.

### 5. Document usage in CLAUDE.md (Key File Locations table)
Add two rows:
| `vendor/chatterbox/` | TTS submodule — Python API (`ChatterboxTurboTTS`) |
| `vendor/live2d/`     | Live2D renderer submodule — CLI: `live2d-render`, `live2d-inspect` |

## Files to Modify
- `requirements.txt` — add `-e vendor/chatterbox`
- `.gitignore` — add `vendor/live2d/build/`
- `CLAUDE.md` — add rows to Key File Locations table
- `Makefile` — new file
- `.gitmodules` — auto-created by `git submodule add`

## Ongoing Update Workflow
```bash
# Pull latest from both upstream repos:
git submodule update --remote --merge

# After updating live2d, rebuild:
make live2d-build

# After updating chatterbox, reinstall:
pip install -e vendor/chatterbox
```

## Verification
1. After `git submodule update --init`, `vendor/chatterbox/` and `vendor/live2d/` are populated.
2. `pip install -e vendor/chatterbox` succeeds; `python -c "from chatterbox.tts_turbo import ChatterboxTurboTTS"` works.
3. `make live2d-build` completes; `vendor/live2d/build/bin/live2d-render --help` runs.
4. `git status` shows `.gitmodules` tracked, no untracked vendor contents.
