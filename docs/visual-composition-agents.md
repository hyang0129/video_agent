# Visual & Composition Agents Specification

## Overview

This specification defines the architecture for the visual asset generation and video composition stages of the pipeline, completing the journey from script to final rendered video.

**Pipeline Position:**
```
Market Research → Script → Video Plan → Audio → Visual → Composition → Final Video
     ✅           ✅         ✅          ✅        🔜         🔜            🔜
```

**Key Principles:**
- Follow established multi-agent patterns (clear I/O contracts, deterministic processing)
- Separate concerns: visual selection/validation vs. composition/timing
- Support progressive complexity (Phase 1: static images → Phase 2: motion/effects → Phase 3: AI-generated)
- Enable human-in-the-loop review at each stage

---

## Agent Architecture

### 3-Agent Design (Recommended)

We propose **3 specialized agents** rather than a monolithic "video renderer":

1. **Visual Asset Agent** - Selects and validates images/footage
2. **Composition Agent** - Handles timing, transitions, and effects
3. **Render Agent** - Executes final video compilation

**Why 3 agents?**
- **Separation of concerns:** Image selection requires different tools (image search APIs, content moderation) than composition (FFmpeg, MoviePy)
- **Human review points:** Can inspect/approve visuals before committing to render
- **Parallel development:** Teams can work on asset generation and composition independently
- **Flexibility:** Swap composition engines (FFmpeg → cloud renderer) without touching asset logic

---

## Agent 1: Visual Asset Agent

### Responsibility
Select, validate, and prepare visual assets (images/video clips) that match the script content and pass content safety checks.

### Input Contract: VideoPlan
```json
{
  "schema_version": "1.0.0",
  "video_plan_id": "vp_20260201_scifi_a1b2c3",
  "scenes": [
    {
      "scene_id": "scene_01",
      "t_start_s": 0.0,
      "t_end_s": 6.5,
      "vo_line": "The multiverse theory suggests...",
      "on_screen_text": "THE MULTIVERSE",
      "visual_direction": "b-roll or simple illustration supporting the on-screen text",
      "asset_prompts": ["multiverse concept", "parallel universes"]
    }
  ]
}
```

### Output Contract: VisualManifest
```json
{
  "schema_version": "1.0.0",
  "visual_manifest_id": "vm_20260201_scifi_a1b2c3",
  "video_plan_ref": "vp_20260201_scifi_a1b2c3",
  "created_at": "2026-02-02T10:30:00Z",
  "total_scenes": 8,
  "total_assets": 8,
  "assets": [
    {
      "asset_id": "asset_scene_01",
      "scene_id": "scene_01",
      "type": "image",
      "source": "unsplash",
      "file_path": "assets/scene_01_multiverse.jpg",
      "url": "https://images.unsplash.com/photo-123...",
      "resolution": [1920, 1080],
      "attribution": {
        "required": true,
        "text": "Photo by John Doe on Unsplash",
        "license": "Unsplash License"
      },
      "content_safety": {
        "validated": true,
        "service": "google_vision_api",
        "flags": [],
        "score": 0.98
      },
      "metadata": {
        "search_query": "multiverse concept visualization",
        "alternatives_considered": 5,
        "selection_reason": "Best match for 'parallel universes', high resolution, safe content"
      }
    }
  ]
}
```

### Core Responsibilities

#### 1. Asset Discovery
**Phase 1 (MVP):**
- Search free stock image APIs (Unsplash, Pexels, Pixabay)
- Use `asset_prompts` from VideoPlan
- Filter by license compatibility (creative commons / free commercial use)
- Prioritize high resolution (1920x1080+)

**Phase 2:**
- Search stock video APIs (Pexels Video, Pixabay Video)
- Support AI image generation (DALL-E, Midjourney, Stable Diffusion)
- Custom asset upload/library management

**Phase 3:**
- AI video generation (Runway, Pika, etc.)

#### 2. Content Validation
**Must implement:**
- Content safety API (Google Vision API, AWS Rekognition, Azure Content Moderator)
- Check for: violence, adult content, misleading imagery
- Relevance scoring (does image match script context?)
- License verification

**Decision logic:**
- Each asset must pass content safety threshold (e.g., safety_score > 0.9)
- If asset fails validation, automatically select next alternative
- Log all validation attempts for audit

#### 3. Asset Preparation
- Download and cache assets locally
- Validate file integrity (not corrupted)
- Store in `results/<run_id>/assets/` directory
- Track attribution requirements

### API Design

```python
class VisualAssetAgent:
    """Agent for discovering, validating, and preparing visual assets.
    
    Attributes:
        output_dir: Directory for cached assets and manifest.
        image_sources: List of enabled image sources ['unsplash', 'pexels'].
        content_validator: Content safety validation service.
        min_safety_score: Minimum safety score (0-1) to accept asset.
    """
    
    def __init__(
        self,
        output_dir: Path,
        image_sources: List[str] = ["unsplash", "pexels"],
        content_validator: str = "google_vision",
        min_safety_score: float = 0.9,
    ):
        """Initialize visual asset agent."""
        pass
    
    def generate_visual_manifest(
        self,
        video_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate complete visual manifest from video plan.
        
        Main entry point. For each scene:
        1. Extract asset_prompts
        2. Search image sources
        3. Validate top candidates
        4. Select best valid asset
        5. Download and cache
        
        Args:
            video_plan: VideoPlan dictionary with scenes and asset requirements.
        
        Returns:
            VisualManifest dictionary with validated assets.
        
        Raises:
            VisualAssetError: If unable to find valid assets for required scenes.
        """
        pass
    
    def search_assets(
        self,
        query: str,
        asset_type: str = "image",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search for assets matching query.
        
        Returns:
            List of asset metadata (url, source, license, etc.)
        """
        pass
    
    def validate_content(
        self,
        asset_url: str,
    ) -> Dict[str, Any]:
        """Validate asset content safety.
        
        Returns:
            {
                "validated": bool,
                "service": str,
                "flags": List[str],
                "score": float
            }
        """
        pass
    
    def download_asset(
        self,
        asset_url: str,
        scene_id: str,
    ) -> Path:
        """Download and cache asset locally.
        
        Returns:
            Path to cached file.
        """
        pass
```

### Tool Dependencies

```python
# src/tools/image_search_tools.py
def search_unsplash(query: str, per_page: int = 10) -> List[Dict]:
    """Search Unsplash API for images."""
    pass

def search_pexels(query: str, per_page: int = 10) -> List[Dict]:
    """Search Pexels API for images."""
    pass

# src/tools/content_validation_tools.py
def validate_image_safety(image_url: str, provider: str = "google") -> Dict:
    """Validate image content safety using cloud APIs."""
    pass

def check_relevance_score(image_url: str, text_context: str) -> float:
    """Use CLIP or similar to score image-text relevance."""
    pass
```

### Configuration

```python
# Environment variables
UNSPLASH_API_KEY = os.getenv("UNSPLASH_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY")

# Constants
MIN_IMAGE_WIDTH = 1920
MIN_IMAGE_HEIGHT = 1080
MAX_ASSET_FILE_SIZE_MB = 50
CONTENT_SAFETY_THRESHOLD = 0.9
```

---

## Agent 2: Composition Agent

### Responsibility
Create a render specification that defines exact timing, transitions, effects, and layering for the final video, integrating audio timeline and visual manifest.

### Input Contracts
1. **AudioTimeline** (from Audio Agent)
2. **VisualManifest** (from Visual Asset Agent)
3. **VideoPlan** (original plan with scene structure)

### Output Contract: RenderSpecification
```json
{
  "schema_version": "1.0.0",
  "render_spec_id": "rs_20260201_scifi_a1b2c3",
  "created_at": "2026-02-02T10:45:00Z",
  "video_plan_ref": "vp_20260201_scifi_a1b2c3",
  "audio_timeline_ref": "at_20260201_scifi_a1b2c3",
  "visual_manifest_ref": "vm_20260201_scifi_a1b2c3",
  "output_settings": {
    "resolution": [1080, 1920],
    "fps": 30,
    "format": "mp4",
    "codec": "h264",
    "duration_seconds": 45.0
  },
  "layers": [
    {
      "layer_id": "layer_video",
      "type": "video",
      "z_index": 0,
      "clips": [
        {
          "clip_id": "clip_scene_01",
          "scene_id": "scene_01",
          "asset_ref": "asset_scene_01",
          "source_file": "assets/scene_01_multiverse.jpg",
          "t_start_s": 0.0,
          "t_end_s": 6.5,
          "duration_s": 6.5,
          "effects": [
            {
              "type": "ken_burns",
              "direction": "zoom_in",
              "intensity": 1.15,
              "anchor": "center"
            }
          ],
          "transition_in": {
            "type": "fade",
            "duration_s": 0.3
          },
          "transition_out": {
            "type": "fade",
            "duration_s": 0.3
          }
        }
      ]
    },
    {
      "layer_id": "layer_subtitles",
      "type": "text",
      "z_index": 2,
      "elements": [
        {
          "element_id": "subtitle_scene_01",
          "scene_id": "scene_01",
          "text": "THE MULTIVERSE",
          "t_start_s": 0.5,
          "t_end_s": 6.0,
          "position": {"x": "center", "y": 0.75},
          "style": {
            "font": "Montserrat-Bold",
            "size": 72,
            "color": "#FFFFFF",
            "stroke": {"color": "#000000", "width": 4},
            "shadow": {"blur": 8, "opacity": 0.8}
          },
          "animation": {
            "in": {"type": "fade_up", "duration_s": 0.3},
            "out": {"type": "fade", "duration_s": 0.2}
          }
        }
      ]
    },
    {
      "layer_id": "layer_audio",
      "type": "audio",
      "z_index": -1,
      "tracks": [
        {
          "track_id": "track_vo",
          "type": "voiceover",
          "segments": [
            {
              "segment_id": "vo_scene_01",
              "scene_id": "scene_01",
              "source_file": "audio_segments/vo_scene_01.mp3",
              "t_start_s": 0.0,
              "t_end_s": 6.5,
              "volume_db": 0
            }
          ]
        }
      ]
    }
  ]
}
```

### Core Responsibilities

#### 1. Timing Synchronization
**Critical:** Audio is the **source of truth** for timing.
- Extract scene durations from AudioTimeline tracks
- Ensure visual clips exactly match audio segment durations
- Handle timing edge cases (pauses, overlaps)

**Logic:**
```python
for audio_segment in audio_timeline['tracks']:
    scene_id = audio_segment['scene_id']
    t_start = audio_segment['t_start_s']
    t_end = audio_segment['t_end_s']
    
    # Find corresponding visual asset
    visual_asset = get_asset_for_scene(visual_manifest, scene_id)
    
    # Create video clip with exact audio timing
    create_clip(visual_asset, t_start, t_end)
```

#### 2. Effect Application (Ken Burns)
**Phase 1:** Simple Ken Burns effect (zoom + pan)
- Apply to static images to create motion
- Randomize or alternate directions (zoom in/out, pan left/right)
- Keep intensity subtle (1.1x - 1.2x zoom)

**Configuration:**
```python
KEN_BURNS_EFFECTS = [
    {"direction": "zoom_in", "intensity": 1.15, "anchor": "center"},
    {"direction": "zoom_out", "intensity": 0.85, "anchor": "center"},
    {"direction": "pan_left", "distance": 0.1, "zoom": 1.1},
    {"direction": "pan_right", "distance": 0.1, "zoom": 1.1},
]
```

**Phase 2:** Advanced effects
- Parallax motion
- Color grading
- Vignettes

#### 3. Transition Management
- Add smooth transitions between clips (fade, crossfade, wipe)
- Default: 0.3s fade-in, 0.3s fade-out
- Prevent jarring cuts

#### 4. Text Overlay (Subtitles/Captions)
- Extract `on_screen_text` from VideoPlan scenes
- Position appropriately (typically lower third or center)
- Apply styling from CreativeSpec
- Time to align with voiceover

#### 5. Multi-Layer Composition
Define render order:
- **Layer 0 (bottom):** Video clips / images
- **Layer 1:** Overlays / effects
- **Layer 2 (top):** Text / subtitles
- **Layer -1 (audio):** Audio tracks

### API Design

```python
class CompositionAgent:
    """Agent for creating render specifications from audio and visual assets.
    
    Attributes:
        output_dir: Directory for render specification output.
        default_fps: Target frame rate (30 or 60).
        resolution: Output resolution [width, height].
        transition_duration_s: Default transition duration.
    """
    
    def __init__(
        self,
        output_dir: Path,
        resolution: Tuple[int, int] = (1080, 1920),  # Vertical video
        fps: int = 30,
        transition_duration_s: float = 0.3,
    ):
        """Initialize composition agent."""
        pass
    
    def create_render_specification(
        self,
        video_plan: Dict[str, Any],
        audio_timeline: Dict[str, Any],
        visual_manifest: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create complete render specification.
        
        Main entry point. Combines all inputs into a deterministic
        render specification that a renderer can execute.
        
        Args:
            video_plan: VideoPlan with scene structure and text overlays.
            audio_timeline: AudioTimeline with voiceover timing.
            visual_manifest: VisualManifest with validated assets.
        
        Returns:
            RenderSpecification dictionary.
        
        Raises:
            CompositionError: If inputs are incompatible or incomplete.
        """
        pass
    
    def synchronize_timing(
        self,
        audio_timeline: Dict[str, Any],
        visual_manifest: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Synchronize visual clips to audio timing.
        
        Returns:
            List of clip definitions with exact timing.
        """
        pass
    
    def apply_effects(
        self,
        clip: Dict[str, Any],
        effect_style: str = "ken_burns",
    ) -> Dict[str, Any]:
        """Apply motion effects to static image clip.
        
        Returns:
            Clip definition with effects added.
        """
        pass
    
    def create_text_overlays(
        self,
        video_plan: Dict[str, Any],
        audio_timeline: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Create text overlay elements from on_screen_text.
        
        Returns:
            List of text element definitions.
        """
        pass
```

### Determinism & Reproducibility
**Critical:** Same inputs → same render spec
- Use deterministic effect selection (scene_id hash → effect choice)
- No random choices without seed
- All decisions should be auditable

---

## Agent 3: Render Agent

### Responsibility
Execute the render specification to produce the final video file using a rendering engine (FFmpeg, MoviePy, cloud service).

### Input Contract: RenderSpecification
(See Composition Agent output above)

### Output Contract: FinalVideo
```json
{
  "schema_version": "1.0.0",
  "final_video_id": "fv_20260201_scifi_a1b2c3",
  "render_spec_ref": "rs_20260201_scifi_a1b2c3",
  "created_at": "2026-02-02T11:00:00Z",
  "video_file_path": "results/run_20260201/final_video.mp4",
  "thumbnail_path": "results/run_20260201/thumbnail.jpg",
  "file_size_mb": 15.3,
  "duration_seconds": 45.0,
  "resolution": [1080, 1920],
  "fps": 30,
  "codec": "h264",
  "bitrate_kbps": 2800,
  "render_metadata": {
    "engine": "ffmpeg",
    "render_time_seconds": 23.5,
    "success": true,
    "warnings": [],
    "preview_url": null
  }
}
```

### Core Responsibilities

#### 1. Engine Abstraction
Support multiple rendering backends:
- **FFmpeg** (local, fast, free)
- **MoviePy** (local, Python-friendly, slower)
- **Cloud services** (Shotstack, Creatomate, etc.)

```python
class RenderEngine(ABC):
    """Abstract base class for render engines."""
    
    @abstractmethod
    def render(self, render_spec: Dict) -> Path:
        """Execute render and return video file path."""
        pass
```

#### 2. Render Execution
- Parse RenderSpecification layers
- Build render pipeline (filters, overlays, compositing)
- Execute render process
- Monitor progress (if supported)

**FFmpeg Example:**
```python
def build_ffmpeg_command(render_spec: Dict) -> List[str]:
    """Convert RenderSpecification to FFmpeg command."""
    cmd = ["ffmpeg", "-y"]
    
    # Add video inputs (image sequences with Ken Burns)
    for clip in render_spec['layers'][0]['clips']:
        cmd.extend([
            "-loop", "1",
            "-t", str(clip['duration_s']),
            "-i", clip['source_file'],
        ])
    
    # Add audio input
    cmd.extend(["-i", audio_timeline['audio_file_path']])
    
    # Add filters (zoompan for Ken Burns, overlays for text)
    filter_complex = build_filter_complex(render_spec)
    cmd.extend(["-filter_complex", filter_complex])
    
    # Output settings
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "output.mp4"
    ])
    
    return cmd
```

#### 3. Quality Control
- Validate output file exists and is not corrupted
- Verify duration matches expected
- Check video/audio sync
- Generate thumbnail

#### 4. Error Handling
- Retry logic for transient failures
- Detailed error logging
- Cleanup partial renders

### API Design

```python
class RenderAgent:
    """Agent for executing render specifications to produce final videos.
    
    Attributes:
        output_dir: Directory for rendered video output.
        engine: Rendering engine to use ('ffmpeg', 'moviepy', 'shotstack').
        quality_preset: Quality/speed tradeoff ('fast', 'medium', 'high').
    """
    
    def __init__(
        self,
        output_dir: Path,
        engine: str = "ffmpeg",
        quality_preset: str = "medium",
    ):
        """Initialize render agent."""
        pass
    
    def render_video(
        self,
        render_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Render final video from specification.
        
        Main entry point. Executes the full render pipeline.
        
        Args:
            render_spec: RenderSpecification dictionary.
        
        Returns:
            FinalVideo dictionary with file path and metadata.
        
        Raises:
            RenderError: If render fails or output is invalid.
        """
        pass
    
    def validate_output(
        self,
        video_path: Path,
        expected_duration_s: float,
    ) -> Dict[str, Any]:
        """Validate rendered video quality.
        
        Returns:
            Validation report with success status and any warnings.
        """
        pass
    
    def generate_thumbnail(
        self,
        video_path: Path,
        timestamp_s: float = 1.0,
    ) -> Path:
        """Extract thumbnail frame from video.
        
        Returns:
            Path to thumbnail image.
        """
        pass
```

---

## Phase 1 Implementation Plan

### Milestone 1: Visual Asset Agent (MVP)
**Goal:** Select and validate images for each scene
- [ ] Implement Unsplash/Pexels search integration
- [ ] Add basic content safety validation (Google Vision API)
- [ ] Download and cache assets locally
- [ ] Generate VisualManifest output
- [ ] Unit tests for asset search and validation

**Deliverables:**
- `src/visual_asset_agent.py`
- `src/tools/image_search_tools.py`
- `src/tools/content_validation_tools.py`
- `docs/visual-asset-agent.md`

### Milestone 2: Composition Agent (Static Images)
**Goal:** Create render specs with Ken Burns effects and text overlays
- [ ] Implement timing synchronization with AudioTimeline
- [ ] Add Ken Burns effect definitions
- [ ] Create text overlay layer from on_screen_text
- [ ] Add transition definitions
- [ ] Generate RenderSpecification output
- [ ] Unit tests for composition logic

**Deliverables:**
- `src/composition_agent.py`
- `docs/composition-agent.md`

### Milestone 3: Render Agent (FFmpeg)
**Goal:** Execute renders using FFmpeg locally
- [ ] Implement FFmpeg command builder
- [ ] Add Ken Burns effect (zoompan filter)
- [ ] Add text overlay rendering (drawtext filter)
- [ ] Add audio mixing
- [ ] Implement quality validation
- [ ] Generate thumbnail
- [ ] Integration tests with real assets

**Deliverables:**
- `src/render_agent.py`
- `src/tools/ffmpeg_tools.py`
- `docs/render-agent.md`

### Milestone 4: End-to-End Integration
**Goal:** Complete pipeline from market research to final video
- [ ] Integration script: `examples/full_pipeline_example.py`
- [ ] Update `docs/pipeline-integration.md` with visual/render steps
- [ ] Performance benchmarks
- [ ] Error handling and recovery
- [ ] Logging and observability

---

## Phase 2: Advanced Features

### Visual Enhancements
- AI-generated images (DALL-E 3, Stable Diffusion)
- Stock video clips (with playback speed adjustments)
- Advanced effects (parallax, color grading, vignettes)

### Composition Improvements
- Dynamic subtitle timing with word-level highlighting
- Multi-voice support (different text styles per character)
- Scene-aware transition selection
- Automatic B-roll cutting for longer videos

### Render Optimization
- GPU acceleration (NVENC, QuickSync)
- Cloud rendering (Shotstack, Creatomate)
- Parallel rendering (split video into chunks)
- Adaptive quality (target bitrate optimization)

---

## Design Decisions & Rationale

### Why 3 Agents Instead of 1?

**Alternative considered:** Single "VideoRenderer" agent
**Rejected because:**
- Violates single responsibility principle
- Hard to test image search independently from FFmpeg
- Can't review/approve visuals before render
- Tightly couples asset discovery to rendering engine

### Why Audio Timing is Source of Truth?

Audio duration is known and fixed after TTS generation. Visual clips must adapt to audio, not vice versa. This prevents audio-video desynchronization issues.

### Why Deterministic Composition?

Random effects make debugging impossible and prevent reproducible builds. Use deterministic algorithms (hash scene_id → effect choice) to ensure same inputs always produce same output.

### Why Static Images First?

**Complexity ladder:**
1. Static images (easy, free, fast)
2. Stock video (moderate cost, licensing complexity)
3. AI-generated video (expensive, slow, bleeding edge)

Start simple, prove the pipeline, then add complexity.

---

## API & Tool Requirements

### Required External APIs

#### Image Search (Free Tier Available)
- **Unsplash API:** 50 requests/hour free
- **Pexels API:** 200 requests/hour free
- **Pixabay API:** 5000 requests/hour (conditional)

#### Content Safety
- **Google Cloud Vision API:** Free tier available
- **AWS Rekognition:** Free tier available
- **Azure Content Moderator:** Free tier available

#### Future (Phase 2)
- **OpenAI DALL-E 3:** $0.04 per image
- **Stability AI:** Various pricing
- **Shotstack (Render):** $9/month + per-minute rendering

### Local Dependencies

```bash
# FFmpeg (required for render agent)
# Windows:
choco install ffmpeg
# or download from https://ffmpeg.org/

# ImageMagick (optional, for advanced image processing)
choco install imagemagick

# Python packages
pip install Pillow>=10.0.0         # Image processing
pip install requests>=2.31.0        # API calls
pip install moviepy>=1.0.3          # Alternative render engine
```

---

## Configuration Example

```python
# config.py additions

# Visual Asset Agent
UNSPLASH_API_KEY = os.getenv("UNSPLASH_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY")

IMAGE_SEARCH_SOURCES = ["unsplash", "pexels"]
MIN_IMAGE_RESOLUTION = (1920, 1080)
CONTENT_SAFETY_THRESHOLD = 0.9

# Composition Agent
DEFAULT_RESOLUTION = (1080, 1920)  # Vertical for Shorts/TikTok
DEFAULT_FPS = 30
TRANSITION_DURATION_S = 0.3
KEN_BURNS_INTENSITY_RANGE = (1.1, 1.2)

# Render Agent
RENDER_ENGINE = "ffmpeg"  # or "moviepy", "shotstack"
FFMPEG_PRESET = "medium"  # fast, medium, slow
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
TARGET_BITRATE_KBPS = 2800
```

---

## Testing Strategy

### Unit Tests
- Visual Asset Agent: Mock API responses, test validation logic
- Composition Agent: Test timing sync with fixture data
- Render Agent: Test command generation (don't execute)

### Integration Tests
- End-to-end: VideoPlan → VisualManifest → RenderSpec → FinalVideo
- Use small test assets to minimize test runtime
- Verify file outputs exist and are valid

### Performance Tests
- Benchmark asset search latency
- Measure render time per second of video
- Track API quota usage

---

## Error Handling & Recovery

### Visual Asset Agent Errors
- **No valid assets found:** Fallback to generic placeholder images
- **API rate limit:** Cache results, implement exponential backoff
- **Content safety failure:** Try next search result, log rejection reason

### Composition Agent Errors
- **Missing asset:** Error early, don't attempt render
- **Timing mismatch:** Error if audio/visual durations don't align
- **Invalid effect:** Skip effect, log warning, continue

### Render Agent Errors
- **FFmpeg crash:** Retry once, log full command and stderr
- **Corrupted output:** Delete partial file, re-render
- **Timeout:** Configurable max render time, terminate and report

---

## Success Metrics

### Phase 1 Goals
- [ ] Generate VisualManifest with 100% scene coverage
- [ ] All assets pass content safety validation
- [ ] Render 45-second video in < 60 seconds on CPU
- [ ] No audio-video desynchronization (< 50ms drift)
- [ ] 90%+ asset search success rate

### Quality Targets
- **Visual relevance:** 80%+ CLIP similarity score (image matches script context)
- **Content safety:** Zero unsafe assets shipped
- **Render success rate:** 95%+ first-attempt success
- **Output quality:** No visible compression artifacts at 2800 kbps

---

## Next Steps

1. **Create tool files:**
   - `src/tools/image_search_tools.py`
   - `src/tools/content_validation_tools.py`
   - `src/tools/ffmpeg_tools.py`

2. **Implement agents:**
   - `src/visual_asset_agent.py`
   - `src/composition_agent.py`
   - `src/render_agent.py`

3. **Write tests:**
   - `tests/test_visual_asset_agent.py`
   - `tests/test_composition_agent.py`
   - `tests/test_render_agent.py`

4. **Create examples:**
   - `examples/visual_asset_example.py`
   - `examples/full_render_example.py`

5. **Update integration docs:**
   - Add visual/composition/render steps to `docs/pipeline-integration.md`

---

## References

- Audio Agent: `docs/audio-agent.md`
- Pipeline Integration: `docs/pipeline-integration.md`
- Market Research Artifacts: `docs/market-research-handoff-artifacts.md`
- FFmpeg Documentation: https://ffmpeg.org/documentation.html
- Ken Burns Effect with FFmpeg: https://trac.ffmpeg.org/wiki/Zoompan
