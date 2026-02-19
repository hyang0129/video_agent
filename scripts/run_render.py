"""Run a render from a RenderSpecification with validation and retries.

This utility helps avoid silently keeping truncated MP4 files by:
- removing stale outputs before each attempt,
- executing the existing render pipeline,
- validating the produced MP4 with ffprobe,
- retrying render attempts when validation fails.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from src.artifacts.io import write_json
from src.render_agent import RenderError, create_render_agent


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Returns:
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Render video from RenderSpecification with retries.")
    parser.add_argument("render_spec", type=Path, help="Path to render_spec.json")
    parser.add_argument("--engine", choices=["ffmpeg", "dry_run"], default="ffmpeg")
    parser.add_argument("--attempts", type=int, default=3, help="Max render attempts.")
    parser.add_argument("--retry-delay-s", type=float, default=2.0, help="Delay between attempts in seconds.")
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=100_000,
        help="Minimum output size required for a valid MP4.",
    )
    return parser.parse_args()


def _load_render_spec(path: Path) -> Dict[str, Any]:
    """Load a RenderSpecification JSON file.

    Args:
        path: Path to render_spec JSON file.

    Returns:
        RenderSpecification dictionary.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_mp4(mp4_path: Path, min_bytes: int) -> Tuple[bool, str]:
    """Verify that an MP4 is playable and has valid container metadata.

    Args:
        mp4_path: Path to generated MP4.
        min_bytes: Minimum required file size.

    Returns:
        Tuple of (is_valid, details).
    """
    if not mp4_path.exists():
        return False, "missing output file"

    size = mp4_path.stat().st_size
    if size < min_bytes:
        return False, f"output too small ({size} bytes < {min_bytes})"

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        str(mp4_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "ffprobe not found on PATH"

    if proc.returncode != 0:
        details = proc.stderr.strip() or "ffprobe failed"
        return False, details

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, "ffprobe returned invalid JSON"

    duration = float(payload.get("format", {}).get("duration") or 0.0)
    if duration <= 0.0:
        return False, "duration <= 0"

    return True, f"duration={duration:.3f}s size={size}"


def _cleanup_previous_outputs(run_dir: Path) -> None:
    """Remove previous output artifacts before a new render attempt.

    Args:
        run_dir: Directory where render outputs are written.
    """
    for rel in ["final_video.mp4", "final_video.json"]:
        path = run_dir / rel
        if path.exists():
            path.unlink()


def main() -> None:
    """Run render with retries and output validation."""
    args = parse_args()

    render_spec_path = args.render_spec.expanduser().resolve()
    if not render_spec_path.exists():
        raise FileNotFoundError(f"RenderSpecification not found: {render_spec_path}")

    render_spec = _load_render_spec(render_spec_path)
    run_dir = render_spec_path.parent

    print(f"RUN_DIR={run_dir}")
    print(f"ENGINE={args.engine}")
    print(f"ATTEMPTS={args.attempts}")

    last_error = "unknown"

    for attempt in range(1, max(1, args.attempts) + 1):
        print(f"\n--- Attempt {attempt}/{args.attempts} ---")
        _cleanup_previous_outputs(run_dir)

        try:
            agent = create_render_agent(output_dir=run_dir, engine=args.engine)
            final_video = agent.render(render_spec)
            write_json(run_dir / "final_video.json", final_video)
        except RenderError as exc:
            last_error = str(exc)
            print(f"RENDER_ERROR={last_error}")
            if attempt < args.attempts:
                time.sleep(max(0.0, args.retry_delay_s))
            continue

        mp4_path = run_dir / "final_video.mp4"

        if args.engine == "dry_run":
            print("VERIFY=SKIPPED (dry_run engine)")
            print("RENDER_OK=True")
            print(f"OUTPUT_MP4={mp4_path}")
            print(f"OUTPUT_JSON={run_dir / 'final_video.json'}")
            return

        ok, details = _verify_mp4(mp4_path=mp4_path, min_bytes=args.min_bytes)
        print(f"VERIFY={ok} ({details})")
        if ok:
            print("RENDER_OK=True")
            print(f"OUTPUT_MP4={mp4_path}")
            print(f"OUTPUT_JSON={run_dir / 'final_video.json'}")
            return

        last_error = details
        if attempt < args.attempts:
            time.sleep(max(0.0, args.retry_delay_s))

    raise RuntimeError(f"Render failed after {args.attempts} attempts: {last_error}")


if __name__ == "__main__":
    main()