"""Script-to-image retrieval agent.

This agent maps script beats to image search queries, retrieves 1-5 candidate
images for each beat, and writes an artifact that references where each image
fits in the script timeline.

Current provider support:
- Pexels image search (metadata only; no image download)

Provider architecture:
- Ordered `image_sources` fallback chain
- Non-fatal unsupported-provider handling for future source expansion

This module intentionally does not integrate with the render pipeline yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import json
import re
import uuid

from .artifacts.io import write_json
from .config import RESULTS_DIR
from .tools.image_search_tools import ImageSearchError, search_pexels_images, search_wikimedia_images

# Relevance score below which an image candidate is considered too low-quality
_RELEVANCE_THRESHOLD = 2.0


def _write_production_report(run_dir: Path, run_id: str, new_issues: List[Dict[str, Any]]) -> None:
    """Append new_issues to production_report.json, creating the file if absent."""
    report_path = run_dir / "production_report.json"
    if report_path.exists():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
            all_issues: List[Dict[str, Any]] = list(existing.get("issues") or []) + new_issues
        except Exception:
            all_issues = new_issues
    else:
        all_issues = new_issues
    write_json(report_path, {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "issues": all_issues,
        "degraded_scene_count": sum(1 for i in all_issues if i.get("status") == "degraded"),
    })


_RELEVANCE_STOPWORDS = {
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
    "fact",
    "facts",
    "hook",
    "follow",
    "more",
    "know",
    "think",
}


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


def _tokenize_relevance(text: str) -> List[str]:
    """Tokenize text for lightweight relevance scoring.

    Args:
        text: Input text.

    Returns:
        Normalized keyword token list.
    """
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return [token for token in tokens if len(token) > 2 and token not in _RELEVANCE_STOPWORDS]


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
        image_sources: Enabled image providers in fallback order.
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
        self.image_sources = self._normalize_image_sources(self.config.image_sources)

    def _normalize_image_sources(self, image_sources: Sequence[str]) -> List[str]:
        """Normalize provider list to an ordered unique source chain.

        Args:
            image_sources: Raw provider names from config.

        Returns:
            Lower-cased unique provider list. Defaults to ``["pexels"]``.
        """
        normalized: List[str] = []
        for source in image_sources:
            name = str(source or "").strip().lower()
            if not name:
                continue
            if name not in normalized:
                normalized.append(name)

        if not normalized:
            normalized.append("pexels")

        return normalized

    def _search_source(
        self,
        source_name: str,
        query: str,
        per_page: int,
    ) -> List[Dict[str, Any]]:
        """Dispatch search call to a provider implementation.

        Args:
            source_name: Provider name.
            query: Search query.
            per_page: Desired max result count.

        Returns:
            Provider-normalized candidate dicts.

        Raises:
            ImageSearchError: If provider is unavailable or not implemented.
        """
        if source_name == "pexels":
            return search_pexels_images(
                query=query,
                per_page=max(1, int(per_page)),
                orientation=self.config.orientation,
            )

        if source_name == "wikimedia":
            return search_wikimedia_images(
                query=query,
                per_page=max(1, int(per_page)),
                orientation=self.config.orientation,
            )

        raise ImageSearchError(f"Image source '{source_name}' is not implemented")

    def generate_script_image_manifest(
        self,
        script_package: Dict[str, Any],
        scene_ids: Optional[List[str]] = None,
        run_id: str = "",
    ) -> Dict[str, Any]:
        """Generate a beat-referenced image candidate manifest.

        Args:
            script_package: ScriptPackage artifact containing script beats.
            scene_ids: Optional list of scene IDs to process. When provided, only
                matching beats are fetched; others are skipped. When None, all beats
                are processed (existing behaviour, no regression).
            run_id: Pipeline run identifier written into production_report.json.

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
        production_issues: List[Dict[str, Any]] = []

        for beat_index, beat in enumerate(beats):
            # Derive scene_id: prefer explicit field (added by screenplay bridge), else positional
            beat_scene_id = str(beat.get("scene_id") or f"scene_{beat_index + 1:02d}")

            # scene_ids filter: skip beats not in the requested subset
            if scene_ids is not None and beat_scene_id not in scene_ids:
                continue

            segment_context = self._segment_context_for_beat(script=script, beat=beat)
            segment = self._build_segment_candidate(
                beat=beat,
                beat_index=beat_index,
                topic_hint=topic_hint,
                segment_context=segment_context,
                scene_id=beat_scene_id,
            )
            segment_assets.append(segment)

            # Detect degraded segments and accumulate production issues
            if segment["candidate_count"] == 0:
                production_issues.append({
                    "agent": "ScriptImageAgent",
                    "scene_id": beat_scene_id,
                    "status": "degraded",
                    "issue": "no_relevant_image",
                    "detail": f"No candidates found for queries: {segment['queries']}",
                    "suggestion": "Rephrase visual.description to be more concrete and specific",
                    "revision_field": "visual",
                    "revision_possible": True,
                })
            else:
                best_score = self._best_relevance_score(segment)
                if best_score < _RELEVANCE_THRESHOLD:
                    production_issues.append({
                        "agent": "ScriptImageAgent",
                        "scene_id": beat_scene_id,
                        "status": "degraded",
                        "issue": "no_relevant_image",
                        "detail": f"Best result relevance {best_score:.2f}, threshold {_RELEVANCE_THRESHOLD:.2f}",
                        "suggestion": "Rephrase visual.description to be more concrete and specific",
                        "revision_field": "visual",
                        "revision_possible": True,
                    })

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

        # Write production report (merges with any existing report from audio agent)
        _effective_run_id = run_id or str(script_package.get("script_package_id") or "unknown")
        _write_production_report(self.output_dir, _effective_run_id, production_issues)
        if production_issues:
            print(f"[WARN] ScriptImageAgent: {len(production_issues)} degraded scene(s) written to production_report.json")

        return manifest

    def _best_relevance_score(self, segment: Dict[str, Any]) -> float:
        """Return the highest relevance score among all candidates in a segment."""
        best = 0.0
        for cand in segment.get("candidates") or []:
            score = float((cand.get("metadata") or {}).get("relevance", {}).get("score") or 0.0)
            if score > best:
                best = score
        return best

    def _build_segment_candidate(
        self,
        beat: Dict[str, Any],
        beat_index: int,
        topic_hint: str,
        segment_context: str = "",
        scene_id: str = "",
    ) -> Dict[str, Any]:
        """Build candidate list for a single script beat.

        Args:
            beat: Script beat.
            beat_index: Zero-based beat index.
            topic_hint: Topic-level text context.
            scene_id: Optional explicit scene identifier (from screenplay bridge).

        Returns:
            Segment candidate object.
        """
        beat_id = scene_id or f"beat_{beat_index + 1:02d}"
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
        configured_sources = list(self.image_sources)
        max_candidates = max(1, int(self.config.max_candidates_per_segment))

        for query in queries:
            if len(candidates) >= max_candidates:
                break

            for source_name in configured_sources:
                if len(candidates) >= max_candidates:
                    break

                sources_attempted.append(source_name)
                remaining = max(1, max_candidates - len(candidates))

                try:
                    results = self._search_source(
                        source_name=source_name,
                        query=query,
                        per_page=remaining,
                    )
                except ImageSearchError as exc:
                    provider_errors.append(f"{source_name}: {exc}")
                    continue

                for item in results:
                    if len(candidates) >= max_candidates:
                        break

                    url = str(item.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue

                    seen_urls.add(url)
                    candidates.append(
                        {
                            "candidate_id": f"cand_{uuid.uuid4().hex[:8]}",
                            "source": str(item.get("source") or source_name),
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
        object_terms = _extract_focus_terms(
            text=f"{str(beat.get('vo_line') or '')} {segment_context}",
            max_terms=5,
        )
        candidates = self._rerank_candidates(
            candidates=candidates,
            beat=beat,
            queries=queries,
            topic_hint=topic_hint,
            segment_context=segment_context,
            object_terms=object_terms,
        )
        candidates = candidates[:max_candidates]
        candidate_sources = sorted(
            {
                str(candidate.get("source") or "").strip().lower()
                for candidate in candidates
                if str(candidate.get("source") or "").strip()
            }
        )
        source_fallback_used = bool(candidate_sources) and (
            bool(configured_sources)
            and any(source != configured_sources[0] for source in candidate_sources)
        )

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
                "configured_sources": configured_sources,
                "sources_attempted": list(dict.fromkeys(sources_attempted)),
                "candidate_sources": candidate_sources,
                "provider_errors": provider_errors,
                "source_fallback_strategy": "ordered_provider_chain",
                "source_fallback_used": source_fallback_used,
                "segment_context": segment_context,
                "reranked_by_alt_relevance": True,
            },
        }

    def _rerank_candidates(
        self,
        candidates: List[Dict[str, Any]],
        beat: Dict[str, Any],
        queries: List[str],
        topic_hint: str,
        segment_context: str,
        object_terms: List[str],
    ) -> List[Dict[str, Any]]:
        """Rerank candidates using alt text relevance to script context.

        Args:
            candidates: Raw candidate list.
            beat: Current script beat.
            queries: Search queries used for retrieval.
            topic_hint: Topic-level hint.
            segment_context: Optional segment context.
            object_terms: Focus terms extracted from beat and context.

        Returns:
            Reranked candidate list (highest relevance first).
        """
        if not candidates:
            return []

        beat_text = _normalize_phrase(
            f"{str(beat.get('on_screen_text') or '')} {str(beat.get('vo_line') or '')}"
        )
        topic_anchor = _topic_anchor(topic_hint)

        scored: List[Dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            score_payload = self._score_candidate_alt_relevance(
                candidate=candidate,
                beat_text=beat_text,
                queries=queries,
                topic_anchor=topic_anchor,
                segment_context=segment_context,
                object_terms=object_terms,
            )

            updated = dict(candidate)
            metadata = dict(updated.get("metadata") or {})
            metadata["relevance"] = score_payload
            updated["metadata"] = metadata

            # preserve deterministic fallback order on ties by original index
            updated["_rank_score"] = float(score_payload.get("score", 0.0))
            updated["_rank_index"] = index
            scored.append(updated)

        scored.sort(
            key=lambda item: (
                float(item.get("_rank_score", 0.0)),
                self._candidate_resolution_area(item),
                -int(item.get("_rank_index", 0)),
            ),
            reverse=True,
        )

        cleaned: List[Dict[str, Any]] = []
        for item in scored:
            item.pop("_rank_score", None)
            item.pop("_rank_index", None)
            cleaned.append(item)

        return cleaned

    def _score_candidate_alt_relevance(
        self,
        candidate: Dict[str, Any],
        beat_text: str,
        queries: List[str],
        topic_anchor: str,
        segment_context: str,
        object_terms: List[str],
    ) -> Dict[str, Any]:
        """Score one candidate using its alt text against script/query context.

        Args:
            candidate: Candidate entry.
            beat_text: Current beat text content.
            queries: Search queries used.
            topic_anchor: Topic anchor phrase.
            segment_context: Segment detail text.
            object_terms: Focus terms for entities/objects.

        Returns:
            Relevance metadata including score, matches, and penalties.
        """
        metadata = candidate.get("metadata") or {}
        alt_raw = _normalize_phrase(str(metadata.get("alt") or ""))
        alt_lower = alt_raw.lower()

        baseline_tokens = set(
            _tokenize_relevance(
                f"{beat_text} {' '.join(queries)} {topic_anchor} {segment_context}"
            )
        )
        alt_tokens = set(_tokenize_relevance(alt_raw))

        overlap = sorted(token for token in baseline_tokens.intersection(alt_tokens))
        score = float(len(overlap)) * 1.5
        script_lower = f"{beat_text} {segment_context} {topic_anchor}".lower()

        bonuses: List[str] = []
        if "tank" in script_lower and "tank" in alt_lower:
            score += 3.0
            bonuses.append("primary_object_tank_matched")

        phrase_matches: List[str] = []
        generic_phrases = {"world", "war", "tank", "tanks", "fact", "facts"}
        for phrase in object_terms:
            clean_phrase = _normalize_phrase(phrase).lower()
            if not clean_phrase or clean_phrase in generic_phrases:
                continue
            if clean_phrase in alt_lower:
                score += 2.5
                phrase_matches.append(clean_phrase)

        penalties: List[str] = []
        if "world war 1" in script_lower and ("world war ii" in alt_lower or "wwii" in alt_lower):
            score -= 4.0
            penalties.append("era_conflict_ww1_vs_ww2")

        if "tank" in script_lower and "tank" not in alt_lower:
            score -= 1.5
            penalties.append("missing_primary_object_tank")

        return {
            "score": round(score, 3),
            "alt_text": alt_raw,
            "token_overlap": overlap,
            "phrase_matches": phrase_matches,
            "bonuses": bonuses,
            "penalties": penalties,
        }

    def _candidate_resolution_area(self, candidate: Dict[str, Any]) -> int:
        """Get candidate pixel area for deterministic tie-breaking.

        Args:
            candidate: Candidate dictionary.

        Returns:
            Resolution area (width * height), or 0.
        """
        resolution = candidate.get("resolution")
        if not isinstance(resolution, list) or len(resolution) != 2:
            return 0
        width = int(resolution[0]) if isinstance(resolution[0], int) else 0
        height = int(resolution[1]) if isinstance(resolution[1], int) else 0
        return max(0, width * height)

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
