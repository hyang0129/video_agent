"""ConceptAgent: generates N distinct video concepts from a TopicBrief."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import make_llm
from ..utils.json_utils import safe_json_loads
from ..artifacts.screenplay import new_concept

_FORMAT_LIBRARY_DIR = Path(__file__).parent / "format_library"
_ALL_FORMATS = ["facts", "storytime", "tutorial", "debate"]

_SYSTEM_PROMPT = """\
You are a short-form video concept writer.

Given a TopicBrief, generate exactly {n} distinct video concepts.
Each concept must use a different hook style and emotional angle.
Available formats: {formats}.

Output a JSON array of exactly {n} objects. Each object must have:
- "format": one of the available formats (use each format at most once)
- "hook": opening line, 15 words or fewer, hooks the viewer immediately
- "angle": one sentence — the specific lens or framing for this concept

Return ONLY the JSON array. No markdown, no explanation.
"""


def _estimate_hook_strength(hook: str) -> float:
    score = 0.5
    if hook.strip().endswith("?"):
        score += 0.15
    if any(c.isdigit() for c in hook):
        score += 0.1
    words = hook.split()
    if 6 <= len(words) <= 12:
        score += 0.1
    high_valence = {"never", "always", "secret", "wrong", "real", "truth", "shocking", "hidden"}
    if any(w.lower() in high_valence for w in words):
        score += 0.15
    return min(1.0, score)


class ConceptAgent:
    def __init__(self) -> None:
        self.llm = make_llm(temperature=0.9)

    def _load_format_names(self, formats: list[str] | None) -> list[str]:
        available = formats or _ALL_FORMATS
        # validate each format has a template file
        return [f for f in available if (_FORMAT_LIBRARY_DIR / f"{f}.json").exists()]

    def generate_concepts(
        self,
        topic_brief: dict[str, Any],
        n_concepts: int = 3,
        formats: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a list of Concept dicts ordered by hook_strength_estimate descending."""
        fmt_names = self._load_format_names(formats)
        if not fmt_names:
            fmt_names = _ALL_FORMATS[:n_concepts]

        # cap n to available formats
        n = min(n_concepts, len(fmt_names))
        fmt_subset = fmt_names[:n]

        system = _SYSTEM_PROMPT.format(n=n, formats=", ".join(fmt_subset))
        human_payload = {
            "topic_brief": topic_brief,
            "requested_concepts": n,
            "formats": fmt_subset,
        }

        messages = [
            SystemMessage(content=system),
            HumanMessage(content="Generate concepts for:\n\n" + json.dumps(human_payload, ensure_ascii=False)),
        ]

        response = self.llm.invoke(messages)
        raw = safe_json_loads(str(response.content))

        if not isinstance(raw, list):
            # tolerate {concepts: [...]} wrapper
            if isinstance(raw, dict):
                for key in ("concepts", "items", "results"):
                    if isinstance(raw.get(key), list):
                        raw = raw[key]
                        break
            if not isinstance(raw, list):
                raw = []

        topic_brief_ref = str(topic_brief.get("topic_brief_id") or topic_brief.get("topic_id") or "")
        concepts: list[dict[str, Any]] = []

        for item in raw[:n]:
            if not isinstance(item, dict):
                continue
            hook = str(item.get("hook") or "").strip()
            angle = str(item.get("angle") or "").strip()
            fmt = str(item.get("format") or "facts").strip()
            if not hook:
                continue
            strength = _estimate_hook_strength(hook)
            concepts.append(new_concept(
                topic_brief_ref=topic_brief_ref,
                fmt=fmt,
                hook=hook,
                angle=angle,
                hook_strength_estimate=strength,
            ))

        # Sort descending by hook strength
        concepts.sort(key=lambda c: c["hook_strength_estimate"], reverse=True)
        return concepts
