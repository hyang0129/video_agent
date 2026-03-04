"""Tests for CompositionAgent.

Run with: pytest tests/test_composition_agent.py -v
"""

from pathlib import Path

from src.composition_agent import CompositionAgent


def test_create_render_specification_basic(tmp_path: Path) -> None:
    video_plan = {
        "schema_version": "1.0.0",
        "video_plan_id": "vp_test_123",
        "scenes": [
            {
                "scene_id": "scene_01",
                "t_start_s": 0.0,
                "t_end_s": 5.0,
                "vo_line": "Hello world.",
                "on_screen_text": "HELLO",
            },
            {
                "scene_id": "scene_02",
                "t_start_s": 5.0,
                "t_end_s": 10.0,
                "vo_line": "Second line.",
                "on_screen_text": "SECOND",
            },
        ],
    }

    audio_timeline = {
        "schema_version": "1.0.0",
        "audio_timeline_id": "at_test_123",
        "audio_file_path": "audio_master.m4a",
        "duration_seconds": 10.0,
        "tracks": [
            {
                "type": "voiceover",
                "file": "audio_segments/vo_scene_01.mp3",
                "scene_id": "scene_01",
                "t_start_s": 0.0,
                "t_end_s": 5.0,
                "volume_db": 0,
            },
            {
                "type": "voiceover",
                "file": "audio_segments/vo_scene_02.mp3",
                "scene_id": "scene_02",
                "t_start_s": 5.0,
                "t_end_s": 10.0,
                "volume_db": 0,
            },
        ],
    }

    visual_manifest = {
        "schema_version": "1.0.0",
        "visual_manifest_id": "vm_test_123",
        "assets": [
            {
                "asset_id": "asset_scene_01",
                "scene_id": "scene_01",
                "type": "image",
                "file_path": "assets/scene_01_placeholder.bmp",
            },
            {
                "asset_id": "asset_scene_02",
                "scene_id": "scene_02",
                "type": "image",
                "file_path": "assets/scene_02_placeholder.bmp",
            },
        ],
    }

    agent = CompositionAgent(output_dir=tmp_path)
    spec = agent.create_render_specification(video_plan, audio_timeline, visual_manifest)

    assert spec["schema_version"] == "1.0.0"
    assert spec["video_plan_ref"] == "vp_test_123"
    assert spec["audio_timeline_ref"] == "at_test_123"
    assert spec["visual_manifest_ref"] == "vm_test_123"

    video_layer = [l for l in spec["layers"] if l["type"] == "video"][0]
    assert len(video_layer["clips"]) == 2

    clip1 = video_layer["clips"][0]
    assert clip1["scene_id"] == "scene_01"
    assert clip1["t_start_s"] == 0.0
    assert clip1["t_end_s"] == 5.0
    assert clip1["duration_s"] == 5.0
    assert clip1["effects"]

    text_layer = [l for l in spec["layers"] if l["type"] == "text"][0]
    assert len(text_layer["elements"]) == 2
    assert text_layer["elements"][0]["text"] == "Hello world."
    assert text_layer["elements"][1]["text"] == "Second line."

    audio_layer = [l for l in spec["layers"] if l["type"] == "audio"][0]
    assert len(audio_layer["tracks"]) == 2
    assert audio_layer["tracks"][0]["type"] == "master"
    assert audio_layer["tracks"][0]["source_file"] == "audio_master.m4a"
