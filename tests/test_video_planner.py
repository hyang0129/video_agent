"""Tests for video_planner module.

Run with: pytest tests/test_video_planner.py -v
"""

import pytest

from video_agent.video_planner import script_package_to_video_plan


def _make_script_package(**overrides):
    base = {
        "schema_version": "1.0.0",
        "script_package_id": "sg_abc123",
        "topic_id": "topic_ww2_tanks",
        "subtopic_id": "sub_tiger_tank",
        "script": {
            "voiceover": "Line one. Line two.",
            "beats": [
                {"t_start_s": 0.0, "t_end_s": 5.0, "on_screen_text": "Fact 1", "vo_line": "Line one."},
                {"t_start_s": 5.0, "t_end_s": 10.0, "on_screen_text": "Fact 2", "vo_line": "Line two."},
            ],
        },
    }
    base.update(overrides)
    return base


class TestBasicConversion:
    def test_basic_conversion(self):
        sp = _make_script_package()
        vp = script_package_to_video_plan(sp)
        assert vp["schema_version"] == "1.0.0"
        assert len(vp["scenes"]) == 2
        assert vp["topic_id"] == "topic_ww2_tanks"
        assert "video_plan_id" in vp
        assert "created_at" in vp


class TestInputValidation:
    def test_invalid_input_not_dict(self):
        with pytest.raises(ValueError, match="must be a dict"):
            script_package_to_video_plan("not a dict")

    def test_missing_script(self):
        with pytest.raises(ValueError, match="script must be an object"):
            script_package_to_video_plan({"topic_id": "t"})

    def test_empty_beats(self):
        sp = _make_script_package()
        sp["script"]["beats"] = []
        with pytest.raises(ValueError, match="non-empty list"):
            script_package_to_video_plan(sp)


class TestSceneGeneration:
    def test_scene_ids_generated(self):
        sp = _make_script_package()
        for beat in sp["script"]["beats"]:
            beat.pop("scene_id", None)
        vp = script_package_to_video_plan(sp)
        assert vp["scenes"][0]["scene_id"] == "scene_01"
        assert vp["scenes"][1]["scene_id"] == "scene_02"

    def test_timestamps_preserved(self):
        sp = _make_script_package()
        vp = script_package_to_video_plan(sp)
        assert vp["scenes"][0]["t_start_s"] == 0.0
        assert vp["scenes"][0]["t_end_s"] == 5.0
        assert vp["scenes"][1]["t_start_s"] == 5.0
        assert vp["scenes"][1]["t_end_s"] == 10.0


class TestVideoPlanId:
    def test_video_plan_id_from_script_package_id(self):
        sp = _make_script_package(script_package_id="sg_abc123")
        vp = script_package_to_video_plan(sp)
        assert vp["video_plan_id"] == "vp_abc123"

    def test_video_plan_id_non_sg_prefix(self):
        sp = _make_script_package(script_package_id="other_id")
        vp = script_package_to_video_plan(sp)
        assert vp["video_plan_id"] == "vp_other_id"
