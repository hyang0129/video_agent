# Converting video_agent to an Installable Python Package

This document covers the full process for converting `video_agent` into a proper
installable Python package, enabling a private commercial repo to depend on it via
`pip install -e ../video_agent` (development) or `pip install git+https://...@v1.x`
(production).

---

## Why this matters

Right now `video_agent` is a runnable project, not a library. A private repo cannot
`import video_agent` — it can only copy code or call the MCP server over HTTP. Making
it an installable package enables:

- Direct subclassing of agents and pipeline runners
- Reuse of artifact schemas and utility functions
- Clean dependency pinning (`video-agent>=1.0,<2.0`)
- Proper versioning and changelogs

---

## Execution sequence

This migration and roadmap item 1.0b (MCP consolidation) are done together.
1.0b runs first — as Step 0 — because it deletes ~14 files and ~2,600 lines that
would otherwise be in the rename scope, and it settles the architecture the public
API must be designed against.

```
Step 0   1.0b MCP consolidation     ← architecture cleanup first
Step 1   Choose layout              ← decided: flat layout
Step 2   Rename src/ → video_agent/ ← smaller scope after 1.0b deletion
Step 3   Add pyproject.toml
Step 4   Single-source version
Step 5   Verify package data
Step 6   Define public API          ← designed against post-1.0b architecture
Step 7   Console script entry point ← main.py settled by 1.0b
Step 8A  Fix paths (unblock install)
Step 9   Update .gitignore
Step 10  Install editable + verify
Step 8B  Remove import-time mkdirs  ← after agent landscape stabilises
Step 11  Tag v1.0.0
```

---

## Step 0: Run 1.0b MCP Consolidation

> **1.0b has its own implementation plan.**
> See [plan-mcp-consolidation.md](plan-mcp-consolidation.md) before starting.

Running 1.0b before packaging has three concrete benefits:

**Reduces rename scope.** 1.0b deletes these files, which are currently in the
Step 2 rename scope:

| File | Lines |
|---|---|
| `run_pipeline.py` | 375 |
| `src/full_pipeline_runner.py` | 238 |
| `run_star_wars_auto.py` | 261 |
| `run_star_wars_pipeline.py` | 561 |
| `scripts/run_full_pipeline.py` | 79 |
| `examples/audio_agent_example.py` | ~20 |
| `examples/fact_mining_example.py` | ~20 |
| `examples/generate_sample_video.py` | ~20 |
| `tests/deprecated/` (7 files) | ~500 |

Doing 1.0b first means the rename touches ~45 files instead of 63, and the
`tests/deprecated/` deletion in the Step 2 plan is already done.

**Settles `main.py`.** 1.0b rewrites `main.py` from 797 lines to ~250 lines as a
thin MCP client CLI. Step 7 (console scripts) is then a small move of a stable
file, not a move of a file mid-refactor.

**Clarifies the public API.** `FullPipelineRunner` (proposed in Step 6 as a public
symbol) is deleted by 1.0b. Running 1.0b first means Step 6 designs the public API
against the final architecture, not a transitional one.

**1.0b phases summary:**
1. Fill 5 missing MCP tool gaps (`research_topic`, `mine_facts`, `generate_script`, `create_video_plan`, `select_music`)
2. Remove dual `use_mcp` branching from `orchestrator.py` (~135 lines)
3. Rewrite `main.py` as thin MCP client CLI (797 → ~250 lines)
4. Delete legacy files and `tests/deprecated/` (~2,074 lines)
5. Update tests (remove `use_mcp=False` paths)
6. Sweep dead imports

---

## Step 0b: Understand the current structure problem

**The biggest pitfall in this migration is the package name.**

All internal imports currently use:
```python
from src.config import Config
from src.agents.audio_agent import AudioAgent
```

The directory is literally called `src/`, which is an ambiguous name that collides with
the common `src/` layout convention (explained below). An installable package cannot be
named `src` — every Python project has a `src/` directory.

**The package must be renamed from `src` to `video_agent`.**

This is the highest-effort step and the one most likely to introduce bugs if rushed.

---

## Step 1: Choose a package layout

Two conventions exist. Choose one before touching any files.

### Option A: Flat layout (recommended for this project)

```
video_agent/           ← repo root
├── video_agent/       ← package directory (renamed from src/)
│   ├── __init__.py
│   ├── config.py
│   ├── agents/
│   └── ...
├── tests/
├── main.py
└── pyproject.toml
```

Pros: Simpler, fewer configuration surprises, most tutorials use this.
Cons: `video_agent/` is importable from the repo root during development even without
installing, which can mask missing package metadata.

### Option B: src layout

```
video_agent/           ← repo root
├── src/
│   └── video_agent/   ← package directory (src/ is a container, not the package)
│       ├── __init__.py
│       ├── config.py
│       └── ...
├── tests/
├── main.py
└── pyproject.toml
```

Pros: Forces proper installation before the package is importable; catches missing
data files and entry points that the flat layout would hide.
Cons: All existing `from src.xxx` imports still break — same rename work required.
IDE path resolution sometimes needs extra config.

**Recommendation: Option A (flat layout).** The src-layout benefit is real but most
valuable on large teams. For a project at this scale the extra complexity is not worth
it.

---

## Step 2: Rename `src/` to `video_agent/`

> **This step has a detailed implementation plan.**
> See [plan-pkg-step2-rename.md](plan-pkg-step2-rename.md) before starting.

226 import occurrences across 63 files, 12 `sys.path` hacks to remove, and a decision
on 7 deprecated test files. The plan covers exact commands, ordering constraints,
a verification gate, and pitfalls.

Summary:
1. Delete `tests/deprecated/` (40 occurrences, already marked deprecated)
2. `git mv src video_agent` (must happen before find-replace)
3. Sed pass: `from src.` → `from video_agent.`, `import src.` → `import video_agent.`
4. Remove all `sys.path.insert` blocks (12 files)
5. Update `video_agent/__init__.py` for `importlib.metadata` version
6. Verify with grep gate + import smoke test + test suite

---

## Step 3: Add `pyproject.toml`

Replace `requirements.txt` as the dependency source of truth. Keep `requirements.txt`
temporarily for backward compatibility (point it at the new file), then remove it once
the private repo is set up.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "video-agent"
version = "0.1.0"
description = "Multi-agent AI video content pipeline"
requires-python = ">=3.10,<3.11"
readme = "README.md"
license = { text = "MIT" }  # or your chosen license

dependencies = [
    "langchain>=0.3.0,<2.0",
    "langchain-community>=0.3.0,<1.0",
    "langchain-core>=0.3.0,<1.0",
    "langchain-google-genai>=2.0.0",
    "langchain-anthropic>=0.3.0",
    "python-dotenv>=1.0.0",
    "google-api-python-client>=2.100.0",
    "google-auth-httplib2>=0.1.1",
    "youtube-transcript-api>=0.6.0",
    "google-auth-oauthlib>=1.1.0",
    "pandas>=2.0.0",
    "requests>=2.31.0",
    "requests-cache>=1.1.0",
    "isodate>=0.6.1",
    "pydantic>=2.0.0",
    "tqdm>=4.66.0",
    "loguru>=0.7.0",
    "elevenlabs>=0.2.0",
    "mcp>=1.0.0",
    "fastapi>=0.111.0",
    "uvicorn>=0.29.0",
    "trustme>=0.9.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
trends = ["pytrends>=4.9.0"]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
]

[project.scripts]
video-agent = "video_agent.main:main"
video-agent-mcp = "video_agent.mcp.video_agent_server:main"

[tool.hatch.build.targets.wheel]
packages = ["video_agent"]

[tool.hatch.build.targets.wheel.force-include]
"video_agent/screenwriting/format_library" = "video_agent/screenwriting/format_library"
```

**Why hatchling?** It is the default build backend for modern Python packaging
(recommended by PyPA), has zero configuration overhead for straightforward packages,
and handles package data discovery correctly without a `MANIFEST.in`. `setuptools` is
also fine if the team is more familiar with it — the migration steps are identical.

---

## Step 4: Single-source the version

The version string must live in exactly one place. Do not duplicate it across
`pyproject.toml` and `__init__.py`.

In `video_agent/__init__.py`:
```python
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("video-agent")
except PackageNotFoundError:
    # Package not installed (running from source without pip install)
    __version__ = "0.0.0.dev"
```

Remove the hardcoded `__version__ = "0.1.0"` line that is currently in `src/__init__.py`.

---

## Step 5: Include package data files

Two directories contain non-Python files that must travel with the package:

- `video_agent/screenwriting/format_library/` — prompt templates (`.txt` or `.json`)
- `creative_spec.example.json` — example config (include as documentation, not runtime data)

Hatchling includes all files tracked by git inside the package directory by default.
Verify with a dry-run build:

```bash
pip install hatchling
python -m hatchling build --dry-run
```

Check the output includes `format_library/` contents. If not, add explicit includes
to the `[tool.hatch.build.targets.wheel.force-include]` section shown above.

**Pitfall:** If format templates are loaded via `open("src/screenwriting/format_library/...")`,
those paths break after installation because installed packages do not live in the
project root. Use `importlib.resources` or `pathlib` relative to `__file__` instead:

```python
# Before (breaks after packaging)
with open("src/screenwriting/format_library/facts.txt") as f:
    ...

# After (works installed or from source)
from pathlib import Path
LIBRARY_DIR = Path(__file__).parent / "screenwriting" / "format_library"
with open(LIBRARY_DIR / "facts.txt") as f:
    ...
```

Search for all `open(` calls that reference `src/` and update them.

---

## Step 6: Define a public API surface

> **This step has a detailed implementation plan.**
> See [plan-pkg-step6-public-api.md](plan-pkg-step6-public-api.md) before starting.
>
> **Depends on Step 0 (1.0b) being complete.** `FullPipelineRunner` is deleted by
> 1.0b and must not be promoted to the public API. Design this step against the
> post-1.0b architecture.

Every symbol exported in `__all__` is a contractual commitment — removing it later
requires a major version bump. The plan covers design criteria for what belongs in the
public API, a proposed initial `__all__` with rationale for each symbol, what to
explicitly keep internal, and how the private repo should import.

Summary of proposed public API (post-1.0b):
- `ProductionOrchestrator` — core extension point (simplified by 1.0b, MCP-only)
- `new_concept`, `new_screenplay`, `screenplay_to_script_package` — artifact constructors
- `new_run_id`, `ensure_run_dir`, `write_json` — artifact I/O utilities
- Agent factory functions — conditionally public, add when needed

Start narrow. The private repo can request promotion of additional symbols.

---

## Step 7: Add console script entry points

> **Depends on Step 0 (1.0b) being complete.** 1.0b rewrites `main.py` from 797
> lines to ~250 lines as a stable MCP client CLI. Move that settled file, not the
> pre-consolidation version.

`main.py` at the repo root is not importable after packaging. Convert it to a proper
entry point (already declared in `pyproject.toml` above).

The function `main.py` calls must be importable from within the package:

```python
# video_agent/main.py  (moved from repo root into the package)
def main():
    ...  # existing CLI logic

if __name__ == "__main__":
    main()
```

Then the root `main.py` can become a thin shim for backward compatibility during
transition:
```python
# main.py (repo root — keep temporarily, delete after transition)
from video_agent.main import main
if __name__ == "__main__":
    main()
```

After packaging, users run `video-agent` (the console script) instead of
`python main.py`.

---

## Step 8: Fix the `results/` and `.cache/` paths

> **This step has a detailed implementation plan.**
> See [plan-pkg-step8-paths.md](plan-pkg-step8-paths.md) before starting.

There are two distinct problems. First, `config.py` calls `mkdir()` at import time —
a side effect that no library should have. Second, `PROJECT_ROOT` is derived from
`Path(__file__).parent.parent` which resolves to `site-packages/` after `pip install`,
not the user's working directory.

The plan covers a two-phase fix: Phase A (unblocks packaging — replace `PROJECT_ROOT`
with CWD-relative paths and add env-var overrides, one-file change) and Phase B
(removes import-time side effects by moving `mkdir()` calls into agent constructors).

Environment variables introduced:

| Variable | Default |
|---|---|
| `VIDEO_AGENT_RESULTS_DIR` | `./results` |
| `VIDEO_AGENT_CACHE_DIR` | `./.cache` |
| `VIDEO_AGENT_ASSETS_DIR` | `./assets` |

---

## Step 9: Update `.gitignore`

After renaming `src/` to `video_agent/`, add packaging artifacts:

```gitignore
# Packaging
dist/
*.egg-info/
video_agent.egg-info/
__pycache__/
*.pyc
```

---

## Step 10: Install in development mode

Once `pyproject.toml` exists and the rename is done:

```bash
# In the video_agent venv (for running its own tests)
source /workspaces/.venvs/video_agent/bin/activate
pip install -e ".[dev]"

# In the private repo's venv (for using video_agent as a dependency)
source /workspaces/.venvs/<private-repo>/bin/activate
pip install -e /workspaces/hub2/repos/video_agent
```

Verify the install:
```python
import video_agent
print(video_agent.__version__)  # should print version without error
from video_agent import ProductionOrchestrator  # should not raise
from video_agent import new_screenplay  # should not raise
```

---

## Step 11: Tag and version for production

Once the private repo is consuming the package:

```bash
# In video_agent repo
git tag v1.0.0
git push origin v1.0.0
```

Private repo `pyproject.toml`:
```toml
[project]
dependencies = [
    "video-agent @ git+https://github.com/org/video_agent@v1.0.0",
]
```

For development, the private repo uses the editable install. For CI and production it
pins to a tag. Never pin to a branch name — branch tips move.

---

## Migration checklist

Work through this in order. Each step should pass the existing test suite before moving
to the next.

**Phase 1 — Architecture cleanup (Step 0)**
- [ ] **1.0b Phase 1** Add 5 missing MCP tools (`research_topic`, `mine_facts`, `generate_script`, `create_video_plan`, `select_music`)
- [ ] **1.0b Phase 2** Remove dual `use_mcp` branching from `orchestrator.py`
- [ ] **1.0b Phase 3** Rewrite `main.py` as thin MCP client CLI (~250 lines)
- [ ] **1.0b Phase 4** Delete legacy files and `tests/deprecated/`
- [ ] **1.0b Phase 5-6** Update tests + sweep dead imports

**Phase 2 — Mechanical packaging (Steps 2–5)**
- [ ] **Rename** `src/` → `video_agent/` (`git mv src video_agent`)
- [ ] **Global import replace** `from src.` → `from video_agent.`, `import src.` → `import video_agent.`
- [ ] **Remove** `sys.path` hacks in scripts and tests
- [ ] **Add** `pyproject.toml`
- [ ] **Single-source** `__version__` via `importlib.metadata`
- [ ] **Fix** hardcoded `open("src/...")` file paths to use `Path(__file__).parent`
- [ ] **Fix** `PROJECT_ROOT` path bug and add env-var overrides (Step 8 Phase A)
- [ ] **Update** `.gitignore`

**Phase 3 — API and polish (Steps 6–11)**
- [ ] **Define** public API in `video_agent/__init__.py` with `__all__` (post-1.0b architecture)
- [ ] **Move** `main.py` logic into `video_agent/main.py`; add console script entry point
- [ ] **Verify** package data (format_library) is included in dry-run build
- [ ] **Remove** import-time `mkdir()` calls from `config.py` (Step 8 Phase B)
- [ ] **Run** full test suite: `pytest tests/`
- [ ] **Install** editable in private repo venv and confirm imports work
- [ ] **Update** `CLAUDE.md` with new import paths and public API boundary
- [ ] **Tag** `v1.0.0`

---

## Common pitfalls summary

| Pitfall | Symptom | Fix |
|---|---|---|
| Package named `src` | `import src` works locally, breaks installed | Rename to `video_agent` |
| Hardcoded `open("src/...")` paths | `FileNotFoundError` after install | Use `Path(__file__).parent` |
| Hardcoded `results/` output paths | Writes to wrong directory when installed | Make configurable via env var |
| `sys.path` manipulation | Works from source, breaks installed | Remove; packaging fixes this |
| `main.py` at repo root not in package | `video-agent` console script fails | Move into `video_agent/main.py` |
| `__version__` duplicated | Drift between metadata and runtime value | Use `importlib.metadata` |
| Exposing too much in `__all__` | Can't refactor internals without breaking private repo | Start narrow, expand deliberately |
| Pinning to branch in production | Private repo unexpectedly breaks on new commits | Always pin to a git tag |
| Format library missing from wheel | `FileNotFoundError` on prompt template load | Verify with `hatchling build --dry-run` |
| Forgetting `requires-python` | Installs on wrong Python, breaks at runtime | Set `requires-python = ">=3.10,<3.11"` |
