"""Tests for music_agent module.

Run with: pytest tests/test_music_agent.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.music_agent import MusicAgent, MusicAgentError, create_music_agent, _probe_duration_seconds


class TestSelectMusicBasic:
    @patch("src.music_agent.shutil.which", return_value="/usr/bin/ffprobe")
    @patch("src.music_agent.subprocess.run")
    def test_select_music_basic(self, mock_run, mock_which, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="45.0\n")
        music_file = tmp_path / "test.mp3"
        music_file.write_bytes(b"\x00" * 100)
        agent = MusicAgent(default_music_path=music_file)
        result = agent.select_music({"duration_seconds": 45.0})
        assert result["schema_version"] == "1.0.0"
        assert result["selection_method"] == "default"
        assert result["target_duration_s"] == 45.0
        assert result["source_duration_s"] == 45.0
        assert result["loop"] is True


class TestSelectMusicMissingFile:
    def test_raises_on_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.mp3"
        agent = MusicAgent(default_music_path=missing)
        with pytest.raises(MusicAgentError, match="not found"):
            agent.select_music({"duration_seconds": 30.0})


class TestSelectByTone:
    @patch("src.music_agent.shutil.which", return_value="/usr/bin/ffprobe")
    @patch("src.music_agent.subprocess.run")
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


class TestCreateMusicAgentFactory:
    def test_returns_music_agent_instance(self):
        agent = create_music_agent(default_music_path=Path("/tmp/fake.mp3"))
        assert isinstance(agent, MusicAgent)


class TestProbeDuration:
    @patch("src.music_agent.shutil.which", return_value=None)
    def test_probe_duration_no_ffprobe(self, mock_which, tmp_path):
        music_file = tmp_path / "test.mp3"
        music_file.write_bytes(b"\x00" * 100)
        result = _probe_duration_seconds(music_file)
        assert result is None
