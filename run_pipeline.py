"""Full pipeline runner: setting name -> final_video.mp4

Usage:
    python run_pipeline.py "cheese facts" [--engine ffmpeg|dry_run] [--creative-spec path/to/spec.json]

Runs all 9 stages in sequence:
    0. MarketResearchAgent  -> topic_brief.json
    1. FactMiner            -> facts.db (populated for this topic)
    2. ScriptAgent          -> script_package.json
    3. VideoPlanner         -> video_plan.json
    4. AudioAgent           -> audio_timeline.json + MP3s
    5. MusicAgent           -> music_selection.json
    6. VisualAgent          -> visual_manifest.json
    7. CompositorAgent      -> render_spec.json
    8. RenderAgent          -> final_video.mp4
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.agent import create_agent
from src.facts.fact_miner import FactMiner
from src.script_agent import create_script_agent
from src.video_agent import create_video_agent
from src.audio_agent import create_audio_agent
from src.music_agent import create_music_agent
from src.visual_agent import create_visual_agent
from src.composition_agent import create_composition_agent
from src.render_agent import create_render_agent
from src.artifacts.io import ensure_run_dir, new_run_id, write_json
from src.config import (
    ANTHROPIC_API_KEY,
    ELEVENLABS_API_KEY,
    GOOGLE_API_KEY,
    LLM_PROVIDER,
    RESULTS_DIR,
    YOUTUBE_API_KEY,
)
from src.creative_spec import load_creative_spec


COOKIES_PATH = Path(__file__).parent / "youtube_cookies.txt"
_YOUTUBE_DOMAINS = {".youtube.com", "youtube.com", ".googlevideo.com"}
_WARN_DAYS = 30


def check_cookies():
    if not COOKIES_PATH.exists():
        print("[WARN] youtube_cookies.txt not found. Caption extraction may fail (IP blocking).")
        return

    now = int(time.time())
    expired = []
    expiring_soon = []

    with COOKIES_PATH.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _, _, _, expiry_str, name, _ = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
            if domain not in _YOUTUBE_DOMAINS:
                continue
            try:
                expiry = int(expiry_str)
            except ValueError:
                continue
            if expiry == 0:
                continue  # session cookie, no expiry
            days_left = (expiry - now) // 86400
            if days_left < 0:
                expired.append(f"{name} (expired {-days_left}d ago)")
            elif days_left < _WARN_DAYS:
                expiring_soon.append(f"{name} (expires in {days_left}d)")

    if expired:
        print(f"[ERROR] YouTube cookies expired: {', '.join(expired)}")
        print("        Re-export cookies from your browser using a cookies.txt extension.")
        sys.exit(1)
    if expiring_soon:
        print(f"[WARN] YouTube cookies expiring soon: {', '.join(expiring_soon)}")
        print("       Re-export from browser before they expire to avoid caption failures.")
    else:
        print("[OK] YouTube cookies valid")


def check_api_keys():
    missing = []
    if not YOUTUBE_API_KEY:
        missing.append("YOUTUBE_API_KEY")
    if LLM_PROVIDER == "claude" and not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    elif LLM_PROVIDER == "google" and not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    if not ELEVENLABS_API_KEY:
        missing.append("ELEVENLABS_API_KEY")
    if missing:
        print("[ERROR] Missing required API keys:")
        for k in missing:
            print(f"   - {k}")
        sys.exit(1)
    print(f"[OK] API keys configured (LLM provider: {LLM_PROVIDER})")


def validate_final_video(mp4_path) -> bool:
    mp4_path = Path(mp4_path)
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        print(f"[ERROR] Post-render validation FAILED: {mp4_path} missing or empty")
        return False
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type,duration",
            "-of", "csv=p=0",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"[ERROR] Post-render validation FAILED: no readable video stream in {mp4_path.name}")
        print(f"        ffprobe: {result.stderr.strip()}")
        return False
    print(f"[OK] Post-render validation passed: {mp4_path.name} is playable")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run the full Vibe Insta pipeline from a setting name.")
    parser.add_argument("setting", help='Content setting, e.g. "cheese facts" or "ww2 tank facts"')
    parser.add_argument(
        "--engine",
        choices=["ffmpeg", "dry_run"],
        default="dry_run",
        help="Render engine (default: dry_run)",
    )
    parser.add_argument(
        "--creative-spec",
        metavar="PATH",
        default=None,
        help="Optional path to a creative_spec.json",
    )
    args = parser.parse_args()

    setting = args.setting.strip()
    engine = args.engine
    creative_spec = load_creative_spec(Path(args.creative_spec) if args.creative_spec else None)

    check_api_keys()
    check_cookies()

    if not shutil.which("ffmpeg") and engine == "ffmpeg":
        print("[ERROR] ffmpeg not found on PATH. Install it or use --engine dry_run.")
        sys.exit(1)

    # Create the single run directory for the entire pipeline.
    from src.artifacts.io import slugify
    run_id = new_run_id("sample", slugify(setting)[:40])
    run_dir = ensure_run_dir(RESULTS_DIR, run_id)
    print(f"\n[INFO] Run directory: {run_dir}")
    print(f"[INFO] Setting: {setting}")
    print(f"[INFO] Engine: {engine}\n")

    # ------------------------------------------------------------------
    # Stage 0: Market Research -> TopicBrief
    # ------------------------------------------------------------------
    print("[INFO] Stage 0/7: MarketResearchAgent")
    mr_agent = create_agent()
    mr_result = mr_agent.research_category_artifacts(setting)

    topic_brief_paths = mr_result.get("topic_brief_paths") or []
    if not topic_brief_paths:
        print("[ERROR] Stage 0 produced no topic briefs. Aborting pipeline.")
        print("        Try a different setting or check YOUTUBE_API_KEY connectivity.")
        sys.exit(1)

    # Use the top-scored topic brief (first entry).
    source_brief_path = Path(topic_brief_paths[0])
    topic_brief = json.loads(source_brief_path.read_text(encoding="utf-8"))

    # Copy topic_brief into this run's directory for a self-contained record.
    dest_brief_path = run_dir / "topic_brief.json"
    shutil.copy2(source_brief_path, dest_brief_path)

    seed_videos = (topic_brief.get("evidence") or {}).get("seed_videos") or []
    opportunity_score = (topic_brief.get("why_this") or {}).get("opportunity_score") or 0.0
    if not seed_videos or opportunity_score <= 0.0:
        print("[ERROR] Stage 0 topic brief has no real evidence (seed_videos empty or score=0). Aborting pipeline.")
        print("        The LLM fallback fired with no YouTube data. Try a different setting.")
        sys.exit(1)
    print(f"[OK] Stage 0 complete. TopicBrief: {dest_brief_path} (score={opportunity_score:.1f}, {len(seed_videos)} seed videos)")

    # ------------------------------------------------------------------
    # Stage 1: Fact Mining -> facts.db
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 1/8: FactMiner")
    topic_id = str(topic_brief.get("topic_id") or "")
    subtopic_id = str(topic_brief.get("subtopic_id") or "")
    evidence = topic_brief.get("evidence") or {}
    source_queries = list(evidence.get("source_queries") or [])
    topic_query = source_queries[0] if source_queries else setting

    fact_miner = FactMiner()
    mining_result = fact_miner.mine_top_videos(
        topic_query=topic_query,
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        max_videos=5,
        use_captions=True,
    )
    total_facts = mining_result.get("total_facts", 0)
    if total_facts == 0:
        print("[ERROR] Stage 1 mined 0 facts. Aborting pipeline.")
        print("        Captions may be blocked or disabled. Check YOUTUBE_API_KEY and network access.")
        sys.exit(1)
    print(f"[OK] Stage 1 complete. Mined {total_facts} facts into facts.db")

    # ------------------------------------------------------------------
    # Stage 2: Script
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 2/8: ScriptAgent")
    script_agent = create_script_agent()
    script_package = script_agent.generate_script_package(
        topic_brief=topic_brief,
        creative_spec=creative_spec,
    )
    write_json(run_dir / "script_package.json", script_package)
    print(f"[OK] Stage 2 complete. ScriptPackage: {run_dir / 'script_package.json'}")

    # ------------------------------------------------------------------
    # Stage 3: Video plan
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 3/8: VideoPlanner")
    video_agent = create_video_agent()
    video_plan = video_agent.create_video_plan(
        script_package=script_package,
        creative_spec=creative_spec,
    )
    write_json(run_dir / "video_plan.json", video_plan)
    print(f"[OK] Stage 3 complete. VideoPlan: {run_dir / 'video_plan.json'}")

    # ------------------------------------------------------------------
    # Stage 4: Audio timeline + segments
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 4/8: AudioAgent")
    voice = str(video_plan.get("audio", {}).get("tts", {}).get("voice") or "narrator")
    audio_agent = create_audio_agent(output_dir=run_dir, voice=voice)
    audio_timeline = audio_agent.generate_audio_timeline(video_plan)
    write_json(run_dir / "audio_timeline.json", audio_timeline)
    print(f"[OK] Stage 4 complete. AudioTimeline: {run_dir / 'audio_timeline.json'}")

    # ------------------------------------------------------------------
    # Stage 5: Music selection
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 5/8: MusicAgent")
    music_agent = create_music_agent()
    music_selection = music_agent.select_music(audio_timeline)
    write_json(run_dir / "music_selection.json", music_selection)
    print(f"[OK] Stage 5 complete. MusicSelection: {run_dir / 'music_selection.json'}")

    # ------------------------------------------------------------------
    # Stage 6: Visual manifest + assets
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 6/8: VisualAgent")
    visual_agent = create_visual_agent(output_dir=run_dir)
    visual_manifest = visual_agent.generate_visual_manifest(video_plan)
    write_json(run_dir / "visual_manifest.json", visual_manifest)
    print(f"[OK] Stage 6 complete. VisualManifest: {run_dir / 'visual_manifest.json'}")

    # ------------------------------------------------------------------
    # Stage 7: Render spec
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 7/8: CompositorAgent")
    comp_agent = create_composition_agent(output_dir=run_dir)
    render_spec = comp_agent.create_render_specification(
        video_plan, audio_timeline, visual_manifest, music_selection
    )
    write_json(run_dir / "render_spec.json", render_spec)
    print(f"[OK] Stage 7 complete. RenderSpec: {run_dir / 'render_spec.json'}")

    # ------------------------------------------------------------------
    # Stage 8: Render
    # ------------------------------------------------------------------
    print("\n[INFO] Stage 8/8: RenderAgent")
    render_agent = create_render_agent(output_dir=run_dir, engine=engine)
    final_video = render_agent.render(render_spec)
    write_json(run_dir / "final_video.json", final_video)
    print(f"[OK] Stage 8 complete. FinalVideo: {run_dir / 'final_video.mp4'}")

    validate_final_video(run_dir / "final_video.mp4")

    print(f"\n{'='*60}")
    print(f"[OK] Pipeline complete: {run_dir}")
    print(f"{'='*60}")
    print(f"   topic_brief.json      <- Stage 0 (market research)")
    print(f"   facts.db              <- Stage 1 (fact mining)")
    print(f"   script_package.json   <- Stage 2")
    print(f"   video_plan.json       <- Stage 3")
    print(f"   audio_timeline.json   <- Stage 4")
    print(f"   music_selection.json  <- Stage 5")
    print(f"   visual_manifest.json  <- Stage 6")
    print(f"   render_spec.json      <- Stage 7")
    print(f"   final_video.mp4       <- Stage 8")


if __name__ == "__main__":
    main()
