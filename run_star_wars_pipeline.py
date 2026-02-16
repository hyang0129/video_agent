"""Star Wars facts pipeline with grounded script and voiced audio output.

This script runs an end-to-end pipeline:
1. Mine facts from YouTube (optional)
2. Generate a fact-grounded ScriptPackage
3. Normalize/build script beats for timing
4. Convert ScriptPackage -> VideoPlan
5. Generate TTS voiceover segments
6. Export a combined voiceover audio file
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from src.audio_agent import AudioGenerationError, create_audio_agent
from src.facts.fact_miner import FactMiner
from src.facts.fact_store import FactStore
from src.script_agent import ScriptGenerationAgent, _normalize_beats
from src.video_planner import script_package_to_video_plan


def print_section(title: str) -> None:
    """Print a formatted section header.

    Args:
        title: Section title.
    """
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def _build_voiceover_text(script: Dict[str, Any]) -> str:
    """Build full voiceover text from script format.

    Args:
        script: Script object from ScriptPackage.

    Returns:
        Concatenated full voiceover text.
    """
    if not isinstance(script, dict):
        return ""

    existing_vo = str(script.get("voiceover") or "").strip()
    if existing_vo:
        return existing_vo

    if isinstance(script.get("beats"), list):
        beat_lines = [
            str(beat.get("vo_line") or "").strip()
            for beat in script.get("beats", [])
            if isinstance(beat, dict)
        ]
        beat_lines = [line for line in beat_lines if line]
        if beat_lines:
            return " ".join(beat_lines)

    parts: List[str] = []
    hook = str(script.get("hook") or "").strip()
    if hook:
        parts.append(hook)

    body = script.get("body")
    if isinstance(body, list):
        for segment in body:
            if not isinstance(segment, dict):
                continue
            content = str(segment.get("content") or "").strip()
            if content:
                parts.append(content)

    cta = str(script.get("call_to_action") or "").strip()
    if cta:
        parts.append(cta)

    return " ".join(parts)


def _ensure_beats_for_video_plan(script_package: Dict[str, Any], target_seconds: int) -> None:
    """Ensure script contains meaningful beats for VideoPlan generation.

    If script has fact-grounded hook/body/call_to_action format, this function
    derives beats from that content and applies content-aware timing.

    Args:
        script_package: ScriptPackage object (mutated in place).
        target_seconds: Target total duration in seconds.
    """
    script = script_package.get("script")
    if not isinstance(script, dict):
        script = {}
        script_package["script"] = script

    hook = str(script.get("hook") or "").strip()
    body = script.get("body")
    cta = str(script.get("call_to_action") or "").strip()

    derived_beats: List[Dict[str, Any]] = []

    if hook:
        derived_beats.append({"on_screen_text": "Hook", "vo_line": hook})

    if isinstance(body, list):
        for index, segment in enumerate(body, 1):
            if not isinstance(segment, dict):
                continue
            content = str(segment.get("content") or "").strip()
            if not content:
                continue
            derived_beats.append(
                {
                    "on_screen_text": f"Fact {index}",
                    "vo_line": content,
                }
            )

    if cta:
        derived_beats.append({"on_screen_text": "Follow for more", "vo_line": cta})

    if derived_beats:
        script["beats"] = _normalize_beats(derived_beats, target_seconds)
        script["voiceover"] = " ".join(
            [str(beat.get("vo_line") or "").strip() for beat in script["beats"] if isinstance(beat, dict)]
        )
        return

    existing_beats = script.get("beats")
    if isinstance(existing_beats, list) and existing_beats:
        script["beats"] = _normalize_beats(existing_beats, target_seconds)
        script["voiceover"] = _build_voiceover_text(script)


def _is_generic_voiceover_template(beats: List[Dict[str, Any]]) -> bool:
    """Check whether beat lines match known non-factual placeholder copy.

    Args:
        beats: Beat list from script package.

    Returns:
        True when placeholder template language is detected.
    """
    if not beats:
        return True

    full_text = " ".join([str(beat.get("vo_line") or "").strip().lower() for beat in beats if isinstance(beat, dict)])
    if not full_text:
        return True

    markers = [
        "quick",
        "today: facts",
        "core idea in plain english",
        "why it matters",
        "one example",
        "the takeaway",
        "want more quick facts like this",
    ]
    return sum(1 for marker in markers if marker in full_text) >= 3


def _override_beats_with_fact_lines(
    script_package: Dict[str, Any],
    facts: List[Dict[str, Any]],
    target_seconds: int,
) -> None:
    """Override script beats with deterministic fact-grounded lines.

    Args:
        script_package: ScriptPackage (mutated in place).
        facts: Retrieved fact records used for grounding.
        target_seconds: Target script duration.
    """
    script = script_package.get("script")
    if not isinstance(script, dict):
        script = {}
        script_package["script"] = script

    beats = script.get("beats")
    usable_beats = [beat for beat in beats if isinstance(beat, dict)] if isinstance(beats, list) else []

    if not _is_generic_voiceover_template(usable_beats):
        return

    topic_id = str(script_package.get("topic_id") or "topic").replace("_", " ")
    draft_beats: List[Dict[str, Any]] = [
        {
            "on_screen_text": "Hook",
            "vo_line": f"Think you know {topic_id}? Here are surprising Star Wars facts.",
        }
    ]

    for index, fact in enumerate(facts[:5], 1):
        if not isinstance(fact, dict):
            continue
        line = str(fact.get("fact_text") or "").strip()
        if not line:
            continue
        draft_beats.append(
            {
                "on_screen_text": f"Fact {index}",
                "vo_line": line,
            }
        )

    draft_beats.append(
        {
            "on_screen_text": "Follow for more",
            "vo_line": "Which fact surprised you most? Follow for more Star Wars facts.",
        }
    )

    script["beats"] = _normalize_beats(beats=draft_beats, target_seconds=target_seconds)
    script["voiceover"] = " ".join(
        [str(beat.get("vo_line") or "").strip() for beat in script["beats"] if isinstance(beat, dict)]
    )


def _write_readable_script(
    readable_path: Path,
    script_package: Dict[str, Any],
    target_seconds: int,
) -> None:
    """Write a human-readable script artifact.

    Args:
        readable_path: Output path for readable text file.
        script_package: Generated ScriptPackage.
        target_seconds: Target script duration.
    """
    script = script_package.get("script", {})
    beats = script.get("beats", []) if isinstance(script, dict) else []
    hashtags = script_package.get("hashtags", [])
    voiceover = _build_voiceover_text(script if isinstance(script, dict) else {})

    with open(readable_path, "w", encoding="utf-8") as file:
        file.write("=" * 80 + "\n")
        file.write("FACT-GROUNDED SCRIPT\n")
        file.write("=" * 80 + "\n\n")
        file.write(f"Script ID: {script_package.get('script_package_id', 'N/A')}\n")
        file.write(f"Duration: {target_seconds}s\n")
        file.write(f"Facts Used: {len(script_package.get('fact_sources', []))}\n\n")

        hook = str(script.get("hook") or "").strip() if isinstance(script, dict) else ""
        if hook:
            file.write("HOOK:\n")
            file.write("-" * 80 + "\n")
            file.write(hook + "\n\n")

        body = script.get("body") if isinstance(script, dict) else None
        if isinstance(body, list) and body:
            file.write("FACT-BASED CONTENT:\n")
            file.write("-" * 80 + "\n\n")
            for index, segment in enumerate(body, 1):
                if not isinstance(segment, dict):
                    continue
                file.write(f"Segment {index}:\n")
                file.write(str(segment.get("content") or "") + "\n")
                fact_ids = segment.get("fact_ids")
                if isinstance(fact_ids, list) and fact_ids:
                    file.write(f"Facts: {', '.join([str(fid) for fid in fact_ids])}\n")
                file.write("\n")

        file.write("FULL VOICEOVER:\n")
        file.write("-" * 80 + "\n")
        file.write(voiceover + "\n\n")

        if isinstance(beats, list) and beats:
            file.write("BEAT-BY-BEAT TIMING:\n")
            file.write("-" * 80 + "\n")
            for index, beat in enumerate(beats, 1):
                if not isinstance(beat, dict):
                    continue
                file.write(
                    f"Beat {index} [{float(beat.get('t_start_s', 0)):.2f}s - {float(beat.get('t_end_s', 0)):.2f}s]\n"
                )
                file.write(f"  On-Screen: {str(beat.get('on_screen_text') or '')}\n")
                file.write(f"  Voiceover: {str(beat.get('vo_line') or '')}\n\n")

        file.write("CAPTION:\n")
        file.write("-" * 80 + "\n")
        file.write(str(script_package.get("caption") or "") + "\n\n")

        file.write("HASHTAGS:\n")
        file.write("-" * 80 + "\n")
        file.write(" ".join([str(tag) for tag in hashtags]) + "\n")


def _resolve_ffmpeg_bin(project_root: Path) -> Optional[str]:
    """Resolve FFmpeg binary path.

    Priority:
      1) ffmpeg on PATH
      2) ffmpeg_path.txt in project root

    Args:
        project_root: Project root directory.

    Returns:
        FFmpeg executable path if found, else None.
    """
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    ffmpeg_hint = project_root / "ffmpeg_path.txt"
    if ffmpeg_hint.exists():
        candidate = ffmpeg_hint.read_text(encoding="utf-8").strip()
        if candidate and Path(candidate).exists():
            return candidate

    return None


def _render_voiceover_master(
    output_dir: Path,
    audio_timeline: Dict[str, Any],
    ffmpeg_bin: str,
) -> Path:
    """Combine generated voiceover segments into a single MP3 file.

    Args:
        output_dir: Pipeline output directory.
        audio_timeline: AudioTimeline generated by audio agent.
        ffmpeg_bin: Path to ffmpeg executable.

    Returns:
        Path to combined voiceover file.

    Raises:
        RuntimeError: If no voiceover tracks are found or ffmpeg fails.
    """
    tracks = audio_timeline.get("tracks", [])
    if not isinstance(tracks, list):
        raise RuntimeError("AudioTimeline.tracks is invalid")

    voice_tracks = [
        track
        for track in tracks
        if isinstance(track, dict) and track.get("type") == "voiceover" and track.get("file")
    ]

    if not voice_tracks:
        raise RuntimeError("No voiceover tracks found in AudioTimeline")

    voice_tracks.sort(key=lambda item: float(item.get("t_start_s", 0.0) or 0.0))

    concat_file = output_dir / "voiceover_concat.txt"
    with open(concat_file, "w", encoding="utf-8") as file:
        for track in voice_tracks:
            rel = str(track.get("file"))
            abs_path = (output_dir / rel).resolve()
            if not abs_path.exists():
                raise RuntimeError(f"Missing voice segment: {abs_path}")
            escaped = str(abs_path).replace("'", "'\\''")
            file.write(f"file '{escaped}'\n")

    master_path = output_dir / "voiceover_master.mp3"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(master_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "FFmpeg concat failed")

    return master_path


def main() -> None:
    """Run the full Star Wars fact-grounded + voiced pipeline."""
    print_section("STAR WARS FACTS + VOICED SCRIPT PIPELINE")

    force_mine = "--mine" in sys.argv
    skip_mine = "--no-mine" in sys.argv

    project_root = Path(__file__).parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = project_root / "results" / f"star_wars_pipeline_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize components.
    print("\n[INIT] Setting up fact store and miner...")
    fact_store = FactStore()
    fact_miner = FactMiner(fact_store=fact_store)

    # Existing facts check.
    existing_facts = fact_store.query(topic_id="star_wars", limit=1)
    if existing_facts:
        print("✓ Found existing Star Wars facts in database")
        stats = fact_store.get_stats(topic_id="star_wars")
        print(f"  Total Star Wars facts: {stats['total_facts']}")
        print(f"  Avg engagement: {stats['avg_engagement_score']:.1f}/10")
        if force_mine:
            should_mine = True
        elif skip_mine:
            should_mine = False
        else:
            user_input = input("\nMine more facts? (y/N): ").strip().lower()
            should_mine = user_input == "y"
    else:
        print("No Star Wars facts found. Will mine from YouTube...")
        should_mine = True

    if should_mine:
        print_section("STEP 1: MINING FACTS FROM YOUTUBE")
        print("\nSearching for top Star Wars fact videos...")
        print("(This may take a few minutes)")
        mining_results = fact_miner.mine_top_videos(
            topic_query="star wars facts explained",
            topic_id="star_wars",
            subtopic_id="facts",
            max_videos=5,
            use_captions=True,
        )
        print("\n✓ Mining complete")
        print(f"  Videos processed: {mining_results.get('videos_mined', 0)}")
        print(f"  Facts extracted: {mining_results.get('total_facts', 0)}")

    print_section("STEP 2: QUERYING FACT DATABASE")
    facts = fact_store.query(
        topic_id="star_wars",
        subtopic_id="facts",
        limit=10,
        min_engagement_score=2.0,
    )
    if not facts:
        facts = fact_store.query(topic_id="star_wars", limit=10, min_engagement_score=1.0)

    print(f"\n✓ Retrieved {len(facts)} facts for script generation")

    print_section("STEP 3: GENERATING GROUNDED SCRIPT")
    topic_brief: Dict[str, Any] = {
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
        "script_constraints": {
            "tone": "energetic, enthusiastic",
            "claims_policy": "Use only verified facts from database",
        },
    }

    script_agent = ScriptGenerationAgent(fact_store=fact_store)
    script_package = script_agent.generate_script_package(
        topic_brief=topic_brief,
        use_fact_grounding=True,
        min_facts=3,
        max_facts=10,
    )

    target_seconds = int(topic_brief["format"]["target_duration_seconds"])
    _ensure_beats_for_video_plan(script_package=script_package, target_seconds=target_seconds)
    _override_beats_with_fact_lines(
        script_package=script_package,
        facts=facts,
        target_seconds=target_seconds,
    )
    script = script_package.get("script", {})
    voiceover_text = _build_voiceover_text(script if isinstance(script, dict) else {})

    print("\n✓ Script generated and beats normalized")
    print(f"  Script ID: {script_package.get('script_package_id', 'N/A')}")
    print(f"  Facts used: {len(script_package.get('fact_sources', []))}")
    print(f"  Voiceover length: {len(voiceover_text.split())} words")

    print_section("STEP 4: VIDEO PLAN + TTS AUDIO")

    video_plan = script_package_to_video_plan(script_package=script_package)
    audio_agent = create_audio_agent(output_dir=output_dir, voice="energetic", music_volume_db=-18.0)

    try:
        audio_timeline = audio_agent.generate_audio_timeline(video_plan)
    except AudioGenerationError as error:
        print("\n❌ Audio generation failed.")
        print("   Ensure ELEVENLABS_API_KEY is set in your environment or .env file.")
        raise RuntimeError(str(error)) from error

    # Save core artifacts.
    script_path = output_dir / "script_package.json"
    video_plan_path = output_dir / "video_plan.json"
    readable_path = output_dir / "script_readable.txt"

    script_path.write_text(json.dumps(script_package, indent=2, ensure_ascii=False), encoding="utf-8")
    video_plan_path.write_text(json.dumps(video_plan, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_readable_script(readable_path=readable_path, script_package=script_package, target_seconds=target_seconds)

    # Combine voice tracks into one file.
    ffmpeg_bin = _resolve_ffmpeg_bin(project_root=project_root)
    voiceover_master_path: Optional[Path] = None
    if ffmpeg_bin:
        try:
            voiceover_master_path = _render_voiceover_master(
                output_dir=output_dir,
                audio_timeline=audio_timeline,
                ffmpeg_bin=ffmpeg_bin,
            )
        except RuntimeError as error:
            print(f"\n⚠️  Could not combine voice segments into one file: {error}")
    else:
        print("\n⚠️  FFmpeg not found. Skipping combined voiceover export.")

    print_section("OUTPUT ARTIFACTS")
    print(f"✓ ScriptPackage: {script_path}")
    print(f"✓ VideoPlan: {video_plan_path}")
    print(f"✓ Readable script: {readable_path}")
    print(f"✓ Audio timeline: {output_dir / 'audio_timeline.json'}")
    print(f"✓ Voice segments dir: {output_dir / 'audio_segments'}")
    if voiceover_master_path and voiceover_master_path.exists():
        print(f"✅ Combined voiceover file: {voiceover_master_path}")
    else:
        print("⚠️  Combined voiceover file not created; use segment files in audio_segments/")

    print_section("PIPELINE COMPLETE")
    print("Your fact-grounded script has been generated and voiced audio has been rendered.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Pipeline interrupted by user.")
    except Exception as error:  # pragma: no cover - CLI safety
        print(f"\n\n❌ Error: {error}")
        import traceback

        traceback.print_exc()
