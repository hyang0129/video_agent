"""Full Star Wars pipeline integration test.

This test executes the full pipeline in isolation:
1. Topic selection
2. Fact mining
3. Script generation
4. Video plan generation
5. Audio timeline generation
6. Visual manifest generation
7. Composition
8. MP4 render

It intentionally uses only artifacts produced inside the test run directory.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

from src.artifacts.io import write_json
from src.audio_agent import create_audio_agent
from src.composition_agent import create_composition_agent
from src.facts.caption_cache import CaptionCache
from src.facts.fact_miner import FactMiner
from src.facts.fact_store import FactStore
from src.render_agent import create_render_agent
from src.script_agent import ScriptGenerationAgent
from src.video_planner import script_package_to_video_plan
from src.visual_agent import create_visual_agent


def _select_star_wars_topic() -> Dict[str, Any]:
    """Return a deterministic topic brief for Star Wars facts."""
    candidates = [
        {
            "topic_id": "star_wars",
            "subtopic_id": "facts",
            "topic_name": "Star Wars",
            "subtopic_name": "Star Wars Facts",
            "query": "star wars facts explained",
            "angle": "Surprising behind-the-scenes facts and universe lore",
            "score": 9.5,
        },
        {
            "topic_id": "marvel",
            "subtopic_id": "facts",
            "topic_name": "Marvel",
            "subtopic_name": "Marvel Facts",
            "query": "marvel facts explained",
            "angle": "Surprising MCU production facts",
            "score": 8.9,
        },
    ]

    selected = max(candidates, key=lambda item: float(item.get("score", 0.0)))

    return {
        "topic_id": selected["topic_id"],
        "subtopic_id": selected["subtopic_id"],
        "topic": {
            "name": selected["topic_name"],
            "positioning": "Mind-blowing Star Wars facts",
        },
        "subtopic": {
            "name": selected["subtopic_name"],
            "query": selected["query"],
            "angle": selected["angle"],
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 30,
        },
        "script_constraints": {
            "tone": "energetic, enthusiastic",
            "claims_policy": "Use only verified facts from database",
        },
    }


def _seed_star_wars_facts(
    fact_store: FactStore,
    topic_id: str,
    subtopic_id: str,
) -> Dict[str, Any]:
    """Seed deterministic Star Wars facts into an isolated fact store."""
    seeded_facts = [
        "Chewbacca's name comes from a Russian word for dog, inspired by George Lucas's own dog.",
        "Yoda was almost played by a monkey in an early concept before the puppet approach was chosen.",
        "The original film released in 1977 was later retitled Episode IV: A New Hope.",
        "James Earl Jones voiced Darth Vader while David Prowse performed Vader's physical role on set.",
        "The iconic lightsaber hum was created by combining projector motor sounds with TV interference.",
        "R2-D2's name was borrowed from film editing shorthand for Reel 2, Dialog 2.",
    ]

    inserted = 0
    for fact_text in seeded_facts:
        fact_store.add_fact(
            fact_text=fact_text,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            sources=[{"type": "integration_seed", "name": "test_fixture"}],
            engagement_score=7.0,
            verified=True,
            keywords=["star wars", "facts"],
            metadata={"mode": "seeded"},
        )
        inserted += 1

    return {
        "topic_query": "seeded_star_wars_facts",
        "videos_found": 0,
        "videos_mined": 0,
        "total_facts": inserted,
        "video_results": [],
    }


@pytest.mark.integration
def test_star_wars_full_pipeline_to_mp4(tmp_path: Path) -> None:
    """Run full Star Wars pipeline from topic selection to MP4 output."""
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("Missing GOOGLE_API_KEY for full pipeline integration test")
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg not found on PATH")

    run_dir = tmp_path / "star_wars_full_pipeline"
    run_dir.mkdir(parents=True, exist_ok=True)

    db_path = run_dir / "facts.db"
    caption_cache_dir = run_dir / "caption_cache"

    assert not db_path.exists()
    assert not caption_cache_dir.exists()

    fact_store = FactStore(db_path=str(db_path))

    project_root = Path(__file__).resolve().parents[1]
    cookies_file = project_root / "youtube_cookies.txt"
    cookies_path = str(cookies_file) if cookies_file.exists() else None

    topic_brief = _select_star_wars_topic()

    use_live_mining = os.getenv("PIPELINE_TEST_USE_LIVE_MINING", "false").strip().lower() == "true"
    if use_live_mining:
        if not os.getenv("YOUTUBE_API_KEY"):
            pytest.skip("Live mining requested but YOUTUBE_API_KEY is missing")

        caption_cache = CaptionCache(cache_dir=caption_cache_dir)
        fact_miner = FactMiner(
            fact_store=fact_store,
            caption_cache=caption_cache,
            cookies_file=cookies_path,
        )

        topic_query = str(topic_brief["subtopic"]["query"])
        videos = fact_miner.youtube_client.search_videos(
            query=topic_query,
            max_results=2,
            order="viewCount",
            duration="medium",
        )

        mined_results = []
        for video in videos[:2]:
            video_id = str(video.get("id") or "").strip()
            if not video_id:
                continue
            mined_results.append(
                fact_miner.mine_video_captions(
                    video_id=video_id,
                    topic_id=str(topic_brief["topic_id"]),
                    subtopic_id=str(topic_brief["subtopic_id"]),
                    store_facts=True,
                )
            )

        mining_results = {
            "topic_query": topic_query,
            "videos_found": len(videos),
            "videos_mined": len([r for r in mined_results if bool(r.get("success"))]),
            "total_facts": sum(int(r.get("facts_extracted") or 0) for r in mined_results),
            "video_results": mined_results,
        }
    else:
        mining_results = _seed_star_wars_facts(
            fact_store=fact_store,
            topic_id=str(topic_brief["topic_id"]),
            subtopic_id=str(topic_brief["subtopic_id"]),
        )

    facts = fact_store.query(
        topic_id=str(topic_brief["topic_id"]),
        subtopic_id=str(topic_brief["subtopic_id"]),
        limit=10,
        min_engagement_score=0.0,
    )
    assert facts, f"No facts mined for isolated run. Mining results: {mining_results}"

    script_agent = ScriptGenerationAgent(fact_store=fact_store)
    script_package = script_agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
        min_facts=1,
        max_facts=10,
    )

    video_plan = script_package_to_video_plan(script_package=script_package)

    requested_tts_mode = os.getenv("PIPELINE_TEST_TTS_MODE", "auto").strip().lower()
    elevenlabs_available = bool(os.getenv("ELEVENLABS_API_KEY"))
    use_real_tts = requested_tts_mode == "real" or (requested_tts_mode == "auto" and elevenlabs_available)
    selected_voice = "narrator" if use_real_tts else "silent"

    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = selected_voice

    audio_agent = create_audio_agent(output_dir=run_dir, voice=selected_voice, music_volume_db=-18.0)
    audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)

    visual_agent = create_visual_agent(
        output_dir=run_dir,
        image_sources=(),
        content_validator="none",
    )
    visual_manifest = visual_agent.generate_visual_manifest(video_plan=video_plan)

    composition_agent = create_composition_agent(output_dir=run_dir)
    render_spec = composition_agent.create_render_specification(
        video_plan=video_plan,
        audio_timeline=audio_timeline,
        visual_manifest=visual_manifest,
    )

    render_agent = create_render_agent(output_dir=run_dir, engine="ffmpeg")
    final_video = render_agent.render(render_spec=render_spec)

    write_json(run_dir / "script_package.json", script_package)
    write_json(run_dir / "video_plan.json", video_plan)
    write_json(run_dir / "audio_timeline.json", audio_timeline)
    write_json(run_dir / "visual_manifest.json", visual_manifest)
    write_json(run_dir / "render_spec.json", render_spec)
    write_json(run_dir / "final_video.json", final_video)

    final_mp4 = run_dir / "final_video.mp4"
    assert final_mp4.exists(), f"Expected MP4 output was not created in {run_dir}"
    assert final_mp4.stat().st_size > 0, "Rendered MP4 is empty"
    assert str(final_video.get("video_file_path")) == "final_video.mp4"

    project_root = Path(__file__).resolve().parents[1]
    review_root = project_root / "results" / "test"
    review_root.mkdir(parents=True, exist_ok=True)
    review_run_dir = review_root / f"star_wars_full_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copytree(run_dir, review_run_dir)

    print(f"FULL_PIPELINE_RUN_DIR={run_dir}")
    print(f"FULL_PIPELINE_MP4={final_mp4}")
    print(f"FULL_PIPELINE_REVIEW_DIR={review_run_dir}")
    print(f"FULL_PIPELINE_REVIEW_MP4={review_run_dir / 'final_video.mp4'}")
