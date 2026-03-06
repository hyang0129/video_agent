"""Stage 6: Image Retrieval

Tests VisualAgent → VisualManifest (scene descriptions → fetched images).

What this stage does:
  - Reads scene visual descriptions from VideoPlan
  - Searches Pexels for relevant images per scene
  - Falls back to deterministic placeholder BMPs when Pexels is unavailable
  - Validates images and writes a VisualManifest with resolved asset paths

Human review checklist (requires PEXELS_API_KEY):
  - Images are visually relevant to each scene description
  - No obviously wrong or misleading images (e.g. modern tanks for WW2 scenes)
  - Image resolution is suitable for 9:16 vertical format
  - All scenes have at least one assigned image (no missing assets)
  - Placeholder BMPs are used as expected when Pexels is unavailable

Run:
    pytest tests/integration/test_stage_06_image_retrieval.py -v -s -m integration

Requires:
    PEXELS_API_KEY    for real image search (placeholder BMPs used if absent)

Input fixture:
    tests/fixtures/script_package_ww2_tanks.json
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.artifacts.io import write_json
from src.video_planner import script_package_to_video_plan
from src.visual_agent import create_visual_agent
from .helpers import load_fixture, copy_to_review


@pytest.mark.integration
def test_image_retrieval_produces_visual_manifest(tmp_path: Path) -> None:
    script_package = load_fixture("script_package_ww2_tanks.json")
    video_plan = script_package_to_video_plan(script_package=script_package)

    pexels_available = bool(os.getenv("PEXELS_API_KEY"))
    # Wikimedia Commons is always available (no key required); Pexels as fallback.
    image_sources = ("wikimedia", "pexels") if pexels_available else ("wikimedia",)

    visual_agent = create_visual_agent(
        output_dir=tmp_path,
        image_sources=image_sources,
        content_validator="none",
    )
    visual_manifest = visual_agent.generate_visual_manifest(video_plan=video_plan)

    scenes = visual_manifest.get("assets", [])
    assert scenes, "No scenes in VisualManifest"
    for i, scene in enumerate(scenes):
        assert scene.get("file_path"), f"Scene {i} has no file_path"

    write_json(tmp_path / "visual_manifest.json", visual_manifest)
    review = copy_to_review(tmp_path, "06_image_retrieval")

    sources_used = sorted({s.get("source", "unknown") for s in scenes})
    print(f"\n--- Human Review: Image Retrieval ---")
    print(f"Image sources: {image_sources}")
    print(f"Sources used in manifest: {sources_used}")
    print(f"Scenes with assets: {len(scenes)}")
    print(f"Review dir: {review}")
    print(f"Check: open each image in visual_manifest.json -- is it relevant to its scene?")
    print(f"Check: no anachronistic images (e.g. modern equipment for historical topics)")
    print(f"Check: image orientation suitable for 9:16 vertical video")
