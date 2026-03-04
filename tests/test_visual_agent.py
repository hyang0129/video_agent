"""Tests for VisualAssetAgent.

Run with: pytest tests/test_visual_agent.py -v
"""

from pathlib import Path

import pytest

from src.visual_agent import VisualAssetAgent


@pytest.fixture
def sample_video_plan() -> dict:
    return {
        "schema_version": "1.0.0",
        "created_at": "2026-02-02T12:00:00Z",
        "video_plan_id": "vp_test_123",
        "scenes": [
            {
                "scene_id": "scene_01",
                "t_start_s": 0.0,
                "t_end_s": 5.0,
                "vo_line": "Hello world.",
                "on_screen_text": "HELLO",
                "asset_prompts": ["hello background"],
            },
            {
                "scene_id": "scene_02",
                "t_start_s": 5.0,
                "t_end_s": 10.0,
                "vo_line": "Second line.",
                "on_screen_text": "SECOND",
                "asset_prompts": ["second background"],
            },
        ],
    }


def test_visual_manifest_placeholder_assets(tmp_path: Path, sample_video_plan: dict) -> None:
    agent = VisualAssetAgent(
        output_dir=tmp_path,
        image_sources=(),  # force placeholder path
        content_validator="none",
    )

    manifest = agent.generate_visual_manifest(sample_video_plan)

    assert manifest["schema_version"] == "1.0.0"
    assert manifest["video_plan_ref"] == "vp_test_123"
    assert manifest["total_assets"] == 2

    assets = manifest["assets"]
    assert len(assets) == 2

    for asset in assets:
        assert asset["source"] == "placeholder"
        file_path = tmp_path / asset["file_path"]
        assert file_path.exists()
        assert file_path.suffix.lower() == ".bmp"
        assert asset["content_safety"]["validated"] is True
