"""Tests for RhubarbAgent.

Unit tests use mocked subprocess calls — no Rhubarb binary required.
Fixture integration tests use real audio from tests/fixtures/cheese_facts_2026_03_08/
and require rhubarb.exe at the path in RHUBARB_EXECUTABLE (config.py).

Run unit tests only:
    pytest tests/test_rhubarb_agent.py -v -m "not fixture_integration"

Run all tests including fixture integration (requires Rhubarb installed):
    pytest tests/test_rhubarb_agent.py -v
"""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.rhubarb_agent import RhubarbAgent

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CHEESE_FIXTURE = Path(__file__).parent / "fixtures" / "cheese_facts_2026_03_08"

MOCK_RHUBARB_CUES = {
    "metadata": {"soundFile": "vo_scene_01.wav", "duration": 7.15},
    "mouthCues": [
        {"start": 0.00, "end": 0.15, "value": "X"},
        {"start": 0.15, "end": 0.32, "value": "C"},
        {"start": 0.32, "end": 0.71, "value": "B"},
        {"start": 0.71, "end": 0.85, "value": "F"},
        {"start": 0.85, "end": 1.06, "value": "B"},
        {"start": 1.06, "end": 1.25, "value": "A"},
        {"start": 1.25, "end": 7.15, "value": "X"},
    ],
}

MINIMAL_AUDIO_TIMELINE = {
    "schema_version": "1.0.0",
    "audio_timeline_id": "at_test001",
    "tracks": [
        {
            "type": "voiceover",
            "scene_id": "scene_01",
            "file": "audio_segments/vo_scene_01.mp3",
            "t_start_s": 0.0,
            "t_end_s": 7.15,
        },
        {
            "type": "voiceover",
            "scene_id": "scene_02",
            "file": "audio_segments/vo_scene_02.mp3",
            "t_start_s": 7.15,
            "t_end_s": 11.47,
        },
        {
            "type": "music",
            "file": "assets/music/default_music.mp3",
            "t_start_s": 0.0,
            "t_end_s": 38.0,
        },
    ],
}


@pytest.fixture
def run_dir(tmp_path):
    """Minimal run directory with stub audio files."""
    seg_dir = tmp_path / "audio_segments"
    seg_dir.mkdir()
    for name in ["vo_scene_01.mp3", "vo_scene_02.mp3"]:
        (seg_dir / name).write_bytes(b"\xff\xfb" + b"\x00" * 512)
    return tmp_path


@pytest.fixture
def agent():
    return RhubarbAgent()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_process_segment(cue_data=None, fail_scenes=None):
    """Return a side_effect function that writes a cue file and returns parsed cues."""
    if cue_data is None:
        cue_data = MOCK_RHUBARB_CUES
    if fail_scenes is None:
        fail_scenes = set()

    def fake(audio_path, cue_output_path, scene_id):
        if scene_id in fail_scenes:
            return None
        cue_output_path.parent.mkdir(parents=True, exist_ok=True)
        cue_output_path.write_text(json.dumps(cue_data), encoding="utf-8")
        return [
            {"start": c["start"], "end": c["end"], "value": c["value"]}
            for c in cue_data["mouthCues"]
        ]

    return fake


# ---------------------------------------------------------------------------
# Unit tests — no binary required
# ---------------------------------------------------------------------------

class TestGenerateLipsyncManifest:

    def test_manifest_schema_fields(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        assert manifest["schema_version"] == "1.0.0"
        assert "created_at" in manifest
        assert manifest["lipsync_manifest_id"].startswith("ls_")
        assert manifest["audio_timeline_ref"] == "at_test001"
        assert manifest["recognizer"] == "phonetic"
        assert isinstance(manifest["scenes"], list)
        assert isinstance(manifest["processing_notes"], list)

    def test_only_voiceover_tracks_processed(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        # music track must be excluded
        assert len(manifest["scenes"]) == 2
        scene_ids = {s["scene_id"] for s in manifest["scenes"]}
        assert scene_ids == {"scene_01", "scene_02"}

    def test_scene_has_required_fields(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        scene = manifest["scenes"][0]
        assert "scene_id" in scene
        assert "audio_file" in scene
        assert "cue_file" in scene
        assert "t_start_s" in scene
        assert "cues" in scene

    def test_t_start_s_preserved(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        scenes_by_id = {s["scene_id"]: s for s in manifest["scenes"]}
        assert scenes_by_id["scene_01"]["t_start_s"] == 0.0
        assert scenes_by_id["scene_02"]["t_start_s"] == 7.15

    def test_cue_file_paths_relative_to_run_dir(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        for scene in manifest["scenes"]:
            assert scene["cue_file"].startswith("lipsync/")
            assert scene["cue_file"].endswith("_cues.json")

    def test_manifest_written_to_disk(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        manifest_path = run_dir / "lipsync_manifest.json"
        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text())
        assert loaded["schema_version"] == "1.0.0"

    def test_lipsync_dir_created(self, agent, run_dir):
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        assert (run_dir / "lipsync").is_dir()

    def test_missing_audio_file_skipped(self, agent, tmp_path):
        """Scene whose audio file does not exist is skipped; others proceed."""
        seg_dir = tmp_path / "audio_segments"
        seg_dir.mkdir()
        (seg_dir / "vo_scene_02.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 512)
        # vo_scene_01.mp3 intentionally missing

        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, tmp_path)

        scene_ids = {s["scene_id"] for s in manifest["scenes"]}
        assert "scene_01" not in scene_ids
        assert "scene_02" in scene_ids
        assert any("SKIP" in n and "scene_01" in n for n in manifest["processing_notes"])

    def test_failed_rhubarb_scene_skipped(self, agent, run_dir):
        """If _process_segment returns None, scene is omitted and a note is added."""
        fake = _make_fake_process_segment(fail_scenes={"scene_01"})
        with patch.object(agent, "_process_segment", side_effect=fake):
            manifest = agent.generate_lipsync_manifest(MINIMAL_AUDIO_TIMELINE, run_dir)

        scene_ids = {s["scene_id"] for s in manifest["scenes"]}
        assert "scene_01" not in scene_ids
        assert "scene_02" in scene_ids
        assert any("ERROR" in n and "scene_01" in n for n in manifest["processing_notes"])

    def test_empty_tracks_produces_empty_scenes(self, agent, tmp_path):
        empty_timeline = {"audio_timeline_id": "at_empty", "tracks": []}
        with patch.object(agent, "_process_segment", side_effect=_make_fake_process_segment()):
            manifest = agent.generate_lipsync_manifest(empty_timeline, tmp_path)

        assert manifest["scenes"] == []


class TestConvertToWav:

    def test_returns_true_on_success(self, agent, tmp_path):
        src = tmp_path / "test.mp3"
        src.write_bytes(b"\x00" * 10)
        dst = tmp_path / "test.wav"

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = agent._convert_to_wav(src, dst)

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert str(src) in cmd
        assert str(dst) in cmd

    def test_returns_false_on_nonzero_exit(self, agent, tmp_path):
        src = tmp_path / "test.mp3"
        src.write_bytes(b"\x00" * 10)
        dst = tmp_path / "test.wav"

        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            result = agent._convert_to_wav(src, dst)

        assert result is False

    def test_returns_false_on_ffmpeg_not_found(self, agent, tmp_path):
        src = tmp_path / "test.mp3"
        src.write_bytes(b"\x00" * 10)
        dst = tmp_path / "test.wav"

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = agent._convert_to_wav(src, dst)

        assert result is False

    def test_returns_false_on_timeout(self, agent, tmp_path):
        import subprocess
        src = tmp_path / "test.mp3"
        src.write_bytes(b"\x00" * 10)
        dst = tmp_path / "test.wav"

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 60)):
            result = agent._convert_to_wav(src, dst)

        assert result is False


class TestRunRhubarb:

    def test_returns_cues_on_success(self, agent, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"\x00" * 10)
        cue_path = tmp_path / "test_cues.json"

        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_subprocess_run(cmd, **kwargs):
            # Simulate rhubarb writing the output file
            cue_path.write_text(json.dumps(MOCK_RHUBARB_CUES), encoding="utf-8")
            return mock_result

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            cues = agent._run_rhubarb(wav_path, cue_path, "scene_01")

        assert cues is not None
        assert len(cues) == len(MOCK_RHUBARB_CUES["mouthCues"])
        assert all({"start", "end", "value"} <= set(c) for c in cues)

    def test_returns_none_if_output_file_missing(self, agent, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"\x00" * 10)
        cue_path = tmp_path / "test_cues.json"

        mock_result = MagicMock()
        mock_result.returncode = 0
        # Don't write the cue file — simulates rhubarb not producing output

        with patch("subprocess.run", return_value=mock_result):
            cues = agent._run_rhubarb(wav_path, cue_path, "scene_01")

        assert cues is None

    def test_returns_none_on_nonzero_exit(self, agent, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"\x00" * 10)
        cue_path = tmp_path / "test_cues.json"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "{ \"type\": \"failure\", \"reason\": \"some error\" }"

        with patch("subprocess.run", return_value=mock_result):
            cues = agent._run_rhubarb(wav_path, cue_path, "scene_01")

        assert cues is None

    def test_returns_none_if_rhubarb_not_found(self, agent, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"\x00" * 10)
        cue_path = tmp_path / "test_cues.json"

        with patch("src.rhubarb_agent.RHUBARB_EXECUTABLE", "/nonexistent/rhubarb.exe"):
            cues = agent._run_rhubarb(wav_path, cue_path, "scene_01")

        assert cues is None

    def test_cue_values_are_valid_mouth_shapes(self, agent, tmp_path):
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(b"\x00" * 10)
        cue_path = tmp_path / "test_cues.json"

        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(cmd, **kwargs):
            cue_path.write_text(json.dumps(MOCK_RHUBARB_CUES), encoding="utf-8")
            return mock_result

        with patch("subprocess.run", side_effect=fake_run):
            cues = agent._run_rhubarb(wav_path, cue_path, "scene_01")

        valid_shapes = set("ABCDEFGHX")
        for cue in cues:
            assert cue["value"] in valid_shapes, f"Unexpected mouth shape: {cue['value']}"


class TestProcessSegment:

    def test_temp_wav_deleted_on_success(self, agent, tmp_path):
        audio_path = tmp_path / "vo.mp3"
        audio_path.write_bytes(b"\xff\xfb" + b"\x00" * 512)
        cue_path = tmp_path / "cues.json"

        created_wavs = []

        def fake_convert(src, dst):
            dst.write_bytes(b"\x00" * 10)
            created_wavs.append(dst)
            return True

        def fake_rhubarb(wav, cue_out, scene_id):
            cue_out.write_text(json.dumps(MOCK_RHUBARB_CUES))
            return [{"start": 0.0, "end": 1.0, "value": "X"}]

        with patch.object(agent, "_convert_to_wav", side_effect=fake_convert), \
             patch.object(agent, "_run_rhubarb", side_effect=fake_rhubarb):
            agent._process_segment(audio_path, cue_path, "scene_01")

        for wav in created_wavs:
            assert not wav.exists(), "Temp WAV should be deleted after processing"

    def test_temp_wav_deleted_on_rhubarb_failure(self, agent, tmp_path):
        audio_path = tmp_path / "vo.mp3"
        audio_path.write_bytes(b"\xff\xfb" + b"\x00" * 512)
        cue_path = tmp_path / "cues.json"

        created_wavs = []

        def fake_convert(src, dst):
            dst.write_bytes(b"\x00" * 10)
            created_wavs.append(dst)
            return True

        with patch.object(agent, "_convert_to_wav", side_effect=fake_convert), \
             patch.object(agent, "_run_rhubarb", return_value=None):
            result = agent._process_segment(audio_path, cue_path, "scene_01")

        assert result is None
        for wav in created_wavs:
            assert not wav.exists(), "Temp WAV should be deleted even on failure"

    def test_returns_none_if_conversion_fails(self, agent, tmp_path):
        audio_path = tmp_path / "vo.mp3"
        audio_path.write_bytes(b"\xff\xfb" + b"\x00" * 512)
        cue_path = tmp_path / "cues.json"

        with patch.object(agent, "_convert_to_wav", return_value=False):
            result = agent._process_segment(audio_path, cue_path, "scene_01")

        assert result is None


# ---------------------------------------------------------------------------
# Fixture integration tests — require rhubarb.exe installed
# ---------------------------------------------------------------------------

@pytest.fixture
def cheese_run_dir(tmp_path):
    """Copy cheese_facts fixture into a temporary run directory."""
    if not CHEESE_FIXTURE.exists():
        pytest.skip(f"Cheese facts fixture not found: {CHEESE_FIXTURE}")
    dst = tmp_path / "cheese_facts_2026_03_08"
    shutil.copytree(CHEESE_FIXTURE, dst)
    return dst


@pytest.mark.fixture_integration
class TestFixtureIntegration:
    """Integration tests using the cheese_facts_2026_03_08 fixture.

    These tests call Rhubarb for real. Run time: ~10-30s per scene.
    Mark: fixture_integration
    """

    def test_rhubarb_installed(self):
        """Verify rhubarb.exe is present and reports a version."""
        agent = RhubarbAgent()
        version = agent._get_rhubarb_version()
        assert "Rhubarb" in version or version != "unknown", (
            "rhubarb.exe not found or not working — install from "
            "https://github.com/DanielSWolf/rhubarb-lip-sync/releases"
        )

    def test_full_manifest_from_cheese_fixture(self, cheese_run_dir):
        """Run full lipsync pipeline on all 6 cheese_facts scenes."""
        audio_timeline_path = cheese_run_dir / "audio_timeline.json"
        audio_timeline = json.loads(audio_timeline_path.read_text())

        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        voiceover_count = sum(
            1 for t in audio_timeline["tracks"] if t.get("type") == "voiceover"
        )

        assert len(manifest["scenes"]) == voiceover_count, (
            f"Expected {voiceover_count} scenes, got {len(manifest['scenes'])}. "
            f"Notes: {manifest['processing_notes']}"
        )

    def test_all_scenes_have_cues(self, cheese_run_dir):
        """Every processed scene must have at least one cue."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        for scene in manifest["scenes"]:
            assert len(scene["cues"]) > 0, f"{scene['scene_id']} has no cues"

    def test_cue_values_are_valid_mouth_shapes(self, cheese_run_dir):
        """All cue values must be valid Preston Blair mouth shape characters."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        valid = set("ABCDEFGHX")
        for scene in manifest["scenes"]:
            for cue in scene["cues"]:
                assert cue["value"] in valid, (
                    f"{scene['scene_id']}: invalid mouth shape '{cue['value']}'"
                )

    def test_cue_timing_is_contiguous(self, cheese_run_dir):
        """Cues within each scene should be contiguous (end == next start)."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        for scene in manifest["scenes"]:
            cues = scene["cues"]
            for i in range(len(cues) - 1):
                assert abs(cues[i]["end"] - cues[i + 1]["start"]) < 0.01, (
                    f"{scene['scene_id']} gap between cue {i} and {i+1}: "
                    f"{cues[i]['end']} -> {cues[i+1]['start']}"
                )

    def test_cue_files_written_to_disk(self, cheese_run_dir):
        """Individual cue JSON files must exist for each processed scene."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        for scene in manifest["scenes"]:
            cue_file = cheese_run_dir / scene["cue_file"]
            assert cue_file.exists(), f"Cue file missing: {cue_file}"
            raw = json.loads(cue_file.read_text())
            assert "mouthCues" in raw

    def test_manifest_json_written_to_disk(self, cheese_run_dir):
        """lipsync_manifest.json must be valid JSON with expected structure."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        manifest_path = cheese_run_dir / "lipsync_manifest.json"
        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text())
        assert loaded["audio_timeline_ref"] == "at_6a7dee35"
        assert loaded["rhubarb_version"].startswith("Rhubarb")

    def test_scene_01_timing_matches_audio_timeline(self, cheese_run_dir):
        """scene_01 t_start_s in manifest must match audio_timeline value."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        timeline_starts = {
            t["scene_id"]: t["t_start_s"]
            for t in audio_timeline["tracks"]
            if t.get("type") == "voiceover"
        }
        for scene in manifest["scenes"]:
            expected = timeline_starts[scene["scene_id"]]
            assert scene["t_start_s"] == expected

    def test_get_mouth_shape_helper(self, cheese_run_dir):
        """Validate the absolute-time lookup helper against the manifest."""
        audio_timeline = json.loads((cheese_run_dir / "audio_timeline.json").read_text())
        agent = RhubarbAgent()
        manifest = agent.generate_lipsync_manifest(audio_timeline, cheese_run_dir)

        # t=0 should return a valid shape (start of scene_01)
        shape = get_mouth_shape(manifest, 0.0)
        assert shape in set("ABCDEFGHX")

        # t beyond all scenes should return X (silence)
        shape = get_mouth_shape(manifest, 9999.0)
        assert shape == "X"


def get_mouth_shape(manifest: dict, t: float) -> str:
    """Return the mouth shape at absolute video time t (seconds).

    Searches all scenes in the manifest. If t falls within a cue's
    [start, end) window (relative to the scene's t_start_s offset),
    returns that cue's value. Returns 'X' (neutral/silence) if no match.
    """
    for scene in manifest["scenes"]:
        t_scene = t - scene["t_start_s"]
        for cue in scene["cues"]:
            if cue["start"] <= t_scene < cue["end"]:
                return cue["value"]
    return "X"
