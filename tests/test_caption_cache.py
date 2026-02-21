"""Unit tests for src/facts/caption_cache.py."""

import json
import pytest

from src.facts.caption_cache import CaptionCache


@pytest.fixture
def cache(tmp_path):
    """Return a CaptionCache backed by a temporary directory."""
    return CaptionCache(cache_dir=tmp_path / "captions")


SAMPLE_CAPTION = {
    "video_id": "abc123",
    "text": "Hello world",
    "segments": [{"text": "Hello world", "start": 0.0, "duration": 2.0}],
    "language": "en",
}


class TestCaptionCacheGetSet:
    """Tests for get/set operations."""

    def test_get_returns_none_for_missing_video(self, cache):
        assert cache.get("nonexistent") is None

    def test_set_and_get_roundtrip(self, cache):
        cache.set("abc123", SAMPLE_CAPTION)
        result = cache.get("abc123")
        assert result == SAMPLE_CAPTION

    def test_has_returns_false_before_set(self, cache):
        assert cache.has("abc123") is False

    def test_has_returns_true_after_set(self, cache):
        cache.set("abc123", SAMPLE_CAPTION)
        assert cache.has("abc123") is True

    def test_set_returns_true_on_success(self, cache):
        assert cache.set("abc123", SAMPLE_CAPTION) is True


class TestCaptionCacheDelete:
    """Tests for delete operation."""

    def test_delete_existing_entry(self, cache):
        cache.set("abc123", SAMPLE_CAPTION)
        assert cache.delete("abc123") is True
        assert cache.has("abc123") is False

    def test_delete_missing_entry_returns_false(self, cache):
        assert cache.delete("nothere") is False


class TestCaptionCacheClear:
    """Tests for clear operation."""

    def test_clear_removes_all_entries(self, cache):
        cache.set("v1", SAMPLE_CAPTION)
        cache.set("v2", SAMPLE_CAPTION)
        count = cache.clear()
        assert count == 2
        assert cache.has("v1") is False
        assert cache.has("v2") is False

    def test_clear_empty_cache_returns_zero(self, cache):
        assert cache.clear() == 0


class TestCaptionCacheGetStats:
    """Tests for get_stats."""

    def test_stats_empty_cache(self, cache):
        stats = cache.get_stats()
        assert stats["cached_videos"] == 0
        assert stats["total_size_bytes"] == 0

    def test_stats_with_entries(self, cache):
        cache.set("v1", SAMPLE_CAPTION)
        cache.set("v2", SAMPLE_CAPTION)
        stats = cache.get_stats()
        assert stats["cached_videos"] == 2
        assert stats["total_size_bytes"] > 0


class TestCaptionCacheCorruptFile:
    """Tests for resilience against corrupt cache files."""

    def test_get_returns_none_for_corrupt_file(self, cache, tmp_path):
        corrupt_path = tmp_path / "captions" / "corrupt.json"
        corrupt_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt_path.write_text("not valid json")
        # Re-instantiate cache pointing at same dir
        c = CaptionCache(cache_dir=tmp_path / "captions")
        assert c.get("corrupt") is None
