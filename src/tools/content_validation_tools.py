"""Content validation tools for visual assets.

Phase 1 focuses on an interface-first approach:
- Always returns a structured validation result
- Supports a "none" provider for offline/dev environments

Future: integrate Google Vision, Rekognition, or Azure.
"""

from __future__ import annotations

from typing import Any, Dict, List


class ContentValidationError(Exception):
    """Raised when content validation fails unexpectedly."""


def validate_image_safety(
    image_url: str,
    provider: str = "none",
) -> Dict[str, Any]:
    """Validate image content safety.

    Args:
        image_url: Public URL for the image.
        provider: Validation provider. Phase 1 supports "none".

    Returns:
        Dict:
        {
            "validated": bool,
            "service": str,
            "flags": List[str],
            "score": float,
        }

    Notes:
        For Phase 1, the pipeline can run without external moderation.
        When provider != "none", this function returns a safe, explicit
        failure result rather than silently accepting.
    """
    if provider == "none":
        return {
            "validated": True,
            "service": "none",
            "flags": ["content_validation_skipped"],
            "score": 1.0,
        }

    # Interface placeholder for future integrations.
    return {
        "validated": False,
        "service": provider,
        "flags": ["content_validation_not_implemented"],
        "score": 0.0,
    }


def check_relevance_score(
    image_url: str,
    text_context: str,
) -> float:
    """Score relevance between an image and text context.

    Args:
        image_url: Public URL for the image.
        text_context: Scene/beat text.

    Returns:
        Relevance score from 0.0 to 1.0.

    Notes:
        Phase 1 returns a neutral score. Future versions can use CLIP.
    """
    _ = (image_url, text_context)
    return 0.5
