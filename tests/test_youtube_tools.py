"""Unit tests for src/tools/youtube_tools.py helper functions."""

from unittest.mock import MagicMock, patch
import pytest

from src.tools.youtube_tools import (
    _videos_to_public_dicts,
    compute_content_gap_metrics,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(
    id="v1",
    title="Title",
    channel_id="ch1",
    channel_name="Channel",
    published="2024-01-01T00:00:00Z",
    duration_seconds=300,
    views=1_000_000,
    likes=20_000,
    comments=500,
    engagement_rate=0.02,
    tags=None,
):
    """Build a minimal video dict matching the internal schema."""
    return {
        "id": id,
        "title": title,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "published": published,
        "duration_seconds": duration_seconds,
        "views": views,
        "likes": likes,
        "comments": comments,
        "engagement_rate": engagement_rate,
        "tags": tags or [],
    }


# ---------------------------------------------------------------------------
# Tests for _videos_to_public_dicts
# ---------------------------------------------------------------------------

class TestVideosToPublicDicts:
    """Tests for the _videos_to_public_dicts helper."""

    def test_empty_list_returns_empty_list(self):
        assert _videos_to_public_dicts([]) == []

    def test_all_fields_preserved(self):
        video = _make_video(
            id="abc",
            title="My Video",
            channel_id="ch99",
            channel_name="Great Channel",
            published="2024-06-01T00:00:00Z",
            duration_seconds=120,
            views=5000,
            likes=100,
            comments=10,
            engagement_rate=0.02,
            tags=["sci-fi", "shorts"],
        )
        result = _videos_to_public_dicts([video])
        assert len(result) == 1
        pub = result[0]
        assert pub["id"] == "abc"
        assert pub["title"] == "My Video"
        assert pub["channel_id"] == "ch99"
        assert pub["channel_name"] == "Great Channel"
        assert pub["published"] == "2024-06-01T00:00:00Z"
        assert pub["duration_seconds"] == 120
        assert pub["views"] == 5000
        assert pub["likes"] == 100
        assert pub["comments"] == 10
        assert pub["engagement_rate"] == pytest.approx(0.02)
        assert pub["tags"] == ["sci-fi", "shorts"]

    def test_none_numeric_values_default_to_zero(self):
        video = {"id": "x", "views": None, "likes": None, "comments": None,
                 "duration_seconds": None, "engagement_rate": None}
        result = _videos_to_public_dicts([video])
        pub = result[0]
        assert pub["views"] == 0
        assert pub["likes"] == 0
        assert pub["comments"] == 0
        assert pub["duration_seconds"] == 0
        assert pub["engagement_rate"] == pytest.approx(0.0)

    def test_multiple_videos_are_all_converted(self):
        videos = [_make_video(id=f"v{i}") for i in range(5)]
        result = _videos_to_public_dicts(videos)
        assert len(result) == 5
        assert [r["id"] for r in result] == ["v0", "v1", "v2", "v3", "v4"]

    def test_tags_defaults_to_empty_list_when_missing(self):
        video = {"id": "x"}
        result = _videos_to_public_dicts([video])
        assert result[0]["tags"] == []


# ---------------------------------------------------------------------------
# Tests for compute_content_gap_metrics (mocked YouTube client)
# ---------------------------------------------------------------------------

LONGFORM_VIDEOS = [
    _make_video(id="lf1", channel_name="BigChannel", views=2_000_000, engagement_rate=0.04),
    _make_video(id="lf2", channel_name="OtherChannel", views=1_000_000, engagement_rate=0.02),
]

SHORTFORM_VIDEOS = [
    _make_video(id="sf1", duration_seconds=45, views=50_000),
    _make_video(id="sf2", duration_seconds=30, views=30_000),
    # This one is over 60s and should be filtered out
    _make_video(id="sf3", duration_seconds=120, views=10_000),
]


class TestComputeContentGapMetrics:
    """Tests for compute_content_gap_metrics."""

    def _mock_client(self, longform=LONGFORM_VIDEOS, shortform=SHORTFORM_VIDEOS):
        """Return a mock YouTubeClient whose search_videos returns given data."""
        mock = MagicMock()

        def search_videos(query, max_results, order, duration):
            if duration == "medium":
                return longform
            return shortform

        mock.search_videos.side_effect = search_videos
        return mock

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_returns_viable_true_with_longform_content(self, mock_get_client):
        mock_get_client.return_value = self._mock_client()
        result = compute_content_gap_metrics("sci-fi")
        assert result["viable"] is True

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_topic_field_matches_input(self, mock_get_client):
        mock_get_client.return_value = self._mock_client()
        result = compute_content_gap_metrics("space travel")
        assert result["topic"] == "space travel"

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_longform_stats_computed_correctly(self, mock_get_client):
        mock_get_client.return_value = self._mock_client()
        result = compute_content_gap_metrics("topic")
        lf = result["longform"]
        assert lf["videos_found"] == 2
        assert lf["total_views"] == 3_000_000
        assert lf["avg_engagement"] == pytest.approx(0.03)
        assert lf["top_channel"] == "BigChannel"

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_shortform_stats_filter_over_60s(self, mock_get_client):
        mock_get_client.return_value = self._mock_client()
        result = compute_content_gap_metrics("topic")
        sf = result["shortform"]
        # sf3 (120s) should be filtered out
        assert sf["shorts_found"] == 2
        assert sf["total_views"] == 80_000

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_scores_are_present_and_in_range(self, mock_get_client):
        mock_get_client.return_value = self._mock_client()
        result = compute_content_gap_metrics("topic")
        scores = result["scores"]
        for key in ("opportunity", "demand", "gap", "engagement"):
            assert key in scores
            assert 0.0 <= scores[key] <= 10.0

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_returns_not_viable_when_no_longform(self, mock_get_client):
        mock_get_client.return_value = self._mock_client(longform=[], shortform=[])
        result = compute_content_gap_metrics("empty_topic")
        assert result["viable"] is False
        assert result["reason"] == "insufficient_longform"

    @patch("src.tools.youtube_tools.get_youtube_client")
    def test_demand_score_capped_at_10(self, mock_get_client):
        massive_views = [_make_video(id=f"lf{i}", views=100_000_000) for i in range(3)]
        mock_get_client.return_value = self._mock_client(longform=massive_views)
        result = compute_content_gap_metrics("blockbuster")
        assert result["scores"]["demand"] == pytest.approx(10.0)
