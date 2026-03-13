"""Tests for src/facts/fact_miner.py.

Run with: pytest tests/test_fact_miner.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from video_agent.facts.fact_miner import FactMiner


@patch("video_agent.facts.fact_miner.get_youtube_client")
@patch("video_agent.facts.fact_miner.make_llm")
def test_extract_facts_short_text_returns_empty(mock_make_llm, mock_yt):
    mock_make_llm.return_value = MagicMock()
    mock_yt.return_value = MagicMock()

    miner = FactMiner()
    facts = miner.extract_facts_from_text("Too short")
    assert facts == []


@patch("video_agent.facts.fact_miner.get_youtube_client")
@patch("video_agent.facts.fact_miner.make_llm")
def test_extract_facts_from_text_success(mock_make_llm, mock_yt):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='[{"fact_text": "Test fact", "keywords": ["test"], "confidence": "high"}]'
    )
    mock_make_llm.return_value = mock_llm
    mock_yt.return_value = MagicMock()

    miner = FactMiner()
    facts = miner.extract_facts_from_text("A" * 200)
    assert len(facts) == 1
    assert facts[0]["fact_text"] == "Test fact"
    assert facts[0]["keywords"] == ["test"]
    assert facts[0]["confidence"] == "high"


@patch("video_agent.facts.fact_miner.get_youtube_client")
@patch("video_agent.facts.fact_miner.make_llm")
def test_extract_facts_truncates_long_text(mock_make_llm, mock_yt):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='[{"fact_text": "Truncated fact", "keywords": [], "confidence": "medium"}]'
    )
    mock_make_llm.return_value = mock_llm
    mock_yt.return_value = MagicMock()

    miner = FactMiner()
    long_text = "B" * 20000
    facts = miner.extract_facts_from_text(long_text)

    call_args = mock_llm.invoke.call_args[0][0]
    prompt_text = call_args[1].content
    assert "... [truncated]" in prompt_text
    assert len(facts) == 1


@patch("video_agent.facts.fact_miner.get_youtube_client")
@patch("video_agent.facts.fact_miner.make_llm")
def test_mine_video_captions_cached(mock_make_llm, mock_yt):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='[{"fact_text": "Cached fact", "keywords": [], "confidence": "high"}]'
    )
    mock_make_llm.return_value = mock_llm
    mock_yt_client = MagicMock()
    mock_yt_client.search_videos.return_value = []
    mock_yt.return_value = mock_yt_client

    mock_cache = MagicMock()
    mock_cache.get.return_value = {"text": "A" * 200, "language": "en"}

    mock_store = MagicMock()
    mock_store.add_fact.return_value = "fact_001"

    miner = FactMiner(fact_store=mock_store, caption_cache=mock_cache)
    result = miner.mine_video_captions(video_id="vid123", topic_id="test_topic")

    assert result["success"] is True
    mock_cache.get.assert_called_once_with("vid123")
    mock_yt_client.get_video_captions.assert_not_called()


@patch("video_agent.facts.fact_miner.get_youtube_client")
@patch("video_agent.facts.fact_miner.make_llm")
def test_mine_video_captions_unavailable(mock_make_llm, mock_yt):
    mock_make_llm.return_value = MagicMock()
    mock_yt_client = MagicMock()
    mock_yt_client.get_video_captions.return_value = None
    mock_yt.return_value = mock_yt_client

    mock_cache = MagicMock()
    mock_cache.get.return_value = None

    miner = FactMiner(caption_cache=mock_cache)
    result = miner.mine_video_captions(video_id="vid_none", topic_id="test_topic")

    assert result["success"] is False
    assert result["reason"] == "captions_unavailable"
    assert result["facts"] == []
