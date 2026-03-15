"""Tests for src/screenwriting/screenplay_reviewer.py.

Run with: pytest tests/test_screenplay_reviewer.py -v
"""

import pytest

from video_agent.screenwriting.screenplay_reviewer import ScreenplayReviewer, _is_generic_visual


def _valid_screenplay():
    return {
        "screenplay_id": "sp_test123",
        "target_duration_s": 30,
        "scenes": [
            {
                "scene_id": "scene_01",
                "vo_line": "A tank rolls across the battlefield.",
                "target_duration_s": 15.0,
                "visual": {
                    "description": "WWII Tiger tank crossing muddy field",
                    "mood": "dramatic",
                    "search_queries": ["Tiger tank muddy field WW2", "WW2 tank battle", "military tank"],
                },
                "on_screen_text": "The Tiger Tank",
            },
            {
                "scene_id": "scene_02",
                "vo_line": "It changed warfare forever.",
                "target_duration_s": 15.0,
                "visual": {
                    "description": "soldiers watching tank advance across open ground",
                    "mood": "intense",
                    "search_queries": ["soldiers watching tank advance WW2", "WW2 soldiers battlefield", "soldiers battlefield"],
                },
                "on_screen_text": "Forever Changed",
            },
        ],
    }


class TestScreenplayReviewer:

    def test_approve_valid_screenplay(self):
        reviewer = ScreenplayReviewer()
        report = reviewer.review(_valid_screenplay())
        assert report["recommended_action"] == "approve"
        assert report["overall_score"] > 0.8

    def test_reject_no_scenes(self):
        reviewer = ScreenplayReviewer()
        sp = {"screenplay_id": "sp_empty", "target_duration_s": 30, "scenes": []}
        report = reviewer.review(sp)
        assert report["recommended_action"] == "reject"
        assert report["overall_score"] == 0.0

    def test_error_empty_vo_line(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        sp["scenes"][0]["vo_line"] = ""
        report = reviewer.review(sp)
        issues = [i for i in report["scene_issues"] if i["issue"] == "empty_vo_line"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"

    def test_error_empty_visual_description(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        sp["scenes"][0]["visual"]["description"] = ""
        report = reviewer.review(sp)
        issues = [i for i in report["scene_issues"]
                  if i["issue"] == "empty_visual_description"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"

    def test_warn_generic_visual(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        sp["scenes"][0]["visual"]["description"] = "people talking"
        report = reviewer.review(sp)
        issues = [i for i in report["scene_issues"]
                  if i["issue"] == "visual_too_generic"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "warn"

    def test_warn_vo_too_long(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        sp["scenes"][0]["vo_line"] = " ".join(["word"] * 200)
        sp["scenes"][0]["target_duration_s"] = 3.0
        report = reviewer.review(sp)
        issues = [i for i in report["scene_issues"]
                  if i["issue"] == "vo_too_long"]
        assert len(issues) >= 1
        assert issues[0]["severity"] == "warn"

    def test_warn_search_queries_count_too_few(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        sp["scenes"][0]["visual"]["search_queries"] = ["only one query"]
        report = reviewer.review(sp)
        issues = [i for i in report["scene_issues"]
                  if i["issue"] == "search_queries_count" and i["scene_id"] == "scene_01"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "warn"
        assert "3" in issues[0]["detail"]

    def test_warn_search_queries_count_correct(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        for scene in sp["scenes"]:
            scene["visual"]["search_queries"] = ["exact query", "general query", "fallback query"]
        report = reviewer.review(sp)
        issues = [i for i in report["scene_issues"] if i["issue"] == "search_queries_count"]
        assert issues == []

    def test_score_calculation(self):
        reviewer = ScreenplayReviewer()
        sp = _valid_screenplay()
        sp["scenes"][0]["vo_line"] = ""
        sp["scenes"][1]["visual"]["description"] = ""
        report = reviewer.review(sp)
        assert report["overall_score"] < 1.0
        assert report["overall_score"] == pytest.approx(1.0 - 2 * 0.2, abs=0.1)


class TestIsGenericVisual:

    def test_exact_match(self):
        assert _is_generic_visual("people talking") is True

    def test_non_generic(self):
        assert _is_generic_visual("WWII Tiger tank crossing muddy field") is False

    def test_close_match(self):
        assert _is_generic_visual("a people talking") is True
