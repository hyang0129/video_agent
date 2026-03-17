"""AI image generation tools for the visual asset stage.

Provides a provider-agnostic interface to generate scene-specific background
images using AI image generation APIs. Used as a fallback when stock image
search (Pexels, Wikimedia) returns no usable candidates.

Supported providers: openai (GPT Image 1).
Additional providers can be added behind the same interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..config import IMAGE_GENERATION_API_KEY


class ImageGenerationError(Exception):
    """Raised when image generation fails (missing key, API error, timeout)."""


# Quality tier -> (provider-specific value, estimated cost per image USD)
_OPENAI_QUALITY_MAP: Dict[str, tuple[str, float]] = {
    "low": ("low", 0.005),
    "medium": ("medium", 0.07),
    "high": ("high", 0.167),
}


def _generate_openai(
    prompt: str,
    output_path: Path,
    size: str,
    quality: str,
) -> Dict[str, Any]:
    """Generate an image using OpenAI GPT Image 1.

    Args:
        prompt: Image generation prompt.
        output_path: Local path to save the generated PNG.
        size: Dimensions as "WxH" (e.g. "1024x1536" for portrait 9:16).
        quality: Quality tier ("low", "medium", "high").

    Returns:
        Normalized candidate dict.

    Raises:
        ImageGenerationError: On any failure.
    """
    api_key = IMAGE_GENERATION_API_KEY
    if not api_key:
        raise ImageGenerationError(
            "IMAGE_GENERATION_API_KEY (or OPENAI_API_KEY) is not configured"
        )

    try:
        import openai  # lazy import -- only needed when generation is enabled
    except ImportError:
        raise ImageGenerationError(
            "openai package is not installed. Run: pip install openai>=1.0.0"
        )

    oai_quality, cost_usd = _OPENAI_QUALITY_MAP.get(quality, _OPENAI_QUALITY_MAP["medium"])

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            n=1,
            size=size,
            quality=oai_quality,
        )
    except openai.APIError as exc:
        raise ImageGenerationError(f"OpenAI image generation failed: {exc}") from exc
    except Exception as exc:
        raise ImageGenerationError(f"OpenAI image generation error: {exc}") from exc

    if not response.data:
        raise ImageGenerationError("OpenAI returned empty response data")

    image_data = response.data[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer b64_json (avoids expiring URL), fall back to url
    if getattr(image_data, "b64_json", None):
        import base64
        raw = base64.b64decode(image_data.b64_json)
        output_path.write_bytes(raw)
    elif getattr(image_data, "url", None):
        import requests
        try:
            resp = requests.get(image_data.url, timeout=60)
            resp.raise_for_status()
        except Exception as exc:
            raise ImageGenerationError(f"Failed to download generated image: {exc}") from exc
        output_path.write_bytes(resp.content)
    else:
        raise ImageGenerationError("OpenAI returned neither b64_json nor url in response")

    try:
        w, h = (int(d) for d in size.split("x"))
    except (ValueError, AttributeError):
        w, h = 0, 0

    return {
        "source": "generated_openai",
        "url": str(output_path),
        "resolution": [w, h],
        "attribution": {
            "required": False,
            "text": "AI-generated (OpenAI GPT Image 1)",
            "license": "generated",
        },
        "metadata": {
            "alt": prompt[:200],
            "generation_prompt": prompt,
            "provider": "openai",
            "model": "gpt-image-1",
            "quality": oai_quality,
            "cost_usd": cost_usd,
        },
    }


_PROVIDERS = {
    "openai": _generate_openai,
}


def generate_image(
    prompt: str,
    output_path: Path,
    provider: str = "openai",
    size: str = "1024x1536",
    quality: str = "medium",
) -> Dict[str, Any]:
    """Generate an image from a text prompt and save it to disk.

    Args:
        prompt: Image generation prompt text.
        output_path: Where to save the generated image.
        provider: Provider name ("openai"). Others can be added later.
        size: Image dimensions as "WxH". Default "1024x1536" for 9:16 portrait.
        quality: Quality tier ("low", "medium", "high").

    Returns:
        Normalized candidate dict matching the stock image schema:
        {
            "source": "generated_openai",
            "url": str(output_path),
            "resolution": [w, h],
            "attribution": {...},
            "metadata": {"alt", "generation_prompt", "provider", "cost_usd", ...}
        }

    Raises:
        ImageGenerationError: On any failure (missing key, network, timeout, content policy).
    """
    if not prompt or not str(prompt).strip():
        raise ImageGenerationError("Empty prompt")

    provider = str(provider).strip().lower()
    if provider not in _PROVIDERS:
        raise ImageGenerationError(
            f"Unknown image generation provider: {provider!r}. Available: {list(_PROVIDERS)}"
        )

    return _PROVIDERS[provider](str(prompt).strip(), output_path, size, quality)
