"""Text-to-Speech and audio tools for the audio agent.

This module provides tools for:
- Generating voiceover using TTS APIs (ElevenLabs)
- Audio file management and processing
- Audio mixing and normalization
- Default background music application
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import ELEVENLABS_API_KEY, AUDIO_SAMPLE_RATE, DEFAULT_MUSIC_PATH


class TTSError(Exception):
    """Exception raised for TTS-related errors."""
    pass


class AudioMixingError(Exception):
    """Exception raised for audio mixing errors."""
    pass


def _get_retry_session() -> requests.Session:
    """Create requests session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def generate_voiceover(
    text: str,
    voice_id: str = "JBFqnCBsd6RMkjVDRZzb",  # Default: George (ElevenLabs)
    output_path: Optional[Path] = None,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> Tuple[Path, Dict[str, Any]]:
    """Generate voiceover audio from text using ElevenLabs TTS API.
    
    Args:
        text: The text to convert to speech.
        voice_id: ElevenLabs voice ID. Default is Rachel.
        output_path: Optional output file path. If None, generates temp path.
        stability: Voice stability (0.0-1.0). Lower = more expressive.
        similarity_boost: Voice similarity (0.0-1.0). Higher = closer to original.
    
    Returns:
        Tuple of (audio_file_path, metadata_dict) containing:
            - Path: Path to the generated audio file
            - Dict: Metadata including duration, characters, voice_id
    
    Raises:
        TTSError: If API key is missing or API call fails.
    
    Example:
        >>> path, meta = generate_voiceover("Hello world!", voice_id="rachel")
        >>> print(f"Generated {meta['duration_s']}s audio at {path}")
    """
    if not ELEVENLABS_API_KEY:
        raise TTSError("ELEVENLABS_API_KEY not configured in environment")
    
    if not text or not text.strip():
        raise TTSError("Text cannot be empty")
    
    # Generate output path if not provided
    if output_path is None:
        timestamp = int(time.time() * 1000)
        output_path = Path(f"vo_segment_{timestamp}.mp3")
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # ElevenLabs API endpoint
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",  # Free tier compatible model
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
        },
    }
    
    try:
        session = _get_retry_session()
        response = session.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Write audio data to file
        with open(output_path, "wb") as f:
            f.write(response.content)
        
        # Get file size for metadata
        file_size = output_path.stat().st_size
        
        # Estimate duration (rough estimate: ~24KB per second for MP3)
        estimated_duration = file_size / 24000
        
        metadata = {
            "voice_id": voice_id,
            "character_count": len(text),
            "file_size_bytes": file_size,
            "estimated_duration_s": round(estimated_duration, 2),
            "stability": stability,
            "similarity_boost": similarity_boost,
        }
        
        return output_path, metadata
    
    except requests.exceptions.RequestException as e:
        raise TTSError(f"ElevenLabs API request failed: {e}")
    except OSError as e:
        raise TTSError(f"Failed to write audio file: {e}")


def get_available_voices() -> List[Dict[str, Any]]:
    """Retrieve list of available voices from ElevenLabs.
    
    Returns:
        List of voice dictionaries with id, name, and metadata.
    
    Raises:
        TTSError: If API key is missing or API call fails.
    
    Example:
        >>> voices = get_available_voices()
        >>> for v in voices:
        ...     print(f"{v['name']}: {v['voice_id']}")
    """
    if not ELEVENLABS_API_KEY:
        raise TTSError("ELEVENLABS_API_KEY not configured")
    
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    
    try:
        session = _get_retry_session()
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        voices = data.get("voices", [])
        
        return [
            {
                "voice_id": v.get("voice_id"),
                "name": v.get("name"),
                "category": v.get("category"),
                "labels": v.get("labels", {}),
            }
            for v in voices
        ]
    
    except requests.exceptions.RequestException as e:
        raise TTSError(f"Failed to retrieve voices: {e}")


def apply_background_music(
    voiceover_path: Path,
    music_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    music_volume_db: float = -18.0,
) -> Path:
    """Mix voiceover with background music.
    
    This is a placeholder function that will be implemented with audio
    processing libraries (pydub or ffmpeg) in Phase 2.
    
    Args:
        voiceover_path: Path to voiceover audio file.
        music_path: Path to background music. Uses default if None.
        output_path: Output path for mixed audio.
        music_volume_db: Music volume adjustment in dB (negative = quieter).
    
    Returns:
        Path to the mixed audio file.
    
    Raises:
        AudioMixingError: If mixing fails or files not found.
    
    Note:
        Current implementation returns voiceover_path unchanged.
        Phase 2 will implement actual mixing with pydub/ffmpeg.
    """
    if not voiceover_path.exists():
        raise AudioMixingError(f"Voiceover file not found: {voiceover_path}")
    
    if music_path is None:
        music_path = DEFAULT_MUSIC_PATH
    
    # Phase 1: Return voiceover unchanged (no mixing yet)
    # TODO: Implement actual audio mixing in Phase 2
    #   1. Load voiceover and music tracks
    #   2. Adjust music volume by music_volume_db
    #   3. Mix tracks (voiceover + music)
    #   4. Normalize output
    #   5. Export to output_path
    
    return voiceover_path


def mix_audio_tracks(
    tracks_config: List[Dict[str, Any]],
    output_path: Path,
    total_duration_s: Optional[float] = None,
) -> Path:
    """Mix multiple audio tracks into a single timeline.
    
    Phase 2 placeholder for advanced multi-track mixing.
    
    Args:
        tracks_config: List of track configurations, each with:
            - file: Path to audio file
            - type: "voiceover", "sfx", "music"
            - t_start_s: Start time in seconds
            - volume_db: Volume adjustment in dB
        output_path: Output path for mixed audio.
        total_duration_s: Total duration of output audio.
    
    Returns:
        Path to the mixed audio file.
    
    Raises:
        AudioMixingError: If mixing fails.
    
    Example:
        >>> config = [
        ...     {"file": "vo.mp3", "type": "voiceover", "t_start_s": 0, "volume_db": 0},
        ...     {"file": "music.mp3", "type": "music", "t_start_s": 0, "volume_db": -18},
        ... ]
        >>> mix_audio_tracks(config, Path("output.wav"))
    """
    # Phase 1: Placeholder
    # TODO: Implement multi-track mixing in Phase 2
    #   1. Create silent base track of total_duration_s
    #   2. For each track:
    #       - Load audio file
    #       - Apply volume_db adjustment
    #       - Overlay at t_start_s
    #   3. Normalize final mix
    #   4. Export to output_path
    
    raise NotImplementedError("Multi-track mixing will be implemented in Phase 2")


def normalize_audio(
    input_path: Path,
    output_path: Optional[Path] = None,
    target_lufs: float = -16.0,
) -> Path:
    """Normalize audio to target loudness (LUFS).
    
    Phase 2 placeholder for audio normalization.
    
    Args:
        input_path: Input audio file.
        output_path: Output path. If None, overwrites input.
        target_lufs: Target loudness in LUFS (default: -16.0).
    
    Returns:
        Path to normalized audio file.
    
    Raises:
        AudioMixingError: If normalization fails.
    """
    # Phase 1: Return input unchanged
    # TODO: Implement normalization with pyloudnorm in Phase 2
    
    if not input_path.exists():
        raise AudioMixingError(f"Audio file not found: {input_path}")
    
    return input_path


# Voice presets for common use cases.
#
# These IDs are intentionally pinned for determinism and to match
# the pipeline docs + tests.
VOICE_PRESETS = {
    "narrator": "JBFqnCBsd6RMkjVDRZzb",  # George - Warm, Captivating Storyteller
    "energetic": "TX3LPaxmHKxFdv7VOQHJ",  # Liam - Energetic, Social Media Creator
    "calm": "EXAVITQu4vr4xnSDxMaL",       # Sarah - Mature, Reassuring, Confident
    "authoritative": "IKne3meq5aSn9XLyUdCD",  # Charlie - Deep, Confident, Energetic
}


def get_voice_id(voice_name: str) -> str:
    """Get ElevenLabs voice ID from preset name or return as-is if already an ID.
    
    Args:
        voice_name: Preset name (e.g., "narrator") or ElevenLabs voice ID.
    
    Returns:
        ElevenLabs voice ID string.
    
    Example:
        >>> get_voice_id("narrator")
        '21m00Tcm4TlvDq8ikWAM'
        >>> get_voice_id("custom_id_123")
        'custom_id_123'
    """
    return VOICE_PRESETS.get(voice_name, voice_name)
