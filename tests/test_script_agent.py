"""Tests for script_agent module.

Run with: pytest tests/test_script_agent.py -v
"""

import pytest

from video_agent.script_agent import (
    _target_duration_seconds,
    _normalize_beats,
    _is_generic_placeholder_beats,
    _extract_beats_from_script_content,
    _validate_or_fix_script_package,
    generate_offline_script_package,
)


class TestTargetDurationSeconds:
    def test_target_duration_from_creative_spec(self):
        tb = {"format": {"target_duration_seconds": 30}}
        cs = {"style": {"target_duration_seconds": 60}}
        assert _target_duration_seconds(tb, cs) == 60

    def test_target_duration_from_topic_brief(self):
        tb = {"format": {"target_duration_seconds": 30}}
        assert _target_duration_seconds(tb, None) == 30

    def test_target_duration_default(self):
        assert _target_duration_seconds({}, None) == 45


class TestNormalizeBeats:
    def test_normalize_beats_timestamps(self):
        beats = [
            {"on_screen_text": "A", "vo_line": "Hello world."},
            {"on_screen_text": "B", "vo_line": "Goodbye world."},
        ]
        result = _normalize_beats(beats, target_seconds=20)
        assert len(result) == 2
        assert result[0]["t_start_s"] == 0.0
        assert result[-1]["t_end_s"] == 20.0
        for i in range(len(result) - 1):
            assert result[i]["t_end_s"] == result[i + 1]["t_start_s"]

    def test_normalize_beats_empty(self):
        assert _normalize_beats([], target_seconds=30) == []


class TestIsGenericPlaceholderBeats:
    def test_detects_generic_content(self):
        beats = [
            {"vo_line": "Quick topic fact you probably missed."},
            {"vo_line": "Today: facts about stuff."},
            {"vo_line": "Core idea in plain English."},
            {"vo_line": "Why it matters to you."},
            {"vo_line": "One example that clicks."},
            {"vo_line": "The takeaway is simple."},
            {"vo_line": "Want more quick facts like this?"},
        ]
        assert _is_generic_placeholder_beats(beats) is True

    def test_real_content_not_flagged(self):
        beats = [
            {"vo_line": "The Tiger tank weighed 54 tonnes."},
            {"vo_line": "Its 88mm gun could pierce 150mm of armor."},
        ]
        assert _is_generic_placeholder_beats(beats) is False


class TestExtractBeatsFromScriptContent:
    def test_converts_script_content_format(self):
        sp = {
            "script_content": [
                {"segment_id": "intro", "text": "Welcome to facts.", "duration_seconds": 5},
                {"segment_id": "fact_one", "text": "Here is fact one.", "duration_seconds": 10},
            ]
        }
        beats = _extract_beats_from_script_content(sp)
        assert len(beats) == 2
        assert beats[0]["vo_line"] == "Welcome to facts."
        assert beats[0]["on_screen_text"] == "Intro"
        assert beats[1]["on_screen_text"] == "Fact One"

    def test_no_script_content(self):
        assert _extract_beats_from_script_content({}) == []


class TestValidateOrFixScriptPackage:
    def test_fixes_bad_timestamps(self):
        sp = {
            "script": {
                "voiceover": "A. B.",
                "beats": [
                    {"t_start_s": -1.0, "t_end_s": 3.0, "on_screen_text": "A", "vo_line": "A sentence."},
                    {"t_start_s": 3.0, "t_end_s": 6.0, "on_screen_text": "B", "vo_line": "B sentence."},
                ],
            }
        }
        tb = {"format": {"target_duration_seconds": 30}}
        result = _validate_or_fix_script_package(sp, tb, None)
        beats = result["script"]["beats"]
        assert beats[0]["t_start_s"] == 0.0
        assert beats[-1]["t_end_s"] == 30.0


class TestGenerateOfflineScriptPackage:
    def test_produces_valid_output(self):
        tb = {
            "topic_id": "ww2_tanks",
            "subtopic_id": "tiger_tank",
            "angle": "Most feared tank of WW2",
        }
        result = generate_offline_script_package(tb)
        assert result["schema_version"] == "1.0.0"
        assert result["topic_id"] == "ww2_tanks"
        assert result["script_package_id"].startswith("sg_")
        beats = result["script"]["beats"]
        assert len(beats) > 0
        assert beats[0]["t_start_s"] == 0.0
        assert result["script"]["voiceover"]
