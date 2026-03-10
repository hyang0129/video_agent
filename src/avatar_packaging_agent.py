"""Avatar Packaging Agent.

Reads lipsync_manifest.json and audio_timeline.json from a run directory and
emits one AvatarSceneManifest.json per voiceover scene into avatar_takes/.

Each manifest is the direct input for the live2d-render CLI.

Usage:
    from src.avatar_packaging_agent import AvatarPackagingAgent
    agent = AvatarPackagingAgent(model_id="shiori")
    manifests = agent.package(lipsync_manifest, audio_timeline, run_dir)
"""

import json
import subprocess
from pathlib import Path

from src.config import AUDIO_SAMPLE_RATE


_DEFAULT_MODEL = {
    "id": "shiori",
    "path": "assets/models/shiori/shiori.model3.json",
}

_DEFAULT_RESOLUTION = [1080, 1920]
_DEFAULT_FPS = 30
_DEFAULT_BACKGROUND = "transparent"
_DEFAULT_CUES = [{"time": 0.0, "emotion": "neutral"}]


class AvatarPackagingAgent:
    """Packages pipeline artifacts into AvatarSceneManifest files for live2d-render."""

    def __init__(
        self,
        model_id: str = "shiori",
        model_path: str = "assets/models/shiori/shiori.model3.json",
        resolution: list = None,
        fps: int = _DEFAULT_FPS,
        background: str = _DEFAULT_BACKGROUND,
    ):
        self.model = {"id": model_id, "path": model_path}
        self.resolution = resolution or _DEFAULT_RESOLUTION
        self.fps = fps
        self.background = background

    def package(
        self,
        lipsync_manifest: dict,
        audio_timeline: dict,
        run_dir: Path,
        cues_by_scene: dict = None,
    ) -> list[dict]:
        """Generate one AvatarSceneManifest per scene.

        Args:
            lipsync_manifest: Loaded lipsync_manifest.json dict.
            audio_timeline: Loaded audio_timeline.json dict. Used only for t_start_s
                            cross-check if lipsync_manifest is missing timing.
            run_dir: Pipeline run directory. WAV files and manifests are written here.
            cues_by_scene: Optional dict mapping scene_id → list of cue dicts.
                           Defaults to [{time:0.0, emotion:"neutral"}] per scene.

        Returns:
            List of manifest dicts (one per scene), also written to disk.
        """
        takes_dir = run_dir / "avatar_takes"
        takes_dir.mkdir(exist_ok=True)

        wav_dir = takes_dir / "wav"
        wav_dir.mkdir(exist_ok=True)

        if cues_by_scene is None:
            cues_by_scene = {}

        results = []

        for scene in lipsync_manifest.get("scenes", []):
            scene_id = scene["scene_id"]
            audio_rel = scene["audio_file"].replace("\\", "/")
            mp3_path = run_dir / audio_rel

            if not mp3_path.exists():
                print(f"[SKIP] {scene_id}: audio file not found: {mp3_path}")
                continue

            wav_path = wav_dir / f"{scene_id}.wav"
            if not self._convert_to_wav(mp3_path, wav_path):
                print(f"[ERROR] {scene_id}: WAV conversion failed, skipping")
                continue

            lipsync_keyframes = self._build_lipsync(scene["cues"])
            cues = cues_by_scene.get(scene_id, list(_DEFAULT_CUES))

            manifest = {
                "schema_version": "1.0",
                "model": self.model,
                "audio": str(wav_path).replace("\\", "/"),
                "output": str(takes_dir / f"{scene_id}.mp4").replace("\\", "/"),
                "resolution": self.resolution,
                "fps": self.fps,
                "background": self.background,
                "lipsync": lipsync_keyframes,
                "cues": cues,
            }

            manifest_path = takes_dir / f"{scene_id}_manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"[OK] {scene_id}: {len(lipsync_keyframes)} lipsync keyframes -> {manifest_path.name}")

            results.append(manifest)

        print(f"[OK] avatar_takes/: {len(results)} scene manifests written")
        return results

    def _build_lipsync(self, cues: list) -> list:
        """Convert Rhubarb cues [{start, end, value}] to Live2D keyframes [{time, mouth_shape}].

        Uses the cue start time as the keyframe time (relative to scene).
        Appends a closing X keyframe at the final cue's end time.
        """
        if not cues:
            return [{"time": 0.0, "mouth_shape": "X"}]

        keyframes = [
            {"time": round(c["start"], 3), "mouth_shape": c["value"]}
            for c in cues
        ]

        # Close out with a silence keyframe at the end of the last cue
        last = cues[-1]
        if last["value"] != "X":
            keyframes.append({"time": round(last["end"], 3), "mouth_shape": "X"})

        return keyframes

    def _convert_to_wav(self, src: Path, dst: Path) -> bool:
        """Convert audio file to WAV via FFmpeg. Returns True on success."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-ac", "1",
            str(dst),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[ERROR] ffmpeg: {e}")
            return False

        if result.returncode != 0:
            print(f"[ERROR] ffmpeg exited {result.returncode} for {src.name}")
            return False
        return True
