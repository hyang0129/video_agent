"""Full pipeline integration test with Live2D avatar overlay.

Runs the complete pipeline (facts → script → audio → visual → avatar → render)
and produces a human-reviewable MP4 with the majo avatar composited over the
background slideshow.

Skip conditions (checked before any external calls):
  - live2d-render executable not found
  - rhubarb executable not found
  - No LLM API key available (ANTHROPIC_API_KEY or GOOGLE_API_KEY)

Output lands in results/test/ for human review.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from src.config import LIVE2D_RENDER_EXECUTABLE, RHUBARB_EXECUTABLE
from src.full_pipeline_runner import FullPipelineConfig, FullPipelineRunner


_SEEDED_FACTS = [
    "Chewbacca's name comes from a Russian word for dog, inspired by George Lucas's own dog.",
    "Yoda was almost played by a monkey in an early concept before the puppet approach was chosen.",
    "The original film released in 1977 was later retitled Episode IV: A New Hope.",
    "James Earl Jones voiced Darth Vader while David Prowse performed Vader's physical role on set.",
    "The iconic lightsaber hum was created by combining projector motor sounds with TV interference.",
    "R2-D2's name was borrowed from film editing shorthand for Reel 2, Dialog 2.",
]


@pytest.mark.integration
def test_avatar_full_pipeline_produces_composited_video(tmp_path: Path) -> None:
    """Full pipeline with avatar: assert final_video.mp4 and avatar_full.mov both exist."""
    if not Path(LIVE2D_RENDER_EXECUTABLE).exists():
        pytest.skip(f"live2d-render not found: {LIVE2D_RENDER_EXECUTABLE}")
    if not Path(RHUBARB_EXECUTABLE).exists():
        pytest.skip(f"rhubarb not found: {RHUBARB_EXECUTABLE}")
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        pytest.skip("No LLM API key available (set ANTHROPIC_API_KEY or GOOGLE_API_KEY)")
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not found on PATH")

    project_root = Path(__file__).resolve().parents[1]

    config = FullPipelineConfig(
        topic_name="Star Wars",
        topic_query="star wars facts explained",
        topic_id="star_wars_avatar_test",
        subtopic_id="facts",
        angle="Surprising behind-the-scenes facts and universe lore",
        target_duration_seconds=30,
        force_fallback_facts=True,
        fallback_facts=_SEEDED_FACTS,
        voice_mode="auto",
        render_engine="ffmpeg",
        enable_avatar=True,
        output_root=tmp_path,
        output_prefix="avatar_pipeline",
    )

    runner = FullPipelineRunner(project_root=project_root)
    result = runner.run(config=config)

    run_dir = Path(result["run_dir"])

    # --- Final video assertions ---
    final_mp4 = Path(result["final_mp4"])
    assert result["final_mp4_exists"], f"final_video.mp4 not created in {run_dir}"
    assert final_mp4.stat().st_size > 0, "final_video.mp4 is empty"

    # --- Avatar artifact assertions ---
    avatar_takes_dir = run_dir / "avatar_takes"
    assert avatar_takes_dir.exists(), "avatar_takes/ directory not created"

    avatar_manifest_json = run_dir / "avatar_full_manifest.json"
    assert avatar_manifest_json.exists(), "avatar_full_manifest.json not written"

    assert result["avatar_enabled"], "avatar_enabled should be True"
    assert result["avatar_mov_exists"], (
        f"avatar_full.mov not produced. Check {avatar_takes_dir / 'avatar_full.log'} for renderer errors."
    )

    avatar_mov = Path(result["avatar_mov"])
    assert avatar_mov.stat().st_size > 0, "avatar_full.mov is empty"

    lipsync_json = run_dir / "lipsync_manifest.json"
    assert lipsync_json.exists(), "lipsync_manifest.json not written"

    # --- Copy to persistent review directory ---
    review_root = project_root / "results" / "test"
    review_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_dir = review_root / f"avatar_pipeline_{stamp}"
    shutil.copytree(run_dir, review_dir)

    review_mp4 = review_dir / "final_video.mp4"
    review_mov = review_dir / "avatar_takes" / avatar_mov.name

    print()
    print("=" * 60)
    print("AVATAR PIPELINE TEST - HUMAN REVIEW")
    print("=" * 60)
    print(f"RUN_DIR          = {run_dir}")
    print(f"REVIEW_DIR       = {review_dir}")
    print()
    print("Files to review:")
    print(f"  Final video    = {review_mp4}")
    print(f"  Avatar MOV     = {review_mov}")
    print(f"  Render log     = {review_dir / 'avatar_takes' / 'avatar_full.log'}")
    print(f"  Lipsync JSON   = {review_dir / 'lipsync_manifest.json'}")
    print(f"  Avatar manifest= {review_dir / 'avatar_full_manifest.json'}")
    print()
    print("What to check in the final video:")
    print("  - Majo avatar visible in lower-right portrait area")
    print("  - Avatar lip-syncs with voiceover audio")
    print("  - Avatar persists continuously across all scenes (no hard cuts)")
    print("  - Subtitles appear above the avatar")
    print("  - Background images change per scene")
    print("=" * 60)
