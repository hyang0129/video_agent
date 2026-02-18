# Multi-Agent Pipeline Integration Guide

## Complete Pipeline Flow

This guide shows how to use all implemented agents together to go from market research to audio-ready video content.

## Pipeline Overview

```
Market Research → Script Generation → Video Planning → Audio Generation → [Visual → Compositor]
     ✅                 ✅                  ✅                 ✅              🔜       🔜
```

## Step-by-Step Integration

### Step 1: Market Research (TopicBrief)

```python
from src.agent import create_market_research_agent

# Initialize market research agent
mr_agent = create_market_research_agent()

# Research a category
result = mr_agent.research_category("science fiction")

# This generates: results/mr_<timestamp>_<topic>_<hash>/
#   - market_research_report.json
#   - topicbrief_topic_<topic>_sub_<subtopic>.json
```

**Output:** `TopicBrief` JSON

### Step 2: Script Generation (ScriptPackage)

```python
from pathlib import Path
import json
from src.script_agent import create_script_agent

# Load TopicBrief from previous step
topic_brief_path = Path("results/mr_<timestamp>/topicbrief_*.json")
with open(topic_brief_path) as f:
    topic_brief = json.load(f)

# Optional: Load creative spec
creative_spec_path = Path("creative_spec.example.json")
with open(creative_spec_path) as f:
    creative_spec = json.load(f)

# Initialize script agent
script_agent = create_script_agent()

# Generate script package
script_package = script_agent.generate_script(
    topic_brief=topic_brief,
    creative_spec=creative_spec
)

# This generates: results/sg_<timestamp>_<topic>_<hash>/
#   - script_package.json
```

**Output:** `ScriptPackage` JSON with voiceover lines and timing

### Step 3: Video Planning (VideoPlan)

```python
from src.video_agent import create_video_agent

# Initialize video planning agent
video_agent = create_video_agent()

# Create video plan from script
video_plan = video_agent.create_video_plan(
    script_package=script_package,
    creative_spec=creative_spec
)

# This generates: results/vp_<timestamp>_<topic>_<hash>/
#   - video_plan.json
```

**Output:** `VideoPlan` JSON with scene breakdown

### Step 4: Audio Generation (AudioTimeline)

```python
from src.audio_agent import create_audio_agent

# Create output directory for this run
output_dir = Path("results/at_<timestamp>_<topic>_<hash>")
output_dir.mkdir(parents=True, exist_ok=True)

# Initialize audio agent
audio_agent = create_audio_agent(
    output_dir=output_dir,
    voice="narrator",  # or "energetic", "calm", "authoritative"
    music_volume_db=-18.0
)

# Generate audio timeline
audio_timeline = audio_agent.generate_audio_timeline(video_plan)

# Get statistics
stats = audio_agent.get_audio_stats(audio_timeline)
print(f"✅ Generated {stats['voiceover_tracks']} voiceover tracks")
print(f"   Total duration: {stats['total_duration_s']}s")

# This generates: results/at_<timestamp>_<topic>_<hash>/
#   - audio_timeline.json
#   - audio_segments/
#       - vo_scene_01.mp3
#       - vo_scene_02.mp3
#       - ...
```

**Output:** `AudioTimeline` JSON + MP3 voiceover segments

### Step 5: Visual Generation (Phase 2)

```python
# 🔜 Coming in Phase 2
from src.visual_agent import create_visual_agent

visual_agent = create_visual_agent(output_dir=output_dir)
visual_manifest = visual_agent.generate_visual_assets(video_plan)
```

### Step 6: Video Composition (Phase 2)

```python
# 🔜 Coming in Phase 2
from src.compositor_agent import create_compositor_agent

compositor = create_compositor_agent(output_dir=output_dir)
final_video = compositor.compose_video(
    audio_timeline=audio_timeline,
    visual_manifest=visual_manifest
)
```

## Complete Pipeline Script

```python
"""Complete multi-agent pipeline execution."""

from pathlib import Path
import json
from datetime import datetime

from src.agent import create_market_research_agent
from src.script_agent import create_script_agent
from src.video_agent import create_video_agent
from src.audio_agent import create_audio_agent


def run_complete_pipeline(category: str, creative_spec_path: str = None):
    """Run complete pipeline from research to audio generation."""
    
    print("=" * 60)
    print("Multi-Agent Content Creation Pipeline")
    print("=" * 60)
    
    # Step 1: Market Research
    print("\n[1/4] Running market research...")
    mr_agent = create_market_research_agent()
    research_result = mr_agent.research_category(category)
    
    # Find generated TopicBrief
    # (In production, you'd parse research_result for the path)
    topic_brief_path = Path("results") / "latest_topicbrief.json"
    with open(topic_brief_path) as f:
        topic_brief = json.load(f)
    
    print(f"✅ Topic: {topic_brief.get('topic_name')}")
    
    # Step 2: Script Generation
    print("\n[2/4] Generating script...")
    creative_spec = None
    if creative_spec_path:
        with open(creative_spec_path) as f:
            creative_spec = json.load(f)
    
    script_agent = create_script_agent()
    script_package = script_agent.generate_script(
        topic_brief=topic_brief,
        creative_spec=creative_spec
    )
    
    print(f"✅ Script ID: {script_package.get('script_package_id')}")
    print(f"   Beats: {len(script_package['script']['beats'])}")
    
    # Step 3: Video Planning
    print("\n[3/4] Creating video plan...")
    video_agent = create_video_agent()
    video_plan = video_agent.create_video_plan(
        script_package=script_package,
        creative_spec=creative_spec
    )
    
    print(f"✅ Scenes: {len(video_plan['scenes'])}")
    
    # Step 4: Audio Generation
    print("\n[4/4] Generating audio...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("results") / f"pipeline_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    audio_agent = create_audio_agent(
        output_dir=output_dir,
        voice="narrator"
    )
    audio_timeline = audio_agent.generate_audio_timeline(video_plan)
    
    stats = audio_agent.get_audio_stats(audio_timeline)
    print(f"✅ Audio tracks: {stats['voiceover_tracks']}")
    print(f"   Duration: {stats['total_duration_s']}s")
    
    # Summary
    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print("=" * 60)
    print(f"\n📁 Output: {output_dir}")
    print(f"   - audio_timeline.json")
    print(f"   - audio_segments/ ({stats['voiceover_tracks']} files)")
    
    return {
        "topic_brief": topic_brief,
        "script_package": script_package,
        "video_plan": video_plan,
        "audio_timeline": audio_timeline,
        "output_dir": output_dir,
    }


if __name__ == "__main__":
    import sys
    
    category = sys.argv[1] if len(sys.argv) > 1 else "science fiction"
    creative_spec = sys.argv[2] if len(sys.argv) > 2 else None
    
    result = run_complete_pipeline(category, creative_spec)
    print(f"\n✨ All artifacts saved to: {result['output_dir']}")
```

## Agent Communication Contracts

Each agent has a clear input/output contract:

| Agent | Input | Output |
|-------|-------|--------|
| Market Research | Category string | TopicBrief JSON |
| Script Generation | TopicBrief JSON | ScriptPackage JSON |
| Video Planning | ScriptPackage JSON | VideoPlan JSON |
| Audio Generation | VideoPlan JSON | AudioTimeline JSON + MP3s |
| Visual (Phase 2) | VideoPlan JSON | VisualManifest JSON + assets |
| Compositor (Phase 2) | AudioTimeline + VisualManifest | Final Video MP4 |

## Data Flow

```
Category String
    ↓ [Market Research Agent]
TopicBrief.json
    ↓ [Script Generation Agent]
ScriptPackage.json
    ↓ [Video Planning Agent]
VideoPlan.json
    ↓ [Audio Generation Agent]
AudioTimeline.json + MP3 segments
    ↓ [Visual Agent - Phase 2]
VisualManifest.json + images/videos
    ↓ [Compositor Agent - Phase 2]
Final Video (MP4)
```

## Error Handling Strategy

```python
from src.agent import MarketResearchError
from src.script_agent import ScriptGenerationError
from src.audio_agent import AudioGenerationError
from src.tools.tts_tools import TTSError

try:
    # Run pipeline
    result = run_complete_pipeline("science fiction")
    
except MarketResearchError as e:
    print(f"❌ Market research failed: {e}")
    # Handle: retry with different category
    
except ScriptGenerationError as e:
    print(f"❌ Script generation failed: {e}")
    # Handle: adjust creative spec, retry
    
except AudioGenerationError as e:
    print(f"❌ Audio generation failed: {e}")
    # Handle: check API keys, retry with different voice
    
except TTSError as e:
    print(f"❌ TTS API error: {e}")
    # Handle: check quota, wait and retry
```

## Configuration for Pipeline

```python
# src/config.py
# All agents read from centralized config

# Market Research
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
MIN_VIEWS_LONGFORM = 100000

# Script Generation  
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = "gemini-flash-latest"

# Audio Generation
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
DEFAULT_VOICE = "narrator"
BACKGROUND_MUSIC_VOLUME_DB = -18.0
```

## Directory Structure

```
results/
├── mr_2026-02-01_science_fiction_abc123/
│   ├── market_research_report.json
│   └── topicbrief_topic_science_fiction_sub_time_travel.json
│
├── sg_2026-02-01_topic_science_fiction_def456/
│   └── script_package.json
│
├── vp_2026-02-01_topic_science_fiction_ghi789/
│   └── video_plan.json
│
└── at_2026-02-01_topic_science_fiction_jkl012/
    ├── audio_timeline.json
    └── audio_segments/
        ├── vo_scene_01.mp3
        ├── vo_scene_02.mp3
        └── ...
```

## Best Practices

### 1. Save Intermediate Artifacts
Always save outputs from each stage - enables debugging and rerunning from any point.

### 2. Use Consistent IDs
Each artifact includes references to its input:
- `script_package.topic_id` → links to TopicBrief
- `audio_timeline.video_plan_ref` → links to VideoPlan

### 3. Validate Between Stages
Each agent validates its input before processing.

### 4. Handle Errors Gracefully
Use specific exceptions and provide context.

### 5. Track Progress
Use statistics methods to monitor processing.

## Performance Optimization

### Parallel Execution (Future)
When Orchestrator is implemented:
```python
# Audio and Visual agents can run in parallel
import asyncio

async def generate_assets(video_plan):
    audio_task = asyncio.create_task(audio_agent.generate_async(video_plan))
    visual_task = asyncio.create_task(visual_agent.generate_async(video_plan))
    
    audio_timeline, visual_manifest = await asyncio.gather(
        audio_task, 
        visual_task
    )
    return audio_timeline, visual_manifest
```

### Caching
- Market Research: Cache YouTube API results
- Script Generation: Cache LLM responses for same input
- Audio Generation: Cache TTS outputs per voice+text combo

## Testing Pipeline Integration

```bash
# Test each stage independently
pytest tests/test_agent.py -v
pytest tests/test_script_agent.py -v
pytest tests/test_video_agent.py -v
pytest tests/test_audio_agent.py -v

# Test full integration (requires all API keys)
pytest tests/test_pipeline_integration.py -v -m integration
```

## Next Steps

Roadmap and prioritization are consolidated in [ROADMAP.md](../ROADMAP.md).

Use this guide for integration flow and contracts; use the roadmap for what to build next and in what order.

## Related Documentation

- [Market Research Architecture](market-research-agent-architecture.md)
- [Video Production Pipeline](video-production-pipeline-architecture.md)
- [Audio Agent Documentation](audio-agent.md)
- [Multi-Agent Best Practices](video-production-pipeline-architecture.md#multi-agent-workflow-best-practices)
