"""Screenplay artifact schemas and helper constructors.

Defines Concept, Screenplay, and FeasibilityReport typed dict shapes.
Uses plain dicts to match existing project style (no Pydantic).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------

def new_concept(
    topic_brief_ref: str,
    fmt: str,
    hook: str,
    angle: str,
    hook_strength_estimate: float = 0.5,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "concept_id": f"c_{uuid.uuid4().hex[:12]}",
        "topic_brief_ref": topic_brief_ref,
        "format": fmt,
        "hook": hook,
        "angle": angle,
        "hook_strength_estimate": hook_strength_estimate,
        "feasibility_score": None,
    }


def new_screenplay(
    concept_ref: str,
    fmt: str,
    target_duration_s: int,
    narrator_character: dict[str, Any],
    music_tone: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "screenplay_id": f"sp_{uuid.uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "concept_ref": concept_ref,
        "format": fmt,
        "target_duration_s": target_duration_s,
        "narrator_character": narrator_character,
        "music_tone": music_tone,
        "scenes": scenes,
        "feasibility_report": None,
    }


def new_feasibility_report(
    screenplay_ref: str,
    overall_score: float,
    scene_issues: list[dict[str, Any]],
    recommended_action: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "screenplay_ref": screenplay_ref,
        "overall_score": overall_score,
        "scene_issues": scene_issues,
        "recommended_action": recommended_action,
    }


# ---------------------------------------------------------------------------
# bridge: Screenplay -> ScriptPackage
# ---------------------------------------------------------------------------

def screenplay_to_script_package(screenplay: dict[str, Any]) -> dict[str, Any]:
    """Convert a Screenplay to the existing ScriptPackage format.

    Mapping:
    - scenes[i].vo_line           -> script.beats[i].vo_line
    - scenes[i].on_screen_text    -> script.beats[i].on_screen_text
    - scenes[i].target_duration_s -> t_start_s / t_end_s (cumulative)
    - scenes[i].visual.search_queries -> asset_prompts (first query per scene)
    - narrator_character.voice_preset -> audio.tts.voice

    Returns a ScriptPackage dict valid for video_planner.script_package_to_video_plan().
    """
    scenes = screenplay.get("scenes") or []
    beats: list[dict[str, Any]] = []
    asset_prompts: list[str] = []

    current_t = 0.0
    for scene in scenes:
        dur = float(scene.get("target_duration_s") or 5.0)
        t_start = round(current_t, 2)
        t_end = round(current_t + dur, 2)
        current_t = t_end

        visual = scene.get("visual") or {}
        queries = visual.get("search_queries") or []
        asset_prompts.append(str(queries[0]) if queries else str(visual.get("description") or ""))

        beats.append({
            "scene_id": str(scene.get("scene_id") or f"scene_{i + 1:02d}"),
            "t_start_s": t_start,
            "t_end_s": t_end,
            "on_screen_text": str(scene.get("on_screen_text") or "").strip(),
            "vo_line": str(scene.get("vo_line") or "").strip(),
            "visual_queries": queries,
        })

    voiceover = " ".join(b["vo_line"] for b in beats if b.get("vo_line"))

    narrator = screenplay.get("narrator_character") or {}
    voice = str(narrator.get("voice_preset") or "narrator")

    topic_id = str(screenplay.get("format") or "topic")
    # Derive a readable subtopic from VO text so image queries use real keywords.
    # Strip punctuation so tokens like "?" don't contaminate search queries.
    import re as _re
    vo_raw = " ".join(b["vo_line"] for b in beats[:3] if b.get("vo_line"))
    vo_words = _re.sub(r"[^a-zA-Z0-9 ]", " ", vo_raw).split()
    subtopic_id = " ".join(vo_words[:8]) if vo_words else str(screenplay.get("screenplay_id") or "sub")

    return {
        "schema_version": "1.0.0",
        "created_at": screenplay.get("created_at", ""),
        "script_package_id": f"sg_{uuid.uuid4().hex[:12]}",
        "screenplay_ref": screenplay.get("screenplay_id"),
        "topic_id": topic_id,
        "subtopic_id": subtopic_id,
        "hook_variants": [
            str(screenplay.get("concept_ref") or ""),
        ],
        "script": {
            "voiceover": voiceover,
            "beats": beats,
        },
        "asset_prompts": asset_prompts,
        "caption": voiceover[:120] if voiceover else "",
        "hashtags": ["#shorts", "#didyouknow", "#facts", "#learn"],
        "safety_notes": [],
        "audio": {
            "tts": {
                "voice": voice,
            }
        },
        "generation": {
            "mode": "screenplay",
            "screenplay_id": screenplay.get("screenplay_id"),
            "format": screenplay.get("format"),
        },
    }
