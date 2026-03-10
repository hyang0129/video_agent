# Rhubarb Lip Sync Integration

## Overview

[Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) is a command-line tool that analyzes an audio file and outputs **mouth-shape cues** — timestamped phoneme approximations mapped to the classic Preston Blair mouth shapes. This document specifies how to integrate Rhubarb into the pipeline to generate lip sync data from the voiceover MP3 segments produced by `AudioAgent`.

### Where it fits in the pipeline

```
AudioAgent → AudioTimeline + MP3 segments
    → RhubarbAgent  ← NEW
        → LipSyncManifest (JSON)
            → Live2D / CompositorAgent
```

Rhubarb runs **after** `AudioAgent` and **before** the compositor/renderer. It takes each `vo_scene_XX.mp3` file from `audio_segments/` and produces a JSON cue file with mouth-shape timings per scene.

---

## Mouth Shape Reference

Rhubarb maps phonemes to 9 mouth shapes:

| Shape | Phonemes | Description |
|-------|----------|-------------|
| `A`   | MBP      | Closed lips |
| `B`   | EE       | Slightly open, teeth visible |
| `C`   | EH, AE   | Open, rounded |
| `D`   | AI, AY   | Open, wide |
| `E`   | OH       | Rounded open |
| `F`   | OOH      | Tight rounded |
| `G`   | F, V     | Teeth on lip |
| `H`   | L, TH    | Tongue visible |
| `X`   | (silence)| Mouth closed / neutral |

These map directly to Live2D mouth parameter groups or sprite sheet frames.

---

## Prerequisites

### 1. Install Rhubarb

Download the latest release for Windows from:
`https://github.com/DanielSWolf/rhubarb-lip-sync/releases`

Extract to a stable path, e.g. `C:\tools\rhubarb\rhubarb.exe`.

Add to `config.py`:

```python
# Rhubarb Lip Sync
RHUBARB_EXECUTABLE = os.getenv("RHUBARB_PATH", r"C:\tools\rhubarb\rhubarb.exe")
RHUBARB_RECOGNIZER = "phonetic"   # "phonetic" (offline) or "pocketSphinx" (more accurate, requires install)
RHUBARB_OUTPUT_FORMAT = "json"
```

Set `RHUBARB_PATH` in your `.env` to override the default path.

### 2. Python dependency

No additional Python packages are required — Rhubarb is called via `subprocess`.

---

## Artifact Schema: `LipSyncManifest`

File: `results/<run_id>/lipsync_manifest.json`

```json
{
  "schema_version": "1.0.0",
  "created_at": "2026-03-10T12:00:00Z",
  "lipsync_manifest_id": "ls_<8-char-hex>",
  "audio_timeline_ref": "at_4bd9ca1c",
  "run_id": "<run_id>",
  "scenes": [
    {
      "scene_id": "scene_01",
      "audio_file": "audio_segments/vo_scene_01.mp3",
      "cue_file": "lipsync/scene_01_cues.json",
      "t_start_s": 0.0,
      "cues": [
        { "start": 0.00, "end": 0.18, "value": "X" },
        { "start": 0.18, "end": 0.32, "value": "A" },
        { "start": 0.32, "end": 0.55, "value": "D" },
        { "start": 0.55, "end": 0.71, "value": "B" }
      ]
    }
  ],
  "rhubarb_version": "1.13.0",
  "recognizer": "phonetic",
  "processing_notes": []
}
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `audio_timeline_ref` | ID of the `AudioTimeline` this was derived from |
| `t_start_s` | Scene start offset within the full video (for absolute timing) |
| `cues[].start` | Cue start time **relative to the segment file** (seconds) |
| `cues[].end` | Cue end time relative to the segment file (seconds) |
| `cues[].value` | Mouth shape character: A–H or X |

> **Absolute timing**: To get the mouth shape at any point in the final video, resolve `t_start_s + cue.start`.

---

## Implementation

### New file: `src/rhubarb_agent.py`

```python
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.config import RHUBARB_EXECUTABLE, RHUBARB_RECOGNIZER, RHUBARB_OUTPUT_FORMAT


class RhubarbAgent:
    """
    Processes voiceover MP3 segments from an AudioTimeline and produces
    a LipSyncManifest containing per-scene mouth-shape cues.
    """

    def generate_lipsync_manifest(self, audio_timeline: dict, run_dir: Path) -> dict:
        """
        Entry point. Takes a loaded audio_timeline dict and the run directory.
        Returns the LipSyncManifest dict and writes it to disk.
        """
        lipsync_dir = run_dir / "lipsync"
        lipsync_dir.mkdir(exist_ok=True)

        voiceover_tracks = [
            t for t in audio_timeline.get("tracks", [])
            if t.get("type") == "voiceover"
        ]

        scene_results = []
        notes = []

        for track in voiceover_tracks:
            scene_id = track["scene_id"]
            audio_rel = track["file"]
            audio_path = run_dir / audio_rel
            t_start_s = track.get("t_start_s", 0.0)

            if not audio_path.exists():
                notes.append(f"[SKIP] {scene_id}: audio file not found at {audio_path}")
                continue

            cue_file_rel = f"lipsync/{scene_id}_cues.json"
            cue_path = run_dir / cue_file_rel

            cues, rhubarb_version = self._run_rhubarb(audio_path, cue_path)

            if cues is None:
                notes.append(f"[ERROR] {scene_id}: rhubarb failed, skipping")
                continue

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
            "rhubarb_version": rhubarb_version or "unknown",
            "recognizer": RHUBARB_RECOGNIZER,
            "processing_notes": notes,
        }

        manifest_path = run_dir / "lipsync_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"[OK] lipsync_manifest.json written ({len(scene_results)} scenes)")
        return manifest

    def _run_rhubarb(self, audio_path: Path, cue_output_path: Path):
        """
        Calls the Rhubarb executable on a single audio file.
        Returns (cues_list, rhubarb_version) or (None, None) on failure.
        """
        exe = RHUBARB_EXECUTABLE
        if not Path(exe).exists():
            print(f"[ERROR] Rhubarb executable not found: {exe}")
            return None, None

        cmd = [
            exe,
            "-r", RHUBARB_RECOGNIZER,
            "-f", RHUBARB_OUTPUT_FORMAT,
            "-o", str(cue_output_path),
            "--machineReadable",
            str(audio_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            print(f"[ERROR] Rhubarb timed out on {audio_path.name}")
            return None, None
        except FileNotFoundError:
            print(f"[ERROR] Rhubarb executable not found: {exe}")
            return None, None

        if result.returncode != 0:
            print(f"[ERROR] Rhubarb exited {result.returncode}: {result.stderr[:200]}")
            return None, None

        if not cue_output_path.exists():
            print(f"[ERROR] Rhubarb did not produce output at {cue_output_path}")
            return None, None

        with open(cue_output_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        cues = [
            {
                "start": entry["start"],
                "end": entry["end"],
                "value": entry["value"],
            }
            for entry in raw.get("mouthCues", [])
        ]

        version = raw.get("metadata", {}).get("soundFile", "")
        rhubarb_version = self._parse_rhubarb_version(exe)

        return cues, rhubarb_version

    def _parse_rhubarb_version(self, exe: str) -> str:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
            return r.stdout.strip().split()[-1] if r.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
```

---

## Pipeline Integration

### `main.py` — add stage 5.5

In `main.py`, add a new stage between `audio` and `compositor`:

```python
elif args.stage == "lipsync":
    from src.rhubarb_agent import RhubarbAgent
    audio_timeline = load_artifact(run_dir / "audio_timeline.json")
    agent = RhubarbAgent()
    manifest = agent.generate_lipsync_manifest(audio_timeline, run_dir)
    print(f"[OK] LipSyncManifest: {manifest['lipsync_manifest_id']}")
```

CLI usage:

```bash
venv/Scripts/python.exe main.py --stage lipsync --run-id <run_id>
```

### Full pipeline run

When running end-to-end, insert the lipsync stage after `audio`:

```
main.py --stage market_research
main.py --stage script
main.py --stage video_plan
main.py --stage audio      # produces audio_timeline.json + MP3s
main.py --stage lipsync    # produces lipsync_manifest.json   <- NEW
main.py --stage compositor
main.py --stage render
```

---

## Consuming the LipSyncManifest

### In the compositor / Live2D renderer

Load `lipsync_manifest.json` alongside `audio_timeline.json`. For each frame at time `t`:

```python
def get_mouth_shape(lipsync_manifest: dict, t: float) -> str:
    """Return the mouth shape character at absolute time t (seconds)."""
    for scene in lipsync_manifest["scenes"]:
        t_scene = t - scene["t_start_s"]
        for cue in scene["cues"]:
            if cue["start"] <= t_scene < cue["end"]:
                return cue["value"]
    return "X"  # silence / default
```

This function can be called at video frame rate (e.g. every 1/30 s) to drive a
Live2D mouth parameter or swap a sprite-sheet mouth frame.

### Live2D parameter mapping

| Rhubarb shape | Live2D parameter suggestion |
|---------------|-----------------------------|
| `X`           | `ParamMouthOpenY = 0.0`     |
| `A`           | `ParamMouthOpenY = 0.05`    |
| `B`           | `ParamMouthOpenY = 0.2`     |
| `C`           | `ParamMouthOpenY = 0.4`     |
| `D`           | `ParamMouthOpenY = 0.7`     |
| `E`           | `ParamMouthOpenY = 0.5`, `ParamMouthForm = -0.5` |
| `F`           | `ParamMouthOpenY = 0.3`, `ParamMouthForm = -1.0` |
| `G`           | `ParamMouthOpenY = 0.15`    |
| `H`           | `ParamMouthOpenY = 0.25`    |

Smooth between consecutive cues using linear interpolation over ~30–60 ms to
avoid hard snapping.

---

## Testing

### Offline test (no API keys required)

Use the existing WW2 Tanks fixture audio once it exists, or generate a short test
segment with `--voice silent` to produce a placeholder:

```bash
# Generate a real segment for testing
venv/Scripts/python.exe main.py --stage audio --run-id test_rhubarb

# Then run lipsync stage on the result
venv/Scripts/python.exe main.py --stage lipsync --run-id test_rhubarb
```

### Verify output

```bash
# Check cue file was produced for each scene
ls results/test_rhubarb/lipsync/

# Inspect a cue file
cat results/test_rhubarb/lipsync/scene_01_cues.json

# Confirm manifest is valid
venv/Scripts/python.exe -c "
import json
m = json.load(open('results/test_rhubarb/lipsync_manifest.json'))
print('scenes:', len(m['scenes']))
for s in m['scenes']:
    print(s['scene_id'], len(s['cues']), 'cues')
"
```

### Pytest unit test skeleton

Add to `tests/test_rhubarb_agent.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.rhubarb_agent import RhubarbAgent


MOCK_RHUBARB_OUTPUT = {
    "metadata": {"soundFile": "vo_scene_01.mp3"},
    "mouthCues": [
        {"start": 0.00, "end": 0.18, "value": "X"},
        {"start": 0.18, "end": 0.45, "value": "A"},
        {"start": 0.45, "end": 0.72, "value": "D"},
    ],
}

def test_generate_lipsync_manifest(tmp_path):
    audio_dir = tmp_path / "audio_segments"
    audio_dir.mkdir()
    (audio_dir / "vo_scene_01.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)

    audio_timeline = {
        "audio_timeline_id": "at_test001",
        "tracks": [
            {
                "type": "voiceover",
                "scene_id": "scene_01",
                "file": "audio_segments/vo_scene_01.mp3",
                "t_start_s": 0.0,
            }
        ],
    }

    agent = RhubarbAgent()

    def fake_run_rhubarb(audio_path, cue_output_path):
        cue_output_path.parent.mkdir(exist_ok=True)
        cue_output_path.write_text(json.dumps(MOCK_RHUBARB_OUTPUT))
        cues = [
            {"start": c["start"], "end": c["end"], "value": c["value"]}
            for c in MOCK_RHUBARB_OUTPUT["mouthCues"]
        ]
        return cues, "1.13.0"

    with patch.object(agent, "_run_rhubarb", side_effect=fake_run_rhubarb):
        manifest = agent.generate_lipsync_manifest(audio_timeline, tmp_path)

    assert len(manifest["scenes"]) == 1
    assert manifest["scenes"][0]["scene_id"] == "scene_01"
    assert len(manifest["scenes"][0]["cues"]) == 3
    assert (tmp_path / "lipsync_manifest.json").exists()
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Rhubarb not installed | `[ERROR]` log, scene skipped, manifest still written with `processing_notes` |
| Audio segment missing | `[SKIP]` log, scene omitted from manifest |
| Rhubarb timeout (>120s) | `[ERROR]` log, scene skipped |
| Rhubarb non-zero exit | `[ERROR]` log with first 200 chars of stderr, scene skipped |
| All scenes fail | Manifest written with empty `scenes` list; downstream agent should check and warn |

The stage is **non-blocking** by design: a missing or failed lipsync stage should
not prevent the render from completing. The compositor/Live2D layer should fall
back to a neutral mouth pose (`X`) when `lipsync_manifest.json` is absent.

---

## Config additions summary

Add to `src/config.py`:

```python
# ── Rhubarb Lip Sync ──────────────────────────────────────────────────────────
RHUBARB_EXECUTABLE = os.getenv("RHUBARB_PATH", r"C:\tools\rhubarb\rhubarb.exe")
RHUBARB_RECOGNIZER = "phonetic"   # "phonetic" | "pocketSphinx"
RHUBARB_OUTPUT_FORMAT = "json"
```

Add to `.env.example`:

```
RHUBARB_PATH=C:\tools\rhubarb\rhubarb.exe
```

---

## Rhubarb output format reference

When called with `-f json`, Rhubarb writes:

```json
{
  "metadata": {
    "soundFile": "vo_scene_01.mp3",
    "duration": 3.019
  },
  "mouthCues": [
    { "start": 0.00, "end": 0.18, "value": "X" },
    { "start": 0.18, "end": 0.32, "value": "A" },
    ...
  ]
}
```

The `--machineReadable` flag suppresses progress output to stderr, keeping logs
clean in CI/pipeline runs.
