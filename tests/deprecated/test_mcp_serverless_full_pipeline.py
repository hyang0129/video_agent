"""MCP serverless (in-process) full pipeline integration test.

Exercises the full screenwriting pipeline using MCP tool calls dispatched
in-process via _call_tool_inprocess (no HTTP server required).

Conditions:
  - use_mcp=True, serial=True
  - TTS backend: chatterbox_server (default; requires chatterbox HTTP server at
    CHATTERBOX_SERVER_URL, default http://localhost:8000)
  - No artifact reuse — fresh tmp_path each run

Usage:
    python3 -m pytest tests/test_mcp_serverless_full_pipeline.py -v -s

Environment variables:
    ANTHROPIC_API_KEY or GOOGLE_API_KEY  -- required (LLM for concept/screenplay)
    CHATTERBOX_SERVER_URL                -- optional (default: http://localhost:8000)
    TTS_BACKEND                          -- optional (default: chatterbox_server)
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from src.artifacts.io import write_json
from src.artifacts.screenplay import screenplay_to_script_package
from src.composition_agent import create_composition_agent
from src.orchestrator import ProductionOrchestrator
from src.render_agent import create_render_agent
from src.screenwriting.concept_agent import ConceptAgent
from src.screenwriting.screenplay_agent import ScreenplayAgent
from src.screenwriting.screenplay_reviewer import ScreenplayReviewer
from src.video_planner import script_package_to_video_plan

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TOPIC_BRIEF_PATH = _FIXTURES_DIR / "topic_brief_ww2_tanks.json"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_mcp_serverless_full_pipeline(tmp_path: Path) -> None:
    """Full pipeline via MCP in-process (no HTTP server). Audio via Chatterbox."""

    has_llm = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if not has_llm:
        pytest.skip("No LLM API key available (ANTHROPIC_API_KEY or GOOGLE_API_KEY)")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    topic_brief = json.loads(_TOPIC_BRIEF_PATH.read_text(encoding="utf-8"))

    # --- Stage 1: ConceptAgent ---
    print("\n[INFO] Stage 1: Generating concepts...")
    concept_agent = ConceptAgent()
    concepts = concept_agent.generate_concepts(topic_brief=topic_brief, n_concepts=1)
    assert concepts, "ConceptAgent returned no concepts"
    concept = concepts[0]
    write_json(run_dir / "concept.json", concept)
    print(f"[OK] Concept: format={concept.get('format')} title={concept.get('title', '')[:50]}")

    # --- Stage 2: ScreenplayAgent ---
    print("\n[INFO] Stage 2: Writing screenplay...")
    screenplay_agent = ScreenplayAgent()
    screenplay = screenplay_agent.write_screenplay(concept=concept, topic_brief=topic_brief)
    assert screenplay, "ScreenplayAgent returned empty screenplay"
    write_json(run_dir / "screenplay.json", screenplay)
    scenes = screenplay.get("scenes") or []
    print(f"[OK] Screenplay: {len(scenes)} scene(s)")

    # --- Stage 3: ScreenplayReviewer ---
    print("\n[INFO] Stage 3: Reviewing feasibility...")
    reviewer = ScreenplayReviewer()
    report = reviewer.review(screenplay)
    write_json(run_dir / "feasibility.json", report)
    print(f"[OK] Feasibility: score={report.get('overall_score', '?')} action={report.get('recommended_action', '?')}")

    # --- Stage 4: screenplay -> script_package ---
    print("\n[INFO] Stage 4: Converting Screenplay -> ScriptPackage...")
    script_package = screenplay_to_script_package(screenplay)
    beats = (script_package.get("script") or {}).get("beats") or []
    assert beats, "ScriptPackage has no beats"
    write_json(run_dir / "script_package.json", script_package)
    print(f"[OK] ScriptPackage: {len(beats)} beats")

    # --- Stage 5: VideoPlanner ---
    print("\n[INFO] Stage 5: Creating VideoPlan...")
    video_plan = script_package_to_video_plan(script_package=script_package)
    write_json(run_dir / "video_plan.json", video_plan)
    print("[OK] VideoPlan written")

    # --- Stage 6+7: Orchestrator (MCP in-process, serial) ---
    print("\n[INFO] Stages 6+7: Orchestrator [MCP in-process, serial, chatterbox TTS]...")
    orch = ProductionOrchestrator()
    audio_timeline, revised_sp, revised_vp = orch.run(
        screenplay=screenplay,
        script_package=script_package,
        video_plan=video_plan,
        run_dir=run_dir,
        screenplay_agent=screenplay_agent,
        voice="narrator",
        use_mcp=True,
        serial=True,
    )
    write_json(run_dir / "audio_timeline.json", audio_timeline)
    write_json(run_dir / "video_plan_revised.json", revised_vp)
    segments = audio_timeline.get("segments") or []
    print(f"[OK] AudioTimeline: {len(segments)} segment(s), total_duration={audio_timeline.get('total_duration_s')}s")

    # Refresh for downstream stages
    script_package = screenplay_to_script_package(revised_sp)
    video_plan = revised_vp

    # --- Stage 8: CompositionAgent ---
    print("\n[INFO] Stage 8: Creating RenderSpec...")
    comp_agent = create_composition_agent(output_dir=run_dir)

    # Load visual_manifest written by orchestrator
    vm_path = run_dir / "visual_manifest.json"
    assert vm_path.exists(), "Orchestrator did not write visual_manifest.json"
    visual_manifest = json.loads(vm_path.read_text(encoding="utf-8"))

    # Music is optional
    music_selection = None
    ms_path = run_dir / "music_selection.json"
    if ms_path.exists():
        music_selection = json.loads(ms_path.read_text(encoding="utf-8"))

    render_spec = comp_agent.create_render_specification(
        video_plan=video_plan,
        audio_timeline=audio_timeline,
        visual_manifest=visual_manifest,
        music_selection=music_selection,
    )
    write_json(run_dir / "render_spec.json", render_spec)
    print("[OK] RenderSpec written")

    # --- Stage 9: RenderAgent ---
    print("\n[INFO] Stage 9: Rendering final_video.mp4...")
    render_agent = create_render_agent(output_dir=run_dir, engine="ffmpeg")
    final_video = render_agent.render(render_spec=render_spec)
    write_json(run_dir / "final_video.json", final_video)

    final_mp4 = run_dir / "final_video.mp4"
    assert final_mp4.exists(), f"final_video.mp4 not found in {run_dir}"
    assert final_mp4.stat().st_size > 0, "Rendered final_video.mp4 is empty"
    duration = final_video.get("duration_seconds", 0)
    print(f"[OK] Rendered: {final_mp4.name} ({final_mp4.stat().st_size // 1024} KB, {duration:.2f}s)")

    # --- Copy to persistent review dir ---
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_root = _PROJECT_ROOT / "results" / "test" / "stages"
    review_root.mkdir(parents=True, exist_ok=True)
    review_dir = review_root / f"mcp_serverless_{stamp}"
    shutil.copytree(run_dir, review_dir)

    print("\n" + "=" * 70)
    print("MCP SERVERLESS PIPELINE -- HUMAN REVIEW TARGETS")
    print("=" * 70)
    print(f"Review dir : {review_dir}")
    print(f"MP4        : {review_dir / 'final_video.mp4'}")
    print(f"Script pkg : {review_dir / 'script_package.json'}")
    print(f"Screenplay : {review_dir / 'screenplay.json'}")
    print("\nMode       : MCP in-process (no HTTP server)")
    print("TTS        : chatterbox_server")
    print("=" * 70)
    print(f"MCP_SERVERLESS_MP4={review_dir / 'final_video.mp4'}")
