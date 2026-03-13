"""Unit tests for the 5 new MCP tools (1.0a): research_topic, mine_facts,
generate_script, create_video_plan, select_music.

Each test calls the tool handler in-process via call_tool() -- no server needed.
Heavy agents (YouTube API, LLM) are mocked; deterministic tools run unmocked.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from src.mcp.video_agent_server import call_tool

_FIXTURES = Path(__file__).parent / "fixtures"


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _call(name: str, arguments: dict) -> Dict[str, Any]:
    """Call an MCP tool and return the parsed JSON result."""
    result = _run(call_tool(name, arguments))
    assert result, f"Tool {name} returned empty result"
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# Tool 11: research_topic
# ---------------------------------------------------------------------------

class TestResearchTopic:
    @patch("src.mcp.video_agent_server.call_tool.__module__", new="test")
    def test_research_topic_returns_topic_brief(self, tmp_path: Path):
        brief = {"topic_id": "cheese", "title": "Cheese Facts", "score": 0.9}
        brief_path = tmp_path / "topic_brief_0.json"
        brief_path.write_text(json.dumps(brief), encoding="utf-8")

        mock_agent = MagicMock()
        mock_agent.research_category_artifacts.return_value = {
            "run_id": "mr_test_123",
            "topic_brief_paths": [str(brief_path)],
            "report_path": str(tmp_path / "report.json"),
        }

        with patch("src.agent.create_agent", return_value=mock_agent):
            result = _call("research_topic", {"setting": "cheese facts"})

        assert result["status"] == "ok"
        assert result["run_id"] == "mr_test_123"
        assert result["topic_brief"]["topic_id"] == "cheese"
        assert result["topic_brief_count"] == 1
        assert "elapsed_seconds" in result

    def test_research_topic_no_results(self):
        mock_agent = MagicMock()
        mock_agent.research_category_artifacts.return_value = {
            "run_id": "mr_empty",
            "topic_brief_paths": [],
            "report_path": "",
        }

        with patch("src.agent.create_agent", return_value=mock_agent):
            result = _call("research_topic", {"setting": "nonexistent"})

        assert result["status"] == "no_results"
        assert result["topic_brief"] is None


# ---------------------------------------------------------------------------
# Tool 12: mine_facts
# ---------------------------------------------------------------------------

class TestMineFacts:
    def test_mine_facts_returns_stats(self):
        mock_miner = MagicMock()
        mock_miner.mine_top_videos.return_value = {
            "total_facts": 42,
            "videos_found": 5,
            "videos_mined": 4,
        }

        with patch("src.facts.fact_miner.FactMiner", return_value=mock_miner):
            result = _call("mine_facts", {
                "topic_query": "cheese facts",
                "topic_id": "cheese",
                "subtopic_id": "history",
                "max_videos": 5,
            })

        assert result["status"] == "ok"
        assert result["total_facts"] == 42
        assert result["videos_mined"] == 4
        assert "elapsed_seconds" in result

        mock_miner.mine_top_videos.assert_called_once_with(
            topic_query="cheese facts",
            topic_id="cheese",
            subtopic_id="history",
            max_videos=5,
            use_captions=True,
        )


# ---------------------------------------------------------------------------
# Tool 13: generate_script
# ---------------------------------------------------------------------------

class TestGenerateScript:
    def test_generate_script_returns_package(self):
        topic_brief = json.loads(
            (_FIXTURES / "topic_brief_ww2_tanks.json").read_text(encoding="utf-8")
        )
        fake_package = {"script": {"beats": [{"id": "b1"}]}, "metadata": {}}

        mock_agent = MagicMock()
        mock_agent.generate_script_package.return_value = fake_package

        with patch("src.script_agent.create_script_agent", return_value=mock_agent):
            result = _call("generate_script", {"topic_brief": topic_brief})

        assert result["status"] == "ok"
        assert result["script_package"]["script"]["beats"][0]["id"] == "b1"
        assert "elapsed_seconds" in result


# ---------------------------------------------------------------------------
# Tool 14: create_video_plan (deterministic -- no mocking needed)
# ---------------------------------------------------------------------------

class TestCreateVideoPlan:
    def test_create_video_plan_from_fixture(self):
        script_package = json.loads(
            (_FIXTURES / "script_package_ww2_tanks.json").read_text(encoding="utf-8")
        )
        result = _call("create_video_plan", {"script_package": script_package})

        assert result["status"] == "ok"
        assert "video_plan" in result
        vp = result["video_plan"]
        assert vp.get("scenes") or vp.get("segments") or vp.get("beats")
        assert "elapsed_seconds" in result

    def test_create_video_plan_with_creative_spec(self):
        script_package = json.loads(
            (_FIXTURES / "script_package_ww2_tanks.json").read_text(encoding="utf-8")
        )
        result = _call("create_video_plan", {
            "script_package": script_package,
            "creative_spec": {"style": {"subtitle_style": "bold, white"}},
        })
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Tool 15: select_music
# ---------------------------------------------------------------------------

class TestSelectMusic:
    def test_select_music_returns_selection(self, tmp_path: Path):
        music_file = tmp_path / "test_music.mp3"
        # Write a minimal file so MusicAgent doesn't raise
        music_file.write_bytes(b"\x00" * 100)

        audio_timeline = {"duration_seconds": 45.0, "tracks": []}

        with patch("src.music_agent.DEFAULT_MUSIC_PATH", music_file):
            result = _call("select_music", {"audio_timeline": audio_timeline})

        assert result["status"] == "ok"
        assert "music_selection" in result
        ms = result["music_selection"]
        assert ms["target_duration_s"] == 45.0
        assert "elapsed_seconds" in result

    def test_select_music_missing_file_returns_error(self):
        audio_timeline = {"duration_seconds": 30.0, "tracks": []}

        with patch("src.music_agent.DEFAULT_MUSIC_PATH", Path("/nonexistent/music.mp3")):
            result = _call("select_music", {"audio_timeline": audio_timeline})

        # Should return error (MusicAgentError caught by top-level handler)
        assert "error" in result
