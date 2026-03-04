"""Shared helpers for stage integration tests."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_fixture(name: str) -> Dict[str, Any]:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def review_dir(stage: str) -> Path:
    root = PROJECT_ROOT / "results" / "test" / "stages"
    return root / f"{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def copy_to_review(src: Path, stage: str) -> Path:
    dest = review_dir(stage)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return dest
