# Implementation Plan: Step 8 — Fix `results/` and `.cache/` Paths

## The two problems

### Problem 1: Import-time side effects

`config.py` lines 72–74 run `mkdir()` unconditionally at module import time:

```python
# config.py (current)
PROJECT_ROOT = Path(__file__).parent.parent   # ← problem (see below)
CACHE_DIR = PROJECT_ROOT / ".cache"
RESULTS_DIR = PROJECT_ROOT / "results"
ASSETS_DIR = PROJECT_ROOT / "assets"

CACHE_DIR.mkdir(exist_ok=True)    # ← runs on every import
RESULTS_DIR.mkdir(exist_ok=True)  # ← runs on every import
ASSETS_DIR.mkdir(exist_ok=True)   # ← runs on every import
```

A library must not create directories as a side effect of being imported. The moment
the private repo does `from video_agent import FullPipelineRunner`, it creates three
directories in whatever the current working directory happens to be. This is surprising
and incorrect library behavior.

### Problem 2: `PROJECT_ROOT` points to the wrong place after packaging

Before packaging:
```
video_agent/          ← repo root
└── src/              ← package directory
    └── config.py     ← Path(__file__).parent.parent == repo root ✓
```

After packaging (flat layout):
```
video_agent/          ← repo root
└── video_agent/      ← package directory (renamed from src/)
    └── config.py     ← Path(__file__).parent.parent == repo root ✓ (still works from source)
```

After `pip install` (installed into site-packages):
```
site-packages/
└── video_agent/
    └── config.py     ← Path(__file__).parent.parent == site-packages/ ✗
```

Once installed, `PROJECT_ROOT` resolves to `site-packages/`, which is not a directory
the user owns and is not where results should be written.

---

## Affected files

12 files reference `RESULTS_DIR` or `CACHE_DIR` from `config.py`:

| File | Usage |
|---|---|
| `config.py` | Defines and creates the directories |
| `audio_agent.py` | Default `output_dir` in agent constructor |
| `visual_agent.py` | Default `output_dir` + cache file path |
| `script_image_agent.py` | Default `output_dir` |
| `agent.py` | `ensure_run_dir(RESULTS_DIR, run_id)` |
| `full_pipeline_runner.py` | Default `output_root` |
| `orchestrator.py` | `metrics_path` default |
| `facts/fact_store.py` | SQLite db default path (docstring) |
| `facts/caption_cache.py` | Default cache directory |
| `tools/youtube_tools.py` | YouTube cache directory |
| `artifacts/io.py` | Docstring reference |
| `metrics.py` | `results/metrics_summary.json` path |

---

## Solution: lazy defaults via a runtime resolver

Replace the module-level constants with a resolver function that computes paths
relative to the **caller's working directory** at the time they are first used,
not at import time. Directories are created only when the resolver is first called.

### `config.py` changes

```python
# config.py (after)

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ... (API keys, model config, thresholds — unchanged) ...

# ---------------------------------------------------------------------------
# Runtime paths — resolved lazily, relative to CWD at first use.
# Override with environment variables for production deployments.
# ---------------------------------------------------------------------------

def _resolve_dir(env_var: str, default_name: str) -> Path:
    """Return a Path from env var or CWD/default_name. Creates the dir on first call."""
    raw = os.environ.get(env_var)
    path = Path(raw) if raw else Path.cwd() / default_name
    path.mkdir(parents=True, exist_ok=True)
    return path


# Call these functions where a path is needed. Do not call at module level.
def get_results_dir() -> Path:
    return _resolve_dir("VIDEO_AGENT_RESULTS_DIR", "results")

def get_cache_dir() -> Path:
    return _resolve_dir("VIDEO_AGENT_CACHE_DIR", ".cache")

def get_assets_dir() -> Path:
    return _resolve_dir("VIDEO_AGENT_ASSETS_DIR", "assets")


# Backward-compatible aliases for the transition period.
# These are evaluated lazily (called, not accessed as attributes).
# Remove once all internal callers are updated.
@property
def RESULTS_DIR() -> Path:      # noqa: N802  (uppercase intentional for compat)
    return get_results_dir()

@property
def CACHE_DIR() -> Path:        # noqa: N802
    return get_cache_dir()
```

**Note on the backward-compat aliases:** Module-level `@property` does not work in
Python (properties only work on classes). The transition approach is simpler: keep
`RESULTS_DIR` and `CACHE_DIR` as constants but point them to `Path.cwd()` instead of
`Path(__file__).parent.parent`, and move the `mkdir()` calls into agent constructors
where they belong. See the phased approach below.

---

## Phased approach (lower risk)

Do this in two phases rather than one large change:

### Phase A — Fix the `PROJECT_ROOT` problem (unblock packaging)

Replace the broken `PROJECT_ROOT` derivation with a CWD-based default. This is the
minimum required to make `pip install` not write into `site-packages/`.

```python
# config.py — Phase A change only

# Remove this:
# PROJECT_ROOT = Path(__file__).parent.parent

# Replace path definitions with:
CACHE_DIR = Path(os.environ.get("VIDEO_AGENT_CACHE_DIR", ".cache"))
RESULTS_DIR = Path(os.environ.get("VIDEO_AGENT_RESULTS_DIR", "results"))
ASSETS_DIR = Path(os.environ.get("VIDEO_AGENT_ASSETS_DIR", "assets"))

# Keep mkdir() calls for now — Phase B removes them
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
```

`Path(".cache")` is relative to `os.getcwd()` at import time. This is still an
import-time side effect but it creates dirs in the *right* place. Phase B removes
the side effect entirely.

Phase A is a one-file change, easily verified, and unblocks the rest of the
packaging migration.

### Phase B — Remove import-time side effects (clean library behavior)

Move directory creation out of `config.py` and into each agent's `__init__`:

```python
# audio_agent.py — Phase B change
class AudioGenerationAgent:
    def __init__(self, output_dir=None, ...):
        from video_agent.config import get_results_dir
        self.output_dir = output_dir or (get_results_dir() / f"audio_{uuid.uuid4().hex[:6]}")
        self.output_dir.mkdir(parents=True, exist_ok=True)  # only when agent is constructed
```

Repeat for every agent that uses `RESULTS_DIR` or `CACHE_DIR` as a default.

Remove the `mkdir()` calls from `config.py` entirely once all agents own their own
directory creation.

Phase B can be done as a follow-up after the initial packaging is working.

---

## Environment variable contract

Document these in `README.md` and `pyproject.toml` (under `[project.entry-points]`
or a config section):

| Variable | Default | Purpose |
|---|---|---|
| `VIDEO_AGENT_RESULTS_DIR` | `./results` | Per-run artifact output root |
| `VIDEO_AGENT_CACHE_DIR` | `./.cache` | YouTube captions, image query cache, fact DBs |
| `VIDEO_AGENT_ASSETS_DIR` | `./assets` | Static assets (default music, etc.) |

The private repo sets these to point to its own directories:
```bash
export VIDEO_AGENT_RESULTS_DIR=/path/to/private_repo/results
export VIDEO_AGENT_CACHE_DIR=/path/to/private_repo/.cache
```

---

## Verification

**1. Import does not create directories:**
```bash
cd /tmp
python -c "import video_agent"
ls -la | grep -E "results|\.cache|assets"
# Must show nothing — no directories created
```

**2. Directories are created in the right place when the pipeline runs:**
```bash
cd /tmp/test_workspace
VIDEO_AGENT_RESULTS_DIR=/tmp/test_workspace/results \
    python -c "from video_agent import FullPipelineRunner; r = FullPipelineRunner()"
ls /tmp/test_workspace/results
# Directory should exist now
```

**3. Full test suite still passes:**
```bash
cd /workspaces/hub2/repos/video_agent
pytest tests/ -x -q
```

---

## `DEFAULT_MUSIC_PATH` — related issue

`config.py` also defines:
```python
DEFAULT_MUSIC_PATH = ASSETS_DIR / "music" / "default_music.mp3"
```

After Phase A, `ASSETS_DIR` is `Path("assets")` (relative). `DEFAULT_MUSIC_PATH`
will be `Path("assets/music/default_music.mp3")` — relative to CWD at import time.

This is fine for the running pipeline (CWD is the project root), but fragile for
testing from arbitrary directories. Address in Phase B: make `DEFAULT_MUSIC_PATH`
also env-var configurable or resolve it lazily.
