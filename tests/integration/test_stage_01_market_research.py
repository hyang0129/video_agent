"""Stage 1: Market Research

Tests MarketResearchAgent → TopicBrief artifacts.

What this stage does:
  - Searches YouTube for trending long-form content in a category
  - Scores topics by view count, engagement rate, and short-form gap
  - Emits ranked TopicBrief JSON files for downstream script generation

Human review checklist:
  - Topics are relevant to the category (not off-topic results)
  - Scores are plausible (higher-engagement topics rank higher)
  - Angle and positioning are specific enough to guide a script
  - No inappropriate or off-brand topics selected

Run:
    pytest tests/integration/test_stage_01_market_research.py -v -s -m integration

Requires:
    YOUTUBE_API_KEY    for video search and engagement metrics
    GOOGLE_API_KEY     for LLM-based topic scoring and angle generation
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.agent import create_agent
from src.artifacts.io import write_json
from .helpers import copy_to_review

CATEGORY = "world war 2 tanks"


@pytest.mark.integration
def test_market_research_produces_topic_briefs(tmp_path: Path) -> None:
    if not os.getenv("YOUTUBE_API_KEY"):
        pytest.skip("Missing YOUTUBE_API_KEY")
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("Missing GOOGLE_API_KEY")

    agent = create_agent()
    result = agent.research_category_artifacts(CATEGORY)

    assert result.get("topic_brief_paths"), "No TopicBrief artifacts produced"

    # Load and validate the first topic brief
    first_path = Path(result["topic_brief_paths"][0])
    assert first_path.exists(), f"TopicBrief file not found: {first_path}"

    import json
    brief = json.loads(first_path.read_text(encoding="utf-8"))
    assert "topic_id" in brief, "TopicBrief missing topic_id"
    assert "subtopic" in brief, "TopicBrief missing subtopic"

    # Copy run dir to results/test/stages/ for human review
    run_dir = Path(result["run_dir"])
    review = copy_to_review(run_dir, "01_market_research")

    print(f"\n--- Human Review: Market Research ---")
    print(f"Category searched: {CATEGORY}")
    print(f"Topic briefs found: {len(result['topic_brief_paths'])}")
    print(f"Review dir: {review}")
    print(f"Check: are the topics relevant and well-scored?")
    print(f"Check: are the angles specific enough to guide a script?")
