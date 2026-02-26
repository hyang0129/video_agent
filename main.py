"""Main entry point for Market Research Agent."""

import sys
import warnings
# Suppress Google API warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="google")

from pathlib import Path
import json
import shutil

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.agent import create_agent
from src.script_agent import create_script_agent, generate_offline_script_package
from src.video_agent import create_video_agent
from src.audio_agent import create_audio_agent
from src.visual_agent import create_visual_agent
from src.composition_agent import create_composition_agent
from src.render_agent import create_render_agent
from src.script_image_agent import ScriptImageConfig, create_script_image_agent
from src.artifacts.io import ensure_run_dir, new_run_id, write_json
from src.config import YOUTUBE_API_KEY, GOOGLE_API_KEY, ELEVENLABS_API_KEY, RESULTS_DIR
from src.creative_spec import load_creative_spec


def check_api_keys():
    """Verify that required API keys are configured."""
    missing = []
    
    if not YOUTUBE_API_KEY:
        missing.append("YOUTUBE_API_KEY")
    if not GOOGLE_API_KEY:
        missing.append("GOOGLE_API_KEY")
    
    if missing:
        print("❌ Missing required API keys:")
        for key in missing:
            print(f"   - {key}")
        print("\nPlease:")
        print("1. Copy .env.example to .env")
        print("2. Add your API keys to .env")
        print("3. Get YouTube API key: https://console.cloud.google.com/apis/credentials")
        print("4. Get Google AI Studio key: https://aistudio.google.com/app/apikey (FREE!)")
        sys.exit(1)
    
    print("✅ API keys configured")


def check_tts_key():
    """Verify TTS API key is configured for audio generation."""
    if ELEVENLABS_API_KEY:
        print("✅ ELEVENLABS_API_KEY configured")
        return

    print("❌ Missing required API key: ELEVENLABS_API_KEY")
    print("\nPlease:")
    print("1. Copy .env.example to .env")
    print("2. Add ELEVENLABS_API_KEY to .env")
    print("3. Get ElevenLabs key: https://elevenlabs.io/app/settings/api-keys")
    sys.exit(1)


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


def example_research_category():
    """Example: Research a broad category."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Research a Category")
    print("="*60 + "\n")
    
    agent = create_agent()

    exported = agent.research_category_artifacts("science fiction")
    print(f"\n✅ Exported artifacts to: {exported['run_dir']}")
    print(f"Report: {exported['report_path']}")
    if exported.get("topic_brief_paths"):
        print("Topic briefs:")
        for p in exported["topic_brief_paths"]:
            print(f"- {p}")


def example_analyze_topic():
    """Example: Deep dive into a specific topic."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Analyze Specific Topic")
    print("="*60 + "\n")
    
    agent = create_agent()
    
    result = agent.analyze_topic("sci-fi movie facts")
    print(result)


def example_find_opportunities():
    """Example: Scan multiple categories for best opportunities."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Find Top Opportunities")
    print("="*60 + "\n")
    
    agent = create_agent()
    
    categories = [
        "science fiction",
        "ancient history",
        "space exploration",
        "true crime",
    ]
    
    result = agent.find_opportunities(categories, min_score=6.0)
    print(result)


def interactive_mode():
    """Interactive chat mode with the agent."""
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("\nType your research questions. Type 'quit' to exit.\n")
    
    agent = create_agent()
    
    while True:
        try:
            query = input("\n🔍 Your query: ").strip()
            
            if query.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            
            if not query:
                continue
            
            print("\n🤖 Agent working...\n")
            result = agent.chat(query)
            print(result)
            
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


def main():
    """Main function."""
    print("="*60)
    print("YouTube Market Research Agent")
    print("="*60)
    
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

        # Only require API keys for modes that actually call external LLM/YouTube APIs.
        if mode in {"example1", "example2", "example3", "interactive", "script"}:
            check_api_keys()
        if mode in {"mvp"}:
            # MVP runs script generation (Google) + audio (ElevenLabs).
            if not GOOGLE_API_KEY:
                check_api_keys()
            check_tts_key()
        
        if mode == "example1":
            example_research_category()
        elif mode == "example2":
            example_analyze_topic()
        elif mode == "example3":
            example_find_opportunities()
        elif mode == "interactive":
            interactive_mode()
        elif mode == "preflight":
            preflight()
        elif mode == "script":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py script <path-to-topicbrief.json>")
                sys.exit(2)

            topic_brief_path = Path(sys.argv[2]).expanduser().resolve()
            if not topic_brief_path.exists():
                print(f"\n❌ TopicBrief not found: {topic_brief_path}")
                sys.exit(2)

            creative_spec_path = None
            if len(sys.argv) >= 4:
                creative_spec_path = Path(sys.argv[3])
            creative_spec = load_creative_spec(creative_spec_path)

            topic_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
            agent = create_script_agent()
            script_package = agent.generate_script_package(
                topic_brief=topic_brief,
                creative_spec=creative_spec,
            )

            run_id = new_run_id("sg", f"{script_package.get('topic_id','topic')}_{script_package.get('subtopic_id','sub')}")
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)
            out_path = run_dir / "script_package.json"
            write_json(out_path, script_package)
            print(f"\n✅ Wrote ScriptPackage: {out_path}")
        elif mode == "videoplan":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py videoplan <path-to-script_package.json>")
                sys.exit(2)

            script_package_path = Path(sys.argv[2]).expanduser().resolve()
            if not script_package_path.exists():
                print(f"\n❌ ScriptPackage not found: {script_package_path}")
                sys.exit(2)

            creative_spec_path = None
            if len(sys.argv) >= 4:
                creative_spec_path = Path(sys.argv[3])
            creative_spec = load_creative_spec(creative_spec_path)

            script_package = json.loads(script_package_path.read_text(encoding="utf-8"))
            agent = create_video_agent()
            video_plan = agent.create_video_plan(script_package=script_package, creative_spec=creative_spec)

            run_id = new_run_id("vp", f"{video_plan.get('topic_id','topic')}_{video_plan.get('subtopic_id','sub')}")
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)
            out_path = run_dir / "video_plan.json"
            write_json(out_path, video_plan)
            print(f"\n✅ Wrote VideoPlan: {out_path}")
        elif mode == "visualmanifest":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py visualmanifest <path-to-video_plan.json>")
                sys.exit(2)

            video_plan_path = Path(sys.argv[2]).expanduser().resolve()
            if not video_plan_path.exists():
                print(f"\n❌ VideoPlan not found: {video_plan_path}")
                sys.exit(2)

            video_plan = json.loads(video_plan_path.read_text(encoding="utf-8"))
            run_id = new_run_id("vm", f"{video_plan.get('topic_id','topic')}_{video_plan.get('subtopic_id','sub')}")
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)

            agent = create_visual_agent(output_dir=run_dir)
            visual_manifest = agent.generate_visual_manifest(video_plan)
            out_path = run_dir / "visual_manifest.json"
            write_json(out_path, visual_manifest)
            print(f"\n✅ Wrote VisualManifest: {out_path}")
        elif mode == "scriptimages":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py scriptimages <path-to-script_package.json>")
                sys.exit(2)

            script_package_path = Path(sys.argv[2]).expanduser().resolve()
            if not script_package_path.exists():
                print(f"\n❌ ScriptPackage not found: {script_package_path}")
                sys.exit(2)

            script_package = json.loads(script_package_path.read_text(encoding="utf-8"))
            run_id = new_run_id(
                "sim",
                f"{script_package.get('topic_id','topic')}_{script_package.get('subtopic_id','sub')}",
            )
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)

            agent = create_script_image_agent(
                ScriptImageConfig(
                    output_dir=run_dir,
                    min_candidates_per_segment=1,
                    max_candidates_per_segment=5,
                )
            )
            manifest = agent.generate_script_image_manifest(script_package=script_package)

            out_path = run_dir / "script_image_manifest.json"
            write_json(out_path, manifest)
            print(f"\n✅ Wrote ScriptImageManifest: {out_path}")
        elif mode == "audio":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py audio <path-to-video_plan.json> [voice]")
                sys.exit(2)

            video_plan_path = Path(sys.argv[2]).expanduser().resolve()
            if not video_plan_path.exists():
                print(f"\n❌ VideoPlan not found: {video_plan_path}")
                sys.exit(2)

            voice = "narrator"
            if len(sys.argv) >= 4:
                voice = str(sys.argv[3]).strip() or "narrator"

            if voice.strip().lower() not in {"silent", "none", "off"}:
                check_tts_key()

            video_plan = json.loads(video_plan_path.read_text(encoding="utf-8"))

            # Write audio outputs next to the VideoPlan so downstream paths stay render-spec-relative.
            out_dir = video_plan_path.parent
            agent = create_audio_agent(output_dir=out_dir, voice=voice)
            audio_timeline = agent.generate_audio_timeline(video_plan)

            out_path = out_dir / "audio_timeline.json"
            write_json(out_path, audio_timeline)
            print(f"\n✅ Wrote AudioTimeline: {out_path}")
            print(f"   Segments: {out_dir / 'audio_segments'}")
        elif mode == "mvp":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py mvp <path-to-topicbrief.json> [creative_spec.json] [ffmpeg|dry_run]")
                sys.exit(2)

            topic_brief_path = Path(sys.argv[2]).expanduser().resolve()
            if not topic_brief_path.exists():
                print(f"\n❌ TopicBrief not found: {topic_brief_path}")
                sys.exit(2)

            creative_spec_path = None
            if len(sys.argv) >= 4:
                creative_spec_path = Path(sys.argv[3])
            creative_spec = load_creative_spec(creative_spec_path)

            engine = "dry_run"
            if len(sys.argv) >= 5:
                engine = str(sys.argv[4]).strip().lower() or "dry_run"

            topic_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
            topic_id = str(topic_brief.get("topic_id") or "topic")
            subtopic_id = str(topic_brief.get("subtopic_id") or "sub")

            run_id = new_run_id("sample", f"{topic_id}_{subtopic_id}")
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)

            # 1) Script
            script_agent = create_script_agent()
            script_package = script_agent.generate_script_package(topic_brief=topic_brief, creative_spec=creative_spec)
            write_json(run_dir / "script_package.json", script_package)

            # 2) Video plan
            video_agent = create_video_agent()
            video_plan = video_agent.create_video_plan(script_package=script_package, creative_spec=creative_spec)
            write_json(run_dir / "video_plan.json", video_plan)

            # 3) Audio timeline + segments
            audio_agent = create_audio_agent(output_dir=run_dir, voice=str(video_plan.get("audio", {}).get("tts", {}).get("voice") or "narrator"))
            audio_timeline = audio_agent.generate_audio_timeline(video_plan)
            write_json(run_dir / "audio_timeline.json", audio_timeline)

            # 4) Visual manifest + assets (uses placeholders if Pexels not configured)
            visual_agent = create_visual_agent(output_dir=run_dir)
            visual_manifest = visual_agent.generate_visual_manifest(video_plan)
            write_json(run_dir / "visual_manifest.json", visual_manifest)

            # 5) Render spec
            comp_agent = create_composition_agent(output_dir=run_dir)
            render_spec = comp_agent.create_render_specification(video_plan, audio_timeline, visual_manifest)
            write_json(run_dir / "render_spec.json", render_spec)

            # 6) Render
            render_agent = create_render_agent(output_dir=run_dir, engine=engine)
            final_video = render_agent.render(render_spec)
            write_json(run_dir / "final_video.json", final_video)

            print(f"\n✅ MVP run complete: {run_dir}")
            print(f"   - ScriptPackage: {run_dir / 'script_package.json'}")
            print(f"   - VideoPlan: {run_dir / 'video_plan.json'}")
            print(f"   - AudioTimeline: {run_dir / 'audio_timeline.json'}")
            print(f"   - VisualManifest: {run_dir / 'visual_manifest.json'}")
            print(f"   - RenderSpec: {run_dir / 'render_spec.json'}")
            print(f"   - FinalVideo: {run_dir / 'final_video.json'}")
            print(f"   - MP4: {run_dir / 'final_video.mp4'}")
        elif mode == "mvp_offline":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py mvp_offline <path-to-topicbrief.json> [creative_spec.json] [ffmpeg|dry_run]")
                sys.exit(2)

            topic_brief_path = Path(sys.argv[2]).expanduser().resolve()
            if not topic_brief_path.exists():
                print(f"\n❌ TopicBrief not found: {topic_brief_path}")
                sys.exit(2)

            creative_spec_path = None
            if len(sys.argv) >= 4:
                creative_spec_path = Path(sys.argv[3])
            creative_spec = load_creative_spec(creative_spec_path)

            engine = "dry_run"
            if len(sys.argv) >= 5:
                engine = str(sys.argv[4]).strip().lower() or "dry_run"

            topic_brief = json.loads(topic_brief_path.read_text(encoding="utf-8"))
            topic_id = str(topic_brief.get("topic_id") or "topic")
            subtopic_id = str(topic_brief.get("subtopic_id") or "sub")

            run_id = new_run_id("sample", f"{topic_id}_{subtopic_id}_offline")
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)

            # 1) Script (offline template)
            script_package = generate_offline_script_package(topic_brief=topic_brief, creative_spec=creative_spec)
            write_json(run_dir / "script_package.json", script_package)

            # 2) Video plan
            video_agent = create_video_agent()
            video_plan = video_agent.create_video_plan(script_package=script_package, creative_spec=creative_spec)
            write_json(run_dir / "video_plan.json", video_plan)

            # 3) Audio timeline + segments (silent placeholder)
            audio_agent = create_audio_agent(output_dir=run_dir, voice="silent")
            audio_timeline = audio_agent.generate_audio_timeline(video_plan)
            write_json(run_dir / "audio_timeline.json", audio_timeline)

            # 4) Visual manifest + assets
            visual_agent = create_visual_agent(output_dir=run_dir)
            visual_manifest = visual_agent.generate_visual_manifest(video_plan)
            write_json(run_dir / "visual_manifest.json", visual_manifest)

            # 5) Render spec
            comp_agent = create_composition_agent(output_dir=run_dir)
            render_spec = comp_agent.create_render_specification(video_plan, audio_timeline, visual_manifest)
            write_json(run_dir / "render_spec.json", render_spec)

            # 6) Render
            render_agent = create_render_agent(output_dir=run_dir, engine=engine)
            final_video = render_agent.render(render_spec)
            write_json(run_dir / "final_video.json", final_video)

            print(f"\n✅ Offline MVP run complete: {run_dir}")
            print(f"   - RenderSpec: {run_dir / 'render_spec.json'}")
            print(f"   - MP4: {run_dir / 'final_video.mp4'}")
        elif mode == "renderspec":
            if len(sys.argv) < 5:
                print("\n❌ Usage: python main.py renderspec <video_plan.json> <audio_timeline.json> <visual_manifest.json>")
                sys.exit(2)

            video_plan_path = Path(sys.argv[2]).expanduser().resolve()
            audio_timeline_path = Path(sys.argv[3]).expanduser().resolve()
            visual_manifest_path = Path(sys.argv[4]).expanduser().resolve()

            for p, name in [
                (video_plan_path, "VideoPlan"),
                (audio_timeline_path, "AudioTimeline"),
                (visual_manifest_path, "VisualManifest"),
            ]:
                if not p.exists():
                    print(f"\n❌ {name} not found: {p}")
                    sys.exit(2)

            video_plan = json.loads(video_plan_path.read_text(encoding="utf-8"))
            audio_timeline = json.loads(audio_timeline_path.read_text(encoding="utf-8"))
            visual_manifest = json.loads(visual_manifest_path.read_text(encoding="utf-8"))

            run_id = new_run_id("rs", f"{video_plan.get('topic_id','topic')}_{video_plan.get('subtopic_id','sub')}")
            run_dir = ensure_run_dir(RESULTS_DIR, run_id)

            agent = create_composition_agent(output_dir=run_dir)
            render_spec = agent.create_render_specification(video_plan, audio_timeline, visual_manifest)
            out_path = run_dir / "render_spec.json"
            write_json(out_path, render_spec)
            print(f"\n✅ Wrote RenderSpecification: {out_path}")
        elif mode == "render":
            if len(sys.argv) < 3:
                print("\n❌ Usage: python main.py render <path-to-render_spec.json> [ffmpeg|dry_run]")
                sys.exit(2)

            render_spec_path = Path(sys.argv[2]).expanduser().resolve()
            if not render_spec_path.exists():
                print(f"\n❌ RenderSpecification not found: {render_spec_path}")
                sys.exit(2)

            engine = "dry_run"
            if len(sys.argv) >= 4:
                engine = sys.argv[3].strip().lower()

            render_spec = json.loads(render_spec_path.read_text(encoding="utf-8"))
            # Assume render-spec-relative paths; use the render spec folder as work dir.
            run_dir = render_spec_path.parent
            agent = create_render_agent(output_dir=run_dir, engine=engine)
            final_video = agent.render(render_spec)

            out_path = run_dir / "final_video.json"
            write_json(out_path, final_video)
            print(f"\n✅ Wrote FinalVideo: {out_path}")
        else:
            print(f"\n❌ Unknown mode: {mode}")
            print_usage()
    else:
        print_usage()


def print_usage():
    """Print usage instructions."""
    print("\nUsage:")
    print("  python main.py example1        - Research a category")
    print("  python main.py example2        - Analyze specific topic")
    print("  python main.py example3        - Find top opportunities")
    print("  python main.py interactive     - Interactive chat mode")
    print("  python main.py preflight       - Check keys + FFmpeg availability")
    print("  python main.py script <topicbrief.json> [creative_spec.json]   - Generate script")
    print("  python main.py videoplan <script_package.json> [creative_spec.json] - Create VideoPlan")
    print("  python main.py scriptimages <script_package.json> - Create ScriptImageManifest (artifact-only)")
    print("  python main.py audio <video_plan.json> [voice] - Generate AudioTimeline + voiceover segments")
    print("  python main.py visualmanifest <video_plan.json> - Create VisualManifest")
    print("  python main.py renderspec <video_plan.json> <audio_timeline.json> <visual_manifest.json> - Create RenderSpec")
    print("  python main.py render <render_spec.json> [ffmpeg|dry_run] - Render final video")
    print("  python main.py mvp <topicbrief.json> [creative_spec.json] [ffmpeg|dry_run] - End-to-end MVP")
    print("  python main.py mvp_offline <topicbrief.json> [creative_spec.json] [ffmpeg|dry_run] - End-to-end offline MVP")
    print("\nOr import and use programmatically:")
    print("  from src.agent import create_agent")
    print("  agent = create_agent()")
    print("  result = agent.research_category('your category')")


if __name__ == "__main__":
    main()
