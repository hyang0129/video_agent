"""Tools package.

This package contains tool modules used by various agents.

Important:
We keep imports *lazy* here so that optional dependencies for one tool set
don't prevent importing unrelated agents.
"""

from __future__ import annotations

from typing import Any


def _lazy_youtube() -> Any:
    from . import youtube_tools

    return youtube_tools


def search_longform_content(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().search_longform_content(*args, **kwargs)


def search_shortform_content(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().search_shortform_content(*args, **kwargs)


def fetch_videos_corpus(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().fetch_videos_corpus(*args, **kwargs)


def analyze_channel(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().analyze_channel(*args, **kwargs)


def compare_content_gap(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().compare_content_gap(*args, **kwargs)


def compute_content_gap_metrics(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().compute_content_gap_metrics(*args, **kwargs)


def get_youtube_client(*args: Any, **kwargs: Any) -> Any:
    return _lazy_youtube().get_youtube_client(*args, **kwargs)


__all__ = [
    "search_longform_content",
    "search_shortform_content",
    "fetch_videos_corpus",
    "analyze_channel",
    "compare_content_gap",
    "compute_content_gap_metrics",
    "get_youtube_client",
]

