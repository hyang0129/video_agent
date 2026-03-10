"""TTS duration estimation utilities.

Shared by ScreenplayReviewer and producer_server so both use the same heuristic.
No external API calls.
"""

from __future__ import annotations

_WPM_BY_PRESET: dict[str, int] = {
    "calm": 130,
    "narrator": 150,
    "energetic": 170,
    "authoritative": 140,
}

_DEFAULT_WPM = 150


def estimate_duration_s(text: str, voice_preset: str = "narrator") -> float:
    """Estimate TTS speech duration in seconds using a word-count heuristic.

    Args:
        text: Voiceover text to estimate.
        voice_preset: One of calm | narrator | energetic | authoritative.

    Returns:
        Estimated duration in seconds.
    """
    wpm = _WPM_BY_PRESET.get(voice_preset, _DEFAULT_WPM)
    words = len(text.split())
    return (words / wpm) * 60.0
