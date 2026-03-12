# Deprecated Tests

These tests were moved here as part of the test standardization effort (March 2026).

## Why deprecated

The project standardized on two test tiers:

1. **Unit tests** (`tests/test_*.py`) -- one per agent, mocked, fast, offline
2. **Full-pipeline E2E** (`tests/test_mcp_server_full_pipeline.py`) -- MCP server integration, outputs video for human review

These files were superseded by that structure:

| File | Reason |
|------|--------|
| `test_screenwriting_full_pipeline.py` | Full pipeline without MCP -- replaced by MCP server E2E |
| `test_settings_pipeline.py` | Multi-setting pipeline without MCP -- replaced by MCP server E2E |
| `test_star_wars_full_pipeline_integration.py` | Full pipeline without MCP -- replaced by MCP server E2E |
| `test_mcp_serverless_full_pipeline.py` | MCP in-process (no server) -- replaced by MCP server E2E |
| `test_audio_generation_demo.py` | Overlaps with `test_audio_agent.py` unit tests |
| `test_audio_generation_integration.py` | Overlaps with `test_audio_agent.py` unit tests |

## Can I delete these?

Yes, once the new unit tests and MCP server E2E test cover the same scenarios, these can be safely deleted.
