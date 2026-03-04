"""Stage 3: Script Writing

Tests ScriptGenerationAgent → ScriptPackage (facts + topic brief → script).

What this stage does:
  - Loads facts from FactStore (seeded from fixture for determinism)
  - Uses LLM to write a short-form script grounded only in those facts
  - Produces beats with timing, on-screen text, and voiceover lines
  - Emits hooks, caption, hashtags, and safety notes

Human review checklist:
  - Script uses only the provided facts (no hallucinated claims)
  - Voiceover lines are punchy and suitable for 30-60s short-form
  - Beat timing is contiguous and sums to target duration
  - On-screen text captions are short and readable
  - Hook is attention-grabbing (<=12 words)
  - Safety notes flag any uncertain claims

Run:
    pytest tests/integration/test_stage_03_script_writing.py -v -s -m integration

Requires:
    GOOGLE_API_KEY    for LLM script generation

Input fixture:
    tests/fixtures/topic_brief_ww2_tanks.json  (defines topic + constraints)
    Seeded facts embedded in this test           (stand in for mined facts)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

import pytest

from src.artifacts.io import write_json
from src.facts.fact_store import FactStore
from src.script_agent import ScriptGenerationAgent
from .helpers import load_fixture, copy_to_review

SEEDED_FACTS: List[str] = [
    "Allied soldiers called any enemy tank a 'Tiger' regardless of its actual type, reflecting the Tiger I's fearsome reputation.",
    "The American M4 Sherman was produced in over 49,000 units, overwhelming German armor through attrition rather than individual tank quality.",
    "The Soviet T-34's sloped armor design shocked German engineers so much they considered copying it for future Panzer designs.",
    "Germany's Panzer VIII Maus weighed 188 tonnes and could only cross rivers by driving along the submerged riverbed.",
    "Britain's Hobart's Funnies were Churchill tank variants fitted with flails, bridges, and mats for assault engineering.",
    "A single Tiger I could engage multiple Sherman or T-34 tanks before being disabled due to its superior 88mm gun and armor.",
]


@pytest.mark.integration
def test_script_writing_produces_grounded_script(tmp_path: Path) -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        pytest.skip("Missing GOOGLE_API_KEY")

    topic_brief = load_fixture("topic_brief_ww2_tanks.json")
    topic_id = topic_brief["topic_id"]
    subtopic_id = topic_brief["subtopic_id"]

    db_path = tmp_path / "facts.db"
    fact_store = FactStore(db_path=str(db_path))
    for fact_text in SEEDED_FACTS:
        fact_store.add_fact(
            fact_text=fact_text,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            sources=[{"type": "integration_seed", "name": "test_fixture"}],
            engagement_score=7.0,
            verified=True,
            keywords=["ww2", "tanks"],
            metadata={"mode": "seeded"},
        )

    agent = ScriptGenerationAgent(fact_store=fact_store)
    script_package = agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
        min_facts=1,
        max_facts=10,
    )

    script = script_package.get("script", {})
    beats = script.get("beats", [])

    assert beats, "No beats in script"
    assert script.get("voiceover"), "Missing voiceover"
    assert script_package.get("fact_sources"), "No fact_sources — script may be ungrounded"

    write_json(tmp_path / "script_package.json", script_package)
    review = copy_to_review(tmp_path, "03_script_writing")

    print(f"\n--- Human Review: Script Writing ---")
    print(f"Topic: {topic_id}/{subtopic_id}")
    print(f"Beats: {len(beats)}")
    print(f"Fact sources used: {script_package.get('fact_sources', [])}")
    print(f"Review dir: {review}")
    print(f"Check: script_package.json — do voiceover lines use only provided facts?")
    print(f"Check: are beats punchy and timed correctly?")
    print(f"Check: safety_notes — any claims that need verification?")
    if script_package.get("safety_notes"):
        print(f"Safety notes: {script_package['safety_notes']}")
