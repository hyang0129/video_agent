"""Rolling metrics summary for pipeline runs.

Appends per-run timing and status data to results/metrics_summary.json,
maintaining aggregate counters (total runs, success rate, avg duration).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def update_metrics_summary(
    metrics_path: Path,
    run_id: str,
    run_duration_s: float,
    stage_timings: Dict[str, float],
    passed: bool,
    mode: str = "mcp-parallel",
) -> Dict[str, Any]:
    """Append a run entry to the rolling metrics summary and recompute aggregates.

    Creates the file if it does not exist. Handles corrupt/missing files
    gracefully by starting fresh.

    Returns the full updated summary dict.
    """
    summary = _load_or_init(metrics_path)

    entry: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(run_duration_s, 2),
        "passed": passed,
        "mode": mode,
        "stage_timings": {k: round(v, 2) for k, v in stage_timings.items()},
    }

    summary["runs"].append(entry)
    summary["total_runs"] = len(summary["runs"])
    summary["successful_runs"] = sum(1 for r in summary["runs"] if r.get("passed"))

    durations = [r["duration_s"] for r in summary["runs"] if r.get("duration_s")]
    summary["avg_pipeline_duration_s"] = (
        round(sum(durations) / len(durations), 2) if durations else 0.0
    )

    _atomic_write(metrics_path, summary)
    return summary


def _load_or_init(path: Path) -> Dict[str, Any]:
    """Load existing metrics summary or return a blank one."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("runs"), list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "schema_version": "1.0.0",
        "total_runs": 0,
        "successful_runs": 0,
        "avg_pipeline_duration_s": 0.0,
        "runs": [],
    }


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically via a temp file to avoid corruption on crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
