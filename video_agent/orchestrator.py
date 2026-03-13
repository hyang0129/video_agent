"""Production orchestrator with scene-level revision loop.

Manages the audio + image production pass for a screenplay run.
When agents report degraded scenes the orchestrator revises the screenplay
and re-runs only the affected agents (max MAX_REVISION_ROUNDS rounds).

Outputs written to run_dir:
- production_report.json  - combined structured failures from all agents
- scene_results.json      - per-scene production status after final round

MCP mode:
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
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .artifacts.io import write_json
from .artifacts.screenplay import screenplay_to_script_package
from .config import TTS_BACKEND
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


async def _produce_parallel(
    screenplay: Dict[str, Any],
    script_package: Dict[str, Any],
    run_dir: Path,
    run_id: str,
    voice: str,
    audio_scene_ids: Optional[List[str]] = None,
    image_scene_ids: Optional[List[str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, float]]:
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
    tool_timings = {
        "generate_audio": audio_result.get("elapsed_seconds", 0.0),
        "fetch_assets": image_result.get("elapsed_seconds", 0.0),
    }
    logger.debug(
        "[orch] MCP parallel done: audio_tracks={} image_assets={}",
        len(audio_timeline.get("tracks") or []),
        len(image_manifest.get("assets") or []),
    )
    return audio_timeline, image_manifest, tool_timings


async def _produce_serial(
    screenplay: Dict[str, Any],
    script_package: Dict[str, Any],
    run_dir: Path,
    run_id: str,
    voice: str,
    audio_scene_ids: Optional[List[str]] = None,
    image_scene_ids: Optional[List[str]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, float]]:
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
    tool_timings = {
        "generate_audio": audio_result.get("elapsed_seconds", 0.0),
        "fetch_assets": image_result.get("elapsed_seconds", 0.0),
    }
    return audio_timeline, image_manifest, tool_timings


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
            serial: If True, run audio then image sequentially instead of in parallel.
                    Useful for debugging and deterministic test runs.

        Returns:
            Tuple of (audio_timeline, revised_screenplay, revised_video_plan).
        """
        run_id = str(video_plan.get("video_plan_id") or "unknown")
        mode = "mcp-serial" if serial else "mcp-parallel"

        log_path = Path(run_dir) / "orchestrator.log"
        log_id = logger.add(str(log_path), level="DEBUG", encoding="utf-8")

        logger.info("[orch] run start  run_id={} voice={} mode={}", run_id, voice, mode)
        logger.debug("[orch] run_dir={}", run_dir)

        run_t0 = time.monotonic()
        tool_timings: Dict[str, float] = {}
        revision_timings: List[Dict[str, Any]] = []

        production_t0 = time.monotonic()
        _produce_fn = _produce_serial if serial else _produce_parallel
        logger.info("[orch] round 0 -- full production pass ({})", mode)
        self._reset_production_report(run_dir, run_id)
        audio_timeline, image_manifest, tool_timings = asyncio.run(
            _produce_fn(screenplay, script_package, run_dir, run_id, voice)
        )
        production_elapsed_s = round(time.monotonic() - production_t0, 2)

        logger.info(
            "[orch] round 0 complete -- audio_tracks={} image_segments={} elapsed={:.1f}s",
            len(audio_timeline.get("tracks") or []),
            len(image_manifest.get("segments") or image_manifest.get("assets") or []),
            production_elapsed_s,
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

            round_t0 = time.monotonic()
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

            re_audio, re_image, _rev_timings = asyncio.run(
                _produce_fn(
                    screenplay,
                    script_package,
                    run_dir,
                    run_id,
                    voice,
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

            round_elapsed_s = round(time.monotonic() - round_t0, 2)
            revision_timings.append({
                "round": round_num,
                "elapsed_s": round_elapsed_s,
                "scenes_revised": len(degraded),
            })
            logger.info("[orch] revision round {} complete ({:.1f}s)", round_num, round_elapsed_s)

        total_elapsed_s = round(time.monotonic() - run_t0, 2)

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
        degraded_count = len(scene_results) - ok_count

        # Write timing-enriched production report
        write_json(run_dir / "production_report.json", {
            "schema_version": "1.1.0",
            "run_id": run_id,
            "mode": mode,
            "total_elapsed_s": total_elapsed_s,
            "production_elapsed_s": production_elapsed_s,
            "tool_timings": tool_timings,
            "revision_rounds": revision_timings,
            "issues": self._read_production_issues(run_dir),
            "degraded_scene_count": degraded_count,
        })

        # Update rolling metrics summary
        from .metrics import update_metrics_summary
        from .config import RESULTS_DIR
        stage_timings = {**tool_timings, "production_total": production_elapsed_s}
        update_metrics_summary(
            metrics_path=RESULTS_DIR / "metrics_summary.json",
            run_id=run_id,
            run_duration_s=total_elapsed_s,
            stage_timings=stage_timings,
            passed=(degraded_count == 0),
            mode=mode,
        )

        logger.info(
            "[orch] run complete  scenes={} ok={} degraded={} elapsed={:.1f}s",
            len(scene_results),
            ok_count,
            degraded_count,
            total_elapsed_s,
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
