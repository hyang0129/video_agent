"""Creative spec loading.

`CreativeSpec` is a stable channel-level configuration shared across agents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import json


def load_creative_spec(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Load a CreativeSpec JSON file.

    Args:
        path: Path to a JSON file, or None.

    Returns:
        Parsed dict if provided and exists, else None.

    Raises:
        ValueError: If the file exists but is not valid JSON.
    """
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return None
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid CreativeSpec JSON: {resolved}") from exc
