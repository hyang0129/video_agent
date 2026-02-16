from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.facts.fact_store import FactStore
from src.script_agent import ScriptGenerationAgent


def main() -> None:
    fact_store = FactStore()
    topic_brief = {
        "topic_id": "star_wars",
        "subtopic_id": "facts",
        "topic": {
            "name": "Star Wars",
            "positioning": "Mind-blowing Star Wars facts",
        },
        "subtopic": {
            "name": "Star Wars Facts",
            "angle": "Surprising behind-the-scenes facts and universe lore that even superfans don't know",
        },
        "format": {
            "primary": "Did You Know",
            "target_duration_seconds": 45,
        },
    }

    agent = ScriptGenerationAgent(fact_store=fact_store)
    script_package = agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
        min_facts=3,
        max_facts=10,
    )

    script = script_package.get("script", {})
    beats = script.get("beats", []) if isinstance(script, dict) else []

    print("SCRIPT_ID:", script_package.get("script_package_id"))
    print("HAS_SCRIPT_CONTENT:", isinstance(script_package.get("script_content"), list))
    print("FACT_SOURCES_COUNT:", len(script_package.get("fact_sources", [])))
    print("BEATS_COUNT:", len(beats))
    print("VOICEOVER_WORDS:", len(str(script.get("voiceover", "")).split()))
    print("--- BEATS ---")
    for i, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            continue
        print(f"{i}. {beat.get('on_screen_text')}: {beat.get('vo_line')}")

    out_dir = Path("results") / "debug_script_check"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "script_package_debug.json"
    out_path.write_text(json.dumps(script_package, indent=2, ensure_ascii=False), encoding="utf-8")
    print("SAVED:", out_path)


if __name__ == "__main__":
    main()
