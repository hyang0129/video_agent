"""Configuration management for Market Research Agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Video Production API Keys
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# Model configuration
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-flash-latest")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# LLM provider: "claude" or "google". Auto-detected from available API keys.
# Explicit ANTHROPIC_API_KEY takes priority over GOOGLE_API_KEY.
LLM_PROVIDER = os.getenv(
    "LLM_PROVIDER",
    "claude" if os.getenv("ANTHROPIC_API_KEY") else "google",
)


_llm_cache: dict = {}


def make_llm(temperature: float = 0.5):
    """Return a cached LangChain chat model for the configured provider.

    The same instance is returned for the same temperature value, so callers
    don't need their own caching wrappers.
    """
    key = (LLM_PROVIDER, temperature)
    if key in _llm_cache:
        return _llm_cache[key]
    if LLM_PROVIDER == "claude":
        from langchain_anthropic import ChatAnthropic  # lazy import
        llm = ChatAnthropic(
            model=CLAUDE_MODEL,
            temperature=temperature,
            anthropic_api_key=ANTHROPIC_API_KEY,
            max_tokens=4096,
        )
    else:
        from langchain_google_genai import ChatGoogleGenerativeAI  # lazy import
        llm = ChatGoogleGenerativeAI(
            model=GOOGLE_MODEL,
            temperature=temperature,
            google_api_key=GOOGLE_API_KEY,
        )
    _llm_cache[key] = llm
    return llm

# Cache settings
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true"
CACHE_EXPIRE_HOURS = int(os.getenv("CACHE_EXPIRE_HOURS", "24"))

# Paths
import os as _os

CACHE_DIR = Path(_os.environ.get("VIDEO_AGENT_CACHE_DIR", ".cache"))
RESULTS_DIR = Path(_os.environ.get("VIDEO_AGENT_RESULTS_DIR", "results"))
ASSETS_DIR = Path(_os.environ.get("VIDEO_AGENT_ASSETS_DIR", "assets"))


# Directories are created on first use by agents, not at import time.
# Call these only when needed, not at module level.
def _ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# YouTube API limits
YOUTUBE_QUOTA_COST = {
    "search": 100,
    "videos": 1,
    "channels": 1,
}
DAILY_QUOTA_LIMIT = 10000

# Content thresholds
MIN_VIEWS_LONGFORM = 100000  # Minimum views to consider a topic viable
MIN_ENGAGEMENT_RATE = 0.02  # 2% engagement rate (likes/views)
SHORT_FORM_DURATION = 60  # Videos under 60 seconds

# Gap analysis scoring weights
SCORING_WEIGHTS = {
    "longform_demand": 0.4,
    "shortform_gap": 0.3,
    "engagement": 0.2,
    "trend": 0.1,
}

# Video Production Settings
DEFAULT_MUSIC_PATH = ASSETS_DIR / "music" / "default_music.mp3"
VIDEO_FORMAT = "9:16"  # Instagram/TikTok vertical format
VIDEO_RESOLUTION = (1080, 1920)  # Width x Height
TARGET_DURATION_SECONDS = 45  # Default video length
AUDIO_SAMPLE_RATE = 44100
VIDEO_FPS = 30

# Audio Generation Settings
DEFAULT_VOICE = "narrator"  # Default ElevenLabs voice preset
BACKGROUND_MUSIC_VOLUME_DB = -18.0  # Background music volume (dB)
VOICEOVER_VOLUME_DB = 0.0  # Voiceover volume (dB)
TARGET_LUFS = -16.0  # Target loudness normalization (LUFS)
TTS_STABILITY = 0.5  # ElevenLabs voice stability (0.0-1.0)
TTS_SIMILARITY_BOOST = 0.75  # ElevenLabs similarity boost (0.0-1.0)

# Audio file formats
AUDIO_EXPORT_FORMAT = "mp3"  # or "wav" for uncompressed
AUDIO_BITRATE = "192k"  # MP3 bitrate

# Music Generation (ACE-Step)
# Values: "acestep" | "default"
MUSIC_BACKEND = os.getenv("MUSIC_BACKEND", "acestep")
ACESTEP_BASE_URL = os.getenv("ACESTEP_BASE_URL", "http://localhost:8001")

# TTS Backend Selection
# Values: "elevenlabs" | "chatterbox_direct" | "chatterbox_server"
TTS_BACKEND = os.getenv("TTS_BACKEND", "chatterbox_server")
CHATTERBOX_SERVER_URL = os.getenv("CHATTERBOX_SERVER_URL", "http://localhost:8000")
CHATTERBOX_VOICE = os.getenv("CHATTERBOX_VOICE", "kronimi7030")

# Rhubarb Lip Sync
RHUBARB_EXECUTABLE = os.getenv("RHUBARB_PATH", "")
RHUBARB_RECOGNIZER = "phonetic"   # "phonetic" (offline) | "pocketSphinx" (more accurate)
RHUBARB_OUTPUT_FORMAT = "json"
RHUBARB_WAV_SAMPLE_RATE = 22050   # Hz — 22050 mono is sufficient and faster to process

# Live2D Renderer
LIVE2D_RENDER_EXECUTABLE = os.getenv("LIVE2D_RENDER_PATH", "")
LIVE2D_MODEL_ID = os.getenv("LIVE2D_MODEL_ID", "majo")
LIVE2D_MODEL_PATH = os.getenv("LIVE2D_MODEL_PATH", "")

# Avatar overlay position and render size within the final video canvas.
# Render at full production resolution so the live2d model fills the frame
# at proper scale.  A crop is applied in FFmpeg to show only head+shoulders.
# AVATAR_CROP_HEIGHT: how many pixels to keep from the TOP of the rendered
#   avatar (head+shoulders region).  860 ≈ top 45% of 1920px.
# AVATAR_OVERLAY_Y: y position of the cropped avatar on the final canvas;
#   set to VIDEO_HEIGHT - CROP_HEIGHT so it sits flush at the bottom.
# All values are overridable via environment variables for production tuning.
AVATAR_RENDER_WIDTH = int(os.getenv("AVATAR_RENDER_WIDTH", str(VIDEO_RESOLUTION[0])))
AVATAR_RENDER_HEIGHT = int(os.getenv("AVATAR_RENDER_HEIGHT", str(VIDEO_RESOLUTION[1])))
AVATAR_CROP_HEIGHT = int(os.getenv("AVATAR_CROP_HEIGHT", "860"))
AVATAR_OVERLAY_X = int(os.getenv("AVATAR_OVERLAY_X", "0"))
AVATAR_OVERLAY_Y = int(os.getenv("AVATAR_OVERLAY_Y", str(VIDEO_RESOLUTION[1] - 860)))
