# Video Production Pipeline Architecture

## Overview
The video production pipeline transforms market research into finished short-form videos through a multi-agent architecture with clear handoffs.

## Current Implementation Status (Phase 1)

```
┌─────────────────────┐
│  Market Research    │  ✅ IMPLEMENTED
│  Agent              │
└──────────┬──────────┘
           │ TopicBrief.json
           ↓
┌─────────────────────┐
│  Script Generation  │  ✅ IMPLEMENTED
│  Agent              │
└──────────┬──────────┘
           │ ScriptPackage.json
           ↓
┌─────────────────────┐
│  Video Planning     │  ✅ IMPLEMENTED
│  Agent              │
└──────────┬──────────┘
           │ VideoPlan.json
           ↓
┌─────────────────────┐
│  Audio Generation   │  ✅ IMPLEMENTED (Phase 1)
│  Agent              │  • TTS voiceover ✅
│                     │  • Timeline manifest ✅
│                     │  • Voice presets ✅
│                     │  • Mixing 🔜 Phase 2
└──────────┬──────────┘
           │ AudioTimeline.json + MP3 segments
           ↓
┌─────────────────────┐
│  Visual Agent       │  🔜 PLANNED (Phase 2)
│                     │
└──────────┬──────────┘
           │ VisualAssetManifest.json
           ↓
┌─────────────────────┐
│  Compositor Agent   │  🔜 PLANNED (Phase 2)
│                     │
└──────────┬──────────┘
           │
           ↓
     Final Video (MP4)
```

## Full Pipeline Architecture (Target State)

```
Script Package (JSON)
      ↓
┌─────────────────────┐
│ Orchestrator Agent  │ - Analyzes script timing
│                     │ - Creates production manifest
│                     │ - Coordinates parallel agents
└─────────────────────┘
      ↓
   ┌──────┴──────┐
   ↓             ↓
┌──────────┐  ┌──────────────┐
│  Audio   │  │   Visual     │
│  Agent   │  │   Agent      │
└──────────┘  └──────────────┘
   ↓                ↓
   │           ┌────────────┐
   │           │   Asset    │
   │           │  Library   │
   │           └────────────┘
   │                ↓
   └──→ ┌──────────────────┐ ←──┘
        │  Compositor      │
        │  Agent           │
        └──────────────────┘
              ↓
        Final Video (MP4)
```

## Component Specifications

### 1. Orchestrator Agent
**File**: `src/video_orchestrator.py`

**Responsibilities**:
- Parse script package JSON
- Validate timing and duration constraints
- Create production manifest with scene breakdown
- Coordinate parallel execution of audio and visual agents
- Handle error recovery and retry logic
- Monitor quota usage across APIs

**Input**: Script Package JSON
**Output**: Production Manifest JSON

**Production Manifest Structure**:
```json
{
  "manifest_id": "pm_<uuid>",
  "script_package_id": "sg_<uuid>",
  "scenes": [
    {
      "scene_id": "scene_001",
      "t_start_s": 0.0,
      "t_end_s": 6.43,
      "vo_text": "...",
      "visual_description": "...",
      "on_screen_text": "...",
      "audio_requirements": {
        "sfx": ["energetic_synth_sting"],
        "music_intensity": "high"
      }
    }
  ],
  "global_audio": {
    "background_music_url": "...",
    "tone": "energetic, informative"
  },
  "visual_style": {
    "format": "9:16",
    "resolution": "1080x1920",
    "transitions": "quick_cuts"
  }
}
```

---

### 2. Audio Agent
**File**: `src/audio_agent.py`  
**Status**: ✅ **IMPLEMENTED (Phase 1)**

**Implementation Details**:
- **Class**: `AudioGenerationAgent`
- **Factory**: `create_audio_agent(output_dir, voice, music_volume_db)`
- **Main Method**: `generate_audio_timeline(video_plan) -> AudioTimeline`

**Responsibilities**:
- Convert vo_lines to speech using ElevenLabs TTS API ✅
- Generate individual voiceover segments per scene ✅
- Create structured audio timeline manifest ✅
- Reference background music (Phase 1: no mixing yet) ✅
- Validate video plan structure ✅
- Handle errors with specific exceptions ✅
- *(Phase 2: Audio mixing, normalization, master file export)*

**Tools** (`src/tools/tts_tools.py`):
- ✅ `generate_voiceover(text, voice_id, output_path, stability, similarity_boost)` - ElevenLabs TTS
- ✅ `get_available_voices()` - List available ElevenLabs voices
- ✅ `get_voice_id(voice_name)` - Resolve voice presets to IDs
- 🔜 `apply_background_music(voiceover, music, output, volume_db)` - Phase 2
- 🔜 `mix_audio_tracks(tracks_config, output_path)` - Phase 2
- 🔜 `normalize_audio(input_path, output_path, target_lufs)` - Phase 2

**Voice Presets**:
- `narrator` - Rachel (clear, professional)
- `energetic` - Adam (dynamic, enthusiastic)
- `calm` - Bella (soothing, calm)
- `authoritative` - Arnold (deep, authoritative)

**Multi-Agent Best Practices Implemented**:
1. **Clear Input/Output Contracts**: Accepts VideoPlan, returns AudioTimeline
2. **Deterministic Processing**: Same input produces same output
3. **Structured Artifacts**: JSON manifests with schema versions
4. **Error Handling**: Custom exceptions (AudioGenerationError, TTSError)
5. **Separation of Concerns**: Delegates TTS to tools module
6. **Type Safety**: Full type hints throughout
7. **Documentation**: Google-style docstrings
8. **Validation**: Validates video plan structure before processing
9. **Factory Pattern**: `create_audio_agent()` for easy instantiation
10. **Progress Tracking**: Returns statistics via `get_audio_stats()`

**Input**: VideoPlan (from VideoGenerationAgent)
**Output**: AudioTimeline JSON + Individual Audio Segments

**Audio Timeline Structure**:
```json
{
  "schema_version": "1.0.0",
  "created_at": "2026-02-01T12:00:00Z",
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
      "t_end_s": 6.43,
      "volume_db": 0,
      "metadata": {
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "character_count": 85,
        "file_size_bytes": 154368,
        "estimated_duration_s": 6.43,
        "stability": 0.5,
        "similarity_boost": 0.75
      }
    },
    {
      "type": "music",
      "file": "assets/default_music.mp3",
      "t_start_s": 0.0,
      "t_end_s": 45.0,
      "volume_db": -18,
      "metadata": {
        "comment": "Placeholder track: Creative Commons licensed",
        "note": "Phase 2 will implement actual mixing"
      }
    }
  ],
  "processing_notes": [
    "Phase 1: Individual voiceover segments generated",
    "Phase 2 will add: audio mixing, normalization, master file export"
  ]
}
```

**Configuration** (`src/config.py`):
```python
DEFAULT_VOICE = "narrator"
BACKGROUND_MUSIC_VOLUME_DB = -18.0
VOICEOVER_VOLUME_DB = 0.0
TARGET_LUFS = -16.0
TTS_STABILITY = 0.5
TTS_SIMILARITY_BOOST = 0.75
AUDIO_EXPORT_FORMAT = "mp3"
AUDIO_BITRATE = "192k"
```

**Dependencies** (`requirements.txt`):
```
elevenlabs>=0.2.0
# Phase 2 dependencies (commented):
# pydub>=0.25.0  # for audio mixing
# pyloudnorm>=0.1.0  # for normalization
# ffmpeg-python>=0.2.0  # for advanced processing
```

---

### 3. Visual Agent
**File**: `src/visual_agent.py`  
**Status**: 🔜 **PLANNED**

**Responsibilities**:
- Interpret visual requirements from each scene
- **Phase 1**: Search/generate static images for slideshow
- **Phase 2**: Search/generate video clips
- Generate on-screen text overlays with styling
- Ensure visual coherence across scenes
- Cache and reuse assets when appropriate

**Tools** (`src/tools/visual_tools.py`):
- `search_stock_images(query, orientation, style)` - Stock photo APIs
- `generate_ai_image(prompt, style, aspect_ratio)` - AI image generation
- `search_stock_clips(query, duration)` - Stock video APIs (Phase 2)
- `create_text_overlay(text, style, position)` - Text rendering

**Input**: Production Manifest
**Output**: Visual Asset Manifest JSON + Asset Files

**Visual Asset Manifest Structure**:
```json
{
  "scenes": [
    {
      "scene_id": "scene_001",
      "assets": [
        {
          "type": "image",
          "file_path": "results/<id>/assets/scene_001_bg.jpg",
          "display_duration_s": 6.43,
          "transitions": ["fade_in", "ken_burns"]
        },
        {
          "type": "text_overlay",
          "text": "Time Dilation",
          "style": "bold_white_outline",
          "position": "center",
          "t_start_s": 1.0,
          "t_end_s": 5.0
        }
      ]
    }
  ]
}
```

---

### 4. Compositor Agent
**File**: `src/compositor_agent.py`

**Responsibilities**:
- Receive audio timeline + visual asset manifest
- Assemble all elements with precise timing
- Apply transitions between scenes
- Render on-screen text overlays
- Add visual effects (zoom, pan, etc.)
- Export final video in target format

**Tools** (`src/tools/compositor_tools.py`):
- `create_video_sequence(visual_assets, audio_timeline)` - Main assembly
- `apply_transition(clip1, clip2, transition_type)` - Transition effects
- `render_text_overlay(clip, text_config)` - Text rendering
- `export_video(composition, output_path, format_spec)` - Final export

**Input**: Audio Timeline + Visual Asset Manifest + Production Manifest
**Output**: Final Video (MP4)

**Technology Stack**:
- **MoviePy**: Python video editing library
- **FFmpeg**: Low-level video processing (via subprocess)
- **Pillow**: Image manipulation for text overlays

---

## Implementation Phases

### Phase 1: Image Slideshow Pipeline (Current Focus)
- Orchestrator creates manifest
- Audio Agent generates voiceover + applies default music track
- Visual Agent sources static images
- Compositor creates slideshow-style video

**Use Case**: Low compute cost, fast iteration, proof of concept
**Music**: Single placeholder track ("Pixel Peeker Polka - slower" by Kevin MacLeod, CC BY 4.0)

### Phase 2: Video Clip Integration (Future)
- Visual Agent searches stock video clips instead of images
- Compositor handles video-to-video transitions
- More dynamic visual storytelling

**Use Case**: Higher production value, competitive with professional content

### Phase 3: AI-Generated Clips (Future)
- Visual Agent uses generative video AI (Runway, Pika, etc.)
- Custom visuals for every scene
- No stock footage licensing concerns

**Use Case**: Unique content, brand differentiation

---

## Data Flow

1. **Script Package** → Orchestrator
2. Orchestrator creates **Production Manifest**
3. **Parallel Execution**:
   - Audio Agent → Audio Timeline + WAV file
   - Visual Agent → Visual Asset Manifest + Image/Video files
4. Compositor receives all inputs
5. Compositor outputs **Final Video MP4**

---

## Error Handling

### Orchestrator
- Validates script package schema before processing
- Retries failed API calls with exponential backoff
- Falls back to cached assets if APIs unavailable

### Audio Agent
- Validates TTS output duration matches expected timing
- Automatic audio level normalization to prevent clipping
- Fallback to alternative TTS voices if primary fails

### Visual Agent
- Multiple fallback sources for images (Pexels → Unsplash → AI generation)
- Cache results to avoid redundant API calls
- Validate image dimensions and quality

### Compositor
- Validates all input files exist before rendering
- Progress tracking for long renders
- Automatic cleanup of temporary files

---

## File Organization

```
results/
  vp_<date>_<topic>_<hash>/        # Video Production folder
    production_manifest.json         # Orchestrator output
    audio_timeline.json              # Audio Agent output
    visual_asset_manifest.json       # Visual Agent output
    audio_master.wav                 # Mixed audio
    assets/                          # Visual assets
      scene_001_bg.jpg
      scene_002_bg.jpg
      ...
    temp/                            # Temporary files (auto-cleanup)
    final_video.mp4                  # Compositor output
```

---

## Performance Considerations

### Parallelization
- Audio and Visual agents run concurrently (50% time savings)
- Asset downloads can be batched/parallelized
- Compositor pre-loads assets while rendering

### Caching Strategy
- Cache TTS outputs per voice + text combination
- Cache stock images/clips per query
- Reuse background music across similar topics

### Quota Management
- Track API usage across all tools
- Implement rate limiting to avoid quota exhaustion
- Graceful degradation when quotas exceeded

---

## API Keys & Configuration

See `src/config.py` for centralized API key management. All agents should read from environment variables with fallback to config file.

Required services documented in separate section below.

---

## Multi-Agent Workflow Best Practices

This pipeline follows industry-standard multi-agent design patterns to ensure reliability, maintainability, and scalability.

### 1. Clear Agent Contracts
**Each agent has well-defined inputs and outputs:**
- **Input Schema**: Validated JSON with required fields
- **Output Schema**: Versioned artifacts with metadata
- **Schema Versions**: All artifacts include `schema_version` for evolution

**Example**:
```python
# Input: VideoPlan v1.0.0
# Output: AudioTimeline v1.0.0
timeline = audio_agent.generate_audio_timeline(video_plan)
```

### 2. Separation of Concerns
**Each agent has a single, focused responsibility:**
- **Market Research Agent**: YouTube analysis → TopicBrief
- **Script Agent**: TopicBrief → ScriptPackage
- **Video Planner**: ScriptPackage → VideoPlan
- **Audio Agent**: VideoPlan → AudioTimeline
- **Visual Agent**: VideoPlan → VisualAssetManifest (planned)
- **Compositor**: AudioTimeline + VisualAssets → Video (planned)

**Benefits**:
- Independent development and testing
- Easy to replace/upgrade individual agents
- Parallel execution where possible

### 3. Deterministic Processing
**Same input → Same output:**
- Agents are stateless and reproducible
- Random elements use fixed seeds when needed
- Timestamps use consistent UTC timezone

**Example**:
```python
# Running twice with same input produces identical output
result1 = agent.process(input_data)
result2 = agent.process(input_data)
assert result1 == result2
```

### 4. Structured Error Handling
**Agent-specific exceptions with clear error messages:**
```python
class AudioGenerationError(Exception):
    """Base exception for audio generation failures."""
    
class TTSError(Exception):
    """TTS API-specific errors."""
    
class AudioMixingError(Exception):
    """Audio processing failures."""
```

**Error propagation with context:**
```python
try:
    audio_path, metadata = generate_voiceover(text, voice_id)
except TTSError as e:
    raise AudioGenerationError(
        f"Failed to generate voiceover for scene {scene_id}: {e}"
    )
```

### 5. Factory Pattern for Agent Creation
**Consistent instantiation across all agents:**
```python
# Market Research Agent
agent = create_market_research_agent()

# Script Agent
agent = create_script_agent(model="gemini-flash-latest")

# Video Agent
agent = create_video_agent()

# Audio Agent
agent = create_audio_agent(
    output_dir=Path("results/run_001"),
    voice="narrator",
    music_volume_db=-18.0
)
```

### 6. Comprehensive Type Hints
**Full type annotations for better IDE support and error detection:**
```python
def generate_audio_timeline(
    self,
    video_plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate audio timeline from video plan."""
    pass
```

### 7. Tool Delegation Pattern
**Agents delegate specialized tasks to tool modules:**
- **Audio Agent** → `tts_tools.py` for TTS generation
- **Visual Agent** → `visual_tools.py` for image search
- **Market Research Agent** → `youtube_tools.py` for YouTube API

**Benefits**:
- Tools can be unit tested independently
- Multiple agents can share tools
- Easy to swap implementations (e.g., different TTS providers)

### 8. Artifact Persistence
**All intermediate outputs saved as JSON + files:**
```
results/
  mr_2026-02-01_science_fiction_5b4c37/
    market_research_report.json
    topicbrief_*.json
  sg_2026-02-01_topic_science_fiction_fa_dcfe74/
    script_package.json
  vp_2026-02-01_topic_science_fiction_fa_cc636b/
    video_plan.json
  at_2026-02-01_topic_science_fiction_fa_a1b2c3/
    audio_timeline.json
    audio_segments/
      vo_scene_01.mp3
      vo_scene_02.mp3
```

**Benefits**:
- Debugging intermediate stages
- Rerunning from any stage
- Auditing agent decisions
- Training data for ML models

### 9. Configuration Management
**Centralized config with environment variable overrides:**
```python
# src/config.py
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "narrator")
BACKGROUND_MUSIC_VOLUME_DB = float(
    os.getenv("BACKGROUND_MUSIC_VOLUME_DB", "-18.0")
)
```

### 10. Documentation Standards
**Google-style docstrings throughout:**
```python
def generate_voiceover(
    text: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
    output_path: Optional[Path] = None,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> Tuple[Path, Dict[str, Any]]:
    """Generate voiceover audio from text using ElevenLabs TTS API.
    
    Args:
        text: The text to convert to speech.
        voice_id: ElevenLabs voice ID. Default is Rachel.
        output_path: Optional output file path.
        stability: Voice stability (0.0-1.0).
        similarity_boost: Voice similarity (0.0-1.0).
    
    Returns:
        Tuple of (audio_file_path, metadata_dict).
    
    Raises:
        TTSError: If API key is missing or API call fails.
    """
```

### 11. Progress Tracking & Statistics
**Agents provide introspection methods:**
```python
# Audio Agent provides statistics
stats = audio_agent.get_audio_stats(audio_timeline)
print(f"Generated {stats['voiceover_tracks']} tracks")
print(f"Total duration: {stats['total_duration_s']}s")
print(f"Avg speaking rate: {stats['avg_chars_per_second']} chars/s")
```

### 12. Validation at Boundaries
**Input validation before processing:**
```python
def _validate_video_plan(self, video_plan: Dict[str, Any]) -> None:
    """Validate video plan structure."""
    if not isinstance(video_plan, dict):
        raise AudioGenerationError("video_plan must be a dictionary")
    
    if "scenes" not in video_plan:
        raise AudioGenerationError("video_plan missing 'scenes' field")
    
    for i, scene in enumerate(video_plan["scenes"]):
        required_fields = ["t_start_s", "t_end_s", "vo_line"]
        for field in required_fields:
            if field not in scene:
                raise AudioGenerationError(
                    f"Scene {i} missing required field: {field}"
                )
```

### Anti-Patterns Avoided
❌ **Monolithic agents** - Each agent should do one thing well  
❌ **Tight coupling** - Agents communicate via structured artifacts only  
❌ **Implicit contracts** - All inputs/outputs explicitly documented  
❌ **Silent failures** - All errors raise specific exceptions  
❌ **Global state** - Agents are stateless and reproducible  
❌ **Direct tool calls** - Use agent methods, not direct tool imports  
❌ **Undocumented outputs** - All artifacts include metadata and timestamps  

### Benefits of This Architecture
✅ **Testability** - Each agent can be unit tested independently  
✅ **Debuggability** - All intermediate artifacts are saved  
✅ **Scalability** - Independent agents can run in parallel  
✅ **Maintainability** - Clear responsibilities and contracts  
✅ **Extensibility** - Easy to add new agents or replace existing ones  
✅ **Reliability** - Deterministic processing with error handling  

---

## Future Enhancements

1. **Real-time Preview**: Stream preview to user before final render
2. **A/B Testing**: Generate multiple visual variations for same script
3. **Internationalization**: Multi-language voiceover support
4. **Analytics Integration**: Track which visual styles perform best
5. **Brand Customization**: Consistent color schemes, fonts, logos
