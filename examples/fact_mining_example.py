"""Example: Fact Mining and RAG-Powered Script Generation

This example demonstrates the complete fact mining and script generation workflow:

1. Mine facts from top YouTube videos on a topic
2. Store facts in the fact database
3. Generate a script using RAG (Retrieval-Augmented Generation)
4. Compare with non-RAG script generation

Usage:
    python examples/fact_mining_example.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.facts.fact_store import FactStore
from src.facts.fact_miner import FactMiner
from src.script_agent import ScriptGenerationAgent
import json


def main():
    """Run the fact mining and RAG script generation example."""
    
    print("=" * 80)
    print("FACT MINING & RAG-POWERED SCRIPT GENERATION EXAMPLE")
    print("=" * 80)
    
    # Step 1: Initialize components
    print("\n[1] Initializing fact store and miner...")
    fact_store = FactStore()
    fact_miner = FactMiner(fact_store=fact_store)
    
    # Check existing facts
    stats = fact_store.get_stats()
    print(f"   Current fact database: {stats['total_facts']} facts")
    
    # Step 2: Mine facts from top videos
    print("\n[2] Mining facts from top Star Wars videos...")
    print("   (This will download captions and extract facts using LLM)")
    
    topic_id = "star_wars"
    subtopic_id = "facts"
    
    mining_results = fact_miner.mine_top_videos(
        topic_query="star wars facts explained",
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        max_videos=3,  # Start with 3 videos for testing
        use_captions=True,
    )
    
    print(f"\n   Mining Results:")
    print(f"   - Videos found: {mining_results.get('videos_found', 0)}")
    print(f"   - Videos mined: {mining_results.get('videos_mined', 0)}")
    print(f"   - Total facts extracted: {mining_results.get('total_facts', 0)}")
    
    # Show some extracted facts
    print("\n   Sample extracted facts:")
    for video_result in mining_results.get('video_results', [])[:2]:
        if video_result.get('success') and video_result.get('facts'):
            print(f"\n   Video: {video_result.get('video_id')}")
            for fact in video_result['facts'][:3]:
                print(f"      • {fact['fact_text'][:80]}...")
    
    # Step 3: Query facts from store
    print("\n[3] Querying fact store...")
    stored_facts = fact_store.query(
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        limit=10,
    )
    
    print(f"   Retrieved {len(stored_facts)} facts for script generation")
    if stored_facts:
        print("\n   Top 3 facts by engagement:")
        for i, fact in enumerate(stored_facts[:3], 1):
            print(f"   {i}. [{fact['engagement_score']:.1f}/10] {fact['fact_text'][:70]}...")
    
    # Step 4: Generate script with RAG
    print("\n[4] Generating script WITH RAG (fact-grounded)...")
    
    topic_brief = {
        "topic_id": topic_id,
        "subtopic_id": subtopic_id,
        "topic": {
            "name": "Star Wars",
            "positioning": "Surprising facts about Star Wars",
        },
        "subtopic": {
            "name": "Star Wars Facts",
            "angle": "Lesser-known trivia that will surprise fans",
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 45,
        },
    }
    
    script_agent = ScriptGenerationAgent(fact_store=fact_store)
    
    script_with_rag = script_agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
    )
    
    print("\n   Generated script (WITH RAG):")
    print(f"   - Script ID: {script_with_rag.get('script_package_id')}")
    print(f"   - Facts used: {len(script_with_rag.get('fact_sources', []))}")
    print(f"   - Hook: {script_with_rag.get('hook_variants', [''])[0]}")
    
    script_obj = script_with_rag.get('script', {})
    beats = script_obj.get('beats', [])
    print(f"   - Beats: {len(beats)}")
    if beats:
        print(f"   - First beat VO: {beats[0].get('vo_line', 'N/A')[:60]}...")
    
    # Step 5: Generate script WITHOUT RAG for comparison
    print("\n[5] Generating script WITHOUT RAG (for comparison)...")
    
    script_without_rag = script_agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=False,  # Disable RAG
    )
    
    print("\n   Generated script (WITHOUT RAG):")
    print(f"   - Script ID: {script_without_rag.get('script_package_id')}")
    print(f"   - Facts used: {len(script_without_rag.get('fact_sources', []))}")
    print(f"   - Hook: {script_without_rag.get('hook_variants', [''])[0]}")
    
    # Step 6: Save outputs
    print("\n[6] Saving outputs...")
    
    output_dir = Path(__file__).parent.parent / "results" / "fact_mining_demo"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save mining results
    with open(output_dir / "mining_results.json", "w") as f:
        json.dump(mining_results, f, indent=2)
    
    # Save scripts
    with open(output_dir / "script_with_rag.json", "w") as f:
        json.dump(script_with_rag, f, indent=2)
    
    with open(output_dir / "script_without_rag.json", "w") as f:
        json.dump(script_without_rag, f, indent=2)
    
    print(f"   Saved to: {output_dir}")
    
    # Step 7: Show statistics
    print("\n[7] Final Statistics:")
    final_stats = fact_store.get_stats(topic_id=topic_id)
    print(f"   Total facts in database (all topics): {fact_store.get_stats()['total_facts']}")
    print(f"   Facts for '{topic_id}': {final_stats['total_facts']}")
    print(f"   Verified facts: {final_stats['verified_count']}")
    print(f"   Avg engagement score: {final_stats['avg_engagement_score']:.2f}/10")
    
    print("\n" + "=" * 80)
    print("DEMO COMPLETE!")
    print("=" * 80)
    print("\nKey Takeaways:")
    print("✓ Facts are now stored in: results/facts.db")
    print("✓ Scripts can be grounded in verified facts via RAG")
    print("✓ Script quality improves with fact grounding")
    print("\nNext Steps:")
    print("- Mine more topics to build your fact database")
    print("- Integrate external sources (Wikipedia) for verification")
    print("- Add fact verification workflow")
    print("- Build script verifier to catch hallucinations")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
