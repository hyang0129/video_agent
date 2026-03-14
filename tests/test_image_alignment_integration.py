"""Integration test for image alignment evaluator (issue 2.6).

Runs the evaluator against real stock images using a live vision-model API.
Prints a human-readable report of per-scene scores for manual review.

Usage:
    pytest tests/test_image_alignment_integration.py -v -s

Requires: ANTHROPIC_API_KEY or GOOGLE_API_KEY set in environment.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from video_agent.tools.image_alignment_tools import (
    ImageAlignmentEvaluator,
    OnlineImageEvalBackend,
    SceneAlignmentResult,
)
from video_agent.tools.image_search_tools import (
    search_pexels_images,
    search_wikimedia_images,
)

# Mark all tests in this module as integration (skip in CI).
pytestmark = pytest.mark.integration

# Scenes to evaluate — based on WW2 tanks fixture + one deliberately poor match.
TEST_SCENES: List[Dict[str, Any]] = [
    {
        "scene_id": "scene_01",
        "visual_description": "A Sherman M4 tank advancing through a muddy European battlefield",
        "vo_line": "The Sherman tank was the backbone of Allied armored forces in World War II",
        "scene_mood": "tense",
        "search_query": "Sherman M4 tank WW2",
    },
    {
        "scene_id": "scene_02",
        "visual_description": "A Tiger I heavy tank in a snowy forest during the Battle of the Bulge",
        "vo_line": "The German Tiger tank struck fear into Allied soldiers with its thick armor",
        "scene_mood": "ominous",
        "search_query": "Tiger tank WW2 winter",
    },
    {
        "scene_id": "scene_03",
        "visual_description": "A T-34 Soviet tank rolling through the streets of Berlin in 1945",
        "vo_line": "Soviet T-34 tanks played a decisive role in the Eastern Front",
        "scene_mood": "triumphant",
        "search_query": "T-34 Soviet tank Berlin 1945",
    },
]


def _has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _has_pexels_key() -> bool:
    return bool(os.getenv("PEXELS_API_KEY"))


def _fetch_candidates(query: str, per_page: int = 3) -> List[Dict[str, Any]]:
    """Fetch real image candidates from available sources."""
    candidates: List[Dict[str, Any]] = []
    try:
        results = search_wikimedia_images(query=query, per_page=per_page, orientation="portrait")
        for r in results:
            r["candidate_id"] = f"wiki_{len(candidates)}"
            candidates.append(r)
    except Exception:
        pass

    if _has_pexels_key() and len(candidates) < per_page:
        try:
            results = search_pexels_images(query=query, per_page=per_page - len(candidates), orientation="portrait")
            for r in results:
                r["candidate_id"] = f"pexels_{len(candidates)}"
                candidates.append(r)
        except Exception:
            pass

    return candidates


def _print_report(scene: Dict[str, Any], result: SceneAlignmentResult, candidates: List[Dict[str, Any]]) -> None:
    """Print a human-readable score report for one scene."""
    print(f"\n{'='*70}")
    print(f"SCENE: {scene['scene_id']}")
    print(f"  Description: {scene['visual_description']}")
    print(f"  VO line:     {scene['vo_line']}")
    print(f"  Mood:        {scene['scene_mood']}")
    print(f"  Query:       {scene['search_query']}")
    print(f"  Candidates evaluated: {result.candidates_evaluated}")
    print(f"  Early exit: {result.early_exit}")
    print(f"  Revision requested: {result.revision_requested}")
    print(f"  Best score: {result.best_score:.2f}")
    if result.scores_by_axis:
        print(f"  Best axis scores: {result.scores_by_axis}")
    print(f"  Best candidate: {result.best_candidate_id}")
    print()

    for score in result.all_scores:
        cand = next((c for c in candidates if c.get("candidate_id") == score.candidate_id), None)
        url = (cand or {}).get("url", "unknown")
        alt = ((cand or {}).get("metadata") or {}).get("alt", "")[:60]
        print(f"  [{score.candidate_id}] score={score.weighted_score:.2f} axes={score.axis_scores}")
        print(f"    URL: {url}")
        if alt:
            print(f"    Alt: {alt}")
    print(f"{'='*70}")


@pytest.mark.skipif(not _has_api_key(), reason="No LLM API key available")
class TestImageAlignmentIntegration:
    """Run the alignment evaluator against real images and print results for human review."""

    def test_evaluate_scenes_and_print_report(self, tmp_path: Path):
        """Score real images for test scenes and write results for human review.

        This test ALWAYS passes (scores are for human judgment, not assertions).
        Review the printed output to validate that the rubric produces sensible scores.
        """
        evaluator = ImageAlignmentEvaluator(
            backend=OnlineImageEvalBackend(),
            mode="batch",
        )

        results_dir = tmp_path / "alignment_eval"
        results_dir.mkdir()

        all_results: List[Dict[str, Any]] = []

        print("\n\n" + "=" * 70)
        print("IMAGE ALIGNMENT EVALUATOR - INTEGRATION TEST")
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
        print(f"Backend: online (LLM provider from config)")
        print(f"Mode: batch (score all candidates)")
        print(f"Accept threshold: {evaluator.accept_threshold}")
        print(f"Min threshold: {evaluator.min_threshold}")
        print("=" * 70)

        for scene in TEST_SCENES:
            print(f"\n[INFO] Fetching candidates for {scene['scene_id']}...")
            candidates = _fetch_candidates(scene["search_query"], per_page=3)

            if not candidates:
                print(f"[SKIP] No candidates found for {scene['scene_id']}")
                continue

            scene_context = {
                "visual_description": scene["visual_description"],
                "vo_line": scene["vo_line"],
                "scene_mood": scene["scene_mood"],
                "scene_id": scene["scene_id"],
            }

            t0 = time.monotonic()
            chosen, result = evaluator.select_best(candidates, scene_context=scene_context)
            elapsed = time.monotonic() - t0

            if result is not None:
                _print_report(scene, result, candidates)
                print(f"  Elapsed: {elapsed:.1f}s")
                entry = result.to_dict()
                entry["elapsed_s"] = round(elapsed, 1)
                entry["candidates"] = [
                    {"candidate_id": c.get("candidate_id"), "url": c.get("url")}
                    for c in candidates
                ]
                all_results.append(entry)

        # Write results to file for later review
        output_path = results_dir / "alignment_scores.json"
        output_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
        print(f"\n[INFO] Results written to: {output_path}")

        # Also write to results/test/ if it exists
        persistent_dir = Path("results/test/alignment_eval")
        persistent_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        persistent_path = persistent_dir / f"scores_{ts}.json"
        persistent_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
        print(f"[INFO] Persistent copy: {persistent_path}")

        print("\n[HUMAN REVIEW] Check the scores above against the candidate images.")
        print("Look for:")
        print("  - Subject scores: do they reflect whether the image shows the right subject?")
        print("  - Setting scores: does era/location accuracy look correct?")
        print("  - Composition scores: are portrait-friendly images scored higher?")
        print("  - Artifacts scores: are watermarked images penalized?")
        print("  - Revision flags: are they appropriate for the score levels?")
