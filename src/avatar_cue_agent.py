"""Avatar Cue Agent — Stage 1 (neutral-only).

Generates per-scene emotion/reaction cues for the avatar.

Stage 1 (this file): always returns a single neutral cue at t=0 for every
scene. The output feeds directly into AvatarPackagingAgent.package_full().

Stage 2 (future): LLM-driven cue generation derived from vo_line /
on_screen_text, adding emotion shifts and reaction beats within each scene.

Usage:
    from src.avatar_cue_agent import AvatarCueAgent
    cues_by_scene = AvatarCueAgent().generate_cues(audio_timeline)
"""


class AvatarCueAgent:
    """Generates per-scene avatar cues from an audio timeline."""

    def generate_cues(self, audio_timeline: dict) -> dict:
        """Return cues_by_scene mapping scene_id -> list of cue dicts.

        Each cue dict follows the AvatarSceneManifest cue vocabulary:
            { "time": float, "emotion": str }
            { "time": float, "reaction": str }

        Args:
            audio_timeline: AudioTimeline dict — used to enumerate scene IDs
                in timeline order from voiceover tracks.

        Returns:
            Dict[scene_id, list[cue dict]] — one neutral cue per scene.
        """
        cues_by_scene = {}
        for track in audio_timeline.get("tracks", []):
            if track.get("type") != "voiceover":
                continue
            scene_id = track.get("scene_id")
            if not scene_id:
                continue
            cues_by_scene[scene_id] = [{"time": 0.0, "emotion": "neutral"}]
        return cues_by_scene
