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
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / ".cache"
RESULTS_DIR = PROJECT_ROOT / "results"
ASSETS_DIR = PROJECT_ROOT / "assets"

# Create directories if they don't exist
CACHE_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

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

# TTS Backend Selection
# Values: "elevenlabs" | "chatterbox_direct" | "chatterbox_server"
TTS_BACKEND = os.getenv("TTS_BACKEND", "chatterbox_server")
CHATTERBOX_SERVER_URL = os.getenv("CHATTERBOX_SERVER_URL", "http://localhost:8000")

# Rhubarb Lip Sync
RHUBARB_EXECUTABLE = os.getenv("RHUBARB_PATH", r"C:\tools\rhubarb\rhubarb.exe")
RHUBARB_RECOGNIZER = "phonetic"   # "phonetic" (offline) | "pocketSphinx" (more accurate)
RHUBARB_OUTPUT_FORMAT = "json"
RHUBARB_WAV_SAMPLE_RATE = 22050   # Hz — 22050 mono is sufficient and faster to process
