"""Tests for VisualAssetAgent.

Run with: pytest tests/test_visual_agent.py -v
"""

from pathlib import Path

import pytest

from video_agent.visual_agent import VisualAssetAgent


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


def test_visual_manifest_schema_fields(tmp_path: Path, sample_video_plan: dict) -> None:
    agent = VisualAssetAgent(
        output_dir=tmp_path,
        image_sources=(),
        content_validator="none",
    )
    manifest = agent.generate_visual_manifest(sample_video_plan)

    assert "visual_manifest_id" in manifest
    assert manifest["visual_manifest_id"].startswith("vm_")
    assert "created_at" in manifest
    assert manifest["schema_version"] == "1.0.0"


def test_visual_manifest_single_scene(tmp_path: Path) -> None:
    plan = {
        "schema_version": "1.0.0",
        "video_plan_id": "vp_single",
        "scenes": [
            {
                "scene_id": "scene_01",
                "t_start_s": 0.0,
                "t_end_s": 10.0,
                "vo_line": "Only scene.",
                "on_screen_text": "ONLY",
                "asset_prompts": ["single background"],
            },
        ],
    }

    agent = VisualAssetAgent(
        output_dir=tmp_path,
        image_sources=(),
        content_validator="none",
    )
    manifest = agent.generate_visual_manifest(plan)

    assert manifest["total_assets"] == 1
    assert len(manifest["assets"]) == 1
    assert manifest["assets"][0]["scene_id"] == "scene_01"


def test_placeholder_bmp_is_valid_file(tmp_path: Path, sample_video_plan: dict) -> None:
    agent = VisualAssetAgent(
        output_dir=tmp_path,
        image_sources=(),
        content_validator="none",
    )
    manifest = agent.generate_visual_manifest(sample_video_plan)

    for asset in manifest["assets"]:
        bmp_path = tmp_path / asset["file_path"]
        assert bmp_path.stat().st_size > 0
        with open(bmp_path, "rb") as f:
            header = f.read(2)
            assert header == b"BM", "BMP file should start with BM magic bytes"
