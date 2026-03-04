"""Stage 4: Video Planning

Tests script_package_to_video_plan() → VideoPlan.

What this stage does:
  - Converts a ScriptPackage into a structured VideoPlan
  - Maps beats to scenes with timing, on-screen text, and voiceover lines
  - Deterministic — no LLM or external API calls

Human review checklist:
  - Scene count matches beat count in the script
  - t_start_s / t_end_s are contiguous and non-overlapping
  - vo_line and on_screen_text are present for every scene
  - Total duration matches the script target duration
  - Scene IDs are unique and well-formed

Run:
    pytest tests/integration/test_stage_04_video_planning.py -v -s -m integration

Requires: nothing (fully deterministic)

Input fixture:
    tests/fixtures/script_package_ww2_tanks.json
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.artifacts.io import write_json
from src.video_planner import script_package_to_video_plan
from .helpers import load_fixture, copy_to_review


@pytest.mark.integration
def test_video_planning_produces_valid_plan(tmp_path: Path) -> None:
    script_package = load_fixture("script_package_ww2_tanks.json")

    video_plan = script_package_to_video_plan(script_package=script_package)

    scenes = video_plan.get("scenes", [])
    assert scenes, "No scenes in VideoPlan"

    # Contiguous timing check
    for i, scene in enumerate(scenes):
        assert "t_start_s" in scene, f"Scene {i} missing t_start_s"
        assert "t_end_s" in scene, f"Scene {i} missing t_end_s"
        assert scene["t_end_s"] > scene["t_start_s"], f"Scene {i} has zero/negative duration"
        if i > 0:
            assert abs(scene["t_start_s"] - scenes[i - 1]["t_end_s"]) < 0.01, (
                f"Gap between scene {i-1} and {i}"
            )

    write_json(tmp_path / "video_plan.json", video_plan)
    review = copy_to_review(tmp_path, "04_video_planning")

    print(f"\n--- Human Review: Video Planning ---")
    print(f"Scenes: {len(scenes)}")
    print(f"Total duration: {scenes[-1]['t_end_s']:.1f}s")
    print(f"Review dir: {review}")
    print(f"Check: video_plan.json — scene timing contiguous and sensible?")
    print(f"Check: on_screen_text is short enough to display without truncation?")
