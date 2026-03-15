"""Tests for tools/image_alignment_tools.py."""

from video_agent.tools.image_alignment_tools import ImageAlignmentEvaluator


class TestImageAlignmentEvaluator:

    def test_select_best_returns_first_candidate(self):
        evaluator = ImageAlignmentEvaluator()
        candidates = [
            {"candidate_id": "cand_a", "url": "https://example.com/a.jpg"},
            {"candidate_id": "cand_b", "url": "https://example.com/b.jpg"},
        ]
        result = evaluator.select_best(candidates)
        assert result is candidates[0]

    def test_select_best_empty_list_returns_none(self):
        evaluator = ImageAlignmentEvaluator()
        assert evaluator.select_best([]) is None

    def test_select_best_single_candidate(self):
        evaluator = ImageAlignmentEvaluator()
        candidate = {"candidate_id": "cand_solo", "url": "https://example.com/solo.jpg"}
        result = evaluator.select_best([candidate])
        assert result is candidate
