"""Star Wars Facts Pipeline - AUTO MODE (always mines fresh facts)"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from src.facts.fact_store import FactStore
from src.facts.fact_miner import FactMiner
from src.script_agent import ScriptGenerationAgent


def print_section(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


print_section("STAR WARS FACTS PIPELINE - AUTO MODE")

# Initialize
print("\n[INIT] Setting up fact store and miner...")
fact_store = FactStore()
fact_miner = FactMiner(fact_store=fact_store)

# Always mine fresh facts
print_section("STEP 1: MINING FACTS FROM YOUTUBE")
print("\nSearching for top Star Wars fact videos...")
print("This will download captions and extract facts using LLM")
print("Estimated time: 2-4 minutes...\n")

mining_results = fact_miner.mine_top_videos(
    topic_query="star wars facts explained trivia",
    topic_id="star_wars",
    subtopic_id="facts",
    max_videos=3,  # Start with 3 videos
    use_captions=True,
)

print(f"\nMining complete!")
print(f"  Videos processed: {mining_results.get('videos_mined', 0)}")
print(f"  Facts extracted: {mining_results.get('total_facts', 0)}")

# Show sample facts
if mining_results.get('video_results'):
    print("\nSample extracted facts:")
    for video_result in mining_results['video_results'][:2]:
        if video_result.get('success') and video_result.get('facts'):
            print(f"\n  Video ID: {video_result['video_id']}")
            for fact in video_result['facts'][:3]:
                print(f"    - {fact['fact_text'][:80]}...")

# Query facts
print_section("STEP 2: QUERYING FACT DATABASE")

facts = fact_store.query(
    topic_id="star_wars",
    subtopic_id="facts",
    limit=10,
    min_engagement_score=1.0,
)

if not facts:
    facts = fact_store.query(topic_id="star_wars", limit=10)

print(f"\nRetrieved {len(facts)} facts for script generation")

if facts:
    print("\nTop 5 facts by engagement score:")
    for i, fact in enumerate(facts[:5], 1):
        print(f"\n  {i}. [Score: {fact['engagement_score']:.1f}/10]")
        print(f"     {fact['fact_text']}")

# Generate script
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
        "angle": "Surprising facts that even superfans don't know",
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

print("\nGenerating script with LLM and RAG...")

script_agent = ScriptGenerationAgent(fact_store=fact_store)
script_package = script_agent.generate_script_package(
    topic_brief=topic_brief,
    use_fact_grounding=True,
    min_facts=3,
    max_facts=8,
)

print("\nScript generated!")

# Display script
print_section("FINAL SCRIPT")

print(f"\nScript ID: {script_package['script_package_id']}")
print(f"Facts Used: {len(script_package.get('fact_sources', []))} facts")

# Hooks
print("\nHOOK OPTIONS:")
for i, hook in enumerate(script_package.get('hook_variants', []), 1):
    print(f"  {i}. {hook}")

# Beats
print("\nSCRIPT BEATS:")
script = script_package.get('script', {})
beats = script.get('beats', [])

for i, beat in enumerate(beats, 1):
    t_start = beat.get('t_start_s', 0)
    t_end = beat.get('t_end_s', 0)
    vo_line = beat.get('vo_line', '')
    on_screen = beat.get('on_screen_text', '')
    
    print(f"\n  Beat {i} [{t_start:.1f}s - {t_end:.1f}s]")
    print(f"  On-Screen: \"{on_screen}\"")
    print(f"  Voiceover: \"{vo_line}\"")

# Full voiceover
print("\nFULL VOICEOVER:")
print("-" * 80)
vo_text = script.get('voiceover', '')
if vo_text:
    words = vo_text.split()
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > 76:
            print(line)
            line = word
        else:
            line += (" " + word) if line else word
    if line:
        print(line)
print("-" * 80)

# Caption and hashtags
print(f"\nCAPTION: {script_package.get('caption', 'N/A')}")
print(f"HASHTAGS: {' '.join(script_package.get('hashtags', []))}")

# Save output
print_section("SAVING OUTPUT")

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_dir = Path(__file__).parent / "results" / f"star_wars_pipeline_{timestamp}"
output_dir.mkdir(parents=True, exist_ok=True)

# Save JSON
script_path = output_dir / "script_package.json"
with open(script_path, 'w', encoding='utf-8') as f:
    json.dump(script_package, f, indent=2, ensure_ascii=False)

# Save readable
readable_path = output_dir / "script_readable.txt"
with open(readable_path, 'w', encoding='utf-8') as f:
    f.write("STAR WARS FACTS - VERIFIED SCRIPT\n")
    f.write("=" * 80 + "\n\n")
    f.write(f"Script ID: {script_package['script_package_id']}\n")
    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"Facts Used: {len(script_package.get('fact_sources', []))}\n\n")
    
    f.write("HOOKS:\n")
    for i, hook in enumerate(script_package.get('hook_variants', []), 1):
        f.write(f"  {i}. {hook}\n")
    
    f.write("\n" + "=" * 80 + "\n")
    f.write("FULL VOICEOVER:\n")
    f.write("=" * 80 + "\n")
    f.write(vo_text + "\n\n")
    
    f.write("=" * 80 + "\n")
    f.write("BEAT-BY-BEAT:\n")
    f.write("=" * 80 + "\n\n")
    
    for i, beat in enumerate(beats, 1):
        f.write(f"Beat {i} [{beat.get('t_start_s', 0):.1f}s - {beat.get('t_end_s', 0):.1f}s]\n")
        f.write(f"  On-Screen: {beat.get('on_screen_text', '')}\n")
        f.write(f"  VO: {beat.get('vo_line', '')}\n\n")
    
    f.write("=" * 80 + "\n")
    f.write(f"Caption: {script_package.get('caption', '')}\n")
    f.write(f"Hashtags: {' '.join(script_package.get('hashtags', []))}\n")

print(f"\nScript saved to: {output_dir}")
print(f"  - JSON: script_package.json")
print(f"  - Readable: script_readable.txt")

print_section("PIPELINE COMPLETE!")
print("\nYour verified Star Wars script is ready for video production!")
print(f"\nOutput location: {output_dir}")
