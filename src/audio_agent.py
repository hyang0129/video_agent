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
import shutil
import subprocess
import wave
import uuid

from .artifacts.io import write_json as _write_json


def _write_production_report(run_dir: Path, run_id: str, new_issues: List[Dict[str, Any]]) -> None:
    """Append new_issues to production_report.json, creating the file if absent."""
    report_path = run_dir / "production_report.json"
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
            all_issues: List[Dict[str, Any]] = list(existing.get("issues") or []) + new_issues
        except Exception:
            all_issues = new_issues
    else:
        all_issues = new_issues
    _write_json(report_path, {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "issues": all_issues,
        "degraded_scene_count": sum(1 for i in all_issues if i.get("status") == "degraded"),
    })

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


def _probe_audio_duration_seconds(audio_path: Path) -> Optional[float]:
    """Probe audio file duration with ffprobe when available.

    Args:
        audio_path: Path to an audio file.

    Returns:
        Duration in seconds when detectable, else None.
    """
    path = Path(audio_path)
    if not path.exists() or path.stat().st_size <= 0:
        return None

    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return None

    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None

    raw = (proc.stdout or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None

    if value <= 0:
        return None
    return value


def _resolve_segment_duration_seconds(
    audio_path: Path,
    metadata: Dict[str, Any],
    fallback_duration_s: float,
) -> float:
    """Resolve best-available segment duration for timeline alignment.

    Priority:
    1) ffprobe measured duration
    2) metadata.estimated_duration_s
    3) fallback planned scene duration
    """
    probed = _probe_audio_duration_seconds(audio_path=audio_path)
    if isinstance(probed, (int, float)) and float(probed) > 0:
        return float(probed)

    estimated = metadata.get("estimated_duration_s") if isinstance(metadata, dict) else None
    if isinstance(estimated, (int, float)) and float(estimated) > 0:
        return float(estimated)

    return max(0.0, float(fallback_duration_s))


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
        scene_ids: Optional[List[str]] = None,
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
                "audio_file_path": "audio_master.mp3",
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
        current_time_s = 0.0
        production_issues: List[Dict[str, Any]] = []

        for scene in scenes:
            vo_line = scene.get("vo_line", "").strip()
            if not vo_line:
                continue

            scene_id = scene.get("scene_id", "unknown")

            # scene_ids filter: skip scenes not in the requested subset
            if scene_ids is not None and scene_id not in scene_ids:
                continue

            planned_start = float(scene.get("t_start_s", 0))
            planned_end = float(scene.get("t_end_s", 0))
            scene_duration = planned_end - planned_start

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

                actual_duration_s = _resolve_segment_duration_seconds(
                    audio_path=audio_path,
                    metadata=metadata,
                    fallback_duration_s=scene_duration,
                )

                # Duration overshoot: flag if TTS ran >20% longer than planned
                if actual_duration_s > scene_duration * 1.2:
                    word_count = len(vo_line.split())
                    target_words = max(1, int(word_count * (scene_duration / actual_duration_s)))
                    production_issues.append({
                        "agent": "AudioAgent",
                        "scene_id": scene_id,
                        "status": "degraded",
                        "issue": "vo_too_long",
                        "detail": f"TTS duration {actual_duration_s:.1f}s, target {scene_duration:.1f}s",
                        "suggestion": f"Shorten vo_line from {word_count} words to ~{target_words} words",
                        "revision_field": "vo_line",
                        "revision_possible": True,
                    })

            except TTSError as e:
                # Do not abort: write silent fallback and record the degraded issue
                print(f"[WARN] TTS failed for scene {scene_id}: {e}")
                production_issues.append({
                    "agent": "AudioAgent",
                    "scene_id": scene_id,
                    "status": "degraded",
                    "issue": "tts_failed",
                    "detail": str(e),
                    "suggestion": "Simplify vo_line: remove special characters, shorten to under 20 words",
                    "revision_field": "vo_line",
                    "revision_possible": True,
                })
                segment_path = self.audio_segments_dir / f"vo_{scene_id}.wav"
                audio_path, metadata = _write_silent_wav(
                    output_path=segment_path,
                    duration_s=scene_duration,
                    sample_rate=AUDIO_SAMPLE_RATE,
                )
                actual_duration_s = scene_duration

            track_start_s = round(current_time_s, 3)
            track_end_s = round(current_time_s + actual_duration_s, 3)

            tracks.append({
                "type": "voiceover",
                "file": str(audio_path.relative_to(self.output_dir)),
                "scene_id": scene_id,
                "t_start_s": track_start_s,
                "t_end_s": track_end_s,
                "volume_db": 0,
                "metadata": {
                    **metadata,
                    "planned_scene_duration_s": round(scene_duration, 3),
                    "timeline_duration_s": round(actual_duration_s, 3),
                },
            })
            current_time_s = track_end_s
        
        if not tracks:
            raise AudioGenerationError("No voiceover tracks generated")
        
        # Add background music track (Phase 1: reference only, no mixing)
        if DEFAULT_MUSIC_PATH.exists():
            tracks.append({
                "type": "music",
                "file": str(DEFAULT_MUSIC_PATH.relative_to(RESULTS_DIR.parent)),
                "t_start_s": 0.0,
                "t_end_s": round(current_time_s, 3),
                "volume_db": self.music_volume_db,
                "metadata": {
                    "comment": "Placeholder track: Creative Commons licensed",
                    "note": "Phase 2 will implement actual mixing",
                },
            })
        
        master_audio_relpath: Optional[str] = None
        master_audio_notes: List[str] = []
        master_audio_path = self._build_master_voiceover(tracks=tracks)
        if master_audio_path is not None:
            master_audio_relpath = str(master_audio_path.relative_to(self.output_dir)).replace("\\", "/")
            master_audio_notes.append("Phase 1 integration: created master voiceover track for render")
        else:
            master_audio_notes.append(
                "Phase 1 integration: master voiceover export unavailable; renderer will use segment fallback"
            )

        # Construct audio timeline manifest
        audio_timeline = {
            "schema_version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "audio_timeline_id": timeline_id,
            "video_plan_ref": video_plan.get("video_plan_id", "unknown"),
            "audio_file_path": master_audio_relpath,
            "duration_seconds": round(current_time_s, 2),
            "voice_id": voice_id,
            "tracks": tracks,
            "processing_notes": [
                "Phase 1: Individual voiceover segments generated",
                "Phase 2 will add: audio mixing, normalization, master file export",
                *master_audio_notes,
            ],
        }
        
        # Save timeline manifest
        timeline_path = self.output_dir / "audio_timeline.json"
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump(audio_timeline, f, indent=2, ensure_ascii=False)

        # Write production report (merges with any existing report from other agents)
        run_id = str(video_plan.get("video_plan_id") or "unknown")
        _write_production_report(self.output_dir, run_id, production_issues)
        if production_issues:
            print(f"[WARN] AudioAgent: {len(production_issues)} degraded scene(s) written to production_report.json")

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

    def _build_master_voiceover(self, tracks: List[Dict[str, Any]]) -> Optional[Path]:
        """Build a single master voiceover audio file from segment tracks.

        Args:
            tracks: AudioTimeline track entries.

        Returns:
            Path to master audio file when generated, else None.
        """
        voiceover_tracks = [
            t for t in tracks if isinstance(t, dict) and t.get("type") == "voiceover" and t.get("file")
        ]
        if not voiceover_tracks:
            return None

        segment_paths: List[Path] = []
        for track in sorted(voiceover_tracks, key=lambda t: float(t.get("t_start_s") or 0.0)):
            p = self.output_dir / str(track.get("file"))
            if p.exists() and p.stat().st_size > 0:
                segment_paths.append(p)

        if not segment_paths:
            return None

        if len(segment_paths) == 1:
            return segment_paths[0]

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return None

        concat_list_path = self.output_dir / "audio_segments" / "voiceover_concat.txt"
        concat_lines = ["file '" + str(path.resolve()).replace("'", "'\\''") + "'" for path in segment_paths]
        concat_list_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        out_path = self.output_dir / "audio_master.m4a"
        cmd = [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(out_path),
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return None
        if not out_path.exists() or out_path.stat().st_size <= 0:
            return None
        return out_path


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
