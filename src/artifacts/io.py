"""Artifact IO utilities.

Artifacts are written to the workspace `results/` directory in a
run-scoped folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import json
import re
import uuid


_slug_re = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Create a filesystem-friendly slug.

    Args:
        value: Arbitrary input string.

    Returns:
        Lowercased slug.
    """
    value = (value or "").strip().lower()
    value = _slug_re.sub("_", value)
    value = value.strip("_")
    return value or "run"


def new_run_id(prefix: str, label: str) -> str:
    """Create a run id like `mr_2026-01-31_scifi_ab12cd`.

    Args:
        prefix: Short prefix (e.g., "mr", "sg").
        label: Human label to include (category/topic).

    Returns:
        Run id string.
    """
    date_str = datetime.now(timezone.utc).date().isoformat()
    short = uuid.uuid4().hex[:6]
    return f"{prefix}_{date_str}_{slugify(label)[:24]}_{short}"


@dataclass(frozen=True)
class ArtifactWriteResult:
    """Metadata about an artifact write."""

    run_id: str
    run_dir: Path


def ensure_run_dir(results_dir: Path, run_id: str) -> Path:
    """Ensure a run directory exists."""
    run_dir = results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_json(path: Path, payload: Any) -> None:
    """Write JSON with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
