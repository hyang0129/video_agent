"""ScreenplayAgent: writes a full Screenplay from a Concept + format template."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import make_llm
from ..utils.json_utils import safe_json_loads
from ..artifacts.screenplay import new_screenplay

_FORMAT_LIBRARY_DIR = Path(__file__).parent / "format_library"

_WRITE_SYSTEM = """\
You are a short-form video screenplay writer specializing in faceless, narrated YouTube Shorts.

Given a Concept and a format template, write a full Screenplay as a JSON object.

The Screenplay must have:
- "target_duration_s": integer seconds (use the template's target_duration_s)
- "narrator_character": {{"type": "voice_only", "voice_preset": "<calm|narrator|energetic|authoritative>"}}
- "music_tone": string matching the template's music_tone
- "scenes": array of scene objects

Each scene object must have:
- "scene_id": "scene_01", "scene_02", ... (zero-padded, sequential)
- "vo_line": the narration text for this scene (spoken aloud)
- "target_duration_s": float seconds for this scene (all scenes must sum to target_duration_s)
- "visual": {{
    "description": specific, concrete description of what the camera sees (NOT abstract, NOT "people talking"),
    "mood": one word mood,
    "search_queries": list of 1-3 Pexels-friendly search queries ordered by specificity
  }}
- "on_screen_text": caption text displayed on screen (brief, punchy)
- "music_energy": "low" | "medium" | "high"

CRITICAL: visual.description must be concrete and specific. Do NOT write:
- "people talking"
- "person thinking"
- "group of people"
- "background"
These will fail image search. Write what the camera literally sees: objects, places, events.

Return ONLY the JSON object with keys: target_duration_s, narrator_character, music_tone, scenes.
No markdown. No explanation.
"""

_REVISE_SYSTEM = """\
You are a short-form video screenplay editor.
You will be given an existing Screenplay and a specific scene revision task.
Revise ONLY the specified field(s) of the specified scene. Leave all other scenes and fields unchanged.
Return the full updated Screenplay JSON object.
No markdown. No explanation.
"""


def _load_format_template(fmt: str) -> dict[str, Any]:
    path = _FORMAT_LIBRARY_DIR / f"{fmt}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _coerce_scenes(raw_scenes: Any, target_duration_s: int) -> list[dict[str, Any]]:
    if not isinstance(raw_scenes, list):
        return []

    scenes: list[dict[str, Any]] = []
    for i, s in enumerate(raw_scenes):
        if not isinstance(s, dict):
            continue
        scene_id = str(s.get("scene_id") or f"scene_{i+1:02d}")
        vo = str(s.get("vo_line") or "").strip()
        dur = float(s.get("target_duration_s") or 5.0)
        visual_raw = s.get("visual") or {}
        visual: dict[str, Any] = {
            "description": str(visual_raw.get("description") or "").strip(),
            "mood": str(visual_raw.get("mood") or "neutral").strip(),
            "search_queries": list(visual_raw.get("search_queries") or []),
        }
        scenes.append({
            "scene_id": scene_id,
            "vo_line": vo,
            "target_duration_s": dur,
            "visual": visual,
            "on_screen_text": str(s.get("on_screen_text") or "").strip(),
            "music_energy": str(s.get("music_energy") or "medium").strip(),
        })

    if not scenes:
        return scenes

    # Normalize durations to sum to target_duration_s
    total = sum(sc["target_duration_s"] for sc in scenes)
    if total > 0 and abs(total - target_duration_s) > 1.0:
        scale = target_duration_s / total
        for sc in scenes:
            sc["target_duration_s"] = round(sc["target_duration_s"] * scale, 1)
        # Fix rounding drift on last scene
        drift = target_duration_s - sum(sc["target_duration_s"] for sc in scenes)
        scenes[-1]["target_duration_s"] = round(scenes[-1]["target_duration_s"] + drift, 1)

    return scenes


class ScreenplayAgent:
    def __init__(self) -> None:
        self.llm = make_llm(temperature=0.8)

    def write_screenplay(
        self,
        concept: dict[str, Any],
        topic_brief: dict[str, Any],
        format_template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a full Screenplay for the given Concept."""
        fmt = str(concept.get("format") or "facts")
        template = format_template or _load_format_template(fmt)
        target_duration_s = int(template.get("target_duration_s") or 45)

        human_payload = {
            "concept": concept,
            "topic_brief": topic_brief,
            "format_template": template,
        }

        messages = [
            SystemMessage(content=_WRITE_SYSTEM),
            HumanMessage(content="Write the screenplay:\n\n" + json.dumps(human_payload, ensure_ascii=False)),
        ]

        response = self.llm.invoke(messages)
        raw = safe_json_loads(str(response.content))

        if not isinstance(raw, dict):
            raw = {}

        scenes = _coerce_scenes(raw.get("scenes") or [], target_duration_s)
        narrator = raw.get("narrator_character") or {"type": "voice_only", "voice_preset": "calm"}
        music_tone = str(raw.get("music_tone") or template.get("music_tone") or "neutral")

        return new_screenplay(
            concept_ref=str(concept.get("concept_id") or ""),
            fmt=fmt,
            target_duration_s=target_duration_s,
            narrator_character=narrator,
            music_tone=music_tone,
            scenes=scenes,
        )

    def revise_scene(
        self,
        screenplay: dict[str, Any],
        scene_id: str,
        issue: str,
        suggestion: str,
        revision_field: str,
    ) -> dict[str, Any]:
        """Rewrite only the specified field(s) of one scene.

        revision_field: "visual" | "vo_line" | "both"
        Returns an updated Screenplay dict with all other scenes unchanged.
        """
        if revision_field == "visual":
            field_instruction = (
                f"Rewrite ONLY visual.description and visual.search_queries for scene {scene_id}. "
                "Do not change vo_line or any other scene."
            )
        elif revision_field == "vo_line":
            target_dur = next(
                (sc["target_duration_s"] for sc in (screenplay.get("scenes") or []) if sc.get("scene_id") == scene_id),
                5.0,
            )
            field_instruction = (
                f"Rewrite ONLY vo_line for scene {scene_id} to fit within {target_dur}s. "
                "Do not change visual or any other scene."
            )
        else:
            field_instruction = (
                f"Rewrite visual.description, visual.search_queries, AND vo_line for scene {scene_id}. "
                "Do not change any other scene."
            )

        human_payload = {
            "screenplay": screenplay,
            "revision_task": {
                "scene_id": scene_id,
                "issue": issue,
                "suggestion": suggestion,
                "revision_field": revision_field,
                "instruction": field_instruction,
            },
        }

        messages = [
            SystemMessage(content=_REVISE_SYSTEM),
            HumanMessage(content=json.dumps(human_payload, ensure_ascii=False)),
        ]

        response = self.llm.invoke(messages)
        raw = safe_json_loads(str(response.content))

        if not isinstance(raw, dict) or not raw.get("scenes"):
            # revision failed; return original unchanged
            print(f"[WARN] Scene revision returned invalid JSON; keeping original scene {scene_id}")
            return screenplay

        # Merge: keep revised screenplay but preserve screenplay_id and metadata
        raw["screenplay_id"] = screenplay.get("screenplay_id")
        raw["schema_version"] = screenplay.get("schema_version")
        raw["created_at"] = screenplay.get("created_at")
        raw["concept_ref"] = screenplay.get("concept_ref")
        raw["format"] = screenplay.get("format")

        target_duration_s = int(screenplay.get("target_duration_s") or 45)
        raw["scenes"] = _coerce_scenes(raw.get("scenes") or [], target_duration_s)

        return raw
