"""Stage 8: Composition

Tests CompositionAgent → RenderSpecification (all artifacts → render spec).

What this stage does:
  - Combines VideoPlan, AudioTimeline, VisualManifest, and MusicSelection
  - Resolves asset paths and timing into a flat, renderable scene list
  - Emits text overlay specs (drawtext parameters) per scene
  - Produces a deterministic RenderSpecification — no LLM or external APIs

Human review checklist:
  - Every scene has a resolved image asset path that exists on disk
  - Every scene has timing that matches the AudioTimeline (not the VideoPlan beats)
  - Text overlay content is correct and matches the script on_screen_text
  - Font size, position, and color are appropriate for 9:16 vertical
  - Music track path is resolved and present in the spec
  - No missing or null asset references

Run:
    pytest tests/integration/test_stage_08_composition.py -v -s -m integration

Requires: ffprobe on PATH (for music duration)

Input fixture:
    tests/fixtures/script_package_ww2_tanks.json
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.artifacts.io import write_json
from src.audio_agent import create_audio_agent
from src.composition_agent import create_composition_agent
from src.music_agent import create_music_agent
from src.video_planner import script_package_to_video_plan
from src.visual_agent import create_visual_agent
from .helpers import load_fixture, copy_to_review


@pytest.mark.integration
def test_composition_produces_render_spec(tmp_path: Path) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe not found on PATH")

    script_package = load_fixture("script_package_ww2_tanks.json")
    video_plan = script_package_to_video_plan(script_package=script_package)
    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = "silent"

    audio_agent = create_audio_agent(output_dir=tmp_path, voice="silent")
    audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)

    visual_agent = create_visual_agent(output_dir=tmp_path, image_sources=(), content_validator="none")
    visual_manifest = visual_agent.generate_visual_manifest(video_plan=video_plan)

    music_agent = create_music_agent()
    music_selection = music_agent.select_music(audio_timeline)

    comp_agent = create_composition_agent(output_dir=tmp_path)
    render_spec = comp_agent.create_render_specification(
        video_plan=video_plan,
        audio_timeline=audio_timeline,
        visual_manifest=visual_manifest,
        music_selection=music_selection,
    )

    scenes = render_spec.get("scenes", [])
    assert scenes, "No scenes in RenderSpecification"
    for i, scene in enumerate(scenes):
        assert scene.get("image_path"), f"Scene {i} missing image_path"
        assert scene.get("t_start_s") is not None, f"Scene {i} missing t_start_s"

    write_json(tmp_path / "render_spec.json", render_spec)
    review = copy_to_review(tmp_path, "08_composition")

    print(f"\n--- Human Review: Composition ---")
    print(f"Scenes in spec: {len(scenes)}")
    print(f"Review dir: {review}")
    print(f"Check: render_spec.json — all image_path entries exist on disk")
    print(f"Check: text overlay content, font size, and position look correct")
    print(f"Check: scene timing matches audio timeline (not just script beats)")
    print(f"Check: music_path is present and resolved")
