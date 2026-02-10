"""Image search tools for the visual asset stage.

This module is intentionally small and deterministic at the boundary:
- It returns normalized metadata (source, url, resolution, attribution)
- It does not download assets (download handled by VisualAssetAgent)

Phase 1 supports Pexels. Additional sources (Unsplash, Pixabay) can be added
behind the same interface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from ..config import PEXELS_API_KEY


class ImageSearchError(Exception):
    """Raised when an image search provider call fails."""


def search_pexels_images(
    query: str,
    per_page: int = 10,
    orientation: str = "portrait",
) -> List[Dict[str, Any]]:
    """Search the Pexels API for images.

    Args:
        query: Search query.
        per_page: Number of results to request.
        orientation: One of "landscape" | "portrait" | "square".

    Returns:
        List of normalized image results:
        {
            "source": "pexels",
            "url": "...",
            "resolution": [width, height],
            "attribution": {"required": True, "text": "...", "license": "..."},
            "metadata": {...}
        }

    Raises:
        ImageSearchError: If the API key is missing or the request fails.
    """
    if not query or not query.strip():
        return []

    if not PEXELS_API_KEY:
        raise ImageSearchError("PEXELS_API_KEY is not configured")

    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query.strip(),
        "per_page": max(1, min(int(per_page), 80)),
        "orientation": orientation,
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise ImageSearchError(f"Pexels request failed: {exc}")
    except ValueError as exc:
        raise ImageSearchError(f"Pexels response was not JSON: {exc}")

    photos = payload.get("photos")
    if not isinstance(photos, list):
        return []

    results: List[Dict[str, Any]] = []
    for item in photos:
        if not isinstance(item, dict):
            continue

        src = item.get("src")
        if not isinstance(src, dict):
            continue

        image_url: Optional[str] = None
        # Prefer higher quality but stable keys.
        for key in ("original", "large2x", "large", "portrait"):
            value = src.get(key)
            if isinstance(value, str) and value.startswith("http"):
                image_url = value
                break

        if not image_url:
            continue

        width = item.get("width")
        height = item.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            width, height = 0, 0

        photographer = str(item.get("photographer") or "Pexels Creator").strip()
        photographer_url = str(item.get("photographer_url") or "https://www.pexels.com").strip()

        results.append(
            {
                "source": "pexels",
                "url": image_url,
                "resolution": [width, height],
                "attribution": {
                    "required": True,
                    "text": f"Photo by {photographer} on Pexels ({photographer_url})",
                    "license": "Pexels License",
                },
                "metadata": {
                    "search_query": query.strip(),
                    "pexels_id": item.get("id"),
                    "alt": item.get("alt"),
                },
            }
        )

    return results
