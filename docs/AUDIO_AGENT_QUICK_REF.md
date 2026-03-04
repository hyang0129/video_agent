# Audio Agent Quick Reference

## One-Liner Usage

```python
from src.audio_agent import create_audio_agent

agent = create_audio_agent(output_dir=Path("results/run_001"), voice="narrator")
audio_timeline = agent.generate_audio_timeline(video_plan)
```

## Voice Presets

| Name | Voice | Use Case |
|------|-------|----------|
| `narrator` | Rachel | Educational, documentaries |
| `energetic` | Adam | Action, exciting topics |
| `calm` | Bella | Relaxing, meditation |
| `authoritative` | Arnold | Serious topics |

## Input Schema

VideoPlan must have:
```python
{
    "scenes": [
        {
            "scene_id": "scene_01",
            "t_start_s": 0.0,
            "t_end_s": 6.5,
            "vo_line": "Your text here"
        }
    ]
}
```

## Output Schema

AudioTimeline returns:
```python
{
    "audio_timeline_id": "at_...",
    "duration_seconds": 45.0,
    "tracks": [
        {
            "type": "voiceover",
            "file": "audio_segments/vo_scene_01.mp3",
            "t_start_s": 0.0,
            "t_end_s": 6.5
        }
    ]
}
```

## Statistics

```python
stats = agent.get_audio_stats(audio_timeline)
# Returns: {
#     "voiceover_tracks": 8,
#     "total_duration_s": 45.0,
#     "total_characters": 450,
#     "avg_chars_per_second": 10.0
# }
```

## Error Handling

```python
from src.audio_agent import AudioGenerationError
from src.tools.tts_tools import TTSError

try:
    timeline = agent.generate_audio_timeline(video_plan)
except AudioGenerationError as e:
    print(f"Agent error: {e}")
except TTSError as e:
    print(f"TTS API error: {e}")
```

## Configuration

```python
# src/config.py or environment variables
DEFAULT_VOICE = "narrator"
BACKGROUND_MUSIC_VOLUME_DB = -18.0
TTS_STABILITY = 0.5  # 0.0-1.0
TTS_SIMILARITY_BOOST = 0.75  # 0.0-1.0
```

## File Output

```
results/at_<timestamp>/
├── audio_timeline.json
└── audio_segments/
    ├── vo_scene_01.mp3
    ├── vo_scene_02.mp3
    └── ...
```

## Common Issues

| Issue | Solution |
|-------|----------|
| "ELEVENLABS_API_KEY not configured" | Set in `.env` file |
| "Scene missing required field" | Ensure `t_start_s`, `t_end_s`, `vo_line` |
| "Failed to generate voiceover" | Check API quota and key validity |

## Testing

```bash
# Unit tests
pytest tests/test_audio_agent.py -v

# Integration test (requires API key)
pytest tests/test_audio_agent.py -v -m integration

# Run example
python examples/audio_agent_example.py
```

## Custom Voice IDs

```python
# Use ElevenLabs voice ID directly
agent = create_audio_agent(voice="your_custom_voice_id_here")

# Or get available voices
from src.tools.tts_tools import get_available_voices
voices = get_available_voices()
for v in voices:
    print(f"{v['name']}: {v['voice_id']}")
```

## Phase 2 Features (Coming Soon)

- Audio mixing with background music
- Loudness normalization
- Sound effects
- Master audio file export

## Full Documentation

- [Audio Agent Docs](audio-agent.md)
- [Architecture Docs](video-production-pipeline-architecture.md)
- [Implementation Summary](AUDIO_AGENT_IMPLEMENTATION.md)
