"""Run Star Wars render with live logging and sensible defaults.

Usage:
    python scripts/run_starwars_render_with_logs.py

Defaults are preconfigured for the current Star Wars troubleshooting flow, so
no arguments are required.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def _default_render_spec() -> Path:
    """Resolve a default RenderSpecification for Star Wars troubleshooting.

    Returns:
        Path to a render_spec.json file. Prefers the latest
        ``results/star_wars_words_*/render_spec.json`` and falls back to the
        known run from this debugging session.
    """
    project_root = Path(__file__).resolve().parents[1]
    candidates = sorted(
        project_root.glob("results/star_wars_words_*/render_spec.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]

    return project_root / "results" / "star_wars_words_20260218_174827" / "render_spec.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments for the render wrapper.
    """
    project_root = Path(__file__).resolve().parents[1]
    default_log_name = f"starwars_render_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    parser = argparse.ArgumentParser(description="Run Star Wars render with live logs.")
    parser.add_argument(
        "--render-spec",
        type=Path,
        default=_default_render_spec(),
        help="Path to render_spec.json. Defaults to latest star_wars_words run.",
    )
    parser.add_argument("--engine", choices=["ffmpeg", "dry_run"], default="ffmpeg")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay-s", type=float, default=2.0)
    parser.add_argument("--min-bytes", type=int, default=100000)
    parser.add_argument(
        "--log-file",
        type=Path,
        default=project_root / "results" / default_log_name,
        help="Combined stdout/stderr log path.",
    )
    return parser.parse_args()


def run_with_live_logs(command: list[str], log_file: Path, cwd: Path) -> int:
    """Run a command and stream output to terminal + log file.

    Args:
        command: Command and args to execute.
        log_file: Destination file for combined output logs.
        cwd: Working directory for process execution.

    Returns:
        Process exit code.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w", encoding="utf-8") as handle:
        handle.write("COMMAND: " + " ".join(command) + "\n")
        handle.flush()

        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if proc.stdout is None:
            return proc.wait()

        for line in proc.stdout:
            print(line, end="")
            handle.write(line)
            handle.flush()

        return proc.wait()


def main() -> None:
    """Entry point for Star Wars render wrapper."""
    args = parse_args()

    project_root = Path(__file__).resolve().parents[1]
    render_spec = args.render_spec.expanduser().resolve()
    log_file = args.log_file.expanduser().resolve()

    if not render_spec.exists():
        raise FileNotFoundError(f"RenderSpecification not found: {render_spec}")

    min_bytes = args.min_bytes
    if args.engine == "dry_run" and min_bytes == 100000:
        min_bytes = 0

    command = [
        sys.executable,
        str(project_root / "scripts" / "run_render.py"),
        str(render_spec),
        "--engine",
        args.engine,
        "--attempts",
        str(args.attempts),
        "--retry-delay-s",
        str(args.retry_delay_s),
        "--min-bytes",
        str(min_bytes),
    ]

    print(f"RENDER_SPEC={render_spec}")
    print(f"LOG_FILE={log_file}")
    print("Starting render...\n")

    code = run_with_live_logs(command=command, log_file=log_file, cwd=project_root)
    if code != 0:
        raise SystemExit(code)

    print("\nRender completed successfully.")


if __name__ == "__main__":
    main()