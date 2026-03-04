"""Run reusable full pipeline for any fact topic.

Example:
    python scripts/run_full_pipeline.py --topic-name "World War 1 Tanks" --query "world war 1 tanks facts explained"
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.full_pipeline_runner import FullPipelineConfig, FullPipelineRunner


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run end-to-end facts pipeline for a topic.")
    parser.add_argument("--topic-name", required=True, help="Human-readable topic name.")
    parser.add_argument("--query", required=True, help="YouTube mining query.")
    parser.add_argument("--topic-id", default=None, help="Optional explicit topic id slug.")
    parser.add_argument("--subtopic-id", default="facts", help="Subtopic id.")
    parser.add_argument("--angle", default=None, help="Optional content angle for script generation.")
    parser.add_argument("--duration", type=int, default=35, help="Target duration in seconds.")
    parser.add_argument("--max-videos", type=int, default=3, help="Max videos to mine.")
    parser.add_argument(
        "--voice-mode",
        default="auto",
        help="auto|real|silent or explicit voice preset/id",
    )
    parser.add_argument(
        "--render-engine",
        default="ffmpeg",
        choices=["ffmpeg", "dry_run"],
        help="Render engine.",
    )
    parser.add_argument(
        "--force-fallback-facts",
        action="store_true",
        help="Skip mining and use fallback seeded facts.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the full pipeline and print output locations."""
    args = parse_args()

    runner = FullPipelineRunner(project_root=PROJECT_ROOT)
    config = FullPipelineConfig(
        topic_name=args.topic_name,
        topic_query=args.query,
        topic_id=args.topic_id,
        subtopic_id=args.subtopic_id,
        angle=args.angle,
        target_duration_seconds=args.duration,
        max_videos=args.max_videos,
        force_fallback_facts=bool(args.force_fallback_facts),
        voice_mode=args.voice_mode,
        render_engine=args.render_engine,
        output_prefix="full_pipeline",
    )

    result = runner.run(config=config)

    print(f"RUN_DIR={result['run_dir']}")
    print(f"FINAL_MP4={result['final_mp4']}")
    print(f"FINAL_MP4_EXISTS={result['final_mp4_exists']}")
    print(f"FINAL_MP4_SIZE_BYTES={result['final_mp4_size_bytes']}")
    print(f"FACTS_COUNT={result['facts_count']}")
    print(f"SEEDED_FALLBACK={result['seeded_fallback']}")
    print(f"VOICE_MODE={result['voice_mode']}")


if __name__ == "__main__":
    main()
