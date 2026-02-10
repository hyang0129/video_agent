"""Audio generation agent for video production pipeline.

This agent is responsible for:
1. Converting script voiceover lines to speech using TTS
2. Generating audio timeline with proper timing
3. Applying background music (Phase 1: default placeholder)
4. Exporting audio master file and timeline manifest

Follows multi-agent best practices:
- Clear input/output contracts (VideoPlan → AudioTimeline)
- Deterministic processing (same input → same output)
- Structured artifact generation
- Error handling and validation
- Separation of concerns (delegates to tools)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import wave
import uuid

from .tools.tts_tools import (
    generate_voiceover,
    get_voice_id,
    apply_background_music,
    TTSError,
    AudioMixingError,
)
from .config import (
    RESULTS_DIR,
    DEFAULT_MUSIC_PATH,
    AUDIO_SAMPLE_RATE,
)
from .artifacts.io import ensure_run_dir


class AudioGenerationError(Exception):
    """Exception raised for audio generation failures."""
    pass


class AudioGenerationAgent:
    """Agent for generating audio timeline from video plan.
    
    This agent follows the multi-agent pattern established in the pipeline:
    - Accepts structured input (VideoPlan)
    - Produces structured output (AudioTimeline + audio files)
    - Handles errors gracefully
    - Logs progress and decisions
    
    Attributes:
        output_dir: Directory for saving audio artifacts.
        voice_id: ElevenLabs voice ID for TTS.
        music_volume_db: Background music volume in dB.
    
    Example:
        >>> agent = AudioGenerationAgent(output_dir=Path("results/run_001"))
        >>> timeline = agent.generate_audio_timeline(video_plan)
        >>> print(f"Generated audio: {timeline['audio_file_path']}")
    """
    
    def __init__(
        self,
        output_dir: Optional[Path] = None,
        voice_id: str = "narrator",
        music_volume_db: float = -18.0,
    ):
        """Initialize audio generation agent.
        
        Args:
            output_dir: Directory for output files. Creates temp dir if None.
            voice_id: Voice preset name or ElevenLabs voice ID.
            music_volume_db: Background music volume adjustment in dB.
        """
        self.output_dir = output_dir or RESULTS_DIR / f"audio_{uuid.uuid4().hex[:6]}"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.voice_id = get_voice_id(voice_id)
        self.music_volume_db = music_volume_db
        
        # Create subdirectories
        self.audio_segments_dir = self.output_dir / "audio_segments"
        self.audio_segments_dir.mkdir(exist_ok=True)
    
    def generate_audio_timeline(
        self,
        video_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate complete audio timeline from video plan.
        
        This is the main entry point for the audio agent. It:
        1. Validates the video plan structure
        2. Extracts voiceover requirements from scenes
        3. Generates TTS audio for each segment
        4. Constructs audio timeline manifest
        5. Applies background music (Phase 1: placeholder)
        
        Args:
            video_plan: VideoPlan dictionary from video planner.
        
        Returns:
            AudioTimeline dictionary with structure:
            {
                "schema_version": "1.0.0",
                "created_at": "2026-02-01T...",
                "audio_timeline_id": "at_...",
                "video_plan_ref": "vp_...",
                "audio_file_path": "results/.../audio_master.mp3",
                "duration_seconds": 45.0,
                "tracks": [
                    {
                        "type": "voiceover",
                        "file": "audio_segments/vo_001.mp3",
                        "t_start_s": 0.0,
                        "t_end_s": 6.43,
                        "volume_db": 0,
                        "metadata": {...}
                    },
                    ...
                ]
            }
        
        Raises:
            AudioGenerationError: If video plan is invalid or TTS fails.
        """
        # Validate input
        self._validate_video_plan(video_plan)
        
        # Extract scenes
        scenes = video_plan.get("scenes", [])
        if not scenes:
            raise AudioGenerationError("VideoPlan contains no scenes")
        
        # Generate timeline ID
        timeline_id = f"at_{uuid.uuid4().hex[:8]}"
        
        # Get voice configuration from video plan
        audio_config = video_plan.get("audio", {})
        tts_config = audio_config.get("tts", {})
        voice_override = tts_config.get("voice")
        
        if voice_override:
            voice_id = get_voice_id(voice_override)
        else:
            voice_id = self.voice_id

        silent_mode = str(voice_id).strip().lower() in {"silent", "none", "off"}
        
        # Generate voiceover tracks
        tracks = []
        total_duration = 0.0
        
        for scene in scenes:
            vo_line = scene.get("vo_line", "").strip()
            if not vo_line:
                continue
            
            scene_id = scene.get("scene_id", "unknown")
            t_start = float(scene.get("t_start_s", 0))
            t_end = float(scene.get("t_end_s", 0))
            scene_duration = t_end - t_start
            
            if scene_duration <= 0:
                continue
            
            try:
                # Generate voiceover for this scene
                if silent_mode:
                    segment_path = self.audio_segments_dir / f"vo_{scene_id}.wav"
                    audio_path, metadata = _write_silent_wav(
                        output_path=segment_path,
                        duration_s=scene_duration,
                        sample_rate=AUDIO_SAMPLE_RATE,
                    )
                else:
                    segment_path = self.audio_segments_dir / f"vo_{scene_id}.mp3"
                    audio_path, metadata = generate_voiceover(
                        text=vo_line,
                        voice_id=voice_id,
                        output_path=segment_path,
                    )
                
                # Add track to timeline
                tracks.append({
                    "type": "voiceover",
                    "file": str(audio_path.relative_to(self.output_dir)),
                    "scene_id": scene_id,
                    "t_start_s": t_start,
                    "t_end_s": t_end,
                    "volume_db": 0,
                    "metadata": metadata,
                })
                
                total_duration = max(total_duration, t_end)
            
            except TTSError as e:
                raise AudioGenerationError(
                    f"Failed to generate voiceover for scene {scene_id}: {e}"
                )
        
        if not tracks:
            raise AudioGenerationError("No voiceover tracks generated")
        
        # Add background music track (Phase 1: reference only, no mixing)
        if DEFAULT_MUSIC_PATH.exists():
            tracks.append({
                "type": "music",
                "file": str(DEFAULT_MUSIC_PATH.relative_to(RESULTS_DIR.parent)),
                "t_start_s": 0.0,
                "t_end_s": total_duration,
                "volume_db": self.music_volume_db,
                "metadata": {
                    "comment": "Placeholder track: Creative Commons licensed",
                    "note": "Phase 2 will implement actual mixing",
                },
            })
        
        # Construct audio timeline manifest
        audio_timeline = {
            "schema_version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "audio_timeline_id": timeline_id,
            "video_plan_ref": video_plan.get("video_plan_id", "unknown"),
            "audio_file_path": None,  # Phase 1: no master file yet
            "duration_seconds": round(total_duration, 2),
            "voice_id": voice_id,
            "tracks": tracks,
            "processing_notes": [
                "Phase 1: Individual voiceover segments generated",
                "Phase 2 will add: audio mixing, normalization, master file export",
            ],
        }
        
        # Save timeline manifest
        timeline_path = self.output_dir / "audio_timeline.json"
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump(audio_timeline, f, indent=2, ensure_ascii=False)
        
        return audio_timeline

    def _validate_video_plan(self, video_plan: Dict[str, Any]) -> None:
        """Validate video plan structure.

        Args:
            video_plan: VideoPlan dictionary to validate.

        Raises:
            AudioGenerationError: If required fields are missing or invalid.
        """
        if not isinstance(video_plan, dict):
            raise AudioGenerationError("video_plan must be a dictionary")

        if "scenes" not in video_plan:
            raise AudioGenerationError("video_plan missing 'scenes' field")

        scenes = video_plan.get("scenes")
        if not isinstance(scenes, list):
            raise AudioGenerationError("video_plan.scenes must be a list")

        # Validate each scene has required fields
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise AudioGenerationError(f"Scene {i} is not a dictionary")

            required_fields = ["t_start_s", "t_end_s", "vo_line"]
            for field in required_fields:
                if field not in scene:
                    raise AudioGenerationError(f"Scene {i} missing required field: {field}")

    def get_audio_stats(self, audio_timeline: Dict[str, Any]) -> Dict[str, Any]:
        """Get statistics about generated audio timeline.

        Args:
            audio_timeline: AudioTimeline dictionary.

        Returns:
            Dictionary with basic statistics.
        """
        tracks = audio_timeline.get("tracks", [])
        vo_tracks = [t for t in tracks if t.get("type") == "voiceover"]

        total_chars = sum(t.get("metadata", {}).get("character_count", 0) for t in vo_tracks)

        duration = audio_timeline.get("duration_seconds", 0)
        avg_chars_per_sec = total_chars / duration if duration > 0 else 0

        return {
            "total_duration_s": duration,
            "voiceover_tracks": len(vo_tracks),
            "music_tracks": len([t for t in tracks if t.get("type") == "music"]),
            "total_characters": total_chars,
            "avg_chars_per_second": round(avg_chars_per_sec, 2),
        }


def _write_silent_wav(
    output_path: Path,
    duration_s: float,
    sample_rate: int,
    channels: int = 1,
    sample_width_bytes: int = 2,
) -> tuple[Path, Dict[str, Any]]:
    """Write a silent PCM WAV file.

    Args:
        output_path: Where to write the WAV.
        duration_s: Duration in seconds.
        sample_rate: Sample rate (Hz).
        channels: Number of channels.
        sample_width_bytes: Sample width in bytes (2 == 16-bit).

    Returns:
        Tuple of (path, metadata).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dur = max(0.0, float(duration_s))
    sr = max(8000, int(sample_rate))
    ch = max(1, int(channels))
    sw = 2 if int(sample_width_bytes) != 1 else 1

    frame_count = int(round(dur * sr))
    silence_frame = (b"\x00" * sw) * ch

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(sr)

        # Write in chunks to avoid large memory allocations.
        chunk_frames = 4096
        remaining = frame_count
        while remaining > 0:
            n = min(chunk_frames, remaining)
            wf.writeframes(silence_frame * n)
            remaining -= n

    metadata = {
        "voice_id": "silent",
        "character_count": 0,
        "file_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "estimated_duration_s": round(dur, 2),
        "note": "Silent placeholder audio (offline mode)",
    }

    return output_path, metadata


def create_audio_agent(
    output_dir: Optional[Path] = None,
    voice: str = "narrator",
    music_volume_db: float = -18.0,
) -> AudioGenerationAgent:
    """Factory function for creating audio generation agent.
    
    Follows the factory pattern established in other agents.
    
    Args:
        output_dir: Output directory for audio files.
        voice: Voice preset name or ElevenLabs voice ID.
        music_volume_db: Background music volume in dB.
    
    Returns:
        Configured AudioGenerationAgent instance.
    
    Example:
        >>> agent = create_audio_agent(
        ...     output_dir=Path("results/run_001"),
        ...     voice="energetic",
        ... )
        >>> timeline = agent.generate_audio_timeline(video_plan)
    """
    return AudioGenerationAgent(
        output_dir=output_dir,
        voice_id=voice,
        music_volume_db=music_volume_db,
    )
