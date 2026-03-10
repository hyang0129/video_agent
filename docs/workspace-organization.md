# Workspace Organization — Vibe Insta

**Status:** Design — Pending Implementation
**Date:** March 2026
**Relates to:** [mcp-architecture-upgrade.md](mcp-architecture-upgrade.md), [mcp-production-server-plan.md](mcp-production-server-plan.md)

---

## Problem with the Current Layout

The pipeline currently writes all output into `results/<run_id>/`. This conflates three
distinct concerns:

- **Per-run artifacts** — screenplay, audio, images, final video for a single execution
- **Project-level state** — the working set for "cheese video #2" across multiple runs
- **Shared state** — facts databases and avatar models that are reused across projects

The result is that:
- `facts.db` is buried in `results/` with no clear owner
- "Cheese video #2" cannot easily reference cheese video #1's facts
- The orchestrator has no concept of which project it is currently serving
- Each run folder is ephemeral; there is no durable project identity

---

## Workspace Concept

A **workspace** is the durable home for a single content project. It spans multiple
pipeline runs (initial generation, revisions, re-renders) and holds all project-specific
artifacts.

**Shared assets** live outside any workspace, in a common directory referenced by all
projects that need them.

### Directory layout

```
workspaces/
  cheese/
    workspace.json              # project identity and metadata
    runs/
      v1_2026-03-08_f77975/     # immutable run snapshot
        screenplay.json
        script_package.json
        video_plan.json
        audio/
        images/
        final_video.mp4
        evaluation.json
        scene_results.json
      v2_2026-03-09_e25190/     # revision run, same project
        ...

shared/
  facts/
    cheese.db                   # reusable across cheese v1, v2, v3
    ww2_tanks.db
  avatars/                      # avatar models (when avatar narration is supported)
  asset_cache/                  # Pexels images keyed by content hash
```

### workspace.json

```json
{
  "project_slug": "cheese",
  "topic": "history of cheese",
  "created_at": "2026-03-08T10:00:00Z",
  "runs": [
    { "run_id": "v1_2026-03-08_f77975", "status": "complete" },
    { "run_id": "v2_2026-03-09_e25190", "status": "complete" }
  ],
  "shared_refs": {
    "facts_db": "shared/facts/cheese.db"
  }
}
```

---

## Workspace Object in Code

Agents and the orchestrator receive a `Workspace` object rather than a bare `run_dir`
path. This makes the project context explicit and the shared-asset boundary enforced.

```python
@dataclass
class Workspace:
    project_slug: str       # "cheese", "ww2_tanks"
    workspace_dir: Path     # workspaces/cheese/
    run_dir: Path           # workspaces/cheese/runs/v2_.../
    shared_dir: Path        # shared/

    @property
    def facts_db(self) -> Path:
        return self.shared_dir / "facts" / f"{self.project_slug}.db"

    @property
    def avatars_dir(self) -> Path:
        return self.shared_dir / "avatars"

    @property
    def asset_cache_dir(self) -> Path:
        return self.shared_dir / "asset_cache"
```

The orchestrator signature changes from:

```python
def run(self, run_dir: Path, screenplay, script_package, ...)
```

to:

```python
def run(self, workspace: Workspace, screenplay, script_package, ...)
```

All agents that currently accept `output_dir` receive `workspace.run_dir` for
per-run output and `workspace.facts_db` (or other shared refs) for shared state.

---

## "Current Project" Tracking

The orchestrator itself is stateless — it does not own the concept of which project
is active. That is a **caller/CLI concern**.

Two supported patterns:

### 1. Explicit at invocation (default, recommended)

```bash
python main.py produce --project cheese --run v2
```

The CLI constructs the `Workspace` object from the slug and passes it into the
orchestrator. No ambient state required.

### 2. Active project pointer (for interactive / scripted use)

```json
// workspaces/active_project.json
{
  "project": "cheese",
  "run": "v2_2026-03-09_e25190"
}
```

The CLI reads this file when no `--project` flag is given. Updated on each invocation.
Easy to inspect, easy to override.

---

## MCP Alignment

MCP defines **roots** as the filesystem boundaries a server should operate within.
The client declares roots at session initialization:

```json
{
  "roots": [
    { "uri": "file:///workspaces/cheese/", "name": "project" },
    { "uri": "file:///shared/",            "name": "shared"  }
  ]
}
```

This maps exactly onto the `Workspace` object:

| `Workspace` field | MCP root |
|---|---|
| `workspace_dir` | Root #1 — project scope |
| `shared_dir`    | Root #2 — shared scope  |

The `Workspace` design should be kept roots-compatible so that when persistent
MCP sessions are adopted the mapping is trivial.

---

## MCP Server Lifecycle — Current Approach

Full MCP lifecycle management (persistent servers, roots negotiation) is deferred.
The current non-persistent approach is retained with one change: instead of passing
`run_dir` as a raw string argument on every tool call, tools accept a **workspace
context block**.

### Workspace context block (tool argument)

```json
{
  "workspace": {
    "project_slug": "cheese",
    "workspace_dir": "/workspaces/cheese",
    "run_dir": "/workspaces/cheese/runs/v2_2026-03-09_e25190",
    "shared_dir": "/shared"
  }
}
```

Every tool that previously took `run_dir: str` will accept `workspace: object`
instead. The server extracts `workspace["run_dir"]` for per-run output and
`workspace["shared_dir"]` for shared state. This is a direct drop-in replacement
that keeps the non-persistent server model intact while establishing the structural
convention that roots-based sessions will formalize later.

### Tool signature example

Before:
```json
{ "run_dir": "/absolute/results/run_xyz", "screenplay": {...} }
```

After:
```json
{
  "workspace": {
    "project_slug": "cheese",
    "workspace_dir": "/workspaces/cheese",
    "run_dir": "/workspaces/cheese/runs/v2_2026-03-09_e25190",
    "shared_dir": "/shared"
  },
  "screenplay": { ... }
}
```

### What deferred lifecycle management will add

When persistent servers are adopted, the workspace context block is removed from
tool arguments and replaced by roots declared at session init. Tool calls become
purely logical (content and IDs only, no filesystem paths). Artifacts are exposed
as MCP resources rather than returned as inline JSON blobs. The `Workspace`
dataclass maps directly onto the two declared roots.

The non-persistent server model is a staging step, not a dead end.

---

## Migration from `results/`

| Current path | New path |
|---|---|
| `results/<run_id>/` | `workspaces/<project>/runs/<run_id>/` |
| `results/facts.db` | `shared/facts/<project_slug>.db` |
| `results/metrics_summary.json` | `shared/metrics_summary.json` |
| _(no concept)_ | `workspaces/<project>/workspace.json` |
| _(no concept)_ | `workspaces/active_project.json` |

The `results/` directory is retired. Gitignore rules update from `results/*/` to
`workspaces/*/runs/` and `shared/facts/` (facts databases are generated, not
committed). `workspace.json` files are committed — they are project metadata, not
generated artifacts.

---

## Implementation Order

1. Add `src/workspace.py` — `Workspace` dataclass and `load_workspace()` factory
2. Update `main.py` CLI — `--project` / `--run` flags, active project pointer
3. Update `ProductionOrchestrator.run()` — accept `Workspace` instead of `run_dir`
4. Update MCP tool schemas — replace `run_dir: str` with `workspace: object`
5. Update MCP tool implementations — extract paths from workspace context block
6. Migrate `facts.db` handling to `workspace.facts_db`
7. Update gitignore and directory scaffolding scripts
