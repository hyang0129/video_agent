"""Tests for src/screenwriting/concept_agent.py.

Run with: pytest tests/test_concept_agent.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from video_agent.screenwriting.concept_agent import _estimate_hook_strength, ConceptAgent


class TestEstimateHookStrength:

    def test_estimate_hook_strength_question(self):
        score = _estimate_hook_strength("Did you know this?")
        base = 0.5 + 0.15  # question mark
        assert abs(score - base) < 0.01

    def test_estimate_hook_strength_digits(self):
        score = _estimate_hook_strength("Top 5 facts about tanks")
        assert score >= 0.5 + 0.1  # digits bonus

    def test_estimate_hook_strength_high_valence(self):
        score = _estimate_hook_strength("The secret nobody knows")
        assert score >= 0.5 + 0.15  # high_valence bonus

    def test_estimate_hook_strength_optimal_length(self):
        hook = "one two three four five six seven"  # 7 words
        score = _estimate_hook_strength(hook)
        assert score >= 0.5 + 0.1  # length bonus

    def test_estimate_hook_strength_max_cap(self):
        hook = "Did you know these 5 secret hidden truth facts are shocking?"
        score = _estimate_hook_strength(hook)
        assert score <= 1.0


@patch("video_agent.screenwriting.concept_agent.make_llm")
def test_generate_concepts_mocked_llm(mock_make_llm):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(
        content='[{"format": "facts", "hook": "Did you know these 5 secrets?", "angle": "Hidden history revealed"}]'
    )
    mock_make_llm.return_value = mock_llm

    agent = ConceptAgent()
    concepts = agent.generate_concepts(
        topic_brief={"topic_id": "test_topic", "topic_brief_id": "tb_123"},
        n_concepts=1,
        formats=["facts"],
    )
    assert len(concepts) >= 1
    assert "concept_id" in concepts[0]
    assert concepts[0]["format"] == "facts"
    assert concepts[0]["hook"] == "Did you know these 5 secrets?"
    assert concepts[0]["hook_strength_estimate"] > 0.5
