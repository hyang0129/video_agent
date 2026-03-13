# Implementation Plan: Step 2 — Rename `src/` to `video_agent/`

## Scope

226 import occurrences across 63 Python files. 12 files also contain `sys.path.insert`
hacks that become unnecessary after packaging. 7 deprecated test files contain 40 more
occurrences and require a deletion decision.

Estimated risk: **high** — a missed file causes a silent import error at runtime, not
at rename time. Mitigation is a grep verification gate at the end.

---

## Pre-conditions

- `pyproject.toml` does not need to exist yet for this step, but `git mv` must run
  before any find-replace so git tracks the rename as a rename (not delete + add).
- Working tree is clean (`git status` shows no uncommitted changes).
- Full test suite passes on the current `src/` layout before touching anything.

---

## Decision: deprecated tests

`tests/deprecated/` contains 7 files with 40 `from src.` occurrences. These are
already marked deprecated. **Delete them during this step** rather than updating
them — they represent old pipeline paths that are not part of the current test
suite and updating them would add noise without value.

Confirm the files are not referenced from `pytest.ini`, `pyproject.toml`, or any
CI config before deleting. If `pytest` is configured to collect `tests/deprecated/`
explicitly, update that config too.

---

## Execution order

Order is mandatory. Do not swap steps.

### 1. Delete deprecated tests

```bash
cd /workspaces/hub2/repos/video_agent
git rm -r tests/deprecated/
```

Removes 40 import occurrences from the rename scope.

---

### 2. Rename the package directory

```bash
git mv src video_agent
```

Git records this as a rename, preserving blame history. Do not use `mv` — a plain
move looks like a delete + untracked add and loses history.

After this step `from src.xxx` imports are broken. Do not commit yet.

---

### 3. Update all Python imports

Run a single sed pass across every `.py` file in the repo:

```bash
find . -name "*.py" \
  -not -path "./.git/*" \
  -not -path "./venv/*" \
  -not -path "./.venv/*" \
  exec sed -i \
    -e 's/from src\./from video_agent./g' \
    -e 's/import src\./import video_agent./g' \
    {} +
```

This covers all 63 files in one pass.

**Internal relative imports** inside `video_agent/` itself (e.g., `from .config import X`)
are not affected — they use relative syntax and require no change.

---

### 4. Remove `sys.path` hacks

12 files insert the repo root onto `sys.path` to make `src` importable without
installation. These are now unnecessary. The files are:

```
main.py
run_pipeline.py
run_star_wars_pipeline.py
run_star_wars_auto.py
check_fact_db.py
debug_fact_extraction.py
debug_script_generation.py
examples/generate_sample_video.py
examples/fact_mining_example.py
examples/audio_agent_example.py
scripts/run_full_pipeline.py
scripts/benchmark_parallel.py
```

In each file, remove the block that looks like:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
```

Some files also import `sys` only for this purpose. If `sys` has no other uses in
the file after removing the `sys.path` line, remove the `import sys` too.

---

### 5. Update `video_agent/__init__.py`

The file currently contains only `__version__ = "0.1.0"`. Update it:

```python
"""video_agent — multi-agent AI video content pipeline."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("video-agent")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
```

The full `__all__` export list comes in Step 6. For now this is sufficient.

---

### 6. Update non-Python references

These do not affect runtime but should be updated to avoid confusion:

**Shell scripts / Makefiles** — search for `python src/` or `python -m src`:
```bash
grep -r "python src\|python -m src\|-m src\." --include="*.sh" --include="Makefile" .
```

**Docs** — 14 `.md` files reference `src.` in code examples. Update code blocks
that show import statements. Do not update prose that describes the old layout as
historical context.

```bash
grep -rl "from src\.\|import src\." docs/
```

---

### 7. Verification gate

Do not commit until all three checks pass.

**Check 1 — no remaining `src.` imports:**
```bash
grep -r "from src\.\|import src\." --include="*.py" .
# Must return zero results
```

**Check 2 — package is importable:**
```bash
pip install -e . --quiet
python -c "import video_agent; print(video_agent.__version__)"
# Must print version without error
```

**Check 3 — test suite passes:**
```bash
pytest tests/ -x -q
# Must pass (or match the pre-rename baseline failure count exactly)
```

If any check fails, do not move on. Fix the specific file before re-running.

---

### 8. Commit

Stage and commit as a single atomic change:

```bash
git add -A
git commit -m "rename src/ to video_agent/ for installable package"
```

A single commit keeps the rename + import update together so `git log --follow`
can still trace file history.

---

## Pitfalls

**`from src import something` (bare package import)**
The sed pattern above covers `from src.` (with dot) but not a hypothetical
`from src import X`. Run an additional check:
```bash
grep -r "from src import\|import src$" --include="*.py" .
```

**`conftest.py` path manipulation**
`tests/conftest.py` may have its own `sys.path` insert. Check it separately —
it's the pytest root conftest and behaves differently from scripts.

**IDE / editor caches**
After the rename, IDEs may still show red import errors until they re-index.
This is cosmetic. The verification gate above is the authoritative check.

**`__pycache__` directories**
Git ignores these, but stale `.pyc` files referencing `src.` can cause confusing
errors in the Python process that ran before the rename. Clear them:
```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
```
