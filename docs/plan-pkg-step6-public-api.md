# Implementation Plan: Step 6 — Define the Public API Surface

## Pre-condition: Step 0 (1.0b) must be complete

`FullPipelineRunner` is deleted by 1.0b Phase 4. Do not begin this step until 1.0b
is merged. The proposed API below reflects the post-1.0b architecture.

---

## Why this step is high-consequence

The public API is a **contractual commitment**. Every symbol exported in `__all__`
can be imported by the private repo and relied upon. Removing or renaming a public
symbol later requires a major version bump (semver: v1 → v2) and a corresponding
update in the private repo.

The default for any symbol that is *not* listed in `__all__` should be: internal,
subject to change, no compatibility guarantee.

Start narrow. The private repo can always request that something be promoted to
public. Promoting is cheap. Demoting is expensive.

---

## Design criteria for what goes public

A symbol belongs in the public API if **all three** of these are true:

1. The private repo needs to import or subclass it directly (not just call it via MCP)
2. The interface is stable — it is unlikely to change as the pipeline evolves
3. It represents a meaningful extension point (a class to subclass, a schema to reuse,
   or a utility with a clear contract)

Utility functions that are only called inside the pipeline, internal data structures,
and anything LLM-prompt-shaped are **not** good public API candidates — they change
frequently as the pipeline matures.

---

## Proposed public API

### Tier 1 — Core extension points (definitely public)

After 1.0b, the primary extension model shifts. The private repo no longer subclasses
`FullPipelineRunner` (deleted) to build a custom pipeline. Instead it builds its own
MCP orchestrator that calls the public MCP tools alongside its own private tools.

`ProductionOrchestrator` survives 1.0b in a simplified form (MCP-only, no `use_mcp`
flag). It is the right extension point for a private repo that wants to override the
parallel audio+image production stage while reusing the rest of the pipeline.

```python
# video_agent/__init__.py

from video_agent.orchestrator import ProductionOrchestrator
```

**`ProductionOrchestrator`** — coordinates parallel audio + image production via MCP
tool calls. The private repo subclasses this to inject custom production stages (e.g.,
call a private MCP tool before or after `generate_audio`, change parallelism, add
custom revision logic). The `run()` method signature is stable post-1.0b.

**What replaces `FullPipelineRunner` for full pipeline extension?**
The private repo writes its own pipeline runner (not a subclass) that calls the public
MCP tools via `_call_tool_inprocess()` or the HTTPS MCP client, interspersed with
calls to its own private MCP server. This is the cleaner model: explicit composition
over deep inheritance of a 238-line class.

---

### Tier 1 — Artifact constructors (definitely public)

These are the typed JSON schema constructors. The private repo must use the same
artifact shapes as the public pipeline to interoperate.

```python
from video_agent.artifacts.screenplay import (
    new_concept,
    new_screenplay,
    screenplay_to_script_package,
)
from video_agent.artifacts.io import (
    new_run_id,
    ensure_run_dir,
    write_json,
)
```

These are stable — they represent the pipeline's data contract. Any change to an
artifact schema is already a breaking change for the pipeline itself, so the public
API stability promise here adds no additional cost.

---

### Tier 1 — Config (public, but carefully scoped)

```python
from video_agent.config import Config
```

**Do not** export the module-level constants (`RESULTS_DIR`, `CACHE_DIR`, etc.)
directly. After Step 8 these become lazy/configurable, and exporting them as
top-level names would re-introduce the tight coupling. Export only the `Config`
class (or a config-accessor function) so callers go through a controlled interface.

If `config.py` does not yet have a `Config` class (it currently uses module-level
constants), this export can be deferred until Step 8 introduces the class.

---

### Tier 2 — Agent factories (conditionally public)

```python
from video_agent.audio_agent import create_audio_agent
from video_agent.script_agent import create_script_agent
from video_agent.render_agent import create_render_agent
```

Expose the **factory functions**, not the agent classes themselves. Factory functions
have a simpler, more stable interface than the classes. The private repo calls the
factory to get a configured agent rather than constructing the class directly.

If the private repo needs to *subclass* an agent (not just use it), then the class
must also be public. Add it only when that need is confirmed — don't anticipate it.

---

### Not public (internal, subject to change)

| Symbol | Why excluded |
|---|---|
| `screenplay_agent.ScreenplayAgent` | Internal LLM prompt wrapper; prompt changes frequently |
| `concept_agent.ConceptAgent` | Same |
| `video_planner.script_package_to_video_plan` | Internal data transformation |
| `mcp.video_agent_server.*` | MCP server internals; consumed via network, not import |
| `tools.*` | Third-party API wrappers; implementation detail |
| `facts.*` | Fact mining pipeline; internal data layer |
| `metrics.*` | Internal observability; not an extension point |
| `config.RESULTS_DIR`, `config.CACHE_DIR` | Post-Step-8, these become runtime values |
| `creative_spec.py` | Channel-config loader; loaded from file, not imported |

---

## Implementation

### `video_agent/__init__.py` after Step 6

```python
"""video_agent — multi-agent AI video content pipeline."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("video-agent")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

# Public API — stable across minor versions.
# Changes to these symbols require a major version bump.
# FullPipelineRunner is intentionally absent — deleted by 1.0b.
# Private repos build their own pipeline runners using MCP tool composition.
from video_agent.orchestrator import ProductionOrchestrator
from video_agent.artifacts.screenplay import (
    new_concept,
    new_screenplay,
    screenplay_to_script_package,
)
from video_agent.artifacts.io import new_run_id, ensure_run_dir, write_json

__all__ = [
    "__version__",
    # Production orchestration (subclass to customise audio+image stage)
    "ProductionOrchestrator",
    # Artifact constructors
    "new_concept",
    "new_screenplay",
    "screenplay_to_script_package",
    # Artifact I/O
    "new_run_id",
    "ensure_run_dir",
    "write_json",
]
```

---

## How to mark internals

Add a module-level note to files that are intentionally internal so future
contributors don't accidentally promote them:

```python
# video_agent/screenwriting/screenplay_agent.py

# Internal module — not part of the public API.
# Do not import from video_agent.__init__; import directly if needed.
```

This is documentation only, not enforced by Python. Enforcement comes from `__all__`
in `__init__.py` and discipline in the private repo's import style.

---

## How the private repo should import

**Prefer top-level imports for public symbols:**
```python
# Good — uses the public API
from video_agent import FullPipelineRunner, new_screenplay

# Acceptable — direct submodule import for symbols not in __all__
from video_agent.audio_agent import create_audio_agent
```

**Avoid deep internal imports:**
```python
# Fragile — this path may change without a major version bump
from video_agent.screenwriting.screenplay_agent import ScreenplayAgent
```

Document this convention in the private repo's `CLAUDE.md` once it exists.

---

## Deferral option

If `ProductionOrchestrator` is still changing frequently after 1.0b, defer promoting
it to public API until its interface has settled. The private repo can use a direct
submodule import (`from video_agent.orchestrator import ProductionOrchestrator`)
during that period without the stability guarantee — then migrate to the public API
import once it is declared stable.

Artifact constructors and I/O utilities are already stable and can be promoted now.
