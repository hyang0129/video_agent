"""Reusable full pipeline runner for topic-based short-form video generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .artifacts.io import slugify, write_json
from .audio_agent import create_audio_agent
from .avatar_cue_agent import AvatarCueAgent
from .avatar_packaging_agent import AvatarPackagingAgent
from .avatar_render_agent import AvatarRenderAgent
from .composition_agent import create_composition_agent
from .config import ELEVENLABS_API_KEY, RESULTS_DIR
from .facts.caption_cache import CaptionCache
from .facts.fact_miner import FactMiner
from .facts.fact_store import FactStore
from .render_agent import create_render_agent
from .rhubarb_agent import RhubarbAgent
from .script_agent import ScriptGenerationAgent
from .video_planner import script_package_to_video_plan
from .visual_agent import create_visual_agent


@dataclass(frozen=True)
class FullPipelineConfig:
    """Configuration for a full topic pipeline run."""

    topic_name: str
    topic_query: str
    topic_id: Optional[str] = None
    subtopic_id: str = "facts"
    angle: Optional[str] = None
    target_duration_seconds: int = 35
    max_videos: int = 3
    use_caption_mining: bool = True
    force_fallback_facts: bool = False
    fallback_facts: Optional[List[str]] = None
    output_root: Optional[Path] = None
    output_prefix: str = "full_pipeline"
    voice_mode: str = "auto"  # auto|real|silent|<voice preset/id>
    render_engine: str = "ffmpeg"  # ffmpeg|dry_run
    enable_avatar: bool = True  # include Live2D avatar overlay


class FullPipelineRunner:
    """Runs topic -> facts -> script -> audio/visual -> render end-to-end."""

    def __init__(self, project_root: Path):
        """Initialize runner.

        Args:
            project_root: Workspace/project root path.
        """
        self.project_root = Path(project_root).resolve()

    def run(self, config: FullPipelineConfig) -> Dict[str, Any]:
        """Execute full pipeline and return artifact metadata."""
        safe_topic_id = config.topic_id or slugify(config.topic_name)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        output_root = config.output_root or (RESULTS_DIR / "test")
        run_dir = output_root / f"{config.output_prefix}_{safe_topic_id}_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        fact_store = FactStore(db_path=str(run_dir / "facts.db"))
        caption_cache = CaptionCache(cache_dir=run_dir / "caption_cache")

        cookies_file = self.project_root / "youtube_cookies.txt"
        cookies_path = str(cookies_file) if cookies_file.exists() else None

        miner = FactMiner(
            fact_store=fact_store,
            caption_cache=caption_cache,
            cookies_file=cookies_path,
        )

        if config.force_fallback_facts:
            mining_results: Dict[str, Any] = {
                "success": True,
                "reason": "force_fallback_facts",
                "videos_found": 0,
                "videos_mined": 0,
                "total_facts": 0,
            }
        else:
            try:
                mining_results = miner.mine_top_videos(
                    topic_query=config.topic_query,
                    topic_id=safe_topic_id,
                    subtopic_id=config.subtopic_id,
                    max_videos=config.max_videos,
                    use_captions=config.use_caption_mining,
                )
            except Exception as exc:
                mining_results = {
                    "success": False,
                    "reason": "mining_exception",
                    "error": str(exc),
                    "videos_found": 0,
                    "videos_mined": 0,
                    "total_facts": 0,
                }

        facts = fact_store.query(
            topic_id=safe_topic_id,
            subtopic_id=config.subtopic_id,
            limit=12,
            min_engagement_score=0.0,
        )

        seeded_fallback = False
        if not facts:
            seeded_fallback = True
            fallback_facts = config.fallback_facts or self._default_fallback_facts(config.topic_name)
            for fact_text in fallback_facts:
                fact_store.add_fact(
                    fact_text=fact_text,
                    topic_id=safe_topic_id,
                    subtopic_id=config.subtopic_id,
                    sources=[{"type": "fallback_seed", "name": "full_pipeline_runner"}],
                    engagement_score=6.0,
                    verified=True,
                    keywords=[config.topic_name.lower(), config.subtopic_id.lower()],
                    metadata={"mode": "fallback"},
                )
            facts = fact_store.query(
                topic_id=safe_topic_id,
                subtopic_id=config.subtopic_id,
                limit=12,
                min_engagement_score=0.0,
            )

        if not facts:
            raise RuntimeError("No facts available after mining and fallback")

        topic_brief: Dict[str, Any] = {
            "topic_id": safe_topic_id,
            "subtopic_id": config.subtopic_id,
            "topic": {
                "name": config.topic_name,
                "positioning": f"Surprising {config.topic_name} facts",
            },
            "subtopic": {
                "name": f"{config.topic_name} Facts",
                "query": config.topic_query,
                "angle": config.angle or f"Interesting and lesser-known facts about {config.topic_name}",
            },
            "format": {
                "primary": "Did You Know",
                "target_duration_seconds": int(config.target_duration_seconds),
            },
            "script_constraints": {
                "tone": "energetic, authoritative",
                "claims_policy": "Use only facts from database",
            },
        }

        script_agent = ScriptGenerationAgent(fact_store=fact_store)
        script_package = script_agent.generate_script_package(
            topic_brief=topic_brief,
            use_fact_grounding=True,
            min_facts=1,
            max_facts=10,
        )

        video_plan = script_package_to_video_plan(script_package=script_package)

        selected_voice = self._select_voice(config.voice_mode)
        video_plan.setdefault("audio", {}).setdefault("tts", {})["voice"] = selected_voice

        audio_agent = create_audio_agent(output_dir=run_dir, voice=selected_voice, music_volume_db=-18.0)
        audio_timeline = audio_agent.generate_audio_timeline(video_plan=video_plan)

        visual_agent = create_visual_agent(
            output_dir=run_dir,
            image_sources=("pexels",),
            content_validator="none",
        )
        visual_manifest = visual_agent.generate_visual_manifest(video_plan=video_plan)

        # Avatar pipeline: rhubarb → cues → package (full continuous) → render.
        # Non-blocking: if any stage fails, avatar_manifest stays None and
        # the compositor skips the avatar overlay layer.
        avatar_manifest = None
        avatar_mov_path: Optional[Path] = None
        if config.enable_avatar:
            try:
                lipsync_manifest = RhubarbAgent().generate_lipsync_manifest(audio_timeline, run_dir)
                write_json(run_dir / "lipsync_manifest.json", lipsync_manifest)

                cues_by_scene = AvatarCueAgent().generate_cues(audio_timeline)

                pkg_agent = AvatarPackagingAgent()
                avatar_manifest = pkg_agent.package_full(
                    lipsync_manifest=lipsync_manifest,
                    audio_timeline=audio_timeline,
                    run_dir=run_dir,
                    cues_by_scene=cues_by_scene,
                )
                write_json(run_dir / "avatar_full_manifest.json", avatar_manifest)

                avatar_mov_path = AvatarRenderAgent().render(avatar_manifest, run_dir)
                if avatar_mov_path is None:
                    print("[WARN] avatar render failed; final video will have no avatar overlay")
                    avatar_manifest = None
            except Exception as exc:
                print(f"[WARN] avatar pipeline error: {exc}; continuing without avatar")
                avatar_manifest = None
        else:
            print("[INFO] avatar pipeline disabled (enable_avatar=False)")

        composition_agent = create_composition_agent(output_dir=run_dir)
        render_spec = composition_agent.create_render_specification(
            video_plan=video_plan,
            audio_timeline=audio_timeline,
            visual_manifest=visual_manifest,
            avatar_manifest=avatar_manifest,
        )

        render_agent = create_render_agent(output_dir=run_dir, engine=config.render_engine)
        final_video = render_agent.render(render_spec=render_spec)

        write_json(run_dir / "mining_results.json", mining_results)
        write_json(run_dir / "script_package.json", script_package)
        write_json(run_dir / "video_plan.json", video_plan)
        write_json(run_dir / "audio_timeline.json", audio_timeline)
        write_json(run_dir / "visual_manifest.json", visual_manifest)
        write_json(run_dir / "render_spec.json", render_spec)
        write_json(run_dir / "final_video.json", final_video)
        # lipsync_manifest.json and avatar_full_manifest.json already written
        # inside the avatar pipeline block above.

        final_mp4 = run_dir / "final_video.mp4"
        return {
            "run_dir": str(run_dir),
            "final_mp4": str(final_mp4),
            "final_mp4_exists": final_mp4.exists(),
            "final_mp4_size_bytes": final_mp4.stat().st_size if final_mp4.exists() else 0,
            "facts_count": len(facts),
            "seeded_fallback": seeded_fallback,
            "voice_mode": selected_voice,
            "topic_id": safe_topic_id,
            "subtopic_id": config.subtopic_id,
            "avatar_enabled": config.enable_avatar,
            "avatar_mov": str(avatar_mov_path) if avatar_mov_path else None,
            "avatar_mov_exists": avatar_mov_path is not None and avatar_mov_path.exists(),
        }

    def _select_voice(self, voice_mode: str) -> str:
        mode = str(voice_mode or "auto").strip().lower()
        if mode == "auto":
            return "narrator" if ELEVENLABS_API_KEY else "silent"
        if mode == "real":
            return "narrator"
        if mode == "silent":
            return "silent"
        return voice_mode

    def _default_fallback_facts(self, topic_name: str) -> List[str]:
        """Provide generic fallback facts when mining returns none."""
        lower_topic = topic_name.lower()
        if "world war 1" in lower_topic and "tank" in lower_topic:
            return [
                "The British Mark I, introduced in 1916, is widely regarded as the first combat tank.",
                "The French Renault FT popularized the rotating-turret layout seen in many later tanks.",
                "At Cambrai in 1917, large-scale tank use helped demonstrate armored breakthrough tactics.",
                "WW1 tanks often struggled with mechanical reliability, heat, and toxic fumes inside the hull.",
                "Early tanks were designed to cross trenches and barbed wire that stalled infantry assaults.",
            ]

        return [
            f"{topic_name} has lesser-known facts that are often overlooked in mainstream summaries.",
            f"Historical sources about {topic_name} can vary, so claims are often best presented with context.",
            f"A focused review of {topic_name} reveals practical details beyond headline-level narratives.",
            f"Experts studying {topic_name} often highlight how constraints shaped real-world outcomes.",
            f"Comparing multiple sources improves confidence when presenting facts about {topic_name}.",
        ]
