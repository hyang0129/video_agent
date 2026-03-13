"""Video planning agent.

This is intentionally separate from ScriptGenerationAgent.
Today it produces a `VideoPlan` (no rendering), which can be handed off to a
future renderer or automation pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .creative_spec import load_creative_spec
from .video_planner import script_package_to_video_plan


class VideoGenerationAgent:
    """Create a VideoPlan from a ScriptPackage."""

    def create_video_plan(
        self,
        script_package: Dict[str, Any],
        creative_spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a deterministic VideoPlan."""
        return script_package_to_video_plan(script_package=script_package, creative_spec=creative_spec)


def create_video_agent() -> VideoGenerationAgent:
    """Factory for VideoGenerationAgent."""
    return VideoGenerationAgent()
