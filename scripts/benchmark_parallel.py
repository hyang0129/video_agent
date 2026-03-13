#!/usr/bin/env python3
"""Benchmark serial vs parallel orchestrator execution.

Runs the same fixture through ProductionOrchestrator in both serial and
parallel MCP modes, then prints a timing comparison table.

Usage:
    python scripts/benchmark_parallel.py [--fixture PATH]

Requires: TTS backend available (chatterbox_server or elevenlabs).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.artifacts.io import ensure_run_dir, new_run_id
from src.artifacts.screenplay import screenplay_to_script_package
from src.config import RESULTS_DIR
from src.orchestrator import ProductionOrchestrator
from src.screenwriting.screenplay_agent import ScreenplayAgent
from src.video_planner import script_package_to_video_plan


DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "script_package_ww2_tanks.json"


def _build_minimal_screenplay(script_package: dict) -> dict:
    """Build a minimal screenplay dict from a script_package for the orchestrator."""
    scenes = []
    for seg in (script_package.get("script", {}).get("segments") or []):
        scenes.append({
            "scene_id": f"scene_{seg.get('segment_id', 0):02d}",
            "vo_line": seg.get("audio_narration", ""),
            "visual": seg.get("visual_description", ""),
            "duration_s": seg.get("duration_seconds", 5),
        })
    return {
        "title": script_package.get("title", "Benchmark"),
        "scenes": scenes,
    }


def run_benchmark(fixture_path: Path) -> None:
    script_package = json.loads(fixture_path.read_text(encoding="utf-8"))
    screenplay = _build_minimal_screenplay(script_package)
    video_plan = script_package_to_video_plan(script_package)
    screenplay_agent = ScreenplayAgent()

    results = {}
    for mode_name, serial_flag in [("mcp-serial", True), ("mcp-parallel", False)]:
        run_id = new_run_id("benchmark", mode_name)
        run_dir = ensure_run_dir(RESULTS_DIR, run_id)

        print(f"\n{'='*60}")
        print(f"[INFO] Running benchmark: {mode_name}")
        print(f"[INFO] Run dir: {run_dir}")
        print(f"{'='*60}\n")

        t0 = time.monotonic()
        try:
            orch = ProductionOrchestrator()
            orch.run(
                screenplay=screenplay,
                script_package=script_package,
                video_plan=video_plan,
                run_dir=run_dir,
                screenplay_agent=screenplay_agent,
                voice="narrator",
                serial=serial_flag,
            )
        except Exception as exc:
            print(f"[ERROR] {mode_name} failed: {exc}")
            continue
        wall_clock = round(time.monotonic() - t0, 2)

        # Read production_report for tool timings
        report_path = run_dir / "production_report.json"
        report = {}
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))

        tool_timings = report.get("tool_timings", {})
        results[mode_name] = {
            "wall_clock_s": wall_clock,
            "production_s": report.get("production_elapsed_s", wall_clock),
            "audio_s": tool_timings.get("generate_audio", 0.0),
            "image_s": tool_timings.get("fetch_assets", 0.0),
        }

    if not results:
        print("[ERROR] No benchmark results collected.")
        sys.exit(1)

    # Print comparison table
    print(f"\n{'='*70}")
    print("BENCHMARK RESULTS")
    print(f"{'='*70}")
    print(f"{'Mode':<16} | {'Wall (s)':>10} | {'Production (s)':>14} | {'Audio (s)':>10} | {'Image (s)':>10} | {'Speedup':>8}")
    print(f"{'-'*16}-+-{'-'*10}-+-{'-'*14}-+-{'-'*10}-+-{'-'*10}-+-{'-'*8}")

    baseline = results.get("mcp-serial", {}).get("wall_clock_s", 1.0)
    for mode_name, data in results.items():
        speedup = baseline / data["wall_clock_s"] if data["wall_clock_s"] > 0 else 0
        print(
            f"{mode_name:<16} | {data['wall_clock_s']:>10.2f} | {data['production_s']:>14.2f} "
            f"| {data['audio_s']:>10.2f} | {data['image_s']:>10.2f} | {speedup:>7.2f}x"
        )
    print(f"{'='*70}")

    # Write machine-readable results
    benchmark_path = RESULTS_DIR / "benchmark_results.json"
    benchmark_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[INFO] Machine-readable results: {benchmark_path}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark serial vs parallel orchestrator execution.")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help=f"Path to script_package fixture (default: {DEFAULT_FIXTURE})",
    )
    args = parser.parse_args()

    if not args.fixture.exists():
        print(f"[ERROR] Fixture not found: {args.fixture}")
        sys.exit(1)

    run_benchmark(args.fixture)


if __name__ == "__main__":
    main()
