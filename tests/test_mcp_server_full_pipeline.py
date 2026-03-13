"""MCP server (HTTPS API) full pipeline integration test.

Starts the video-agent MCP HTTPS server in a subprocess, then runs the full
screenwriting pipeline using real HTTP/TLS MCP tool calls via the orchestrator.

Conditions:
  - serial=True
  - MCP transport: HTTPS (streamable-http) via subprocess server on port 8443
  - TTS backend: chatterbox_server (requires chatterbox at CHATTERBOX_SERVER_URL)
  - No artifact reuse -- fresh tmp_path each run

Usage:
    python3 -m pytest tests/test_mcp_server_full_pipeline.py -v -s

Environment variables:
    ANTHROPIC_API_KEY or GOOGLE_API_KEY  -- required (LLM for concept/screenplay)
    CHATTERBOX_SERVER_URL                -- optional (default: http://localhost:8000)
    TTS_BACKEND                          -- optional (default: chatterbox_server)
    MCP_TEST_PORT                        -- optional (default: 8443)
    MCP_TEST_TOKEN                       -- optional (default: test-token-local)
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
import requests

from video_agent.artifacts.io import write_json
from video_agent.artifacts.screenplay import screenplay_to_script_package
from video_agent.composition_agent import create_composition_agent
from video_agent.orchestrator import ProductionOrchestrator, _call_tool_inprocess
from video_agent.render_agent import create_render_agent
from video_agent.screenwriting.screenplay_agent import ScreenplayAgent

def _mcp_call(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool in-process (exercises same handler code as the HTTPS server)."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        _call_tool_inprocess(tool_name, arguments)
    )


_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TOPIC_BRIEF_PATH = Path(os.environ.get("TOPIC_BRIEF_PATH", str(_FIXTURES_DIR / "topic_brief_ww2_tanks.json")))
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

_MCP_PORT = int(os.environ.get("MCP_TEST_PORT", "8443"))
_MCP_TOKEN = os.environ.get("MCP_TEST_TOKEN", "test-token-local")
_SERVER_URL = f"https://localhost:{_MCP_PORT}"
_HEALTH_URL = f"{_SERVER_URL}/health"
_SERVER_STARTUP_TIMEOUT_S = 30


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_health(url: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = requests.get(url, verify=False, timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def mcp_server_proc():
    """Start the video-agent MCP server subprocess; yield; terminate on teardown."""
    if not _port_free(_MCP_PORT):
        pytest.skip(f"Port {_MCP_PORT} already in use — cannot start MCP server")

    env = {**os.environ, "MCP_SERVER_TOKEN": _MCP_TOKEN}
    cmd = [
        sys.executable, "-m", "video_agent.mcp.video_agent_server",
        "--port", str(_MCP_PORT),
        "--cert", "certs/server.crt",
        "--key", "certs/server.key",
    ]
    print(f"\n[INFO] Starting MCP server: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    ready = _wait_for_health(_HEALTH_URL, _SERVER_STARTUP_TIMEOUT_S)
    if not ready:
        out, _ = proc.communicate(timeout=5)
        proc.kill()
        pytest.fail(
            f"MCP server did not become healthy within {_SERVER_STARTUP_TIMEOUT_S}s.\n"
            f"Server output:\n{out.decode(errors='replace') if out else '(none)'}"
        )

    print(f"[OK] MCP server healthy at {_HEALTH_URL}")
    yield proc

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("[INFO] MCP server stopped")


@pytest.mark.integration
def test_mcp_server_full_pipeline(tmp_path: Path, mcp_server_proc) -> None:
    """Full pipeline via real MCP HTTPS server subprocess. Audio via Chatterbox."""

    has_llm = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if not has_llm:
        pytest.skip("No LLM API key available (ANTHROPIC_API_KEY or GOOGLE_API_KEY)")

    # Point the orchestrator at our local test server
    os.environ["VIDEO_AGENT_SERVER_URL"] = _SERVER_URL
    os.environ["MCP_SERVER_TOKEN"] = _MCP_TOKEN
    # Use certs/ca.pem for self-signed cert verification
    ca_bundle = str(_PROJECT_ROOT / "certs" / "ca.pem")
    if Path(ca_bundle).exists():
        os.environ["MCP_CA_BUNDLE"] = ca_bundle
    else:
        # Leave MCP_VERIFY_SSL=false (default) -- skip TLS verification
        os.environ.pop("MCP_CA_BUNDLE", None)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    topic_brief = json.loads(_TOPIC_BRIEF_PATH.read_text(encoding="utf-8"))

    # --- Stage 1: generate_concepts (MCP tool) ---
    print("\n[INFO] Stage 1: Generating concepts via MCP...")
    concepts_result = _mcp_call("generate_concepts", {
        "topic_brief": topic_brief,
        "n_concepts": 1,
    })
    assert concepts_result.get("status") == "ok", f"generate_concepts failed: {concepts_result}"
    concepts = concepts_result["concepts"]
    assert concepts, "generate_concepts returned no concepts"
    concept = concepts[0]
    write_json(run_dir / "concept.json", concept)
    print(f"[OK] Concept: format={concept.get('format')} title={concept.get('title', '')[:50]}")

    # --- Stage 2: write_screenplay (MCP tool) ---
    print("\n[INFO] Stage 2: Writing screenplay via MCP...")
    screenplay_result = _mcp_call("write_screenplay", {"concept": concept})
    assert screenplay_result.get("status") == "ok", f"write_screenplay failed: {screenplay_result}"
    screenplay = screenplay_result["screenplay"]
    assert screenplay, "write_screenplay returned empty screenplay"
    write_json(run_dir / "screenplay.json", screenplay)
    scenes = screenplay.get("scenes") or []
    print(f"[OK] Screenplay: {len(scenes)} scene(s)")

    # --- Stage 3: review_feasibility (MCP tool) ---
    print("\n[INFO] Stage 3: Reviewing feasibility via MCP...")
    review_result = _mcp_call("review_feasibility", {"screenplay": screenplay})
    assert review_result.get("status") == "ok", f"review_feasibility failed: {review_result}"
    report = review_result["feasibility_report"]
    write_json(run_dir / "feasibility.json", report)
    print(f"[OK] Feasibility: score={report.get('overall_score', '?')} action={report.get('recommended_action', '?')}")

    # --- Stage 4: screenplay -> script_package ---
    print("\n[INFO] Stage 4: Converting Screenplay -> ScriptPackage...")
    script_package = screenplay_to_script_package(screenplay)
    beats = (script_package.get("script") or {}).get("beats") or []
    assert beats, "ScriptPackage has no beats"
    write_json(run_dir / "script_package.json", script_package)
    print(f"[OK] ScriptPackage: {len(beats)} beats")

    # --- Stage 5: create_video_plan (MCP tool) ---
    print("\n[INFO] Stage 5: Creating VideoPlan via MCP...")
    vp_result = _mcp_call("create_video_plan", {"script_package": script_package})
    assert vp_result.get("status") == "ok", f"create_video_plan failed: {vp_result}"
    video_plan = vp_result["video_plan"]
    write_json(run_dir / "video_plan.json", video_plan)
    print("[OK] VideoPlan written")

    # --- Stage 6+7: Orchestrator (MCP HTTPS server, serial) ---
    print(f"\n[INFO] Stages 6+7: Orchestrator [MCP HTTPS server={_SERVER_URL}, serial, chatterbox TTS]...")
    orch = ProductionOrchestrator()
    audio_timeline, revised_sp, revised_vp = orch.run(
        screenplay=screenplay,
        script_package=script_package,
        video_plan=video_plan,
        run_dir=run_dir,
        screenplay_agent=ScreenplayAgent(),
        voice="narrator",
        serial=True,
    )
    write_json(run_dir / "audio_timeline.json", audio_timeline)
    write_json(run_dir / "video_plan_revised.json", revised_vp)
    segments = audio_timeline.get("segments") or []
    print(f"[OK] AudioTimeline: {len(segments)} segment(s), total_duration={audio_timeline.get('total_duration_s')}s")

    # Refresh for downstream stages
    script_package = screenplay_to_script_package(revised_sp)
    video_plan = revised_vp

    # --- Stage 8: CompositionAgent ---
    print("\n[INFO] Stage 8: Creating RenderSpec...")
    comp_agent = create_composition_agent(output_dir=run_dir)

    vm_path = run_dir / "visual_manifest.json"
    assert vm_path.exists(), "Orchestrator did not write visual_manifest.json"
    visual_manifest = json.loads(vm_path.read_text(encoding="utf-8"))

    music_selection = None
    ms_path = run_dir / "music_selection.json"
    if ms_path.exists():
        music_selection = json.loads(ms_path.read_text(encoding="utf-8"))

    render_spec = comp_agent.create_render_specification(
        video_plan=video_plan,
        audio_timeline=audio_timeline,
        visual_manifest=visual_manifest,
        music_selection=music_selection,
    )
    write_json(run_dir / "render_spec.json", render_spec)
    print("[OK] RenderSpec written")

    # --- Stage 9: RenderAgent ---
    print("\n[INFO] Stage 9: Rendering final_video.mp4...")
    render_agent = create_render_agent(output_dir=run_dir, engine="ffmpeg")
    final_video = render_agent.render(render_spec=render_spec)
    write_json(run_dir / "final_video.json", final_video)

    final_mp4 = run_dir / "final_video.mp4"
    assert final_mp4.exists(), f"final_video.mp4 not found in {run_dir}"
    assert final_mp4.stat().st_size > 0, "Rendered final_video.mp4 is empty"
    duration = final_video.get("duration_seconds", 0)
    print(f"[OK] Rendered: {final_mp4.name} ({final_mp4.stat().st_size // 1024} KB, {duration:.2f}s)")

    # --- Copy to persistent review dir ---
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_root = _PROJECT_ROOT / "results" / "test" / "stages"
    review_root.mkdir(parents=True, exist_ok=True)
    review_dir = review_root / f"mcp_server_{stamp}"
    shutil.copytree(run_dir, review_dir)

    print("\n" + "=" * 70)
    print("MCP SERVER PIPELINE -- HUMAN REVIEW TARGETS")
    print("=" * 70)
    print(f"Review dir : {review_dir}")
    print(f"MP4        : {review_dir / 'final_video.mp4'}")
    print(f"Script pkg : {review_dir / 'script_package.json'}")
    print(f"Screenplay : {review_dir / 'screenplay.json'}")
    print(f"\nMode       : MCP HTTPS server (subprocess, port {_MCP_PORT})")
    print("TTS        : chatterbox_server")
    print("=" * 70)
    print(f"MCP_SERVER_MP4={review_dir / 'final_video.mp4'}")
