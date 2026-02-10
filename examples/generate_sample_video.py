"""Generate a self-contained sample video run.

This script creates a small, offline-safe pipeline run under `results/`:
- Writes a minimal VideoPlan (3 scenes)
- Writes a minimal AudioTimeline using a bundled silent MP3 for each scene
- Generates a VisualManifest with deterministic placeholder BMPs (no external APIs)
- Creates a RenderSpecification
- Renders a final video using FFmpeg if available; otherwise uses a dry-run renderer

Run:
    py examples/generate_sample_video.py

Outputs:
    results/sample_*/video_plan.json
    results/sample_*/audio_timeline.json
    results/sample_*/visual_manifest.json
    results/sample_*/render_spec.json
    results/sample_*/final_video.mp4
    results/sample_*/final_video.json
"""

from __future__ import annotations

from pathlib import Path
import sys
import shutil
import subprocess
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.artifacts.io import ensure_run_dir, new_run_id, write_json
from src.config import RESULTS_DIR
from src.visual_agent import create_visual_agent
from src.composition_agent import create_composition_agent
from src.render_agent import create_render_agent


def _make_sample_video_plan() -> Dict[str, Any]:
    """Create a minimal VideoPlan with 3 scenes."""
    scenes: List[Dict[str, Any]] = [
        {
            "scene_id": "scene_01",
            "t_start_s": 0.0,
            "t_end_s": 3.0,
            "vo_line": "Here is a quick sample scene one.",
            "on_screen_text": "SAMPLE SCENE 1",
            "visual_direction": "simple abstract background",
            "asset_prompts": ["abstract gradient background"],
        },
        {
            "scene_id": "scene_02",
            "t_start_s": 3.0,
            "t_end_s": 6.0,
            "vo_line": "Scene two continues the story.",
            "on_screen_text": "SAMPLE SCENE 2",
            "visual_direction": "simple abstract background",
            "asset_prompts": ["geometric shapes background"],
        },
        {
            "scene_id": "scene_03",
            "t_start_s": 6.0,
            "t_end_s": 9.0,
            "vo_line": "And scene three wraps it up.",
            "on_screen_text": "SAMPLE SCENE 3",
            "visual_direction": "simple abstract background",
            "asset_prompts": ["soft texture background"],
        },
    ]

    return {
        "schema_version": "1.0.0",
        "created_at": "2026-02-03T00:00:00Z",
        "video_plan_id": "vp_sample",
        "topic_id": "sample",
        "subtopic_id": "demo",
        "inputs": {"script_package_ref": None, "creative_spec": None},
        "audio": {"tts": {"enabled": False, "voice": "narrator"}},
        "subtitles": {"enabled": True, "style": "large, high-contrast"},
        "scenes": scenes,
    }


def _make_sample_audio_timeline(run_dir: Path, video_plan: Dict[str, Any]) -> Dict[str, Any]:
    """Create a minimal AudioTimeline with silent MP3 segments.

    Args:
        run_dir: The run directory that will contain `audio_segments/`.
        video_plan: VideoPlan providing scene IDs and timing.

    Returns:
        AudioTimeline dict.

    Raises:
        FileNotFoundError: If the bundled silent MP3 is missing.
    """
    ffmpeg = shutil.which("ffmpeg")
    silent_src = RESULTS_DIR / "test_silent_mp3" / "test_silent_1sec.mp3"
    if not ffmpeg and not silent_src.exists():
        raise FileNotFoundError(
            f"Neither ffmpeg nor bundled silent MP3 found. Missing: {silent_src}"
        )

    audio_segments_dir = run_dir / "audio_segments"
    audio_segments_dir.mkdir(parents=True, exist_ok=True)

    tracks: List[Dict[str, Any]] = []
    scenes = video_plan.get("scenes")
    assert isinstance(scenes, list)

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "")
        if not scene_id:
            continue

        t_start = float(scene.get("t_start_s") or 0.0)
        t_end = float(scene.get("t_end_s") or 0.0)
        if t_end <= t_start:
            continue

        out_name = f"vo_{scene_id}.mp3"
        out_path = audio_segments_dir / out_name
        dur = t_end - t_start

        if ffmpeg:
            # Generate a valid silent MP3 matching the scene duration.
            # Using -f lavfi anullsrc avoids needing any bundled assets.
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=stereo",
                "-t",
                f"{dur:.3f}",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "9",
                str(out_path),
            ]
            subprocess.run(cmd, check=True)
        else:
            # Fallback: copy the bundled 1s silent file.
            shutil.copyfile(silent_src, out_path)

        tracks.append(
            {
                "type": "voiceover",
                "scene_id": scene_id,
                "t_start_s": round(t_start, 2),
                "t_end_s": round(t_end, 2),
                "file": f"audio_segments/{out_name}",
                "volume_db": 0,
            }
        )

    duration_seconds = max((float(t.get("t_end_s") or 0.0) for t in tracks), default=0.0)

    return {
        "schema_version": "1.0.0",
        "created_at": "2026-02-03T00:00:00Z",
        "audio_timeline_id": "at_sample",
        "video_plan_ref": video_plan.get("video_plan_id", "unknown"),
        "duration_seconds": round(duration_seconds, 2),
        "tracks": tracks,
    }


def main() -> None:
    """Generate a sample run folder and (if possible) render a video."""
    run_id = new_run_id("sample", "demo")
    run_dir = ensure_run_dir(RESULTS_DIR, run_id)

    video_plan = _make_sample_video_plan()
    audio_timeline = _make_sample_audio_timeline(run_dir=run_dir, video_plan=video_plan)

    write_json(run_dir / "video_plan.json", video_plan)
    write_json(run_dir / "audio_timeline.json", audio_timeline)

    visual_agent = create_visual_agent(output_dir=run_dir, image_sources=(), content_validator="none")
    visual_manifest = visual_agent.generate_visual_manifest(video_plan)

    composition_agent = create_composition_agent(output_dir=run_dir)
    render_spec = composition_agent.create_render_specification(video_plan, audio_timeline, visual_manifest)

    ffmpeg_available = shutil.which("ffmpeg") is not None
    engine = "ffmpeg" if ffmpeg_available else "dry_run"
    render_agent = create_render_agent(output_dir=run_dir, engine=engine)
    final_video = render_agent.render(render_spec)

    write_json(run_dir / "final_video.json", final_video)

    print(f"\n✅ Sample run created: {run_dir}")
    print(f"- Engine: {engine}")
    print(f"- Video:  {run_dir / 'final_video.mp4'}")
    if not ffmpeg_available:
        print("\nNote: ffmpeg was not found on PATH, so a dry-run placeholder MP4 was written.")
        print("Install ffmpeg and re-run to render a real slideshow video.")


if __name__ == "__main__":
    main()
