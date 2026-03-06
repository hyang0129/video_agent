"""Multi-setting full pipeline integration tests.

Each test setting runs the complete pipeline end-to-end:
  fact seeding → script generation (LLM) → video plan → audio → visual → compose → render

Settings:
  - ww2_tanks:      WW2 Tanks (replaces WW1 tanks)
  - cheese_history: History of Different Kinds of Cheese
  - sports_facts:   Sports Facts

Run a single setting:
    pytest tests/test_settings_pipeline.py -k ww2_tanks -v -s -m integration

Run all settings:
    pytest tests/test_settings_pipeline.py -v -s -m integration

Requires:
    GOOGLE_API_KEY      for LLM script generation
    ffmpeg              on PATH for rendering
    ELEVENLABS_API_KEY  optional; silent audio used when absent

# TODO: Add component caching so expensive artifacts (script_package, video_plan,
#       audio segments) are reused across runs of the same setting without
#       regenerating from scratch. Candidates for caching:
#         - script_package: keyed by (topic_id, subtopic_id, facts_hash)
#         - audio segments: keyed by (vo_line_text, voice_id)
#         - visual assets:  keyed by (search_query, pexels_photo_id)
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.artifacts.io import write_json
from src.audio_agent import create_audio_agent
from src.composition_agent import create_composition_agent
from src.facts.fact_store import FactStore
from src.render_agent import create_render_agent
from src.script_agent import ScriptGenerationAgent
from src.video_planner import script_package_to_video_plan
from src.visual_agent import create_visual_agent


# ---------------------------------------------------------------------------
# Test setting definitions
# ---------------------------------------------------------------------------

def _setting_ww2_tanks() -> Dict[str, Any]:
    topic_brief = {
        "topic_id": "world_war_2_tanks",
        "subtopic_id": "facts",
        "topic": {
            "name": "World War 2 Tanks",
            "positioning": "Surprising facts about the iconic armored vehicles of WW2",
        },
        "subtopic": {
            "name": "WW2 Tank Facts",
            "query": "world war 2 tanks facts",
            "angle": "Shocking engineering facts and battlefield realities",
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 35,
        },
        "script_constraints": {
            "tone": "energetic, authoritative",
            "claims_policy": "Use only verified facts from database",
        },
    }
    seeded_facts: List[str] = [
        "Allied soldiers called any enemy tank a 'Tiger' regardless of its actual type, reflecting the Tiger I's fearsome reputation.",
        "The American M4 Sherman was produced in such massive quantities — over 49,000 units — that it overwhelmed German armor through attrition.",
        "The Soviet T-34's sloped armor design shocked German engineers so much they considered copying it for future Panzer designs.",
        "Germany's Panzer VIII Maus was the heaviest tank ever built at 188 tonnes; it crossed rivers by driving along the submerged riverbed.",
        "The British 'Hobart's Funnies' were specialized Churchill tank variants fitted with flails, bridges, and bobbin mats for assault engineering.",
        "A single Tiger I could engage and destroy multiple Sherman or T-34 tanks before being disabled due to its superior armor and 88mm gun.",
    ]
    return {"topic_brief": topic_brief, "seeded_facts": seeded_facts}


def _setting_cheese_history() -> Dict[str, Any]:
    topic_brief = {
        "topic_id": "cheese_history",
        "subtopic_id": "facts",
        "topic": {
            "name": "History of Different Kinds of Cheese",
            "positioning": "Surprising origins and facts about the world's most beloved cheeses",
        },
        "subtopic": {
            "name": "Cheese History Facts",
            "query": "history of cheese types facts",
            "angle": "Ancient origins, surprising accidents, and wild cheese varieties",
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 35,
        },
        "script_constraints": {
            "tone": "curious, enthusiastic",
            "claims_policy": "Use only verified facts from database",
        },
    }
    seeded_facts: List[str] = [
        "Cheese is believed to have been discovered accidentally around 8,000 BCE when milk was stored in pouches made from animal stomachs containing rennet.",
        "Roquefort, one of the world's oldest blue cheeses, was allegedly discovered when a French shepherd left his lunch in a cave and returned months later to find it transformed.",
        "Parmesan (Parmigiano-Reggiano) can only legally be produced in specific provinces of Italy; wheels are aged at least 12 months and can weigh up to 40 kg.",
        "Cheddar cheese gets its distinctive color from annatto, a natural dye from the achiote tree, added to distinguish it — original cheddar is actually white.",
        "Switzerland's Emmental cheese develops its iconic holes (called 'eyes') from carbon dioxide produced by Propionibacterium bacteria during the aging process.",
        "Brie de Meaux was declared the 'King of Cheeses' at the Congress of Vienna in 1815, outcompeting cheeses from across Europe.",
    ]
    return {"topic_brief": topic_brief, "seeded_facts": seeded_facts}


def _setting_sports_facts() -> Dict[str, Any]:
    topic_brief = {
        "topic_id": "sports_facts",
        "subtopic_id": "facts",
        "topic": {
            "name": "Sports Facts",
            "positioning": "Mind-blowing records, accidents, and hidden history from the world of sports",
        },
        "subtopic": {
            "name": "Surprising Sports Facts",
            "query": "surprising sports facts history",
            "angle": "Records, bizarre rules, and shocking moments fans never knew",
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 35,
        },
        "script_constraints": {
            "tone": "energetic, exciting",
            "claims_policy": "Use only verified facts from database",
        },
    }
    seeded_facts: List[str] = [
        "The Olympic marathon distance of 26.2 miles was standardized in 1908 to accommodate the British royal family's viewing position at Windsor Castle.",
        "Basketball was invented in 1891 by Canadian physician James Naismith, who used peach baskets as the original hoops — players had to manually retrieve the ball after each score.",
        "Baseball's unwritten 'infield fly rule' exists specifically to prevent fielders from intentionally dropping easy pop-ups to trick baserunners into double plays.",
        "Usain Bolt set the 100m world record of 9.58 seconds in 2009; at peak speed he covered approximately 12.4 meters per second — faster than most cars in a school zone.",
        "The first FIFA World Cup in 1930 had no qualifying rounds; thirteen teams simply accepted invitations to participate in Uruguay.",
        "Golf balls were originally smooth; the dimple pattern was discovered when golfers noticed that old, nicked balls flew farther and more accurately than new smooth ones.",
    ]
    return {"topic_brief": topic_brief, "seeded_facts": seeded_facts}


ALL_SETTINGS = {
    "ww2_tanks": _setting_ww2_tanks,
    "cheese_history": _setting_cheese_history,
    "sports_facts": _setting_sports_facts,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_facts(fact_store: FactStore, topic_id: str, subtopic_id: str, facts: List[str]) -> None:
    for fact_text in facts:
        fact_store.add_fact(
            fact_text=fact_text,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            sources=[{"type": "integration_seed", "name": "test_fixture"}],
            engagement_score=7.0,
            verified=True,
            keywords=[topic_id.replace("_", " ")],
            metadata={"mode": "seeded"},
        )


def _review_dir(setting_name: str) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    return project_root / "results" / "test" / f"{setting_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


# ---------------------------------------------------------------------------
# Parametrized integration test
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("setting_name", list(ALL_SETTINGS.keys()))
def test_setting_full_pipeline_to_mp4(setting_name: str, tmp_path: Path) -> None:
    """Run the full pipeline for a test setting from script generation to MP4 output.

    Copies rendered artifacts to results/test/<setting_name>_<timestamp>/ for human review.
    """
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("Missing GOOGLE_API_KEY — required for LLM script generation")
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg not found on PATH")

    setting = ALL_SETTINGS[setting_name]()
    topic_brief: Dict[str, Any] = setting["topic_brief"]
    seeded_facts: List[str] = setting["seeded_facts"]

    topic_id = str(topic_brief["topic_id"])
    subtopic_id = str(topic_brief["subtopic_id"])

    run_dir = tmp_path / f"{setting_name}_pipeline"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1) Seed facts into an isolated fact store
    db_path = run_dir / "facts.db"
    fact_store = FactStore(db_path=str(db_path))
    _seed_facts(fact_store, topic_id, subtopic_id, seeded_facts)

    facts = fact_store.query(
        topic_id=topic_id,
        subtopic_id=subtopic_id,
        limit=10,
        min_engagement_score=0.0,
    )
    assert facts, f"No facts seeded for setting '{setting_name}'"

    # 2) Generate script via LLM
    script_agent = ScriptGenerationAgent(fact_store=fact_store)
    script_package = script_agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
        min_facts=1,
        max_facts=10,
    )
    write_json(run_dir / "script_package.json", script_package)

    # 3) Video plan (deterministic)
    video_plan = script_package_to_video_plan(script_package=script_package)
    write_json(run_dir / "video_plan.json", video_plan)

    # 4) Audio timeline (real TTS if ElevenLabs key present, silent otherwise)
    elevenlabs_available = bool(os.getenv("ELEVENLABS_API_KEY"))
    tts_mode = os.getenv("PIPELINE_TEST_TTS_MODE", "auto").strip().lower()
    use_real_tts = tts_mode == "real" or (tts_mode == "auto" and elevenlabs_available)
    selected_voice = "narrator" if use_real_tts else "silent"

    video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = selected_voice

    audio_agent = create_audio_agent(output_dir=run_dir, voice=selected_voice, music_volume_db=-18.0)
    audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)
    write_json(run_dir / "audio_timeline.json", audio_timeline)

    # 5) Visual manifest (real images if PEXELS_API_KEY is set, placeholders otherwise)
    pexels_available = bool(os.getenv("PEXELS_API_KEY"))
    visual_agent = create_visual_agent(
        output_dir=run_dir,
        image_sources=("pexels",) if pexels_available else (),
        content_validator="none",
    )
    visual_manifest = visual_agent.generate_visual_manifest(video_plan=video_plan)
    write_json(run_dir / "visual_manifest.json", visual_manifest)

    # 6) Render spec
    composition_agent = create_composition_agent(output_dir=run_dir)
    render_spec = composition_agent.create_render_specification(
        video_plan=video_plan,
        audio_timeline=audio_timeline,
        visual_manifest=visual_manifest,
    )
    write_json(run_dir / "render_spec.json", render_spec)

    # 7) Render to MP4
    render_agent = create_render_agent(output_dir=run_dir, engine="ffmpeg")
    final_video = render_agent.render(render_spec=render_spec)
    write_json(run_dir / "final_video.json", final_video)

    final_mp4 = run_dir / "final_video.mp4"
    assert final_mp4.exists(), f"[{setting_name}] Expected MP4 was not created in {run_dir}"
    assert final_mp4.stat().st_size > 0, f"[{setting_name}] Rendered MP4 is empty"

    # Copy artifacts to results/test/ for human review
    review_run_dir = _review_dir(setting_name)
    review_run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(run_dir, review_run_dir, dirs_exist_ok=True)

    print(f"\n--- Human Review: {setting_name} ---")
    print(f"Setting:    {setting_name}")
    print(f"MP4:        {review_run_dir / 'final_video.mp4'}")
    print(f"Script:     {review_run_dir / 'script_package.json'}")
    print(f"Review dir: {review_run_dir}")
    print(f"Run command to re-render from existing spec:")
    print(f"  python main.py render {review_run_dir / 'render_spec.json'} ffmpeg")
