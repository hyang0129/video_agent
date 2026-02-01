"""JSON extraction and parsing utilities.

These helpers are used at agent boundaries to make cross-agent artifacts
robust to occasional formatting drift.
"""

from __future__ import annotations

from typing import Any, Optional
import json


def extract_json_object(text: str) -> Optional[str]:
    """Extract the first top-level JSON object from text.

    This is a best-effort extractor for LLM outputs that may accidentally
    include preamble/postamble text or markdown code blocks.

    Args:
        text: Raw text that should contain a JSON object.

    Returns:
        A JSON string representing the first object found, or None.
    """
    if not text:
        return None

    # Remove markdown code blocks if present
    if "```json" in text:
        parts = text.split("```json", 1)
        if len(parts) > 1:
            content = parts[1].split("```", 1)[0].strip()
            if content:
                text = content
    elif "```" in text:
        parts = text.split("```", 1)
        if len(parts) > 1:
            content = parts[1].split("```", 1)[0].strip()
            if content and (content.startswith("{") or content.startswith("[")):
                text = content

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = text[start : end + 1].strip()
    return candidate or None


def safe_json_loads(text: str) -> Any:
    """Parse JSON with a best-effort fallback for LLM formatting drift.

    Args:
        text: A JSON string, or a string containing a JSON object.

    Returns:
        Parsed JSON.

    Raises:
        json.JSONDecodeError: If parsing fails.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        extracted = extract_json_object(text)
        if extracted is None:
            raise
        return json.loads(extracted)
