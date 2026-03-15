"""Music selection agent for video production pipeline.

Uses an LLM to analyse the script and produce a tailored ACE-Step music
description, then generates background music via the ACE-Step v1.5 model.
Uses the bundled default_music.mp3 only when ``MUSIC_BACKEND=default``.
When ``MUSIC_BACKEND=acestep``, failures raise ``MusicAgentError`` rather
than silently falling back.

Input:  AudioTimeline  (+ optional VideoPlan / ScriptPackage / VisualManifest)
Output: MusicSelection artifact
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import (
    ACESTEP_BASE_URL,
    ASSETS_DIR,
    BACKGROUND_MUSIC_VOLUME_DB,
    DEFAULT_MUSIC_PATH,
    MUSIC_BACKEND,
    RESULTS_DIR,
    make_llm,
)

logger = logging.getLogger(__name__)


class MusicAgentError(Exception):
    """Raised when music selection fails."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _probe_duration_seconds(path: Path) -> Optional[float]:
    """Return ffprobe-measured duration, or None if unavailable."""
    ffprobe = shutil.which("ffprobe")
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


# ------------------------------------------------------------------
# LLM-based music description prompt
# ------------------------------------------------------------------

_MUSIC_PROMPT = """\
You are a music director for short-form vertical video content (15-60 second \
YouTube Shorts / TikTok / Reels).

Given the script below, produce a JSON object describing the ideal \
*instrumental* background music track. The music must:
- Support the voiceover without competing with it (background role).
- Match the emotional arc and energy of the content.
- Be appropriate for the short-form format: immediate impact, no long intros.

Script metadata:
- Topic: {topic}
- Tone: {tone}
- Format: {video_format}
- Duration: {duration}s

Full voiceover:
{voiceover}

Respond with ONLY a JSON object (no markdown fences, no extra text):
{{
  "description": "<ACE-Step caption: comma-separated style tags describing \
instruments, mood, energy, genre — 10-25 words>",
  "bpm": <integer beats per minute, 60-140>,
  "key": <musical key string like "C Major" or "D minor", or null>,
  "guidance_scale": <float 5.0-10.0, higher = stricter adherence to description>
}}"""


def _build_script_summary(script_package: Dict[str, Any]) -> Dict[str, str]:
    """Extract the fields needed for the music prompt from a ScriptPackage."""
    metadata = script_package.get("metadata", {})
    script = script_package.get("script", {})
    return {
        "topic": (
            metadata.get("topic_id")
            or script_package.get("topic_id")
            or "unknown"
        ),
        "tone": metadata.get("tone", "neutral"),
        "video_format": metadata.get("format", "short-form"),
        "voiceover": script.get("voiceover", ""),
    }


def _llm_describe_music(
    script_package: Dict[str, Any],
    duration_s: float,
) -> Dict[str, Any]:
    """Ask the LLM to describe ideal background music for the script.

    Returns a dict with keys: description, bpm, key, guidance_scale.
    Raises on LLM or parse failure (caller handles fallback).
    """
    summary = _build_script_summary(script_package)
    prompt_text = _MUSIC_PROMPT.format(
        topic=summary["topic"],
        tone=summary["tone"],
        video_format=summary["video_format"],
        duration=int(duration_s),
        voiceover=summary["voiceover"][:1500],
    )

    llm = make_llm(temperature=0.4)
    response = llm.invoke(prompt_text)
    raw = response.content.strip()

    # Strip markdown fences if the LLM wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    result = json.loads(raw)

    # Validate required fields
    if not isinstance(result.get("description"), str) or not result["description"]:
        raise ValueError("LLM response missing 'description'")

    return {
        "description": result["description"],
        "bpm": int(result["bpm"]) if result.get("bpm") else None,
        "key": result.get("key"),
        "guidance_scale": float(result.get("guidance_scale", 7.0)),
    }


class MusicAgent:
    """Generates background music for a video pipeline run.

    When backend is ``acestep``, uses an LLM to analyse the script and
    craft a tailored ACE-Step music description, then generates the track.
    Falls back to the bundled default MP3 if the server is down.

    Example:
        >>> agent = create_music_agent(output_dir=Path("results/run_001"))
        >>> selection = agent.select_music(audio_timeline, script_package=sp)
        >>> print(selection["music_file_path"])
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        default_music_path: Optional[Path] = None,
        volume_db: float = BACKGROUND_MUSIC_VOLUME_DB,
        backend: str = MUSIC_BACKEND,
        acestep_url: str = ACESTEP_BASE_URL,
    ):
        self.output_dir = output_dir or RESULTS_DIR
        self.default_music_path = (
            Path(default_music_path) if default_music_path else DEFAULT_MUSIC_PATH
        )
        self.volume_db = volume_db
        self.backend = backend
        self.acestep_url = acestep_url

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
        """Select or generate background music for a video.

        Args:
            audio_timeline: AudioTimeline artifact (provides target duration).
            video_plan: Optional VideoPlan (unused — reserved).
            script_package: Optional ScriptPackage (fed to the LLM for analysis).
            visual_manifest: Optional VisualManifest (unused — reserved).

        Returns:
            MusicSelection artifact dict.
        """
        target_duration_s = float(audio_timeline.get("duration_seconds") or 0.0)

        if self.backend == "acestep":
            return self._acestep_generation(
                target_duration_s=target_duration_s,
                script_package=script_package,
            )

        return self._default_selection(target_duration_s=target_duration_s)

    # ------------------------------------------------------------------
    # ACE-Step generation
    # ------------------------------------------------------------------

    def _acestep_generation(
        self,
        target_duration_s: float,
        script_package: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate music via ACE-Step. Raises MusicAgentError on failure."""
        try:
            from ace_step.client import AceStepClient
        except ImportError:
            raise MusicAgentError(
                "ace_step package not installed. "
                "Install it or set MUSIC_BACKEND=default."
            )

        client = AceStepClient(base_url=self.acestep_url)

        if not client.health_sync():
            raise MusicAgentError(
                f"ACE-Step server unreachable at {self.acestep_url}. "
                f"Start the server or set MUSIC_BACKEND=default."
            )

        duration = max(10, min(600, int(target_duration_s))) if target_duration_s > 0 else 30

        # Use LLM to craft a music description from the script
        music_spec = self._describe_music(script_package, duration)

        logger.info(
            "[INFO] Generating music: description='%s', bpm=%s, "
            "key=%s, duration=%ds",
            music_spec["description"][:80],
            music_spec["bpm"],
            music_spec["key"],
            duration,
        )

        result = client.generate_sync(
            description=music_spec["description"],
            duration=duration,
            instrumental=True,
            bpm=music_spec["bpm"],
            key=music_spec["key"],
            guidance_scale=music_spec["guidance_scale"],
            audio_format="mp3",
        )

        music_path = Path(self.output_dir) / "music_generated.mp3"
        result.save_to_file(music_path)
        source_duration_s = _probe_duration_seconds(music_path)

        logger.info(
            "[OK] Generated %s (%.1fs, task=%s)",
            music_path.name, result.duration_s, result.task_id,
        )

        return {
            "schema_version": "1.0.0",
            "music_selection_id": f"ms_{uuid.uuid4().hex[:8]}",
            "created_at": _utc_now_iso(),
            "selection_method": "generated",
            "music_file_path": str(music_path.resolve()),
            "title": "ACE-Step LLM-directed",
            "artist": None,
            "license": "AI-generated (ACE-Step v1.5)",
            "volume_db": self.volume_db,
            "loop": False,
            "target_duration_s": round(target_duration_s, 2),
            "source_duration_s": (
                round(source_duration_s, 2)
                if source_duration_s
                else round(result.duration_s, 2)
            ),
            "music_description": music_spec["description"],
            "music_bpm": music_spec["bpm"],
            "music_key": music_spec["key"],
            "task_id": result.task_id,
        }

    # ------------------------------------------------------------------
    # LLM music description
    # ------------------------------------------------------------------

    def _describe_music(
        self,
        script_package: Optional[Dict[str, Any]],
        duration_s: float,
    ) -> Dict[str, Any]:
        """Use the LLM to describe ideal music. Falls back to preset only
        when no script_package is provided (not on LLM errors).
        """
        if script_package:
            spec = _llm_describe_music(script_package, duration_s)
            logger.info("[LLM] Music description: %s", spec["description"])
            return spec

        # No script provided — use mood-matching preset
        from ace_step.mood import match_preset

        preset = match_preset("documentary")
        logger.info("[INFO] No script_package provided, using preset: %s", preset.description)
        return {
            "description": preset.description,
            "bpm": preset.bpm,
            "key": preset.key,
            "guidance_scale": preset.guidance_scale,
        }

    # ------------------------------------------------------------------
    # Default fallback
    # ------------------------------------------------------------------

    def _default_selection(
        self,
        target_duration_s: float,
        degraded_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a MusicSelection using the configured default music file."""
        path = self.default_music_path
        if not path.exists():
            raise MusicAgentError(
                f"Default music file not found: {path}\n"
                f"Place an MP3 at that path to enable background music."
            )

        source_duration_s = _probe_duration_seconds(path)

        selection: Dict[str, Any] = {
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
            "source_duration_s": (
                round(source_duration_s, 2) if source_duration_s is not None else None
            ),
        }
        if degraded_reason:
            selection["degraded_reason"] = degraded_reason
        return selection


def create_music_agent(
    output_dir: Optional[Path] = None,
    default_music_path: Optional[Path] = None,
    volume_db: float = BACKGROUND_MUSIC_VOLUME_DB,
    backend: str = MUSIC_BACKEND,
    acestep_url: str = ACESTEP_BASE_URL,
) -> MusicAgent:
    """Factory for MusicAgent.

    Args:
        output_dir: Directory for generated music files.
        default_music_path: Override path to default music file.
        volume_db: Background music volume relative to voiceover (dB).
        backend: "acestep" or "default".
        acestep_url: ACE-Step server URL.

    Returns:
        Configured MusicAgent.
    """
    return MusicAgent(
        output_dir=output_dir,
        default_music_path=default_music_path,
        volume_db=volume_db,
        backend=backend,
        acestep_url=acestep_url,
    )
