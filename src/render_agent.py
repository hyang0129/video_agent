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
        text_layer = _find_layer(render_spec, "text")

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

        final_video_label = "[vout]"

        # Text overlays: drawtext chain from text layer elements.
        text_filters, text_out_label = _build_drawtext_filters(
            text_layer=text_layer,
            in_label="vout",
            width=width,
            height=height,
        )
        if text_filters:
            filter_parts.extend(text_filters)
        if text_out_label:
            final_video_label = f"[{text_out_label}]"

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
        cmd.extend(["-map", final_video_label])
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
        if has_text and isinstance(engine, DryRunRenderEngine):
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


def _build_drawtext_filters(
    text_layer: Dict[str, Any],
    in_label: str,
    width: int,
    height: int,
) -> Tuple[List[str], Optional[str]]:
    """Build FFmpeg drawtext filter chain for text elements.

    Args:
        text_layer: Render text layer dictionary.
        in_label: Input video stream label (without brackets).
        width: Output video width in pixels.
        height: Output video height in pixels.

    Returns:
        Tuple of (filter_parts, final_output_label).
    """
    elements = text_layer.get("elements") if isinstance(text_layer, dict) else None
    if not isinstance(elements, list) or not elements:
        return [], None

    filters: List[str] = []
    current_label = in_label
    drawtext_index = 0

    for element in elements:
        if not isinstance(element, dict):
            continue

        text = str(element.get("text") or "").strip()
        if not text:
            continue

        t_start = float(element.get("t_start_s") or 0.0)
        t_end = float(element.get("t_end_s") or 0.0)
        if t_end <= t_start:
            continue

        style = element.get("style") if isinstance(element.get("style"), dict) else {}
        stroke = style.get("stroke") if isinstance(style.get("stroke"), dict) else {}

        font_size = int(style.get("size") or 72)
        font_color = _hex_to_ffmpeg_color(str(style.get("color") or "#FFFFFF"), default="FFFFFF")
        border_color = _hex_to_ffmpeg_color(str(stroke.get("color") or "#000000"), default="000000")
        border_width = max(0, int(stroke.get("width") or 0))

        x_expr, y_expr = _position_to_drawtext(
            position=element.get("position") if isinstance(element.get("position"), dict) else {},
            width=width,
            height=height,
        )

        escaped_text = _escape_drawtext_text(text)

        options = [
            f"text='{escaped_text}'",
            f"fontsize={font_size}",
            f"fontcolor=#{font_color}",
            f"x={x_expr}",
            f"y={y_expr}",
            f"enable='between(t,{t_start:.3f},{t_end:.3f})'",
        ]

        if border_width > 0:
            options.extend([
                f"borderw={border_width}",
                f"bordercolor=#{border_color}",
            ])

        out_label = f"vtxt{drawtext_index}"
        filters.append(f"[{current_label}]drawtext={':'.join(options)}[{out_label}]")
        current_label = out_label
        drawtext_index += 1

    if not filters:
        return [], None
    return filters, current_label


def _position_to_drawtext(position: Dict[str, Any], width: int, height: int) -> Tuple[str, str]:
    """Convert text position object to drawtext x/y expressions."""
    x_value = position.get("x", "center")
    y_value = position.get("y", 0.75)

    if isinstance(x_value, (int, float)):
        x_expr = str(int(float(x_value) * width)) if 0.0 <= float(x_value) <= 1.0 else str(int(float(x_value)))
    else:
        x_value_str = str(x_value).lower().strip()
        if x_value_str == "left":
            x_expr = "w*0.05"
        elif x_value_str == "right":
            x_expr = "w-text_w-w*0.05"
        else:
            x_expr = "(w-text_w)/2"

    if isinstance(y_value, (int, float)):
        y_numeric = float(y_value)
        if 0.0 <= y_numeric <= 1.0:
            y_expr = f"h*{y_numeric:.4f}-text_h/2"
        else:
            y_expr = str(int(y_numeric))
    else:
        y_value_str = str(y_value).lower().strip()
        if y_value_str == "top":
            y_expr = "h*0.08"
        elif y_value_str == "center":
            y_expr = "(h-text_h)/2"
        else:
            y_expr = "h*0.75-text_h/2"

    return x_expr, y_expr


def _hex_to_ffmpeg_color(hex_color: str, default: str) -> str:
    """Normalize a hex color string to RRGGBB for FFmpeg."""
    value = hex_color.strip().lstrip("#")
    if len(value) == 3 and all(c in "0123456789abcdefABCDEF" for c in value):
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6 or not all(c in "0123456789abcdefABCDEF" for c in value):
        return default
    return value.upper()


def _escape_drawtext_text(text: str) -> str:
    """Escape text for FFmpeg drawtext option parsing."""
    escaped = text.replace("\\", r"\\")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    escaped = escaped.replace("%", r"\%")
    escaped = escaped.replace("[", r"\[").replace("]", r"\]")
    escaped = escaped.replace("\n", r"\n")
    return escaped


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
