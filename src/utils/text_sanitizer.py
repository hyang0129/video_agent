"""Text sanitizer for screenplay and render-pipeline text fields.

Replaces non-ASCII punctuation (em-dashes, curly quotes, etc.) with safe
ASCII equivalents and strips characters that break FFmpeg drawtext or TTS.

Called at the earliest post-LLM stage (_coerce_scenes) so all downstream
consumers -- audio agent, composition agent, render agent -- receive clean
text.
"""

from __future__ import annotations

import re
import unicodedata

# ---- replacement map: non-ASCII punctuation -> ASCII equivalent ----------
_REPLACE_MAP: dict[str, str] = {
    "\u2014": " - ",   # em-dash
    "\u2013": " - ",   # en-dash
    "\u2012": "-",      # figure dash
    "\u2015": " - ",   # horizontal bar
    "\u2018": "'",      # left single curly quote
    "\u2019": "'",      # right single curly quote / apostrophe
    "\u201A": "'",      # single low-9 quote
    "\u201B": "'",      # single high-reversed-9 quote
    "\u201C": '"',      # left double curly quote
    "\u201D": '"',      # right double curly quote
    "\u201E": '"',      # double low-9 quote
    "\u201F": '"',      # double high-reversed-9 quote
    "\u2026": "...",    # ellipsis
    "\u2032": "'",      # prime
    "\u2033": '"',      # double prime
    "\u00AB": '"',      # left guillemet
    "\u00BB": '"',      # right guillemet
    "\u2039": "'",      # single left guillemet
    "\u203A": "'",      # single right guillemet
    "\u00A0": " ",      # non-breaking space
    "\u2002": " ",      # en space
    "\u2003": " ",      # em space
    "\u2009": " ",      # thin space
    "\u200A": " ",      # hair space
    "\u200B": "",       # zero-width space
    "\u200C": "",       # zero-width non-joiner
    "\u200D": "",       # zero-width joiner
    "\uFEFF": "",       # BOM / zero-width no-break space
}

# Pre-compiled regex matching any key in the map (single pass)
_REPLACE_RE = re.compile("|".join(re.escape(k) for k in _REPLACE_MAP))

# Emoji pattern: broad match for common emoji ranges
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ (catch stragglers)
    "]+",
    flags=re.UNICODE,
)


def sanitize_text(text: str) -> str:
    """Replace non-ASCII punctuation with safe ASCII and strip emoji.

    Returns a cleaned string safe for FFmpeg drawtext and TTS backends.
    """
    if not text:
        return text

    # 1. Apply known replacements (curly quotes, dashes, special spaces)
    text = _REPLACE_RE.sub(lambda m: _REPLACE_MAP[m.group()], text)

    # 2. Strip emoji
    text = _EMOJI_RE.sub("", text)

    # 3. Normalize remaining Unicode (NFC) then drop non-printable
    text = unicodedata.normalize("NFC", text)

    # 4. Collapse runs of whitespace (but preserve newlines)
    text = re.sub(r"[^\S\n]+", " ", text)

    # 5. Strip leading/trailing whitespace
    text = text.strip()

    return text


def has_unsafe_characters(text: str) -> list[str]:
    """Return a list of human-readable issues found in text, or [] if clean.

    Useful for validation / feasibility review without modifying the text.
    """
    issues: list[str] = []
    if not text:
        return issues

    # Check for em/en dashes
    if "\u2014" in text or "\u2013" in text:
        issues.append("contains em-dash or en-dash")

    # Check for curly quotes
    curly = {"\u2018", "\u2019", "\u201C", "\u201D"}
    if any(c in text for c in curly):
        issues.append("contains curly quotes")

    # Check for emoji
    if _EMOJI_RE.search(text):
        issues.append("contains emoji")

    # Check for other non-ASCII
    non_ascii = [c for c in text if ord(c) > 127]
    # Filter out already-flagged categories
    remaining = [c for c in non_ascii if c not in _REPLACE_MAP and not _EMOJI_RE.match(c)]
    if remaining:
        samples = "".join(sorted(set(remaining))[:5])
        issues.append(f"contains non-ASCII characters: {samples}")

    return issues
