"""Debug render execution for a specific RenderSpecification file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_agent.render_agent import RenderError, create_render_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug a single render_spec with ffmpeg.")
    parser.add_argument("render_spec", type=Path)
    parser.add_argument("--engine", default="ffmpeg", choices=["ffmpeg", "dry_run"])
    args = parser.parse_args()

    render_spec_path = args.render_spec.expanduser().resolve()
    run_dir = render_spec_path.parent
    render_spec = json.loads(render_spec_path.read_text(encoding="utf-8"))

    print(f"RUN_DIR={run_dir}")
    print(f"ENGINE={args.engine}")

    agent = create_render_agent(output_dir=run_dir, engine=args.engine)
    try:
        result = agent.render(render_spec)
        print("RENDER_OK=True")
        print(f"VIDEO={run_dir / result.get('video_file_path', 'final_video.mp4')}")
        print(f"SIZE={Path(run_dir / result.get('video_file_path', 'final_video.mp4')).stat().st_size}")
    except RenderError as exc:
        print("RENDER_OK=False")
        print(str(exc))
        raise


if __name__ == "__main__":
    main()