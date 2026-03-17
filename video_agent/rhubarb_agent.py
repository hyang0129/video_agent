"""Rhubarb Lip Sync agent.

Processes voiceover MP3 segments from an AudioTimeline and produces a
LipSyncManifest containing per-scene mouth-shape cues.

Rhubarb only accepts WAV/OGG input, so each MP3 segment is converted to a
temporary WAV via FFmpeg before processing, then deleted.

Usage:
    from video_agent.rhubarb_agent import RhubarbAgent
    manifest = RhubarbAgent().generate_lipsync_manifest(audio_timeline, run_dir)
"""

import json
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from video_agent.config import (
    FFMPEG_PATH,
    RHUBARB_EXECUTABLE,
    RHUBARB_OUTPUT_FORMAT,
    RHUBARB_RECOGNIZER,
    RHUBARB_WAV_SAMPLE_RATE,
)


class RhubarbAgent:
    """Generates lip sync cue data from voiceover audio segments."""

    def generate_lipsync_manifest(self, audio_timeline: dict, run_dir: Path) -> dict:
        """Process all voiceover tracks in audio_timeline and write lipsync_manifest.json.

        Args:
            audio_timeline: Loaded audio_timeline.json dict.
            run_dir: Root directory for this pipeline run (artifacts read/written here).

        Returns:
            The LipSyncManifest dict (also written to run_dir/lipsync_manifest.json).
        """
        lipsync_dir = run_dir / "lipsync"
        lipsync_dir.mkdir(exist_ok=True)

        voiceover_tracks = [
            t for t in audio_timeline.get("tracks", [])
            if t.get("type") == "voiceover"
        ]

        scene_results = []
        notes = []
        rhubarb_version = self._get_rhubarb_version()

        for track in voiceover_tracks:
            scene_id = track["scene_id"]
            audio_rel = track["file"].replace("\\", "/")
            audio_path = run_dir / audio_rel
            t_start_s = track.get("t_start_s", 0.0)

            if not audio_path.exists():
                notes.append(f"[SKIP] {scene_id}: audio file not found: {audio_path}")
                print(f"[SKIP] lipsync {scene_id}: audio file not found")
                continue

            cue_file_rel = f"lipsync/{scene_id}_cues.json"
            cue_path = run_dir / cue_file_rel

            cues = self._process_segment(audio_path, cue_path, scene_id)

            if cues is None:
                # Rhubarb unavailable or failed — include scene with silent default
                # cues so package_avatar can still convert the MP3 to WAV.
                notes.append(f"rhubarb_unavailable: {scene_id}: using default silent cues")
                cues = [{"start": 0.0, "end": 0.1, "value": "X"}]
                print(f"[WARN] lipsync {scene_id}: rhubarb failed, using silent default")

            scene_results.append({
                "scene_id": scene_id,
                "audio_file": audio_rel,
                "cue_file": cue_file_rel,
                "t_start_s": t_start_s,
                "cues": cues,
            })
            print(f"[OK] lipsync {scene_id}: {len(cues)} cues")

        manifest = {
            "schema_version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "lipsync_manifest_id": f"ls_{uuid.uuid4().hex[:8]}",
            "audio_timeline_ref": audio_timeline.get("audio_timeline_id", ""),
            "run_id": run_dir.name,
            "scenes": scene_results,
            "rhubarb_version": rhubarb_version,
            "recognizer": RHUBARB_RECOGNIZER,
            "processing_notes": notes,
        }

        manifest_path = run_dir / "lipsync_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"[OK] lipsync_manifest.json: {len(scene_results)}/{len(voiceover_tracks)} scenes processed")
        return manifest

    def _process_segment(self, audio_path: Path, cue_output_path: Path, scene_id: str):
        """Convert audio to WAV, run Rhubarb, return cues list or None on failure."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)

        try:
            if not self._convert_to_wav(audio_path, wav_path):
                return None
            return self._run_rhubarb(wav_path, cue_output_path, scene_id)
        finally:
            if wav_path.exists():
                wav_path.unlink()

    def _convert_to_wav(self, src: Path, dst: Path) -> bool:
        """Convert audio file to mono WAV via FFmpeg. Returns True on success."""
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(src),
            "-ar", str(RHUBARB_WAV_SAMPLE_RATE),
            "-ac", "1",
            str(dst),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[ERROR] ffmpeg conversion failed: {e}")
            return False

        if result.returncode != 0:
            print(f"[ERROR] ffmpeg exited {result.returncode} for {src.name}")
            return False
        return True

    def _run_rhubarb(self, wav_path: Path, cue_output_path: Path, scene_id: str):
        """Run Rhubarb on a WAV file and return parsed cues list, or None on failure."""
        exe = RHUBARB_EXECUTABLE
        if not Path(exe).exists():
            print(f"[ERROR] Rhubarb executable not found: {exe}")
            return None

        cmd = [
            exe,
            "-r", RHUBARB_RECOGNIZER,
            "-f", RHUBARB_OUTPUT_FORMAT,
            "-o", str(cue_output_path),
            "--machineReadable",
            str(wav_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            print(f"[ERROR] Rhubarb timed out on {scene_id}")
            return None
        except FileNotFoundError:
            print(f"[ERROR] Rhubarb executable not found: {exe}")
            return None

        if result.returncode != 0:
            stderr_snippet = result.stdout[-300:] if result.stdout else result.stderr[-300:]
            print(f"[ERROR] Rhubarb exited {result.returncode} on {scene_id}: {stderr_snippet}")
            return None

        if not cue_output_path.exists():
            print(f"[ERROR] Rhubarb produced no output for {scene_id}")
            return None

        with open(cue_output_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        return [
            {"start": c["start"], "end": c["end"], "value": c["value"]}
            for c in raw.get("mouthCues", [])
        ]

    def _get_rhubarb_version(self) -> str:
        try:
            r = subprocess.run(
                [RHUBARB_EXECUTABLE, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
