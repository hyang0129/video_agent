"""Script generation agent.

Consumes Market Research artifacts (especially `TopicBrief`) and produces a
structured `ScriptPackage` suitable for downstream video generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage

from .config import GOOGLE_API_KEY, GOOGLE_MODEL
from .utils.json_utils import safe_json_loads


SCRIPT_SYSTEM_PROMPT = """You are a short-form video Script Generation Agent.

You will be given a Topic Brief produced by a Market Research stage.
Your job is to generate an engaging short-form script that stays tightly
within the Topic Brief (topic, subtopic, and angle) and follows the
constraints.

Requirements:
- Output MUST be valid JSON only (no markdown).
- Stay on-topic: do not drift to adjacent fandoms/subtopics.
- Avoid unverifiable claims. If a claim may be uncertain, hedge it.
- Prefer punchy, curiosity-driven writing suitable for 30–60s.

Timing requirements:
- Beats must have contiguous timestamps.
- First beat starts at 0.0.
- Final beat ends at target duration (seconds).
- No overlaps and no negative times.

Produce a `ScriptPackage` JSON object with:
- schema_version
- created_at (ISO 8601 UTC)
- script_package_id
- topic_id, subtopic_id
- hook_variants: 2 hooks (<= 12 words each)
- script:
  - voiceover: full VO text
  - beats: 5-9 beats, each with {t_start_s, t_end_s, on_screen_text, vo_line}
- caption (<= 120 chars)
- hashtags: 5-10
- safety_notes: list of any claims that should be fact-checked
"""


def _target_duration_seconds(
    topic_brief: Dict[str, Any],
    creative_spec: Optional[Dict[str, Any]],
) -> int:
    """Derive target duration in seconds.

    Priority order:
    1) creative_spec.style.target_duration_seconds
    2) topic_brief.format.target_duration_seconds
    3) default 45
    """
    if isinstance(creative_spec, dict):
        style = creative_spec.get("style")
        if isinstance(style, dict):
            value = style.get("target_duration_seconds")
            if isinstance(value, (int, float)) and value > 0:
                return int(round(float(value)))

    fmt = topic_brief.get("format")
    if isinstance(fmt, dict):
        value = fmt.get("target_duration_seconds")
        if isinstance(value, (int, float)) and value > 0:
            return int(round(float(value)))

    return 45


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_beats(beats: List[Dict[str, Any]], target_seconds: int) -> List[Dict[str, Any]]:
    """Ensure beats have contiguous timestamps within target duration.

    If timestamps are missing or inconsistent, this function overwrites them
    deterministically based on beat order.
    """
    if target_seconds <= 0:
        target_seconds = 45

    usable = [b for b in beats if isinstance(b, dict)]
    if not usable:
        return []

    # Clamp beat count to a reasonable range.
    if len(usable) < 5:
        # If too few, keep what we have; video planner can still work.
        pass
    if len(usable) > 12:
        usable = usable[:12]

    # Compute uniform segment length.
    seg = float(target_seconds) / float(len(usable))
    current = 0.0
    normalized: List[Dict[str, Any]] = []
    for i, beat in enumerate(usable):
        start = round(current, 2)
        end = round(float(target_seconds) if i == len(usable) - 1 else current + seg, 2)
        current = end

        normalized.append(
            {
                "t_start_s": start,
                "t_end_s": end,
                "on_screen_text": str(beat.get("on_screen_text") or "").strip(),
                "vo_line": str(beat.get("vo_line") or "").strip(),
            }
        )

    # Ensure exact boundary conditions.
    if normalized:
        normalized[0]["t_start_s"] = 0.0
        normalized[-1]["t_end_s"] = float(target_seconds)
    return normalized


def _validate_or_fix_script_package(
    script_package: Dict[str, Any],
    topic_brief: Dict[str, Any],
    creative_spec: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Validate and repair a ScriptPackage in a best-effort way."""
    target_seconds = _target_duration_seconds(topic_brief=topic_brief, creative_spec=creative_spec)

    script = script_package.get("script")
    if not isinstance(script, dict):
        script = {}
        script_package["script"] = script

    beats_raw = script.get("beats")
    beats: List[Dict[str, Any]]
    if isinstance(beats_raw, list):
        beats = [b for b in beats_raw if isinstance(b, dict)]
    else:
        beats = []

    # If beats are missing or obviously invalid, normalize.
    if not beats:
        script["beats"] = _normalize_beats(
            beats=[
                {"on_screen_text": "", "vo_line": ""}
                for _ in range(7)
            ],
            target_seconds=target_seconds,
        )
        return script_package

    # Check monotonicity and bounds; if violated, overwrite timestamps.
    needs_fix = False
    prev_end = 0.0
    for i, beat in enumerate(beats):
        start = _coerce_float(beat.get("t_start_s"), default=prev_end)
        end = _coerce_float(beat.get("t_end_s"), default=start)
        if i == 0 and abs(start - 0.0) > 0.25:
            needs_fix = True
        if start < 0 or end < 0 or end < start:
            needs_fix = True
        if start < prev_end - 0.25:
            needs_fix = True
        prev_end = end

    if prev_end < float(target_seconds) - 0.25 or prev_end > float(target_seconds) + 0.25:
        needs_fix = True

    if needs_fix:
        script["beats"] = _normalize_beats(beats=beats, target_seconds=target_seconds)
    else:
        # Even if valid, gently clamp the final end time to exact duration.
        script["beats"][0]["t_start_s"] = 0.0
        script["beats"][-1]["t_end_s"] = float(target_seconds)

    return script_package


class ScriptGenerationAgent:
    """Generate short-form scripts from Topic Brief artifacts."""

    def __init__(self, model: str = GOOGLE_MODEL):
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=0.7,
            google_api_key=GOOGLE_API_KEY,
        )

    def generate_script_package(
        self,
        topic_brief: Dict[str, Any],
        creative_spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a `ScriptPackage`.

        Args:
            topic_brief: A TopicBrief artifact dict.
            creative_spec: Optional CreativeSpec artifact dict.

        Returns:
            ScriptPackage dict.

        Raises:
            ValueError: If required TopicBrief fields are missing.
        """
        if not isinstance(topic_brief, dict):
            raise ValueError("topic_brief must be a dict")

        topic_id = str(topic_brief.get("topic_id") or "")
        subtopic_id = str(topic_brief.get("subtopic_id") or "")
        if not topic_id or not subtopic_id:
            raise ValueError("TopicBrief must include topic_id and subtopic_id")

        target_seconds = _target_duration_seconds(topic_brief=topic_brief, creative_spec=creative_spec)

        payload: Dict[str, Any] = {
            "topic_brief": topic_brief,
            "creative_spec": creative_spec,
            "target_duration_seconds": target_seconds,
            "time_now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        messages = [
            SystemMessage(content=SCRIPT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "Generate a ScriptPackage JSON for the following inputs.\n\n"
                    + "INPUTS_JSON:\n"
                    + __import__("json").dumps(payload, ensure_ascii=False)
                )
            ),
        ]

        response = self.llm.invoke(messages)
        parsed = safe_json_loads(str(response.content))

        if not isinstance(parsed, dict):
            raise ValueError("Expected ScriptPackage to be a JSON object")

        parsed.setdefault("script_package_id", f"sg_{uuid.uuid4().hex}")
        parsed.setdefault("schema_version", "1.0.0")
        parsed.setdefault("created_at", payload["time_now"])
        parsed.setdefault("topic_id", topic_id)
        parsed.setdefault("subtopic_id", subtopic_id)

        parsed = _validate_or_fix_script_package(
            script_package=parsed,
            topic_brief=topic_brief,
            creative_spec=creative_spec,
        )
        return parsed


def create_script_agent() -> ScriptGenerationAgent:
    """Factory for ScriptGenerationAgent."""
    return ScriptGenerationAgent()
