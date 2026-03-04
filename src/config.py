"""Configuration management for Market Research Agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Video Production API Keys
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# Model configuration
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-flash-latest")

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
