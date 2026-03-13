"""Stage 2: Fact Mining

Tests FactMiner → FactStore (YouTube captions → extracted facts).

What this stage does:
  - Searches YouTube for videos matching the topic query
  - Downloads video captions
  - Uses LLM to extract discrete, verifiable facts from the transcript
  - Scores facts by video engagement (views, likes)
  - Stores facts in SQLite FactStore

Human review checklist:
  - Extracted facts are accurate and not hallucinated
  - Facts are specific (numbers, dates, names preserved)
  - No meta-facts like "this video contains 10 facts"
  - Engagement scores are reasonable relative to video popularity
  - Enough facts for a script (target: 6+ usable facts)

Run:
    pytest tests/integration/test_stage_02_fact_mining.py -v -s -m integration

Requires:
    YOUTUBE_API_KEY    for video search and caption download
    ANTHROPIC_API_KEY or GOOGLE_API_KEY     for LLM fact extraction from transcripts

Input fixture:
    tests/fixtures/topic_brief_ww2_tanks.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from video_agent.artifacts.io import write_json
from video_agent.facts.caption_cache import CaptionCache
from video_agent.facts.fact_miner import FactMiner
from video_agent.facts.fact_store import FactStore
from .helpers import load_fixture, copy_to_review

MIN_FACTS_EXPECTED = 3


@pytest.mark.integration
def test_fact_mining_extracts_facts_from_youtube(tmp_path: Path) -> None:
    if not os.getenv("YOUTUBE_API_KEY"):
        pytest.skip("Missing YOUTUBE_API_KEY")
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        pytest.skip("Missing ANTHROPIC_API_KEY or GOOGLE_API_KEY")

    topic_brief = load_fixture("topic_brief_ww2_tanks.json")
    topic_id = topic_brief["topic_id"]
    subtopic_id = topic_brief["subtopic_id"]
    query = topic_brief["subtopic"]["query"]

    db_path = tmp_path / "facts.db"
    caption_cache_dir = tmp_path / "caption_cache"

    project_root = Path(__file__).resolve().parents[2]
    cookies_file = project_root / "youtube_cookies.txt"
    cookies_path = str(cookies_file) if cookies_file.exists() else None

    fact_store = FactStore(db_path=str(db_path))
    caption_cache = CaptionCache(cache_dir=caption_cache_dir)
    miner = FactMiner(
        fact_store=fact_store,
        caption_cache=caption_cache,
        cookies_file=cookies_path,
    )

    mining_results = miner.mine_top_videos(
        topic_query=query,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        max_videos=3,
        use_captions=True,
    )

    facts = fact_store.query(
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        limit=20,
        min_engagement_score=0.0,
    )

    write_json(tmp_path / "mining_results.json", mining_results)
    write_json(tmp_path / "extracted_facts.json", facts)

    assert len(facts) >= MIN_FACTS_EXPECTED, (
        f"Too few facts extracted: {len(facts)} < {MIN_FACTS_EXPECTED}. "
        f"Mining results: {mining_results}"
    )

    review = copy_to_review(tmp_path, "02_fact_mining")

    print(f"\n--- Human Review: Fact Mining ---")
    print(f"Topic: {topic_id}/{subtopic_id}")
    print(f"Videos found: {mining_results.get('videos_found', 0)}")
    print(f"Videos mined: {mining_results.get('videos_mined', 0)}")
    print(f"Facts extracted: {len(facts)}")
    print(f"Review dir: {review}")
    print(f"Check: extracted_facts.json — are facts accurate and specific?")
    print(f"Check: no meta-facts (e.g. 'this video has 10 facts')")
    print(f"Check: engagement scores correlate with video popularity")
