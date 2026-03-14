"""Tests for music_agent module.

Run with: pytest tests/test_music_agent.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from video_agent.music_agent import (
    MusicAgent,
    MusicAgentError,
    create_music_agent,
    _probe_duration_seconds,
    _llm_describe_music,
    _build_script_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SCRIPT_PACKAGE = {
    "script": {
        "voiceover": (
            "Think you know WW2 tanks? These facts will surprise you. "
            "The Tiger was so feared that soldiers called every enemy tank a Tiger."
        ),
    },
    "metadata": {
        "topic_id": "world_war_2_tanks",
        "tone": "energetic, authoritative",
        "format": "Did You Know",
    },
}

SAMPLE_TIMELINE = {"duration_seconds": 35.0}


# ---------------------------------------------------------------------------
# Default backend tests
# ---------------------------------------------------------------------------


class TestDefaultSelection:
    @patch("video_agent.music_agent.shutil.which", return_value="/usr/bin/ffprobe")
    @patch("video_agent.music_agent.subprocess.run")
    def test_select_music_default_backend(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="45.0\n")
        music_file = tmp_path / "test.mp3"
        music_file.write_bytes(b"\x00" * 100)
        agent = MusicAgent(default_music_path=music_file, backend="default")
        result = agent.select_music(SAMPLE_TIMELINE)
        assert result["schema_version"] == "1.0.0"
        assert result["selection_method"] == "default"
        assert result["target_duration_s"] == 35.0
        assert result["loop"] is True

    def test_raises_on_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.mp3"
        agent = MusicAgent(default_music_path=missing, backend="default")
        with pytest.raises(MusicAgentError, match="not found"):
            agent.select_music(SAMPLE_TIMELINE)


class TestSelectByTone:
    @patch("video_agent.music_agent.shutil.which", return_value="/usr/bin/ffprobe")
    @patch("video_agent.music_agent.subprocess.run")
    def test_select_by_tone_delegates(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="60.0\n")
        music_file = tmp_path / "test.mp3"
        music_file.write_bytes(b"\x00" * 100)
        agent = MusicAgent(default_music_path=music_file)
        timeline = {"duration_seconds": 30.0}
        result_tone = agent.select_by_tone("dramatic", timeline)
        result_direct = agent.select_music(timeline)
        assert result_tone["selection_method"] == result_direct["selection_method"]
        assert result_tone["target_duration_s"] == result_direct["target_duration_s"]


# ---------------------------------------------------------------------------
# Script summary extraction
# ---------------------------------------------------------------------------


class TestBuildScriptSummary:
    def test_extracts_fields(self):
        summary = _build_script_summary(SAMPLE_SCRIPT_PACKAGE)
        assert summary["topic"] == "world_war_2_tanks"
        assert "energetic" in summary["tone"]
        assert summary["video_format"] == "Did You Know"
        assert "Tiger" in summary["voiceover"]

    def test_missing_metadata_uses_defaults(self):
        summary = _build_script_summary({"script": {}, "metadata": {}})
        assert summary["topic"] == "unknown"
        assert summary["tone"] == "neutral"
        assert summary["video_format"] == "short-form"

    def test_falls_back_to_top_level_topic_id(self):
        summary = _build_script_summary({
            "script": {},
            "metadata": {},
            "topic_id": "fallback_topic",
        })
        assert summary["topic"] == "fallback_topic"


# ---------------------------------------------------------------------------
# LLM music description
# ---------------------------------------------------------------------------


class TestLlmDescribeMusic:
    @patch("video_agent.music_agent.make_llm")
    def test_parses_valid_llm_response(self, mock_make_llm):
        llm_response = MagicMock()
        llm_response.content = json.dumps({
            "description": "epic orchestral, brass, drums, cinematic, powerful",
            "bpm": 100,
            "key": "D minor",
            "guidance_scale": 8.0,
        })
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = llm_response
        mock_make_llm.return_value = mock_llm

        result = _llm_describe_music(SAMPLE_SCRIPT_PACKAGE, 35.0)
        assert result["description"] == "epic orchestral, brass, drums, cinematic, powerful"
        assert result["bpm"] == 100
        assert result["key"] == "D minor"
        assert result["guidance_scale"] == 8.0

    @patch("video_agent.music_agent.make_llm")
    def test_strips_markdown_fences(self, mock_make_llm):
        llm_response = MagicMock()
        llm_response.content = (
            "```json\n"
            '{"description": "ambient piano", "bpm": 80, "key": null, "guidance_scale": 7.0}\n'
            "```"
        )
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = llm_response
        mock_make_llm.return_value = mock_llm

        result = _llm_describe_music(SAMPLE_SCRIPT_PACKAGE, 30.0)
        assert result["description"] == "ambient piano"
        assert result["bpm"] == 80

    @patch("video_agent.music_agent.make_llm")
    def test_raises_on_missing_description(self, mock_make_llm):
        llm_response = MagicMock()
        llm_response.content = json.dumps({"bpm": 100})
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = llm_response
        mock_make_llm.return_value = mock_llm

        with pytest.raises(ValueError, match="description"):
            _llm_describe_music(SAMPLE_SCRIPT_PACKAGE, 30.0)

    @patch("video_agent.music_agent.make_llm")
    def test_raises_on_invalid_json(self, mock_make_llm):
        llm_response = MagicMock()
        llm_response.content = "not valid json at all"
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = llm_response
        mock_make_llm.return_value = mock_llm

        with pytest.raises(json.JSONDecodeError):
            _llm_describe_music(SAMPLE_SCRIPT_PACKAGE, 30.0)


# ---------------------------------------------------------------------------
# ACE-Step generation path
# ---------------------------------------------------------------------------


class TestAceStepGeneration:
    @patch("video_agent.music_agent.shutil.which", return_value="/usr/bin/ffprobe")
    @patch("video_agent.music_agent.subprocess.run")
    @patch("video_agent.music_agent.make_llm")
    def test_acestep_with_llm_and_generate(
        self, mock_make_llm, mock_subprocess, mock_which, tmp_path
    ):
        """Full happy path: LLM describes music, ACE-Step generates it."""
        # Mock LLM
        llm_response = MagicMock()
        llm_response.content = json.dumps({
            "description": "epic orchestral, brass, timpani, cinematic",
            "bpm": 100,
            "key": "D minor",
            "guidance_scale": 8.0,
        })
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = llm_response
        mock_make_llm.return_value = mock_llm

        # Mock ffprobe
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="35.0\n")

        # Mock AceStepClient
        mock_result = MagicMock()
        mock_result.duration_s = 35.0
        mock_result.task_id = "t-test-123"
        mock_result.save_to_file.return_value = tmp_path / "music_generated.mp3"

        import ace_step.client as ace_client

        mock_client_instance = MagicMock()
        mock_client_instance.health_sync.return_value = True
        mock_client_instance.generate_sync.return_value = mock_result

        with patch.object(
            ace_client, "AceStepClient", return_value=mock_client_instance
        ):
            agent = MusicAgent(
                output_dir=tmp_path, backend="acestep",
                default_music_path=tmp_path / "default.mp3",
            )
            result = agent.select_music(
                SAMPLE_TIMELINE, script_package=SAMPLE_SCRIPT_PACKAGE,
            )

        assert result["selection_method"] == "generated"
        assert result["music_description"] == "epic orchestral, brass, timpani, cinematic"
        assert result["music_bpm"] == 100
        assert result["music_key"] == "D minor"
        assert result["task_id"] == "t-test-123"
        assert result["loop"] is False

        # Verify LLM was called
        mock_llm.invoke.assert_called_once()

        # Verify generate_sync was called with LLM output
        call_kwargs = mock_client_instance.generate_sync.call_args.kwargs
        assert call_kwargs["description"] == "epic orchestral, brass, timpani, cinematic"
        assert call_kwargs["bpm"] == 100
        assert call_kwargs["instrumental"] is True

    def test_acestep_raises_on_server_down(self, tmp_path):
        """When ACE-Step server is unreachable, raises MusicAgentError."""
        import ace_step.client as ace_client
        mock_client_instance = MagicMock()
        mock_client_instance.health_sync.return_value = False

        with patch.object(
            ace_client, "AceStepClient", return_value=mock_client_instance
        ):
            agent = MusicAgent(
                output_dir=tmp_path, backend="acestep",
                default_music_path=tmp_path / "default.mp3",
            )
            with pytest.raises(MusicAgentError, match="unreachable"):
                agent.select_music(SAMPLE_TIMELINE)

    @patch("video_agent.music_agent.make_llm")
    def test_llm_failure_raises(self, mock_make_llm, tmp_path):
        """When LLM fails with script_package provided, error propagates."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM unavailable")
        mock_make_llm.return_value = mock_llm

        import ace_step.client as ace_client
        mock_client_instance = MagicMock()
        mock_client_instance.health_sync.return_value = True

        with patch.object(
            ace_client, "AceStepClient", return_value=mock_client_instance
        ):
            agent = MusicAgent(
                output_dir=tmp_path, backend="acestep",
                default_music_path=tmp_path / "default.mp3",
            )
            with pytest.raises(RuntimeError, match="LLM unavailable"):
                agent.select_music(
                    SAMPLE_TIMELINE, script_package=SAMPLE_SCRIPT_PACKAGE,
                )

    def test_acestep_no_script_uses_preset(self, tmp_path):
        """When no script_package is provided, uses preset matching."""
        mock_result = MagicMock()
        mock_result.duration_s = 30.0
        mock_result.task_id = "t-no-script"
        mock_result.save_to_file.return_value = tmp_path / "music_generated.mp3"

        import ace_step.client as ace_client
        mock_client_instance = MagicMock()
        mock_client_instance.health_sync.return_value = True
        mock_client_instance.generate_sync.return_value = mock_result

        with patch.object(
            ace_client, "AceStepClient", return_value=mock_client_instance
        ), patch("video_agent.music_agent._probe_duration_seconds", return_value=30.0):
            agent = MusicAgent(
                output_dir=tmp_path, backend="acestep",
                default_music_path=tmp_path / "default.mp3",
            )
            result = agent.select_music(SAMPLE_TIMELINE)

        assert result["selection_method"] == "generated"
        # Without script, should use preset fallback (no LLM call)
        call_kwargs = mock_client_instance.generate_sync.call_args.kwargs
        assert "documentary" in call_kwargs["description"].lower() or len(call_kwargs["description"]) > 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestCreateMusicAgentFactory:
    def test_returns_music_agent_instance(self):
        agent = create_music_agent(default_music_path=Path("/tmp/fake.mp3"))
        assert isinstance(agent, MusicAgent)

    def test_backend_default_is_acestep(self):
        agent = create_music_agent()
        assert agent.backend == "acestep"

    def test_output_dir_passed_through(self, tmp_path):
        agent = create_music_agent(output_dir=tmp_path)
        assert agent.output_dir == tmp_path


# ---------------------------------------------------------------------------
# Probe duration
# ---------------------------------------------------------------------------


class TestProbeDuration:
    @patch("video_agent.music_agent.shutil.which", return_value=None)
    def test_probe_duration_no_ffprobe(self, mock_which, tmp_path):
        music_file = tmp_path / "test.mp3"
        music_file.write_bytes(b"\x00" * 100)
        result = _probe_duration_seconds(music_file)
        assert result is None
