"""Production orchestrator with scene-level revision loop.

Manages the audio + image production pass for a screenplay run.
When agents report degraded scenes the orchestrator revises the screenplay
and re-runs only the affected agents (max MAX_REVISION_ROUNDS rounds).

Outputs written to run_dir:
- production_report.json  - combined structured failures from all agents
- scene_results.json      - per-scene production status after final round

MCP mode (use_mcp=True):
    Calls produce tools from video_agent_server in-process (no subprocess).
    This avoids network overhead and is sufficient for local debugging.
    For HTTPS transport, use _mcp_session() + VIDEO_AGENT_SERVER_URL instead.

Serial mode (serial=True):
    Runs audio generation then image fetching sequentially instead of in
    parallel.  Use this for debugging / deterministic test runs where
    interleaved log output from concurrent tasks makes tracing harder.
"""

from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .artifacts.io import write_json
from .artifacts.screenplay import screenplay_to_script_package
from .audio_agent import AudioGenerationAgent, create_audio_agent
from .config import TTS_BACKEND
from .script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent
from .video_planner import script_package_to_video_plan

MAX_REVISION_ROUNDS = 2

_VERIFY_SSL = os.environ.get("MCP_VERIFY_SSL", "false").lower() == "true"
_CA_BUNDLE = os.environ.get("MCP_CA_BUNDLE") or _VERIFY_SSL


@asynccontextmanager
async def _mcp_session():
    """Hold one TLS connection + MCP session for the duration of a pipeline run.

    Opening a new session per tool call wastes a TLS handshake + MCP initialize
    round-trip on every call -- avoid that pattern.
    """
    import httpx

    base_url = os.environ["VIDEO_AGENT_SERVER_URL"]
    token = os.environ["MCP_SERVER_TOKEN"]
    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        verify=_CA_BUNDLE,
    )
    async with http_client:
        async with streamable_http_client(f"{base_url}/mcp/", http_client=http_client) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session


# ---------------------------------------------------------------------------
# MCP in-process helpers (debug mode — no subprocess/stdio transport)
# ---------------------------------------------------------------------------

async def _call_tool_inprocess(tool_name: str, arguments: dict) -> dict:
    """Call a producer_server tool directly in-process (no subprocess/stdio).

    NOTE: This is a debug shortcut that bypasses the MCP wire transport.
    It imports and calls the tool handler function directly, which avoids
    all pipe/buffer issues while exercising the same handler code.
    """
    from .mcp.video_agent_server import call_tool  # noqa: PLC0415
    logger.debug("[MCP-inproc] calling tool={} args_keys={}", tool_name, list(arguments.keys()))
    result = await call_tool(tool_name, arguments)
    text = result[0].text if result else "{}"
    parsed = json.loads(text)
    logger.debug("[MCP-inproc] tool={} returned status={}", tool_name, parsed.get("status", "?"))
    return parsed


async def _produce_parallel_mcp(
    screenplay: Dict[str, Any],
    script_package: Dict[str, Any],
    run_dir: Path,
    run_id: str,
    voice: str,
    audio_scene_ids: Optional[List[str]] = None,
    image_scene_ids: Optional[List[str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run audio + image production via MCP tool calls in parallel."""
    audio_args: Dict[str, Any] = {
        "screenplay": screenplay,
        "run_dir": str(run_dir),
        "voice_preset": voice,
    }
    if audio_scene_ids is not None:
        audio_args["scene_ids"] = audio_scene_ids

    image_args: Dict[str, Any] = {
        "script_package": script_package,
        "run_dir": str(run_dir),
        "run_id": run_id,
    }
    if image_scene_ids is not None:
        image_args["scene_ids"] = image_scene_ids

    logger.info(
        "[orch] MCP parallel: generate_audio scenes={} | fetch_assets scenes={}",
        audio_scene_ids or "all",
        image_scene_ids or "all",
    )
    audio_result, image_result = await asyncio.gather(
        _call_tool_inprocess("generate_audio", audio_args),
        _call_tool_inprocess("fetch_assets", image_args),
    )

    audio_timeline = audio_result.get("audio_timeline") or {}
    image_manifest = image_result.get("visual_manifest") or {}
    logger.debug(
        "[orch] MCP parallel done: audio_tracks={} image_assets={}",
        len(audio_timeline.get("tracks") or []),
        len(image_manifest.get("assets") or []),
    )
    return audio_timeline, image_manifest


async def _produce_serial_mcp(
    screenplay: Dict[str, Any],
    script_package: Dict[str, Any],
    run_dir: Path,
    run_id: str,
    voice: str,
    audio_scene_ids: Optional[List[str]] = None,
    image_scene_ids: Optional[List[str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run audio then image production via MCP tool calls sequentially."""
    audio_args: Dict[str, Any] = {
        "screenplay": screenplay,
        "run_dir": str(run_dir),
        "voice_preset": voice,
    }
    if audio_scene_ids is not None:
        audio_args["scene_ids"] = audio_scene_ids

    image_args: Dict[str, Any] = {
        "script_package": script_package,
        "run_dir": str(run_dir),
        "run_id": run_id,
    }
    if image_scene_ids is not None:
        image_args["scene_ids"] = image_scene_ids

    logger.info(
        "[orch] MCP serial: step 1/2 generate_audio scenes={}",
        audio_scene_ids or "all",
    )
    audio_result = await _call_tool_inprocess("generate_audio", audio_args)
    logger.debug(
        "[orch] MCP serial: audio done tracks={}",
        len((audio_result.get("audio_timeline") or {}).get("tracks") or []),
    )

    logger.info(
        "[orch] MCP serial: step 2/2 fetch_assets scenes={}",
        image_scene_ids or "all",
    )
    image_result = await _call_tool_inprocess("fetch_assets", image_args)
    logger.debug(
        "[orch] MCP serial: image done assets={}",
        len((image_result.get("visual_manifest") or {}).get("assets") or []),
    )

    audio_timeline = audio_result.get("audio_timeline") or {}
    image_manifest = image_result.get("visual_manifest") or {}
    return audio_timeline, image_manifest


async def _produce_parallel(
    audio_agent: AudioGenerationAgent,
    image_agent: ScriptImageRetrievalAgent,
    video_plan: Dict[str, Any],
    script_package: Dict[str, Any],
    run_id: str,
    audio_scene_ids: Optional[List[str]] = None,
    image_scene_ids: Optional[List[str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run audio and image fetch concurrently using a thread pool."""
    logger.info(
        "[orch] direct parallel: audio scenes={} | image scenes={}",
        audio_scene_ids or "all",
        image_scene_ids or "all",
    )
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as pool:
        audio_fut = loop.run_in_executor(
            pool,
            lambda: audio_agent.generate_audio_timeline(video_plan, scene_ids=audio_scene_ids),
        )
        image_fut = loop.run_in_executor(
            pool,
            lambda: image_agent.generate_script_image_manifest(
                script_package, scene_ids=image_scene_ids, run_id=run_id
            ),
        )
        audio_result, image_result = await asyncio.gather(audio_fut, image_fut)
    logger.debug(
        "[orch] direct parallel done: audio_tracks={} image_segments={}",
        len(audio_result.get("tracks") or []),
        len(image_result.get("segments") or []),
    )
    return audio_result, image_result


async def _produce_serial(
    audio_agent: AudioGenerationAgent,
    image_agent: ScriptImageRetrievalAgent,
    video_plan: Dict[str, Any],
    script_package: Dict[str, Any],
    run_id: str,
    audio_scene_ids: Optional[List[str]] = None,
    image_scene_ids: Optional[List[str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Run audio then image fetch sequentially (serial mode for deterministic test runs)."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        logger.info(
            "[orch] direct serial: step 1/2 audio scenes={}",
            audio_scene_ids or "all",
        )
        audio_result = await loop.run_in_executor(
            pool,
            lambda: audio_agent.generate_audio_timeline(video_plan, scene_ids=audio_scene_ids),
        )
        logger.debug("[orch] direct serial: audio done tracks={}", len(audio_result.get("tracks") or []))

        logger.info(
            "[orch] direct serial: step 2/2 image scenes={}",
            image_scene_ids or "all",
        )
        image_result = await loop.run_in_executor(
            pool,
            lambda: image_agent.generate_script_image_manifest(
                script_package, scene_ids=image_scene_ids, run_id=run_id
            ),
        )
        logger.debug("[orch] direct serial: image done segments={}", len(image_result.get("segments") or []))
    return audio_result, image_result


class ProductionOrchestrator:
    """Run audio + image production with a structured revision loop.

    Usage::

        orch = ProductionOrchestrator()
        audio_timeline, final_screenplay, final_video_plan = orch.run(
            screenplay=screenplay,
            script_package=script_package,
            video_plan=video_plan,
            run_dir=run_dir,
            screenplay_agent=screenplay_agent_inst,
            voice=voice,
        )
    """

    def run(
        self,
        screenplay: Dict[str, Any],
        script_package: Dict[str, Any],
        video_plan: Dict[str, Any],
        run_dir: Path,
        screenplay_agent: Any,
        voice: str = "narrator",
        use_mcp: bool = False,
        serial: bool = False,
    ) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Execute production with up to MAX_REVISION_ROUNDS revision passes.

        Args:
            screenplay: Screenplay artifact (source of truth for revisions).
            script_package: Pre-derived ScriptPackage (from screenplay).
            video_plan: Pre-derived VideoPlan (from script_package).
            run_dir: Run output directory.
            screenplay_agent: ScreenplayAgent instance with a revise_scene() method.
            voice: TTS voice preset name.
            use_mcp: If True, delegate audio+image to the producer-server MCP process.
            serial: If True, run audio then image sequentially instead of in parallel.
                    Useful for debugging and deterministic test runs.

        Returns:
            Tuple of (audio_timeline, revised_screenplay, revised_video_plan).
        """
        run_id = str(video_plan.get("video_plan_id") or "unknown")
        mode = ("mcp-serial" if serial else "mcp-parallel") if use_mcp else ("serial" if serial else "parallel")

        log_path = Path(run_dir) / "orchestrator.log"
        log_id = logger.add(str(log_path), level="DEBUG", encoding="utf-8")

        logger.info("[orch] run start  run_id={} voice={} mode={}", run_id, voice, mode)
        logger.debug("[orch] run_dir={}", run_dir)

        if use_mcp:
            logger.info("[orch] MCP client mode -- delegating to producer-server")
            _mcp_fn = _produce_serial_mcp if serial else _produce_parallel_mcp
            audio_timeline, image_manifest = asyncio.run(
                _mcp_fn(screenplay, script_package, run_dir, run_id, voice)
            )
        else:
            if TTS_BACKEND == "chatterbox_direct" and not serial:
                raise RuntimeError(
                    "[ERROR] chatterbox_direct backend requires serial=True "
                    "(GPU model is not safe for concurrent inference)"
                )
            audio_agent = create_audio_agent(output_dir=run_dir, voice=voice)
            image_agent = ScriptImageRetrievalAgent(ScriptImageConfig(output_dir=run_dir))

            logger.info("[orch] round 0 -- full production pass ({})", mode)
            self._reset_production_report(run_dir, run_id)

            _direct_fn = _produce_serial if serial else _produce_parallel
            audio_timeline, image_manifest = asyncio.run(
                _direct_fn(audio_agent, image_agent, video_plan, script_package, run_id)
            )

        logger.info(
            "[orch] round 0 complete -- audio_tracks={} image_segments={}",
            len(audio_timeline.get("tracks") or []),
            len(image_manifest.get("segments") or image_manifest.get("assets") or []),
        )

        for round_num in range(1, MAX_REVISION_ROUNDS + 1):
            issues = self._read_production_issues(run_dir)
            degraded = [
                i for i in issues
                if i.get("status") == "degraded" and i.get("revision_possible")
            ]
            if not degraded:
                logger.info("[orch] no degraded scenes after round {}; done", round_num - 1)
                break

            logger.info(
                "[orch] revision round {}/{} -- {} degraded scene(s)",
                round_num,
                MAX_REVISION_ROUNDS,
                len(degraded),
            )

            for issue in degraded:
                scene_id = issue.get("scene_id", "")
                if not scene_id:
                    continue
                logger.info(
                    "[orch]   revising scene={} issue={!r} field={}",
                    scene_id,
                    issue.get("issue", ""),
                    issue.get("revision_field", ""),
                )
                screenplay = screenplay_agent.revise_scene(
                    screenplay,
                    scene_id,
                    issue=issue.get("issue", ""),
                    suggestion=issue.get("suggestion", ""),
                    revision_field=issue.get("revision_field", ""),
                )

            script_package = screenplay_to_script_package(screenplay)
            video_plan = script_package_to_video_plan(script_package)
            run_id = str(video_plan.get("video_plan_id") or run_id)

            audio_scene_ids = [
                i["scene_id"] for i in degraded
                if i.get("revision_field") != "visual"
            ]
            image_scene_ids = [
                i["scene_id"] for i in degraded
                if i.get("revision_field") != "vo_line"
            ]

            logger.info(
                "[orch]   re-running audio={} image={} ({})",
                audio_scene_ids or "skip",
                image_scene_ids or "skip",
                mode,
            )
            self._reset_production_report(run_dir, run_id)

            if use_mcp:
                _mcp_fn = _produce_serial_mcp if serial else _produce_parallel_mcp
                re_audio, re_image = asyncio.run(
                    _mcp_fn(
                        screenplay,
                        script_package,
                        run_dir,
                        run_id,
                        voice,
                        audio_scene_ids=audio_scene_ids or None,
                        image_scene_ids=image_scene_ids or None,
                    )
                )
            else:
                _direct_fn = _produce_serial if serial else _produce_parallel
                re_audio, re_image = asyncio.run(
                    _direct_fn(
                        audio_agent,
                        image_agent,
                        video_plan,
                        script_package,
                        run_id,
                        audio_scene_ids=audio_scene_ids or None,
                        image_scene_ids=image_scene_ids or None,
                    )
                )

            if audio_scene_ids:
                # Merge revised tracks by scene_id into the existing timeline.
                re_tracks_by_scene = {
                    t["scene_id"]: t
                    for t in (re_audio.get("tracks") or [])
                    if t.get("type") == "voiceover" and t.get("scene_id")
                }
                merged_tracks = [
                    re_tracks_by_scene.get(t.get("scene_id"), t)
                    if t.get("type") == "voiceover"
                    else t
                    for t in (audio_timeline.get("tracks") or [])
                ]
                audio_timeline = {**audio_timeline, "tracks": merged_tracks}
                logger.debug("[orch]   audio_timeline merged scenes={}", list(re_tracks_by_scene.keys()))
            if image_scene_ids:
                image_manifest = re_image
                logger.debug("[orch]   image_manifest updated")

            logger.info("[orch] revision round {} complete", round_num)

        scene_results = self._build_scene_results(
            audio_timeline=audio_timeline,
            image_manifest=image_manifest,
            production_issues=self._read_production_issues(run_dir),
        )
        write_json(run_dir / "scene_results.json", {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "scenes": scene_results,
        })

        ok_count = sum(1 for s in scene_results if s.get("status") == "ok")
        logger.info(
            "[orch] run complete  scenes={} ok={} degraded={}",
            len(scene_results),
            ok_count,
            len(scene_results) - ok_count,
        )
        logger.remove(log_id)
        return audio_timeline, screenplay, video_plan

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _reset_production_report(self, run_dir: Path, run_id: str) -> None:
        """Overwrite production_report.json with an empty issues list."""
        write_json(run_dir / "production_report.json", {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "issues": [],
            "degraded_scene_count": 0,
        })

    def _read_production_issues(self, run_dir: Path) -> List[Dict[str, Any]]:
        """Read issues list from production_report.json, returning [] if missing."""
        report_path = run_dir / "production_report.json"
        if not report_path.exists():
            return []
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            return list(data.get("issues") or [])
        except Exception:
            return []

    def _build_scene_results(
        self,
        audio_timeline: Dict[str, Any],
        image_manifest: Dict[str, Any],
        production_issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Summarize per-scene production status from agent outputs."""
        # Index degraded issues by scene_id for quick lookup
        degraded_by_scene: Dict[str, Dict[str, Any]] = {}
        for issue in production_issues:
            sid = issue.get("scene_id", "")
            if sid and issue.get("status") == "degraded":
                degraded_by_scene[sid] = issue

        # Collect known scene_ids from audio timeline
        scene_ids: List[str] = []
        seen: set[str] = set()
        for track in (audio_timeline.get("tracks") or []):
            sid = track.get("scene_id", "")
            if sid and track.get("type") == "voiceover" and sid not in seen:
                scene_ids.append(sid)
                seen.add(sid)

        results: List[Dict[str, Any]] = []
        for sid in scene_ids:
            issue = degraded_by_scene.get(sid)
            results.append({
                "scene_id": sid,
                "status": issue["status"] if issue else "ok",
                "issue": issue.get("issue") if issue else None,
                "revision_field": issue.get("revision_field") if issue else None,
                "revision_possible": issue.get("revision_possible", False) if issue else False,
            })

        return results
