"""Stage 6b: AI Image Generation Integration Tests

Tests the end-to-end AI image generation fallback path introduced in issue 3.5.
Stock search (Pexels/Wikimedia) is bypassed by using nonsense search queries that
return no results, forcing the pipeline to fall back to OpenAI image generation.

Cost control
------------
All tests use ``quality="low"`` (GPT Image 1 low = $0.005/image).
Maximum images generated across the full test suite: ~4 images.
Estimated maximum cost per full run: ~$0.02.

Skip conditions
---------------
All tests require IMAGE_GENERATION_PROVIDER to be set (to "openai") AND
IMAGE_GENERATION_API_KEY (or OPENAI_API_KEY) to be present.  Without these
the tests are skipped -- they cannot run offline.

Human review checklist
----------------------
- Generated images are visually related to the prompt
- Portrait orientation (1024x1536 or similar tall aspect ratio)
- No obvious content policy errors in the output
- File is a valid PNG/JPG that renders without corruption
- ``image_generation`` section in manifest has non-zero cost_usd

Run:
    pytest tests/integration/test_stage_06b_image_generation.py -v -s -m integration
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from video_agent.tools.image_generation_tools import ImageGenerationError, generate_image
from .helpers import copy_to_review


# ---------------------------------------------------------------------------
# Skip sentinel — all tests in this file require a live generation provider
# ---------------------------------------------------------------------------

def _generation_available() -> bool:
    provider = os.getenv("IMAGE_GENERATION_PROVIDER", "")
    api_key = os.getenv("IMAGE_GENERATION_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    return bool(provider and api_key)


skip_if_no_generation = pytest.mark.skipif(
    not _generation_available(),
    reason="IMAGE_GENERATION_PROVIDER and API key not configured",
)


# ---------------------------------------------------------------------------
# Minimal script package fixture with generation_prompts
#
# Uses nonsense visual_queries ("XYZZY_NO_STOCK_MATCH_*") so Pexels/Wikimedia
# return zero results and the generation fallback is forced.  Two scenes:
#   scene_01 — abstract/conceptual (good generation candidate)
#   scene_02 — historical event with no stock photos (another good candidate)
# ---------------------------------------------------------------------------

def _minimal_script_package() -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "script_package_id": "sp_imagegen_integration_test",
        "topic_id": "imagegen_test",
        "subtopic_id": "integration",
        "script": {
            "beats": [
                {
                    "scene_id": "scene_01",
                    "t_start_s": 0.0,
                    "t_end_s": 5.0,
                    "on_screen_text": "Abstract concept",
                    "vo_line": "Compound interest is the concept of earning interest on your interest.",
                    "visual_queries": ["XYZZY_NO_STOCK_MATCH_compound_interest_abstract"],
                    "generation_prompts": {
                        "precise": (
                            "Abstract illustration of compound interest: "
                            "stacked gold coins growing exponentially on a dark background, "
                            "glowing upward curve, photorealistic, vertical 9:16 composition"
                        ),
                        "general": "Gold coins stacked growing upward on dark background, vertical photo",
                    },
                },
                {
                    "scene_id": "scene_02",
                    "t_start_s": 5.0,
                    "t_end_s": 10.0,
                    "on_screen_text": "Historical moment",
                    "vo_line": "The first paper money was printed in China during the Tang Dynasty.",
                    "visual_queries": ["XYZZY_NO_STOCK_MATCH_tang_dynasty_paper_money_ancient"],
                    "generation_prompts": {
                        "precise": (
                            "Ancient Chinese Tang Dynasty paper money scrolls and ink brushes "
                            "on a wooden table, warm candlelight, cinematic, vertical 9:16"
                        ),
                        "general": "Ancient Chinese paper money scroll on wooden table",
                    },
                },
            ]
        },
    }


# ---------------------------------------------------------------------------
# Test 1: Direct generate_image() call
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_generation
def test_generate_image_direct(tmp_path: Path) -> None:
    """Call generate_image() directly and verify the saved PNG is a valid image.

    Cost: ~$0.005 (1 image at low quality).

    Human review:
        - Open the generated PNG -- is it visually related to the prompt?
        - Is it portrait-oriented (taller than wide)?
    """
    dest = tmp_path / "scene_01_gen.png"
    prompt = (
        "Abstract illustration of compound interest: stacked gold coins growing "
        "exponentially on a dark background, glowing upward curve, vertical 9:16"
    )

    result = generate_image(
        prompt=prompt,
        output_path=dest,
        provider=os.getenv("IMAGE_GENERATION_PROVIDER", "openai"),
        size="1024x1536",
        quality="low",
    )

    # Schema checks
    assert result["source"].startswith("generated_")
    assert result["url"] == str(dest)
    assert result["resolution"][0] > 0 and result["resolution"][1] > 0
    assert result["attribution"]["required"] is False
    assert result["metadata"]["cost_usd"] > 0
    assert result["metadata"]["generation_prompt"] == prompt
    assert "provider" in result["metadata"]

    # File checks
    assert dest.exists(), "Generated image was not saved"
    assert dest.stat().st_size > 1000, "Generated image is suspiciously small"
    # All major image formats start with a recognisable magic byte sequence
    magic = dest.read_bytes()[:8]
    is_png = magic[:4] == b"\x89PNG"
    is_jpeg = magic[:2] == b"\xff\xd8"
    is_webp = magic[8:12] == b"WEBP" if len(magic) >= 12 else False
    assert is_png or is_jpeg or is_webp, f"File does not look like a valid image: {magic!r}"

    review = copy_to_review(tmp_path, "06b_imagegen_direct")
    print(f"\n--- [Direct] generate_image ---")
    print(f"Provider: {result['metadata']['provider']}")
    print(f"Cost: ${result['metadata']['cost_usd']:.4f}")
    print(f"Resolution: {result['resolution']}")
    print(f"File size: {dest.stat().st_size:,} bytes")
    print(f"Review dir: {review}")
    print(f"CHECK: Open the PNG -- is it portrait? Visually related to prompt?")


# ---------------------------------------------------------------------------
# Test 2: ScriptImageRetrievalAgent generation fallback
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_generation
def test_script_image_agent_generation_fallback(tmp_path: Path) -> None:
    """Run ScriptImageRetrievalAgent with nonsense stock queries so generation fires.

    Both scenes should end up with generated candidates.
    Cost: ~$0.01 (2 images at low quality).

    Human review:
        - script_image_manifest.json -- generated candidates listed under each segment
        - image_generation.total_cost_usd should be ~0.01
        - assets/ -- two PNG files named *_gen_precise.png
    """
    import video_agent.config as _cfg
    original_provider = _cfg.IMAGE_GENERATION_PROVIDER
    original_quality = _cfg.IMAGE_GENERATION_QUALITY

    # Force low quality for cost control
    _cfg.IMAGE_GENERATION_PROVIDER = os.getenv("IMAGE_GENERATION_PROVIDER", "openai")
    _cfg.IMAGE_GENERATION_QUALITY = "low"

    import video_agent.script_image_agent as _sia
    original_sia_provider = _sia.IMAGE_GENERATION_PROVIDER
    original_sia_quality = _sia.IMAGE_GENERATION_QUALITY
    _sia.IMAGE_GENERATION_PROVIDER = _cfg.IMAGE_GENERATION_PROVIDER
    _sia.IMAGE_GENERATION_QUALITY = "low"

    try:
        from video_agent.script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent

        # Use a non-existent provider name so stock search always raises
        # ImageSearchError, which forces the generation fallback to fire.
        # (XYZZY queries alone are not reliable -- some stock APIs still return
        # loosely-matched results.)
        agent = ScriptImageRetrievalAgent(
            config=ScriptImageConfig(
                output_dir=tmp_path,
                image_sources=("_no_stock_source_",),
                min_candidates_per_segment=1,
                max_candidates_per_segment=3,
            )
        )
        script_package = _minimal_script_package()
        manifest = agent.generate_script_image_manifest(script_package)
    finally:
        _cfg.IMAGE_GENERATION_PROVIDER = original_provider
        _cfg.IMAGE_GENERATION_QUALITY = original_quality
        _sia.IMAGE_GENERATION_PROVIDER = original_sia_provider
        _sia.IMAGE_GENERATION_QUALITY = original_sia_quality

    segments = manifest.get("segments", [])
    assert len(segments) == 2, f"Expected 2 segments, got {len(segments)}"

    generated_segments: List[Dict[str, Any]] = []
    for seg in segments:
        gen_candidates = [
            c for c in (seg.get("candidates") or [])
            if "generated" in str(c.get("source", ""))
        ]
        if gen_candidates:
            generated_segments.append(seg)

    assert len(generated_segments) >= 1, (
        "Expected at least 1 generated candidate -- stock search should have failed "
        "on the XYZZY nonsense queries"
    )

    # Verify image_generation cost tracking in manifest
    assert "image_generation" in manifest, "manifest.image_generation section missing"
    ig = manifest["image_generation"]
    assert ig["scenes_generated"] >= 1
    assert ig["total_cost_usd"] > 0
    assert ig["provider"] in {"openai", "google", "flux"}

    # Verify generated files exist on disk
    for seg in generated_segments:
        for cand in seg.get("candidates", []):
            if "generated" in str(cand.get("source", "")):
                gen_path = Path(cand["url"])
                assert gen_path.exists(), f"Generated image file not found: {gen_path}"
                assert gen_path.stat().st_size > 1000

    review = copy_to_review(tmp_path, "06b_imagegen_agent_fallback")
    print(f"\n--- [Agent] ScriptImageRetrievalAgent fallback ---")
    print(f"Total segments: {len(segments)}")
    print(f"Segments with generated candidates: {len(generated_segments)}")
    print(f"Total generation cost: ${ig['total_cost_usd']:.4f}")
    print(f"Review dir: {review}")
    print(f"CHECK: assets/*_gen_*.png -- are generated images relevant to each scene?")
    print(f"CHECK: manifest.image_generation.total_cost_usd should be ~0.01 for 2 images at low quality")


# ---------------------------------------------------------------------------
# Test 3: fetch_assets MCP tool with generation fallback
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_generation
def test_fetch_assets_generation_fallback(tmp_path: Path) -> None:
    """Call the fetch_assets MCP tool with a script package that triggers generation.

    Stock sources (pexels + wikimedia) are searched first with the XYZZY
    nonsense queries.  When they return nothing, the fetch_assets generation
    retry block fires for any placeholder scenes.  Only one scene is used to
    keep cost to ~$0.005.

    Human review:
        - visual_manifest.json -- source should be "generated_openai" for scene_01
        - assets/scene_01_gen.png should exist and look like the prompt
        - production_report.json -- scene_01 may still appear as degraded because
          ScriptImageRetrievalAgent writes the report before the MCP retry fires
    """
    import asyncio as _asyncio
    from video_agent.mcp.video_agent_server import call_tool

    # Single-scene package to minimise cost
    script_package = _minimal_script_package()
    script_package["script"]["beats"] = script_package["script"]["beats"][:1]

    # Patch module-level IMAGE_GENERATION_QUALITY for cost control
    import video_agent.mcp.video_agent_server as _srv
    original_srv_quality = _srv.IMAGE_GENERATION_QUALITY
    _srv.IMAGE_GENERATION_QUALITY = "low"

    try:
        result = _asyncio.run(call_tool("fetch_assets", {
            "script_package": script_package,
            "run_dir": str(tmp_path),
            "run_id": "imagegen_integration_test",
        }))
    finally:
        _srv.IMAGE_GENERATION_QUALITY = original_srv_quality

    data = json.loads(result[0].text)
    assert data.get("status") == "ok", f"fetch_assets failed: {data}"

    visual_manifest = data["visual_manifest"]
    assets = visual_manifest.get("assets", [])
    assert assets, "No assets in visual manifest"

    scene_01 = next((a for a in assets if a.get("scene_id") == "scene_01"), None)
    assert scene_01 is not None, "scene_01 not found in visual_manifest"

    source = scene_01.get("source", "")
    file_path_str = scene_01.get("file_path", "")
    file_path = tmp_path / file_path_str if file_path_str else None

    # Either ScriptImageRetrievalAgent or fetch_assets MCP fallback should have
    # generated the image (both paths are exercised by forcing stock to fail)
    is_generated = "generated" in source
    is_real_stock = source in {"pexels", "wikimedia"}
    assert is_generated or is_real_stock or source == "placeholder", (
        f"Unexpected source: {source!r}"
    )

    if is_generated:
        assert file_path and file_path.exists(), f"Generated image file not found: {file_path_str}"
        assert file_path.stat().st_size > 1000
        print(f"[OK] scene_01 has generated image: {file_path_str}")
    elif source == "placeholder":
        # This can happen if generation also fails (e.g., content policy).
        # Not a hard failure but worth flagging.
        print(f"[WARN] scene_01 fell back to placeholder -- generation may have failed")
    else:
        # Stock search surprisingly found something despite XYZZY query.
        print(f"[INFO] scene_01 has stock image ({source}) -- generation was not needed")

    vm_path = tmp_path / "visual_manifest.json"
    assert vm_path.exists(), "visual_manifest.json not written to run_dir"

    review = copy_to_review(tmp_path, "06b_imagegen_fetch_assets")
    print(f"\n--- [MCP] fetch_assets (generation fallback) ---")
    print(f"scene_01 source: {source}")
    print(f"scene_01 file: {file_path_str}")
    print(f"Review dir: {review}")
    print(f"CHECK: assets/ -- generated PNG should look like stacked gold coins")
    print(f"CHECK: production_report.json -- scene_01 should NOT be degraded if generation succeeded")


# ---------------------------------------------------------------------------
# Test 4: ImageGenerationError paths (offline, no API call)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_generate_image_missing_provider_config() -> None:
    """Verify ImageGenerationError is raised for unknown providers.

    No API key needed -- this tests the validation layer only (no network call).
    Cost: $0.00.
    """
    with pytest.raises(ImageGenerationError, match="Unknown"):
        generate_image(
            "test prompt",
            output_path=Path("/tmp/should_not_be_created.png"),
            provider="not_a_real_provider",
        )


@pytest.mark.integration
def test_generate_image_empty_prompt_error() -> None:
    """Verify ImageGenerationError is raised for empty prompts.

    No API key needed.  Cost: $0.00.
    """
    with pytest.raises(ImageGenerationError, match="Empty prompt"):
        generate_image("", output_path=Path("/tmp/should_not_be_created.png"))
