"""Tests for the text sanitization and on-screen text flow fixes.

Verifies:
1. _coerce_scenes() sanitizes non-ASCII in vo_line and on_screen_text
2. CompositionAgent.create_text_overlays() prefers on_screen_text over vo_line
3. ScreenplayReviewer flags unsafe characters

Run with: pytest tests/test_text_flow.py -v
"""

from src.screenwriting.screenplay_agent import _coerce_scenes
from src.screenwriting.screenplay_reviewer import ScreenplayReviewer


class TestCoerceScenesSanitization:

    def _make_raw_scenes(self, vo_line, on_screen_text):
        return [{
            "scene_id": "scene_01",
            "vo_line": vo_line,
            "target_duration_s": 5.0,
            "visual": {"description": "tank", "mood": "dark", "search_queries": ["tank"]},
            "on_screen_text": on_screen_text,
            "music_energy": "medium",
        }]

    def test_em_dash_sanitized_in_vo_line(self):
        raw = self._make_raw_scenes(
            vo_line="cheese \u2014 the best",
            on_screen_text="Cheese Facts",
        )
        scenes = _coerce_scenes(raw, target_duration_s=5)
        assert "\u2014" not in scenes[0]["vo_line"]
        assert "cheese - the best" == scenes[0]["vo_line"]

    def test_curly_quotes_sanitized_in_on_screen_text(self):
        raw = self._make_raw_scenes(
            vo_line="Hello.",
            on_screen_text="\u201CThe Best\u201D",
        )
        scenes = _coerce_scenes(raw, target_duration_s=5)
        assert scenes[0]["on_screen_text"] == '"The Best"'

    def test_emoji_stripped(self):
        raw = self._make_raw_scenes(
            vo_line="Great food! \U0001F600",
            on_screen_text="Yum \U0001F355",
        )
        scenes = _coerce_scenes(raw, target_duration_s=5)
        assert "\U0001F600" not in scenes[0]["vo_line"]
        assert "\U0001F355" not in scenes[0]["on_screen_text"]

    def test_clean_text_unchanged(self):
        raw = self._make_raw_scenes(
            vo_line="Normal text here.",
            on_screen_text="Caption Text",
        )
        scenes = _coerce_scenes(raw, target_duration_s=5)
        assert scenes[0]["vo_line"] == "Normal text here."
        assert scenes[0]["on_screen_text"] == "Caption Text"


class TestCompositionTextPriority:
    """Verify that on_screen_text is preferred over vo_line for text overlays."""

    def test_on_screen_text_preferred(self):
        from src.composition_agent import CompositionAgent

        agent = CompositionAgent()
        video_plan = {
            "scenes": [
                {
                    "scene_id": "scene_01",
                    "vo_line": "The Tiger tank was a fearsome weapon of World War Two.",
                    "on_screen_text": "Tiger Tank",
                    "t_start_s": 0.0,
                    "t_end_s": 5.0,
                },
            ],
        }
        audio_timeline = {
            "tracks": [
                {
                    "track_type": "voiceover",
                    "segments": [
                        {"scene_id": "scene_01", "t_start_s": 0.0, "t_end_s": 5.0},
                    ],
                },
            ],
        }
        elements = agent.create_text_overlays(video_plan, audio_timeline)
        assert len(elements) == 1
        assert elements[0]["text"] == "Tiger Tank"

    def test_vo_line_fallback_when_no_on_screen_text(self):
        from src.composition_agent import CompositionAgent

        agent = CompositionAgent()
        video_plan = {
            "scenes": [
                {
                    "scene_id": "scene_01",
                    "vo_line": "The Tiger tank was fearsome.",
                    "on_screen_text": "",
                    "t_start_s": 0.0,
                    "t_end_s": 5.0,
                },
            ],
        }
        audio_timeline = {
            "tracks": [
                {
                    "track_type": "voiceover",
                    "segments": [
                        {"scene_id": "scene_01", "t_start_s": 0.0, "t_end_s": 5.0},
                    ],
                },
            ],
        }
        elements = agent.create_text_overlays(video_plan, audio_timeline)
        assert len(elements) == 1
        assert elements[0]["text"] == "The Tiger tank was fearsome."


class TestReviewerUnsafeCharacters:

    def test_flags_unsafe_chars_in_vo_line(self):
        reviewer = ScreenplayReviewer()
        sp = {
            "screenplay_id": "sp_test",
            "target_duration_s": 10,
            "scenes": [{
                "scene_id": "scene_01",
                "vo_line": "cheese \u2014 the best food",
                "target_duration_s": 10.0,
                "visual": {"description": "wheel of cheese", "mood": "warm",
                           "search_queries": ["cheese"]},
                "on_screen_text": "Cheese Facts",
            }],
        }
        report = reviewer.review(sp)
        unsafe_issues = [i for i in report["scene_issues"]
                         if i["issue"] == "unsafe_characters"]
        assert len(unsafe_issues) >= 1
        assert "vo_line" in unsafe_issues[0]["detail"]

    def test_no_flag_for_clean_text(self):
        reviewer = ScreenplayReviewer()
        sp = {
            "screenplay_id": "sp_test",
            "target_duration_s": 10,
            "scenes": [{
                "scene_id": "scene_01",
                "vo_line": "Clean ASCII text here.",
                "target_duration_s": 10.0,
                "visual": {"description": "wheel of cheese", "mood": "warm",
                           "search_queries": ["cheese"]},
                "on_screen_text": "Cheese Facts",
            }],
        }
        report = reviewer.review(sp)
        unsafe_issues = [i for i in report["scene_issues"]
                         if i["issue"] == "unsafe_characters"]
        assert len(unsafe_issues) == 0
