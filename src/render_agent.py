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
import textwrap
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

        # Prefer a single integrated master track when available.
        master_audio_path: Optional[Path] = None
        for track in audio_tracks:
            if not isinstance(track, dict) or track.get("type") != "master":
                continue
            src = str(track.get("source_file") or "").strip()
            if not src:
                continue
            candidate = work_dir / src
            if _is_usable_audio_file(candidate):
                master_audio_path = candidate
                break

        if master_audio_path is not None:
            audio_inputs.append(master_audio_path)
        else:
            # Fallback to segment-based voiceover concat.
            for track in audio_tracks:
                if not isinstance(track, dict):
                    continue
                if track.get("type") != "voiceover":
                    continue
                segments = track.get("segments")
                if not isinstance(segments, list):
                    continue

                sorted_segments = sorted(
                    [seg for seg in segments if isinstance(seg, dict)],
                    key=lambda seg: float(seg.get("t_start_s") or 0.0),
                )

                for seg in sorted_segments:
                    src = str(seg.get("source_file") or "")
                    if not src:
                        continue
                    candidate = work_dir / src
                    if _is_usable_audio_file(candidate):
                        audio_inputs.append(candidate)

        # Resolve music track (shared asset, path may be absolute).
        music_path: Optional[Path] = None
        music_volume_db: float = -18.0
        for track in audio_tracks:
            if not isinstance(track, dict) or track.get("type") != "music":
                continue
            src = str(track.get("source_file") or "").strip()
            if not src:
                continue
            candidate = Path(src) if Path(src).is_absolute() else work_dir / src
            if _is_usable_audio_file(candidate):
                music_path = candidate
                music_volume_db = float(track.get("volume_db") or -18.0)
                break

        # Build ffmpeg inputs.
        cmd: List[str] = [ffmpeg_path, "-y", "-hide_banner"]

        for img_path, dur in video_inputs:
            cmd.extend(["-loop", "1", "-t", f"{dur:.3f}", "-i", str(img_path)])

        for a in audio_inputs:
            cmd.extend(["-i", str(a)])

        if music_path is not None:
            # -stream_loop -1 loops the music indefinitely; duration capped by amix later.
            cmd.extend(["-stream_loop", "-1", "-i", str(music_path)])

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
            work_dir=work_dir,
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

        # Mix background music into voiceover if a music track is present.
        if music_path is not None and aout_label:
            music_idx = len(video_inputs) + len(audio_inputs)
            vol_linear = 10 ** (music_volume_db / 20.0)
            filter_parts.append(
                f"[{music_idx}:a]aresample=44100,"
                f"aformat=sample_fmts=s16:channel_layouts=stereo,"
                f"volume={vol_linear:.4f}[amusic]"
            )
            filter_parts.append(f"[aout][amusic]amix=inputs=2:duration=first[amixed]")
            aout_label = "[amixed]"

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
    work_dir: Path,
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

    text_dir = work_dir / "_drawtext"
    text_dir.mkdir(parents=True, exist_ok=True)

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

        wrapped_text, fitted_font_size = _fit_subtitle_text(
            text=text,
            video_width=width,
            preferred_font_size=font_size,
            min_font_size=42,
            max_lines=3,
        )

        x_expr, y_expr = _position_to_drawtext(
            position=element.get("position") if isinstance(element.get("position"), dict) else {},
            width=width,
            height=height,
        )

        lines = [line.strip() for line in wrapped_text.splitlines() if line.strip()]
        if not lines:
            lines = [wrapped_text.strip()]

        for line_index, line_text in enumerate(lines):
            text_file = text_dir / f"subtitle_{drawtext_index:03d}.txt"
            _write_drawtext_text_file(text_file=text_file, text=line_text)
            text_file_arg = _escape_drawtext_value(str(text_file.resolve()).replace("\\", "/"))

            line_y_expr = _line_offset_y_expr(
                base_y_expr=y_expr,
                line_index=line_index,
                total_lines=len(lines),
                font_size=fitted_font_size,
            )

            options = [
                f"textfile='{text_file_arg}'",
                f"fontsize={fitted_font_size}",
                f"fontcolor=#{font_color}",
                f"x={x_expr}",
                f"y={line_y_expr}",
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


def _escape_drawtext_value(value: str) -> str:
    """Escape drawtext option values (e.g., textfile paths)."""
    escaped = value.replace("\\", r"\\")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    return escaped


def _fit_subtitle_text(
    text: str,
    video_width: int,
    preferred_font_size: int,
    min_font_size: int = 42,
    max_lines: int = 3,
) -> Tuple[str, int]:
    """Wrap subtitle text to fit width and adjust font size if needed.

    Args:
        text: Raw subtitle text.
        video_width: Video width in pixels.
        preferred_font_size: Desired subtitle font size.
        min_font_size: Minimum allowed font size.
        max_lines: Soft cap for wrapped subtitle lines.

    Returns:
        Tuple of (wrapped_text, fitted_font_size).
    """
    font_size = max(min_font_size, int(preferred_font_size))
    wrapped = _wrap_subtitle_text(text=text, video_width=video_width, font_size=font_size)

    while len(wrapped.splitlines()) > max_lines and font_size > min_font_size:
        font_size = max(min_font_size, font_size - 4)
        wrapped = _wrap_subtitle_text(text=text, video_width=video_width, font_size=font_size)

    return wrapped, font_size


def _wrap_subtitle_text(text: str, video_width: int, font_size: int) -> str:
    """Wrap subtitle text into multiple lines based on estimated pixel width."""
    max_chars = _estimate_max_chars_per_line(video_width=video_width, font_size=font_size)
    wrapped_lines: List[str] = []

    for paragraph in text.splitlines() or [text]:
        chunk = paragraph.strip()
        if not chunk:
            wrapped_lines.append("")
            continue

        lines = textwrap.wrap(
            chunk,
            width=max_chars,
            break_long_words=True,
            break_on_hyphens=True,
        )
        wrapped_lines.extend(lines or [chunk])

    return "\n".join(wrapped_lines).strip()


def _estimate_max_chars_per_line(video_width: int, font_size: int) -> int:
    """Estimate max characters per subtitle line to avoid edge clipping."""
    usable_width_px = max(200, int(video_width * 0.86))
    approx_char_width_px = max(8.0, font_size * 0.56)
    return max(12, int(usable_width_px / approx_char_width_px))


def _line_offset_y_expr(base_y_expr: str, line_index: int, total_lines: int, font_size: int) -> str:
    """Offset Y expression so each wrapped line is rendered as its own layer."""
    line_spacing_px = max(18, int(font_size * 1.15))
    center_index = (total_lines - 1) / 2.0
    offset = int(round((line_index - center_index) * line_spacing_px))
    if offset == 0:
        return f"({base_y_expr})"
    sign = "+" if offset > 0 else "-"
    return f"({base_y_expr}){sign}{abs(offset)}"


def _write_drawtext_text_file(text_file: Path, text: str) -> None:
    """Write drawtext text file with normalized LF line endings.

    FFmpeg `drawtext=textfile=...` can render stray box glyphs when Windows CRLF
    (`\r\n`) is present. This function forces LF and strips control characters
    except newline and tab.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_chars: List[str] = []
    for char in normalized:
        codepoint = ord(char)
        if char in {"\n", "\t"} or codepoint >= 32:
            cleaned_chars.append(char)
    cleaned = "".join(cleaned_chars)

    with text_file.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(cleaned)


def _is_usable_audio_file(path: Path) -> bool:
    """Return True when audio input exists and has content."""
    return path.exists() and path.is_file() and path.stat().st_size > 0


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
