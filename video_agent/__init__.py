"""video_agent -- multi-agent AI video content pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("video-agent")
except PackageNotFoundError:
    # Running from source without pip install
    __version__ = "0.0.0.dev"

# Public API -- stable across minor versions.
# Changes to these symbols require a major version bump.
# Note: FullPipelineRunner is intentionally absent (removed in 1.0b).
# Private repos build their own pipeline runners using MCP tool composition.
from video_agent.orchestrator import ProductionOrchestrator
from video_agent.artifacts.screenplay import (
    new_concept,
    new_screenplay,
    screenplay_to_script_package,
)
from video_agent.artifacts.io import ensure_run_dir, new_run_id, write_json

__all__ = [
    "__version__",
    # Production orchestration
    "ProductionOrchestrator",
    # Artifact constructors
    "new_concept",
    "new_screenplay",
    "screenplay_to_script_package",
    # Artifact I/O
    "new_run_id",
    "ensure_run_dir",
    "write_json",
]
