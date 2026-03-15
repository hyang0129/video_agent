"""MCP Video Agent Server — all 18 tools over HTTPS Streamable HTTP transport.

Tools exposed:
  Screenwriting (4):
    1. generate_concepts        -- generate N concept variants from a TopicBrief
    2. write_screenplay         -- write a Screenplay from a Concept
    3. review_feasibility       -- heuristic pre-flight validation (no API call)
    4. revise_scene             -- revise one scene given a structured issue

  Research & planning (5):
   11. research_topic           -- market research via YouTube API + LLM
   12. mine_facts               -- fact mining from YouTube captions
   13. generate_script          -- direct topic->script (non-screenplay path)
   14. create_video_plan        -- ScriptPackage -> VideoPlan (deterministic)
   15. select_music             -- background music selection

  Production (6):
    5. check_asset_availability -- Pexels probe, no download
    6. estimate_tts_duration    -- heuristic, no API call
    7. generate_audio           -- wraps AudioGenerationAgent
    8. fetch_assets             -- wraps ScriptImageRetrievalAgent
    9. render_video             -- wraps CompositorAgent + RenderAgent (avatar_manifest optional)
   10. validate_output          -- ffprobe validation + evaluation.json

  Avatar / Live2D (3):
   16. generate_lipsync         -- Rhubarb lip-sync from AudioTimeline MP3 segments
   17. package_avatar           -- build AvatarSceneManifest (full-timeline, one manifest)
   18. render_avatar            -- invoke live2d-render binary, produce avatar_full.mov

Run as:
    MCP_SERVER_TOKEN=<token> python -m src.mcp.video_agent_server --port 8443
"""

from __future__ import annotations

import json
import struct
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..artifacts.io import write_json
from ..artifacts.screenplay import screenplay_to_script_package
from ..audio_agent import create_audio_agent
from ..avatar_cue_agent import AvatarCueAgent
from ..avatar_packaging_agent import AvatarPackagingAgent
from ..avatar_render_agent import AvatarRenderAgent
from ..rhubarb_agent import RhubarbAgent
from ..composition_agent import create_composition_agent
from ..render_agent import create_render_agent
from ..screenwriting.concept_agent import ConceptAgent
from ..screenwriting.screenplay_agent import ScreenplayAgent
from ..screenwriting.screenplay_reviewer import ScreenplayReviewer
from ..script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent
from ..tools.image_search_tools import ImageSearchError, score_candidate_relevance, search_pexels_images, wikimedia_rate_limiter
from ..utils.ffprobe_utils import probe_video_info
from ..utils.tts_utils import _WPM_BY_PRESET, estimate_duration_s
from ..video_planner import script_package_to_video_plan
from .https_server_base import DEFAULT_CERT, DEFAULT_KEY, run_https_server

app = Server("video-agent-server")

_PARITY_THRESHOLD_S = 0.25


# ---------------------------------------------------------------------------
# Asset download helpers (from former producer_server)
# ---------------------------------------------------------------------------

def _write_placeholder_bmp(path: Path, width: int = 720, height: int = 1280) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_size = (width * 3 + 3) & ~3
    pixel_data_size = row_size * height
    file_size = 54 + pixel_data_size
    bmp = bytearray()
    bmp += b"BM"
    bmp += struct.pack("<I", file_size)
    bmp += b"\x00\x00\x00\x00"
    bmp += struct.pack("<I", 54)
    bmp += struct.pack("<I", 40)
    bmp += struct.pack("<i", width)
    bmp += struct.pack("<i", -height)
    bmp += struct.pack("<H", 1)
    bmp += struct.pack("<H", 24)
    bmp += b"\x00" * 24
    row = bytes([0x80, 0x80, 0x80] * width) + bytes(row_size - width * 3)
    bmp += row * height
    path.write_bytes(bytes(bmp))


_DOWNLOAD_HEADERS = {
    "User-Agent": "VideoAgent/1.0",
}


_WIKIMEDIA_HOSTS = ("upload.wikimedia.org", "commons.wikimedia.org")


def _download_image(url: str, dest: Path) -> bool:
    try:
        if any(h in url for h in _WIKIMEDIA_HOSTS):
            wikimedia_rate_limiter.throttle()
        resp = requests.get(url, timeout=30, stream=True, headers=_DOWNLOAD_HEADERS)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        return True
    except Exception:
        return False


def _script_image_manifest_to_visual_manifest(
    manifest: Dict[str, Any],
    run_dir: Path,
) -> Dict[str, Any]:
    assets_dir = run_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    assets: List[Dict[str, Any]] = []
    for seg in manifest.get("segments") or []:
        scene_id = str(seg.get("segment_id") or seg.get("beat_id") or seg.get("scene_id") or f"scene_{len(assets) + 1:02d}")
        candidates = seg.get("candidates") or []

        downloaded: Optional[Dict[str, Any]] = None
        for cand in candidates:
            ext = Path(str(cand.get("url", ""))).suffix.lower() or ".jpg"
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                ext = ".jpg"
            dest = assets_dir / f"{scene_id}{ext}"
            if _download_image(cand["url"], dest):
                downloaded = cand
                break

        if downloaded:
            source = str(downloaded.get("source", "unknown"))
            attribution: Dict[str, Any] = dict(downloaded.get("attribution") or {})
        else:
            dest = assets_dir / f"{scene_id}_placeholder.bmp"
            _write_placeholder_bmp(dest)
            source = "placeholder"
            attribution = {}

        assets.append({
            "scene_id": scene_id,
            "file_path": str(dest.relative_to(run_dir)).replace("\\", "/"),
            "source": source,
            "attribution": attribution,
        })

    return {
        "schema_version": "1.0.0",
        "visual_manifest_id": f"vm_{uuid.uuid4().hex[:8]}",
        "source": "script_image_agent",
        "assets": assets,
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> List[Tool]:
    return [
        # -- Screenwriting tools (4) --
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
        # -- Research & planning tools (5) --
        Tool(
            name="research_topic",
            description="Run market research for a category. Calls YouTube API + LLM analysis. Returns top topic brief.",
            inputSchema={
                "type": "object",
                "properties": {
                    "setting": {"type": "string", "description": "Category to research, e.g. 'cheese facts'"},
                    "max_results": {"type": "integer", "default": 50, "description": "Max YouTube results to analyse"},
                },
                "required": ["setting"],
            },
        ),
        Tool(
            name="mine_facts",
            description="Mine facts from top YouTube videos for a topic. Writes to facts.db.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_query": {"type": "string", "description": "Search query for YouTube"},
                    "topic_id": {"type": "string", "description": "Topic identifier for facts.db"},
                    "subtopic_id": {"type": "string", "description": "Optional subtopic identifier"},
                    "max_videos": {"type": "integer", "default": 5, "description": "Max videos to mine"},
                    "use_captions": {"type": "boolean", "default": True, "description": "Extract facts from captions"},
                },
                "required": ["topic_query", "topic_id"],
            },
        ),
        Tool(
            name="generate_script",
            description="Generate a ScriptPackage directly from a TopicBrief (non-screenplay path).",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic_brief": {"type": "object", "description": "TopicBrief dict"},
                    "creative_spec": {"type": "object", "description": "Optional CreativeSpec dict"},
                },
                "required": ["topic_brief"],
            },
        ),
        Tool(
            name="create_video_plan",
            description="Convert a ScriptPackage into a VideoPlan. Deterministic, no LLM call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "script_package": {"type": "object", "description": "ScriptPackage dict"},
                    "creative_spec": {"type": "object", "description": "Optional CreativeSpec dict"},
                },
                "required": ["script_package"],
            },
        ),
        Tool(
            name="select_music",
            description="Select background music for a video given its AudioTimeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "audio_timeline": {"type": "object", "description": "AudioTimeline dict"},
                    "video_plan": {"type": "object", "description": "Optional VideoPlan dict"},
                    "script_package": {"type": "object", "description": "Optional ScriptPackage dict"},
                    "visual_manifest": {"type": "object", "description": "Optional VisualManifest dict"},
                },
                "required": ["audio_timeline"],
            },
        ),
        # -- Production tools (6) --
        Tool(
            name="check_asset_availability",
            description="Probe Pexels for a visual description. Returns relevance score. No image download.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Visual description or Pexels search query"},
                    "n_results": {"type": "integer", "default": 5, "description": "Number of results to probe"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="estimate_tts_duration",
            description="Estimate TTS duration for a voice line. Heuristic -- no API call.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The vo_line to estimate"},
                    "voice_preset": {
                        "type": "string",
                        "enum": ["calm", "narrator", "energetic", "authoritative"],
                        "default": "narrator",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="generate_audio",
            description="Run TTS voiceover for one or more scenes. Wraps AudioGenerationAgent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "screenplay": {"type": "object", "description": "Screenplay dict (used to derive video_plan if video_plan not provided)"},
                    "video_plan": {"type": "object", "description": "Pre-built VideoPlan dict (skips screenplay->video_plan derivation)"},
                    "run_dir": {"type": "string", "description": "Path to run output directory"},
                    "scene_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of scene IDs to generate. Omit for all scenes.",
                    },
                    "voice_preset": {"type": "string", "default": "narrator"},
                },
                "required": ["run_dir"],
            },
        ),
        Tool(
            name="fetch_assets",
            description="Retrieve and score images for one or more scenes. Wraps ScriptImageRetrievalAgent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "script_package": {"type": "object", "description": "ScriptPackage dict"},
                    "run_dir": {"type": "string", "description": "Path to run output directory"},
                    "scene_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of scene IDs to fetch. Omit for all scenes.",
                    },
                    "run_id": {"type": "string", "default": ""},
                },
                "required": ["script_package", "run_dir"],
            },
        ),
        Tool(
            name="render_video",
            description="Compositor + FFmpeg render from completed visual manifest and audio timeline. Pass avatar_manifest to composite a Live2D avatar overlay.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visual_manifest": {"type": "object", "description": "VisualManifest or ScriptImageManifest dict"},
                    "audio_timeline": {"type": "object", "description": "AudioTimeline dict"},
                    "video_plan": {"type": "object", "description": "VideoPlan dict (required by CompositionAgent)"},
                    "run_dir": {"type": "string"},
                    "engine": {"type": "string", "default": "ffmpeg"},
                    "avatar_manifest": {"type": "object", "description": "Optional AvatarSceneManifest dict. When provided, the Live2D avatar video is composited into the final render."},
                },
                "required": ["visual_manifest", "audio_timeline", "video_plan", "run_dir"],
            },
        ),
        Tool(
            name="validate_output",
            description="ffprobe validation of the final MP4 and evaluation.json emission.",
            inputSchema={
                "type": "object",
                "properties": {
                    "mp4_path": {"type": "string"},
                    "audio_timeline": {"type": "object", "description": "AudioTimeline dict (for duration reference)"},
                    "run_dir": {"type": "string"},
                },
                "required": ["mp4_path", "run_dir"],
            },
        ),
        # -- Avatar / Live2D tools (3) --
        Tool(
            name="generate_lipsync",
            description="Run Rhubarb lip-sync on voiceover MP3 segments from an AudioTimeline. Produces lipsync_manifest.json. Degrades gracefully if Rhubarb is unavailable.",
            inputSchema={
                "type": "object",
                "properties": {
                    "audio_timeline": {"type": "object", "description": "AudioTimeline dict"},
                    "run_dir": {"type": "string", "description": "Pipeline run directory containing MP3 segments"},
                },
                "required": ["audio_timeline", "run_dir"],
            },
        ),
        Tool(
            name="package_avatar",
            description="Build a single continuous AvatarSceneManifest from lipsync_manifest and audio_timeline. Writes avatar_full_manifest.json and WAV segments to avatar_takes/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lipsync_manifest": {"type": "object", "description": "LipSyncManifest dict from generate_lipsync"},
                    "audio_timeline": {"type": "object", "description": "AudioTimeline dict"},
                    "run_dir": {"type": "string", "description": "Pipeline run directory"},
                    "model_id": {"type": "string", "description": "Live2D model ID (default: from config)"},
                },
                "required": ["lipsync_manifest", "audio_timeline", "run_dir"],
            },
        ),
        Tool(
            name="render_avatar",
            description="Invoke live2d-render to produce avatar_full.mov from the AvatarSceneManifest. Returns path to the rendered .mov file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "avatar_manifest": {"type": "object", "description": "AvatarSceneManifest dict from package_avatar"},
                    "run_dir": {"type": "string", "description": "Pipeline run directory"},
                },
                "required": ["avatar_manifest", "run_dir"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:  # noqa: C901
    _tool_t0 = time.monotonic()

    def _json(obj: Any) -> List[TextContent]:
        if isinstance(obj, dict):
            obj["elapsed_seconds"] = round(time.monotonic() - _tool_t0, 3)
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
            )
            return _json({"status": "ok", "concepts": concepts, "count": len(concepts)})

        # ------------------------------------------------------------------
        # 2. write_screenplay
        # ------------------------------------------------------------------
        elif name == "write_screenplay":
            concept = arguments["concept"]
            creative_spec = arguments.get("creative_spec")

            # ScreenplayAgent needs a topic_brief; derive from creative_spec or
            # build a minimal one from the concept itself.
            topic_brief_arg = creative_spec or {
                "topic": {"name": concept.get("title", "")},
                "subtopic": {"name": concept.get("subtitle", ""), "angle": concept.get("angle", "")},
            }

            agent = ScreenplayAgent()
            screenplay = agent.write_screenplay(
                concept=concept,
                topic_brief=topic_brief_arg,
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

        # ------------------------------------------------------------------
        # 11. research_topic
        # ------------------------------------------------------------------
        elif name == "research_topic":
            setting = str(arguments["setting"])
            max_results = int(arguments.get("max_results", 50))

            from ..agent import create_agent
            agent = create_agent()
            result = agent.research_category_artifacts(setting, max_results=max_results)

            topic_brief_paths = result.get("topic_brief_paths") or []
            topic_brief = None
            if topic_brief_paths:
                topic_brief = json.loads(Path(topic_brief_paths[0]).read_text(encoding="utf-8"))

            return _json({
                "status": "ok" if topic_brief else "no_results",
                "run_id": result.get("run_id", ""),
                "topic_brief": topic_brief,
                "topic_brief_path": topic_brief_paths[0] if topic_brief_paths else None,
                "report_path": result.get("report_path", ""),
                "topic_brief_count": len(topic_brief_paths),
            })

        # ------------------------------------------------------------------
        # 12. mine_facts
        # ------------------------------------------------------------------
        elif name == "mine_facts":
            topic_query = str(arguments["topic_query"])
            topic_id = str(arguments.get("topic_id", ""))
            subtopic_id = str(arguments.get("subtopic_id", "")) or None
            max_videos = int(arguments.get("max_videos", 5))
            use_captions = bool(arguments.get("use_captions", True))

            from ..facts.fact_miner import FactMiner
            miner = FactMiner()
            result = miner.mine_top_videos(
                topic_query=topic_query,
                topic_id=topic_id,
                subtopic_id=subtopic_id,
                max_videos=max_videos,
                use_captions=use_captions,
            )
            return _json({"status": "ok", **result})

        # ------------------------------------------------------------------
        # 13. generate_script
        # ------------------------------------------------------------------
        elif name == "generate_script":
            topic_brief = arguments["topic_brief"]
            creative_spec = arguments.get("creative_spec")

            from ..script_agent import create_script_agent
            agent = create_script_agent()
            script_package = agent.generate_script_package(
                topic_brief=topic_brief,
                creative_spec=creative_spec,
            )
            return _json({"status": "ok", "script_package": script_package})

        # ------------------------------------------------------------------
        # 14. create_video_plan
        # ------------------------------------------------------------------
        elif name == "create_video_plan":
            sp = arguments["script_package"]
            creative_spec = arguments.get("creative_spec")

            video_plan = script_package_to_video_plan(
                script_package=sp,
                creative_spec=creative_spec,
            )
            return _json({"status": "ok", "video_plan": video_plan})

        # ------------------------------------------------------------------
        # 15. select_music
        # ------------------------------------------------------------------
        elif name == "select_music":
            audio_timeline_arg: Dict[str, Any] = arguments["audio_timeline"]

            from ..music_agent import create_music_agent
            from ..config import RESULTS_DIR
            import asyncio
            agent = create_music_agent(output_dir=RESULTS_DIR)

            # MusicAgent uses asyncio.run() internally (sync wrappers for
            # httpx.AsyncClient). Run in a thread to avoid "cannot call
            # asyncio.run() from a running event loop" when dispatched
            # from the MCP in-process path.
            music_selection = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: agent.select_music(
                    audio_timeline_arg,
                    video_plan=arguments.get("video_plan"),
                    script_package=arguments.get("script_package"),
                    visual_manifest=arguments.get("visual_manifest"),
                ),
            )
            return _json({"status": "ok", "music_selection": music_selection})

        # ------------------------------------------------------------------
        # 5. check_asset_availability
        # ------------------------------------------------------------------
        elif name == "check_asset_availability":
            query = str(arguments["query"])
            n = int(arguments.get("n_results", 5))

            try:
                results = search_pexels_images(query, per_page=n, orientation="portrait")
            except ImageSearchError as exc:
                return _json({
                    "status": "error",
                    "query": query,
                    "error": str(exc),
                    "availability": "unknown",
                    "recommendation": "rephrase",
                })

            if not results:
                return _json({
                    "status": "ok",
                    "query": query,
                    "result_count": 0,
                    "top_relevance_score": 0.0,
                    "availability": "poor",
                    "recommendation": "reject",
                    "top_results": [],
                })

            scores = [score_candidate_relevance(r, query) for r in results]
            top_score = max(scores)
            availability = "good" if top_score >= 0.6 else ("marginal" if top_score >= 0.35 else "poor")
            recommendation = "ok" if top_score >= 0.6 else ("rephrase" if top_score >= 0.35 else "reject")

            ranked = sorted(zip(results, scores), key=lambda x: -x[1])
            return _json({
                "status": "ok",
                "query": query,
                "result_count": len(results),
                "top_relevance_score": round(top_score, 3),
                "availability": availability,
                "recommendation": recommendation,
                "top_results": [
                    {"url": r["url"], "resolution": r.get("resolution", []), "relevance_score": round(s, 3)}
                    for r, s in ranked[:3]
                ],
            })

        # ------------------------------------------------------------------
        # 6. estimate_tts_duration
        # ------------------------------------------------------------------
        elif name == "estimate_tts_duration":
            text = str(arguments.get("text", ""))
            preset = str(arguments.get("voice_preset", "narrator"))
            wpm = _WPM_BY_PRESET.get(preset, 150)
            duration = estimate_duration_s(text, voice_preset=preset)
            return _json({
                "status": "ok",
                "text_length_chars": len(text),
                "word_count": len(text.split()),
                "estimated_duration_s": round(duration, 2),
                "voice_preset": preset,
                "wpm_used": wpm,
                "confidence": "heuristic",
            })

        # ------------------------------------------------------------------
        # 7. generate_audio
        # ------------------------------------------------------------------
        elif name == "generate_audio":
            run_dir = Path(str(arguments["run_dir"]))
            scene_ids: Any = arguments.get("scene_ids") or None
            voice = str(arguments.get("voice_preset", "narrator"))

            run_dir.mkdir(parents=True, exist_ok=True)

            if "video_plan" in arguments:
                video_plan: Dict[str, Any] = arguments["video_plan"]
            elif "screenplay" in arguments:
                screenplay_arg: Dict[str, Any] = arguments["screenplay"]
                _sp = screenplay_to_script_package(screenplay_arg)
                video_plan = script_package_to_video_plan(_sp)
            else:
                return _json({"error": "generate_audio requires 'video_plan' or 'screenplay'"})

            agent = create_audio_agent(output_dir=run_dir, voice=voice)
            audio_timeline = agent.generate_audio_timeline(video_plan, scene_ids=scene_ids)

            report_path = run_dir / "production_report.json"
            production_issues: List[Dict[str, Any]] = []
            if report_path.exists():
                try:
                    data = json.loads(report_path.read_text(encoding="utf-8"))
                    production_issues = list(data.get("issues") or [])
                except Exception:
                    pass

            segments = [
                {
                    "scene_id": t["scene_id"],
                    "audio_path": t["file"],
                    "duration_s": round(t["t_end_s"] - t["t_start_s"], 3),
                    "status": "degraded" if any(
                        i.get("scene_id") == t["scene_id"] and i.get("status") == "degraded"
                        for i in production_issues
                    ) else "ok",
                }
                for t in (audio_timeline.get("tracks") or [])
                if t.get("type") == "voiceover"
            ]

            degraded_count = sum(1 for s in segments if s.get("status") == "degraded")
            all_degraded = len(segments) > 0 and degraded_count == len(segments)
            audio_status = "degraded" if all_degraded else ("ok" if degraded_count == 0 else "partial")
            return _json({
                "status": audio_status,
                "audio_timeline": audio_timeline,
                "segments": segments,
                "degraded_count": degraded_count,
                "production_issues": [i for i in production_issues if i.get("agent") == "AudioAgent"],
            })

        # ------------------------------------------------------------------
        # 8. fetch_assets
        # ------------------------------------------------------------------
        elif name == "fetch_assets":
            script_package: Dict[str, Any] = arguments["script_package"]
            run_dir = Path(str(arguments["run_dir"]))
            scene_ids: Any = arguments.get("scene_ids") or None
            run_id = str(arguments.get("run_id", ""))

            run_dir.mkdir(parents=True, exist_ok=True)
            agent = ScriptImageRetrievalAgent(ScriptImageConfig(
                output_dir=run_dir,
                image_sources=("wikimedia", "pexels"),
            ))
            script_image_manifest = agent.generate_script_image_manifest(
                script_package, scene_ids=scene_ids, run_id=run_id
            )

            visual_manifest = _script_image_manifest_to_visual_manifest(script_image_manifest, run_dir)

            # If any scenes are placeholders (Wikimedia downloads failed), retry with Pexels only.
            placeholder_ids = [
                a["scene_id"] for a in (visual_manifest.get("assets") or [])
                if a.get("source") == "placeholder" and a.get("scene_id")
            ]
            if placeholder_ids:
                pexels_agent = ScriptImageRetrievalAgent(ScriptImageConfig(
                    output_dir=run_dir,
                    image_sources=("pexels",),
                ))
                pexels_manifest = pexels_agent.generate_script_image_manifest(
                    script_package, scene_ids=placeholder_ids, run_id=run_id
                )
                pexels_vm = _script_image_manifest_to_visual_manifest(pexels_manifest, run_dir)
                pexels_by_scene = {
                    a["scene_id"]: a for a in (pexels_vm.get("assets") or [])
                    if a.get("source") != "placeholder" and a.get("scene_id")
                }
                if pexels_by_scene:
                    visual_manifest = {
                        **visual_manifest,
                        "assets": [
                            pexels_by_scene.get(a["scene_id"], a)
                            for a in (visual_manifest.get("assets") or [])
                        ],
                    }

            # When re-fetching a subset of scenes, merge into the existing manifest.
            existing_vm_path = run_dir / "visual_manifest.json"
            if scene_ids and existing_vm_path.exists():
                try:
                    existing_vm = json.loads(existing_vm_path.read_text(encoding="utf-8"))
                    new_assets_by_scene = {a["scene_id"]: a for a in (visual_manifest.get("assets") or []) if a.get("scene_id")}
                    merged_assets = [
                        new_assets_by_scene.get(a["scene_id"], a)
                        for a in (existing_vm.get("assets") or [])
                        if a.get("scene_id")
                    ]
                    # Add any new scenes not in the original manifest.
                    existing_ids = {a["scene_id"] for a in merged_assets}
                    for a in (visual_manifest.get("assets") or []):
                        if a.get("scene_id") and a["scene_id"] not in existing_ids:
                            merged_assets.append(a)
                    visual_manifest = {**visual_manifest, "assets": merged_assets}
                except Exception:
                    pass

            write_json(run_dir / "visual_manifest.json", visual_manifest)

            report_path = run_dir / "production_report.json"
            production_issues = []
            if report_path.exists():
                try:
                    data = json.loads(report_path.read_text(encoding="utf-8"))
                    production_issues = list(data.get("issues") or [])
                except Exception:
                    pass

            scene_assets = []
            for seg in (script_image_manifest.get("segments") or []):
                sid = seg.get("segment_id") or seg.get("beat_id") or seg.get("scene_id", "")
                candidates = seg.get("candidates") or []
                top_score = 0.0
                image_paths: List[str] = []
                for c in candidates:
                    score = float(((c.get("metadata") or {}).get("relevance") or {}).get("score") or 0.0)
                    if score > top_score:
                        top_score = score
                    url = c.get("url", "")
                    if url:
                        image_paths.append(url)

                degraded = any(
                    i.get("scene_id") == sid and i.get("status") == "degraded"
                    for i in production_issues
                )
                scene_assets.append({
                    "scene_id": sid,
                    "image_paths": image_paths[:3],
                    "relevance_score": round(top_score, 3),
                    "status": "degraded" if degraded else "ok",
                })

            return _json({
                "status": "ok",
                "visual_manifest": visual_manifest,
                "script_image_manifest": script_image_manifest,
                "scene_assets": scene_assets,
                "production_issues": [i for i in production_issues if i.get("agent") == "ScriptImageAgent"],
            })

        # ------------------------------------------------------------------
        # 9. render_video
        # ------------------------------------------------------------------
        elif name == "render_video":
            visual_manifest: Dict[str, Any] = arguments["visual_manifest"]
            audio_timeline: Dict[str, Any] = arguments["audio_timeline"]
            video_plan_arg: Dict[str, Any] = arguments["video_plan"]
            run_dir = Path(str(arguments["run_dir"]))
            avatar_manifest_arg: Optional[Dict[str, Any]] = arguments.get("avatar_manifest")

            run_dir.mkdir(parents=True, exist_ok=True)

            compositor = create_composition_agent(output_dir=run_dir)
            render_spec = compositor.create_render_specification(
                video_plan=video_plan_arg,
                visual_manifest=visual_manifest,
                audio_timeline=audio_timeline,
                avatar_manifest=avatar_manifest_arg,
            )
            write_json(run_dir / "render_spec.json", render_spec)

            engine_name = str(arguments.get("engine") or "ffmpeg")
            render_agent = create_render_agent(output_dir=run_dir, engine=engine_name)
            render_result = render_agent.render(render_spec)

            mp4_path = str(render_result.get("output_path") or run_dir / "final_video.mp4")
            duration_s = float(render_result.get("duration_s") or 0.0)

            return _json({
                "status": render_result.get("status", "ok"),
                "mp4_path": mp4_path,
                "render_spec_path": str(run_dir / "render_spec.json"),
                "duration_s": duration_s,
            })

        # ------------------------------------------------------------------
        # 10. validate_output
        # ------------------------------------------------------------------
        elif name == "validate_output":
            mp4_path = Path(str(arguments["mp4_path"]))
            run_dir = Path(str(arguments["run_dir"]))
            audio_timeline: Dict[str, Any] = arguments.get("audio_timeline") or {}

            run_dir.mkdir(parents=True, exist_ok=True)

            info = probe_video_info(mp4_path)
            audio_duration_s = float(audio_timeline.get("duration_seconds") or info["audio_duration_s"])
            video_duration_s = info["video_duration_s"]
            parity_s = abs(video_duration_s - audio_duration_s)
            parity_ok = parity_s <= _PARITY_THRESHOLD_S

            failures: List[str] = []
            if not mp4_path.exists():
                failures.append("mp4_missing")
            if not info["has_video"]:
                failures.append("no_video_stream")
            if not parity_ok:
                failures.append(f"duration_parity_{parity_s:.2f}s_exceeds_{_PARITY_THRESHOLD_S}s")

            # render_health: structured critical-failure record (no log parsing)
            file_size_bytes = mp4_path.stat().st_size if mp4_path.exists() else 0

            fv_json_path = run_dir / "final_video.json"
            fv_meta = json.loads(fv_json_path.read_text(encoding="utf-8")) if fv_json_path.exists() else {}
            engine_name = (fv_meta.get("render_metadata") or {}).get("engine", "unknown")

            pr_path = run_dir / "production_report.json"
            pr = json.loads(pr_path.read_text(encoding="utf-8")) if pr_path.exists() else {}
            degraded_count = int(pr.get("degraded_scene_count") or 0)
            total_scenes = len(pr.get("issues") or []) + (degraded_count if not pr.get("issues") else 0)

            critical_failures: List[str] = []
            if file_size_bytes == 0:
                critical_failures.append("mp4_empty")
            if "DryRun" in engine_name:
                critical_failures.append("dry_run_engine_used")
            if not info["has_audio"]:
                critical_failures.append("no_audio_stream")
            if degraded_count > 0 and degraded_count == total_scenes:
                critical_failures.append(f"all_{total_scenes}_scenes_degraded")
            elif degraded_count > 0:
                critical_failures.append(f"{degraded_count}_scenes_degraded")

            render_health = {
                "engine": engine_name,
                "file_size_bytes": file_size_bytes,
                "degraded_scene_count": degraded_count,
                "critical_failures": critical_failures,
                "ok": len(critical_failures) == 0,
            }

            evaluation = {
                "schema_version": "1.0.0",
                "mp4_path": str(mp4_path),
                "video_duration_s": round(video_duration_s, 3),
                "audio_duration_s": round(audio_duration_s, 3),
                "duration_parity_s": round(parity_s, 3),
                "duration_parity_ok": parity_ok,
                "has_video_stream": info["has_video"],
                "has_audio_stream": info["has_audio"],
                "passed": len(failures) == 0,
                "failures": failures,
                "render_health": render_health,
            }
            evaluation_path = run_dir / "evaluation.json"
            write_json(evaluation_path, evaluation)

            validate_status = "ok" if len(failures) == 0 else ("warn" if parity_ok else "fail")
            return _json({
                "status": validate_status,
                "mp4_exists": mp4_path.exists(),
                "has_audio_stream": info["has_audio"],
                "video_duration_s": round(video_duration_s, 3),
                "audio_duration_s": round(audio_duration_s, 3),
                "duration_parity_s": round(parity_s, 3),
                "duration_parity_ok": parity_ok,
                "evaluation_path": str(evaluation_path),
                "passed": len(failures) == 0,
                "failures": failures,
                "render_health": render_health,
            })

        # ------------------------------------------------------------------
        # 16. generate_lipsync
        # ------------------------------------------------------------------
        elif name == "generate_lipsync":
            audio_timeline_arg: Dict[str, Any] = arguments["audio_timeline"]
            run_dir = Path(str(arguments["run_dir"]))
            run_dir.mkdir(parents=True, exist_ok=True)

            agent = RhubarbAgent()
            lipsync_manifest = agent.generate_lipsync_manifest(audio_timeline_arg, run_dir)
            scenes_ok = len(lipsync_manifest.get("scenes", []))
            notes = " ".join(lipsync_manifest.get("processing_notes", []))
            degraded = "rhubarb_unavailable" in notes
            lipsync_status = "degraded" if degraded else "ok"

            return _json({
                "status": lipsync_status,
                "lipsync_manifest": lipsync_manifest,
                "scenes_processed": scenes_ok,
                "degraded": degraded,
                "rhubarb_version": lipsync_manifest.get("rhubarb_version", "unknown"),
            })

        # ------------------------------------------------------------------
        # 17. package_avatar
        # ------------------------------------------------------------------
        elif name == "package_avatar":
            lipsync_manifest_arg: Dict[str, Any] = arguments["lipsync_manifest"]
            audio_timeline_arg: Dict[str, Any] = arguments["audio_timeline"]
            run_dir = Path(str(arguments["run_dir"]))
            run_dir.mkdir(parents=True, exist_ok=True)

            cue_agent = AvatarCueAgent()
            cues_by_scene = cue_agent.generate_cues(audio_timeline_arg)

            pkg_agent = AvatarPackagingAgent()
            avatar_manifest = pkg_agent.package_full(
                lipsync_manifest=lipsync_manifest_arg,
                audio_timeline=audio_timeline_arg,
                run_dir=run_dir,
                cues_by_scene=cues_by_scene,
            )
            scenes_packaged = len(lipsync_manifest_arg.get("scenes", []))

            return _json({
                "status": "ok",
                "avatar_manifest": avatar_manifest,
                "scenes_packaged": scenes_packaged,
                "manifest_path": str(run_dir / "avatar_takes" / "avatar_full_manifest.json"),
            })

        # ------------------------------------------------------------------
        # 18. render_avatar
        # ------------------------------------------------------------------
        elif name == "render_avatar":
            avatar_manifest_arg: Dict[str, Any] = arguments["avatar_manifest"]
            run_dir = Path(str(arguments["run_dir"]))
            run_dir.mkdir(parents=True, exist_ok=True)

            render_agent_av = AvatarRenderAgent()
            mov_path = render_agent_av.render(avatar_manifest_arg, run_dir)

            if mov_path and mov_path.exists():
                size_bytes = mov_path.stat().st_size
                return _json({
                    "status": "ok",
                    "mov_path": str(mov_path),
                    "size_bytes": size_bytes,
                })
            else:
                return _json({
                    "status": "error",
                    "error": "live2d-render produced no output; check LIVE2D_RENDER_PATH and LIVE2D_REPO_ROOT env vars",
                    "mov_path": None,
                })

        else:
            return _json({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        return _json({"error": str(exc), "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Video Agent MCP server over HTTPS")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--cert", type=Path, default=DEFAULT_CERT)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    args = parser.parse_args()
    run_https_server(app, "video-agent-server", args.host, args.port, args.cert, args.key)


if __name__ == "__main__":
    main()
