"""Avatar Packaging Agent.

Reads lipsync_manifest.json and audio_timeline.json from a run directory and
emits one AvatarSceneManifest.json per voiceover scene into avatar_takes/.

Each manifest is the direct input for the live2d-render CLI.

Usage:
    from video_agent.avatar_packaging_agent import AvatarPackagingAgent
    agent = AvatarPackagingAgent(model_id="shiori")
    manifests = agent.package(lipsync_manifest, audio_timeline, run_dir)
"""

import json
import re
import subprocess
from pathlib import Path

from video_agent.config import (
    AUDIO_SAMPLE_RATE,
    FFMPEG_PATH,
    LIVE2D_MODEL_ID,
    LIVE2D_MODEL_PATH,
    RHUBARB_WAV_SAMPLE_RATE,
)


# --- log parsing patterns ---

_RE_CONTAINER_MISMATCH = re.compile(
    r"\[WARN \].*switching container to \"(?P<ext>\.\w+)\""
)
_RE_UNDEFINED_EXPRESSION = re.compile(
    r"\[WARN \] Cue t=(?P<t>[\d.]+)s: emotion \"(?P<name>[^\"]+)\" not defined on model"
)
_RE_UNDEFINED_REACTION = re.compile(
    r"\[WARN \] Cue t=(?P<t>[\d.]+)s: reaction \"(?P<name>[^\"]+)\" not defined on model"
)
_RE_RENDER_COMPLETE = re.compile(
    r"\[INFO \] Render complete: (?P<frames>\d+) frames in (?P<secs>[\d.]+)s \((?P<fps>[\d.]+) fps\)"
)
_RE_OUTPUT_LINE = re.compile(
    r"\[INFO \] Output: \"(?P<path>[^\"]+)\""
)
_RE_FFMPEG_FINAL = re.compile(
    r"\[INFO \] FFmpeg finalized\. Output: \"(?P<path>[^\"]+)\""
)
_RE_ERROR = re.compile(r"\[ERROR\]")


_DEFAULT_MODEL = {
    "id": LIVE2D_MODEL_ID,
    "path": LIVE2D_MODEL_PATH,
}

_DEFAULT_RESOLUTION = [1080, 1920]
_DEFAULT_FPS = 30
_DEFAULT_BACKGROUND = "transparent"
_DEFAULT_CUES = [{"time": 0.0, "emotion": "neutral"}]


class AvatarPackagingAgent:
    """Packages pipeline artifacts into AvatarSceneManifest files for live2d-render."""

    def __init__(
        self,
        model_id: str = LIVE2D_MODEL_ID,
        model_path: str = LIVE2D_MODEL_PATH,
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

    def package_full(
        self,
        lipsync_manifest: dict,
        audio_timeline: dict,
        run_dir: Path,
        cues_by_scene: dict = None,
        resolution: list = None,
        fps: int = None,
    ) -> dict:
        """Build a single continuous AvatarSceneManifest spanning all scenes.

        Rather than one manifest per scene, this produces one manifest that
        covers the entire video duration so live2d-render runs once and
        produces an unbroken avatar video with no inter-scene cuts.

        Lipsync cues are converted to absolute timeline times using each
        scene's t_start_s offset. Emotion cues from cues_by_scene are placed
        at each scene's absolute start time.

        Args:
            lipsync_manifest: Loaded lipsync_manifest.json dict.
            audio_timeline: Loaded audio_timeline.json dict.
            run_dir: Pipeline run directory.
            cues_by_scene: Optional dict mapping scene_id -> list of cue
                           dicts (relative times). Defaults to neutral at 0.
            resolution: [width, height] for the render. Defaults to half of
                        the production resolution (540×960 for 1080p portrait).
            fps: Frame rate. Defaults to self.fps.

        Returns:
            The AvatarSceneManifest dict, also written to disk.
        """
        takes_dir = run_dir / "avatar_takes"
        takes_dir.mkdir(exist_ok=True)
        wav_dir = takes_dir / "wav"
        wav_dir.mkdir(exist_ok=True)

        if cues_by_scene is None:
            cues_by_scene = {}

        render_res = resolution or list(self.resolution)
        render_fps = fps or self.fps

        # --- Sort scenes by timeline start time ---------------------------------
        # Build a timing index from the audio_timeline for t_start_s
        timing_by_scene = {}
        for track in audio_timeline.get("tracks", []):
            if track.get("type") == "voiceover" and track.get("scene_id"):
                timing_by_scene[track["scene_id"]] = float(track.get("t_start_s", 0.0))

        scenes = sorted(
            lipsync_manifest.get("scenes", []),
            key=lambda s: timing_by_scene.get(s["scene_id"], float(s.get("t_start_s", 0.0))),
        )

        if not scenes:
            print("[WARN] package_full: lipsync_manifest has no scenes; writing empty manifest")

        # --- Convert each MP3 segment to a mono WAV ----------------------------
        wav_paths = []
        valid_scenes = []
        for scene in scenes:
            scene_id = scene["scene_id"]
            mp3_path = run_dir / scene["audio_file"].replace("\\", "/")
            if not mp3_path.exists():
                print(f"[SKIP] package_full {scene_id}: audio not found: {mp3_path}")
                continue
            wav_path = wav_dir / f"{scene_id}.wav"
            if not self._convert_to_wav(mp3_path, wav_path):
                print(f"[ERROR] package_full {scene_id}: WAV conversion failed")
                continue
            wav_paths.append(wav_path)
            valid_scenes.append(scene)

        # --- Concatenate WAVs into one full-timeline audio file ----------------
        full_wav = takes_dir / "full_audio.wav"
        if wav_paths:
            if not self._concat_wavs(wav_paths, full_wav):
                print("[ERROR] package_full: WAV concatenation failed; using first segment")
                full_wav = wav_paths[0]
        else:
            print("[WARN] package_full: no valid WAV segments; audio will be silent")
            full_wav = takes_dir / "full_audio.wav"
            full_wav.write_bytes(b"")

        # --- Build absolute lipsync keyframe list ------------------------------
        lipsync_keyframes = []
        for scene in valid_scenes:
            scene_id = scene["scene_id"]
            t_offset = float(scene.get("t_start_s", timing_by_scene.get(scene_id, 0.0)))
            for kf in self._build_lipsync(scene["cues"]):
                lipsync_keyframes.append({
                    "time": round(kf["time"] + t_offset, 4),
                    "mouth_shape": kf["mouth_shape"],
                })
        lipsync_keyframes.sort(key=lambda k: k["time"])

        # Open with X (silence) at t=0 if not already present
        if not lipsync_keyframes or lipsync_keyframes[0]["time"] > 0.0:
            lipsync_keyframes.insert(0, {"time": 0.0, "mouth_shape": "X"})

        # --- Build absolute director cue list ----------------------------------
        director_cues = []
        for scene in valid_scenes:
            scene_id = scene["scene_id"]
            t_offset = float(scene.get("t_start_s", timing_by_scene.get(scene_id, 0.0)))
            scene_cues = cues_by_scene.get(scene_id, list(_DEFAULT_CUES))
            for cue in scene_cues:
                abs_cue = dict(cue)
                abs_cue["time"] = round(float(cue.get("time", 0.0)) + t_offset, 4)
                director_cues.append(abs_cue)
        director_cues.sort(key=lambda c: c["time"])

        # Ensure at least one cue
        if not director_cues:
            director_cues = [{"time": 0.0, "emotion": "neutral"}]

        # --- Write manifest ---------------------------------------------------
        output_path = takes_dir / "avatar_full.mov"
        manifest = {
            "schema_version": "1.0",
            "model": self.model,
            "audio": str(full_wav),
            "output": str(output_path),
            "resolution": render_res,
            "fps": render_fps,
            "background": "transparent",
            "lipsync": lipsync_keyframes,
            "cues": director_cues,
        }

        manifest_path = takes_dir / "avatar_full_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(
            f"[OK] avatar_full_manifest.json: {len(valid_scenes)} scenes, "
            f"{len(lipsync_keyframes)} lipsync keyframes, {len(director_cues)} cues"
        )
        return manifest

    def _concat_wavs(self, wav_paths: list, output_path: Path) -> bool:
        """Concatenate WAV files into one via FFmpeg concat filter."""
        import shutil
        if len(wav_paths) == 1:
            shutil.copy(str(wav_paths[0]), str(output_path))
            return True

        cmd = [FFMPEG_PATH, "-y"]
        for p in wav_paths:
            cmd.extend(["-i", str(p)])

        n = len(wav_paths)
        labels = "".join(f"[{i}:a]" for i in range(n))
        cmd.extend([
            "-filter_complex", f"{labels}concat=n={n}:v=0:a=1[aout]",
            "-map", "[aout]",
            "-ar", str(RHUBARB_WAV_SAMPLE_RATE),
            "-ac", "1",
            str(output_path),
        ])

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[ERROR] ffmpeg concat: {e}")
            return False

        if result.returncode != 0:
            print(f"[ERROR] ffmpeg concat exited {result.returncode}")
            return False
        return True

    def review_takes(self, takes_dir: Path) -> dict:
        """Parse all .log files under takes_dir and emit avatar_render_report.json.

        Returns the report dict. Also writes it to takes_dir/avatar_render_report.json.
        """
        takes_dir = Path(takes_dir)
        log_files = sorted(takes_dir.glob("*.log"))

        scenes = []
        category_totals: dict[str, int] = {}

        for log_path in log_files:
            scene_id = log_path.stem
            scene_entry = self._parse_log(log_path, scene_id)
            scenes.append(scene_entry)
            for issue in scene_entry["issues"]:
                cat = issue["category"]
                category_totals[cat] = category_totals.get(cat, 0) + 1

        ok = sum(1 for s in scenes if s["status"] == "ok")
        warn = sum(1 for s in scenes if s["status"] == "warning")
        error = sum(1 for s in scenes if s["status"] == "error")

        report = {
            "schema_version": "1.0",
            "takes_dir": str(takes_dir).replace("\\", "/"),
            "scenes": scenes,
            "summary": {
                "total_scenes": len(scenes),
                "ok": ok,
                "warning": warn,
                "error": error,
                "by_category": category_totals,
            },
        }

        report_path = takes_dir / "avatar_render_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        status_line = f"ok={ok} warn={warn} error={error}"
        print(f"[INFO] avatar_render_report.json: {len(scenes)} scenes ({status_line})")
        if warn:
            for cat, count in category_totals.items():
                print(f"[WARN] {cat}: {count} occurrence(s)")

        return report

    def _parse_log(self, log_path: Path, scene_id: str) -> dict:
        """Parse a single renderer .log file into a scene result dict."""
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        issues = []
        frame_count = None
        render_fps = None
        output_requested = None
        output_actual = None
        has_error = False

        for line in lines:
            m = _RE_OUTPUT_LINE.search(line)
            if m:
                output_requested = m.group("path")

            m = _RE_CONTAINER_MISMATCH.search(line)
            if m:
                actual_ext = m.group("ext")
                requested = output_requested or ""
                actual = re.sub(r"\.\w+$", actual_ext, requested) if requested else ""
                issues.append({
                    "severity": "warn",
                    "category": "container_mismatch",
                    "message": f"transparent output forced {Path(requested).suffix} -> {actual_ext}",
                    "detail": f"output written to {Path(actual).name if actual else actual_ext}",
                    "implication": "downstream compositor must accept .mov instead of .mp4",
                })
                output_actual = actual

            m = _RE_UNDEFINED_EXPRESSION.search(line)
            if m:
                issues.append({
                    "severity": "warn",
                    "category": "undefined_expression",
                    "message": f"emotion '{m.group('name')}' not defined on model at t={m.group('t')}s",
                    "implication": "expression held at default; visual may be incorrect",
                })

            m = _RE_UNDEFINED_REACTION.search(line)
            if m:
                issues.append({
                    "severity": "warn",
                    "category": "undefined_reaction",
                    "message": f"reaction '{m.group('name')}' not defined on model at t={m.group('t')}s",
                    "implication": "reaction skipped; no motion played",
                })

            m = _RE_RENDER_COMPLETE.search(line)
            if m:
                frame_count = int(m.group("frames"))
                render_fps = float(m.group("fps"))

            m = _RE_FFMPEG_FINAL.search(line)
            if m:
                output_actual = output_actual or m.group("path")

            if _RE_ERROR.search(line):
                has_error = True
                issues.append({
                    "severity": "error",
                    "category": "render_error",
                    "message": line.strip(),
                    "implication": "scene may not have rendered correctly",
                })

        # check output file actually exists
        if output_actual:
            out_path = log_path.parent / Path(output_actual).name
            if not out_path.exists():
                has_error = True
                issues.append({
                    "severity": "error",
                    "category": "missing_output",
                    "message": f"expected output file not found: {out_path.name}",
                    "implication": "render did not complete; scene unusable",
                })

        if has_error:
            status = "error"
        elif issues:
            status = "warning"
        else:
            status = "ok"

        entry = {
            "scene_id": scene_id,
            "status": status,
            "output_file_requested": Path(output_requested).name if output_requested else None,
            "output_file_actual": Path(output_actual).name if output_actual else None,
            "frame_count": frame_count,
            "render_fps": render_fps,
            "issues": issues,
        }
        return entry

    def _convert_to_wav(self, src: Path, dst: Path) -> bool:
        """Convert audio file to WAV via FFmpeg. Returns True on success."""
        cmd = [
            FFMPEG_PATH, "-y",
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
