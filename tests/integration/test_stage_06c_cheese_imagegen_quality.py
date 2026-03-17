"""Stage 6c: Cheese fixture -- AI image generation + alignment quality review

End-to-end integration test using the cheese_facts fixture:
  1. ScriptImageRetrievalAgent runs with _no_stock_source_ so all 6 scenes
     fall back to OpenAI GPT Image 1 generation.
  2. ImageAlignmentEvaluator scores each generated image against its scene
     context using a vision LLM (Claude Haiku or Gemini Flash).
  3. All images + a scored summary JSON are written to the review directory
     for human inspection.

Skip conditions
---------------
Requires IMAGE_GENERATION_PROVIDER + (IMAGE_GENERATION_API_KEY or OPENAI_API_KEY).
Alignment scoring also needs ANTHROPIC_API_KEY or GOOGLE_API_KEY (for make_llm).

Cost estimate
-------------
  - 6 images at low quality ($0.005 ea) = $0.030
  - 6 vision scoring calls (small compressed JPEG, Haiku/Flash) ~$0.002 total
  - Total per run: ~$0.032

Human review checklist
----------------------
  - Open each generated PNG in review_dir/assets/ -- is it visually relevant?
  - Check alignment_scores.json -- do the LLM scores match your intuition?
  - Scene with lowest alignment score: does the image actually look off-topic?
  - All images portrait orientation (taller than wide)?

Run:
    pytest tests/integration/test_stage_06c_cheese_imagegen_quality.py -v -s -m integration
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from .helpers import copy_to_review, FIXTURES_DIR


# ---------------------------------------------------------------------------
# Skip sentinels
# ---------------------------------------------------------------------------

def _generation_available() -> bool:
    provider = os.getenv("IMAGE_GENERATION_PROVIDER", "")
    api_key = os.getenv("IMAGE_GENERATION_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    return bool(provider and api_key)


def _alignment_available() -> bool:
    return bool(
        os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY")
    )


skip_if_no_generation = pytest.mark.skipif(
    not _generation_available(),
    reason="IMAGE_GENERATION_PROVIDER and API key not configured",
)


# ---------------------------------------------------------------------------
# Per-scene generation prompts for the cheese fixture
# (beats have no generation_prompts; we add them here)
# ---------------------------------------------------------------------------

_CHEESE_SCENE_META: List[Dict[str, Any]] = [
    {
        "scene_id": "scene_01",
        "visual_description": "Milk transforming into cheese -- molecular and physical transformation",
        "generation_prompts": {
            "precise": (
                "Glass of fresh white milk beside a golden wedge of aged cheese, "
                "molecular protein strands connecting them, dark studio background, "
                "photorealistic, vertical 9:16 composition"
            ),
            "general": "Fresh milk and golden cheese side by side, dark studio, vertical photo",
        },
    },
    {
        "scene_id": "scene_02",
        "visual_description": "Enzymes breaking down milk proteins, mimicking digestion",
        "generation_prompts": {
            "precise": (
                "Microscopic visualization of glowing enzymes breaking apart milk protein "
                "molecules, blue and white light, dark scientific background, "
                "vertical 9:16 composition"
            ),
            "general": "Glowing molecules breaking apart on dark background, science visualization, vertical",
        },
    },
    {
        "scene_id": "scene_03",
        "visual_description": "Curds separating from whey in a large dairy pot",
        "generation_prompts": {
            "precise": (
                "White cheese curds floating and separating from golden whey liquid "
                "in a large stainless steel pot, warm kitchen light, steam rising, "
                "vertical 9:16 composition"
            ),
            "general": "White cheese curds in golden liquid pot, dairy kitchen, warm light, vertical photo",
        },
    },
    {
        "scene_id": "scene_04",
        "visual_description": "Cheese wheels aging in a cave cellar with mold and bacteria cultures",
        "generation_prompts": {
            "precise": (
                "Rows of aged cheese wheels covered in blue-gray mold resting on wooden "
                "shelves in a dark cave cellar, dramatic candlelight, cinematic atmosphere, "
                "vertical 9:16 composition"
            ),
            "general": "Aged cheese wheels in dark cave cellar with mold, dramatic lighting, vertical photo",
        },
    },
    {
        "scene_id": "scene_05",
        "visual_description": "Orange cheddar cheese next to achiote / annatto seeds from tropical tree",
        "generation_prompts": {
            "precise": (
                "Bright orange block of cheddar cheese beside vibrant red-orange achiote "
                "seeds and tropical achiote tree pods on a wooden cutting board, "
                "colorful close-up, vertical 9:16 composition"
            ),
            "general": "Orange cheddar cheese and red seeds on wooden board, colorful, vertical photo",
        },
    },
    {
        "scene_id": "scene_06",
        "visual_description": "Ancient cheesemaking craft -- clay pots and stone tools from thousands of years ago",
        "generation_prompts": {
            "precise": (
                "Ancient clay pots and wooden ladles used for cheesemaking on a rough stone "
                "table, warm candlelight, archaeological aesthetic, cinematic, "
                "vertical 9:16 composition"
            ),
            "general": "Ancient clay pots and wooden tools on stone table, candlelight, historical, vertical photo",
        },
    },
]


def _augment_script_package(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Add scene_id and generation_prompts to each beat in the cheese package."""
    pkg = copy.deepcopy(raw)
    beats = pkg["script"]["beats"]
    for i, beat in enumerate(beats):
        meta = _CHEESE_SCENE_META[i] if i < len(_CHEESE_SCENE_META) else {}
        beat["scene_id"] = meta.get("scene_id", f"scene_{i + 1:02d}")
        beat["visual_queries"] = [f"XYZZY_NO_MATCH_{beat['scene_id']}"]
        beat["generation_prompts"] = meta.get("generation_prompts", {})
        beat["visual_description"] = meta.get("visual_description", beat.get("vo_line", ""))
    return pkg


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_generation
def test_cheese_imagegen_and_alignment(tmp_path: Path) -> None:
    """Generate images for all 6 cheese scenes then score each with the alignment evaluator.

    Human review:
        - assets/*.png -- are they portrait? visually relevant to the scene?
        - alignment_scores.json -- do LLM scores match your subjective assessment?
        - summary in stdout -- lowest-scoring scene is the most useful signal
    """
    import video_agent.config as _cfg
    import video_agent.script_image_agent as _sia

    # Force low quality + correct provider for cost control
    orig_provider = _cfg.IMAGE_GENERATION_PROVIDER
    orig_quality = _cfg.IMAGE_GENERATION_QUALITY
    _sia.IMAGE_GENERATION_PROVIDER = os.getenv("IMAGE_GENERATION_PROVIDER", "openai")
    _sia.IMAGE_GENERATION_QUALITY = "low"
    _cfg.IMAGE_GENERATION_PROVIDER = _sia.IMAGE_GENERATION_PROVIDER
    _cfg.IMAGE_GENERATION_QUALITY = "low"

    try:
        _run_test(tmp_path)
    finally:
        _cfg.IMAGE_GENERATION_PROVIDER = orig_provider
        _cfg.IMAGE_GENERATION_QUALITY = orig_quality
        _sia.IMAGE_GENERATION_PROVIDER = orig_provider
        _sia.IMAGE_GENERATION_QUALITY = orig_quality


def _run_test(tmp_path: Path) -> None:
    from video_agent.script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent
    from video_agent.tools.image_alignment_tools import ImageAlignmentEvaluator

    # Load and augment the cheese fixture
    raw_pkg = json.loads(
        (FIXTURES_DIR / "cheese_facts_2026_03_08" / "script_package.json").read_text(encoding="utf-8")
    )
    script_package = _augment_script_package(raw_pkg)

    # --- Step 1: Generate images for all 6 scenes ---
    print("\n[INFO] Running ScriptImageRetrievalAgent with _no_stock_source_ ...")
    agent = ScriptImageRetrievalAgent(
        config=ScriptImageConfig(
            output_dir=tmp_path,
            image_sources=("_no_stock_source_",),   # forces generation fallback
            min_candidates_per_segment=1,
            max_candidates_per_segment=1,
        )
    )
    manifest = agent.generate_script_image_manifest(script_package)
    segments = manifest.get("segments", [])
    assert segments, "ScriptImageRetrievalAgent returned empty segments"

    # Verify generation happened
    ig = manifest.get("image_generation", {})
    print(f"[INFO] Generation: {ig.get('scenes_generated', 0)} scenes, "
          f"cost=${ig.get('total_cost_usd', 0):.4f}, provider={ig.get('provider', 'n/a')}")

    generated_segments = [
        seg for seg in segments
        if any("generated" in str(c.get("source", "")) for c in (seg.get("candidates") or []))
    ]
    assert len(generated_segments) >= 1, (
        f"Expected at least 1 generated segment, got {len(generated_segments)}. "
        f"Check IMAGE_GENERATION_PROVIDER env var."
    )

    # --- Step 2: Score each generated image with alignment evaluator ---
    do_alignment = _alignment_available()
    if not do_alignment:
        print("[WARN] No LLM API key -- skipping alignment scoring (set ANTHROPIC_API_KEY or GOOGLE_API_KEY)")

    evaluator = ImageAlignmentEvaluator() if do_alignment else None

    # Build lookup: segment_id -> beat meta (segments use segment_id, not scene_id)
    scene_meta_by_id = {m["scene_id"]: m for m in _CHEESE_SCENE_META}
    beat_by_scene_id = {
        beat["scene_id"]: beat
        for beat in script_package["script"]["beats"]
    }

    alignment_scores: List[Dict[str, Any]] = []
    scored_count = 0

    print("\n[INFO] Scoring generated images ...")
    for seg in generated_segments:
        scene_id = seg.get("segment_id") or seg.get("scene_id", "unknown")
        gen_candidates = [
            c for c in (seg.get("candidates") or [])
            if "generated" in str(c.get("source", ""))
        ]
        if not gen_candidates:
            continue

        cand = gen_candidates[0]
        image_url = cand.get("url", "")
        image_path = Path(image_url) if image_url else None

        # Verify file exists
        assert image_path and image_path.exists(), f"Generated image not found: {image_url}"
        assert image_path.stat().st_size > 1000, f"Generated image suspiciously small: {image_url}"

        meta = scene_meta_by_id.get(scene_id, {})
        beat = beat_by_scene_id.get(scene_id, {})

        score_result: Optional[Dict[str, Any]] = None
        if evaluator:
            scene_context = {
                "scene_id": scene_id,
                "visual_description": meta.get("visual_description", beat.get("vo_line", "")),
                "vo_line": beat.get("vo_line", ""),
                "scene_mood": "informative",
            }
            # Pass local path so evaluator reads from disk (no re-download)
            candidate_for_eval = {
                "candidate_id": scene_id,
                "url": image_url,
                "local_path": image_url,
                "source": cand.get("source", ""),
            }
            _, eval_result = evaluator.select_best([candidate_for_eval], scene_context=scene_context)
            if eval_result:
                score_result = eval_result.to_dict()
                scored_count += 1
                ws = eval_result.best_score
                print(
                    f"  [{scene_id}] score={ws:.2f} | {image_path.name} | "
                    f"axes={eval_result.scores_by_axis}"
                )
        else:
            print(f"  [{scene_id}] (no scoring) | {image_path.name}")

        alignment_scores.append({
            "scene_id": scene_id,
            "image_file": image_path.name,
            "image_size_bytes": image_path.stat().st_size,
            "generation_prompt_precise": meta.get("generation_prompts", {}).get("precise", ""),
            "vo_line": beat.get("vo_line", ""),
            "alignment": score_result,
        })

    # --- Step 3: Write artifacts ---
    scores_path = tmp_path / "alignment_scores.json"
    scores_path.write_text(json.dumps(alignment_scores, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest_path = tmp_path / "script_image_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    review = copy_to_review(tmp_path, "06c_cheese_imagegen_quality")

    # --- Summary ---
    print(f"\n--- [Cheese] Image Generation + Alignment Quality ---")
    print(f"Scenes generated:  {len(generated_segments)} / {len(segments)}")
    print(f"Scenes scored:     {scored_count}")
    print(f"Generation cost:   ${ig.get('total_cost_usd', 0):.4f}")
    print(f"Review dir:        {review}")
    print(f"")
    print(f"CHECK: Open review_dir/assets/*.png")
    print(f"  - Is each image portrait orientation (taller than wide)?")
    print(f"  - Is scene_01 a milk-to-cheese transformation image?")
    print(f"  - Is scene_04 a cave cellar with aged cheese wheels?")
    print(f"  - Is scene_05 showing orange cheddar + achiote seeds?")
    print(f"")
    print(f"CHECK: Open review_dir/alignment_scores.json")
    print(f"  - Do the weighted scores reflect your visual assessment?")
    print(f"  - Lowest scoring scene is the most useful QA signal.")
    if scored_count > 0:
        scored = [x for x in alignment_scores if x.get("alignment")]
        if scored:
            best = max(scored, key=lambda x: x["alignment"].get("best_score", 0))
            worst = min(scored, key=lambda x: x["alignment"].get("best_score", 9))
            print(f"  Best:  {best['scene_id']} score={best['alignment'].get('best_score', 'n/a')}")
            print(f"  Worst: {worst['scene_id']} score={worst['alignment'].get('best_score', 'n/a')}")
