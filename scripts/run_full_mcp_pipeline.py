"""Full MCP pipeline run -- exercises every tool in sequence.

Usage:
    python -m scripts.run_full_mcp_pipeline [topic_brief.json]

Calls all 15 MCP tools via in-process dispatch, logging status and issues.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# In-process MCP dispatch (same handler code as the HTTPS server)
from src.orchestrator import _call_tool_inprocess

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BRIEF = _PROJECT_ROOT / "tests" / "fixtures" / "topic_brief_cheese_facts.json"


def _call(tool_name: str, arguments: dict) -> Dict[str, Any]:
    """Call an MCP tool and return parsed JSON."""
    return asyncio.get_event_loop().run_until_complete(
        _call_tool_inprocess(tool_name, arguments)
    )


def _status_line(step: int, tool: str, result: dict, issues: List[str]) -> None:
    status = result.get("status", "?")
    elapsed = result.get("elapsed_seconds", "?")
    err = result.get("error")
    if err:
        issues.append(f"Step {step} ({tool}): ERROR - {err}")
        print(f"  [{step:>2}] {tool:<30} ERROR  ({elapsed}s) -- {err[:120]}")
    elif status != "ok":
        issues.append(f"Step {step} ({tool}): status={status}")
        print(f"  [{step:>2}] {tool:<30} {status:<6} ({elapsed}s)")
    else:
        print(f"  [{step:>2}] {tool:<30} OK     ({elapsed}s)")


def main():
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
    # Step 1: research_topic (YouTube API + LLM)
    # ---------------------------------------------------------------
    print("\n-- Research & Planning --")
    r1 = _call("research_topic", {"setting": "cheese facts", "max_results": 10})
    _status_line(1, "research_topic", r1, issues)
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
    _status_line(2, "mine_facts", r2, issues)

    # ---------------------------------------------------------------
    # Step 3: generate_concepts (LLM)
    # ---------------------------------------------------------------
    r3 = _call("generate_concepts", {
        "topic_brief": topic_brief_live,
        "n_concepts": 2,
    })
    _status_line(3, "generate_concepts", r3, issues)
    concept = (r3.get("concepts") or [{}])[0] if r3.get("status") == "ok" else {}

    # ---------------------------------------------------------------
    # Step 4: write_screenplay (LLM)
    # ---------------------------------------------------------------
    print("\n-- Screenwriting --")
    r4 = _call("write_screenplay", {"concept": concept})
    _status_line(4, "write_screenplay", r4, issues)
    screenplay = r4.get("screenplay") or {}
    scenes = screenplay.get("scenes") or []
    print(f"     Scenes: {len(scenes)}")

    # ---------------------------------------------------------------
    # Step 5: review_feasibility (heuristic, no API)
    # ---------------------------------------------------------------
    r5 = _call("review_feasibility", {"screenplay": screenplay})
    _status_line(5, "review_feasibility", r5, issues)
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
        _status_line(6, "revise_scene", r6, issues)
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
    _status_line(7, "generate_script", r7, issues)

    # ---------------------------------------------------------------
    # Step 8: create_video_plan (deterministic, no API)
    # ---------------------------------------------------------------
    # Convert screenplay to script_package first (not a tool, pure conversion)
    from src.artifacts.screenplay import screenplay_to_script_package
    script_package = screenplay_to_script_package(screenplay)
    beats = (script_package.get("script") or {}).get("beats") or []
    print(f"\n-- Production Pipeline (screenplay path, {len(beats)} beats) --")

    r8 = _call("create_video_plan", {"script_package": script_package})
    _status_line(8, "create_video_plan", r8, issues)
    video_plan = r8.get("video_plan") or {}

    # ---------------------------------------------------------------
    # Step 9: estimate_tts_duration (heuristic, no API)
    # ---------------------------------------------------------------
    sample_vo = ""
    if scenes:
        sample_vo = scenes[0].get("vo_line", "") or scenes[0].get("voiceover", "") or "Sample text"
    r9 = _call("estimate_tts_duration", {"text": sample_vo, "voice_preset": "narrator"})
    _status_line(9, "estimate_tts_duration", r9, issues)
    print(f"     Estimated: {r9.get('estimated_duration_s', '?')}s for {r9.get('word_count', '?')} words")

    # ---------------------------------------------------------------
    # Step 10: check_asset_availability (Pexels probe, no download)
    # ---------------------------------------------------------------
    sample_query = "wheel of aged cheese on wooden table"
    r10 = _call("check_asset_availability", {"query": sample_query, "n_results": 3})
    _status_line(10, "check_asset_availability", r10, issues)
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
    _status_line(11, "generate_audio", r11, issues)
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
    # Step 12: select_music
    # ---------------------------------------------------------------
    r12 = _call("select_music", {"audio_timeline": audio_timeline})
    _status_line(12, "select_music", r12, issues)
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
    _status_line(13, "fetch_assets", r13, issues)
    visual_manifest = r13.get("visual_manifest") or {}
    vm_assets = visual_manifest.get("assets") or []
    placeholders = [a for a in vm_assets if a.get("source") == "placeholder"]
    print(f"     Assets: {len(vm_assets)} ({len(placeholders)} placeholders)")

    # ---------------------------------------------------------------
    # Step 14: render_video (composition + FFmpeg)
    # ---------------------------------------------------------------
    print("\n-- Render & Validate --")
    r14 = _call("render_video", {
        "visual_manifest": visual_manifest,
        "audio_timeline": audio_timeline,
        "video_plan": video_plan,
        "run_dir": str(run_dir),
        "engine": "ffmpeg",
    })
    _status_line(14, "render_video", r14, issues)
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
    _status_line(15, "validate_output", r15, issues)
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
    from src.tools.chatterbox_server_manager import (
        start_chatterbox_server,
        stop_chatterbox_server,
    )

    chatterbox_proc = start_chatterbox_server()
    try:
        main()
    finally:
        stop_chatterbox_server(chatterbox_proc)
