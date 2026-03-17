"""Visual asset agent for video production pipeline.

This agent selects (or generates placeholders for) visual assets per scene,
validates them, and produces a `VisualManifest` artifact.

Phase 1 supports:
- Pexels image search (optional; requires PEXELS_API_KEY)
- Deterministic placeholder BMP generation when no provider is configured

Design goals:
- Clear I/O contracts (VideoPlan -> VisualManifest)
- Deterministic decisions where possible (hash-based choices)
- Offline-safe defaults
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import logging
import time
import uuid

_log = logging.getLogger(__name__)

import requests

from .config import CACHE_DIR, RESULTS_DIR, VIDEO_RESOLUTION
from .artifacts.io import write_json
from .tools.content_validation_tools import validate_image_safety
from .tools.image_alignment_tools import ImageAlignmentEvaluator, SceneAlignmentResult
from .tools.image_search_tools import ImageSearchError, search_pexels_images, search_wikimedia_images


class VisualAssetError(Exception):
    """Exception raised for visual asset generation failures."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_choice_index(key: str, n: int) -> int:
    if n <= 0:
        return 0
    digest = sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % n


def _write_solid_bmp(
    path: Path,
    width: int,
    height: int,
    rgb: Tuple[int, int, int],
) -> None:
    """Write a solid-color 24-bit BMP.

    This avoids adding Pillow as a dependency while producing a real image file
    that FFmpeg can ingest.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    r, g, b = rgb
    r = max(0, min(int(r), 255))
    g = max(0, min(int(g), 255))
    b = max(0, min(int(b), 255))

    # BMP rows are padded to 4-byte boundaries.
    row_stride = (width * 3 + 3) & ~3
    pixel_array_size = row_stride * height

    file_header_size = 14
    dib_header_size = 40
    offset = file_header_size + dib_header_size
    file_size = offset + pixel_array_size

    # File header (14 bytes)
    file_header = bytearray()
    file_header.extend(b"BM")
    file_header.extend(file_size.to_bytes(4, "little"))
    file_header.extend((0).to_bytes(2, "little"))
    file_header.extend((0).to_bytes(2, "little"))
    file_header.extend(offset.to_bytes(4, "little"))

    # DIB header (BITMAPINFOHEADER, 40 bytes)
    dib = bytearray()
    dib.extend(dib_header_size.to_bytes(4, "little"))
    dib.extend(width.to_bytes(4, "little", signed=True))
    dib.extend(height.to_bytes(4, "little", signed=True))
    dib.extend((1).to_bytes(2, "little"))  # planes
    dib.extend((24).to_bytes(2, "little"))  # bits per pixel
    dib.extend((0).to_bytes(4, "little"))  # compression (BI_RGB)
    dib.extend(pixel_array_size.to_bytes(4, "little"))
    dib.extend((2835).to_bytes(4, "little"))  # x ppm
    dib.extend((2835).to_bytes(4, "little"))  # y ppm
    dib.extend((0).to_bytes(4, "little"))  # colors used
    dib.extend((0).to_bytes(4, "little"))  # important colors

    # Pixel data is BGR, bottom-up.
    pad = b"\x00" * (row_stride - width * 3)
    row = bytes([b, g, r]) * width + pad
    pixel_data = row * height

    path.write_bytes(bytes(file_header) + bytes(dib) + pixel_data)


@dataclass(frozen=True)
class VisualAssetCandidate:
    """Normalized candidate asset."""

    source: str
    url: str
    resolution: Tuple[int, int]
    attribution: Dict[str, Any]
    metadata: Dict[str, Any]


class VisualAssetAgent:
    """Agent for discovering, validating, and preparing visual assets."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        image_sources: Sequence[str] = ("pexels",),
        content_validator: str = "none",
        min_safety_score: float = 0.9,
        min_resolution: Tuple[int, int] = VIDEO_RESOLUTION,
        alignment_evaluator: Optional[ImageAlignmentEvaluator] = None,
    ):
        """Initialize visual asset agent.

        Args:
            output_dir: Directory for cached assets and manifest.
            image_sources: Enabled sources, e.g. ("pexels",).
            content_validator: Content safety provider name (Phase 1: "none").
            min_safety_score: Minimum safety score (0-1) to accept an asset.
            min_resolution: Minimum (width, height) to prefer.
            alignment_evaluator: Image alignment evaluator instance.
        """
        self.alignment_evaluator = alignment_evaluator or ImageAlignmentEvaluator()
        self.output_dir = output_dir or RESULTS_DIR / f"visual_{uuid.uuid4().hex[:6]}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.assets_dir = self.output_dir / "assets"
        self.assets_dir.mkdir(exist_ok=True)

        self.image_sources = list(image_sources)
        self.content_validator = content_validator
        self.min_safety_score = float(min_safety_score)
        self.min_resolution = (int(min_resolution[0]), int(min_resolution[1]))

    def _extract_image_query(self, vo_line: str, topic_context: str) -> str:
        """Use LLM to extract a short image search query from a script line.

        Results are cached in .cache/image_query_cache.json to avoid burning
        free-tier quota on repeated runs. Falls back to vo_line on any error.
        """
        if not vo_line:
            return topic_context or "generic background"

        cache_key = sha256(f"{topic_context}|{vo_line}".encode()).hexdigest()[:16]
        cache_file = CACHE_DIR / "image_query_cache.json"
        cache: Dict[str, str] = {}
        if cache_file.exists():
            try:
                import json
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        if cache_key in cache:
            return cache[cache_key]

        try:
            from .config import make_llm
            llm = make_llm(temperature=0.0)
            prompt = (
                "You are generating a Wikimedia Commons or stock photo search query for a video scene.\n\n"
                f"VIDEO TOPIC: {topic_context}\n"
                f"SCENE NARRATION: {vo_line}\n\n"
                "Rules:\n"
                "- Return ONLY the search query, no explanation or punctuation.\n"
                "- Use 3-6 precise, unambiguous keywords that describe the VISUAL subject.\n"
                "- Avoid words with multiple meanings. Use the domain-specific term instead:\n"
                "  - Use 'armored vehicle' or 'tank vehicle' not 'tank' (could match water tank, fish tank)\n"
                "  - Use 'landmine' or 'anti-tank mine' not 'mine' (could match mining/excavation)\n"
                "  - Use 'WW2' or 'World War II' to anchor historical context\n"
                "- Prefer terms that appear in encyclopedia article titles or image captions.\n\n"
                "Search query:"
            )
            result = llm.invoke(prompt)
            query = str(result.content).strip().strip('"').strip("'")
            if not query:
                return vo_line
            cache[cache_key] = query
            try:
                import json
                cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            except Exception:
                pass
            return query
        except Exception as exc:
            _log.warning("[WARN] LLM query extraction failed, using raw vo_line: %s", exc)
            return vo_line

    def _llm_is_relevant(
        self,
        candidate: VisualAssetCandidate,
        vo_line: str,
        topic_context: str,
    ) -> bool:
        """Ask the LLM whether a candidate image is relevant enough to use.

        Returns True if the LLM says YES, False otherwise. Defaults to True
        on any error so the loop can terminate rather than spin indefinitely.
        """
        alt = candidate.metadata.get("alt") or candidate.metadata.get("title") or ""
        try:
            from .config import make_llm
            llm = make_llm(temperature=0.0)
            prompt = (
                "You are reviewing whether an image is suitable for a video scene.\n\n"
                f"VIDEO TOPIC: {topic_context}\n"
                f"SCENE NARRATION: {vo_line}\n\n"
                f"IMAGE DESCRIPTION: {alt[:400]}\n\n"
                "Is this image visually relevant to the scene narration? "
                "Answer YES if it shows something clearly related to the topic. "
                "Answer NO if it is a completely unrelated subject (e.g. an animal when the topic is a military vehicle).\n\n"
                "Answer (YES or NO):"
            )
            result = llm.invoke(prompt)
            answer = str(result.content).strip().upper()
            return answer.startswith("YES")
        except Exception as exc:
            _log.warning("[WARN] LLM relevance check failed, accepting candidate: %s", exc)
            return True

    def _llm_broaden_query(
        self,
        query: str,
        vo_line: str,
        topic_context: str,
        tried_queries: List[str],
    ) -> Optional[str]:
        """Ask the LLM to produce a simpler, broader search query.

        Returns a new query string, or None if the LLM can't generate one distinct
        from what has already been tried.
        """
        tried_text = ", ".join(f'"{q}"' for q in tried_queries)
        try:
            from .config import make_llm
            llm = make_llm(temperature=0.0)
            prompt = (
                "A Wikimedia Commons image search returned irrelevant results.\n\n"
                f"VIDEO TOPIC: {topic_context}\n"
                f"SCENE NARRATION: {vo_line}\n\n"
                f"Queries already tried (all returned irrelevant images): {tried_text}\n\n"
                "Generate a shorter, more general search query by removing the most specific terms. "
                "Keep only the core subject (e.g. vehicle type or historical era). "
                "Return ONLY the new query, no explanation."
            )
            result = llm.invoke(prompt)
            new_query = str(result.content).strip().strip('"').strip("'")
            if new_query and new_query not in tried_queries:
                return new_query
        except Exception as exc:
            _log.warning("[WARN] LLM query broadening failed: %s", exc)
        return None

    def generate_visual_manifest(self, video_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a complete VisualManifest from a VideoPlan.

        Args:
            video_plan: VideoPlan dictionary with scenes and asset prompts.

        Returns:
            VisualManifest dictionary.

        Raises:
            VisualAssetError: If required inputs are missing.
        """
        self._validate_video_plan(video_plan)

        scenes = video_plan.get("scenes")
        assert isinstance(scenes, list)

        manifest_id = f"vm_{uuid.uuid4().hex[:8]}"
        topic_context = " ".join(filter(None, [
            str(video_plan.get("topic_id") or ""),
            str(video_plan.get("subtopic_id") or ""),
        ])).strip()

        used_urls: set = set()
        assets: List[Dict[str, Any]] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue

            scene_id = str(scene.get("scene_id") or "")
            if not scene_id:
                continue

            vo_line = str(scene.get("vo_line") or "").strip()
            query = self._extract_image_query(vo_line=vo_line, topic_context=topic_context)

            asset = self._select_and_prepare_asset(
                scene_id=scene_id,
                query=query,
                text_context=vo_line,
                topic_context=topic_context,
                used_urls=used_urls,
            )
            chosen_url = asset.get("url")
            if chosen_url:
                used_urls.add(chosen_url)
            assets.append(asset)

        visual_manifest = {
            "schema_version": "1.0.0",
            "visual_manifest_id": manifest_id,
            "video_plan_ref": video_plan.get("video_plan_id", "unknown"),
            "created_at": _utc_now_iso(),
            "total_scenes": len([s for s in scenes if isinstance(s, dict)]),
            "total_assets": len(assets),
            "assets": assets,
        }

        write_json(self.output_dir / "visual_manifest.json", visual_manifest)

        # Write image alignment scores for evaluation.json merge
        alignment_entries = [
            asset["alignment"]
            for asset in assets
            if "alignment" in asset
        ]
        if alignment_entries:
            write_json(
                self.output_dir / "image_alignment_scores.json",
                alignment_entries,
            )

        # Write production issues for scenes that need revision
        import json as _json
        production_issues = []
        for asset in assets:
            ar = asset.get("alignment")
            if ar and ar.get("revision_requested"):
                production_issues.append({
                    "agent": "ImageAlignmentEvaluator",
                    "scene_id": ar["scene_id"],
                    "status": "degraded",
                    "issue": "low_alignment_score",
                    "detail": f"Best alignment score {ar['best_score']:.2f} below minimum threshold",
                    "suggestion": "Rephrase visual.description and search_queries to better match available stock imagery",
                    "revision_field": "visual",
                    "revision_possible": True,
                })
        if production_issues:
            report_path = self.output_dir / "production_report.json"
            existing_issues: List[Dict[str, Any]] = []
            if report_path.exists():
                try:
                    existing = _json.loads(report_path.read_text(encoding="utf-8"))
                    existing_issues = list(existing.get("issues") or [])
                except Exception:
                    pass
            all_issues = existing_issues + production_issues
            write_json(report_path, {
                "schema_version": "1.0.0",
                "issues": all_issues,
                "degraded_scene_count": sum(1 for i in all_issues if i.get("status") == "degraded"),
            })
            _log.warning(
                "[WARN] ImageAlignmentEvaluator: %d scene(s) below minimum threshold, revision requested",
                len(production_issues),
            )

        return visual_manifest

    def search_assets(self, query: str, asset_type: str = "image", limit: int = 10) -> List[VisualAssetCandidate]:
        """Search for assets matching query.

        Args:
            query: Search query.
            asset_type: Currently only "image".
            limit: Max candidates.

        Returns:
            List of normalized candidates.
        """
        if asset_type != "image":
            return []

        candidates: List[VisualAssetCandidate] = []

        def _append_results(results: list) -> None:
            for item in results:
                if len(candidates) >= limit:
                    break
                url = str(item.get("url") or "")
                if not url:
                    continue
                res = item.get("resolution")
                if not isinstance(res, list) or len(res) != 2:
                    res_t = (0, 0)
                else:
                    res_t = (int(res[0]), int(res[1]))
                candidates.append(
                    VisualAssetCandidate(
                        source=str(item.get("source") or "unknown"),
                        url=url,
                        resolution=res_t,
                        attribution=item.get("attribution") or {},
                        metadata=item.get("metadata") or {},
                    )
                )

        for source in self.image_sources:
            if len(candidates) >= limit:
                break
            remaining = limit - len(candidates)
            before = len(candidates)
            try:
                if source == "wikimedia":
                    _append_results(search_wikimedia_images(query=query, per_page=remaining, orientation="portrait"))
                    # If Wikimedia returned nothing, retry with a shorter query (first 3 tokens).
                    if len(candidates) == before:
                        short_query = " ".join(query.split()[:3])
                        if short_query and short_query != query:
                            _log.warning("[INFO] Wikimedia: 0 results for %r, retrying with %r", query, short_query)
                            _append_results(search_wikimedia_images(query=short_query, per_page=remaining, orientation="portrait"))
                elif source == "pexels":
                    _append_results(search_pexels_images(query=query, per_page=remaining, orientation="portrait"))
            except ImageSearchError:
                continue

        return candidates[:limit]

    def validate_content(self, asset_url: str) -> Dict[str, Any]:
        """Validate asset content safety."""
        result = validate_image_safety(image_url=asset_url, provider=self.content_validator)
        try:
            score = float(result.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        if bool(result.get("validated")) and score >= self.min_safety_score:
            return {**result, "validated": True, "score": score}

        return {**result, "validated": False, "score": score}

    def download_asset(self, asset_url: str, scene_id: str) -> Path:
        """Download and cache asset locally."""
        file_name = f"{scene_id}.jpg"
        out = self.assets_dir / file_name

        headers = {}
        if "wikimedia.org" in asset_url or "wikipedia.org" in asset_url:
            headers["User-Agent"] = "Mozilla/5.0 (compatible; VideoAgent/1.0)"
            time.sleep(1.0)
        resp = requests.get(asset_url, headers=headers, stream=True, timeout=60)
        resp.raise_for_status()

        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        return out

    def _select_and_prepare_asset(
        self,
        scene_id: str,
        query: str,
        text_context: str,
        topic_context: str = "",
        used_urls: Optional[set] = None,
        _max_query_attempts: int = 3,
        visual_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Select one valid asset for a scene using a specific-to-general query loop.

        Each iteration:
          1. Search with the current query (10 candidates per source).
          2. Score candidates via the alignment evaluator (vision model).
          3. If best score >= accept threshold, accept. Else broaden query.
        Up to _max_query_attempts iterations (default 3). All tried queries are
        recorded in the manifest metadata.
        """
        tried_queries: List[str] = []
        chosen: Optional[VisualAssetCandidate] = None
        chosen_validation: Optional[Dict[str, Any]] = None
        alignment_result: Optional[SceneAlignmentResult] = None
        valid_candidates: List[VisualAssetCandidate] = []
        current_query = query

        # visual_description is not yet in the video_plan schema -- once the
        # screenplay's per-scene visual description flows through, pass it here
        # instead of reusing the vo_line.
        scene_context = {
            "visual_description": visual_description or text_context,
            "vo_line": text_context,
            "scene_mood": "neutral",
            "scene_id": scene_id,
        }

        for _attempt in range(_max_query_attempts):
            tried_queries.append(current_query)

            raw_candidates: List[VisualAssetCandidate] = []
            try:
                raw_candidates = self.search_assets(query=current_query, limit=10)
            except ImageSearchError:
                pass

            # Skip URLs already used in other scenes.
            if used_urls:
                raw_candidates = [c for c in raw_candidates if c.url not in used_urls]

            # Validate all candidates; keep the ones that pass safety.
            round_valid: List[VisualAssetCandidate] = [
                c for c in raw_candidates
                if self.validate_content(c.url).get("validated") is True
            ]
            # Accumulate across rounds so later rounds can't duplicate earlier picks.
            seen_urls = {c.url for c in valid_candidates}
            for c in round_valid:
                if c.url not in seen_urls:
                    valid_candidates.append(c)
                    seen_urls.add(c.url)

            # Score candidates and pick the best from this round.
            round_chosen, round_alignment = self.alignment_evaluator.select_best(
                round_valid, scene_context=scene_context,
            )

            if round_chosen is None:
                _log.warning("[INFO] No candidates for query %r (attempt %d/%d)", current_query, _attempt + 1, _max_query_attempts)
            else:
                # Use accept threshold to decide: good enough or broaden?
                accepted = (
                    round_alignment is not None
                    and round_alignment.best_score >= self.alignment_evaluator.accept_threshold
                )
                if round_alignment is None or accepted:
                    chosen = round_chosen
                    alignment_result = round_alignment
                    chosen_validation = self.validate_content(chosen.url)
                    score_str = f" (score {round_alignment.best_score:.2f})" if round_alignment else ""
                    _log.warning("[INFO] Accepted image on attempt %d%s: %s", _attempt + 1, score_str, round_chosen.metadata.get("alt", "")[:80])
                    break

                # Below accept threshold — keep best so far, try broadening
                if alignment_result is None or round_alignment.best_score > alignment_result.best_score:
                    chosen = round_chosen
                    alignment_result = round_alignment
                _log.warning(
                    "[INFO] Below accept threshold on attempt %d (score %.2f < %.2f), broadening query",
                    _attempt + 1, round_alignment.best_score, self.alignment_evaluator.accept_threshold,
                )

            # Need a broader query — ask the LLM.
            if _attempt < _max_query_attempts - 1:
                new_query = self._llm_broaden_query(
                    query=current_query,
                    vo_line=text_context,
                    topic_context=topic_context,
                    tried_queries=tried_queries,
                )
                if new_query:
                    current_query = new_query
                else:
                    break  # LLM couldn't suggest anything new

        # If the loop exhausted without acceptance, fall back to best available.
        if chosen is None and valid_candidates:
            chosen, alignment_result = self.alignment_evaluator.select_best(
                valid_candidates, scene_context=scene_context,
            )
            if chosen is not None:
                chosen_validation = self.validate_content(chosen.url)
                _log.warning("[INFO] Using best-available fallback after %d attempts", len(tried_queries))

        # If none pass (or no providers configured), create a deterministic placeholder.
        if chosen is None:
            width, height = self.min_resolution
            palette = [
                (18, 18, 18),
                (30, 58, 138),
                (10, 92, 58),
                (120, 60, 18),
            ]
            rgb = palette[_stable_choice_index(scene_id, len(palette))]
            file_path = self.assets_dir / f"{scene_id}_placeholder.bmp"
            _write_solid_bmp(path=file_path, width=width, height=height, rgb=rgb)

            return {
                "asset_id": f"asset_{scene_id}",
                "scene_id": scene_id,
                "type": "image",
                "source": "placeholder",
                "file_path": str(file_path.relative_to(self.output_dir)).replace("\\", "/"),
                "url": None,
                "resolution": [width, height],
                "attribution": {
                    "required": False,
                    "text": "Generated placeholder",
                    "license": "internal",
                },
                "content_safety": {
                    "validated": True,
                    "service": "none",
                    "flags": ["placeholder_asset"],
                    "score": 1.0,
                },
                "metadata": {
                    "search_query": tried_queries[-1] if tried_queries else query,
                    "queries_tried": tried_queries,
                    "alternatives_considered": len(valid_candidates),
                    "selection_reason": "No valid external assets found; using deterministic placeholder",
                    "script_line": text_context,
                },
            }

        assert chosen is not None
        if chosen_validation is None:
            chosen_validation = {
                "validated": False,
                "service": self.content_validator,
                "flags": ["validation_missing"],
                "score": 0.0,
            }

        downloaded = None
        for cand_attempt in ([chosen] + [c for c in valid_candidates if c is not chosen]):
            try:
                downloaded = self.download_asset(asset_url=cand_attempt.url, scene_id=scene_id)
                chosen = cand_attempt
                break
            except Exception:
                continue

        if downloaded is None:
            width, height = self.min_resolution
            palette = [
                (18, 18, 18),
                (30, 58, 138),
                (10, 92, 58),
                (120, 60, 18),
            ]
            rgb = palette[_stable_choice_index(scene_id, len(palette))]
            file_path = self.assets_dir / f"{scene_id}_placeholder.bmp"
            _write_solid_bmp(path=file_path, width=width, height=height, rgb=rgb)
            return {
                "asset_id": f"asset_{scene_id}",
                "scene_id": scene_id,
                "type": "image",
                "source": "placeholder",
                "file_path": str(file_path.relative_to(self.output_dir)).replace("\\", "/"),
                "url": None,
                "resolution": [width, height],
                "attribution": {"required": False, "text": "Generated placeholder", "license": "internal"},
                "content_safety": {"validated": True, "service": "none", "flags": ["placeholder_download_fallback"], "score": 1.0},
                "metadata": {"search_query": query, "alternatives_considered": len(valid_candidates), "selection_reason": "Download failed for all candidates; using placeholder", "text_context": text_context},
            }

        rel_path = str(downloaded.relative_to(self.output_dir)).replace("\\", "/")

        asset_dict: Dict[str, Any] = {
            "asset_id": f"asset_{scene_id}",
            "scene_id": scene_id,
            "type": "image",
            "source": chosen.source,
            "file_path": rel_path,
            "url": chosen.url,
            "resolution": [int(chosen.resolution[0]), int(chosen.resolution[1])],
            "attribution": chosen.attribution,
            "content_safety": chosen_validation,
            "metadata": {
                **chosen.metadata,
                "queries_tried": tried_queries,
                "alternatives_considered": len(valid_candidates),
                "selection_reason": "Alignment-scored from validated candidates",
                "script_line": text_context,
            },
        }
        if alignment_result is not None:
            asset_dict["alignment"] = alignment_result.to_dict()
        return asset_dict

    def _validate_video_plan(self, video_plan: Dict[str, Any]) -> None:
        if not isinstance(video_plan, dict):
            raise VisualAssetError("video_plan must be a dict")
        scenes = video_plan.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise VisualAssetError("VideoPlan.scenes must be a non-empty list")


def create_visual_agent(
    output_dir: Optional[Path] = None,
    image_sources: Sequence[str] = ("pexels",),
    content_validator: str = "none",
    min_safety_score: float = 0.9,
) -> VisualAssetAgent:
    """Factory for VisualAssetAgent."""
    return VisualAssetAgent(
        output_dir=output_dir,
        image_sources=image_sources,
        content_validator=content_validator,
        min_safety_score=min_safety_score,
    )
