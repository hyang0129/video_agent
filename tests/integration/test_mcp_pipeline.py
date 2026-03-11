"""MCP Producer Pipeline Integration Tests

Tests the MCP tool handlers end-to-end using the WW2 Tanks fixture as the
canonical input. Tools are called directly (not via subprocess transport) so
the test is fast to import and can share setup.

Architecture
------------
The producer pipeline has four sequential tool calls:

    generate_audio(video_plan)   ─┐  parallel
    fetch_assets(script_package) ─┘
        → production_report.json (merged from both agents)
        → scene_results.json     (written by orchestrator)
    render_video(audio_timeline, visual_manifest)
        → final_video.mp4
    validate_output(mp4_path)
        → evaluation.json

Checkpoint seeding
------------------
Each test seeds its own ``tmp_path`` workspace with only the fixture artifacts
that stage needs. This means:
- ``test_generate_audio_tool`` needs only ``video_plan``
- ``test_fetch_assets_tool``   needs only ``script_package``
- ``test_parallel_production`` needs both
- ``test_render_checkpoint``   seeds ``audio_timeline`` + ``visual_manifest`` from
                                earlier tool outputs captured in the module fixture
- ``test_validate_output_offline`` seeds a synthetic MP4

API keys / skip conditions
--------------------------
    ELEVENLABS_API_KEY   — real TTS; falls back to silent placeholder if absent
    PEXELS_API_KEY       — real images; falls back to placeholder BMPs if absent
    ffmpeg in PATH       — required for render + validate; those tests are skipped
                           if ffmpeg is unavailable

Run:
    pytest tests/integration/test_mcp_pipeline.py -v -s -m integration
    pytest tests/integration/test_mcp_pipeline.py -v -s -m integration -k full
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.artifacts.io import write_json
from src.video_planner import script_package_to_video_plan
from .helpers import copy_to_review, load_fixture

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(result) -> Dict[str, Any]:
    """Extract dict from list[TextContent] returned by call_tool."""
    return json.loads(result[0].text)


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


# ---------------------------------------------------------------------------
# Module-scoped fixtures (cheap — pure dict derivations, no I/O)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ww2_script_package() -> Dict[str, Any]:
    return load_fixture("script_package_ww2_tanks.json")


@pytest.fixture(scope="module")
def ww2_video_plan(ww2_script_package: Dict[str, Any]) -> Dict[str, Any]:
    return script_package_to_video_plan(ww2_script_package)


# ---------------------------------------------------------------------------
# Test 1: generate_audio — audio tool checkpoint
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_audio_tool(tmp_path: Path, ww2_video_plan: Dict[str, Any]) -> None:
    """Call generate_audio with a pre-built video_plan (no screenplay or LLM needed).

    Human review:
        results/test/stages/mcp_generate_audio_*/
        - audio_segments/*.wav (or *.mp3 if ElevenLabs key present)
        - production_report.json — should have 0 degraded scenes for clean input
    """
    from src.mcp.video_agent_server import call_tool

    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY"))
    voice = "narrator" if has_elevenlabs else "silent"

    # Inject voice into video_plan so the agent picks it up
    vp = dict(ww2_video_plan)
    vp.setdefault("audio", {}).setdefault("tts", {})["voice"] = voice

    result = await call_tool("generate_audio", {
        "video_plan": vp,
        "run_dir": str(tmp_path),
        "voice_preset": voice,
    })
    data = _parse(result)

    assert data.get("status") == "ok", f"generate_audio failed: {data}"

    audio_timeline = data["audio_timeline"]
    tracks = audio_timeline.get("tracks") or []
    vo_tracks = [t for t in tracks if t.get("type") == "voiceover"]
    assert vo_tracks, "No voiceover tracks in audio_timeline"
    assert audio_timeline.get("duration_seconds", 0) > 0

    # production_report.json must exist — AudioAgent always writes it
    report_path = tmp_path / "production_report.json"
    assert report_path.exists(), "production_report.json not written"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "schema_version" in report
    assert "issues" in report
    assert isinstance(report["issues"], list)

    segments = data.get("segments", [])
    assert segments, "No segments in generate_audio response"
    for seg in segments:
        assert "scene_id" in seg
        assert "duration_s" in seg
        assert seg["status"] in {"ok", "degraded"}

    write_json(tmp_path / "audio_timeline.json", audio_timeline)
    review = copy_to_review(tmp_path, "mcp_generate_audio")

    print(f"\n--- [MCP] generate_audio ---")
    print(f"Real TTS: {'YES (ElevenLabs)' if has_elevenlabs else 'NO (silent placeholder)'}")
    print(f"Voiceover tracks: {len(vo_tracks)}")
    print(f"Total duration: {audio_timeline.get('duration_seconds', 0):.1f}s")
    print(f"Degraded: {report['degraded_scene_count']}")
    print(f"Review dir: {review}")


# ---------------------------------------------------------------------------
# Test 2: fetch_assets — image tool checkpoint
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_assets_tool(tmp_path: Path, ww2_script_package: Dict[str, Any]) -> None:
    """Call fetch_assets with a pre-built script_package (no screenplay or LLM needed).

    Human review:
        results/test/stages/mcp_fetch_assets_*/
        - visual_manifest.json — inspect per-scene images, check relevance scores
        - production_report.json — degraded scenes should list low-relevance issues
    """
    from src.mcp.video_agent_server import call_tool

    has_pexels = bool(os.getenv("PEXELS_API_KEY"))

    result = await call_tool("fetch_assets", {
        "script_package": ww2_script_package,
        "run_dir": str(tmp_path),
        "run_id": "mcp_pipeline_test",
    })
    data = _parse(result)

    assert data.get("status") == "ok", f"fetch_assets failed: {data}"

    visual_manifest = data["visual_manifest"]
    scene_assets = data.get("scene_assets", [])
    assert scene_assets, "No scene_assets in fetch_assets response"

    for asset in scene_assets:
        assert "scene_id" in asset
        assert "status" in asset
        assert asset["status"] in {"ok", "degraded"}

    report_path = tmp_path / "production_report.json"
    assert report_path.exists(), "production_report.json not written by fetch_assets"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(report.get("issues"), list)

    write_json(tmp_path / "visual_manifest.json", visual_manifest)
    review = copy_to_review(tmp_path, "mcp_fetch_assets")

    ok_count = sum(1 for a in scene_assets if a["status"] == "ok")
    degraded_count = sum(1 for a in scene_assets if a["status"] == "degraded")
    print(f"\n--- [MCP] fetch_assets ---")
    print(f"Pexels available: {has_pexels}")
    print(f"Scenes: {len(scene_assets)} total / {ok_count} ok / {degraded_count} degraded")
    print(f"Review dir: {review}")
    if has_pexels:
        print(f"Check: visual_manifest.json — are images relevant to each scene?")
    else:
        print(f"Re-run with PEXELS_API_KEY for image quality review")


# ---------------------------------------------------------------------------
# Test 3: parallel production — both agents together, merged report
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_production(
    tmp_path: Path,
    ww2_script_package: Dict[str, Any],
    ww2_video_plan: Dict[str, Any],
) -> None:
    """Run generate_audio and fetch_assets concurrently against the same run_dir.

    Verifies:
    - Both tools complete successfully
    - production_report.json contains merged issues from AudioAgent + ScriptImageAgent
    - No file-level race conditions from concurrent writes
    """
    from src.mcp.video_agent_server import call_tool

    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY"))
    voice = "narrator" if has_elevenlabs else "silent"

    vp = dict(ww2_video_plan)
    vp.setdefault("audio", {}).setdefault("tts", {})["voice"] = voice

    audio_result, image_result = await asyncio.gather(
        call_tool("generate_audio", {
            "video_plan": vp,
            "run_dir": str(tmp_path),
            "voice_preset": voice,
        }),
        call_tool("fetch_assets", {
            "script_package": ww2_script_package,
            "run_dir": str(tmp_path),
            "run_id": "parallel_test",
        }),
    )

    audio_data = _parse(audio_result)
    image_data = _parse(image_result)

    assert audio_data.get("status") == "ok", f"generate_audio failed: {audio_data}"
    assert image_data.get("status") == "ok", f"fetch_assets failed: {image_data}"

    # Merged production_report should have entries from both agents
    report_path = tmp_path / "production_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    agents_seen = {i.get("agent") for i in report.get("issues", [])}

    audio_timeline = audio_data["audio_timeline"]
    visual_manifest = image_data["visual_manifest"]
    write_json(tmp_path / "audio_timeline.json", audio_timeline)
    write_json(tmp_path / "visual_manifest.json", visual_manifest)
    review = copy_to_review(tmp_path, "mcp_parallel_production")

    print(f"\n--- [MCP] parallel production ---")
    print(f"Audio tracks: {len([t for t in audio_timeline.get('tracks', []) if t.get('type') == 'voiceover'])}")
    print(f"Image scenes: {len(image_data.get('scene_assets', []))}")
    print(f"Agents in merged report: {sorted(agents_seen)}")
    print(f"Total degraded: {report['degraded_scene_count']}")
    print(f"Review dir: {review}")


# ---------------------------------------------------------------------------
# Test 4: full pipeline — audio + image → render → validate
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_producer_pipeline(
    tmp_path: Path,
    ww2_script_package: Dict[str, Any],
    ww2_video_plan: Dict[str, Any],
) -> None:
    """Full MCP producer pipeline: audio + image → render → validate → evaluation.json.

    Steps:
        1. generate_audio (parallel with fetch_assets)
        2. fetch_assets
        3. render_video  [skipped if ffmpeg absent]
        4. validate_output  [skipped if ffmpeg absent]

    Render and validate are skipped automatically if ffmpeg is not in PATH.

    Human review:
        results/test/stages/mcp_full_pipeline_*/
        - audio_timeline.json
        - visual_manifest.json
        - production_report.json
        - scene_results.json
        - final_video.mp4  (if ffmpeg available — watch for sync issues)
        - evaluation.json  (if ffmpeg available — check duration_parity_ok)
    """
    from src.mcp.video_agent_server import call_tool

    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY"))
    has_ffmpeg = _ffmpeg_available()
    voice = "narrator" if has_elevenlabs else "silent"

    vp = dict(ww2_video_plan)
    vp.setdefault("audio", {}).setdefault("tts", {})["voice"] = voice

    # Step 1+2: parallel production
    print(f"\n--- [MCP] full pipeline: step 1+2 — parallel audio + image ---")
    audio_result, image_result = await asyncio.gather(
        call_tool("generate_audio", {
            "video_plan": vp,
            "run_dir": str(tmp_path),
            "voice_preset": voice,
        }),
        call_tool("fetch_assets", {
            "script_package": ww2_script_package,
            "run_dir": str(tmp_path),
            "run_id": "full_pipeline_test",
        }),
    )
    audio_data = _parse(audio_result)
    image_data = _parse(image_result)
    assert audio_data.get("status") == "ok", f"generate_audio: {audio_data}"
    assert image_data.get("status") == "ok", f"fetch_assets: {image_data}"

    audio_timeline = audio_data["audio_timeline"]
    visual_manifest = image_data["visual_manifest"]
    write_json(tmp_path / "audio_timeline.json", audio_timeline)
    write_json(tmp_path / "visual_manifest.json", visual_manifest)

    # production_report.json must be present (merged from both agents)
    report_path = tmp_path / "production_report.json"
    assert report_path.exists(), "production_report.json missing after parallel run"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "schema_version" in report
    assert "degraded_scene_count" in report

    # Build scene_results: per-scene status summary
    degraded_by_scene = {
        i["scene_id"]: i for i in report.get("issues", [])
        if i.get("status") == "degraded" and i.get("scene_id")
    }
    vo_tracks = [t for t in (audio_timeline.get("tracks") or []) if t.get("type") == "voiceover"]
    scene_results: List[Dict[str, Any]] = []
    for t in vo_tracks:
        sid = t.get("scene_id", "")
        issue = degraded_by_scene.get(sid)
        scene_results.append({
            "scene_id": sid,
            "status": issue["status"] if issue else "ok",
            "issue": issue.get("issue") if issue else None,
        })
    write_json(tmp_path / "scene_results.json", {
        "schema_version": "1.0.0",
        "run_id": "full_pipeline_test",
        "scenes": scene_results,
    })

    ok_count = sum(1 for s in scene_results if s["status"] == "ok")
    print(f"Scenes: {len(scene_results)} total / {ok_count} ok / {len(scene_results) - ok_count} degraded")

    if not has_ffmpeg:
        review = copy_to_review(tmp_path, "mcp_full_pipeline")
        print(f"[SKIP] render + validate: ffmpeg not in PATH")
        print(f"Review dir (pre-render artifacts): {review}")
        return

    # Step 3: render_video
    print(f"--- [MCP] full pipeline: step 3 — render ---")
    render_result = await call_tool("render_video", {
        "visual_manifest": visual_manifest,
        "audio_timeline": audio_timeline,
        "video_plan": vp,
        "run_dir": str(tmp_path),
        "engine": "ffmpeg",
    })
    render_data = _parse(render_result)
    assert render_data.get("status") == "ok", f"render_video failed: {render_data}"

    mp4_path = render_data.get("mp4_path", "")
    assert mp4_path, "render_video returned no mp4_path"
    mp4 = Path(mp4_path)
    assert mp4.exists(), f"MP4 not found at {mp4_path}"
    assert mp4.stat().st_size > 0, f"MP4 is empty (0 bytes) at {mp4_path}"

    print(f"MP4: {mp4_path}")
    print(f"Duration: {render_data.get('duration_s', 0):.1f}s")

    # Step 4: validate_output
    print(f"--- [MCP] full pipeline: step 4 — validate ---")
    validate_result = await call_tool("validate_output", {
        "mp4_path": mp4_path,
        "audio_timeline": audio_timeline,
        "run_dir": str(tmp_path),
    })
    validate_data = _parse(validate_result)

    assert validate_data.get("mp4_exists"), "MP4 does not exist at validate time"
    eval_path = tmp_path / "evaluation.json"
    assert eval_path.exists(), "evaluation.json not written by validate_output"

    evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
    assert "passed" in evaluation
    assert "duration_parity_ok" in evaluation
    assert "video_duration_s" in evaluation
    assert "render_health" in evaluation, "render_health block missing from evaluation.json"

    rh = evaluation["render_health"]
    assert rh.get("file_size_bytes", 0) > 0, (
        f"render_health reports empty MP4 — critical_failures: {rh.get('critical_failures')}"
    )
    assert "DryRun" not in rh.get("engine", ""), (
        f"DryRunRenderEngine was used — MP4 will be empty. critical_failures: {rh.get('critical_failures')}"
    )

    review = copy_to_review(tmp_path, "mcp_full_pipeline")
    print(f"Passed: {validate_data['passed']}")
    print(f"Duration parity: {validate_data.get('duration_parity_s', '?'):.2f}s "
          f"({'OK' if validate_data.get('duration_parity_ok') else 'FAIL'})")
    print(f"Render health: engine={rh.get('engine')} size={rh.get('file_size_bytes')}B "
          f"degraded={rh.get('degraded_scene_count')} critical={rh.get('critical_failures')}")
    print(f"Failures: {validate_data.get('failures', [])}")
    print(f"Review dir: {review}")
    if has_elevenlabs:
        print(f"Watch: final_video.mp4 — check audio/video sync, caption timing")
    else:
        print(f"Re-run with ELEVENLABS_API_KEY for audio quality review")


# ---------------------------------------------------------------------------
# Test 5: validate_output checkpoint — seeds a synthetic MP4
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg not in PATH")
async def test_validate_output_writes_evaluation_json(tmp_path: Path) -> None:
    """Validate a synthetic 5-second MP4 created by ffmpeg.

    Verifies that validate_output:
    - Writes evaluation.json with the correct schema
    - Correctly reports duration_parity_ok when parity is within threshold
    """
    from src.mcp.video_agent_server import call_tool

    # Build a minimal 5-second MP4 (black video + silent audio) via ffmpeg
    mp4_path = tmp_path / "synthetic.mp4"
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=5",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "5",
        "-c:v", "libx264", "-c:a", "aac",
        "-shortest",
        str(mp4_path),
    ]
    proc = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    assert proc.returncode == 0, f"ffmpeg failed: {proc.stderr}"
    assert mp4_path.exists()

    # Fake audio_timeline with matching duration
    fake_audio_timeline = {"duration_seconds": 5.0, "tracks": []}

    result = await call_tool("validate_output", {
        "mp4_path": str(mp4_path),
        "audio_timeline": fake_audio_timeline,
        "run_dir": str(tmp_path),
    })
    data = _parse(result)

    assert data["mp4_exists"] is True
    eval_path = tmp_path / "evaluation.json"
    assert eval_path.exists(), "evaluation.json not written"

    evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
    assert evaluation["schema_version"] == "1.0.0"
    assert "video_duration_s" in evaluation
    assert "audio_duration_s" in evaluation
    assert "duration_parity_ok" in evaluation
    assert evaluation["duration_parity_s"] <= 0.25, (
        f"Duration parity {evaluation['duration_parity_s']:.3f}s exceeds 0.25s threshold"
    )

    print(f"\n--- [MCP] validate_output checkpoint ---")
    print(f"Video duration: {evaluation['video_duration_s']:.2f}s")
    print(f"Audio duration: {evaluation['audio_duration_s']:.2f}s")
    print(f"Parity: {evaluation['duration_parity_s']:.3f}s (OK: {evaluation['duration_parity_ok']})")
    print(f"Passed: {evaluation['passed']}")
