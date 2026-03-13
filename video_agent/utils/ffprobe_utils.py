"""FFprobe utilities for video validation.

Shared by main.py and producer_server.validate_output.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict


def probe_video_info(mp4_path: Path) -> Dict[str, Any]:
    """Run ffprobe on mp4_path and return stream metadata.

    Returns:
        Dict with keys: has_video, has_audio, video_duration_s, audio_duration_s.
    """
    result: Dict[str, Any] = {
        "has_video": False,
        "has_audio": False,
        "video_duration_s": 0.0,
        "audio_duration_s": 0.0,
    }

    mp4_path = Path(mp4_path)
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        return result

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return result
        data = json.loads(proc.stdout)
        for stream in data.get("streams") or []:
            codec_type = stream.get("codec_type", "")
            duration = float(stream.get("duration") or 0)
            if codec_type == "video":
                result["has_video"] = True
                result["video_duration_s"] = duration
            elif codec_type == "audio":
                result["has_audio"] = True
                result["audio_duration_s"] = duration
    except Exception:
        pass

    return result


def validate_video(mp4_path: Path) -> bool:
    """Return True if mp4_path is a playable video file with a video stream."""
    mp4_path = Path(mp4_path)
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        print(f"[ERROR] Post-render validation FAILED: {mp4_path} missing or empty")
        return False

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type,duration",
            "-of", "csv=p=0",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"[ERROR] Post-render validation FAILED: no readable video stream in {mp4_path.name}")
        print(f"        ffprobe: {result.stderr.strip()}")
        return False

    print(f"[OK] Post-render validation passed: {mp4_path.name} is playable")
    return True
