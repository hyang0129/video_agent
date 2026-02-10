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
import uuid

import requests

from .config import RESULTS_DIR, VIDEO_RESOLUTION
from .artifacts.io import write_json
from .tools.content_validation_tools import validate_image_safety
from .tools.image_search_tools import ImageSearchError, search_pexels_images


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
    ):
        """Initialize visual asset agent.

        Args:
            output_dir: Directory for cached assets and manifest.
            image_sources: Enabled sources, e.g. ("pexels",).
            content_validator: Content safety provider name (Phase 1: "none").
            min_safety_score: Minimum safety score (0-1) to accept an asset.
            min_resolution: Minimum (width, height) to prefer.
        """
        self.output_dir = output_dir or RESULTS_DIR / f"visual_{uuid.uuid4().hex[:6]}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.assets_dir = self.output_dir / "assets"
        self.assets_dir.mkdir(exist_ok=True)

        self.image_sources = list(image_sources)
        self.content_validator = content_validator
        self.min_safety_score = float(min_safety_score)
        self.min_resolution = (int(min_resolution[0]), int(min_resolution[1]))

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

        assets: List[Dict[str, Any]] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue

            scene_id = str(scene.get("scene_id") or "")
            if not scene_id:
                continue

            prompts = scene.get("asset_prompts")
            prompt_list: List[str] = []
            if isinstance(prompts, list):
                prompt_list = [str(p).strip() for p in prompts if str(p).strip()]
            if not prompt_list:
                fallback = str(scene.get("on_screen_text") or "").strip()
                if fallback:
                    prompt_list = [fallback]

            query = prompt_list[0] if prompt_list else "generic background"

            asset = self._select_and_prepare_asset(
                scene_id=scene_id,
                query=query,
                text_context=str(scene.get("vo_line") or "").strip(),
            )
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

        if "pexels" in self.image_sources:
            results = search_pexels_images(query=query, per_page=limit, orientation="portrait")
            for item in results:
                res = item.get("resolution")
                if not isinstance(res, list) or len(res) != 2:
                    res_t = (0, 0)
                else:
                    res_t = (int(res[0]), int(res[1]))

                candidates.append(
                    VisualAssetCandidate(
                        source=str(item.get("source") or "pexels"),
                        url=str(item.get("url") or ""),
                        resolution=res_t,
                        attribution=item.get("attribution") or {},
                        metadata=item.get("metadata") or {},
                    )
                )

        return [c for c in candidates if c.url][:limit]

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

        resp = requests.get(asset_url, stream=True, timeout=60)
        resp.raise_for_status()

        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        return out

    def _select_and_prepare_asset(self, scene_id: str, query: str, text_context: str) -> Dict[str, Any]:
        """Select one valid asset for a scene, with placeholder fallback."""
        candidates: List[VisualAssetCandidate] = []
        try:
            candidates = self.search_assets(query=query, limit=10)
        except ImageSearchError:
            candidates = []

        # Prefer higher-res candidates first.
        candidates = sorted(
            candidates,
            key=lambda c: (c.resolution[0] * c.resolution[1]),
            reverse=True,
        )

        chosen: Optional[VisualAssetCandidate] = None
        chosen_validation: Optional[Dict[str, Any]] = None

        for cand in candidates:
            validation = self.validate_content(cand.url)
            if validation.get("validated") is True:
                chosen = cand
                chosen_validation = validation
                break

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
                    "search_query": query,
                    "alternatives_considered": len(candidates),
                    "selection_reason": "No valid external assets found; using deterministic placeholder",
                    "text_context": text_context,
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

        try:
            downloaded = self.download_asset(asset_url=chosen.url, scene_id=scene_id)
            rel_path = str(downloaded.relative_to(self.output_dir)).replace("\\", "/")
        except Exception as exc:
            raise VisualAssetError(f"Failed to download asset for scene {scene_id}: {exc}")

        return {
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
                "alternatives_considered": len(candidates),
                "selection_reason": "First candidate passing safety threshold",
            },
        }

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
