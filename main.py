"""Main entry point for video_agent CLI."""

import argparse
import asyncio
import json
import shutil
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="google")

from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.artifacts.io import ensure_run_dir, new_run_id, write_json
from src.config import (
    ANTHROPIC_API_KEY,
    ELEVENLABS_API_KEY,
    GOOGLE_API_KEY,
    LLM_PROVIDER,
    RESULTS_DIR,
    TTS_BACKEND,
    YOUTUBE_API_KEY,
)


# ---------------------------------------------------------------------------
# In-process MCP tool call helper (same pattern as orchestrator)
# ---------------------------------------------------------------------------

async def _call_tool_inprocess(tool_name: str, arguments: dict) -> dict:
    from src.mcp.video_agent_server import call_tool
    result = await call_tool(tool_name, arguments)
    text = result[0].text if result else "{}"
    return json.loads(text)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight() -> None:
    """Print a quick readiness report for running the end-to-end pipeline."""
    keys = {
        "YOUTUBE_API_KEY": bool(YOUTUBE_API_KEY),
        "GOOGLE_API_KEY": bool(GOOGLE_API_KEY),
        "ELEVENLABS_API_KEY": bool(ELEVENLABS_API_KEY),
    }
    print("\nPreflight:")
    for k, ok in keys.items():
        print(f"- {k}: {'OK' if ok else 'MISSING'}")

    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    print(f"- ffmpeg on PATH: {'OK' if ffmpeg_ok else 'MISSING'}")
    if not ffmpeg_ok:
        print("  Windows install tip: winget install Gyan.FFmpeg")


# ---------------------------------------------------------------------------
# API key checks
# ---------------------------------------------------------------------------

def check_api_keys():
    missing = []
    if not YOUTUBE_API_KEY:
        missing.append("YOUTUBE_API_KEY")
    if LLM_PROVIDER == "claude" and not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    elif LLM_PROVIDER == "google" and not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if missing:
        print("[ERROR] Missing required API keys:")
        for key in missing:
            print(f"   - {key}")
        sys.exit(1)
    print(f"[OK] API keys configured (LLM provider: {LLM_PROVIDER})")


def check_tts_key():
    if TTS_BACKEND in {"chatterbox_server", "chatterbox_direct"}:
        print(f"[OK] TTS backend: {TTS_BACKEND} (no API key required)")
        return
    if ELEVENLABS_API_KEY:
        print("[OK] ELEVENLABS_API_KEY configured")
        return
    print("[ERROR] Missing required API key: ELEVENLABS_API_KEY")
    sys.exit(1)


# ---------------------------------------------------------------------------
# screenplay mode
# ---------------------------------------------------------------------------

def run_screenplay(args) -> None:
    """Screenwriting pipeline: concepts -> screenplay -> review -> production."""
    from src.screenwriting.concept_agent import ConceptAgent
    from src.screenwriting.screenplay_agent import ScreenplayAgent
    from src.screenwriting.screenplay_reviewer import ScreenplayReviewer
    from src.artifacts.screenplay import screenplay_to_script_package
    from src.orchestrator import ProductionOrchestrator

    check_api_keys()
    check_tts_key()

    topic_brief_path = Path(args.topicbrief).expanduser().resolve()
    if not topic_brief_path.exists():
        print(f"[ERROR] TopicBrief not found: {topic_brief_path}")
        sys.exit(2)

    topic_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
    topic_id = str(topic_brief.get("topic_id") or "topic")
    subtopic_id = str(topic_brief.get("subtopic_id") or "sub")

    run_id = new_run_id("sp", f"{topic_id}_{subtopic_id}")
    run_dir = ensure_run_dir(RESULTS_DIR, run_id)

    # 1) Generate concepts via MCP
    print(f"\n[INFO] Generating {args.n_concepts} concept(s)...")
    concepts_result = asyncio.run(_call_tool_inprocess("generate_concepts", {
        "topic_brief": topic_brief,
        "n_concepts": args.n_concepts,
        **({"formats": [args.format]} if args.format else {}),
    }))
    concepts = concepts_result.get("concepts") or []
    print(f"[OK] {len(concepts)} concept(s) generated")

    # 2) Write screenplay + review each concept via MCP
    entries = []
    for idx, concept in enumerate(concepts):
        print(f"\n[INFO] Writing screenplay {idx + 1}/{len(concepts)} (format: {concept['format']})...")
        sp_result = asyncio.run(_call_tool_inprocess("write_screenplay", {
            "concept": concept,
            "topic_brief": topic_brief,
        }))
        screenplay = sp_result.get("screenplay") or sp_result

        review_result = asyncio.run(_call_tool_inprocess("review_feasibility", {
            "screenplay": screenplay,
        }))
        report = review_result.get("feasibility_report") or review_result

        screenplay["feasibility_report"] = report
        entries.append((concept, screenplay, report))
        write_json(run_dir / f"concept_{idx + 1}.json", concept)
        write_json(run_dir / f"screenplay_{idx + 1}.json", screenplay)
        write_json(run_dir / f"feasibility_{idx + 1}.json", report)

    # 3) Summary table
    print("\n" + "-" * 80)
    print(f"{'#':<4} {'Format':<12} {'Score':<8} {'Action':<18} Hook")
    print("-" * 80)
    for idx, (concept, sp, report) in enumerate(entries):
        print(
            f"{idx + 1:<4} {concept['format']:<12} {report.get('overall_score', 0):<8.2f} "
            f"{report.get('recommended_action','?'):<18} {concept.get('hook','')[:40]}"
        )
    print("-" * 80)

    # 4) Select screenplay
    approved = [(i, e) for i, e in enumerate(entries) if e[2].get("recommended_action") == "approve"]
    if not approved:
        approved = sorted(enumerate(entries), key=lambda x: x[1][2].get("overall_score", 0), reverse=True)

    if args.auto_select or not sys.stdin.isatty():
        chosen_idx, chosen = approved[0]
        print(f"\n[INFO] Auto-selected screenplay #{chosen_idx + 1}")
    else:
        default = approved[0][0] + 1
        try:
            raw_input = input(f"\nSelect screenplay [1-{len(entries)}, default={default}]: ").strip()
            chosen_idx = (int(raw_input) - 1) if raw_input else (default - 1)
            chosen_idx = max(0, min(len(entries) - 1, chosen_idx))
        except (ValueError, EOFError):
            chosen_idx = default - 1
        chosen = entries[chosen_idx]

    concept, selected_sp, report = chosen

    # 5) Auto-revise flagged scenes (up to 1 round)
    screenplay_agent_inst = ScreenplayAgent()
    if report.get("recommended_action") == "revise_scenes":
        print(f"\n[INFO] Revising flagged scenes (action={report['recommended_action']})...")
        for issue in report.get("scene_issues") or []:
            if issue.get("severity") == "error":
                scene_id = issue["scene_id"]
                if scene_id == "ALL":
                    continue
                print(f"[INFO] Revising scene {scene_id}: {issue['issue']}")
                revision_field = "vo_line" if issue["issue"] in {"vo_too_long", "empty_vo_line"} else "visual"
                selected_sp = screenplay_agent_inst.revise_scene(
                    selected_sp, scene_id,
                    issue=issue["issue"],
                    suggestion=issue.get("suggestion", ""),
                    revision_field=revision_field,
                )
        revised_report = ScreenplayReviewer().review(selected_sp)
        selected_sp["feasibility_report"] = revised_report
        write_json(run_dir / "screenplay_selected_revised.json", selected_sp)
        print(f"[INFO] Post-revision score: {revised_report['overall_score']:.2f} ({revised_report['recommended_action']})")
    else:
        write_json(run_dir / "screenplay_selected.json", selected_sp)

    # 6) video_plan via MCP
    print("\n[INFO] Converting Screenplay to ScriptPackage...")
    script_package = screenplay_to_script_package(selected_sp)
    write_json(run_dir / "script_package.json", script_package)

    vp_result = asyncio.run(_call_tool_inprocess("create_video_plan", {
        "script_package": script_package,
    }))
    video_plan = vp_result.get("video_plan") or vp_result
    write_json(run_dir / "video_plan.json", video_plan)

    voice = str(script_package.get("audio", {}).get("tts", {}).get("voice") or "narrator")

    # 7) Orchestrated production (audio + image with revision loop)
    print(f"[INFO] Orchestrator mode: MCP client (serial={args.serial})")
    orch = ProductionOrchestrator()
    audio_timeline, selected_sp, video_plan = orch.run(
        screenplay=selected_sp,
        script_package=script_package,
        video_plan=video_plan,
        run_dir=run_dir,
        screenplay_agent=screenplay_agent_inst,
        voice=voice,
        serial=args.serial,
    )
    write_json(run_dir / "audio_timeline.json", audio_timeline)

    # Refresh after orchestrator revisions
    script_package = screenplay_to_script_package(selected_sp)
    vp_result2 = asyncio.run(_call_tool_inprocess("create_video_plan", {
        "script_package": script_package,
    }))
    video_plan = vp_result2.get("video_plan") or vp_result2
    write_json(run_dir / "video_plan.json", video_plan)

    # 8) Music selection via MCP
    music_result = asyncio.run(_call_tool_inprocess("select_music", {
        "audio_timeline": audio_timeline,
    }))
    music_selection = music_result.get("music_selection") or music_result
    write_json(run_dir / "music_selection.json", music_selection)

    # 9) Render via MCP
    render_result = asyncio.run(_call_tool_inprocess("render_video", {
        "video_plan": video_plan,
        "audio_timeline": audio_timeline,
        "run_dir": str(run_dir),
        "engine": args.engine,
    }))
    write_json(run_dir / "final_video.json", render_result)

    # 10) Validate
    validate_result = asyncio.run(_call_tool_inprocess("validate_output", {
        "run_dir": str(run_dir),
    }))

    print(f"\n[OK] Screenplay run complete: {run_dir}")
    print(f"   - Concepts:        {len(concepts)} generated")
    print(f"   - Selected:        screenplay #{chosen_idx + 1} ({concept['format']})")
    print(f"   - ScriptPackage:   {run_dir / 'script_package.json'}")
    print(f"   - MP4:             {run_dir / 'final_video.mp4'}")


# ---------------------------------------------------------------------------
# pipeline mode
# ---------------------------------------------------------------------------

def run_pipeline(args) -> None:
    """Full pipeline: research_topic through validate_output via MCP tool calls."""
    topic_brief_path = Path(args.topicbrief).expanduser().resolve()
    if not topic_brief_path.exists():
        print(f"[ERROR] TopicBrief not found: {topic_brief_path}")
        sys.exit(2)

    topic_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
    topic_id = str(topic_brief.get("topic_id") or "topic")
    subtopic_id = str(topic_brief.get("subtopic_id") or "sub")

    run_id = new_run_id("pipe", f"{topic_id}_{subtopic_id}")
    run_dir = ensure_run_dir(RESULTS_DIR, run_id)

    print(f"\n[INFO] Pipeline run_id={run_id}  engine={args.engine}  serial={args.serial}")

    # 1) research_topic
    print("[INFO] Step 1/10: research_topic")
    result = asyncio.run(_call_tool_inprocess("research_topic", {"topic_brief": topic_brief}))
    topic_brief_enriched = result.get("topic_brief") or topic_brief
    write_json(run_dir / "topic_brief_enriched.json", topic_brief_enriched)
    print(f"[OK] research_topic status={result.get('status','?')}")

    # 2) generate_concepts
    print("[INFO] Step 2/10: generate_concepts")
    result = asyncio.run(_call_tool_inprocess("generate_concepts", {
        "topic_brief": topic_brief_enriched,
        "n_concepts": 1,
    }))
    concepts = result.get("concepts") or []
    if not concepts:
        print("[ERROR] generate_concepts returned no concepts")
        sys.exit(1)
    concept = concepts[0]
    write_json(run_dir / "concept.json", concept)
    print(f"[OK] generate_concepts format={concept.get('format','?')}")

    # 3) write_screenplay
    print("[INFO] Step 3/10: write_screenplay")
    result = asyncio.run(_call_tool_inprocess("write_screenplay", {
        "concept": concept,
        "topic_brief": topic_brief_enriched,
    }))
    screenplay = result.get("screenplay") or result
    write_json(run_dir / "screenplay.json", screenplay)
    print(f"[OK] write_screenplay scenes={len(screenplay.get('scenes') or [])}")

    # 4) review_feasibility
    print("[INFO] Step 4/10: review_feasibility")
    result = asyncio.run(_call_tool_inprocess("review_feasibility", {
        "screenplay": screenplay,
    }))
    report = result.get("feasibility_report") or result
    write_json(run_dir / "feasibility_report.json", report)
    print(f"[OK] review_feasibility score={report.get('overall_score','?')} action={report.get('recommended_action','?')}")

    # 5) create_video_plan
    print("[INFO] Step 5/10: create_video_plan")
    from src.artifacts.screenplay import screenplay_to_script_package
    script_package = screenplay_to_script_package(screenplay)
    write_json(run_dir / "script_package.json", script_package)

    result = asyncio.run(_call_tool_inprocess("create_video_plan", {
        "script_package": script_package,
    }))
    video_plan = result.get("video_plan") or result
    write_json(run_dir / "video_plan.json", video_plan)
    print(f"[OK] create_video_plan scenes={len(video_plan.get('scenes') or [])}")

    # 6+7) generate_audio + fetch_assets (via orchestrator)
    print("[INFO] Step 6+7/10: generate_audio + fetch_assets (orchestrator)")
    from src.orchestrator import ProductionOrchestrator
    from src.screenwriting.screenplay_agent import ScreenplayAgent
    voice = str(script_package.get("audio", {}).get("tts", {}).get("voice") or "narrator")
    screenplay_agent_inst = ScreenplayAgent()
    orch = ProductionOrchestrator()
    audio_timeline, screenplay, video_plan = orch.run(
        screenplay=screenplay,
        script_package=script_package,
        video_plan=video_plan,
        run_dir=run_dir,
        screenplay_agent=screenplay_agent_inst,
        voice=voice,
        serial=args.serial,
    )
    write_json(run_dir / "audio_timeline.json", audio_timeline)
    print(f"[OK] orchestrator done  tracks={len(audio_timeline.get('tracks') or [])}")

    # Refresh after orchestrator revisions
    script_package = screenplay_to_script_package(screenplay)
    result = asyncio.run(_call_tool_inprocess("create_video_plan", {
        "script_package": script_package,
    }))
    video_plan = result.get("video_plan") or result
    write_json(run_dir / "video_plan.json", video_plan)

    # 8) select_music
    print("[INFO] Step 8/10: select_music")
    result = asyncio.run(_call_tool_inprocess("select_music", {
        "audio_timeline": audio_timeline,
    }))
    music_selection = result.get("music_selection") or result
    write_json(run_dir / "music_selection.json", music_selection)
    print(f"[OK] select_music file={music_selection.get('music_file_path','?')}")

    # 9) render_video
    print("[INFO] Step 9/10: render_video")
    result = asyncio.run(_call_tool_inprocess("render_video", {
        "video_plan": video_plan,
        "audio_timeline": audio_timeline,
        "run_dir": str(run_dir),
        "engine": args.engine,
    }))
    write_json(run_dir / "final_video.json", result)
    print(f"[OK] render_video status={result.get('status','?')}")

    # 10) validate_output
    print("[INFO] Step 10/10: validate_output")
    result = asyncio.run(_call_tool_inprocess("validate_output", {
        "run_dir": str(run_dir),
    }))
    print(f"[OK] validate_output status={result.get('status','?')}")

    print(f"\n[OK] Pipeline complete: {run_dir}")
    print(f"   - MP4: {run_dir / 'final_video.mp4'}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("video-agent")
    print("=" * 60)

    parser = argparse.ArgumentParser(
        prog="video-agent",
        description="Multi-agent AI video content pipeline",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # preflight
    subparsers.add_parser("preflight", help="Check env keys and FFmpeg availability")

    # screenplay
    sp = subparsers.add_parser("screenplay", help="Screenwriting pipeline with interactive concept selection")
    sp.add_argument("topicbrief", help="Path to topicbrief.json")
    sp.add_argument("--format", dest="format", default=None, help="Filter concepts by format (e.g. facts, storytime)")
    sp.add_argument("--n-concepts", dest="n_concepts", type=int, default=3, help="Number of concepts to generate")
    sp.add_argument("--auto-select", dest="auto_select", action="store_true", help="Auto-select best screenplay")
    sp.add_argument("--serial", action="store_true", help="Run audio/image sequentially instead of in parallel")
    sp.add_argument("--engine", choices=["ffmpeg", "dry_run"], default="dry_run", help="Render engine")

    # pipeline
    pp = subparsers.add_parser("pipeline", help="Full automated pipeline from topicbrief to video")
    pp.add_argument("topicbrief", help="Path to topicbrief.json")
    pp.add_argument("--engine", choices=["ffmpeg", "dry_run"], default="dry_run", help="Render engine")
    pp.add_argument("--serial", action="store_true", help="Run audio/image sequentially instead of in parallel")

    args = parser.parse_args()

    if args.mode == "preflight":
        preflight()
    elif args.mode == "screenplay":
        run_screenplay(args)
    elif args.mode == "pipeline":
        run_pipeline(args)


if __name__ == "__main__":
    main()
