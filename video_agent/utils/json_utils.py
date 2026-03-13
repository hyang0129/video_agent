"""JSON extraction and parsing utilities.

These helpers are used at agent boundaries to make cross-agent artifacts
robust to occasional formatting drift.
"""

from __future__ import annotations

from typing import Any, Optional
import json


def extract_json_object(text: str) -> Optional[str]:
    """Extract the first top-level JSON object or array from text.

    This is a best-effort extractor for LLM outputs that may accidentally
    include preamble/postamble text or markdown code blocks.

    Args:
        text: Raw text that should contain JSON.

    Returns:
        A JSON string representing the first object/array found, or None.
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

    # Try to find JSON object
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    
    # Try to find JSON array
    start_arr = text.find("[")
    end_arr = text.rfind("]")
    
    # Determine which comes first
    if start_obj != -1 and (start_arr == -1 or start_obj < start_arr):
        if end_obj != -1 and end_obj > start_obj:
            candidate = text[start_obj : end_obj + 1].strip()
            return candidate or None
    
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        candidate = text[start_arr : end_arr + 1].strip()
        return candidate or None

    return None


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
