"""Composition agent for video production pipeline.

This agent combines:
- VideoPlan (scene structure + on-screen text)
- AudioTimeline (timing source of truth)
- VisualManifest (validated assets)

into a deterministic `RenderSpecification`.

Phase 1 output is designed for a simple slideshow renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .artifacts.io import write_json
from .config import VIDEO_FPS, VIDEO_RESOLUTION


class CompositionError(Exception):
    """Exception raised for composition failures."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_choice_index(key: str, n: int) -> int:
    if n <= 0:
        return 0
    digest = sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % n


KEN_BURNS_EFFECTS: List[Dict[str, Any]] = [
    {"type": "ken_burns", "direction": "zoom_in", "intensity": 1.15, "anchor": "center"},
    {"type": "ken_burns", "direction": "zoom_out", "intensity": 0.90, "anchor": "center"},
    {"type": "ken_burns", "direction": "pan_left", "distance": 0.08, "zoom": 1.10},
    {"type": "ken_burns", "direction": "pan_right", "distance": 0.08, "zoom": 1.10},
]


class CompositionAgent:
    """Agent for creating render specifications from audio and visual assets."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        resolution: Tuple[int, int] = VIDEO_RESOLUTION,
        fps: int = VIDEO_FPS,
        transition_duration_s: float = 0.3,
    ):
        self.output_dir = output_dir
        self.resolution = (int(resolution[0]), int(resolution[1]))
        self.fps = int(fps)
        self.transition_duration_s = float(transition_duration_s)

        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_render_specification(
        self,
        video_plan: Dict[str, Any],
        audio_timeline: Dict[str, Any],
        visual_manifest: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a RenderSpecification.

        Args:
            video_plan: VideoPlan with scenes.
            audio_timeline: AudioTimeline with timing.
            visual_manifest: VisualManifest with assets.

        Returns:
            RenderSpecification dict.

        Raises:
            CompositionError: If inputs are incompatible.
        """
        self._validate_inputs(video_plan=video_plan, audio_timeline=audio_timeline, visual_manifest=visual_manifest)

        render_spec_id = f"rs_{uuid.uuid4().hex[:8]}"

        clips = self.synchronize_timing(audio_timeline=audio_timeline, visual_manifest=visual_manifest)
        clips = [self.apply_effects(c) for c in clips]

        text_elements = self.create_text_overlays(video_plan=video_plan, audio_timeline=audio_timeline)

        duration_seconds = float(audio_timeline.get("duration_seconds") or 0.0)
        if duration_seconds <= 0.0:
            # Fallback: max t_end_s across voiceover segments.
            duration_seconds = max((float(c.get("t_end_s") or 0.0) for c in clips), default=0.0)

        render_spec: Dict[str, Any] = {
            "schema_version": "1.0.0",
            "render_spec_id": render_spec_id,
            "created_at": _utc_now_iso(),
            "video_plan_ref": video_plan.get("video_plan_id", "unknown"),
            "audio_timeline_ref": audio_timeline.get("audio_timeline_id", "unknown"),
            "visual_manifest_ref": visual_manifest.get("visual_manifest_id", "unknown"),
            "output_settings": {
                "resolution": [self.resolution[0], self.resolution[1]],
                "fps": self.fps,
                "format": "mp4",
                "codec": "h264",
                "duration_seconds": round(duration_seconds, 2),
            },
            "layers": [
                {
                    "layer_id": "layer_video",
                    "type": "video",
                    "z_index": 0,
                    "clips": clips,
                },
                {
                    "layer_id": "layer_subtitles",
                    "type": "text",
                    "z_index": 2,
                    "elements": text_elements,
                },
                {
                    "layer_id": "layer_audio",
                    "type": "audio",
                    "z_index": -1,
                    "tracks": self._audio_tracks_from_timeline(audio_timeline=audio_timeline),
                },
            ],
        }

        if self.output_dir is not None:
            write_json(self.output_dir / "render_spec.json", render_spec)

        return render_spec

    def synchronize_timing(self, audio_timeline: Dict[str, Any], visual_manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create clip definitions aligned to audio timing."""
        assets = visual_manifest.get("assets")
        if not isinstance(assets, list):
            raise CompositionError("VisualManifest.assets must be a list")

        asset_by_scene: Dict[str, Dict[str, Any]] = {}
        for a in assets:
            if not isinstance(a, dict):
                continue
            scene_id = str(a.get("scene_id") or "")
            if scene_id:
                asset_by_scene[scene_id] = a

        tracks = audio_timeline.get("tracks")
        if not isinstance(tracks, list):
            raise CompositionError("AudioTimeline.tracks must be a list")

        voiceover_segments = [t for t in tracks if isinstance(t, dict) and t.get("type") == "voiceover"]
        if not voiceover_segments:
            raise CompositionError("AudioTimeline contains no voiceover segments")

        clips: List[Dict[str, Any]] = []
        for seg in voiceover_segments:
            scene_id = str(seg.get("scene_id") or "")
            if not scene_id:
                continue

            asset = asset_by_scene.get(scene_id)
            if not asset:
                raise CompositionError(f"No visual asset found for scene {scene_id}")

            t_start = float(seg.get("t_start_s") or 0.0)
            t_end = float(seg.get("t_end_s") or 0.0)
            if t_end <= t_start:
                continue

            duration_s = t_end - t_start

            clips.append(
                {
                    "clip_id": f"clip_{scene_id}",
                    "scene_id": scene_id,
                    "asset_ref": str(asset.get("asset_id") or f"asset_{scene_id}"),
                    "source_file": str(asset.get("file_path") or ""),
                    "t_start_s": round(t_start, 2),
                    "t_end_s": round(t_end, 2),
                    "duration_s": round(duration_s, 2),
                    "effects": [],
                    "transition_in": {"type": "fade", "duration_s": self.transition_duration_s},
                    "transition_out": {"type": "fade", "duration_s": self.transition_duration_s},
                }
            )

        return clips

    def apply_effects(self, clip: Dict[str, Any], effect_style: str = "ken_burns") -> Dict[str, Any]:
        """Apply deterministic motion effects."""
        if effect_style != "ken_burns":
            return clip

        scene_id = str(clip.get("scene_id") or "")
        idx = _stable_choice_index(scene_id, len(KEN_BURNS_EFFECTS))
        effect = KEN_BURNS_EFFECTS[idx]
        return {**clip, "effects": [effect]}

    def create_text_overlays(self, video_plan: Dict[str, Any], audio_timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create simple on-screen text overlays aligned to voiceover timing."""
        scenes = video_plan.get("scenes")
        if not isinstance(scenes, list):
            return []

        # Map scene_id -> timing from audio
        tracks = audio_timeline.get("tracks")
        if not isinstance(tracks, list):
            return []

        timing: Dict[str, Tuple[float, float]] = {}
        for t in tracks:
            if not isinstance(t, dict) or t.get("type") != "voiceover":
                continue
            scene_id = str(t.get("scene_id") or "")
            if not scene_id:
                continue
            timing[scene_id] = (float(t.get("t_start_s") or 0.0), float(t.get("t_end_s") or 0.0))

        elements: List[Dict[str, Any]] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or "")
            if not scene_id:
                continue

            text = str(scene.get("on_screen_text") or "").strip()
            if not text:
                continue

            t_start, t_end = timing.get(scene_id, (float(scene.get("t_start_s") or 0.0), float(scene.get("t_end_s") or 0.0)))
            if t_end <= t_start:
                continue

            # Give a small lead-in/out for readability.
            start = min(t_end, t_start + 0.5)
            end = max(start, t_end - 0.25)

            elements.append(
                {
                    "element_id": f"subtitle_{scene_id}",
                    "scene_id": scene_id,
                    "text": text,
                    "t_start_s": round(start, 2),
                    "t_end_s": round(end, 2),
                    "position": {"x": "center", "y": 0.75},
                    "style": {
                        "font": "Montserrat-Bold",
                        "size": 72,
                        "color": "#FFFFFF",
                        "stroke": {"color": "#000000", "width": 4},
                        "shadow": {"blur": 8, "opacity": 0.8},
                    },
                    "animation": {
                        "in": {"type": "fade_up", "duration_s": 0.3},
                        "out": {"type": "fade", "duration_s": 0.2},
                    },
                }
            )

        return elements

    def _audio_tracks_from_timeline(self, audio_timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
        tracks = audio_timeline.get("tracks")
        if not isinstance(tracks, list):
            return []

        voiceover_segments: List[Dict[str, Any]] = []
        for t in tracks:
            if not isinstance(t, dict) or t.get("type") != "voiceover":
                continue
            voiceover_segments.append(
                {
                    "segment_id": f"vo_{t.get('scene_id','unknown')}",
                    "scene_id": t.get("scene_id"),
                    "source_file": t.get("file"),
                    "t_start_s": t.get("t_start_s"),
                    "t_end_s": t.get("t_end_s"),
                    "volume_db": t.get("volume_db", 0),
                }
            )

        return [{"track_id": "track_vo", "type": "voiceover", "segments": voiceover_segments}]

    def _validate_inputs(self, video_plan: Dict[str, Any], audio_timeline: Dict[str, Any], visual_manifest: Dict[str, Any]) -> None:
        if not isinstance(video_plan, dict):
            raise CompositionError("video_plan must be a dict")
        if not isinstance(audio_timeline, dict):
            raise CompositionError("audio_timeline must be a dict")
        if not isinstance(visual_manifest, dict):
            raise CompositionError("visual_manifest must be a dict")

        if not isinstance(video_plan.get("scenes"), list):
            raise CompositionError("VideoPlan.scenes must be a list")
        if not isinstance(audio_timeline.get("tracks"), list):
            raise CompositionError("AudioTimeline.tracks must be a list")
        if not isinstance(visual_manifest.get("assets"), list):
            raise CompositionError("VisualManifest.assets must be a list")


def create_composition_agent(
    output_dir: Optional[Path] = None,
    resolution: Tuple[int, int] = VIDEO_RESOLUTION,
    fps: int = VIDEO_FPS,
    transition_duration_s: float = 0.3,
) -> CompositionAgent:
    """Factory for CompositionAgent."""
    return CompositionAgent(
        output_dir=output_dir,
        resolution=resolution,
        fps=fps,
        transition_duration_s=transition_duration_s,
    )
