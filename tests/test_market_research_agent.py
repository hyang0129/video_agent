"""Tests for market research agent (src/agent.py).

Run with: pytest tests/test_market_research_agent.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from src.agent import MarketResearchAgent


class TestAgentCreation:
    @patch("src.agent.make_llm")
    @patch("src.agent.create_tool_calling_agent")
    @patch("src.agent.AgentExecutor")
    def test_agent_creation(self, mock_executor_cls, mock_create_agent, mock_make_llm):
        mock_make_llm.return_value = MagicMock()
        mock_create_agent.return_value = MagicMock()
        mock_executor_cls.return_value = MagicMock()
        agent = MarketResearchAgent()
        assert agent.llm is not None
        assert len(agent.tools) == 5
        mock_make_llm.assert_called_once()


class TestResearchCategory:
    @patch("src.agent.make_llm")
    @patch("src.agent.create_tool_calling_agent")
    @patch("src.agent.AgentExecutor")
    def test_research_category_calls_executor(self, mock_executor_cls, mock_create_agent, mock_make_llm):
        mock_make_llm.return_value = MagicMock()
        mock_create_agent.return_value = MagicMock()
        mock_executor = MagicMock()
        mock_executor.invoke.return_value = {"output": "test results"}
        mock_executor_cls.return_value = mock_executor
        agent = MarketResearchAgent()
        result = agent.research_category("science")
        assert result == "test results"
        mock_executor.invoke.assert_called_once()


class TestAgentTools:
    @patch("src.agent.make_llm")
    @patch("src.agent.create_tool_calling_agent")
    @patch("src.agent.AgentExecutor")
    def test_agent_has_expected_tools(self, mock_executor_cls, mock_create_agent, mock_make_llm):
        mock_make_llm.return_value = MagicMock()
        mock_create_agent.return_value = MagicMock()
        mock_executor_cls.return_value = MagicMock()
        agent = MarketResearchAgent()
        tool_names = [t.name for t in agent.tools]
        assert "search_longform_content" in tool_names
        assert "search_shortform_content" in tool_names
        assert "fetch_videos_corpus" in tool_names
        assert "analyze_channel" in tool_names
        assert "compare_content_gap" in tool_names
