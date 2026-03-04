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
from .facts.fact_store import FactStore


SCRIPT_SYSTEM_PROMPT = """You are a short-form video Script Generation Agent.

You will be given a Topic Brief produced by a Market Research stage, plus a set of
VERIFIED FACTS from a fact database.

Your job is to generate an engaging short-form script that:
- Uses ONLY the provided verified facts (do not add facts from your training data)
- Stays tightly within the Topic Brief (topic, subtopic, and angle)
- Follows all constraints

CRITICAL GROUNDING RULE:
Every factual claim in your script MUST come from the provided facts list.
If you don't have enough facts, create a shorter script or use more general statements.
DO NOT hallucinate or invent facts.

Requirements:
- Output MUST be valid JSON only (no markdown).
- Stay on-topic: do not drift to adjacent fandoms/subtopics.
- Use cautious language for any uncertain claims (e.g., "reportedly", "according to").
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
- fact_sources: list of fact_ids used in the script
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


def _extract_beats_from_script_content(
    script_package: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract beat candidates from top-level ``script_content`` format.

    Some model responses return factual segments as:
    ``script_content: [{segment_id, text, duration_seconds, fact_ids}, ...]``
    instead of ``script.beats``. This helper converts those segments into beat
    payloads so downstream timing and audio stages remain fact-grounded.

    Args:
        script_package: Raw script package emitted by LLM.

    Returns:
        List of beat dicts with ``on_screen_text`` and ``vo_line``.
    """
    raw_segments = script_package.get("script_content")
    if not isinstance(raw_segments, list):
        return []

    beats: List[Dict[str, Any]] = []
    for segment in raw_segments:
        if not isinstance(segment, dict):
            continue

        line = str(segment.get("text") or "").strip()
        if not line:
            continue

        segment_id = str(segment.get("segment_id") or "").strip()
        if segment_id:
            label = segment_id.replace("_", " ").title()
        else:
            label = f"Beat {len(beats) + 1}"

        beats.append(
            {
                "on_screen_text": label,
                "vo_line": line,
            }
        )

    return beats


def _is_generic_placeholder_beats(beats: List[Dict[str, Any]]) -> bool:
    """Detect fallback/template beat content that is not fact-grounded.

    Args:
        beats: Beat list from ``script.beats``.

    Returns:
        True when beat lines match known generic placeholder patterns.
    """
    if not beats:
        return True

    joined = " ".join([str(beat.get("vo_line") or "").strip().lower() for beat in beats if isinstance(beat, dict)])
    if not joined:
        return True

    markers = [
        "quick",
        "today: facts",
        "core idea in plain english",
        "why it matters",
        "one example",
        "the takeaway",
        "want more quick facts like this",
    ]

    hits = sum(1 for marker in markers if marker in joined)
    return hits >= 3


def _build_fact_grounded_beats_from_facts(
    facts: List[Dict[str, Any]],
    topic_id: str,
    subtopic_id: str,
    target_seconds: int,
) -> List[Dict[str, Any]]:
    """Build a deterministic fact-grounded beat list from retrieved facts.

    Args:
        facts: Retrieved fact records from store.
        topic_id: Current topic id.
        subtopic_id: Current subtopic id.
        target_seconds: Target video duration.

    Returns:
        Normalized beat list timed to target duration.
    """
    safe_topic = topic_id.replace("_", " ").strip() or "this"
    safe_subtopic = subtopic_id.replace("_", " ").strip() or "facts"

    if "fact" in safe_subtopic.lower():
        hook_tail = f"Here are surprising {safe_subtopic}."
    else:
        hook_tail = f"Here are surprising {safe_subtopic} facts."

    cta_subject = safe_subtopic if "fact" in safe_subtopic.lower() else f"{safe_subtopic} facts"
    if cta_subject.strip().lower() == "facts":
        cta_subject = f"{safe_topic} facts"

    draft_beats: List[Dict[str, Any]] = [
        {
            "on_screen_text": "Hook",
            "vo_line": f"Think you know {safe_topic}? {hook_tail}",
        }
    ]

    for index, fact in enumerate(facts[:5], 1):
        if not isinstance(fact, dict):
            continue
        fact_text = str(fact.get("fact_text") or "").strip()
        if not fact_text:
            continue
        draft_beats.append(
            {
                "on_screen_text": f"Fact {index}",
                "vo_line": fact_text,
            }
        )

    draft_beats.append(
        {
            "on_screen_text": "Follow for more",
            "vo_line": f"Which fact surprised you most? Follow for more {cta_subject}.",
        }
    )

    return _normalize_beats(beats=draft_beats, target_seconds=target_seconds)


def _normalize_beats(beats: List[Dict[str, Any]], target_seconds: int) -> List[Dict[str, Any]]:
    """Ensure beats have contiguous timestamps within target duration.
    
    Each beat's duration is calculated based on:
    - Word count in vo_line
    - Speaking rate (words per minute)
    - Complexity factors (technical terms, proper nouns, punctuation)
    
    Durations are then scaled proportionally to fit the target duration exactly.
    """
    if target_seconds <= 0:
        target_seconds = 45

    usable = [b for b in beats if isinstance(b, dict)]
    if not usable:
        return []

    # Clamp beat count to a reasonable range.
    if len(usable) > 12:
        usable = usable[:12]

    # Constants for timing calculation
    BASE_WPM = 170  # Words per minute for conversational VO
    MIN_BEAT_DURATION = 2.0  # Minimum seconds per beat
    MAX_BEAT_DURATION = 15.0  # Maximum seconds per beat
    
    # Calculate raw durations based on content
    raw_durations = []
    for beat in usable:
        vo_line = str(beat.get("vo_line") or "").strip()
        
        if not vo_line:
            # Empty beat gets minimum duration
            raw_durations.append(MIN_BEAT_DURATION)
            continue
        
        # Count words
        word_count = len(vo_line.split())
        
        # Base duration from word count (convert WPM to seconds)
        duration = (word_count / BASE_WPM) * 60.0
        
        # Add complexity buffer for harder-to-read content
        complexity_score = 0.0
        words = vo_line.split()
        
        for i, word in enumerate(words):
            # Capitalized word not at start = likely proper noun (needs emphasis)
            if i > 0 and word and word[0].isupper():
                complexity_score += 0.3
            # Contains digits (numbers take longer to articulate)
            if any(c.isdigit() for c in word):
                complexity_score += 0.2
        
        # Add punctuation complexity (pauses for emphasis)
        if any(p in vo_line for p in [':', '—', '–', '(', ')', '!', '?']):
            complexity_score += 0.5
        
        # Apply complexity buffer (add up to 30% more time)
        duration *= (1.0 + min(complexity_score * 0.1, 0.3))
        
        # Clamp to reasonable bounds
        duration = max(MIN_BEAT_DURATION, min(MAX_BEAT_DURATION, duration))
        raw_durations.append(duration)
    
    # Calculate total and scale to fit target duration
    total_raw = sum(raw_durations)
    if total_raw > 0:
        scale_factor = target_seconds / total_raw
    else:
        scale_factor = 1.0
    
    # Build normalized beats with scaled durations
    current = 0.0
    normalized: List[Dict[str, Any]] = []
    for i, (beat, raw_dur) in enumerate(zip(usable, raw_durations)):
        start = round(current, 2)
        
        # Scale duration to fit target
        scaled_dur = raw_dur * scale_factor
        
        # For last beat, ensure we hit exactly target_seconds
        if i == len(usable) - 1:
            end = float(target_seconds)
        else:
            end = round(current + scaled_dur, 2)
        
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

    # Prefer model-provided factual segments when returned as top-level
    # ``script_content`` format.
    content_beats = _extract_beats_from_script_content(script_package=script_package)
    if content_beats:
        script["beats"] = _normalize_beats(beats=content_beats, target_seconds=target_seconds)
        script["voiceover"] = " ".join(
            [str(beat.get("vo_line") or "").strip() for beat in script["beats"] if isinstance(beat, dict)]
        )

    beats_raw = script.get("beats")
    beats: List[Dict[str, Any]]
    if isinstance(beats_raw, list):
        beats = [b for b in beats_raw if isinstance(b, dict)]
    else:
        beats = []

    # If beats are missing or obviously invalid, normalize.
    if not beats:
        topic_id = str(topic_brief.get("topic_id") or script_package.get("topic_id") or "topic")
        subtopic_id = str(topic_brief.get("subtopic_id") or script_package.get("subtopic_id") or "sub")
        angle = str(topic_brief.get("angle") or "").strip()

        fallback_beats = [
            {"on_screen_text": "Wait for it…", "vo_line": f"Quick {topic_id.replace('_',' ')} fact you probably missed."},
            {"on_screen_text": subtopic_id.replace("_", " ").title(), "vo_line": f"Today: {subtopic_id.replace('_',' ')}."},
            {"on_screen_text": "The idea", "vo_line": angle or "Here’s the core idea in plain English."},
            {"on_screen_text": "Why it matters", "vo_line": "It changes how you think about what’s possible."},
            {"on_screen_text": "One example", "vo_line": "Imagine a simple scenario that makes it click."},
            {"on_screen_text": "The takeaway", "vo_line": "The takeaway is surprisingly practical."},
            {"on_screen_text": "Follow for more", "vo_line": "Want more quick facts like this?"},
        ]

        script["beats"] = _normalize_beats(beats=fallback_beats, target_seconds=target_seconds)
        script["voiceover"] = " ".join([b.get("vo_line", "").strip() for b in script["beats"] if b.get("vo_line")])
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

    # Ensure beats have usable text (avoid empty VO lines that break downstream audio generation).
    for i, beat in enumerate(script.get("beats") or [], 1):
        if not isinstance(beat, dict):
            continue
        vo = str(beat.get("vo_line") or "").strip()
        ost = str(beat.get("on_screen_text") or "").strip()
        if not ost:
            beat["on_screen_text"] = f"Beat {i}"
        if not vo:
            beat["vo_line"] = f"Here’s a quick point for beat {i}."

    if not str(script.get("voiceover") or "").strip():
        script["voiceover"] = " ".join([str(b.get("vo_line") or "").strip() for b in script["beats"] if isinstance(b, dict)])

    return script_package


class ScriptGenerationAgent:
    """Generate short-form scripts from Topic Brief artifacts."""

    def __init__(self, model: str = GOOGLE_MODEL, fact_store: Optional[FactStore] = None):
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            temperature=0.7,
            google_api_key=GOOGLE_API_KEY,
        )
        self.fact_store = fact_store or FactStore()

    def generate_script_package(
        self,
        topic_brief: Dict[str, Any],
        creative_spec: Optional[Dict[str, Any]] = None,
        use_fact_grounding: bool = True,
        min_facts: int = 5,
        max_facts: int = 10,
    ) -> Dict[str, Any]:
        """Generate a `ScriptPackage`.

        Args:
            topic_brief: A TopicBrief artifact dict.
            creative_spec: Optional CreativeSpec artifact dict.
            use_fact_grounding: Whether to use RAG fact grounding.
            min_facts: Minimum facts to retrieve from store.
            max_facts: Maximum facts to retrieve from store.

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

        # RAG: Retrieve facts from store
        facts = []
        if use_fact_grounding:
            try:
                facts = self.fact_store.query(
                    topic_id=topic_id,
                    subtopic_id=subtopic_id,
                    limit=max_facts,
                    min_engagement_score=3.0,
                )
                
                # If not enough facts, try just topic_id
                if len(facts) < min_facts:
                    facts = self.fact_store.query(
                        topic_id=topic_id,
                        limit=max_facts,
                        min_engagement_score=2.0,
                    )
                
                print(f"[RAG] Retrieved {len(facts)} facts for script generation")
            except Exception as e:
                print(f"[RAG] Warning: Could not retrieve facts: {e}")
                facts = []

        payload: Dict[str, Any] = {
            "topic_brief": topic_brief,
            "creative_spec": creative_spec,
            "target_duration_seconds": target_seconds,
            "time_now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "verified_facts": facts,  # NEW: Provide facts to LLM
        }

        # Build prompt with facts if available
        if facts:
            fact_section = "\n\nVERIFIED FACTS (use these in your script):\n"
            for i, fact in enumerate(facts, 1):
                fact_section += f"{i}. [{fact['fact_id']}] {fact['fact_text']}\n"
                fact_section += f"   Engagement: {fact['engagement_score']:.1f}/10\n"
            payload["facts_instruction"] = fact_section
        else:
            payload["facts_instruction"] = "\n\nNOTE: No verified facts available. Generate a general informational script without making specific factual claims."

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
        
        # Track which facts were used
        parsed.setdefault("fact_sources", [f["fact_id"] for f in facts])

        parsed = _validate_or_fix_script_package(
            script_package=parsed,
            topic_brief=topic_brief,
            creative_spec=creative_spec,
        )

        # Hard guardrail: prevent generic placeholder scripts when fact grounding
        # is enabled and facts are available.
        if use_fact_grounding and facts:
            script_obj = parsed.get("script")
            beats_obj: List[Dict[str, Any]] = []
            if isinstance(script_obj, dict):
                raw_beats = script_obj.get("beats")
                if isinstance(raw_beats, list):
                    beats_obj = [beat for beat in raw_beats if isinstance(beat, dict)]

            if _is_generic_placeholder_beats(beats_obj):
                grounded_beats = _build_fact_grounded_beats_from_facts(
                    facts=facts,
                    topic_id=topic_id,
                    subtopic_id=subtopic_id,
                    target_seconds=target_seconds,
                )
                if not isinstance(script_obj, dict):
                    script_obj = {}
                    parsed["script"] = script_obj

                script_obj["beats"] = grounded_beats
                script_obj["voiceover"] = " ".join(
                    [str(beat.get("vo_line") or "").strip() for beat in grounded_beats if isinstance(beat, dict)]
                )

        return parsed


def generate_offline_script_package(
    topic_brief: Dict[str, Any],
    creative_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a deterministic ScriptPackage without calling an LLM.

    This enables offline / keyless MVP runs while still producing a valid
    artifact for downstream agents.

    Args:
        topic_brief: TopicBrief artifact dict.
        creative_spec: Optional CreativeSpec.

    Returns:
        ScriptPackage dict.
    """
    if not isinstance(topic_brief, dict):
        raise ValueError("topic_brief must be a dict")

    topic_id = str(topic_brief.get("topic_id") or "topic")
    subtopic_id = str(topic_brief.get("subtopic_id") or "sub")

    angle = ""
    if isinstance(topic_brief.get("angle"), str):
        angle = topic_brief.get("angle", "").strip()

    target_seconds = _target_duration_seconds(topic_brief=topic_brief, creative_spec=creative_spec)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Make a compact 7-beat template.
    beats = [
        {"on_screen_text": "Wait for it…", "vo_line": f"Quick {topic_id} fact you probably missed."},
        {"on_screen_text": subtopic_id.replace("_", " ").title(), "vo_line": f"Today: {subtopic_id.replace('_',' ')}."},
        {"on_screen_text": "The idea", "vo_line": angle or "Here's the core idea in plain English."},
        {"on_screen_text": "Why it matters", "vo_line": "It changes how you think about what's possible."},
        {"on_screen_text": "One example", "vo_line": "Imagine a simple scenario that makes it click."},
        {"on_screen_text": "The takeaway", "vo_line": "The takeaway is surprisingly practical."},
        {"on_screen_text": "Follow for more", "vo_line": "Want more quick facts like this?"},
    ]

    script: Dict[str, Any] = {
        "beats": _normalize_beats(beats=beats, target_seconds=target_seconds),
    }
    # Stitch voiceover from beats.
    script["voiceover"] = " ".join([b.get("vo_line", "").strip() for b in script["beats"] if b.get("vo_line")])

    script_package: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "created_at": now,
        "script_package_id": f"sg_{uuid.uuid4().hex}",
        "topic_id": topic_id,
        "subtopic_id": subtopic_id,
        "hook_variants": [
            f"A wild {topic_id} fact…",
            f"This {subtopic_id.replace('_',' ')} detail is unreal",
        ],
        "script": script,
        "caption": f"Quick {topic_id} bite: {subtopic_id.replace('_',' ')}.",
        "hashtags": [
            f"#{topic_id.replace('_','')}",
            "#shorts",
            "#didyouknow",
            "#facts",
            "#learn",
        ],
        "safety_notes": ["Offline script is template-based; verify factual claims before publishing."],
        "generation": {
            "mode": "offline_template",
        },
    }

    return _validate_or_fix_script_package(
        script_package=script_package,
        topic_brief=topic_brief,
        creative_spec=creative_spec,
    )


def create_script_agent(fact_store: Optional[FactStore] = None) -> ScriptGenerationAgent:
    """Factory for ScriptGenerationAgent."""
    return ScriptGenerationAgent(fact_store=fact_store)
