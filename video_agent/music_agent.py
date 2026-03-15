"""Music selection agent for video production pipeline.

Selects background music for a video given its AudioTimeline and optionally
other pipeline artifacts. Each selection method is independently invokable.

All extended selection methods (select_by_tone, select_by_script,
select_by_images) are currently stubs that return the default music.
They define the public API surface for future implementation.

Input:  AudioTimeline  (+ optional VideoPlan / ScriptPackage / VisualManifest)
Output: MusicSelection artifact
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import (
    ASSETS_DIR,
    BACKGROUND_MUSIC_VOLUME_DB,
    DEFAULT_MUSIC_PATH,
)


class MusicAgentError(Exception):
    """Raised when music selection fails."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _probe_duration_seconds(path: Path) -> Optional[float]:
    """Return ffprobe-measured duration, or None if unavailable."""
    from video_agent.config import FFPROBE_PATH
    ffprobe = shutil.which(FFPROBE_PATH)
    if not ffprobe or not path.exists() or path.stat().st_size == 0:
        return None
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        val = float((proc.stdout or "").strip())
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


class MusicAgent:
    """Selects background music for a video pipeline run.

    All selection methods return a MusicSelection artifact:
    {
        "schema_version": "1.0.0",
        "music_selection_id": "ms_...",
        "created_at": "...",
        "selection_method": "default" | "tone" | "script" | "images",
        "music_file_path": "<absolute path to .mp3>",
        "title": "...",
        "artist": null,
        "license": "...",
        "volume_db": -18.0,
        "loop": true,
        "target_duration_s": 45.0,
        "source_duration_s": 120.0,
    }

    Extended APIs (select_by_tone, select_by_script, select_by_images) are
    stubs — they accept the relevant artifact but currently delegate to the
    default selection.  Replace the stub body to activate smart selection.

    Example:
        >>> agent = create_music_agent()
        >>> selection = agent.select_music(audio_timeline)
        >>> print(selection["music_file_path"])
    """

    def __init__(
        self,
        default_music_path: Optional[Path] = None,
        volume_db: float = BACKGROUND_MUSIC_VOLUME_DB,
    ):
        self.default_music_path = Path(default_music_path) if default_music_path else DEFAULT_MUSIC_PATH
        self.volume_db = volume_db

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def select_music(
        self,
        audio_timeline: Dict[str, Any],
        *,
        video_plan: Optional[Dict[str, Any]] = None,
        script_package: Optional[Dict[str, Any]] = None,
        visual_manifest: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Select background music for a video.

        All optional kwargs are accepted for forward-compatibility with
        future smart-selection implementations. Currently ignored.

        Args:
            audio_timeline: AudioTimeline artifact (provides target duration).
            video_plan: Optional VideoPlan (unused — reserved for future use).
            script_package: Optional ScriptPackage (unused — reserved).
            visual_manifest: Optional VisualManifest (unused — reserved).

        Returns:
            MusicSelection artifact dict.

        Raises:
            MusicAgentError: If the default music file is missing.
        """
        target_duration_s = float(audio_timeline.get("duration_seconds") or 0.0)
        return self._default_selection(target_duration_s=target_duration_s)

    # ------------------------------------------------------------------
    # Extended stub APIs
    # ------------------------------------------------------------------

    def select_by_tone(
        self,
        tone: str,
        audio_timeline: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Select music matching a requested tone (e.g. "dramatic", "upbeat").

        STUB: Returns default music regardless of tone.
        Future implementation: query a music library by mood/genre tags.

        Args:
            tone: Desired tone description string.
            audio_timeline: AudioTimeline artifact.

        Returns:
            MusicSelection artifact.
        """
        return self.select_music(audio_timeline)

    def select_by_script(
        self,
        script_package: Dict[str, Any],
        audio_timeline: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Select music based on script sentiment and topic.

        STUB: Returns default music regardless of script content.
        Future implementation: analyse script_package sentiment with an LLM,
        then select a music track that matches the inferred mood.

        Args:
            script_package: ScriptPackage artifact.
            audio_timeline: AudioTimeline artifact.

        Returns:
            MusicSelection artifact.
        """
        return self.select_music(audio_timeline, script_package=script_package)

    def select_by_images(
        self,
        visual_manifest: Dict[str, Any],
        audio_timeline: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Select music based on visual tone of the selected images.

        STUB: Returns default music regardless of visual content.
        Future implementation: use CLIP embeddings or image tags from
        VisualManifest to infer visual tone, then pick a music track.

        Args:
            visual_manifest: VisualManifest artifact.
            audio_timeline: AudioTimeline artifact.

        Returns:
            MusicSelection artifact.
        """
        return self.select_music(audio_timeline, visual_manifest=visual_manifest)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _default_selection(self, target_duration_s: float) -> Dict[str, Any]:
        """Build a MusicSelection using the configured default music file."""
        path = self.default_music_path
        if not path.exists():
            raise MusicAgentError(
                f"Default music file not found: {path}\n"
                f"Place an MP3 at that path to enable background music."
            )

        source_duration_s = _probe_duration_seconds(path)

        return {
            "schema_version": "1.0.0",
            "music_selection_id": f"ms_{uuid.uuid4().hex[:8]}",
            "created_at": _utc_now_iso(),
            "selection_method": "default",
            "music_file_path": str(path.resolve()),
            "title": "Default Background Music",
            "artist": None,
            "license": f"see {ASSETS_DIR / 'music' / 'LICENSE'}",
            "volume_db": self.volume_db,
            "loop": True,
            "target_duration_s": round(target_duration_s, 2),
            "source_duration_s": round(source_duration_s, 2) if source_duration_s is not None else None,
        }


def create_music_agent(
    default_music_path: Optional[Path] = None,
    volume_db: float = BACKGROUND_MUSIC_VOLUME_DB,
) -> MusicAgent:
    """Factory for MusicAgent.

    Args:
        default_music_path: Override path to default music file.
        volume_db: Background music volume relative to voiceover (dB).

    Returns:
        Configured MusicAgent.
    """
    return MusicAgent(default_music_path=default_music_path, volume_db=volume_db)
