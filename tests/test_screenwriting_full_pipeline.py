"""Full screenwriting pipeline integration test.

Runs all screenwriting stages in sequence:
  1. ConceptAgent      -> Concept artifacts
  2. ScreenplayAgent   -> Screenplay artifact
  3. ScreenplayReviewer -> FeasibilityReport artifact
  4. screenplay_to_script_package -> ScriptPackage artifact  [primary review target]
  5. script_package_to_video_plan -> VideoPlan
  6. AudioAgent        -> AudioTimeline + MP3 segments
  7. VisualAgent       -> VisualManifest + images
  8. CompositionAgent  -> RenderSpec
  9. RenderAgent       -> final_video.mp4

The final_video.mp4 and all intermediate artifacts are copied to
results/test/stages/screenwriting_<timestamp>/ for human review.

The canonical test topic is WW2 Tanks (tests/fixtures/topic_brief_ww2_tanks.json).

Usage:
    venv/Scripts/python.exe -m pytest tests/test_screenwriting_full_pipeline.py -v -s

Environment variables:
    ANTHROPIC_API_KEY or GOOGLE_API_KEY  -- required (LLM for concept/screenplay)
    ELEVENLABS_API_KEY                   -- optional (TTS; falls back to silent)
    PIPELINE_TEST_TTS_MODE               -- auto|real|silent (default: auto)
    PIPELINE_TEST_FORMAT                 -- facts|storytime|tutorial|debate (default: storytime)
    PIPELINE_TEST_N_CONCEPTS             -- integer (default: 2)
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
from src.audio_agent import create_audio_agent
from src.composition_agent import create_composition_agent
from src.render_agent import create_render_agent
from src.screenwriting.concept_agent import ConceptAgent
from src.screenwriting.screenplay_agent import ScreenplayAgent
from src.screenwriting.screenplay_reviewer import ScreenplayReviewer
from src.video_planner import script_package_to_video_plan
from src.visual_agent import create_visual_agent

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TOPIC_BRIEF_PATH = _FIXTURES_DIR / "topic_brief_ww2_tanks.json"
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_topic_brief() -> dict:
    return json.loads(_TOPIC_BRIEF_PATH.read_text(encoding="utf-8"))


def _select_voice(tts_mode: str) -> str:
    mode = tts_mode.strip().lower()
    if mode == "real":
        return "narrator"
    if mode == "silent":
        return "silent"
    # auto: use real TTS if key present
    return "narrator" if os.getenv("ELEVENLABS_API_KEY") else "silent"


@pytest.mark.integration
def test_screenwriting_full_pipeline(tmp_path: Path) -> None:
    """Run the full screenwriting pipeline from TopicBrief to final_video.mp4.

    Human review targets (in priority order):
      1. script_package.json   -- does the VO and scene breakdown make sense?
      2. screenplay_1.json     -- are scene descriptions concrete and specific?
      3. feasibility_1.json    -- are the reviewer flags reasonable?
      4. final_video.mp4       -- is the output watchable?
    """
    has_llm = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if not has_llm:
        pytest.skip("Missing ANTHROPIC_API_KEY or GOOGLE_API_KEY")
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg not found on PATH")

    run_dir = tmp_path / "screenwriting_pipeline"
    run_dir.mkdir(parents=True, exist_ok=True)

    fmt = os.getenv("PIPELINE_TEST_FORMAT", "storytime").strip().lower()
    n_concepts = int(os.getenv("PIPELINE_TEST_N_CONCEPTS", "2"))
    tts_mode = os.getenv("PIPELINE_TEST_TTS_MODE", "auto").strip().lower()
    selected_voice = _select_voice(tts_mode)

    topic_brief = _load_topic_brief()

    # --- Stage 1: ConceptAgent ---
    print(f"\n[INFO] Stage 1: Generating {n_concepts} concept(s) (format={fmt})...")
    concept_agent = ConceptAgent()
    concepts = concept_agent.generate_concepts(
        topic_brief=topic_brief,
        n_concepts=n_concepts,
        formats=[fmt],
    )
    assert concepts, "ConceptAgent returned no concepts"
    assert all("concept_id" in c for c in concepts)
    assert all("hook" in c and c["hook"] for c in concepts)

    for i, concept in enumerate(concepts, 1):
        write_json(run_dir / f"concept_{i}.json", concept)
    print(f"[OK] {len(concepts)} concept(s) written")

    # --- Stage 2: ScreenplayAgent ---
    print(f"\n[INFO] Stage 2: Writing screenplay for top concept...")
    screenplay_agent = ScreenplayAgent()
    reviewer = ScreenplayReviewer()

    entries = []
    for i, concept in enumerate(concepts, 1):
        sp = screenplay_agent.write_screenplay(concept=concept, topic_brief=topic_brief)
        report = reviewer.review(sp)
        sp["feasibility_report"] = report
        write_json(run_dir / f"screenplay_{i}.json", sp)
        write_json(run_dir / f"feasibility_{i}.json", report)
        entries.append((concept, sp, report))
        print(
            f"  concept {i}: format={concept['format']} "
            f"score={report['overall_score']:.2f} action={report['recommended_action']} "
            f"scenes={len(sp.get('scenes') or [])}"
        )

    # --- Stage 3: ScreenplayReviewer assertions ---
    for i, (concept, sp, report) in enumerate(entries, 1):
        assert "overall_score" in report
        assert report["recommended_action"] in ("approve", "revise_scenes", "reject"), \
            f"screenplay {i}: unexpected action {report['recommended_action']}"
        scenes = sp.get("scenes") or []
        assert scenes, f"screenplay {i}: has no scenes"
        for scene in scenes:
            assert scene.get("scene_id"), f"screenplay {i}: scene missing scene_id"
            assert scene.get("vo_line"), f"screenplay {i}: scene {scene.get('scene_id')} missing vo_line"
            assert scene.get("visual", {}).get("description"), \
                f"screenplay {i}: scene {scene.get('scene_id')} missing visual.description"

    # Select the highest-scoring screenplay
    entries_sorted = sorted(entries, key=lambda e: e[2]["overall_score"], reverse=True)
    chosen_concept, chosen_sp, chosen_report = entries_sorted[0]
    print(f"\n[OK] Selected screenplay: format={chosen_concept['format']} score={chosen_report['overall_score']:.2f}")
    write_json(run_dir / "screenplay_selected.json", chosen_sp)

    # --- Stage 4: screenplay_to_script_package bridge ---
    print("\n[INFO] Stage 4: Converting Screenplay -> ScriptPackage...")
    script_package = screenplay_to_script_package(chosen_sp)

    assert "script" in script_package
    beats = (script_package.get("script") or {}).get("beats") or []
    assert beats, "ScriptPackage has no beats after bridge conversion"
    assert beats[0]["t_start_s"] == 0.0, "First beat must start at 0.0"
    for beat in beats:
        assert beat.get("vo_line"), f"Beat missing vo_line: {beat}"

    write_json(run_dir / "script_package.json", script_package)
    print(f"[OK] ScriptPackage: {len(beats)} beats, voiceover={len(script_package['script'].get('voiceover',''))} chars")

    # --- Stage 5: VideoPlanner ---
    print("\n[INFO] Stage 5: Creating VideoPlan...")
    video_plan = script_package_to_video_plan(script_package=script_package)
    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = selected_voice
    write_json(run_dir / "video_plan.json", video_plan)
    print(f"[OK] VideoPlan written (voice={selected_voice})")

    # --- Stage 6: AudioAgent ---
    print(f"\n[INFO] Stage 6: Generating audio (voice={selected_voice})...")
    audio_agent = create_audio_agent(output_dir=run_dir, voice=selected_voice)
    audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)
    write_json(run_dir / "audio_timeline.json", audio_timeline)
    segments = audio_timeline.get("segments") or []
    print(f"[OK] AudioTimeline: {len(segments)} segment(s), total_duration={audio_timeline.get('total_duration_s')}s")

    # --- Stage 7: VisualAgent ---
    print("\n[INFO] Stage 7: Fetching visual assets...")
    visual_agent = create_visual_agent(
        output_dir=run_dir,
        image_sources=("pexels",) if os.getenv("PEXELS_API_KEY") else (),
        content_validator="none",
    )
    visual_manifest = visual_agent.generate_visual_manifest(video_plan=video_plan)
    write_json(run_dir / "visual_manifest.json", visual_manifest)
    clips = visual_manifest.get("clips") or []
    print(f"[OK] VisualManifest: {len(clips)} clip(s)")

    # --- Stage 8: CompositionAgent ---
    print("\n[INFO] Stage 8: Creating RenderSpec...")
    comp_agent = create_composition_agent(output_dir=run_dir)
    render_spec = comp_agent.create_render_specification(
        video_plan=video_plan,
        audio_timeline=audio_timeline,
        visual_manifest=visual_manifest,
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
    print(f"[OK] Rendered: {final_mp4.name} ({final_mp4.stat().st_size // 1024} KB)")

    # --- Copy to persistent review dir ---
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_root = _PROJECT_ROOT / "results" / "test" / "stages"
    review_root.mkdir(parents=True, exist_ok=True)
    review_dir = review_root / f"screenwriting_{stamp}"
    shutil.copytree(run_dir, review_dir)

    # --- Human review summary ---
    print("\n" + "=" * 70)
    print("SCREENWRITING PIPELINE -- HUMAN REVIEW TARGETS")
    print("=" * 70)
    print(f"Review dir : {review_dir}")
    print(f"Script pkg : {review_dir / 'script_package.json'}")
    print(f"Screenplay : {review_dir / 'screenplay_selected.json'}")
    print(f"Feasibility: {review_dir / 'feasibility_1.json'}")
    print(f"MP4        : {review_dir / 'final_video.mp4'}")
    print("\nWhat to check:")
    print("  1. script_package.json -> beats VO lines are on-topic and well-paced")
    print("  2. screenplay_selected.json -> visual.description is concrete (not 'people talking')")
    print("  3. feasibility_*.json -> reviewer flags match actual quality issues")
    print("  4. final_video.mp4 -> watchable, audio plays, images render")
    print("=" * 70)

    # --- Structured output for CI ---
    print(f"SCREENWRITING_REVIEW_DIR={review_dir}")
    print(f"SCREENWRITING_MP4={review_dir / 'final_video.mp4'}")
    print(f"SCREENWRITING_SCRIPT_PACKAGE={review_dir / 'script_package.json'}")
