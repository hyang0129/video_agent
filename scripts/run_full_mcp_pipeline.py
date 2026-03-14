"""Full MCP pipeline run -- exercises every tool in sequence.

Usage:
    python -m scripts.run_full_mcp_pipeline [topic_brief.json]

Calls all 15 MCP tools via in-process dispatch, logging status and issues.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# In-process MCP dispatch (same handler code as the HTTPS server)
from video_agent.orchestrator import _call_tool_inprocess

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BRIEF = _PROJECT_ROOT / "tests" / "fixtures" / "topic_brief_cheese_facts.json"


def _call(tool_name: str, arguments: dict) -> Dict[str, Any]:
    """Call an MCP tool and return parsed JSON."""
    return asyncio.get_event_loop().run_until_complete(
        _call_tool_inprocess(tool_name, arguments)
    )


def _status_line(step, tool: str, result: dict, issues: List[str], allow_degraded: bool = False) -> None:
    status = result.get("status", "?")
    elapsed = result.get("elapsed_seconds", "?")
    err = result.get("error")
    if err:
        issues.append(f"Step {step} ({tool}): ERROR - {err}")
        print(f"  [{step:>2}] {tool:<30} ERROR  ({elapsed}s) -- {err[:120]}")
    elif status == "ok":
        print(f"  [{step:>2}] {tool:<30} OK     ({elapsed}s)")
    elif status == "warn":
        # warn is informational -- logged but not a failure
        print(f"  [{step:>2}] {tool:<30} WARN   ({elapsed}s)")
    elif status in ("degraded", "partial") and allow_degraded:
        # degraded/partial allowed -- logged but not a failure
        print(f"  [{step:>2}] {tool:<30} {status:<6} ({elapsed}s)")
    else:
        # degraded, partial (when not allowed), or any unknown status = failure
        issues.append(f"Step {step} ({tool}): status={status}")
        print(f"  [{step:>2}] {tool:<30} {status:<6} ({elapsed}s)")


def _check_tool_availability() -> tuple:
    """Check and prepare external tools for the pipeline.

    Actions taken:
    - If a required repo directory is missing -> FATAL (human setup required)
    - If chatterbox server is not running but repo exists -> auto-start it
    - If live2d binary is missing but repo exists -> cmake --build
    - If rhubarb binary is missing -> DEGRADED only (no auto-install possible)

    Returns:
        (fatal_errors, degraded_warnings, started_procs)
        fatal_errors: non-empty means pipeline must not run (human setup problem)
        degraded_warnings: printed as pre-flight warnings; pipeline continues
        started_procs: Popen handles that must be terminated on exit
    """
    import os
    import subprocess as _sp

    from video_agent.config import RHUBARB_EXECUTABLE, LIVE2D_RENDER_EXECUTABLE
    from video_agent.tools.chatterbox_server_manager import (
        CHATTERBOX_APP_DIR, CHATTERBOX_URL,
        is_healthy, start_chatterbox_server, stop_chatterbox_server,
    )

    fatal_errors: List[str] = []
    degraded_warnings: List[str] = []
    started_procs: list = []

    live2d_repo_root = os.environ.get("LIVE2D_REPO_ROOT", "")

    # ------------------------------------------------------------------
    # Chatterbox TTS
    # ------------------------------------------------------------------
    if not CHATTERBOX_APP_DIR or not Path(CHATTERBOX_APP_DIR).is_dir():
        fatal_errors.append(
            f"CHATTERBOX_APP_DIR not found: {CHATTERBOX_APP_DIR!r} -- "
            "clone the chatterbox repo and set CHATTERBOX_APP_DIR in .env"
        )
    else:
        if not is_healthy(CHATTERBOX_URL):
            print("[INFO] Chatterbox server not running -- attempting auto-start...")
            proc = start_chatterbox_server()
            if proc is not None:
                started_procs.append(proc)
            elif not is_healthy(CHATTERBOX_URL):
                degraded_warnings.append(
                    f"chatterbox: server not running at {CHATTERBOX_URL} and auto-start failed"
                    " -- all TTS will be silent"
                )
        else:
            print(f"[OK] Chatterbox server healthy at {CHATTERBOX_URL}")

    # ------------------------------------------------------------------
    # live2d-render binary
    # ------------------------------------------------------------------
    if not live2d_repo_root or not Path(live2d_repo_root).is_dir():
        fatal_errors.append(
            f"LIVE2D_REPO_ROOT not found: {live2d_repo_root!r} -- "
            "clone the live2d repo and set LIVE2D_REPO_ROOT in .env"
        )
    else:
        binary = Path(LIVE2D_RENDER_EXECUTABLE) if LIVE2D_RENDER_EXECUTABLE else None
        if not binary or not binary.exists():
            build_dir = Path(live2d_repo_root) / "build"
            print(f"[INFO] live2d-render binary not found -- attempting cmake build in {build_dir}...")
            if build_dir.is_dir():
                result = _sp.run(
                    ["cmake", "--build", ".", "--", "-j4"],
                    cwd=build_dir,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and binary and binary.exists():
                    print(f"[OK] live2d-render built successfully: {binary}")
                else:
                    err_snippet = (result.stderr or result.stdout or "")[-500:]
                    degraded_warnings.append(
                        f"live2d-render: cmake build failed (exit {result.returncode}) -- "
                        f"avatar render will fail. Error: {err_snippet[:200]}"
                    )
                    print(f"[WARN] cmake --build failed (exit {result.returncode})")
            else:
                degraded_warnings.append(
                    f"live2d-render: build directory not found ({build_dir}) -- "
                    f"run 'cmake -B build .' in {live2d_repo_root} first, then retry"
                )
        else:
            print(f"[OK] live2d-render binary found: {binary}")

    # ------------------------------------------------------------------
    # Rhubarb lip-sync (no auto-install possible)
    # ------------------------------------------------------------------
    if not RHUBARB_EXECUTABLE or not Path(RHUBARB_EXECUTABLE).exists():
        degraded_warnings.append(
            f"rhubarb: binary not found ({RHUBARB_EXECUTABLE!r}) -- "
            "lip-sync will use silent default cues (set RHUBARB_PATH in .env to enable)"
        )
    else:
        print(f"[OK] rhubarb binary found: {RHUBARB_EXECUTABLE}")

    return fatal_errors, degraded_warnings, started_procs


def main(preflight_warnings: List[str] | None = None, allow_degraded: bool = False):
    brief_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_BRIEF
    topic_brief = json.loads(brief_path.read_text(encoding="utf-8"))

    run_dir = _PROJECT_ROOT / "results" / "test" / "full_mcp_pipeline"
    run_dir.mkdir(parents=True, exist_ok=True)

    issues: List[str] = []
    t0 = time.monotonic()

    print("=" * 70)
    print("FULL MCP PIPELINE RUN")
    print(f"Topic: {topic_brief.get('topic', {}).get('name', '?')}")
    print(f"Run dir: {run_dir}")
    print("=" * 70)

    # ---------------------------------------------------------------
    # Pre-flight: show results from availability check run before main()
    # ---------------------------------------------------------------
    print("\n-- Pre-flight: tool availability --")
    if preflight_warnings:
        for w in preflight_warnings:
            print(f"  [WARN] {w}")
            issues.append(f"Pre-flight: {w}")
    else:
        print("  [OK] all external tools available")

    # ---------------------------------------------------------------
    # Step 1: research_topic (YouTube API + LLM)
    # ---------------------------------------------------------------
    print("\n-- Research & Planning --")
    r1 = _call("research_topic", {"setting": "cheese facts", "max_results": 10})
    _status_line(1, "research_topic", r1, issues, allow_degraded)
    # Use fixture brief regardless of research result (research may fail without YouTube API)
    if r1.get("topic_brief"):
        topic_brief_live = r1["topic_brief"]
        print(f"     Using live topic brief: {r1.get('run_id', '?')}")
    else:
        topic_brief_live = topic_brief
        issues.append("Step 1 (research_topic): fell back to fixture topic brief")
        print(f"     Falling back to fixture topic brief")

    # ---------------------------------------------------------------
    # Step 2: mine_facts (YouTube API + captions)
    # ---------------------------------------------------------------
    r2 = _call("mine_facts", {
        "topic_query": "cheese facts",
        "topic_id": "cheese_facts",
        "subtopic_id": "surprising",
        "max_videos": 3,
    })
    _status_line(2, "mine_facts", r2, issues, allow_degraded)

    # ---------------------------------------------------------------
    # Step 3: generate_concepts (LLM)
    # ---------------------------------------------------------------
    r3 = _call("generate_concepts", {
        "topic_brief": topic_brief_live,
        "n_concepts": 2,
    })
    _status_line(3, "generate_concepts", r3, issues, allow_degraded)
    concept = (r3.get("concepts") or [{}])[0] if r3.get("status") == "ok" else {}

    # ---------------------------------------------------------------
    # Step 4: write_screenplay (LLM)
    # ---------------------------------------------------------------
    print("\n-- Screenwriting --")
    r4 = _call("write_screenplay", {"concept": concept})
    _status_line(4, "write_screenplay", r4, issues, allow_degraded)
    screenplay = r4.get("screenplay") or {}
    scenes = screenplay.get("scenes") or []
    print(f"     Scenes: {len(scenes)}")

    # ---------------------------------------------------------------
    # Step 5: review_feasibility (heuristic, no API)
    # ---------------------------------------------------------------
    r5 = _call("review_feasibility", {"screenplay": screenplay})
    _status_line(5, "review_feasibility", r5, issues, allow_degraded)
    report = r5.get("feasibility_report") or {}
    print(f"     Score: {report.get('overall_score', '?')} Action: {report.get('recommended_action', '?')}")

    # ---------------------------------------------------------------
    # Step 6: revise_scene (LLM -- optional, call on first scene)
    # ---------------------------------------------------------------
    if scenes:
        first_scene_id = scenes[0].get("scene_id", "scene_01")
        r6 = _call("revise_scene", {
            "screenplay": screenplay,
            "scene_id": first_scene_id,
            "issue": "vo_too_long",
            "suggestion": "Shorten the voiceover line to under 15 words",
            "revision_field": "vo_line",
        })
        _status_line(6, "revise_scene", r6, issues, allow_degraded)
        # Use revised screenplay going forward
        if r6.get("status") == "ok" and r6.get("screenplay"):
            screenplay = r6["screenplay"]
    else:
        issues.append("Step 6 (revise_scene): skipped -- no scenes")
        print(f"  [ 6] {'revise_scene':<30} SKIP   (no scenes)")

    # ---------------------------------------------------------------
    # Step 7: generate_script (non-screenplay path, LLM)
    # ---------------------------------------------------------------
    print("\n-- Alternative Path: Direct Script --")
    r7 = _call("generate_script", {"topic_brief": topic_brief_live})
    _status_line(7, "generate_script", r7, issues, allow_degraded)

    # ---------------------------------------------------------------
    # Step 8: create_video_plan (deterministic, no API)
    # ---------------------------------------------------------------
    # Convert screenplay to script_package first (not a tool, pure conversion)
    from video_agent.artifacts.screenplay import screenplay_to_script_package
    script_package = screenplay_to_script_package(screenplay)
    beats = (script_package.get("script") or {}).get("beats") or []
    print(f"\n-- Production Pipeline (screenplay path, {len(beats)} beats) --")

    # Persist screenplay and script_package as run artifacts
    sp_path = run_dir / "screenplay.json"
    sp_path.write_text(json.dumps(screenplay, indent=2), encoding="utf-8")
    pkg_path = run_dir / "script_package.json"
    pkg_path.write_text(json.dumps(script_package, indent=2), encoding="utf-8")
    print(f"     Saved: screenplay.json, script_package.json")

    r8 = _call("create_video_plan", {"script_package": script_package})
    _status_line(8, "create_video_plan", r8, issues, allow_degraded)
    video_plan = r8.get("video_plan") or {}

    # ---------------------------------------------------------------
    # Step 9: estimate_tts_duration (heuristic, no API)
    # ---------------------------------------------------------------
    sample_vo = ""
    if scenes:
        sample_vo = scenes[0].get("vo_line", "") or scenes[0].get("voiceover", "") or "Sample text"
    r9 = _call("estimate_tts_duration", {"text": sample_vo, "voice_preset": "narrator"})
    _status_line(9, "estimate_tts_duration", r9, issues, allow_degraded)
    print(f"     Estimated: {r9.get('estimated_duration_s', '?')}s for {r9.get('word_count', '?')} words")

    # ---------------------------------------------------------------
    # Step 10: check_asset_availability (Pexels probe, no download)
    # ---------------------------------------------------------------
    sample_query = "wheel of aged cheese on wooden table"
    r10 = _call("check_asset_availability", {"query": sample_query, "n_results": 3})
    _status_line(10, "check_asset_availability", r10, issues, allow_degraded)
    print(f"     Availability: {r10.get('availability', '?')} ({r10.get('result_count', 0)} results)")

    # ---------------------------------------------------------------
    # Step 11: generate_audio (TTS)
    # ---------------------------------------------------------------
    print("\n-- Audio & Assets --")
    r11 = _call("generate_audio", {
        "screenplay": screenplay,
        "run_dir": str(run_dir),
        "voice_preset": "narrator",
    })
    _status_line(11, "generate_audio", r11, issues, allow_degraded)
    audio_timeline = r11.get("audio_timeline") or {}
    audio_issues = r11.get("production_issues") or []
    if audio_issues:
        for ai in audio_issues:
            issues.append(f"Step 11 (generate_audio): {ai.get('scene_id', '?')} - {ai.get('issue', '?')}")
        print(f"     Audio issues: {len(audio_issues)}")
    segments = r11.get("segments") or []
    degraded = [s for s in segments if s.get("status") == "degraded"]
    print(f"     Segments: {len(segments)} ({len(degraded)} degraded)")

    # ---------------------------------------------------------------
    # Steps 11b-11d: Live2D avatar pipeline (lipsync -> package -> render)
    # ---------------------------------------------------------------
    print("\n-- Live2D Avatar Pipeline --")
    r11b = _call("generate_lipsync", {
        "audio_timeline": audio_timeline,
        "run_dir": str(run_dir),
    })
    _status_line("11b", "generate_lipsync", r11b, issues, allow_degraded)
    lipsync_manifest = r11b.get("lipsync_manifest") or {}
    print(f"     Scenes: {r11b.get('scenes_processed', 0)}, rhubarb={r11b.get('rhubarb_version', '?')}")

    r11c = _call("package_avatar", {
        "lipsync_manifest": lipsync_manifest,
        "audio_timeline": audio_timeline,
        "run_dir": str(run_dir),
    })
    _status_line("11c", "package_avatar", r11c, issues, allow_degraded)
    avatar_manifest = r11c.get("avatar_manifest") or {}
    print(f"     Manifest: {r11c.get('manifest_path', '?')}")

    r11d = _call("render_avatar", {
        "avatar_manifest": avatar_manifest,
        "run_dir": str(run_dir),
    })
    _status_line("11d", "render_avatar", r11d, issues, allow_degraded)
    mov_path = r11d.get("mov_path", "")
    if mov_path:
        size_kb = r11d.get("size_bytes", 0) // 1024
        print(f"     MOV: {mov_path} ({size_kb} KB)")
    else:
        issues.append("Step 11d (render_avatar): avatar_full.mov not produced")
        print(f"     MOV: [not produced]")

    # ---------------------------------------------------------------
    # Step 12: select_music
    # ---------------------------------------------------------------
    r12 = _call("select_music", {
        "audio_timeline": audio_timeline,
        "script_package": script_package,
    })
    _status_line(12, "select_music", r12, issues, allow_degraded)
    music_selection = r12.get("music_selection")
    if music_selection:
        print(f"     Music: {music_selection.get('title', '?')} (method={music_selection.get('selection_method', '?')})")

    # ---------------------------------------------------------------
    # Step 13: fetch_assets (image retrieval)
    # ---------------------------------------------------------------
    r13 = _call("fetch_assets", {
        "script_package": script_package,
        "run_dir": str(run_dir),
    })
    _status_line(13, "fetch_assets", r13, issues, allow_degraded)
    visual_manifest = r13.get("visual_manifest") or {}
    vm_assets = visual_manifest.get("assets") or []
    placeholders = [a for a in vm_assets if a.get("source") == "placeholder"]
    print(f"     Assets: {len(vm_assets)} ({len(placeholders)} placeholders)")

    # ---------------------------------------------------------------
    # Step 14: render_video (composition + FFmpeg)
    # ---------------------------------------------------------------
    print("\n-- Render & Validate --")
    render_args: dict = {
        "visual_manifest": visual_manifest,
        "audio_timeline": audio_timeline,
        "video_plan": video_plan,
        "run_dir": str(run_dir),
        "engine": "ffmpeg",
    }
    if avatar_manifest:
        render_args["avatar_manifest"] = avatar_manifest
    r14 = _call("render_video", render_args)
    _status_line(14, "render_video", r14, issues, allow_degraded)
    mp4_path = r14.get("mp4_path", "")
    print(f"     MP4: {mp4_path}")

    # ---------------------------------------------------------------
    # Step 15: validate_output (ffprobe)
    # ---------------------------------------------------------------
    r15 = _call("validate_output", {
        "mp4_path": mp4_path,
        "audio_timeline": audio_timeline,
        "run_dir": str(run_dir),
    })
    _status_line(15, "validate_output", r15, issues, allow_degraded)
    print(f"     Passed: {r15.get('passed', '?')}")
    print(f"     Video: {r15.get('video_duration_s', '?')}s  Audio: {r15.get('audio_duration_s', '?')}s  Parity: {r15.get('duration_parity_s', '?')}s")
    if r15.get("failures"):
        for f in r15["failures"]:
            issues.append(f"Step 15 (validate_output): {f}")

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    elapsed = round(time.monotonic() - t0, 1)
    print("\n" + "=" * 70)
    print(f"PIPELINE COMPLETE in {elapsed}s")
    print(f"Run dir: {run_dir}")
    if mp4_path and Path(mp4_path).exists():
        size_kb = Path(mp4_path).stat().st_size // 1024
        print(f"Output:  {mp4_path} ({size_kb} KB)")
    print(f"\nIssues ({len(issues)}):")
    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("  None!")
    print("=" * 70)

    # Save issues log
    log = {
        "topic": topic_brief.get("topic", {}).get("name", "?"),
        "elapsed_s": elapsed,
        "issue_count": len(issues),
        "issues": issues,
        "mp4_exists": bool(mp4_path and Path(mp4_path).exists()),
        "validation_passed": r15.get("passed", False),
    }
    log_path = run_dir / "pipeline_run_log.json"
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    from video_agent.tools.chatterbox_server_manager import stop_chatterbox_server

    _parser = argparse.ArgumentParser(description="Full MCP pipeline run")
    _parser.add_argument(
        "--allow-degraded",
        action="store_true",
        default=False,
        help="Treat degraded/partial step results as warnings rather than failures",
    )
    _parser.add_argument("brief", nargs="?", help="Path to topic_brief.json (optional)")
    _args = _parser.parse_args()

    # Inject brief path into argv so main() picks it up via sys.argv[1]
    if _args.brief:
        sys.argv = [sys.argv[0], _args.brief]
    else:
        sys.argv = [sys.argv[0]]

    _fatal_errors, _preflight_warnings, _started_procs = _check_tool_availability()

    if _fatal_errors:
        print("\n[FATAL] Pipeline cannot start -- missing required components:")
        for _e in _fatal_errors:
            print(f"  - {_e}")
        print(
            "\nThese require human setup. Check your .env file and ensure all "
            "repos are cloned before running this script."
        )
        sys.exit(1)

    try:
        main(_preflight_warnings, allow_degraded=_args.allow_degraded)
    finally:
        for _proc in _started_procs:
            stop_chatterbox_server(_proc)
