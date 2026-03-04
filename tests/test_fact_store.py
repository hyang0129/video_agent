"""Unit tests for src/facts/fact_store.py."""

import pytest

from src.facts.fact_store import FactStore


@pytest.fixture
def store(tmp_path):
    """Return a FactStore backed by a temporary SQLite database."""
    return FactStore(db_path=str(tmp_path / "test_facts.db"))


class TestFactStoreAddAndQuery:
    """Tests for adding and querying facts."""

    def test_add_fact_returns_fact_id(self, store):
        fact_id = store.add_fact(
            fact_text="The sky is blue.",
            topic_id="science",
            sources=[{"type": "video", "url": "https://example.com"}],
        )
        assert fact_id.startswith("fact_")

    def test_query_returns_added_fact(self, store):
        store.add_fact(
            fact_text="Water is H2O.",
            topic_id="chemistry",
            sources=[],
        )
        results = store.query("chemistry")
        assert len(results) == 1
        assert results[0]["fact_text"] == "Water is H2O."

    def test_query_filters_by_topic(self, store):
        store.add_fact("Fact A", topic_id="topic_a", sources=[])
        store.add_fact("Fact B", topic_id="topic_b", sources=[])

        results = store.query("topic_a")
        assert len(results) == 1
        assert results[0]["fact_text"] == "Fact A"

    def test_query_filters_by_subtopic(self, store):
        store.add_fact("Subtopic fact", topic_id="sci", subtopic_id="physics", sources=[])
        store.add_fact("Other fact", topic_id="sci", subtopic_id="biology", sources=[])

        results = store.query("sci", subtopic_id="physics")
        assert len(results) == 1
        assert results[0]["fact_text"] == "Subtopic fact"

    def test_query_limit(self, store):
        for i in range(5):
            store.add_fact(f"Fact {i}", topic_id="topic", sources=[])

        results = store.query("topic", limit=3)
        assert len(results) == 3

    def test_query_min_engagement_score(self, store):
        store.add_fact("Low", topic_id="t", sources=[], engagement_score=1.0)
        store.add_fact("High", topic_id="t", sources=[], engagement_score=8.0)

        results = store.query("t", min_engagement_score=5.0)
        assert len(results) == 1
        assert results[0]["fact_text"] == "High"

    def test_query_verified_only(self, store):
        store.add_fact("Unverified", topic_id="t", sources=[], verified=False)
        store.add_fact("Verified", topic_id="t", sources=[], verified=True)

        results = store.query("t", verified_only=True)
        assert len(results) == 1
        assert results[0]["fact_text"] == "Verified"

    def test_query_empty_topic_returns_nothing(self, store):
        results = store.query("nonexistent_topic")
        assert results == []


class TestFactStoreUpdateAndMark:
    """Tests for update and mark operations."""

    def test_update_engagement_score(self, store):
        fact_id = store.add_fact("Some fact", topic_id="t", sources=[])
        store.update_engagement_score(fact_id, 9.5)

        results = store.query("t")
        assert results[0]["engagement_score"] == pytest.approx(9.5)

    def test_mark_verified(self, store):
        fact_id = store.add_fact("Unverified fact", topic_id="t", sources=[], verified=False)
        store.mark_verified(fact_id, verified=True)

        results = store.query("t")
        assert results[0]["verified"] is True


class TestFactStoreSearchByKeyword:
    """Tests for keyword search."""

    def test_search_finds_matching_fact(self, store):
        store.add_fact("Star explodes", topic_id="astro", sources=[], keywords=["star", "supernova"])
        results = store.search_by_keyword(["supernova"])
        assert len(results) == 1

    def test_search_no_match_returns_empty(self, store):
        store.add_fact("Cat fact", topic_id="pets", sources=[], keywords=["cat"])
        results = store.search_by_keyword(["dog"])
        assert results == []

    def test_search_filters_by_topic(self, store):
        store.add_fact("Astro star", topic_id="astro", sources=[], keywords=["star"])
        store.add_fact("Music star", topic_id="music", sources=[], keywords=["star"])

        results = store.search_by_keyword(["star"], topic_id="astro")
        assert len(results) == 1
        assert results[0]["topic_id"] == "astro"


class TestFactStoreGetStats:
    """Tests for get_stats."""

    def test_stats_empty_store(self, store):
        stats = store.get_stats()
        assert stats["total_facts"] == 0

    def test_stats_with_facts(self, store):
        store.add_fact("F1", topic_id="t", sources=[], engagement_score=4.0, verified=True)
        store.add_fact("F2", topic_id="t", sources=[], engagement_score=6.0)

        stats = store.get_stats("t")
        assert stats["total_facts"] == 2
        assert stats["verified_count"] == 1
        assert stats["avg_engagement_score"] == pytest.approx(5.0)
        assert stats["max_engagement_score"] == pytest.approx(6.0)
