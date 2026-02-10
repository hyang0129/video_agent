# Fact-Grounded Script Generation System

## Overview

The fact-grounded script generation system ensures that video scripts are based on **verified facts** rather than LLM hallucinations. This is achieved through:

1. **Fact Mining** - Extract facts from high-engagement YouTube videos
2. **Fact Storage** - SQLite database with engagement scoring
3. **RAG Integration** - Scripts query and use stored facts
4. **Future: Verification** - Cross-check scripts against external sources

---

## Architecture

```
┌─────────────────────────────────┐
│   YouTube Videos (Top Content)  │
│   - Video captions              │
│   - Video titles/descriptions   │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│   Fact Mining Pipeline          │
│   - Extract facts (LLM)         │
│   - Score by engagement         │
│   - Deduplicate                 │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│   Fact Store (SQLite)           │
│   - Indexed by topic/subtopic   │
│   - Engagement scoring          │
│   - Source tracking             │
└────────────┬────────────────────┘
             ↓
┌─────────────────────────────────┐
│   Script Generation (RAG)       │
│   - Query relevant facts        │
│   - Generate grounded scripts   │
│   - Track fact sources          │
└─────────────────────────────────┘
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install youtube-transcript-api
```

(Already included in requirements.txt)

### 2. Mine Facts for a Topic

```python
from src.facts.fact_miner import FactMiner
from src.facts.fact_store import FactStore

# Initialize
fact_store = FactStore()
fact_miner = FactMiner(fact_store)

# Mine facts from top videos
results = fact_miner.mine_top_videos(
    topic_query="star wars facts explained",
    topic_id="star_wars",
    subtopic_id="facts",
    max_videos=5,
    use_captions=True
)

print(f"Extracted {results['total_facts']} facts")
```

### 3. Generate RAG-Powered Scripts

```python
from src.script_agent import ScriptGenerationAgent

# Initialize agent with fact store
agent = ScriptGenerationAgent(fact_store=fact_store)

# Generate script with fact grounding
script = agent.generate_script_package(
    topic_brief={
        "topic_id": "star_wars",
        "subtopic_id": "facts",
        "format": {"target_duration_seconds": 45}
    },
    use_fact_grounding=True  # Enable RAG
)

# Check which facts were used
print(f"Facts used: {script['fact_sources']}")
```

### 4. Run Complete Example

```bash
python examples/fact_mining_example.py
```

---

## Components

### FactStore (`src/facts/fact_store.py`)

SQLite-backed storage for facts with query capabilities.

**Key Methods:**
- `add_fact()` - Store a new fact with sources and metadata
- `query()` - Retrieve facts by topic/subtopic with filters
- `search_by_keyword()` - Search facts by keywords
- `get_stats()` - Get database statistics
- `mark_verified()` - Mark fact as externally verified

**Schema:**
```python
{
    "fact_id": "fact_abc123",
    "topic_id": "star_wars",
    "subtopic_id": "facts",
    "fact_text": "Yoda's species remains unnamed in Star Wars canon",
    "sources": [
        {
            "type": "youtube_captions",
            "video_id": "xyz789",
            "video_url": "...",
            "title": "...",
            "views": 5000000
        }
    ],
    "engagement_score": 8.5,  # 0-10 based on source video engagement
    "verified": false,
    "keywords": ["yoda", "species", "canon"],
    "created_at": "2026-02-03T..."
}
```

### FactMiner (`src/facts/fact_miner.py`)

Extracts facts from YouTube videos using LLM.

**Key Methods:**
- `mine_video_captions()` - Extract facts from video captions
- `mine_video_titles()` - Extract fact hints from video titles
- `mine_top_videos()` - Complete mining workflow for top videos
- `extract_facts_from_text()` - LLM-based fact extraction

**Features:**
- Uses `youtube-transcript-api` (no quota cost)
- Engagement-based scoring
- Automatic deduplication
- Source attribution

### ScriptGenerationAgent (Updated)

Now supports RAG-powered script generation.

**New Parameters:**
- `use_fact_grounding` - Enable/disable RAG (default: True)
- `min_facts` - Minimum facts to retrieve (default: 5)
- `max_facts` - Maximum facts to retrieve (default: 10)

**Output Tracking:**
- `fact_sources` - List of fact IDs used in script

---

## Database Location

Facts are stored in: `results/facts.db`

To inspect:
```bash
sqlite3 results/facts.db
> SELECT COUNT(*) FROM facts;
> SELECT topic_id, COUNT(*) FROM facts GROUP BY topic_id;
```

---

## Fact Mining Best Practices

### 1. Caption Quality
- Captions work best for informational content
- Avoid music videos, short films (captions are sparse)
- Auto-generated captions may have errors but are usually good enough

### 2. Video Selection
- Target high-engagement videos (100K+ views)
- Use specific queries: "X facts explained" not just "X"
- Long-form content (8-15 min) has more facts than shorts

### 3. Engagement Scoring
```python
view_score = min(10, (views / 100000) * 5)
engagement_multiplier = min(2.0, (engagement_rate / 0.02) * 1.5)
final_score = min(10, view_score * engagement_multiplier)
```

### 4. Fact Extraction Prompt
The LLM extracts facts with:
- Confidence levels (high/medium/low)
- Keywords for search
- Cleaned, standalone statements

---

## Workflow Integration

### Market Research → Fact Mining → Script Generation

```python
# 1. Market Research identifies topic
from src.agent import MarketResearchAgent

mr_agent = MarketResearchAgent()
research = mr_agent.research_and_export("science fiction")

# 2. Mine facts for identified topics
fact_miner = FactMiner()
for opportunity in research['opportunities']:
    fact_miner.mine_top_videos(
        topic_query=opportunity['topic_query'],
        topic_id=opportunity['topic_id'],
        max_videos=5
    )

# 3. Generate grounded scripts
script_agent = ScriptGenerationAgent(fact_store=fact_store)
script = script_agent.generate_script_package(
    topic_brief=opportunity['topic_brief'],
    use_fact_grounding=True
)
```

---

## Future Enhancements

### Phase 2: External Verification
- Wikipedia API integration
- Fact cross-referencing
- Confidence scoring

### Phase 3: Script Verifier
- Extract claims from generated scripts
- Check against fact store
- Flag unsupported claims

### Phase 4: Vector Search
- Semantic fact search
- Similar fact detection
- Better deduplication

---

## Troubleshooting

### "No captions available"
- Video has captions disabled
- Try with different videos
- Fall back to title mining

### "Not enough facts found"
- Mine more videos for the topic
- Lower `min_engagement_score` in query
- Use broader topic_id (without subtopic)

### "Facts seem generic"
- Use more specific video queries
- Target expert channels (not viral compilations)
- Increase confidence threshold in extraction

---

## API Reference

See docstrings in:
- `src/facts/fact_store.py`
- `src/facts/fact_miner.py`
- `src/script_agent.py`

Run example:
```bash
python examples/fact_mining_example.py
```
