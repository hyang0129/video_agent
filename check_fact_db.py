"""Quick script to check fact database contents."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.facts.fact_store import FactStore

store = FactStore()

# Get overall stats
stats = store.get_stats()
print(f"Total facts in database: {stats['total_facts']}")
print(f"Average engagement: {stats.get('avg_engagement_score', 0):.1f}/10")

# Get Star Wars stats
sw_stats = store.get_stats(topic_id='star_wars')
print(f"\nStar Wars facts: {sw_stats['total_facts']}")
if sw_stats['total_facts'] > 0:
    print(f"Avg Star Wars engagement: {sw_stats.get('avg_engagement_score', 0):.1f}/10")

# Show sample facts
facts = store.query(topic_id='star_wars', limit=5)
if facts:
    print(f"\nTop {len(facts)} Star Wars facts:")
    for i, fact in enumerate(facts, 1):
        print(f"\n{i}. [Score: {fact['engagement_score']:.1f}/10]")
        print(f"   {fact['fact_text'][:100]}...")
        print(f"   Sources: {len(fact['sources'])}")
else:
    print("\n⚠️  No Star Wars facts found in database")
    print("   Run 'python run_star_wars_auto.py' to mine facts")
