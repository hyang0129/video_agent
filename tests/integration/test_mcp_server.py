"""Integration tests for MCP server modules.

These tests do NOT start the MCP stdio server as a subprocess.
Instead they import the server modules directly and exercise tool logic
using the same call_tool dispatcher that the server would use.

No ElevenLabs or Pexels API keys required for the lightweight tools.
Heavy tools (generate_audio, fetch_assets, render_video) are skipped unless
the relevant environment variables are set.

Run with:
    pytest tests/integration/test_mcp_server.py -v
"""

from __future__ import annotations

import json
import os
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(result) -> dict:
    """Extract dict from list[TextContent] returned by call_tool."""
    text = result[0].text
    return json.loads(text)


# ---------------------------------------------------------------------------
# Producer server — lightweight tools
# ---------------------------------------------------------------------------

class TestProducerServerLightweightTools:
    """Tests that require no external API keys."""

    @pytest.mark.asyncio
    async def test_estimate_tts_duration_narrator(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("estimate_tts_duration", {
            "text": "Hello world. This is a test sentence for TTS duration estimation.",
            "voice_preset": "narrator",
        })
        data = _parse(result)
        word_count = data["word_count"]
        assert word_count > 0
        assert data["wpm_used"] == 150
        assert data["confidence"] == "heuristic"
        assert data["estimated_duration_s"] == pytest.approx(word_count / 150 * 60, abs=0.01)

    @pytest.mark.asyncio
    async def test_estimate_tts_duration_calm_preset(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("estimate_tts_duration", {
            "text": "calm voice test",
            "voice_preset": "calm",
        })
        data = _parse(result)
        assert data["wpm_used"] == 130
        assert data["voice_preset"] == "calm"

    @pytest.mark.asyncio
    async def test_estimate_tts_duration_unknown_preset_fallback(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("estimate_tts_duration", {
            "text": "test",
            "voice_preset": "unknown_preset",
        })
        data = _parse(result)
        assert data["wpm_used"] == 150  # falls back to narrator WPM

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("does_not_exist", {})
        data = _parse(result)
        assert "error" in data

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.environ.get("PEXELS_API_KEY"),
        reason="PEXELS_API_KEY not set",
    )
    async def test_check_asset_availability_live(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("check_asset_availability", {
            "query": "World War II tank battlefield",
            "n_results": 3,
        })
        data = _parse(result)
        assert "result_count" in data
        assert data["availability"] in {"good", "marginal", "poor"}
        assert data["recommendation"] in {"ok", "rephrase", "reject"}
        assert isinstance(data["top_results"], list)

    @pytest.mark.asyncio
    async def test_check_asset_availability_no_pexels_key(self, monkeypatch):
        """When PEXELS_API_KEY is empty, returns unknown availability."""
        monkeypatch.setattr("video_agent.config.PEXELS_API_KEY", "")
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("check_asset_availability", {"query": "test query"})
        data = _parse(result)
        # Should return error dict, not crash
        assert "error" in data or "availability" in data


# ---------------------------------------------------------------------------
# Producer server — list_tools
# ---------------------------------------------------------------------------

class TestVideoAgentServerListTools:
    @pytest.mark.asyncio
    async def test_list_tools_returns_all_tools(self):
        from video_agent.mcp.video_agent_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {
            "check_asset_availability",
            "estimate_tts_duration",
            "generate_audio",
            "fetch_assets",
            "render_video",
            "validate_output",
            "generate_concepts",
            "write_screenplay",
            "review_feasibility",
            "revise_scene",
            "research_topic",
            "mine_facts",
            "generate_script",
            "create_video_plan",
            "select_music",
        }

    @pytest.mark.asyncio
    async def test_all_tools_have_required_inputschema(self):
        from video_agent.mcp.video_agent_server import list_tools

        tools = await list_tools()
        for tool in tools:
            assert tool.inputSchema is not None, f"{tool.name} missing inputSchema"
            assert tool.inputSchema.get("type") == "object"


# ---------------------------------------------------------------------------
# Screenwriting server — review_feasibility (no API key)
# ---------------------------------------------------------------------------

class TestScreenwritingServerReviewFeasibility:
    @pytest.mark.asyncio
    async def test_review_valid_screenplay(self):
        from video_agent.mcp.video_agent_server import call_tool

        screenplay = {
            "screenplay_id": "sp_test",
            "target_duration_s": 10,
            "scenes": [
                {
                    "scene_id": "scene_01",
                    "vo_line": "Hello world.",
                    "on_screen_text": "Hello",
                    "target_duration_s": 5,
                    "visual": {"description": "A close-up of a spinning globe"},
                },
                {
                    "scene_id": "scene_02",
                    "vo_line": "This is scene two.",
                    "on_screen_text": "Scene Two",
                    "target_duration_s": 5,
                    "visual": {"description": "An astronaut floating in space"},
                },
            ],
        }
        result = await call_tool("review_feasibility", {"screenplay": screenplay})
        data = _parse(result)
        assert data["status"] == "ok"
        report = data["feasibility_report"]
        assert report["overall_score"] > 0.0
        assert report["recommended_action"] in {"approve", "revise_scenes", "reject"}

    @pytest.mark.asyncio
    async def test_review_empty_screenplay(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("review_feasibility", {"screenplay": {"scenes": []}})
        data = _parse(result)
        assert data["status"] == "ok"
        assert data["feasibility_report"]["recommended_action"] == "reject"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from video_agent.mcp.video_agent_server import call_tool

        result = await call_tool("nonexistent_tool", {})
        data = _parse(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# Shared utility unit tests
# ---------------------------------------------------------------------------

class TestTtsUtils:
    def test_estimate_duration_narrator(self):
        from video_agent.utils.tts_utils import estimate_duration_s
        dur = estimate_duration_s("word " * 150, "narrator")
        assert pytest.approx(dur, abs=0.1) == 60.0  # 150 words at 150 WPM = 60s

    def test_estimate_duration_calm_slower(self):
        from video_agent.utils.tts_utils import estimate_duration_s
        calm = estimate_duration_s("test sentence", "calm")
        narrator = estimate_duration_s("test sentence", "narrator")
        assert calm > narrator  # calm is slower (130 WPM vs 150 WPM)

    def test_wpm_table_has_all_presets(self):
        from video_agent.utils.tts_utils import _WPM_BY_PRESET
        assert set(_WPM_BY_PRESET) >= {"calm", "narrator", "energetic", "authoritative"}


class TestFfprobeUtils:
    def test_probe_missing_file_returns_empty(self, tmp_path):
        from video_agent.utils.ffprobe_utils import probe_video_info
        result = probe_video_info(tmp_path / "nonexistent.mp4")
        assert result["has_video"] is False
        assert result["has_audio"] is False

    def test_validate_video_missing_file_returns_false(self, tmp_path):
        from video_agent.utils.ffprobe_utils import validate_video
        assert validate_video(tmp_path / "nonexistent.mp4") is False


class TestScoreCandidateRelevance:
    def test_exact_match(self):
        from video_agent.tools.image_search_tools import score_candidate_relevance
        candidate = {"metadata": {"alt": "World War II tank battlefield Germany"}}
        score = score_candidate_relevance(candidate, "World War II tank")
        assert score > 0.5

    def test_no_overlap(self):
        from video_agent.tools.image_search_tools import score_candidate_relevance
        candidate = {"metadata": {"alt": "sunset beach ocean waves"}}
        score = score_candidate_relevance(candidate, "tank warfare military")
        assert score == 0.0

    def test_missing_alt_returns_zero(self):
        from video_agent.tools.image_search_tools import score_candidate_relevance
        candidate = {"metadata": {}}
        assert score_candidate_relevance(candidate, "tank") == 0.0
