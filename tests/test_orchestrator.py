"""Tests for ProductionOrchestrator and ProductionReport emission.

Run with: pytest tests/test_orchestrator.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from video_agent.orchestrator import ProductionOrchestrator, _produce_parallel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sample_screenplay() -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "screenplay_id": "sp_test",
        "concept_ref": "c_test",
        "format": "facts",
        "target_duration_s": 20,
        "narrator_character": {"type": "voice_only", "voice_preset": "narrator"},
        "music_tone": "upbeat",
        "scenes": [
            {
                "scene_id": "scene_01",
                "vo_line": "Hello world.",
                "target_duration_s": 5,
                "on_screen_text": "Hello",
                "visual": {"description": "greeting", "search_queries": ["greeting image"]},
                "music_energy": "low",
            },
            {
                "scene_id": "scene_02",
                "vo_line": "Second fact here.",
                "target_duration_s": 5,
                "on_screen_text": "Fact 2",
                "visual": {"description": "abstract", "search_queries": ["abstract image"]},
                "music_energy": "medium",
            },
        ],
        "feasibility_report": None,
    }


@pytest.fixture
def sample_video_plan() -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "video_plan_id": "vp_test_001",
        "topic_id": "facts",
        "subtopic_id": "sp_test",
        "audio": {"tts": {"enabled": True, "voice": "narrator"}},
        "scenes": [
            {
                "scene_id": "scene_01",
                "t_start_s": 0.0,
                "t_end_s": 5.0,
                "vo_line": "Hello world.",
                "on_screen_text": "Hello",
                "visual_direction": "b-roll",
                "asset_prompts": ["Hello"],
            },
            {
                "scene_id": "scene_02",
                "t_start_s": 5.0,
                "t_end_s": 10.0,
                "vo_line": "Second fact here.",
                "on_screen_text": "Fact 2",
                "visual_direction": "b-roll",
                "asset_prompts": ["Fact 2"],
            },
        ],
    }


@pytest.fixture
def sample_script_package() -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "script_package_id": "sg_test_001",
        "topic_id": "facts",
        "subtopic_id": "sp_test",
        "script": {
            "voiceover": "Hello world. Second fact here.",
            "beats": [
                {
                    "scene_id": "scene_01",
                    "t_start_s": 0.0,
                    "t_end_s": 5.0,
                    "on_screen_text": "Hello",
                    "vo_line": "Hello world.",
                },
                {
                    "scene_id": "scene_02",
                    "t_start_s": 5.0,
                    "t_end_s": 10.0,
                    "on_screen_text": "Fact 2",
                    "vo_line": "Second fact here.",
                },
            ],
        },
        "asset_prompts": ["greeting image", "abstract image"],
        "audio": {"tts": {"voice": "narrator"}},
    }


# ---------------------------------------------------------------------------
# ProductionReport schema tests
# ---------------------------------------------------------------------------

class TestProductionReportSchema:
    def test_audio_agent_writes_production_report_on_tts_failure(
        self, tmp_run_dir, sample_video_plan
    ):
        """When TTS raises TTSError, audio_agent should write a degraded issue and continue."""
        from video_agent.audio_agent import AudioGenerationAgent
        from video_agent.tools.tts_tools import TTSError

        # Construct directly without tts_backend so the ElevenLabs code path is used
        agent = AudioGenerationAgent(output_dir=tmp_run_dir, voice_id="narrator")

        with patch("video_agent.audio_agent.generate_voiceover", side_effect=TTSError("API down")):
            timeline = agent.generate_audio_timeline(sample_video_plan)

        # Timeline still has tracks (silent fallback)
        vo_tracks = [t for t in timeline["tracks"] if t.get("type") == "voiceover"]
        assert len(vo_tracks) == 2

        # production_report.json must exist
        report_path = tmp_run_dir / "production_report.json"
        assert report_path.exists()

        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "1.0.0"
        assert report["degraded_scene_count"] == 2
        issues = report["issues"]
        assert len(issues) == 2
        for issue in issues:
            assert issue["agent"] == "AudioAgent"
            assert issue["issue"] == "tts_failed"
            assert issue["revision_field"] == "vo_line"
            assert issue["revision_possible"] is True

    def test_audio_agent_reports_duration_overshoot(self, tmp_run_dir, sample_video_plan):
        """vo_too_long is flagged when TTS duration exceeds target * 1.2."""
        from video_agent.audio_agent import AudioGenerationAgent

        def _fake_voiceover(text, voice_id, output_path):
            # Write a real file so ffprobe can't be used; metadata drives duration
            Path(output_path).write_bytes(b"\xff\xfb" * 100)
            return Path(output_path), {"estimated_duration_s": 10.0, "character_count": len(text)}

        # Construct directly without tts_backend so the ElevenLabs code path is used
        agent = AudioGenerationAgent(output_dir=tmp_run_dir, voice_id="narrator")

        with patch("video_agent.audio_agent.generate_voiceover", side_effect=_fake_voiceover):
            timeline = agent.generate_audio_timeline(sample_video_plan)

        report_path = tmp_run_dir / "production_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text())

        overshoot_issues = [i for i in report["issues"] if i.get("issue") == "vo_too_long"]
        # Both scenes have t_end - t_start = 5s, fake TTS returns 10s (> 5 * 1.2 = 6s)
        assert len(overshoot_issues) == 2
        assert all(i["revision_field"] == "vo_line" for i in overshoot_issues)

    def test_audio_agent_scene_ids_filter(self, tmp_run_dir, sample_video_plan):
        """Passing scene_ids skips unmatched scenes."""
        from video_agent.audio_agent import create_audio_agent

        agent = create_audio_agent(output_dir=tmp_run_dir, voice="silent")
        timeline = agent.generate_audio_timeline(sample_video_plan, scene_ids=["scene_01"])

        vo_tracks = [t for t in timeline["tracks"] if t.get("type") == "voiceover"]
        assert len(vo_tracks) == 1
        assert vo_tracks[0]["scene_id"] == "scene_01"

    def test_script_image_agent_writes_production_report_on_no_candidates(
        self, tmp_run_dir, sample_script_package
    ):
        """When no images are found, ScriptImageAgent writes a degraded issue."""
        from video_agent.script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent

        agent = ScriptImageRetrievalAgent(
            ScriptImageConfig(output_dir=tmp_run_dir, min_candidates_per_segment=1)
        )

        with patch("video_agent.script_image_agent.search_pexels_images", return_value=[]):
            with patch("video_agent.script_image_agent.search_wikimedia_images", return_value=[]):
                manifest = agent.generate_script_image_manifest(
                    sample_script_package, run_id="vp_test_001"
                )

        report_path = tmp_run_dir / "production_report.json"
        assert report_path.exists()

        report = json.loads(report_path.read_text())
        assert report["degraded_scene_count"] == 2
        issues = report["issues"]
        assert all(i["agent"] == "ScriptImageAgent" for i in issues)
        assert all(i["issue"] == "no_relevant_image" for i in issues)
        assert all(i["revision_field"] == "visual" for i in issues)

    def test_production_report_merges_audio_and_image_issues(
        self, tmp_run_dir, sample_video_plan, sample_script_package
    ):
        """Both agents write to production_report.json; issues accumulate."""
        from video_agent.audio_agent import AudioGenerationAgent
        from video_agent.script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent
        from video_agent.tools.tts_tools import TTSError

        # Construct directly without tts_backend so the ElevenLabs code path is used
        audio_agent = AudioGenerationAgent(output_dir=tmp_run_dir, voice_id="narrator")
        image_agent = ScriptImageRetrievalAgent(
            ScriptImageConfig(output_dir=tmp_run_dir, min_candidates_per_segment=1)
        )

        with patch("video_agent.audio_agent.generate_voiceover", side_effect=TTSError("fail")):
            audio_agent.generate_audio_timeline(sample_video_plan)

        with patch("video_agent.script_image_agent.search_pexels_images", return_value=[]):
            with patch("video_agent.script_image_agent.search_wikimedia_images", return_value=[]):
                image_agent.generate_script_image_manifest(
                    sample_script_package, run_id="vp_test_001"
                )

        report = json.loads((tmp_run_dir / "production_report.json").read_text())
        agents = {i["agent"] for i in report["issues"]}
        assert "AudioAgent" in agents
        assert "ScriptImageAgent" in agents
        assert report["degraded_scene_count"] == len(report["issues"])


# ---------------------------------------------------------------------------
# Orchestrator revision loop tests
# ---------------------------------------------------------------------------

class TestOrchestratorRevisionLoop:
    def _make_audio_timeline(self, scene_ids=("scene_01", "scene_02")) -> Dict[str, Any]:
        tracks = []
        t = 0.0
        for sid in scene_ids:
            tracks.append({
                "type": "voiceover",
                "scene_id": sid,
                "t_start_s": t,
                "t_end_s": t + 5.0,
                "file": f"audio_segments/vo_{sid}.mp3",
                "volume_db": 0,
                "metadata": {},
            })
            t += 5.0
        return {"schema_version": "1.0.0", "tracks": tracks, "duration_seconds": t}

    def _make_image_manifest(self) -> Dict[str, Any]:
        return {"schema_version": "1.0.0", "segments": [], "total_segments": 0}

    def test_no_degraded_scenes_exits_immediately(
        self, tmp_run_dir, sample_screenplay, sample_script_package, sample_video_plan
    ):
        """When production_report has no degraded issues, orchestrator exits after round 0."""
        orch = ProductionOrchestrator()
        mock_screenplay_agent = MagicMock()

        audio_timeline = self._make_audio_timeline()
        image_manifest = self._make_image_manifest()

        with patch("video_agent.orchestrator._produce_parallel") as mock_parallel:
            import asyncio as _asyncio

            async def _ok(*a, **kw):
                return audio_timeline, image_manifest, {}

            mock_parallel.side_effect = _ok

            result_timeline, result_sp, result_vp = orch.run(
                screenplay=sample_screenplay,
                script_package=sample_script_package,
                video_plan=sample_video_plan,
                run_dir=tmp_run_dir,
                screenplay_agent=mock_screenplay_agent,
                voice="silent",
            )

        # revise_scene should not have been called
        mock_screenplay_agent.revise_scene.assert_not_called()

        # scene_results.json must exist
        assert (tmp_run_dir / "scene_results.json").exists()

    def test_degraded_scene_triggers_revision(
        self, tmp_run_dir, sample_screenplay, sample_script_package, sample_video_plan
    ):
        """A degraded scene in the production_report triggers screenplay revision + re-run."""
        orch = ProductionOrchestrator()

        # screenplay_agent.revise_scene returns the same screenplay unchanged (for simplicity)
        mock_screenplay_agent = MagicMock()
        mock_screenplay_agent.revise_scene.return_value = sample_screenplay

        audio_timeline = self._make_audio_timeline()
        image_manifest = self._make_image_manifest()

        call_count = {"n": 0}

        async def _parallel_side_effect(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # After round 0, inject a degraded issue
                from video_agent.artifacts.io import write_json
                write_json(tmp_run_dir / "production_report.json", {
                    "schema_version": "1.0.0",
                    "run_id": "vp_test_001",
                    "issues": [{
                        "agent": "AudioAgent",
                        "scene_id": "scene_01",
                        "status": "degraded",
                        "issue": "tts_failed",
                        "detail": "API down",
                        "suggestion": "Simplify vo_line",
                        "revision_field": "vo_line",
                        "revision_possible": True,
                    }],
                    "degraded_scene_count": 1,
                })
            return audio_timeline, image_manifest, {}

        with patch("video_agent.orchestrator._produce_parallel", side_effect=_parallel_side_effect):
            result_timeline, result_sp, result_vp = orch.run(
                screenplay=sample_screenplay,
                script_package=sample_script_package,
                video_plan=sample_video_plan,
                run_dir=tmp_run_dir,
                screenplay_agent=mock_screenplay_agent,
                voice="silent",
            )

        # revise_scene must have been called for scene_01
        mock_screenplay_agent.revise_scene.assert_called_once()
        call_args = mock_screenplay_agent.revise_scene.call_args
        assert call_args[0][1] == "scene_01"  # second positional arg is scene_id

        # At least 2 parallel passes: round 0 + 1 revision
        assert call_count["n"] >= 2

    def test_scene_results_json_written(
        self, tmp_run_dir, sample_screenplay, sample_script_package, sample_video_plan
    ):
        """scene_results.json is always written after the orchestrator completes."""
        orch = ProductionOrchestrator()
        audio_timeline = self._make_audio_timeline()
        image_manifest = self._make_image_manifest()

        async def _ok(*a, **kw):
            return audio_timeline, image_manifest, {}

        with patch("video_agent.orchestrator._produce_parallel", side_effect=_ok):
            orch.run(
                screenplay=sample_screenplay,
                script_package=sample_script_package,
                video_plan=sample_video_plan,
                run_dir=tmp_run_dir,
                screenplay_agent=MagicMock(),
                voice="silent",
            )

        results_path = tmp_run_dir / "scene_results.json"
        assert results_path.exists()
        data = json.loads(results_path.read_text())
        assert data["schema_version"] == "1.0.0"
        assert isinstance(data["scenes"], list)
        assert len(data["scenes"]) == 2
        scene_ids = {s["scene_id"] for s in data["scenes"]}
        assert scene_ids == {"scene_01", "scene_02"}


# ---------------------------------------------------------------------------
# scene_id propagation tests
# ---------------------------------------------------------------------------

class TestSceneIdPropagation:
    def test_screenplay_to_script_package_preserves_scene_id(self):
        from video_agent.artifacts.screenplay import screenplay_to_script_package

        sp = {
            "screenplay_id": "sp_x",
            "format": "facts",
            "target_duration_s": 10,
            "narrator_character": {"voice_preset": "narrator"},
            "music_tone": "upbeat",
            "scenes": [
                {
                    "scene_id": "scene_01",
                    "vo_line": "Line one.",
                    "on_screen_text": "One",
                    "target_duration_s": 5,
                    "visual": {},
                },
            ],
        }
        pkg = screenplay_to_script_package(sp)
        beats = pkg["script"]["beats"]
        assert beats[0]["scene_id"] == "scene_01"

    def test_screenplay_to_script_package_propagates_generation_prompts(self):
        from video_agent.artifacts.screenplay import screenplay_to_script_package

        sp = {
            "screenplay_id": "sp_gp",
            "format": "facts",
            "target_duration_s": 10,
            "narrator_character": {"voice_preset": "narrator"},
            "music_tone": "upbeat",
            "scenes": [
                {
                    "scene_id": "scene_01",
                    "vo_line": "A tank rolls forward.",
                    "on_screen_text": "Tank",
                    "target_duration_s": 5,
                    "visual": {
                        "description": "Sherman tank on a bridge",
                        "mood": "tense",
                        "search_queries": ["Sherman tank bridge", "WW2 tank", "military tank"],
                        "generation_prompts": {
                            "precise": "Sherman M4 tank crossing bridge, WW2, photorealistic",
                            "general": "Sherman tank WW2 photorealistic",
                        },
                    },
                },
                {
                    "scene_id": "scene_02",
                    "vo_line": "Soldiers advance.",
                    "on_screen_text": "Advance",
                    "target_duration_s": 5,
                    "visual": {
                        "description": "soldiers in a field",
                        "mood": "intense",
                        "search_queries": ["soldiers field", "WW2 soldiers", "battlefield"],
                    },
                },
            ],
        }
        pkg = screenplay_to_script_package(sp)
        beats = pkg["script"]["beats"]
        assert beats[0]["generation_prompts"] == {
            "precise": "Sherman M4 tank crossing bridge, WW2, photorealistic",
            "general": "Sherman tank WW2 photorealistic",
        }
        assert beats[1]["generation_prompts"] == {}

    def test_video_planner_preserves_scene_id_from_beat(self):
        from video_agent.video_planner import script_package_to_video_plan

        pkg = {
            "script_package_id": "sg_test",
            "topic_id": "t",
            "subtopic_id": "s",
            "script": {
                "beats": [
                    {
                        "scene_id": "scene_01",
                        "t_start_s": 0.0,
                        "t_end_s": 5.0,
                        "vo_line": "Hello.",
                        "on_screen_text": "Hello",
                    }
                ]
            },
        }
        vp = script_package_to_video_plan(pkg)
        assert vp["scenes"][0]["scene_id"] == "scene_01"
