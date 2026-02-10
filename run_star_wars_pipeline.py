"""Star Wars Facts Pipeline - Mine facts and generate grounded script.

This script runs the complete pipeline:
1. Mine facts from top Star Wars videos
2. Generate a RAG-grounded script
3. Display the verified script ready for video production
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from src.facts.fact_store import FactStore
from src.facts.fact_miner import FactMiner
from src.script_agent import ScriptGenerationAgent


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def main():
    print_section("STAR WARS FACTS PIPELINE")
    
    # Initialize
    print("\n[INIT] Setting up fact store and miner...")
    fact_store = FactStore()
    fact_miner = FactMiner(fact_store=fact_store)
    
    # Check if we already have Star Wars facts
    existing_facts = fact_store.query(topic_id="star_wars", limit=1)
    
    if existing_facts:
        print(f"✓ Found existing Star Wars facts in database")
        stats = fact_store.get_stats(topic_id="star_wars")
        print(f"  Total Star Wars facts: {stats['total_facts']}")
        print(f"  Avg engagement: {stats['avg_engagement_score']:.1f}/10")
        
        user_input = input("\nMine more facts? (y/N): ").strip().lower()
        should_mine = user_input == 'y'
    else:
        print("No Star Wars facts found. Will mine from YouTube...")
        should_mine = True
    
    # Mine facts if needed
    if should_mine:
        print_section("STEP 1: MINING FACTS FROM YOUTUBE")
        print("\nSearching for top Star Wars fact videos...")
        print("(This will download captions and extract facts using LLM)")
        print("⏱️  This may take 2-3 minutes...\n")
        
        mining_results = fact_miner.mine_top_videos(
            topic_query="star wars facts explained",
            topic_id="star_wars",
            subtopic_id="facts",
            max_videos=5,  # Top 5 videos
            use_captions=True,
        )
        
        print(f"\n✓ Mining complete!")
        print(f"  Videos processed: {mining_results.get('videos_mined', 0)}")
        print(f"  Facts extracted: {mining_results.get('total_facts', 0)}")
        
        # Show sample facts
        if mining_results.get('video_results'):
            print("\n  Sample extracted facts:")
            for video_result in mining_results['video_results'][:2]:
                if video_result.get('success') and video_result.get('facts'):
                    print(f"\n  From video {video_result['video_id']}:")
                    for fact in video_result['facts'][:2]:
                        print(f"    • {fact['fact_text'][:75]}...")
    
    # Query facts for script generation
    print_section("STEP 2: QUERYING FACT DATABASE")
    
    facts = fact_store.query(
        topic_id="star_wars",
        subtopic_id="facts",
        limit=10,
        min_engagement_score=2.0,
    )
    
    if not facts:
        # Try without subtopic
        facts = fact_store.query(
            topic_id="star_wars",
            limit=10,
            min_engagement_score=1.0,
        )
    
    print(f"\n✓ Retrieved {len(facts)} facts for script generation")
    
    if facts:
        print("\nTop 5 facts by engagement score:")
        for i, fact in enumerate(facts[:5], 1):
            print(f"\n  {i}. [Score: {fact['engagement_score']:.1f}/10]")
            print(f"     {fact['fact_text'][:100]}...")
    else:
        print("\n⚠️  No facts available! Script will be generic.")
    
    # Generate script with RAG
    print_section("STEP 3: GENERATING GROUNDED SCRIPT")
    
    topic_brief = {
        "topic_id": "star_wars",
        "subtopic_id": "facts",
        "topic": {
            "name": "Star Wars",
            "positioning": "Mind-blowing Star Wars facts",
        },
        "subtopic": {
            "name": "Star Wars Facts",
            "angle": "Surprising behind-the-scenes facts and universe lore that even superfans don't know",
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 45,
        },
        "script_constraints": {
            "tone": "energetic, enthusiastic",
            "claims_policy": "Use only verified facts from database",
        }
    }
    
    print("\n⏱️  Generating script with LLM...")
    
    script_agent = ScriptGenerationAgent(fact_store=fact_store)
    script_package = script_agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
        min_facts=3,
        max_facts=10,
    )
    
    print("\n✓ Script generated!")
    
    # Display the script
    print_section("FINAL SCRIPT (Ready for Video Production)")
    
    print(f"\n📋 Script ID: {script_package['script_package_id']}")
    print(f"📊 Facts Used: {len(script_package.get('fact_sources', []))} facts")
    
    if script_package.get('fact_sources'):
        print(f"   Fact IDs: {', '.join(script_package['fact_sources'][:3])}...")
    
    # Get script section
    script = script_package.get('script', {})
    
    # Check if we have the body-based format (new format with facts)
    has_body_format = 'body' in script and 'hook' in script
    
    # Hooks
    print("\n🎣 HOOK:")
    if has_body_format and script.get('hook'):
        print(f"   {script['hook']}")
    else:
        for i, hook in enumerate(script_package.get('hook_variants', []), 1):
            print(f"   {i}. {hook}")
    
    # Script content
    if has_body_format:
        print("\n📜 SCRIPT CONTENT (Fact-Grounded):")
        for i, segment in enumerate(script.get('body', []), 1):
            print(f"\n   Segment {i}:")
            print(f"   {segment.get('content', '')}")
            if segment.get('fact_ids'):
                print(f"   📌 Facts: {', '.join(segment['fact_ids'])}")
        
        if script.get('call_to_action'):
            print(f"\n   🎬 CTA: {script['call_to_action']}")
        
        beats = []  # No beats in this format
    else:
        # Original beats format
        print("\n📜 SCRIPT BEATS:")
        beats = script.get('beats', [])
    
        for i, beat in enumerate(beats, 1):
            t_start = beat.get('t_start_s', 0)
            t_end = beat.get('t_end_s', 0)
            vo_line = beat.get('vo_line', '')
            on_screen = beat.get('on_screen_text', '')
            
            print(f"\n   Beat {i} [{t_start:.1f}s - {t_end:.1f}s]")
            print(f"   🎬 On-Screen: \"{on_screen}\"")
            print(f"   🎙️  Voiceover: \"{vo_line}\"")
    
    # Full voiceover
    print("\n📝 FULL VOICEOVER SCRIPT:")
    print("   " + "-" * 76)
    
    if has_body_format:
        # Construct from body segments
        vo_parts = []
        if script.get('hook'):
            vo_parts.append(script['hook'])
        vo_parts.extend([seg.get('content', '') for seg in script.get('body', [])])
        if script.get('call_to_action'):
            vo_parts.append(script['call_to_action'])
        vo_text = ' '.join(vo_parts)
    else:
        vo_text = script.get('voiceover', '')
    if vo_text:
        # Wrap text nicely
        words = vo_text.split()
        line = "   "
        for word in words:
            if len(line) + len(word) + 1 > 80:
                print(line)
                line = "   " + word
            else:
                line += " " + word if line != "   " else word
        if line.strip():
            print(line)
    else:
        print("   (No voiceover text)")
    print("   " + "-" * 76)
    
    # Caption and hashtags
    print(f"\n📱 CAPTION:")
    print(f"   {script_package.get('caption', 'N/A')}")
    
    print(f"\n🏷️  HASHTAGS:")
    hashtags = script_package.get('hashtags', [])
    print(f"   {' '.join(hashtags)}")
    
    # Safety notes
    if script_package.get('safety_notes'):
        print(f"\n⚠️  SAFETY NOTES:")
        for note in script_package['safety_notes']:
            print(f"   • {note}")
    
    # Save output
    print_section("SAVING OUTPUT")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(__file__).parent / "results" / f"star_wars_pipeline_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    FACT-GROUNDED SCRIPT\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Script ID: {script_package['script_package_id']}\n")
        f.write(f"Duration: {topic_brief['format']['target_duration_seconds']}s\n")
        f.write(f"Facts Used: {len(script_package.get('fact_sources', []))}\n\n")
        
        if has_body_format:
            # Write fact-grounded format
            f.write("=" * 80 + "\n")
            f.write("HOOK:\n")
            f.write("=" * 80 + "\n")
            f.write(script.get('hook', '') + "\n\n")
            
            f.write("=" * 80 + "\n")
            f.write("FACT-BASED CONTENT:\n")
            f.write("=" * 80 + "\n\n")
            
            for i, segment in enumerate(script.get('body', []), 1):
                f.write(f"Segment {i}:\n")
                f.write(f"{segment.get('content', '')}\n")
                if segment.get('fact_ids'):
                    f.write(f"Facts: {', '.join(segment['fact_ids'])}\n")
                f.write("\n")
            
            f.write("=" * 80 + "\n")
            f.write("CALL TO ACTION:\n")
            f.write("=" * 80 + "\n")
            f.write(script.get('call_to_action', '') + "\n\n")
            
            f.write("=" * 80 + "\n")
            f.write("FULL VOICEOVER:\n")
            f.write("=" * 80 + "\n")
            f.write(vo_text + "\n\n")
        else:
            # Write beat-based format
            f.write("HOOKS:\n")
            for i, hook in enumerate(script_package.get('hook_variants', []), 1):
                f.write(f"  {i}. {hook}\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("FULL VOICEOVER:\n")
            f.write("=" * 80 + "\n")
            f.write(vo_text + "\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("BEAT-BY-BEAT BREAKDOWN:\n")
            f.write("=" * 80 + "\n\n")
            
            for i, beat in enumerate(beats, 1):
                f.write(f"Beat {i} [{beat.get('t_start_s', 0):.1f}s - {beat.get('t_end_s', 0):.1f}s]\n")
                f.write(f"  On-Screen: {beat.get('on_screen_text', '')}\n")
            f.write("FULL VOICEOVER:\n")
        f.write("=" * 80 + "\n")
        f.write(vo_text + "\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("BEAT-BY-BEAT BREAKDOWN:\n")
        f.write("=" * 80 + "\n\n")
        
        for i, beat in enumerate(beats, 1):
            f.write(f"Beat {i} [{beat.get('t_start_s', 0):.1f}s - {beat.get('t_end_s', 0):.1f}s]\n")
            f.write(f"  On-Screen: {beat.get('on_screen_text', '')}\n")
            f.write(f"  Voiceover: {beat.get('vo_line', '')}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write(f"Caption: {script_package.get('caption', '')}\n")
        f.write(f"Hashtags: {' '.join(hashtags)}\n")
    
    print(f"✓ Readable version: {readable_path}")
    
    # Database stats
    print("\n📊 FACT DATABASE STATS:")
    db_stats = fact_store.get_stats()
    print(f"   Total facts (all topics): {db_stats['total_facts']}")
    
    star_wars_stats = fact_store.get_stats(topic_id="star_wars")
    print(f"   Star Wars facts: {star_wars_stats['total_facts']}")
    print(f"   Avg engagement: {star_wars_stats['avg_engagement_score']:.1f}/10")
    
    print_section("PIPELINE COMPLETE! 🎬")
    
    print("""
✅ Your Star Wars script is ready for video production!

Next steps:
  1. Review the script in: {readable_path.name}
  2. Edit if needed (or regenerate with different facts)
  3. Proceed to video generation pipeline
  
To regenerate with different facts:
  python run_star_wars_pipeline.py
""".format(readable_path=readable_path))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Pipeline interrupted by user.")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
