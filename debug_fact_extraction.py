"""Test fact extraction from a single video to debug issues."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.facts.fact_miner import FactMiner
from src.facts.fact_store import FactStore

print("=" * 80)
print("DEBUGGING FACT EXTRACTION")
print("=" * 80)

# Initialize
fact_store = FactStore()
miner = FactMiner(fact_store=fact_store)

# Test with a specific Star Wars video
video_id = "dQw4w9WgXcQ"  # A test video (Rick Astley as placeholder)
print(f"\nTesting with video: {video_id}")

# Try to get captions
print("\n[1] Fetching captions...")
captions = miner.youtube_client.get_video_captions(video_id)

if captions:
    print(f"✓ Got captions: {len(captions['text'])} characters")
    print(f"  Preview: {captions['text'][:200]}...")
    
    # Try to extract facts
    print("\n[2] Extracting facts with LLM...")
    facts = miner.extract_facts_from_text(captions['text'][:5000])  # Limit to first 5000 chars
    
    print(f"\n[3] Results:")
    print(f"  Facts extracted: {len(facts)}")
    
    if facts:
        print("\n  Sample facts:")
        for i, fact in enumerate(facts[:3], 1):
            print(f"    {i}. {fact['fact_text']}")
    else:
        print("  No facts extracted - check LLM output above")
else:
    print("✗ No captions available")
    print("  This video may not have captions or they may be disabled")

print("\n" + "=" * 80)
