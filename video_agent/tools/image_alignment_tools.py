"""Image alignment evaluator with rubric-based scoring.

Issue 2.6: Replaces the passthrough evaluator from 1.7 with a vision-model
scorer that evaluates candidate images against scene context on 5 axes.

Backends:
  - online: multimodal LLM via LangChain (GPT-4o, Gemini, Claude)
  - local: deferred (LLaVA/CogVLM — not yet implemented)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

import requests
from PIL import Image

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rubric definition
# ---------------------------------------------------------------------------

RUBRIC_AXES: List[Tuple[str, float, str]] = [
    ("subject", 0.35, "Does the image contain the primary subject described in the scene?"),
    ("setting", 0.25, "Does the time period, location, and environment match?"),
    ("mood", 0.15, "Does the image mood match the scene mood?"),
    ("composition", 0.15, "Is the framing usable for 9:16 vertical video?"),
    ("artifacts", 0.10, "Are there watermarks, text overlays, or distracting elements? (5=clean, 1=heavily marked)"),
]

AXIS_NAMES = [name for name, _, _ in RUBRIC_AXES]
AXIS_WEIGHTS = {name: weight for name, weight, _ in RUBRIC_AXES}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlignmentScore:
    """Scoring result for a single candidate image."""

    candidate_id: str
    weighted_score: float
    axis_scores: Dict[str, int]
    raw_rationale: str = ""
    error: str = ""


@dataclass
class SceneAlignmentResult:
    """Aggregated evaluation result for one scene."""

    scene_id: str
    best_score: float = 0.0
    best_candidate_id: str = ""
    best_candidate: Any = None
    scores_by_axis: Dict[str, int] = field(default_factory=dict)
    candidates_evaluated: int = 0
    early_exit: bool = False
    revision_requested: bool = False
    all_scores: List[AlignmentScore] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "scene_id": self.scene_id,
            "best_score": round(self.best_score, 2),
            "best_candidate_id": self.best_candidate_id,
            "scores_by_axis": self.scores_by_axis,
            "candidates_evaluated": self.candidates_evaluated,
            "early_exit": self.early_exit,
            "revision_requested": self.revision_requested,
            "all_scores": [
                {
                    "candidate_id": s.candidate_id,
                    "weighted_score": round(s.weighted_score, 2),
                    "axis_scores": s.axis_scores,
                    "raw_rationale": s.raw_rationale,
                    "error": s.error,
                }
                for s in self.all_scores
            ],
        }


# ---------------------------------------------------------------------------
# Backend protocol and implementations
# ---------------------------------------------------------------------------


class ImageEvalBackend(Protocol):
    """Protocol for pluggable image evaluation backends."""

    def score_image(
        self,
        image_url: str,
        visual_description: str,
        vo_line: str,
        scene_mood: str,
        image_bytes: Optional[bytes] = None,
    ) -> AlignmentScore: ...


def _compute_weighted_score(axis_scores: Dict[str, int]) -> float:
    """Compute weighted average from per-axis scores."""
    total = 0.0
    for name, weight in AXIS_WEIGHTS.items():
        total += weight * float(axis_scores.get(name, 3))
    return round(total, 2)


def _build_rubric_prompt(
    visual_description: str,
    vo_line: str,
    scene_mood: str,
) -> str:
    """Build the structured scoring prompt for the vision model."""
    return (
        "Score this image for use in a short-form video scene.\n\n"
        f"SCENE DESCRIPTION: {visual_description}\n"
        f"NARRATION: {vo_line}\n"
        f"TARGET MOOD: {scene_mood or 'neutral'}\n"
        "VIDEO FORMAT: 9:16 vertical (portrait)\n\n"
        "Rate each axis from 1 (poor) to 5 (excellent):\n"
        "1. subject (weight 0.35): Does the image show the described subject?\n"
        "2. setting (weight 0.25): Does the era, location, environment match?\n"
        "3. mood (weight 0.15): Does the image mood match the target mood?\n"
        "4. composition (weight 0.15): Is the framing usable for 9:16 vertical crop?\n"
        "5. artifacts (weight 0.10): Is the image clean of watermarks, text overlays, "
        "or distracting elements? (5=clean, 1=heavily marked)\n\n"
        'Return ONLY valid JSON: {"subject": N, "setting": N, "mood": N, '
        '"composition": N, "artifacts": N}\n'
        "where each N is an integer from 1 to 5."
    )


def _parse_scores_response(text: str) -> Optional[Dict[str, int]]:
    """Extract axis scores from LLM response text.

    Returns the parsed scores dict, or None if parsing fails.
    """
    if not text:
        _log.error("[ERROR] ImageAlignmentEvaluator: empty LLM response, cannot parse scores")
        return None

    match = re.search(r"\{[^}]+\}", text)
    if not match:
        _log.error("[ERROR] ImageAlignmentEvaluator: no JSON object found in LLM response: %s", text[:200])
        return None

    try:
        raw = json.loads(match.group(0))
        scores: Dict[str, int] = {}
        for name in AXIS_NAMES:
            val = raw.get(name)
            if isinstance(val, (int, float)):
                scores[name] = max(1, min(5, int(round(val))))
            else:
                scores[name] = 3
        return scores
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        _log.error("[ERROR] ImageAlignmentEvaluator: failed to parse JSON from LLM response: %s -- response: %s", exc, text[:200])
        return None


_RE_CODE_FENCE = re.compile(r"```(?:json)?\s*\{[^}]+\}\s*```", re.DOTALL)
_RE_MARKDOWN_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _extract_rationale(text: str) -> str:
    """Extract the human-readable rationale from an LLM scoring response.

    Strips JSON code fences and markdown bold markers so the result reads
    as plain text in a JSON file.
    """
    if not text:
        return ""
    # Remove ```json {...} ``` blocks (the scores are stored separately)
    cleaned = _RE_CODE_FENCE.sub("", text)
    # Remove markdown bold markers
    cleaned = _RE_MARKDOWN_BOLD.sub(r"\1", cleaned)
    # Collapse blank lines left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_MAX_IMAGE_DIM = 480


def _compress_to_jpeg(image_bytes: bytes) -> bytes:
    """Resize image to fit within 480x480 (keeping aspect ratio) and compress to JPEG."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((_MAX_IMAGE_DIM, _MAX_IMAGE_DIM), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _fetch_image_bytes(url: str, timeout: int = 15) -> Optional[bytes]:
    """Fetch image bytes from a URL. Returns None on failure."""
    try:
        headers: Dict[str, str] = {}
        if "wikimedia.org" in url or "wikipedia.org" in url:
            from .image_search_tools import wikimedia_rate_limiter
            wikimedia_rate_limiter.throttle()
            headers["User-Agent"] = "Mozilla/5.0 (compatible; VideoAgent/1.0)"
        resp = requests.get(url, headers=headers, timeout=timeout, stream=False)
        resp.raise_for_status()
        return resp.content
    except requests.exceptions.HTTPError as exc:
        _log.error("[ERROR] ImageAlignmentEvaluator: HTTP %s fetching %s", exc.response.status_code, url[:80])
        return None
    except requests.exceptions.Timeout:
        _log.error("[ERROR] ImageAlignmentEvaluator: timeout fetching %s", url[:80])
        return None
    except Exception as exc:
        _log.error("[ERROR] ImageAlignmentEvaluator: failed to fetch image from %s: %s: %s", url[:80], type(exc).__name__, exc)
        return None


class OnlineImageEvalBackend:
    """Score images using a vision-capable LLM via LangChain."""

    def score_image(
        self,
        image_url: str,
        visual_description: str,
        vo_line: str,
        scene_mood: str,
        image_bytes: Optional[bytes] = None,
    ) -> AlignmentScore:
        from ..config import make_llm
        from langchain_core.messages import HumanMessage

        if image_bytes is None:
            image_bytes = _fetch_image_bytes(image_url)
        if image_bytes is None:
            _log.error("[ERROR] Skipping scoring for %s -- image not available", image_url[:80])
            return AlignmentScore(
                candidate_id="",
                weighted_score=0.0,
                axis_scores={},
                error="image_download_failed",
            )

        try:
            image_bytes = _compress_to_jpeg(image_bytes)
        except Exception as exc:
            _log.error("[ERROR] ImageAlignmentEvaluator: failed to compress image from %s: %s: %s", image_url[:80], type(exc).__name__, exc)
            return AlignmentScore(
                candidate_id="",
                weighted_score=0.0,
                axis_scores={},
                error=f"image_compress_failed: {type(exc).__name__}",
            )

        b64 = base64.b64encode(image_bytes).decode("ascii")
        prompt = _build_rubric_prompt(visual_description, vo_line, scene_mood)

        llm = make_llm(temperature=0.0)
        msg = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ])

        try:
            result = llm.invoke([msg])
            response_text = str(result.content)
        except Exception as exc:
            _log.error("[ERROR] ImageAlignmentEvaluator: LLM call failed for %s: %s: %s", image_url[:80], type(exc).__name__, exc)
            return AlignmentScore(
                candidate_id="",
                weighted_score=0.0,
                axis_scores={},
                error=f"llm_call_failed: {type(exc).__name__}",
            )

        axis_scores = _parse_scores_response(response_text)
        rationale = _extract_rationale(response_text)
        if axis_scores is None:
            return AlignmentScore(
                candidate_id="",
                weighted_score=0.0,
                axis_scores={},
                error="llm_response_parse_failed",
                raw_rationale=rationale,
            )

        weighted = _compute_weighted_score(axis_scores)

        return AlignmentScore(
            candidate_id="",
            weighted_score=weighted,
            axis_scores=axis_scores,
            raw_rationale=rationale,
        )


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------


class ImageAlignmentEvaluator:
    """Rubric-based image alignment evaluator.

    Scores candidate images against scene context using a vision-capable LLM.
    Supports streaming (early exit on good match) and batch (score all, pick
    best) modes, with a two-threshold system for accept/reject decisions.
    """

    def __init__(
        self,
        backend: Optional[ImageEvalBackend] = None,
        accept_threshold: Optional[float] = None,
        min_threshold: Optional[float] = None,
        mode: Optional[str] = None,
    ):
        from ..config import (
            IMAGE_EVAL_BACKEND,
            IMAGE_EVAL_MODE,
            IMAGE_EVAL_ACCEPT_THRESHOLD,
            IMAGE_EVAL_MIN_THRESHOLD,
        )

        self.accept_threshold = accept_threshold if accept_threshold is not None else IMAGE_EVAL_ACCEPT_THRESHOLD
        self.min_threshold = min_threshold if min_threshold is not None else IMAGE_EVAL_MIN_THRESHOLD
        self.mode = mode or IMAGE_EVAL_MODE

        if backend is not None:
            self._backend = backend
        elif IMAGE_EVAL_BACKEND == "local":
            raise NotImplementedError(
                "Local image evaluation backend not yet implemented. "
                "Use IMAGE_EVAL_BACKEND=online."
            )
        else:
            self._backend = OnlineImageEvalBackend()

    def select_best(
        self,
        candidates: list[Any],
        scene_context: Optional[Dict[str, str]] = None,
    ) -> Tuple[Any, Optional[SceneAlignmentResult]]:
        """Score candidates and return the best one.

        Args:
            candidates: Candidate objects (dicts or VisualAssetCandidate
                dataclasses) with a ``url`` attribute or key.
            scene_context: Dict with keys ``visual_description``,
                ``vo_line``, ``scene_mood``, ``scene_id``.
                When None, falls back to passthrough (backward compat).

        Returns:
            Tuple of (best_candidate or None, SceneAlignmentResult or None).
            When scene_context is None, returns (first candidate, None).
        """
        if not candidates:
            return (None, None)

        # Backward-compatible passthrough when no context provided
        if scene_context is None:
            return (candidates[0], None)

        scene_id = scene_context.get("scene_id", "unknown")
        visual_description = scene_context.get("visual_description", "")
        vo_line = scene_context.get("vo_line", "")
        scene_mood = scene_context.get("scene_mood", "neutral")

        result = SceneAlignmentResult(scene_id=scene_id)

        for candidate in candidates:
            url = self._get_url(candidate)
            if not url:
                continue

            candidate_id = self._get_candidate_id(candidate)

            # Prefer local file over re-downloading from URL.
            image_bytes: Optional[bytes] = None
            local_path = self._get_local_path(candidate)
            if local_path:
                try:
                    image_bytes = Path(local_path).read_bytes()
                except OSError as exc:
                    _log.warning("[WARN] Failed to read local image %s: %s", local_path, exc)

            score = self._backend.score_image(
                image_url=url,
                visual_description=visual_description,
                vo_line=vo_line,
                scene_mood=scene_mood,
                image_bytes=image_bytes,
            )
            # Attach the candidate_id
            score = AlignmentScore(
                candidate_id=candidate_id,
                weighted_score=score.weighted_score,
                axis_scores=score.axis_scores,
                raw_rationale=score.raw_rationale,
                error=score.error,
            )
            result.all_scores.append(score)
            result.candidates_evaluated += 1

            if score.weighted_score > result.best_score:
                result.best_score = score.weighted_score
                result.best_candidate = candidate
                result.best_candidate_id = candidate_id
                result.scores_by_axis = dict(score.axis_scores)

            # Streaming: early exit on accept threshold
            if self.mode == "streaming" and score.weighted_score >= self.accept_threshold:
                result.early_exit = True
                _log.info(
                    "[INFO] ImageAlignmentEvaluator: early exit for %s (score %.2f >= %.2f)",
                    scene_id, score.weighted_score, self.accept_threshold,
                )
                break

        # Check minimum threshold
        if result.best_score < self.min_threshold:
            result.revision_requested = True
            _log.warning(
                "[WARN] ImageAlignmentEvaluator: revision requested for %s "
                "(best score %.2f < min threshold %.2f)",
                scene_id, result.best_score, self.min_threshold,
            )

        return (result.best_candidate, result)

    @staticmethod
    def _get_url(candidate: Any) -> str:
        """Extract URL from a candidate (dataclass or dict)."""
        if hasattr(candidate, "url"):
            return str(candidate.url or "")
        if isinstance(candidate, dict):
            return str(candidate.get("url") or "")
        return ""

    @staticmethod
    def _get_candidate_id(candidate: Any) -> str:
        """Extract or generate a candidate ID."""
        if hasattr(candidate, "candidate_id"):
            return str(candidate.candidate_id or "")
        if isinstance(candidate, dict):
            cid = candidate.get("candidate_id") or candidate.get("asset_id") or ""
            return str(cid)
        return ""

    @staticmethod
    def _get_local_path(candidate: Any) -> str:
        """Extract local file path from a candidate, if present."""
        if hasattr(candidate, "local_path"):
            return str(candidate.local_path or "")
        if isinstance(candidate, dict):
            return str(candidate.get("local_path") or "")
        return ""
