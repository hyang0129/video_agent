# Video Production Pipeline Architecture

## Overview
The video production pipeline transforms script packages into finished short-form videos through a parallel agent architecture with a central orchestrator.

## Architecture Diagram

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

**Responsibilities**:
- Convert vo_lines to speech using TTS API
- Apply default placeholder background music
- Mix voiceover with music at appropriate levels
- Normalize audio levels
- Export final audio timeline
- *(Phase 2: Sound effects, dynamic music selection)*

**Tools** (`src/tools/tts_tools.py`):
- `generate_voiceover(text, voice_profile, duration_hint)` - TTS generation
- `fetch_sound_effect(sfx_description)` - SFX library search (Phase 2)
- `apply_background_music(voiceover, music_file, volume)` - Mix default music track
- `mix_audio_tracks(tracks_config)` - Audio mixing

**Input**: Production Manifest
**Output**: Audio Timeline JSON + Audio File (WAV)

**Audio Timeline Structure**:
```json
{
  "audio_file_path": "results/<id>/audio_master.wav",
  "duration_seconds": 45.0,
  "tracks": [
    {
      "type": "voiceover",
      "file": "vo_segment_001.wav",
      "t_start_s": 0.0,
      "volume_db": 0
    },
    {
      "type": "sfx",
      "file": "synth_sting.wav",
      "t_start_s": 0.0,
      "volume_db": -6
    },
    {
      "type": "music",
      "file": "assets/default_music.mp3",
      "t_start_s": 0.0,
      "volume_db": -18,
      "comment": "Placeholder track: Creative Commons licensed"
    }
  ]
}
```

---

### 3. Visual Agent
**File**: `src/visual_agent.py`

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

## Future Enhancements

1. **Real-time Preview**: Stream preview to user before final render
2. **A/B Testing**: Generate multiple visual variations for same script
3. **Internationalization**: Multi-language voiceover support
4. **Analytics Integration**: Track which visual styles perform best
5. **Brand Customization**: Consistent color schemes, fonts, logos
