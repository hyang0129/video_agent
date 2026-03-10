"""MCP Screenwriting Server — exposes screenplay generation tools over stdio transport.

Tools exposed:
  1. generate_concepts    — generate N concept variants from a TopicBrief
  2. write_screenplay     — write a Screenplay from a Concept
  3. review_feasibility   — heuristic pre-flight validation (no API call)
  4. revise_scene         — revise one scene given a structured issue

Run as:
    venv/Scripts/python.exe -m src.mcp.screenwriting_server
"""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any, List

import mcp.server.stdio
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

from ..screenwriting.concept_agent import ConceptAgent
from ..screenwriting.screenplay_agent import ScreenplayAgent
from ..screenwriting.screenplay_reviewer import ScreenplayReviewer

app = Server("screenwriting-server")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="generate_concepts",
            description="Generate N concept variants from a TopicBrief. Returns list of Concept dicts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_brief": {"type": "object", "description": "TopicBrief dict"},
                    "n_concepts": {"type": "integer", "default": 3, "description": "Number of concept variants"},
                    "creative_spec": {"type": "object", "description": "Optional CreativeSpec dict"},
                },
                "required": ["topic_brief"],
            },
        ),
        Tool(
            name="write_screenplay",
            description="Write a Screenplay from a Concept dict. Returns a Screenplay dict.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept": {"type": "object", "description": "Concept dict"},
                    "creative_spec": {"type": "object", "description": "Optional CreativeSpec dict"},
                    "format": {
                        "type": "string",
                        "enum": ["facts", "storytime", "tutorial", "debate"],
                        "default": "facts",
                    },
                },
                "required": ["concept"],
            },
        ),
        Tool(
            name="review_feasibility",
            description="Heuristic pre-flight validation of a Screenplay. No API call. Returns FeasibilityReport.",
            inputSchema={
                "type": "object",
                "properties": {
                    "screenplay": {"type": "object", "description": "Screenplay dict"},
                },
                "required": ["screenplay"],
            },
        ),
        Tool(
            name="revise_scene",
            description="Revise one scene in a Screenplay given a structured issue from production or review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "screenplay": {"type": "object", "description": "Screenplay dict"},
                    "scene_id": {"type": "string"},
                    "issue": {"type": "string", "description": "Issue code, e.g. tts_failed, vo_too_long"},
                    "suggestion": {"type": "string", "description": "Revision suggestion from the production report"},
                    "revision_field": {
                        "type": "string",
                        "enum": ["vo_line", "visual", "on_screen_text"],
                        "description": "Which field to revise",
                    },
                },
                "required": ["screenplay", "scene_id"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    def _json(obj: Any) -> List[TextContent]:
        return [TextContent(type="text", text=json.dumps(obj, ensure_ascii=False))]

    try:
        # ------------------------------------------------------------------
        # 1. generate_concepts
        # ------------------------------------------------------------------
        if name == "generate_concepts":
            topic_brief = arguments["topic_brief"]
            n_concepts = int(arguments.get("n_concepts", 3))
            creative_spec = arguments.get("creative_spec")

            agent = ConceptAgent()
            concepts = agent.generate_concepts(
                topic_brief=topic_brief,
                n_concepts=n_concepts,
                creative_spec=creative_spec,
            )
            return _json({"status": "ok", "concepts": concepts, "count": len(concepts)})

        # ------------------------------------------------------------------
        # 2. write_screenplay
        # ------------------------------------------------------------------
        elif name == "write_screenplay":
            concept = arguments["concept"]
            creative_spec = arguments.get("creative_spec")
            fmt = str(arguments.get("format", "facts"))

            agent = ScreenplayAgent()
            screenplay = agent.write_screenplay(
                concept=concept,
                creative_spec=creative_spec,
                format=fmt,
            )
            return _json({"status": "ok", "screenplay": screenplay})

        # ------------------------------------------------------------------
        # 3. review_feasibility
        # ------------------------------------------------------------------
        elif name == "review_feasibility":
            screenplay = arguments["screenplay"]
            reviewer = ScreenplayReviewer()
            report = reviewer.review(screenplay)
            return _json({"status": "ok", "feasibility_report": report})

        # ------------------------------------------------------------------
        # 4. revise_scene
        # ------------------------------------------------------------------
        elif name == "revise_scene":
            screenplay = arguments["screenplay"]
            scene_id = str(arguments["scene_id"])
            issue = str(arguments.get("issue", ""))
            suggestion = str(arguments.get("suggestion", ""))
            revision_field = str(arguments.get("revision_field", ""))

            agent = ScreenplayAgent()
            revised = agent.revise_scene(
                screenplay=screenplay,
                scene_id=scene_id,
                issue=issue,
                suggestion=suggestion,
                revision_field=revision_field,
            )
            return _json({"status": "ok", "screenplay": revised})

        else:
            return _json({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        return _json({"error": str(exc), "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    import sys
    import anyio
    from io import TextIOWrapper

    # Redirect sys.stdout -> stderr so print() calls inside tool handlers
    # don't corrupt the MCP JSON-RPC stdio stream (see producer_server.py comment).
    _real_stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8"))
    _real_stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
    sys.stdout = sys.stderr

    async with mcp.server.stdio.stdio_server(stdin=_real_stdin, stdout=_real_stdout) as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="screenwriting-server",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
