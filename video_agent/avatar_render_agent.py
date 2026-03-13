"""Avatar Render Agent.

Calls live2d-render for the full continuous AvatarSceneManifest and captures
the render log. The renderer must be run with the live2d repo root as the
working directory because it resolves assets/models/registry.json relative
to its CWD.

Usage:
    from video_agent.avatar_render_agent import AvatarRenderAgent
    mov_path = AvatarRenderAgent().render(avatar_full_manifest, run_dir)
"""

import subprocess
from pathlib import Path

from video_agent.config import LIVE2D_RENDER_EXECUTABLE


# The live2d-render binary resolves registry.json and model paths relative
# to its CWD.  This must point to the root of the live2d repo.
_LIVE2D_REPO_ROOT = "/workspaces/hub/repos/live2d"


class AvatarRenderAgent:
    """Invokes live2d-render for a full-timeline AvatarSceneManifest."""

    def __init__(
        self,
        executable: str = LIVE2D_RENDER_EXECUTABLE,
        live2d_root: str = _LIVE2D_REPO_ROOT,
        timeout_s: int = 600,
    ):
        self.executable = executable
        self.live2d_root = Path(live2d_root)
        self.timeout_s = timeout_s

    def render(self, avatar_manifest: dict, run_dir: Path) -> Path | None:
        """Render the full avatar video from a pre-built AvatarSceneManifest.

        Args:
            avatar_manifest: The manifest dict produced by
                             AvatarPackagingAgent.package_full().
            run_dir: Pipeline run directory (used to locate the manifest file
                     and write the render log alongside it).

        Returns:
            Path to the rendered .mov file, or None on failure.
        """
        takes_dir = run_dir / "avatar_takes"
        manifest_path = takes_dir / "avatar_full_manifest.json"

        if not manifest_path.exists():
            print(f"[ERROR] avatar_render: manifest not found: {manifest_path}")
            return None

        output_path = Path(avatar_manifest.get("output", str(takes_dir / "avatar_full.mov")))

        exe = self.executable
        if not Path(exe).exists():
            print(f"[ERROR] avatar_render: live2d-render not found: {exe}")
            return None

        cmd = [exe, "--scene", str(manifest_path), "--transparent"]

        log_path = takes_dir / "avatar_full.log"
        print(f"[INFO] avatar_render: starting live2d-render (timeout={self.timeout_s}s)")
        print(f"[INFO] avatar_render: output -> {output_path}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                cwd=str(self.live2d_root),
            )
        except subprocess.TimeoutExpired:
            print(f"[ERROR] avatar_render: live2d-render timed out after {self.timeout_s}s")
            return None
        except FileNotFoundError:
            print(f"[ERROR] avatar_render: live2d-render executable not found: {exe}")
            return None

        # Combine stdout + stderr into the log file
        log_text = result.stdout + result.stderr
        log_path.write_text(log_text, encoding="utf-8", errors="replace")

        if result.returncode != 0:
            snippet = log_text[-400:] if log_text else "(no output)"
            print(f"[ERROR] avatar_render: live2d-render exited {result.returncode}: {snippet}")
            return None

        # The renderer may switch from .mp4 to .mov for transparent output;
        # search for the actual output file if the expected path doesn't exist.
        if output_path.exists():
            print(f"[OK] avatar_render: {output_path.name} ({output_path.stat().st_size // 1024} KB)")
            return output_path

        # Try the .mov sibling if output was declared as .mp4
        mov_sibling = output_path.with_suffix(".mov")
        if mov_sibling.exists():
            print(f"[OK] avatar_render: {mov_sibling.name} ({mov_sibling.stat().st_size // 1024} KB)")
            return mov_sibling

        print(f"[ERROR] avatar_render: output file not found at {output_path}")
        return None
