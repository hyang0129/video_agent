"""Render a fast Star Wars preview with spoken-line text overlays.

Creates a short, lower-resolution output (first N scenes) to validate that
script/audio words are synthesized as on-screen text overlays.
"""

from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from video_agent.artifacts.io import write_json
from video_agent.composition_agent import create_composition_agent
from video_agent.render_agent import create_render_agent
from video_agent.visual_agent import create_visual_agent


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Render short Star Wars words-overlay preview.")
    parser.add_argument(
        "--source-run",
        type=Path,
        default=Path("results/star_wars_pipeline_20260216_175137"),
        help="Path to existing Star Wars run.",
    )
    parser.add_argument("--scenes", type=int, default=3, help="Number of scenes to include in preview.")
    return parser.parse_args()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _select_scene_ids(video_plan: Dict[str, Any], limit: int) -> List[str]:
    scenes = video_plan.get("scenes")
    if not isinstance(scenes, list):
        return []
    scene_ids: List[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "").strip()
        if scene_id:
            scene_ids.append(scene_id)
        if len(scene_ids) >= max(1, limit):
            break
    return scene_ids


def main() -> None:
    args = parse_args()
    source_run = args.source_run.expanduser().resolve()
    if not source_run.exists():
        raise FileNotFoundError(f"Source run not found: {source_run}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_run = (Path("results") / f"star_wars_words_preview_{stamp}").resolve()
    output_run.mkdir(parents=True, exist_ok=True)

    video_plan = _load_json(source_run / "video_plan.json")
    audio_timeline = _load_json(source_run / "audio_timeline.json")
    script_package = _load_json(source_run / "script_package.json")

    selected_ids = set(_select_scene_ids(video_plan=video_plan, limit=args.scenes))
    if not selected_ids:
        raise ValueError("No scenes found in source video_plan")

    video_plan_preview = deepcopy(video_plan)
    preview_scenes: List[Dict[str, Any]] = []
    for scene in video_plan_preview.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "")
        if scene_id not in selected_ids:
            continue
        vo_line = str(scene.get("vo_line") or "").strip()
        if vo_line:
            scene["on_screen_text"] = vo_line
        preview_scenes.append(scene)
    video_plan_preview["scenes"] = preview_scenes

    preview_tracks: List[Dict[str, Any]] = []
    for track in audio_timeline.get("tracks", []):
        if not isinstance(track, dict):
            continue
        scene_id = str(track.get("scene_id") or "")
        if scene_id in selected_ids:
            preview_tracks.append(track)

    audio_timeline_preview = deepcopy(audio_timeline)
    audio_timeline_preview["tracks"] = preview_tracks
    audio_timeline_preview["duration_seconds"] = max((float(t.get("t_end_s") or 0.0) for t in preview_tracks), default=0.0)

    write_json(output_run / "video_plan.json", video_plan_preview)
    write_json(output_run / "audio_timeline.json", audio_timeline_preview)
    write_json(output_run / "script_package.json", script_package)

    src_audio_segments = source_run / "audio_segments"
    if src_audio_segments.exists():
        shutil.copytree(src_audio_segments, output_run / "audio_segments", dirs_exist_ok=True)

    visual_agent = create_visual_agent(output_dir=output_run)
    visual_manifest = visual_agent.generate_visual_manifest(video_plan_preview)
    write_json(output_run / "visual_manifest.json", visual_manifest)

    composition_agent = create_composition_agent(output_dir=output_run, resolution=(540, 960), fps=24)
    render_spec = composition_agent.create_render_specification(
        video_plan=video_plan_preview,
        audio_timeline=audio_timeline_preview,
        visual_manifest=visual_manifest,
    )
    write_json(output_run / "render_spec.json", render_spec)

    render_agent = create_render_agent(output_dir=output_run, engine="ffmpeg")
    final_video = render_agent.render(render_spec)
    write_json(output_run / "final_video.json", final_video)

    mp4_path = output_run / "final_video.mp4"
    print(f"OUTPUT_RUN={output_run}")
    print(f"OUTPUT_MP4={mp4_path}")
    print(f"OUTPUT_EXISTS={mp4_path.exists()}")
    print(f"OUTPUT_SIZE_BYTES={mp4_path.stat().st_size if mp4_path.exists() else 0}")


if __name__ == "__main__":
    main()