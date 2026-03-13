"""Stage 7: Music Selection

Tests MusicAgent → MusicSelection (audio timeline → background track).

What this stage does:
  - Reads total duration from AudioTimeline
  - Selects a background music track from local assets
  - Measures track duration via ffprobe
  - Emits a MusicSelection artifact with file path and volume settings

Human review checklist:
  - Music track exists and is playable
  - Mood/tone is appropriate for the topic (e.g. dramatic for military history)
  - Volume level (-18 dB default) won't overpower the voiceover
  - Track duration is sufficient to cover the full video duration
  - If the track is too short, looping behaviour is acceptable

Run:
    pytest tests/integration/test_stage_07_music_selection.py -v -s -m integration

Requires:
    ffprobe    on PATH (for duration measurement)
    assets/music/default_music.mp3    present in repo

Input fixture:
    tests/fixtures/script_package_ww2_tanks.json
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from video_agent.artifacts.io import write_json
from video_agent.audio_agent import create_audio_agent
from video_agent.music_agent import create_music_agent
from video_agent.video_planner import script_package_to_video_plan
from .helpers import load_fixture, copy_to_review


@pytest.mark.integration
def test_music_selection_produces_valid_selection(tmp_path: Path) -> None:
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe not found on PATH")

    script_package = load_fixture("script_package_ww2_tanks.json")
    video_plan = script_package_to_video_plan(script_package=script_package)
    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = "silent"

    audio_agent = create_audio_agent(output_dir=tmp_path, voice="silent")
    audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)

    music_agent = create_music_agent()
    music_selection = music_agent.select_music(audio_timeline)

    music_path = Path(music_selection.get("music_file_path", ""))
    assert music_path.exists(), f"Music file not found: {music_path}"
    assert music_selection.get("target_duration_s", 0) > 0, "Zero target duration"

    write_json(tmp_path / "audio_timeline.json", audio_timeline)
    write_json(tmp_path / "music_selection.json", music_selection)
    review = copy_to_review(tmp_path, "07_music_selection")

    print(f"\n--- Human Review: Music Selection ---")
    print(f"Music file: {music_path}")
    print(f"Source duration: {music_selection.get('source_duration_s')}s")
    print(f"Target duration: {music_selection.get('target_duration_s')}s")
    print(f"Volume: {music_selection.get('volume_db')} dB")
    print(f"Review dir: {review}")
    print(f"Listen: {music_path}")
    print(f"Check: mood/tone suits the topic")
    print(f"Check: volume won't overpower the voiceover")
    print(f"Check: track is long enough or loops acceptably")
