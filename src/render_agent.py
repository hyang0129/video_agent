"""Render agent for video production pipeline.

Phase 1 implements:
- A small render engine abstraction
- A pragmatic local FFmpeg engine that can produce a slideshow video
  from image clips and voiceover segments
- A dry-run engine for environments without FFmpeg (writes a placeholder)

This module intentionally does not aim to fully support every RenderSpecification
feature yet (e.g., advanced Ken Burns, text animations). It focuses on a
reliable MVP that follows the pipeline contracts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import shutil
import subprocess
import time
import uuid

from .artifacts.io import write_json


class RenderError(Exception):
    """Exception raised for render failures."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RenderEngine(ABC):
    """Abstract base class for render engines."""

    @abstractmethod
    def render(self, render_spec: Dict[str, Any], work_dir: Path) -> Path:
        """Execute render and return video file path."""


class DryRunRenderEngine(RenderEngine):
    """Engine that does not render; writes a small placeholder file."""

    def render(self, render_spec: Dict[str, Any], work_dir: Path) -> Path:
        out = work_dir / "final_video.mp4"
        out.write_bytes(b"")
        return out


class FfmpegRenderEngine(RenderEngine):
    """Local FFmpeg slideshow renderer."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin

    def render(self, render_spec: Dict[str, Any], work_dir: Path) -> Path:
        ffmpeg_path = shutil.which(self.ffmpeg_bin)
        if not ffmpeg_path:
            raise RenderError("FFmpeg not found on PATH; install ffmpeg or use DryRunRenderEngine")

        output_settings = render_spec.get("output_settings")
        if not isinstance(output_settings, dict):
            raise RenderError("RenderSpecification.output_settings missing")

        resolution = output_settings.get("resolution")
        if not isinstance(resolution, list) or len(resolution) != 2:
            raise RenderError("RenderSpecification.output_settings.resolution invalid")

        width, height = int(resolution[0]), int(resolution[1])
        fps = int(output_settings.get("fps") or 30)

        video_layer = _find_layer(render_spec, "video")
        clips = video_layer.get("clips") if isinstance(video_layer, dict) else None
        if not isinstance(clips, list) or not clips:
            raise RenderError("RenderSpecification has no video clips")

        audio_layer = _find_layer(render_spec, "audio")
        audio_tracks = audio_layer.get("tracks") if isinstance(audio_layer, dict) else []

        # Resolve inputs.
        video_inputs: List[Tuple[Path, float]] = []
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            src = str(clip.get("source_file") or "")
            dur = float(clip.get("duration_s") or 0.0)
            if not src or dur <= 0:
                continue
            video_inputs.append((work_dir / src, dur))

        if not video_inputs:
            raise RenderError("No valid video clip inputs")

        audio_inputs: List[Path] = []
        for track in audio_tracks:
            if not isinstance(track, dict):
                continue
            if track.get("type") != "voiceover":
                continue
            segments = track.get("segments")
            if not isinstance(segments, list):
                continue
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                src = str(seg.get("source_file") or "")
                if src:
                    audio_inputs.append(work_dir / src)

        # Build ffmpeg inputs.
        cmd: List[str] = [ffmpeg_path, "-y", "-hide_banner"]

        for img_path, dur in video_inputs:
            cmd.extend(["-loop", "1", "-t", f"{dur:.3f}", "-i", str(img_path)])

        for a in audio_inputs:
            cmd.extend(["-i", str(a)])

        filter_parts: List[str] = []

        # Video streams: scale + fps then concat.
        v_labels: List[str] = []
        for i in range(len(video_inputs)):
            out_label = f"v{i}"
            filter_parts.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p[{out_label}]"
            )
            v_labels.append(f"[{out_label}]")

        filter_parts.append("".join(v_labels) + f"concat=n={len(v_labels)}:v=1:a=0[vout]")

        # Audio concat if present.
        aout_label = None
        if audio_inputs:
            a_start = len(video_inputs)
            a_labels: List[str] = []
            for j in range(len(audio_inputs)):
                in_idx = a_start + j
                out_label = f"a{j}"
                # Normalize to avoid concat failures when inputs differ.
                filter_parts.append(
                    f"[{in_idx}:a]aresample=44100,"
                    f"aformat=sample_fmts=s16:channel_layouts=stereo[{out_label}]"
                )
                a_labels.append(f"[{out_label}]")

            filter_parts.append("".join(a_labels) + f"concat=n={len(a_labels)}:v=0:a=1[aout]")
            aout_label = "[aout]"

        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[vout]"])
        if aout_label:
            cmd.extend(["-map", aout_label])
        else:
            # No audio; ensure playable mp4.
            cmd.extend(["-an"])

        out_path = work_dir / "final_video.mp4"
        cmd.extend([
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
        ])
        if aout_label:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd.append(str(out_path))

        started = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - started

        if proc.returncode != 0:
            raise RenderError(f"FFmpeg render failed: {proc.stderr.strip()}")

        if not out_path.exists():
            raise RenderError("FFmpeg completed but output file missing")

        return out_path


class RenderAgent:
    """Agent that executes a RenderSpecification to produce a final video."""

    def __init__(
        self,
        output_dir: Path,
        engine: Optional[RenderEngine] = None,
    ):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine or DryRunRenderEngine()

    def render(self, render_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Render the final video.

        Args:
            render_spec: RenderSpecification dict.

        Returns:
            FinalVideo dict.
        """
        if not isinstance(render_spec, dict):
            raise RenderError("render_spec must be a dict")

        work_dir = self.output_dir
        start = time.time()
        video_path = self.engine.render(render_spec=render_spec, work_dir=work_dir)
        elapsed = time.time() - start

        final_video = {
            "schema_version": "1.0.0",
            "final_video_id": f"fv_{uuid.uuid4().hex[:8]}",
            "render_spec_ref": render_spec.get("render_spec_id", "unknown"),
            "created_at": _utc_now_iso(),
            "video_file_path": str(video_path.relative_to(work_dir)).replace("\\", "/"),
            "thumbnail_path": None,
            "file_size_mb": round((video_path.stat().st_size / (1024 * 1024)) if video_path.exists() else 0.0, 3),
            "duration_seconds": float(render_spec.get("output_settings", {}).get("duration_seconds") or 0.0),
            "resolution": render_spec.get("output_settings", {}).get("resolution"),
            "fps": render_spec.get("output_settings", {}).get("fps"),
            "codec": render_spec.get("output_settings", {}).get("codec"),
            "bitrate_kbps": None,
            "render_metadata": {
                "engine": self.engine.__class__.__name__,
                "render_time_seconds": round(elapsed, 3),
                "success": True,
                "warnings": _render_warnings(render_spec=render_spec, engine=self.engine),
                "preview_url": None,
            },
        }

        write_json(self.output_dir / "final_video.json", final_video)
        return final_video


def _render_warnings(render_spec: Dict[str, Any], engine: RenderEngine) -> List[str]:
    warnings: List[str] = []
    layers = render_spec.get("layers")
    if isinstance(layers, list):
        has_text = any(isinstance(l, dict) and l.get("type") == "text" for l in layers)
        if has_text and isinstance(engine, FfmpegRenderEngine):
            warnings.append("Text layers are present but not rendered in Phase 1")
        elif has_text and isinstance(engine, DryRunRenderEngine):
            warnings.append("Dry-run engine does not render output")
    return warnings


def _find_layer(render_spec: Dict[str, Any], layer_type: str) -> Dict[str, Any]:
    layers = render_spec.get("layers")
    if not isinstance(layers, list):
        return {}
    for layer in layers:
        if isinstance(layer, dict) and layer.get("type") == layer_type:
            return layer
    return {}


def create_render_agent(
    output_dir: Path,
    engine: Optional[str] = None,
) -> RenderAgent:
    """Factory for RenderAgent.

    Args:
        output_dir: Run directory containing render-spec-relative files.
        engine: "ffmpeg" or "dry_run".

    Returns:
        RenderAgent.
    """
    if engine == "ffmpeg":
        return RenderAgent(output_dir=output_dir, engine=FfmpegRenderEngine())
    return RenderAgent(output_dir=output_dir, engine=DryRunRenderEngine())
