"""Create a Star Wars fact video with on-screen words from voice lines.

This script reuses an existing Star Wars pipeline run's script/audio artifacts,
rebuilds text overlays from each scene's `vo_line`, and renders a new MP4.
"""

from __future__ import annotations

import argparse
import json
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.artifacts.io import write_json
from src.composition_agent import create_composition_agent
from src.render_agent import create_render_agent
from src.visual_agent import create_visual_agent


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Render Star Wars video with subtitle text synthesized from vo_line content.",
    )
    parser.add_argument(
        "--source-run",
        type=Path,
        default=Path("results/star_wars_pipeline_20260216_175137"),
        help="Path to existing Star Wars run containing script/audio artifacts.",
    )
    parser.add_argument(
        "--output-run",
        type=Path,
        default=None,
        help="Optional output run directory. Defaults to results/star_wars_words_<timestamp>.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file as dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def _build_video_plan_words(video_plan: Dict[str, Any]) -> Dict[str, Any]:
    """Copy VideoPlan and replace on-screen text with spoken voice lines."""
    updated = deepcopy(video_plan)
    scenes = updated.get("scenes")
    if not isinstance(scenes, list):
        return updated

    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        vo_line = str(scene.get("vo_line") or "").strip()
        if vo_line:
            scene["on_screen_text"] = vo_line
    return updated


def main() -> None:
    """Generate a Star Wars words-overlay video from existing artifacts."""
    args = parse_args()

    source_run = args.source_run.expanduser().resolve()
    if not source_run.exists():
        raise FileNotFoundError(f"Source run not found: {source_run}")

    if args.output_run is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_run = (Path("results") / f"star_wars_words_{stamp}").resolve()
    else:
        output_run = args.output_run.expanduser().resolve()

    output_run.mkdir(parents=True, exist_ok=True)

    video_plan = _load_json(source_run / "video_plan.json")
    audio_timeline = _load_json(source_run / "audio_timeline.json")
    script_package = _load_json(source_run / "script_package.json")

    video_plan_words = _build_video_plan_words(video_plan=video_plan)

    write_json(output_run / "video_plan.json", video_plan_words)
    write_json(output_run / "audio_timeline.json", audio_timeline)
    write_json(output_run / "script_package.json", script_package)

    src_audio_segments = source_run / "audio_segments"
    if src_audio_segments.exists():
        shutil.copytree(src_audio_segments, output_run / "audio_segments", dirs_exist_ok=True)

    voiceover_master = source_run / "voiceover_master.mp3"
    if voiceover_master.exists():
        shutil.copy2(voiceover_master, output_run / "voiceover_master.mp3")

    visual_agent = create_visual_agent(output_dir=output_run)
    visual_manifest = visual_agent.generate_visual_manifest(video_plan_words)
    write_json(output_run / "visual_manifest.json", visual_manifest)

    composition_agent = create_composition_agent(output_dir=output_run)
    render_spec = composition_agent.create_render_specification(
        video_plan=video_plan_words,
        audio_timeline=audio_timeline,
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