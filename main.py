"""Main entry point for Market Research Agent."""

import sys
import warnings
# Suppress Google API warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="google")

from pathlib import Path
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.agent import create_agent
from src.script_agent import create_script_agent
from src.video_agent import create_video_agent
from src.artifacts.io import ensure_run_dir, new_run_id, write_json
from src.config import YOUTUBE_API_KEY, GOOGLE_API_KEY, RESULTS_DIR
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
    
    # Check API keys
    check_api_keys()
    
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        
        if mode == "example1":
            example_research_category()
        elif mode == "example2":
            example_analyze_topic()
        elif mode == "example3":
            example_find_opportunities()
        elif mode == "interactive":
            interactive_mode()
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
    print("  python main.py script <topicbrief.json> [creative_spec.json]   - Generate script")
    print("  python main.py videoplan <script_package.json> [creative_spec.json] - Create VideoPlan")
    print("\nOr import and use programmatically:")
    print("  from src.agent import create_agent")
    print("  agent = create_agent()")
    print("  result = agent.research_category('your category')")


if __name__ == "__main__":
    main()
