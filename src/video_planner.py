"""Video planning utilities.

This stage bridges Script Generation → Video Generation.

It converts a `ScriptPackage` into a deterministic `VideoPlan` structure that
can be rendered later by different toolchains (FFmpeg, MoviePy, CapCut, AE, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def script_package_to_video_plan(
    script_package: Dict[str, Any],
    creative_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert a ScriptPackage into a VideoPlan.

    Args:
        script_package: ScriptPackage dict output from ScriptGenerationAgent.
        creative_spec: Optional CreativeSpec dict.

    Returns:
        VideoPlan dict.

    Raises:
        ValueError: If required fields are missing.
    """
    if not isinstance(script_package, dict):
        raise ValueError("script_package must be a dict")

    script = script_package.get("script")
    if not isinstance(script, dict):
        raise ValueError("ScriptPackage.script must be an object")

    beats = script.get("beats")
    if not isinstance(beats, list) or not beats:
        raise ValueError("ScriptPackage.script.beats must be a non-empty list")

    topic_id = str(script_package.get("topic_id") or "")
    subtopic_id = str(script_package.get("subtopic_id") or "")

    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    script_package_id = script_package.get("script_package_id")
    if isinstance(script_package_id, str) and script_package_id:
        if script_package_id.startswith("sg_"):
            video_plan_id = "vp_" + script_package_id[len("sg_") :]
        else:
            video_plan_id = f"vp_{script_package_id}"
    else:
        video_plan_id = f"vp_{uuid.uuid4().hex[:8]}"

    scenes: List[Dict[str, Any]] = []
    for i, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            continue
        scenes.append(
            {
                "scene_id": f"scene_{i:02d}",
                "t_start_s": float(beat.get("t_start_s", 0) or 0),
                "t_end_s": float(beat.get("t_end_s", 0) or 0),
                "vo_line": str(beat.get("vo_line") or "").strip(),
                "on_screen_text": str(beat.get("on_screen_text") or "").strip(),
                "visual_direction": "b-roll or simple illustration supporting the on-screen text",
                "asset_prompts": [
                    str(beat.get("on_screen_text") or "").strip()
                ],
            }
        )

    return {
        "schema_version": "1.0.0",
        "created_at": created_at,
        "video_plan_id": video_plan_id,
        "topic_id": topic_id,
        "subtopic_id": subtopic_id,
        "inputs": {
            "script_package_ref": script_package.get("script_package_id"),
            "creative_spec": creative_spec,
        },
        "audio": {
            "tts": {
                "enabled": True,
                "voice": (creative_spec or {}).get("channel", {}).get("voice", "narrator"),
            }
        },
        "subtitles": {
            "enabled": True,
            "style": (creative_spec or {}).get("style", {}).get("subtitle_style", "large, high-contrast"),
        },
        "scenes": scenes,
    }
