"""MCP Producer Server — exposes production pipeline tools over stdio transport.

Tools exposed:
  1. check_asset_availability  — Pexels probe, no download
  2. estimate_tts_duration     — heuristic, no API call
  3. generate_audio            — wraps AudioGenerationAgent
  4. fetch_assets              — wraps ScriptImageRetrievalAgent
  5. render_video              — wraps CompositorAgent + RenderAgent
  6. validate_output           — ffprobe validation + evaluation.json

Run as:
    venv/Scripts/python.exe -m src.mcp.producer_server
"""

from __future__ import annotations

import asyncio
import json
import struct
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import mcp.server.stdio
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool

from ..artifacts.io import write_json
from ..artifacts.screenplay import screenplay_to_script_package
from ..audio_agent import create_audio_agent
from ..composition_agent import create_composition_agent
from ..render_agent import create_render_agent
from ..script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent
from ..tools.image_search_tools import ImageSearchError, score_candidate_relevance, search_pexels_images
from ..utils.ffprobe_utils import probe_video_info
from ..utils.tts_utils import _WPM_BY_PRESET, estimate_duration_s
from ..video_planner import script_package_to_video_plan

app = Server("producer-server")

_PARITY_THRESHOLD_S = 0.25


# ---------------------------------------------------------------------------
# Asset download helpers
# ---------------------------------------------------------------------------

def _write_placeholder_bmp(path: Path, width: int = 720, height: int = 1280) -> None:
    """Write a solid grey BMP for use when image download fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row_size = (width * 3 + 3) & ~3
    pixel_data_size = row_size * height
    file_size = 54 + pixel_data_size
    bmp = bytearray()
    # BMP file header
    bmp += b"BM"
    bmp += struct.pack("<I", file_size)
    bmp += b"\x00\x00\x00\x00"
    bmp += struct.pack("<I", 54)
    # DIB header
    bmp += struct.pack("<I", 40)
    bmp += struct.pack("<i", width)
    bmp += struct.pack("<i", -height)  # top-down
    bmp += struct.pack("<H", 1)
    bmp += struct.pack("<H", 24)
    bmp += b"\x00" * 24
    # Pixel data (medium grey)
    row = bytes([0x80, 0x80, 0x80] * width) + bytes(row_size - width * 3)
    bmp += row * height
    path.write_bytes(bytes(bmp))


def _download_image(url: str, dest: Path) -> bool:
    """Download url to dest. Returns True on success."""
    try:
        resp = requests.get(url, timeout=30, stream=True)
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
    """Convert ScriptImageManifest (segments + candidate URLs) to VisualManifest (assets + local paths).

    Downloads the top-ranked candidate for each segment. Falls back to a
    placeholder BMP when the download fails.

    Args:
        manifest: ScriptImageManifest returned by ScriptImageRetrievalAgent.
        run_dir: Run output directory; images land in run_dir/assets/.

    Returns:
        VisualManifest dict compatible with CompositionAgent.
    """
    assets_dir = run_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    assets: List[Dict[str, Any]] = []
    for seg in manifest.get("segments") or []:
        scene_id = str(seg.get("beat_id") or seg.get("scene_id") or f"scene_{len(assets) + 1:02d}")
        candidates = seg.get("candidates") or []

        # Pick best candidate (already sorted by relevance score from ScriptImageRetrievalAgent)
        top = candidates[0] if candidates else None

        if top:
            ext = Path(str(top.get("url", ""))).suffix.lower() or ".jpg"
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                ext = ".jpg"
            dest = assets_dir / f"{scene_id}{ext}"
            ok = _download_image(top["url"], dest)
            if not ok:
                dest = assets_dir / f"{scene_id}_placeholder.bmp"
                _write_placeholder_bmp(dest)
                source = "placeholder"
                attribution: Dict[str, Any] = {}
            else:
                source = str(top.get("source", "unknown"))
                attribution = dict(top.get("attribution") or {})
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
            description="Estimate TTS duration for a voice line. Heuristic — no API call.",
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
                    "video_plan": {"type": "object", "description": "Pre-built VideoPlan dict (skips screenplay→video_plan derivation)"},
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
            description="Compositor + FFmpeg render from completed visual manifest and audio timeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "visual_manifest": {"type": "object", "description": "VisualManifest or ScriptImageManifest dict"},
                    "audio_timeline": {"type": "object", "description": "AudioTimeline dict"},
                    "video_plan": {"type": "object", "description": "VideoPlan dict (required by CompositionAgent)"},
                    "run_dir": {"type": "string"},
                    "engine": {"type": "string", "default": "ffmpeg"},
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
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:  # noqa: C901
    def _json(obj: Any) -> List[TextContent]:
        return [TextContent(type="text", text=json.dumps(obj, ensure_ascii=False))]

    try:
        # ------------------------------------------------------------------
        # 1. check_asset_availability
        # ------------------------------------------------------------------
        if name == "check_asset_availability":
            query = str(arguments["query"])
            n = int(arguments.get("n_results", 5))

            try:
                results = search_pexels_images(query, per_page=n, orientation="portrait")
            except ImageSearchError as exc:
                return _json({
                    "query": query,
                    "error": str(exc),
                    "availability": "unknown",
                    "recommendation": "rephrase",
                })

            if not results:
                return _json({
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
        # 2. estimate_tts_duration
        # ------------------------------------------------------------------
        elif name == "estimate_tts_duration":
            text = str(arguments.get("text", ""))
            preset = str(arguments.get("voice_preset", "narrator"))
            wpm = _WPM_BY_PRESET.get(preset, 150)
            duration = estimate_duration_s(text, voice_preset=preset)
            return _json({
                "text_length_chars": len(text),
                "word_count": len(text.split()),
                "estimated_duration_s": round(duration, 2),
                "voice_preset": preset,
                "wpm_used": wpm,
                "confidence": "heuristic",
            })

        # ------------------------------------------------------------------
        # 3. generate_audio
        # ------------------------------------------------------------------
        elif name == "generate_audio":
            run_dir = Path(str(arguments["run_dir"]))
            scene_ids: Any = arguments.get("scene_ids") or None
            voice = str(arguments.get("voice_preset", "narrator"))

            run_dir.mkdir(parents=True, exist_ok=True)

            # Accept a pre-built video_plan (checkpoint mode) or derive from screenplay
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

            # Read accumulated production issues for this run
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

            return _json({
                "status": "ok",
                "audio_timeline": audio_timeline,
                "segments": segments,
                "production_issues": [i for i in production_issues if i.get("agent") == "AudioAgent"],
            })

        # ------------------------------------------------------------------
        # 4. fetch_assets
        # ------------------------------------------------------------------
        elif name == "fetch_assets":
            script_package: Dict[str, Any] = arguments["script_package"]
            run_dir = Path(str(arguments["run_dir"]))
            scene_ids: Any = arguments.get("scene_ids") or None
            run_id = str(arguments.get("run_id", ""))

            run_dir.mkdir(parents=True, exist_ok=True)
            agent = ScriptImageRetrievalAgent(ScriptImageConfig(output_dir=run_dir))
            script_image_manifest = agent.generate_script_image_manifest(
                script_package, scene_ids=scene_ids, run_id=run_id
            )

            # Download top-ranked candidates to local files and build a
            # VisualManifest (assets list) that CompositionAgent can consume.
            visual_manifest = _script_image_manifest_to_visual_manifest(script_image_manifest, run_dir)
            write_json(run_dir / "visual_manifest.json", visual_manifest)

            report_path = run_dir / "production_report.json"
            production_issues: List[Dict[str, Any]] = []
            if report_path.exists():
                try:
                    data = json.loads(report_path.read_text(encoding="utf-8"))
                    production_issues = list(data.get("issues") or [])
                except Exception:
                    pass

            scene_assets = []
            for seg in (script_image_manifest.get("segments") or []):
                sid = seg.get("beat_id") or seg.get("scene_id", "")
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
        # 5. render_video
        # ------------------------------------------------------------------
        elif name == "render_video":
            visual_manifest: Dict[str, Any] = arguments["visual_manifest"]
            audio_timeline: Dict[str, Any] = arguments["audio_timeline"]
            video_plan_arg: Dict[str, Any] = arguments["video_plan"]
            run_dir = Path(str(arguments["run_dir"]))

            run_dir.mkdir(parents=True, exist_ok=True)

            compositor = create_composition_agent(output_dir=run_dir)
            render_spec = compositor.create_render_specification(
                video_plan=video_plan_arg,
                visual_manifest=visual_manifest,
                audio_timeline=audio_timeline,
            )
            write_json(run_dir / "render_spec.json", render_spec)

            render_agent = create_render_agent(output_dir=run_dir)
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
        # 6. validate_output
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
            }
            evaluation_path = run_dir / "evaluation.json"
            write_json(evaluation_path, evaluation)

            return _json({
                "mp4_exists": mp4_path.exists(),
                "has_audio_stream": info["has_audio"],
                "video_duration_s": round(video_duration_s, 3),
                "audio_duration_s": round(audio_duration_s, 3),
                "duration_parity_s": round(parity_s, 3),
                "duration_parity_ok": parity_ok,
                "evaluation_path": str(evaluation_path),
                "passed": len(failures) == 0,
                "failures": failures,
            })

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

    # Capture the real stdout/stdin buffers before redirecting sys.stdout.
    # Tool handlers (and imported libraries) may call print(), which writes to
    # sys.stdout.  On MCP's stdio transport that stdout is the JSON-RPC channel;
    # any extraneous bytes corrupt the message framing and cause the client to
    # hang.  We fix this by:
    #   1. Wrapping the real buffers explicitly so MCP still uses fd 1 / fd 0.
    #   2. Replacing sys.stdout with sys.stderr so all print() output goes there.
    _real_stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8"))
    _real_stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
    sys.stdout = sys.stderr  # print() -> stderr from here on

    async with mcp.server.stdio.stdio_server(stdin=_real_stdin, stdout=_real_stdout) as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="producer-server",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
