"""Tests for tools/image_alignment_tools.py."""

from video_agent.tools.image_alignment_tools import (
    AlignmentScore,
    ImageAlignmentEvaluator,
    SceneAlignmentResult,
    _compute_weighted_score,
    _parse_scores_response,
)


class TestParseScoresResponse:

    def test_valid_json(self):
        text = '{"subject": 4, "setting": 3, "mood": 5, "composition": 4, "artifacts": 5}'
        scores = _parse_scores_response(text)
        assert scores == {"subject": 4, "setting": 3, "mood": 5, "composition": 4, "artifacts": 5}

    def test_json_with_surrounding_text(self):
        text = 'Here are the scores: {"subject": 2, "setting": 4, "mood": 3, "composition": 3, "artifacts": 4} Hope this helps!'
        scores = _parse_scores_response(text)
        assert scores["subject"] == 2
        assert scores["setting"] == 4

    def test_malformed_json_returns_neutral(self):
        scores = _parse_scores_response("I can't score this image properly")
        assert all(v == 3 for v in scores.values())

    def test_scores_clamped_to_1_5(self):
        text = '{"subject": 0, "setting": 7, "mood": 3, "composition": 3, "artifacts": 3}'
        scores = _parse_scores_response(text)
        assert scores["subject"] == 1
        assert scores["setting"] == 5

    def test_missing_keys_default_to_3(self):
        text = '{"subject": 5}'
        scores = _parse_scores_response(text)
        assert scores["subject"] == 5
        assert scores["mood"] == 3


class TestComputeWeightedScore:

    def test_all_fives(self):
        scores = {"subject": 5, "setting": 5, "mood": 5, "composition": 5, "artifacts": 5}
        assert _compute_weighted_score(scores) == 5.0

    def test_all_ones(self):
        scores = {"subject": 1, "setting": 1, "mood": 1, "composition": 1, "artifacts": 1}
        assert _compute_weighted_score(scores) == 1.0

    def test_weighted_average(self):
        scores = {"subject": 4, "setting": 3, "mood": 4, "composition": 4, "artifacts": 5}
        # 0.35*4 + 0.25*3 + 0.15*4 + 0.15*4 + 0.10*5 = 1.4+0.75+0.6+0.6+0.5 = 3.85
        assert _compute_weighted_score(scores) == 3.85


class TestSceneAlignmentResult:

    def test_to_dict(self):
        result = SceneAlignmentResult(
            scene_id="scene_01",
            best_score=4.2,
            best_candidate_id="cand_a",
            scores_by_axis={"subject": 5, "setting": 4, "mood": 4, "composition": 4, "artifacts": 3},
            candidates_evaluated=3,
            early_exit=True,
            revision_requested=False,
        )
        d = result.to_dict()
        assert d["scene_id"] == "scene_01"
        assert d["best_score"] == 4.2
        assert d["early_exit"] is True


class TestImageAlignmentEvaluator:

    def test_passthrough_when_no_scene_context(self):
        """Backward compat: no scene_context returns first candidate, None."""
        evaluator = ImageAlignmentEvaluator()
        candidates = [
            {"candidate_id": "cand_a", "url": "https://example.com/a.jpg"},
            {"candidate_id": "cand_b", "url": "https://example.com/b.jpg"},
        ]
        chosen, result = evaluator.select_best(candidates)
        assert chosen is candidates[0]
        assert result is None

    def test_empty_list_returns_none(self):
        evaluator = ImageAlignmentEvaluator()
        chosen, result = evaluator.select_best([])
        assert chosen is None
        assert result is None

    def test_streaming_early_exit_with_mock_backend(self):
        """Mock backend: first candidate scores above accept threshold."""

        class MockBackend:
            def score_image(self, image_url, visual_description, vo_line, scene_mood):
                return AlignmentScore(
                    candidate_id="",
                    weighted_score=4.5,
                    axis_scores={"subject": 5, "setting": 4, "mood": 5, "composition": 4, "artifacts": 4},
                )

        evaluator = ImageAlignmentEvaluator(
            backend=MockBackend(),
            accept_threshold=4.0,
            min_threshold=2.5,
            mode="streaming",
        )
        candidates = [
            {"candidate_id": "cand_a", "url": "https://example.com/a.jpg"},
            {"candidate_id": "cand_b", "url": "https://example.com/b.jpg"},
        ]
        scene_context = {
            "visual_description": "A tank crossing a bridge",
            "vo_line": "Allied forces advanced",
            "scene_mood": "tense",
            "scene_id": "scene_01",
        }
        chosen, result = evaluator.select_best(candidates, scene_context=scene_context)
        assert chosen is candidates[0]
        assert result is not None
        assert result.early_exit is True
        assert result.candidates_evaluated == 1

    def test_batch_picks_highest_score(self):
        """Batch mode scores all candidates, picks highest."""
        call_count = 0

        class MockBackend:
            def score_image(self, image_url, visual_description, vo_line, scene_mood):
                nonlocal call_count
                call_count += 1
                if "b.jpg" in image_url:
                    return AlignmentScore(candidate_id="", weighted_score=4.8, axis_scores={})
                return AlignmentScore(candidate_id="", weighted_score=3.0, axis_scores={})

        evaluator = ImageAlignmentEvaluator(
            backend=MockBackend(),
            accept_threshold=4.0,
            min_threshold=2.5,
            mode="batch",
        )
        candidates = [
            {"candidate_id": "cand_a", "url": "https://example.com/a.jpg"},
            {"candidate_id": "cand_b", "url": "https://example.com/b.jpg"},
        ]
        scene_context = {"visual_description": "test", "vo_line": "test", "scene_mood": "neutral", "scene_id": "s1"}
        chosen, result = evaluator.select_best(candidates, scene_context=scene_context)
        assert chosen is candidates[1]
        assert call_count == 2
        assert result.candidates_evaluated == 2

    def test_revision_requested_when_below_min_threshold(self):
        """All candidates below min threshold triggers revision request."""

        class MockBackend:
            def score_image(self, image_url, visual_description, vo_line, scene_mood):
                return AlignmentScore(candidate_id="", weighted_score=2.0, axis_scores={})

        evaluator = ImageAlignmentEvaluator(
            backend=MockBackend(),
            accept_threshold=4.0,
            min_threshold=2.5,
            mode="batch",
        )
        candidates = [{"candidate_id": "c1", "url": "https://example.com/c.jpg"}]
        scene_context = {"visual_description": "test", "vo_line": "test", "scene_mood": "neutral", "scene_id": "s1"}
        chosen, result = evaluator.select_best(candidates, scene_context=scene_context)
        assert result.revision_requested is True
        assert result.best_score == 2.0
