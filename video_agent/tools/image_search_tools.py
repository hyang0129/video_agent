"""Image search tools for the visual asset stage.

This module is intentionally small and deterministic at the boundary:
- It returns normalized metadata (source, url, resolution, attribution)
- It does not download assets (download handled by VisualAssetAgent)

Supported sources: Pexels, Wikimedia Commons.
Additional sources can be added behind the same interface.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_RELEVANCE_STOPWORDS = {"the", "and", "with", "that", "this", "from", "have", "a", "an", "of", "in", "on", "at", "to", "for", "is", "are", "was", "were"}


def _relevance_tokens(text: str) -> set[str]:
    tokens = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return {t for t in tokens if t not in _RELEVANCE_STOPWORDS}


def score_candidate_relevance(candidate: Dict[str, Any], query: str) -> float:
    """Score one image candidate's relevance to a query using alt-text token overlap.

    Args:
        candidate: Normalized image result dict (with metadata.alt or metadata.title).
        query: Search query or visual description.

    Returns:
        Relevance score in [0.0, 1.0]. Higher is better.
    """
    metadata = candidate.get("metadata") or {}
    alt_text = str(metadata.get("alt") or metadata.get("title") or "").strip()
    if not alt_text:
        return 0.0

    query_tokens = _relevance_tokens(query)
    if not query_tokens:
        return 0.0

    alt_tokens = _relevance_tokens(alt_text)
    overlap = query_tokens.intersection(alt_tokens)
    return round(len(overlap) / len(query_tokens), 3)

import threading
import time

import requests

from ..config import PEXELS_API_KEY

_WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
_WIKIMEDIA_HOST = "wikimedia.org"
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp)$", re.IGNORECASE)


class _ThreadLocalRateLimiter:
    """Enforces a minimum interval between calls on a per-thread basis."""

    def __init__(self, min_interval_s: float = 1.0) -> None:
        self._local = threading.local()
        self.min_interval_s = min_interval_s

    def throttle(self) -> None:
        now = time.monotonic()
        last = getattr(self._local, "last_call", 0.0)
        wait = self.min_interval_s - (now - last)
        if wait > 0:
            time.sleep(wait)
        self._local.last_call = time.monotonic()


wikimedia_rate_limiter = _ThreadLocalRateLimiter(min_interval_s=1.0)


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


def search_wikimedia_images(
    query: str,
    per_page: int = 10,
    orientation: str = "portrait",
) -> List[Dict[str, Any]]:
    """Search Wikimedia Commons for freely-licensed images.

    Uses the MediaWiki API generator to fetch file metadata in one request.
    No API key required. Returns JPEG/PNG/WebP files only.

    Args:
        query: Search query (e.g. "Tiger I tank World War II").
        per_page: Maximum number of results to return (capped at 50).
        orientation: Ignored — Wikimedia has no orientation filter.
            Returned images are filtered to at least 400px on the short side.

    Returns:
        List of normalized image results matching the Pexels schema.

    Raises:
        ImageSearchError: If the API request fails.
    """
    if not query or not query.strip():
        return []

    limit = max(1, min(int(per_page), 50))
    # Fetch more candidates than needed so we can filter non-photo types.
    fetch_limit = min(limit * 3, 50)

    params: Dict[str, Any] = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": 6,  # File: namespace
        "gsrsearch": query.strip(),
        "gsrlimit": fetch_limit,
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription",
        "redirects": 1,
    }

    headers = {
        "User-Agent": "VideoAgent/1.0",
    }

    try:
        wikimedia_rate_limiter.throttle()
        resp = requests.get(_WIKIMEDIA_API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise ImageSearchError(f"Wikimedia request failed: {exc}")
    except ValueError as exc:
        raise ImageSearchError(f"Wikimedia response was not JSON: {exc}")

    pages = (payload.get("query") or {}).get("pages") or {}

    results: List[Dict[str, Any]] = []
    for page in pages.values():
        if len(results) >= limit:
            break

        imageinfo_list = page.get("imageinfo")
        if not isinstance(imageinfo_list, list) or not imageinfo_list:
            continue

        info = imageinfo_list[0]
        url: Optional[str] = info.get("url")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        if not _IMAGE_EXT_RE.search(url):
            continue

        width = info.get("width") or 0
        height = info.get("height") or 0
        short_side = min(int(width), int(height))
        if short_side < 400:
            continue

        extmeta = info.get("extmetadata") or {}

        def _meta_value(key: str) -> str:
            entry = extmeta.get(key) or {}
            raw = str(entry.get("value") or "")
            return re.sub(r"<[^>]+>", "", raw).strip()

        license_name = _meta_value("LicenseShortName") or "Wikimedia Commons"
        artist = _meta_value("Artist") or "Wikimedia contributor"
        description = _meta_value("ImageDescription")
        title = str(page.get("title") or "").replace("File:", "").strip()
        alt = description or title

        page_url = f"https://commons.wikimedia.org/wiki/{page.get('title', '').replace(' ', '_')}"

        results.append(
            {
                "source": "wikimedia",
                "url": url,
                "resolution": [int(width), int(height)],
                "attribution": {
                    "required": True,
                    "text": f"{artist} via Wikimedia Commons ({page_url})",
                    "license": license_name,
                },
                "metadata": {
                    "search_query": query.strip(),
                    "title": title,
                    "alt": alt,
                    "page_id": page.get("pageid"),
                },
            }
        )

    return results
