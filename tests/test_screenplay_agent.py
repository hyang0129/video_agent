"""Tests for src/screenwriting/screenplay_agent.py.

Run with: pytest tests/test_screenplay_agent.py -v
"""

import json

import pytest
from unittest.mock import patch, MagicMock

from video_agent.screenwriting.screenplay_agent import ScreenplayAgent, _coerce_scenes


class TestCoerceScenes:

    def test_coerce_scenes_normalizes_durations(self):
        raw = [
            {"scene_id": "scene_01", "vo_line": "Line one.", "target_duration_s": 10.0,
             "visual": {"description": "tank", "mood": "dark", "search_queries": ["tank"]}},
            {"scene_id": "scene_02", "vo_line": "Line two.", "target_duration_s": 10.0,
             "visual": {"description": "field", "mood": "calm", "search_queries": ["field"]}},
        ]
        scenes = _coerce_scenes(raw, target_duration_s=30)
        total = sum(s["target_duration_s"] for s in scenes)
        assert abs(total - 30) < 0.1

    def test_coerce_scenes_preserves_generation_prompts(self):
        raw = [
            {
                "scene_id": "scene_01",
                "vo_line": "A tank rolls.",
                "target_duration_s": 10.0,
                "visual": {
                    "description": "Sherman tank on a bridge",
                    "mood": "tense",
                    "search_queries": ["Sherman tank bridge", "WW2 tank river", "military tank"],
                    "generation_prompts": {
                        "precise": "Sherman M4 tank crossing a narrow wooden bridge, WW2, photorealistic",
                        "general": "Sherman tank WW2 photorealistic",
                    },
                },
            }
        ]
        scenes = _coerce_scenes(raw, target_duration_s=10)
        gp = scenes[0]["visual"]["generation_prompts"]
        assert gp["precise"] == "Sherman M4 tank crossing a narrow wooden bridge, WW2, photorealistic"
        assert gp["general"] == "Sherman tank WW2 photorealistic"

    def test_coerce_scenes_generation_prompts_defaults_to_empty(self):
        raw = [
            {"scene_id": "scene_01", "vo_line": "Line.", "target_duration_s": 5.0,
             "visual": {"description": "sky", "mood": "calm", "search_queries": ["sky"]}},
        ]
        scenes = _coerce_scenes(raw, target_duration_s=5)
        assert scenes[0]["visual"]["generation_prompts"] == {}

    def test_coerce_scenes_search_queries_preserved(self):
        raw = [
            {"scene_id": "scene_01", "vo_line": "Line.", "target_duration_s": 5.0,
             "visual": {"description": "tank", "mood": "dark",
                        "search_queries": ["Sherman tank bridge", "WW2 tank", "military tank"]}},
        ]
        scenes = _coerce_scenes(raw, target_duration_s=5)
        assert scenes[0]["visual"]["search_queries"] == ["Sherman tank bridge", "WW2 tank", "military tank"]

    def test_coerce_scenes_empty_list(self):
        assert _coerce_scenes([], target_duration_s=30) == []

    def test_coerce_scenes_non_list(self):
        assert _coerce_scenes("not a list", target_duration_s=30) == []
        assert _coerce_scenes(None, target_duration_s=30) == []
        assert _coerce_scenes(42, target_duration_s=30) == []


@patch("video_agent.screenwriting.screenplay_agent.make_llm")
def test_write_screenplay_mocked_llm(mock_make_llm):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=json.dumps({
        "target_duration_s": 30,
        "narrator_character": {"type": "voice_only", "voice_preset": "calm"},
        "music_tone": "dramatic",
        "scenes": [
            {
                "scene_id": "scene_01",
                "vo_line": "A tank rolls across the field.",
                "target_duration_s": 15.0,
                "visual": {"description": "WWII tank in field", "mood": "dramatic",
                           "search_queries": ["tank field"]},
                "on_screen_text": "The Tiger",
                "music_energy": "medium",
            },
            {
                "scene_id": "scene_02",
                "vo_line": "It changed warfare forever.",
                "target_duration_s": 15.0,
                "visual": {"description": "battlefield smoke", "mood": "intense",
                           "search_queries": ["battlefield"]},
                "on_screen_text": "Forever Changed",
                "music_energy": "high",
            },
        ]
    }))
    mock_make_llm.return_value = mock_llm

    agent = ScreenplayAgent()
    concept = {"concept_id": "c_test", "format": "facts"}
    topic_brief = {"topic_id": "ww2_tanks"}
    result = agent.write_screenplay(
        concept, topic_brief,
        format_template={"target_duration_s": 30, "music_tone": "dramatic"},
    )

    assert result["schema_version"] == "1.0.0"
    assert "screenplay_id" in result
    assert len(result["scenes"]) == 2
    assert result["music_tone"] == "dramatic"
    assert result["target_duration_s"] == 30


@patch("video_agent.screenwriting.screenplay_agent.make_llm")
def test_revise_scene_missing_scene(mock_make_llm):
    mock_make_llm.return_value = MagicMock()

    agent = ScreenplayAgent()
    screenplay = {
        "screenplay_id": "sp_test",
        "scenes": [
            {"scene_id": "scene_01", "vo_line": "Hello.", "visual": {"description": "sky"}},
        ],
    }
    result = agent.revise_scene(
        screenplay=screenplay,
        scene_id="scene_99",
        issue="nonexistent",
        suggestion="fix it",
        revision_field="visual",
    )
    assert result is screenplay
