"""Script-to-image retrieval agent.

This agent maps script beats to image search queries, retrieves 1-5 candidate
images for each beat, and writes an artifact that references where each image
fits in the script timeline.

Current provider support:
- Pexels image search (metadata only; no image download)

This module intentionally does not integrate with the render pipeline yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import re
import uuid

from .artifacts.io import write_json
from .config import RESULTS_DIR
from .tools.image_search_tools import ImageSearchError, search_pexels_images


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 `Z` format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float safely.

    Args:
        value: Input value.
        default: Fallback value if conversion fails.

    Returns:
        Float value.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_phrase(value: str) -> str:
    """Normalize text phrase for query generation.

    Args:
        value: Raw phrase.

    Returns:
        Cleaned phrase.
    """
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    cleaned = cleaned.replace("_", " ")
    return cleaned


def _topic_anchor(topic_hint: str) -> str:
    """Build a clean topic anchor phrase for retrieval queries.

    Args:
        topic_hint: Combined topic/subtopic hint.

    Returns:
        Query-safe anchor phrase.
    """
    anchor = _normalize_phrase(topic_hint)
    # Remove overly generic trailing tokens that dilute query quality.
    anchor = re.sub(r"\b(fact|facts|did you know|shorts?)\b", "", anchor, flags=re.IGNORECASE)
    anchor = re.sub(r"\s+", " ", anchor).strip()
    return anchor


def _extract_focus_terms(text: str, max_terms: int = 3) -> List[str]:
    """Extract likely objects/entities from script text.

    Heuristic extraction favors:
    - Alphanumeric special terms (e.g., R2-D2)
    - Capitalized multi-word phrases (proper nouns)
    - Long non-stopword tokens as fallback

    Args:
        text: Input beat text.
        max_terms: Maximum terms to return.

    Returns:
        Ranked list of candidate entity phrases.
    """
    raw = _normalize_phrase(text)
    if not raw:
        return []

    seen: set[str] = set()
    terms: List[str] = []
    generic_terms = {
        "hook",
        "fact",
        "facts",
        "follow",
        "more",
        "think",
        "know",
        "here",
        "surprising",
        "early",
        "finally",
    }

    # 1) Token patterns like R2D2, R2-D2, C-3PO, T-800.
    special_tokens = re.findall(r"\b[A-Za-z]+\d+[A-Za-z\d-]*\b|\b\d+[A-Za-z][A-Za-z\d-]*\b", raw)
    for token in special_tokens:
        norm = token.strip(" .,!?:;\"'()[]{}")
        key = norm.lower()
        if norm and key not in seen:
            seen.add(key)
            terms.append(norm)

    # 2) Capitalized word spans (proper noun-ish).
    proper_spans = re.findall(r"\b(?:[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,3})\b", raw)
    for span in proper_spans:
        norm = _normalize_phrase(span)
        if len(norm) < 3:
            continue
        if norm.lower() in generic_terms:
            continue
        key = norm.lower()
        if key not in seen:
            seen.add(key)
            terms.append(norm)

    # 3) Fallback meaningful tokens.
    stopwords = {
        "the",
        "and",
        "with",
        "that",
        "this",
        "from",
        "have",
        "were",
        "when",
        "where",
        "what",
        "which",
        "into",
        "about",
        "your",
        "their",
        "they",
        "them",
        "there",
        "here",
        "would",
        "could",
        "should",
        "might",
    }
    for token in re.findall(r"\b[a-zA-Z][a-zA-Z0-9-]{3,}\b", raw):
        lower = token.lower()
        if lower in stopwords or lower in generic_terms:
            continue
        if lower not in seen:
            seen.add(lower)
            terms.append(token)

    return terms[: max(1, int(max_terms))]


def _build_search_queries(
    beat: Dict[str, Any],
    topic_hint: str,
    segment_context: str = "",
    max_queries: int = 3,
) -> List[str]:
    """Build search queries from a script beat.

    Args:
        beat: Beat dictionary from ScriptPackage.
        topic_hint: Topic context for grounding searches.
        max_queries: Maximum number of generated queries.

    Returns:
        Ordered list of search queries.
    """
    on_screen_text = _normalize_phrase(str(beat.get("on_screen_text") or ""))
    vo_line = _normalize_phrase(str(beat.get("vo_line") or ""))
    segment_context = _normalize_phrase(segment_context)
    anchor = _topic_anchor(topic_hint)

    focus_input = f"{on_screen_text} {vo_line} {segment_context}".strip()
    focus_terms = _extract_focus_terms(focus_input, max_terms=max_queries)

    queries: List[str] = []
    seen: set[str] = set()

    # Always include a topic-level anchor to keep retrieval on-subject.
    if anchor:
        key = anchor.lower()
        seen.add(key)
        queries.append(anchor)

    for term in focus_terms:
        query = _normalize_phrase(term)
        if anchor and anchor.lower() not in query.lower():
            query = f"{query} {anchor}".strip()
        key = query.lower()
        if query and key not in seen:
            seen.add(key)
            queries.append(query)

    if not queries:
        fallback = anchor or on_screen_text or vo_line or topic_hint or "historical reference"
        queries = [_normalize_phrase(fallback)]

    return queries[: max(1, int(max_queries))]


@dataclass(frozen=True)
class ScriptImageConfig:
    """Configuration for script-image retrieval.

    Attributes:
        output_dir: Destination directory for image artifacts.
        image_sources: Enabled image providers.
        min_candidates_per_segment: Minimum number of candidates per beat.
        max_candidates_per_segment: Maximum number of candidates per beat.
        max_queries_per_segment: Maximum queries generated per beat.
        orientation: Preferred image orientation.
    """

    output_dir: Optional[Path] = None
    image_sources: Sequence[str] = ("pexels",)
    min_candidates_per_segment: int = 1
    max_candidates_per_segment: int = 5
    max_queries_per_segment: int = 3
    orientation: str = "portrait"


class ScriptImageRetrievalAgent:
    """Retrieve image candidates for script beats and write artifacts."""

    def __init__(self, config: Optional[ScriptImageConfig] = None):
        """Initialize agent.

        Args:
            config: Optional retrieval configuration.
        """
        self.config = config or ScriptImageConfig()
        self.output_dir = self.config.output_dir or (RESULTS_DIR / f"sim_{uuid.uuid4().hex[:8]}")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_script_image_manifest(self, script_package: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a beat-referenced image candidate manifest.

        Args:
            script_package: ScriptPackage artifact containing script beats.

        Returns:
            ScriptImageManifest dictionary.

        Raises:
            ValueError: If script_package is invalid.
        """
        if not isinstance(script_package, dict):
            raise ValueError("script_package must be a dict")

        script = script_package.get("script")
        if not isinstance(script, dict):
            raise ValueError("script_package.script must be a dict")

        beats_raw = script.get("beats")
        if not isinstance(beats_raw, list):
            raise ValueError("script_package.script.beats must be a list")

        beats: List[Dict[str, Any]] = [beat for beat in beats_raw if isinstance(beat, dict)]
        topic_hint = _normalize_phrase(
            f"{script_package.get('topic_id') or ''} {script_package.get('subtopic_id') or ''}"
        )

        segment_assets: List[Dict[str, Any]] = []
        for beat_index, beat in enumerate(beats):
            segment_context = self._segment_context_for_beat(script=script, beat=beat)
            segment_assets.append(
                self._build_segment_candidate(
                    beat=beat,
                    beat_index=beat_index,
                    topic_hint=topic_hint,
                    segment_context=segment_context,
                )
            )

        manifest = {
            "schema_version": "1.0.0",
            "script_image_manifest_id": f"sim_{uuid.uuid4().hex[:8]}",
            "created_at": _utc_now_iso(),
            "script_package_ref": script_package.get("script_package_id"),
            "topic_id": script_package.get("topic_id"),
            "subtopic_id": script_package.get("subtopic_id"),
            "policy": {
                "intent": "Use license-friendly stock imagery with attribution metadata",
                "note": "Review usage rights and attribution requirements before publishing",
            },
            "total_segments": len(segment_assets),
            "segments": segment_assets,
        }

        write_json(self.output_dir / "script_image_manifest.json", manifest)
        return manifest

    def _build_segment_candidate(
        self,
        beat: Dict[str, Any],
        beat_index: int,
        topic_hint: str,
        segment_context: str = "",
    ) -> Dict[str, Any]:
        """Build candidate list for a single script beat.

        Args:
            beat: Script beat.
            beat_index: Zero-based beat index.
            topic_hint: Topic-level text context.

        Returns:
            Segment candidate object.
        """
        beat_id = f"beat_{beat_index + 1:02d}"
        queries = _build_search_queries(
            beat=beat,
            topic_hint=topic_hint,
            segment_context=segment_context,
            max_queries=self.config.max_queries_per_segment,
        )

        candidates: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        sources_attempted: List[str] = []
        provider_errors: List[str] = []

        for query in queries:
            if len(candidates) >= int(self.config.max_candidates_per_segment):
                break

            if "pexels" in self.config.image_sources:
                sources_attempted.append("pexels")
                try:
                    results = search_pexels_images(
                        query=query,
                        per_page=int(self.config.max_candidates_per_segment),
                        orientation=self.config.orientation,
                    )
                except ImageSearchError as exc:
                    provider_errors.append(str(exc))
                    results = []

                for item in results:
                    if len(candidates) >= int(self.config.max_candidates_per_segment):
                        break

                    url = str(item.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue

                    seen_urls.add(url)
                    candidates.append(
                        {
                            "candidate_id": f"cand_{uuid.uuid4().hex[:8]}",
                            "source": str(item.get("source") or "pexels"),
                            "url": url,
                            "resolution": item.get("resolution") or [0, 0],
                            "attribution": item.get("attribution") or {},
                            "metadata": {
                                "search_query": query,
                                **(item.get("metadata") or {}),
                            },
                        }
                    )

        min_candidates = max(0, int(self.config.min_candidates_per_segment))
        max_candidates = max(1, int(self.config.max_candidates_per_segment))
        candidates = candidates[:max_candidates]

        return {
            "segment_id": beat_id,
            "beat_index": beat_index,
            "script_ref": {
                "t_start_s": _safe_float(beat.get("t_start_s"), 0.0),
                "t_end_s": _safe_float(beat.get("t_end_s"), 0.0),
                "on_screen_text": str(beat.get("on_screen_text") or ""),
                "vo_line": str(beat.get("vo_line") or ""),
            },
            "object_of_interest": (_extract_focus_terms(str(beat.get("vo_line") or ""), max_terms=1) or [None])[0],
            "queries": queries,
            "candidate_count": len(candidates),
            "required_candidate_min": min_candidates,
            "candidates": candidates,
            "status": "ok" if len(candidates) >= min_candidates else "insufficient_candidates",
            "retrieval_notes": {
                "sources_attempted": list(dict.fromkeys(sources_attempted)),
                "provider_errors": provider_errors,
                "segment_context": segment_context,
            },
        }

    def _segment_context_for_beat(self, script: Dict[str, Any], beat: Dict[str, Any]) -> str:
        """Derive optional segment context for a beat.

        If the script includes a ``segments`` list, this maps ``Fact N`` beats
        to segment ``N`` and returns visual/audio context to improve retrieval.

        Args:
            script: Script object from ScriptPackage.
            beat: Current beat.

        Returns:
            Combined segment context string, or empty string.
        """
        segments = script.get("segments")
        if not isinstance(segments, list):
            return ""

        label = str(beat.get("on_screen_text") or "").strip().lower()
        match = re.match(r"fact\s+(\d+)", label)
        if not match:
            return ""

        fact_index = int(match.group(1)) - 1
        if fact_index < 0 or fact_index >= len(segments):
            return ""

        segment = segments[fact_index]
        if not isinstance(segment, dict):
            return ""

        visual = _normalize_phrase(str(segment.get("visual_description") or ""))
        audio = _normalize_phrase(str(segment.get("audio_narration") or ""))
        return _normalize_phrase(f"{visual} {audio}")


def create_script_image_agent(config: Optional[ScriptImageConfig] = None) -> ScriptImageRetrievalAgent:
    """Create a `ScriptImageRetrievalAgent`.

    Args:
        config: Optional retrieval config.

    Returns:
        Script image retrieval agent.
    """
    return ScriptImageRetrievalAgent(config=config)
