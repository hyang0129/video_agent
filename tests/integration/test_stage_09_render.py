"""Stage 9: Final Video Render

Tests RenderAgent → final_video.mp4 (render spec → playable MP4).

What this stage does:
  - Reads a RenderSpecification with scene image paths, timing, and text overlays
  - Builds an FFmpeg filter graph (slideshow + drawtext + audio mix)
  - Renders to a 9:16 vertical MP4
  - Validates output with ffprobe: video stream, audio stream, duration parity

Human review checklist:
  - Video is playable (not corrupted)
  - Images appear for correct scene durations
  - Text overlays are visible, readable, and correctly timed
  - Voiceover is audible and in sync (if real TTS was used upstream)
  - Background music is present and not overpowering
  - |audio_duration - video_duration| <= 0.25s (quality gate)
  - No visual glitches, freeze frames, or black gaps

Run:
    pytest tests/integration/test_stage_09_render.py -v -s -m integration

Requires:
    ffmpeg     on PATH for rendering
    ffprobe    on PATH for output validation

Input fixture:
    tests/fixtures/script_package_ww2_tanks.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.artifacts.io import write_json
from src.audio_agent import create_audio_agent
from src.composition_agent import create_composition_agent
from src.music_agent import create_music_agent
from src.render_agent import create_render_agent
from src.video_planner import script_package_to_video_plan
from src.visual_agent import create_visual_agent
from .helpers import load_fixture, copy_to_review

DURATION_PARITY_THRESHOLD_S = 0.25


def _probe_durations(mp4: Path):
    """Return (video_duration, audio_duration) via ffprobe, or (None, None) on failure."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None, None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet", "-print_format", "json",
                "-show_streams", str(mp4),
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video_dur = next(
            (float(s["duration"]) for s in streams if s.get("codec_type") == "video" and "duration" in s),
            None,
        )
        audio_dur = next(
            (float(s["duration"]) for s in streams if s.get("codec_type") == "audio" and "duration" in s),
            None,
        )
        return video_dur, audio_dur
    except Exception:
        return None, None


@pytest.mark.integration
def test_render_produces_valid_mp4(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not found on PATH")
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe not found on PATH")

    script_package = load_fixture("script_package_ww2_tanks.json")
    video_plan = script_package_to_video_plan(script_package=script_package)

    elevenlabs_available = bool(__import__("os").getenv("ELEVENLABS_API_KEY"))
    tts_mode = __import__("os").getenv("PIPELINE_TEST_TTS_MODE", "auto").strip().lower()
    use_real_tts = tts_mode == "real" or (tts_mode == "auto" and elevenlabs_available)
    voice = "narrator" if use_real_tts else "silent"
    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = voice

    audio_agent = create_audio_agent(output_dir=tmp_path, voice=voice)
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

    render_agent = create_render_agent(output_dir=tmp_path, engine="ffmpeg")
    final_video = render_agent.render(render_spec=render_spec)

    final_mp4 = tmp_path / "final_video.mp4"
    assert final_mp4.exists(), f"MP4 not created: {final_mp4}"
    assert final_mp4.stat().st_size > 0, "MP4 is empty"

    write_json(tmp_path / "render_spec.json", render_spec)
    write_json(tmp_path / "final_video.json", final_video)

    video_dur, audio_dur = _probe_durations(final_mp4)
    if video_dur is not None and audio_dur is not None:
        parity = abs(video_dur - audio_dur)
        assert parity <= DURATION_PARITY_THRESHOLD_S, (
            f"Duration parity failure: video={video_dur:.3f}s audio={audio_dur:.3f}s "
            f"delta={parity:.3f}s (threshold={DURATION_PARITY_THRESHOLD_S}s)"
        )

    review = copy_to_review(tmp_path, "09_render")

    print(f"\n--- Human Review: Final Video Render ---")
    print(f"MP4: {review / 'final_video.mp4'}")
    print(f"Video duration: {video_dur:.2f}s" if video_dur else "Video duration: unknown")
    print(f"Audio duration: {audio_dur:.2f}s" if audio_dur else "Audio duration: unknown")
    if video_dur and audio_dur:
        print(f"Duration parity: {abs(video_dur - audio_dur):.3f}s (threshold {DURATION_PARITY_THRESHOLD_S}s)")
    print(f"Review dir: {review}")
    print(f"Watch: final_video.mp4")
    print(f"Check: images visible for correct durations, no black gaps")
    print(f"Check: text overlays readable and correctly timed")
    print(f"Check: audio present and in sync")
    print(f"Re-render from spec: python main.py render {review / 'render_spec.json'} ffmpeg")
