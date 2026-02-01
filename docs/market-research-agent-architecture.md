# Market Research Agent Architecture

## The Core Question: Agent vs Pipeline?

### What Makes This "Agent-Worthy"?

**Agent Characteristics Present:**
- Multi-step reasoning (discover → analyze → compare → score)
- Adaptive exploration (follows interesting patterns, abandons dead ends)
- Decision-making (which topics to pursue deeper, when to stop searching)
- Iterative refinement (adjusts search strategies based on findings)

**Simple Pipeline Characteristics:**
- Fixed sequence of operations
- No decision points
- Predictable outputs from given inputs
- No learning or adaptation

**Verdict:** This task benefits from agentic behavior, but not all components need to be agents.

## Hybrid Architecture Recommendation

### Orchestration Layer: Agent
The orchestrator should be an LLM-based agent because:
- It needs to interpret ambiguous results (is this topic truly "sci-fi" or "general science"?)
- It makes judgment calls (is this gap worth pursuing?)
- It adapts strategy (if YouTube rate limits, pivot to different data source)
- It synthesizes findings into actionable insights

### Execution Layer: Tools/APIs
The actual data collection should be deterministic tools:
- Faster execution
- Lower cost
- Predictable behavior
- Easier debugging

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│         Market Research Agent (LLM)              │
│  - Interprets requirements                       │
│  - Plans research strategy                       │
│  - Makes decisions on what to explore            │
│  - Synthesizes findings                          │
└─────────────────┬───────────────────────────────┘
                  │
                  │ Uses Tools
                  ▼
┌─────────────────────────────────────────────────┐
│              Tool Collection                     │
│                                                  │
│  ┌────────────────────────────────────────┐    │
│  │  YouTube Discovery Tool                 │    │
│  │  - Search videos by keyword             │    │
│  │  - Get channel statistics               │    │
│  │  - Fetch video metadata                 │    │
│  └────────────────────────────────────────┘    │
│                                                  │
│  ┌────────────────────────────────────────┐    │
│  │  Short-Form Content Scanner             │    │
│  │  - YouTube Shorts search                │    │
│  │  - TikTok hashtag analysis              │    │
│  │  - Instagram Reels discovery            │    │
│  └────────────────────────────────────────┘    │
│                                                  │
│  ┌────────────────────────────────────────┐    │
│  │  Trend Analysis Tool                    │    │
│  │  - Google Trends API                    │    │
│  │  - Historical view data                 │    │
│  │  - Seasonal pattern detection           │    │
│  └────────────────────────────────────────┘    │
│                                                  │
│  ┌────────────────────────────────────────┐    │
│  │  Database/Cache Layer                   │    │
│  │  - Store research results               │    │
│  │  - Cache API responses                  │    │
│  │  - Track analyzed topics                │    │
│  └────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

## Data Sources & APIs

### Primary: YouTube Data API v3

**What It Provides:**
- Video search by keyword
- Video statistics (views, likes, comments)
- Channel information (subscriber count, video count)
- Related videos
- Video categories and tags

**Limitations:**
- Daily quota limits (10,000 units by default)
- Each search = 100 units
- Video details = 1 unit per video
- **Strategy:** Cache aggressively, batch requests

**API Key Required:** Yes (free tier available)

### YouTube Shorts Detection

**Challenge:** No official "Shorts" API endpoint

**Solutions:**
1. **Duration Filter:** Videos < 60 seconds
2. **URL Pattern:** Contains `/shorts/` in URL
3. **Aspect Ratio:** Vertical videos (9:16)

**Implementation:** 
- Use regular YouTube API with duration filter
- Secondary verification using video details

### TikTok Data

**Official API:**
- TikTok Research API (requires approval, mainly for researchers)
- TikTok Business API (for advertisers)

**Challenges:**
- Restrictive access
- Limited data for non-business accounts

**Alternative Approaches:**
1. **Web Scraping** (use with caution)
   - Libraries: playwright, puppeteer
   - Risks: Rate limiting, IP blocking, TOS violations
   
2. **Third-Party APIs**
   - RapidAPI TikTok endpoints
   - Apify TikTok scrapers
   - Cost: Paid services

3. **Manual Sampling**
   - Human-in-the-loop verification
   - Spot checks on high-priority topics

### Instagram Reels

**Official API:**
- Instagram Graph API (requires business/creator account)
- Limited to your own content primarily

**Reality:** Difficult to get comprehensive market data

**Alternative:**
- Focus on YouTube Shorts as primary short-form indicator
- Use Instagram as secondary validation
- Manual competitive analysis for key topics

### Google Trends

**API:** Google Trends Unofficial API (pytrends)

**What It Provides:**
- Search interest over time
- Related queries
- Geographic breakdown
- Rising vs declining trends

**Use Cases:**
- Validate topic demand
- Identify trending sub-topics
- Seasonal pattern detection
- Geographic targeting opportunities

**Limitations:**
- Unofficial (could break)
- Rate limiting
- Relative data (not absolute numbers)

## Agent Orchestration Flow

### Phase 1: Topic Discovery (Agent-Driven)

```
Agent Prompt:
"Find informative long-form content channels with high engagement 
in the [category] space. Focus on 'Did You Know', 'Top X', and 
explanatory content."

Agent Actions:
1. Generates search queries (tool call: youtube_search)
2. Reviews results, identifies patterns
3. Decides which channels to investigate deeper
4. Extracts topic themes from successful content
5. Categorizes topics hierarchically
```

**Why Agent?** The agent can recognize patterns that simple rules might miss (e.g., "This channel says 'movie facts' but it's really sci-fi focused").

### Phase 2: Gap Analysis (Hybrid)

```
Agent Workflow:
1. Takes topics from Phase 1
2. For each topic:
   - Tool: Search long-form content (count, metrics)
   - Tool: Search short-form content (count, metrics)
   - Agent: Compares and interprets gap
   - Agent: Decides if gap is "opportunity" or "no demand"
3. Ranks opportunities
```

**Why Hybrid?** Data collection is deterministic, but interpretation requires judgment.

### Phase 3: Sub-Topic Expansion (Agent-Driven)

```
Agent Prompt:
"For the topic '[validated topic]', identify specific sub-topics 
that have proven engagement in long-form."

Agent Actions:
1. Analyzes video titles in topic area
2. Extracts recurring themes
3. Groups related content
4. Identifies sub-topic hierarchy
5. Validates each sub-topic has sufficient content
```

**Why Agent?** Natural language understanding needed to group "Star Wars trivia", "SW facts", "Star Wars secrets" as same sub-topic.

## Tool Specifications

### Tool 1: YouTube Search Tool

```python
def youtube_search(
    query: str,
    max_results: int = 50,
    order: str = "relevance",  # or "viewCount", "date"
    duration: str = "any",  # "short", "medium", "long"
    video_type: str = "any"  # "video", "channel"
) -> dict:
    """
    Returns:
    {
        "videos": [
            {
                "id": "video_id",
                "title": "...",
                "channel": "...",
                "views": 123456,
                "likes": 1234,
                "comments": 123,
                "published": "2024-01-15",
                "duration": "PT10M30S",
                "description": "...",
                "tags": [...]
            }
        ],
        "quota_used": 100
    }
    """
```

### Tool 2: Channel Analysis Tool

```python
def analyze_channel(
    channel_id: str,
    video_count: int = 50
) -> dict:
    """
    Returns:
    {
        "channel_id": "...",
        "name": "...",
        "subscribers": 500000,
        "total_views": 50000000,
        "video_count": 234,
        "recent_videos": [
            {
                "title": "...",
                "views": 123456,
                "engagement_rate": 0.045,
                "published": "..."
            }
        ],
        "topics": ["sci-fi", "space", "technology"],
        "avg_views": 213675,
        "view_trend": "growing"  # or "stable", "declining"
    }
    """
```

### Tool 3: Gap Analysis Tool

```python
def analyze_content_gap(
    topic: str,
    keywords: list[str]
) -> dict:
    """
    Returns:
    {
        "topic": "sci-fi facts",
        "long_form": {
            "total_videos": 1250,
            "total_views": 45000000,
            "top_channels": [...],
            "avg_engagement": 0.052
        },
        "short_form": {
            "total_videos": 87,
            "total_views": 2300000,
            "competition_level": "low"
        },
        "gap_score": 8.5,  # 0-10 scale
        "opportunity": "high",  # "high", "medium", "low"
        "reasons": [
            "High long-form demand (45M views)",
            "Low short-form supply (87 videos)",
            "Strong engagement rates"
        ]
    }
    """
```

### Tool 4: Trend Validator

```python
def validate_trend(
    topic: str,
    timeframe: str = "12m"
) -> dict:
    """
    Uses Google Trends to validate topic demand
    
    Returns:
    {
        "topic": "sci-fi facts",
        "trend": "rising",  # "rising", "stable", "declining"
        "interest_over_time": [...],
        "related_queries": [...],
        "seasonal_pattern": "none",  # or description
        "geographic_interest": {
            "US": 100,
            "UK": 75,
            ...
        }
    }
    """
```

## Implementation Strategy

### MVP Approach (Fastest to Value)

**Week 1: Manual + Simple Tools**
- Use YouTube Data API directly (no agent)
- Manual topic selection
- Spreadsheet for gap analysis
- Goal: Validate one profitable topic

**Week 2: Add Agent Layer**
- LangChain or similar framework
- Agent uses 2-3 tools
- Focus on topic discovery only
- Human review of all findings

**Week 3: Expand Coverage**
- Add short-form scanning
- Automated gap analysis
- Sub-topic expansion

**Week 4: Polish & Iterate**
- Caching layer
- Better scoring algorithms
- Feedback loop from content performance

### Technology Stack Recommendations

**Agent Framework:**
- **LangChain**: Mature, many integrations
- **CrewAI**: Multi-agent by design
- **Custom**: More control, less overhead

**APIs/Libraries:**
- `google-api-python-client`: YouTube Data API
- `pytrends`: Google Trends (unofficial)
- `playwright`: Web scraping (if needed)
- `requests-cache`: API response caching

**Storage:**
- **SQLite**: Simple, local, good for MVP
- **PostgreSQL**: If scaling up
- **JSON files**: Acceptable for prototyping

**Scheduling:**
- **Cron**: Simple, built-in
- **Celery**: If need complex workflows
- **GitHub Actions**: If want cloud-based

## Cost Considerations

### API Costs (Monthly)

**YouTube Data API:**
- Free tier: 10,000 quota units/day
- Estimated usage: 2,000-5,000 units/day (well within free tier)
- **Cost: $0**

**Google Trends:**
- Unofficial API: Free
- Rate limited but manageable
- **Cost: $0**

**LLM Costs (Agent):**
- OpenAI GPT-4: ~$0.01-0.03 per topic analyzed
- Claude: Similar pricing
- For 100 topics/month: ~$1-3
- **Cost: $1-3/month**

**Third-Party APIs (Optional):**
- TikTok scrapers: $20-50/month
- Instagram data: $30-100/month
- **Cost: $0-150/month** (depending on needs)

**Total Monthly Cost: $1-153**
- MVP (YouTube only): $1-3
- Full coverage: $51-153

## Recommendations

### Start Here:

1. **Build YouTube-focused agent first**
   - Free API access
   - Rich data available
   - Validates core hypothesis

2. **Use agent for interpretation, tools for data**
   - Agent decides what to search
   - Tools fetch data deterministically
   - Agent synthesizes findings

3. **Manual validation loop initially**
   - Agent suggests topics
   - Human approves before content creation
   - Iterate based on what works

4. **Add complexity gradually**
   - Start: YouTube long-form vs Shorts
   - Next: Add TikTok sampling
   - Later: Full multi-platform analysis

### Agent or Not?

**Yes, use an agent for:**
- Topic discovery (pattern recognition)
- Gap interpretation (judgment calls)
- Sub-topic categorization (semantic understanding)
- Strategy adaptation (learning from results)

**No, don't use an agent for:**
- Raw data fetching (use API tools)
- Metric calculations (use scripts)
- Data storage (use database)
- Scheduled execution (use cron/scheduler)

### Architecture Decision: **Agentic Orchestrator + Deterministic Tools**

This gives you:
- ✅ Intelligent decision-making where needed
- ✅ Reliable, fast data collection
- ✅ Debuggable components
- ✅ Cost-effective operation
- ✅ Incremental complexity
