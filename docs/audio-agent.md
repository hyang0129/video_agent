# Audio Generation Agent

The Audio Generation Agent converts video plans into audio timelines with AI-generated voiceovers using ElevenLabs TTS.

## Overview

Part of the multi-agent video production pipeline, the Audio Agent:
- ✅ Generates voiceover audio from script text (Phase 1)
- ✅ Creates structured audio timeline manifests
- ✅ Manages multiple voice presets
- 🔜 Mixes audio tracks with background music (Phase 2)
- 🔜 Applies normalization and effects (Phase 2)

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install elevenlabs>=0.2.0

# Set up environment variable
export ELEVENLABS_API_KEY="your_api_key_here"
```

### Basic Usage

```python
from pathlib import Path
from src.audio_agent import create_audio_agent

# Create agent
agent = create_audio_agent(
    output_dir=Path("results/my_video"),
    voice="narrator",  # or "energetic", "calm", "authoritative"
    music_volume_db=-18.0
)

# Generate audio from video plan
audio_timeline = agent.generate_audio_timeline(video_plan)

# Get statistics
stats = agent.get_audio_stats(audio_timeline)
print(f"Generated {stats['voiceover_tracks']} tracks")
print(f"Total duration: {stats['total_duration_s']}s")
```

### Run Example

```bash
python examples/audio_agent_example.py
```

## Voice Presets

| Preset | Voice Name | Characteristics | Best For |
|--------|-----------|-----------------|----------|
| `narrator` | Rachel | Clear, professional | Educational content, documentaries |
| `energetic` | Adam | Dynamic, enthusiastic | Action content, exciting topics |
| `calm` | Bella | Soothing, gentle | Relaxing content, meditation |
| `authoritative` | Arnold | Deep, commanding | Serious topics, announcements |

Custom voice IDs from ElevenLabs can also be used directly.

## Input/Output Contracts

### Input: VideoPlan

```json
{
  "schema_version": "1.0.0",
  "video_plan_id": "vp_...",
  "audio": {
    "tts": {
      "enabled": true,
      "voice": "narrator"
    }
  },
  "scenes": [
    {
      "scene_id": "scene_01",
      "t_start_s": 0.0,
      "t_end_s": 6.5,
      "vo_line": "Your voiceover text here",
      "on_screen_text": "Text overlay"
    }
  ]
}
```

### Output: AudioTimeline

```json
{
  "schema_version": "1.0.0",
  "audio_timeline_id": "at_a1b2c3d4",
  "video_plan_ref": "vp_...",
  "audio_file_path": null,
  "duration_seconds": 45.0,
  "voice_id": "21m00Tcm4TlvDq8ikWAM",
  "tracks": [
    {
      "type": "voiceover",
      "file": "audio_segments/vo_scene_01.mp3",
      "scene_id": "scene_01",
      "t_start_s": 0.0,
      "t_end_s": 6.5,
      "volume_db": 0,
      "metadata": {
        "character_count": 85,
        "estimated_duration_s": 6.43
      }
    }
  ]
}
```

## API Reference

### AudioGenerationAgent

Main agent class for audio generation.

#### Methods

##### `generate_audio_timeline(video_plan: Dict) -> Dict`

Generate complete audio timeline from video plan.

**Args:**
- `video_plan`: VideoPlan dictionary with scenes and voiceover lines

**Returns:**
- AudioTimeline dictionary with generated tracks

**Raises:**
- `AudioGenerationError`: If video plan is invalid or TTS fails

##### `get_audio_stats(audio_timeline: Dict) -> Dict`

Get statistics about generated audio.

**Returns:**
```python
{
    "total_duration_s": 45.0,
    "voiceover_tracks": 8,
    "music_tracks": 1,
    "total_characters": 450,
    "avg_chars_per_second": 10.0
}
```

### Factory Function

##### `create_audio_agent(output_dir, voice, music_volume_db) -> AudioGenerationAgent`

Create configured audio agent instance.

**Args:**
- `output_dir`: Directory for audio files
- `voice`: Voice preset or ElevenLabs voice ID
- `music_volume_db`: Background music volume (dB)

## Configuration

Edit `src/config.py` or set environment variables:

```python
# Audio Generation Settings
DEFAULT_VOICE = "narrator"
BACKGROUND_MUSIC_VOLUME_DB = -18.0
VOICEOVER_VOLUME_DB = 0.0
TARGET_LUFS = -16.0
TTS_STABILITY = 0.5  # 0.0-1.0, lower = more expressive
TTS_SIMILARITY_BOOST = 0.75  # 0.0-1.0, higher = closer to original
```

## Error Handling

The agent uses specific exceptions for clear error messages:

```python
from src.audio_agent import AudioGenerationError
from src.tools.tts_tools import TTSError

try:
    timeline = agent.generate_audio_timeline(video_plan)
except AudioGenerationError as e:
    print(f"Audio generation failed: {e}")
except TTSError as e:
    print(f"TTS API error: {e}")
```

## Testing

```bash
# Run unit tests
pytest tests/test_audio_agent.py -v

# Run integration tests (requires API key)
pytest tests/test_audio_agent.py -v -m integration
```

## File Structure

```
results/
  at_2026-02-01_topic_name_abc123/
    audio_timeline.json          # Timeline manifest
    audio_segments/              # Generated voiceover files
      vo_scene_01.mp3
      vo_scene_02.mp3
      ...
```

## Multi-Agent Best Practices

This agent follows established patterns:

1. **Clear Contracts**: Well-defined input (VideoPlan) and output (AudioTimeline)
2. **Deterministic**: Same input produces same output
3. **Separation of Concerns**: Delegates TTS to tools module
4. **Error Handling**: Custom exceptions with clear messages
5. **Type Safety**: Full type hints throughout
6. **Documentation**: Google-style docstrings
7. **Validation**: Input validation before processing
8. **Factory Pattern**: `create_audio_agent()` for instantiation
9. **Artifact Persistence**: All outputs saved as JSON + files
10. **Progress Tracking**: Statistics available via `get_audio_stats()`

## Phase 2 Roadmap

Planning is centralized in [ROADMAP.md](../ROADMAP.md).

Use this document for implementation details and contracts; use the roadmap for priorities and sequencing.

## Troubleshooting

### "ELEVENLABS_API_KEY not configured"

Set the API key in your `.env` file:
```bash
ELEVENLABS_API_KEY=your_key_here
```

### "Failed to generate voiceover"

- Check API key is valid
- Verify ElevenLabs account has quota remaining
- Ensure text is not empty
- Check network connectivity

### "Scene missing required field"

Ensure your VideoPlan includes all required fields:
- `t_start_s`
- `t_end_s`
- `vo_line`

## Examples

See `examples/audio_agent_example.py` for a complete working example.

## Related Documentation

- [Video Production Pipeline Architecture](../docs/video-production-pipeline-architecture.md)
- [Multi-Agent Workflow Best Practices](../docs/video-production-pipeline-architecture.md#multi-agent-workflow-best-practices)
- [API Keys and Services](../docs/api-keys-and-services.md)
