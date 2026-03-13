"""Tests for render agent text overlay helpers."""

from pathlib import Path

from video_agent.render_agent import (
    _build_drawtext_filters,
    _fit_subtitle_text,
    _escape_drawtext_text,
    _hex_to_ffmpeg_color,
    _position_to_drawtext,
)


def test_build_drawtext_filters_creates_chained_filters(tmp_path: Path) -> None:
    text_layer = {
        "type": "text",
        "elements": [
            {
                "text": "HELLO WORLD",
                "t_start_s": 0.5,
                "t_end_s": 2.0,
                "position": {"x": "center", "y": 0.75},
                "style": {
                    "size": 72,
                    "color": "#FFFFFF",
                    "stroke": {"color": "#000000", "width": 4},
                },
            },
            {
                "text": "NEXT LINE",
                "t_start_s": 2.1,
                "t_end_s": 4.5,
                "position": {"x": "left", "y": "top"},
                "style": {
                    "size": 60,
                    "color": "#FFAA00",
                    "stroke": {"color": "#111111", "width": 2},
                },
            },
        ],
    }

    filters, out_label = _build_drawtext_filters(
        text_layer=text_layer,
        in_label="vout",
        width=1080,
        height=1920,
        work_dir=tmp_path,
    )

    assert len(filters) == 2
    assert filters[0].startswith("[vout]drawtext=")
    assert "[vtxt0]" in filters[0]
    assert filters[1].startswith("[vtxt0]drawtext=")
    assert "[vtxt1]" in filters[1]
    assert "textfile='" in filters[0]
    assert "subtitle_000.txt'" in filters[0]
    assert "textfile='" in filters[1]
    assert "subtitle_001.txt'" in filters[1]
    assert "enable='between(t,0.500,2.000)'" in filters[0]
    assert "enable='between(t,2.100,4.500)'" in filters[1]
    assert out_label == "vtxt1"
    assert (tmp_path / "_drawtext" / "subtitle_000.txt").exists()
    assert (tmp_path / "_drawtext" / "subtitle_001.txt").exists()


def test_position_to_drawtext_supports_keywords_and_ratios() -> None:
    x_expr, y_expr = _position_to_drawtext({"x": "center", "y": 0.75}, width=1080, height=1920)
    assert x_expr == "(w-text_w)/2"
    assert y_expr == "h*0.7500-text_h/2"

    x_expr, y_expr = _position_to_drawtext({"x": "right", "y": "center"}, width=1080, height=1920)
    assert x_expr == "w-text_w-w*0.05"
    assert y_expr == "(h-text_h)/2"


def test_escape_drawtext_text_escapes_reserved_characters() -> None:
    raw = "A:B [C] 50% 'quote' \\\n+line"
    escaped = _escape_drawtext_text(raw)

    assert r"\:" in escaped
    assert r"\[" in escaped and r"\]" in escaped
    assert r"\%" in escaped
    assert r"\'" in escaped


def test_hex_to_ffmpeg_color_normalizes_or_falls_back() -> None:
    assert _hex_to_ffmpeg_color("#fff", default="000000") == "FFFFFF"
    assert _hex_to_ffmpeg_color("abc123", default="000000") == "ABC123"
    assert _hex_to_ffmpeg_color("not-a-color", default="123456") == "123456"


def test_fit_subtitle_text_wraps_long_lines() -> None:
    text = "Commandant Aresko and Taskmaster Grint are both voiced by the same actor, David Shaughnessy."
    wrapped, font_size = _fit_subtitle_text(
        text=text,
        video_width=1080,
        preferred_font_size=72,
        min_font_size=42,
        max_lines=3,
    )

    assert "\n" in wrapped
    assert len(wrapped.splitlines()) <= 3
    assert 42 <= font_size <= 72


def test_drawtext_text_file_uses_lf_not_crlf(tmp_path: Path) -> None:
    text_layer = {
        "type": "text",
        "elements": [
            {
                "text": "Line one\nLine two",
                "t_start_s": 0.0,
                "t_end_s": 1.0,
                "position": {"x": "center", "y": 0.75},
                "style": {
                    "size": 72,
                    "color": "#FFFFFF",
                    "stroke": {"color": "#000000", "width": 4},
                },
            }
        ],
    }

    _build_drawtext_filters(
        text_layer=text_layer,
        in_label="vout",
        width=1080,
        height=1920,
        work_dir=tmp_path,
    )

    first = tmp_path / "_drawtext" / "subtitle_000.txt"
    second = tmp_path / "_drawtext" / "subtitle_001.txt"

    payload_first = first.read_bytes()
    payload_second = second.read_bytes()

    assert b"\r" not in payload_first
    assert b"\r" not in payload_second
    assert payload_first == b"Line one"
    assert payload_second == b"Line two"