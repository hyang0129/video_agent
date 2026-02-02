# Vibe Insta - AI-Powered Social Media Content Pipeline

## Overview

An intelligent content creation pipeline that identifies market opportunities and generates engaging short-form social media content.

This repository contains the design, development, and deployment assets for a multi-agent system that:
- **Identifies content opportunities** through market research
- Generates, evaluates, and optimizes short-form video content
- Targets **YouTube Shorts**, TikTok, and Instagram Reels

The system uses specialized agents that collaborate to:
- Research topics and identify gaps in short-form content
- Ideate and script parameterized content
- Render and package videos
- Evaluate outputs against quantitative and qualitative metrics

## Project Structure

```
video_agent/
├── src/
│   ├── agent.py                 # Market research agent
│   ├── script_agent.py          # Script generation agent
│   ├── video_planner.py         # Video planning utilities
│   ├── video_agent.py           # Video planning agent wrapper
│   ├── audio_agent.py           # ✨ Audio generation agent
│   ├── config.py                # Configuration management
│   ├── creative_spec.py         # Creative specifications
│   ├── tools/
│   │   ├── youtube_tools.py     # YouTube API integration
│   │   └── tts_tools.py         # ✨ Text-to-speech tools (ElevenLabs)
│   ├── artifacts/
│   │   └── io.py                # Artifact I/O utilities
│   └── utils/
│       └── json_utils.py        # JSON parsing utilities
├── docs/
│   ├── content-type-targeting.md
│   ├── topic-identification.md
│   ├── market-research-agent-architecture.md
│   ├── video-production-pipeline-architecture.md
│   └── audio-agent.md           # ✨ Audio agent documentation
├── examples/
│   └── audio_agent_example.py   # ✨ Audio agent usage example
├── tests/
│   └── test_audio_agent.py      # ✨ Audio agent tests
├── results/                     # Output directory for artifacts
├── assets/                      # Static assets (music, etc.)
├── main.py                      # Entry point for market research
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
└── README.md                    # This file
```

## Current Implementation Status

### ✅ Implemented Agents

#### 1. Market Research Agent 🔍
Identifies content opportunities through YouTube analysis.

**Capabilities:**
- Search and analyze YouTube videos by topic
- Compare long-form vs short-form presence
- Score opportunities (0-10 scale)
- Identify specific sub-topics for content creation
- Multi-category scanning for best opportunities

**Output:** TopicBrief JSON for downstream agents

#### 2. Script Generation Agent ✍️
Converts topic briefs into structured video scripts.

**Capabilities:**
- Generate engaging hooks and captions
- Create beat-by-beat script timing
- On-screen text suggestions
- Safety notes and fact-checking flags

**Output:** ScriptPackage JSON with voiceover and timing

#### 3. Video Planning Agent 📋
Transforms scripts into actionable video plans.

**Capabilities:**
- Convert script beats to video scenes
- Define visual direction per scene
- Configure TTS and subtitle settings
- Generate asset prompts

**Output:** VideoPlan JSON for production agents

#### 4. Audio Generation Agent 🎙️
Generates voiceover audio using AI TTS.

**Capabilities:**
- ElevenLabs TTS integration with multiple voices
- Scene-by-scene voiceover generation
- Audio timeline manifest creation
- Voice preset management (narrator, energetic, calm, authoritative)
- Voiceover statistics and validation

**Output:** AudioTimeline JSON + MP3 voiceover segments

**Phase 2 Roadmap:**
- Audio mixing with background music
- Loudness normalization (LUFS)
- Sound effects support
- Master audio file export

[📖 Audio Agent Documentation](docs/audio-agent.md)

### 🔜 Planned Agents

#### 5. Visual Agent (Phase 2)
- Stock image/video search
- AI image generation
- Text overlay creation
- Visual coherence management

#### 6. Compositor Agent (Phase 2)
- Final video assembly
- Transition effects
- Text rendering
- Video export (MP4)

## Setup

### 1. Prerequisites

- Python 3.8+
- YouTube Data API key
- Google AI Studio API key (FREE!)

### 2. Installation

```powershell
# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure API Keys

```powershell
# Copy example environment file
copy .env.example .env

# Edit .env and add your API keys
```

Get your API keys:
- **YouTube Data API**: https://console.cloud.google.com/apis/credentials
  1. Create a new project
  2. Enable YouTube Data API v3
  3. Create credentials (API Key)
  
- **Google AI Studio**: https://aistudio.google.com/app/apikey
  1. Sign in with Google account
  2. Click "Get API key" or "Create API key"
  3. No credit card required!
  4. Free tier: 15 requests/min, 1M tokens/day

- **ElevenLabs TTS** (for audio generation): https://elevenlabs.io
  1. Sign up for free account
  2. Navigate to Profile → API Keys
  3. Create new API key
  4. Free tier: 10,000 characters/month

### 4. Verify Setup

```powershell
python main.py
```

Should show usage instructions if setup is correct.

## Usage

### Quick Start Examples

#### Example 1: Research a Category
```powershell
python main.py example1
```
Exports structured market research artifacts (JSON) to `results/<run_id>/`.

#### Example 2: Analyze Specific Topic
```powershell
python main.py example2
```
Deep dive into "sci-fi movie facts" with sub-topic recommendations.

#### Example 3: Multi-Category Scan
```powershell
python main.py example3
```
Scans multiple categories (sci-fi, history, space, true crime) for best opportunities.

#### Interactive Mode
```powershell
python main.py interactive
```
Chat with the agent for custom research queries.

### Cross-Agent Artifact Outputs

The market research stage can export downstream-ready artifacts:
- `market_research_report.json`
- `topicbrief_*.json`

These live under a run folder like `results/mr_2026-01-31_science_fiction_<id>/`.

See [docs/market-research-handoff-artifacts.md](docs/market-research-handoff-artifacts.md) for the handoff contract.

### Script Generation

Generate a script from a TopicBrief JSON:

```powershell
python main.py script results/<mr_run_id>/topicbrief_....json
```

Optionally pass a CreativeSpec JSON (channel-level defaults):

```powershell
python main.py script results/<mr_run_id>/topicbrief_....json creative_spec.json
```

A template is provided at `creative_spec.example.json`.

### Video Planning (Script → Video)

Create a deterministic `VideoPlan` from a ScriptPackage:

```powershell
python main.py videoplan results/<sg_run_id>/script_package.json creative_spec.json
```

This intentionally does not render video yet; it produces a renderer-agnostic plan suitable for a future Video Generation stage.

### Programmatic Usage

```python
from src.agent import create_agent

# Create agent
agent = create_agent()

# Research a category
result = agent.research_category("ancient history")
print(result)

# Analyze specific topic
result = agent.analyze_topic("Roman Empire facts")
print(result)

# Find opportunities across categories
categories = ["science", "history", "technology"]
result = agent.find_opportunities(categories, min_score=6.0)
print(result)

# Custom query
result = agent.chat("What are trending topics in space exploration?")
print(result)
```

## How It Works

### Market Research Pipeline

1. **Topic Discovery**
   - Agent searches for popular long-form content
   - Identifies patterns in successful videos
   - Extracts topic themes and categories

2. **Gap Analysis**
   - Compares long-form content presence (views, engagement)
   - Assesses short-form content competition
   - Calculates opportunity scores (0-10)

3. **Opportunity Scoring**
   - **Demand Score** (50% weight): Based on long-form views
   - **Gap Score** (30% weight): Based on short-form competition
   - **Engagement Score** (20% weight): Based on like/view ratio

4. **Sub-Topic Mapping**
   - Breaks down high-opportunity topics
   - Identifies specific content angles
   - Prioritizes by production feasibility

### Scoring System

**Opportunity Score: 0-10**
- 🟢 **7.0+**: High opportunity - Strong demand, low competition
- 🟡 **5.0-6.9**: Medium opportunity - Worth exploring sub-topics
- 🔴 **<5.0**: Low opportunity - High competition or low demand

## API Usage & Costs

### YouTube Data API
- **Free Tier**: 10,000 quota units/day
- **Search**: 100 units
- **Video Details**: 1 unit
- **Typical Usage**: 2,000-5,000 units/day

### Google AI Studio (Gemini)
- **Free Tier**: 15 requests/minute, 1M tokens/day
- **Model**: Gemini 1.5 Flash (or Pro)
- **Cost per Request**: $0 (completely free!)
- **Monthly Estimate**: $0 for typical usage

**Total Monthly Cost: $0** ✅ (both APIs free tier)

## Configuration

Edit `src/config.py` to customize:

```python
# Content thresholds
MIN_VIEWS_LONGFORM = 100000      # Minimum views for viability
MIN_ENGAGEMENT_RATE = 0.02       # 2% minimum engagement
SHORT_FORM_DURATION = 60         # Seconds

# Scoring weights
SCORING_WEIGHTS = {
    "longform_demand": 0.4,
    "shortform_gap": 0.3,
    "engagement": 0.2,
    "trend": 0.1,
}
```

## Tools & Technologies

- **LangChain**: Agent orchestration framework
- **Google Gemini 1.5**: LLM for decision-making and analysis (FREE!)
- **YouTube Data API v3**: Video and channel data
- **Requests-Cache**: API response caching
- **Pandas**: Data processing

## Project Roadmap

- [x] Market research agent with YouTube API
- [ ] Video script generation agent
- [ ] Fact checking agent (make sure script is consistent with reality)
- [ ] Video script generation agent
- [ ] Content scheduling system
- [ ] Multi-platform publishing (TikTok, Instagram Reels)
- [ ] Performance tracking and feedback loop
- [ ] Automated A/B testing

## Documentation

See `docs/` folder for detailed documentation:
- [Content Type Targeting](docs/content-type-targeting.md)
- [Topic Identification](docs/topic-identification.md)
- [Market Research Architecture](docs/market-research-agent-architecture.md)

## Troubleshooting

**Issue: YouTube API quota exceeded**
- Solution: Enable caching in `.env` (`ENABLE_CACHE=true`)
- Wait 24 hours for quota reset
- Consider using fewer max_results in searches

**Issue: No short-form content found**
- This is actually good! It indicates a content gap opportunity
- Verify with manual YouTube Shorts search

**Issue: Google AI Studio API errors**
- Check API key is valid at https://aistudio.google.com/app/apikey
- Verify you haven't exceeded rate limits (15 req/min)
- Try using gemini-1.5-flash instead of gemini-1.5-pro
- Check you're within free tier limits

## Contributing

This is a personal project, but suggestions are welcome!

## License

MIT License

---

**Note**: Always comply with YouTube's Terms of Service and API usage policies.
- Enforce strict, configurable content guidelines
- Manage publishing workflows and integrate with YouTube's platform and analytics

**Platform Focus**: YouTube-first strategy leverages YouTube's mature analytics, monetization opportunities, and algorithmic promotion of Shorts content.

## Initial Content Target

**Primary Format**: Faceless caption-first shorts with voiceover narration

This format is optimized for rapid iteration, low production cost, and effective hook testing:
- **Voiceover narration**: Generated TTS with consistent voice personality
- **On-screen captions**: Large, readable text synced to narration for accessibility and engagement
- **Visual assets**: Background loops or themed still images (minimal visual complexity)
- **Duration**: 15-60 second shorts optimized for YouTube Shorts (vertical 9:16 format)
- **YouTube optimization**: Titles, descriptions, tags, and thumbnails designed for YouTube's recommendation algorithm

**Rationale**: 
- Fastest feedback loop for learning what hooks and topics resonate
- Lowest production cost per video enables high-volume testing
- Easy to maintain quality standards with templated visual approach
- Strong accessibility (captions enable sound-off viewing)
- No face/identity required allows brand-agnostic scaling
- **YouTube advantages**: Rich analytics, monetization eligibility, Shorts Fund opportunities, subscriber conversion

**Future Expansion**:
- **Stock video b-roll**: Semantic shot matching with beat-aligned stock footage for higher production value
- **AI-generated visuals**: Custom scene generation to match narrative beats and create unique visual styles
- **Advanced motion graphics**: Data visualizations, kinetic typography, animated explainers

## High-Level Objectives

- **Automation-first**: Minimize human-in-the-loop effort for routine content creation while preserving control over strategy and safety.
- **Policy-aware**: Encode enforceable content guidelines to limit disallowed topics and style, aligned with YouTube's Community Guidelines and monetization policies.
- **Data-driven optimization**: Continuously improve generation quality and performance using YouTube Analytics (views, watch time, CTR, audience retention).
- **Modular architecture**: Separate agents and services for generation, evaluation, optimization, and YouTube platform integration.
- **YouTube-native**: Full integration with YouTube Data API for uploads, metadata management, and performance tracking.

## System Capabilities

### 1. Automated Parameterized Content Generation

Goal: Produce short-form video drafts end-to-end from structured parameters.

**Initial Focus (Caption-First Shorts)**:
- **Script generation agent**: Creates voiceover scripts optimized for 15-60s format with strong hooks
- **TTS synthesis**: Converts scripts to natural-sounding voiceover audio
- **Caption formatter**: Generates synced on-screen captions with timing and styling
- **Background asset manager**: Selects themed still images or background loops from approved libraries
- **Video compositor**: Assembles voiceover + captions + background into final video (9:16 aspect ratio)

Planned components for future expansion:
- **Stock footage agent**: Semantic search and beat alignment for b-roll clips
**Initial Focus**:
- **Hook strength evaluator**: Assesses first 2-3 seconds for attention-grabbing potential
- **Script clarity checker**: Ensures voiceover is understandable and well-paced
- **Caption readability validator**: Checks text size, contrast, and timing for mobile viewing
- **Audio quality checker**: Validates TTS pronunciation, pacing, and naturalness
- **Policy & safety checker**: Flags content that violates guidelines (see Section 4)
- **Platform-compatibility checker**: Ensures 9:16 format, duration, and file specs meet platform requirements

Planned for expansion:
- **Visual-audio sync evaluator**: Ensures b-roll/visuals match narrative beats
- **Retention predictor**: ML model trained on actual performance data to predict watch time
- **Engagement forecaster**: Predicts likely comments, shares, and saves based on historical patterns

Goal: Score and classify generated content to decide whether to publish, revise, or discard.

Planned components:
- **Quality evaluator**: Rates engagement potential (hook strength, clarity, pacing) using models and heuristic rules.
- **Policy & safety checker**: Flags or blocks content that violates guidelines (see Section 4).
- **Platform-compatibility checker**: Ensures formats, durations, and metadata match target platform requirements.

### 3. Optimization of the Generation Pipeline

Goal: Improve content performance and system efficiency over time.

**Initial Focus**:
- **YouTube Analytics ingestion**: Views, watch time, average view duration, traffic sources, audience retention graphs
- **A/B test tracking**: Compare performance of hook variations, title formulations, thumbnail designs
- **Parameter optimization**: Adjust script templates and generation parameters based on what performs best
- **Topic/niche discovery**: Identify which content themes drive highest engagement and subscriber conversion

Planned components for expansion:
- **Predictive modeling**: Train ML models on historical data to forecast performance pre-publication
- **Automated experiment design**: System-generated A/B tests for continuous improvement
- **Multi-variate optimization**: Simultaneously test hooks, visuals, CTAs, and pacing variations

### 4. Enforceable Content Guidelines

Goal: Enforce configurable rules that strictly limit the types and styles of content the system can produce.

**YouTube-Specific Considerations**:
- **Community Guidelines compliance**: No hate speech, harassment, dangerous content, misinformation
- **Monetization eligibility**: Advertiser-friendly content standards
- **Copyright protection**: No unauthorized music, footage, or copyrighted material
- **Age-appropriate content**: Suitable for all audiences or properly age-gated

Planned components:YouTube Integration

Goal: Manage content lifecycle and integrate seamlessly with YouTube.

**YouTube Data API Integration**:
- **Video uploads**: Automated upload of rendered Shorts with proper formatting
- **Metadata management**: Titles, descriptions, tags optimized for discovery and SEO
- **Thumbnail management**: Upload and set custom thumbnails
- **Playlist organization**: Categorize content into thematic playlists
- **Analytics retrieval**: Fetch detailed performance metrics for optimization loop
- **Comment management**: Monitor and respond to viewer feedback (future)

**Content Lifecycle Management**:
- **Content registry**: Track states (draft, scheduled, published, archived) with full metadata
- **Scheduling system**: Define posting cadence and optimal upload times
- **Approval workflows**: Human review gates for policy-sensitive content
- **Performance dashboard**: Unified view of content performance across all published Shortsed) and metadata.
- **YouTube integration**: Interface with the YouTube Data API for:
  - Uploading Shorts
  - Setting titles, descriptions, tags, and visibility
  - Managing thumbnails and playlists
  - Fetching performance metrics
- **Scheduling & workflows**: Define calendars, posting cadences, and approval flows.

## Repository Layout (Initial)

Planned structure (subject to change as the project evolves):

- `src/` – Core multi-agent logic, pipelines, and integrations
  -Development Roadmap

### Phase 1: MVP - Caption-First Shorts Pipeline
- [ ] Script generation with hook optimization
- [ ] TTS integration with voice consistency
- [ ] Caption synchronization and styling
- [ ] Background asset library and selection
- [ ] Basic video composition (VO + captions + background)
- [ ] Hook strength and policy evaluation
- [ ] YouTube Analytics API integration
- [ ] Performance data ingestion and analysis
- [ ] Parameter tuning based on engagement metrics
- [ ] Content guidelines refinement based on policy feedback
- [ ] Batch generation and scheduling workflows
- [ ] Automated title and description optimization
- [ ] A/B testing framework for hooks and templates
- [ ] Performance data ingestion from YouTube Analytics
- [ ] Parameter tuning based on engagement metrics
- [ ] Content guidelines refinement
- [ ] Batch generation and scheduling workflows

### Phase 3: Visual Enhancement
- [ ] Stock footage integration with semantic search
- [ ] Beat-aligned b-roll synchronization
- [ ] Advanced caption styling and motion effects
- [ ] Template variation system

### Phase 4: AI-Generated Visuals (Future)
- [ ] Custom image generation for scene matching
- [ ] AI video generation exploration
- [ ] Dynamic visual storytelling based on script

## Getting Started

*(Coming soon: installation, configuration, and usage instructions)*
- `scripts/` – Utility scripts (data ingestion, maintenance, analytics)
- `tests/` – Automated tests for agents and pipelines

## Next Steps

- Finalize detailed requirements for each agent and pipeline stage.
- Choose core libraries/frameworks for orchestration and API integration.
- Implement minimal end-to-end prototype: parameterized script → simple video → evaluation → mock upload.

This README will be expanded as the architecture and implementation mature.