"""Stage 5: Audio Generation

Tests AudioAgent → AudioTimeline + MP3 voiceover segments.

What this stage does:
  - Reads scene voiceover lines from VideoPlan
  - Calls ElevenLabs TTS to synthesize each line as an MP3 segment
  - Assembles an AudioTimeline with file paths and measured durations
  - Falls back to silent audio if ELEVENLABS_API_KEY is absent

Human review checklist (requires ELEVENLABS_API_KEY):
  - Each MP3 segment is audible and clearly spoken
  - Voice tone matches the topic (authoritative for history, etc.)
  - Pacing is natural — not too fast or robotic
  - No mispronunciations of key terms (tank names, battle names, etc.)
  - Segment durations roughly match the allocated beat durations
  - Audio timeline total duration is close to video target duration

Run:
    pytest tests/integration/test_stage_05_audio_generation.py -v -s -m integration

Requires:
    ELEVENLABS_API_KEY    for real TTS (silent placeholder used if absent)

Input fixture:
    tests/fixtures/script_package_ww2_tanks.json
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.artifacts.io import write_json
from src.audio_agent import create_audio_agent
from src.video_planner import script_package_to_video_plan
from .helpers import load_fixture, copy_to_review


@pytest.mark.integration
def test_audio_generation_produces_timeline_and_segments(tmp_path: Path) -> None:
    script_package = load_fixture("script_package_ww2_tanks.json")
    video_plan = script_package_to_video_plan(script_package=script_package)

    elevenlabs_available = bool(os.getenv("ELEVENLABS_API_KEY"))
    tts_mode = os.getenv("PIPELINE_TEST_TTS_MODE", "auto").strip().lower()
    use_real_tts = tts_mode == "real" or (tts_mode == "auto" and elevenlabs_available)
    voice = "narrator" if use_real_tts else "silent"

    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = voice

    audio_agent = create_audio_agent(output_dir=tmp_path, voice=voice)
    audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)

    segments = [t for t in audio_timeline.get("tracks", []) if t.get("type") == "voiceover"]
    assert segments, "No audio segments in timeline"
    assert audio_timeline.get("duration_seconds", 0) > 0, "Zero total duration"

    write_json(tmp_path / "audio_timeline.json", audio_timeline)
    review = copy_to_review(tmp_path, "05_audio_generation")

    using_real = "YES (ElevenLabs)" if use_real_tts else "NO (silent placeholder — set ELEVENLABS_API_KEY for real review)"
    print(f"\n--- Human Review: Audio Generation ---")
    print(f"Real TTS: {using_real}")
    print(f"Voice: {voice}")
    print(f"Segments: {len(segments)}")
    print(f"Total duration: {audio_timeline.get('duration_seconds', 0):.1f}s")
    print(f"Review dir: {review}")
    if use_real_tts:
        print(f"Listen: audio_segments/*.mp3")
        print(f"Check: voice is clear, pacing natural, no mispronunciations")
        print(f"Check: segment durations roughly match beat allocations")
    else:
        print(f"Re-run with ELEVENLABS_API_KEY set for audio quality review")
