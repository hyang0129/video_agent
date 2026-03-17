"""Tests for video_agent.tools.image_generation_tools."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_agent.tools.image_generation_tools import (
    ImageGenerationError,
    generate_image,
)


class TestGenerateImageValidation:
    def test_empty_prompt_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ImageGenerationError, match="Empty prompt"):
            generate_image("", output_path=tmp_path / "out.png")

    def test_whitespace_only_prompt_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ImageGenerationError, match="Empty prompt"):
            generate_image("   ", output_path=tmp_path / "out.png")

    def test_unknown_provider_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ImageGenerationError, match="Unknown"):
            generate_image("a cat", output_path=tmp_path / "out.png", provider="invalid_provider")

    def test_unknown_provider_lists_available(self, tmp_path: Path) -> None:
        with pytest.raises(ImageGenerationError, match="openai"):
            generate_image("a cat", output_path=tmp_path / "out.png", provider="nonexistent")


class TestGenerateImageOpenAI:
    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "")
    def test_missing_api_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ImageGenerationError, match="not configured"):
            generate_image("a cat", output_path=tmp_path / "out.png", provider="openai")

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_import_error_raises(self, tmp_path: Path) -> None:
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises((ImageGenerationError, ImportError)):
                generate_image("a cat", output_path=tmp_path / "out.png", provider="openai")

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_b64_success(self, tmp_path: Path) -> None:
        import base64
        dest = tmp_path / "assets" / "scene_01.png"
        # Minimal valid PNG bytes, b64-encoded
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50).decode()

        mock_image_data = MagicMock()
        mock_image_data.b64_json = fake_png
        mock_image_data.url = None

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        mock_openai_module = MagicMock()
        mock_openai_module.OpenAI.return_value.images.generate.return_value = mock_response
        mock_openai_module.APIError = Exception

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            with patch("video_agent.tools.image_generation_tools.openai", mock_openai_module, create=True):
                result = generate_image(
                    "a dramatic tiger tank on a battlefield",
                    output_path=dest,
                    provider="openai",
                    size="1024x1536",
                    quality="medium",
                )

        assert result["source"] == "generated_openai"
        assert result["url"] == str(dest)
        assert result["resolution"] == [1024, 1536]
        assert result["attribution"]["required"] is False
        assert result["metadata"]["cost_usd"] == 0.07
        assert result["metadata"]["provider"] == "openai"
        assert result["metadata"]["model"] == "gpt-image-1"
        assert "a dramatic tiger tank" in result["metadata"]["alt"]
        assert dest.exists()

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_low_quality_cost(self, tmp_path: Path) -> None:
        import base64
        dest = tmp_path / "out.png"
        fake_b64 = base64.b64encode(b"\x89PNG\r\n" + b"\x00" * 20).decode()

        mock_image_data = MagicMock()
        mock_image_data.b64_json = fake_b64
        mock_image_data.url = None

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        mock_openai_module = MagicMock()
        mock_openai_module.OpenAI.return_value.images.generate.return_value = mock_response
        mock_openai_module.APIError = Exception

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            with patch("video_agent.tools.image_generation_tools.openai", mock_openai_module, create=True):
                result = generate_image("a cat", output_path=dest, provider="openai", quality="low")

        assert result["metadata"]["cost_usd"] == 0.005
        assert result["metadata"]["quality"] == "low"

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_api_error_raises(self, tmp_path: Path) -> None:
        mock_openai_module = MagicMock()
        mock_openai_module.APIError = RuntimeError
        mock_openai_module.OpenAI.return_value.images.generate.side_effect = RuntimeError("rate limited")

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            with patch("video_agent.tools.image_generation_tools.openai", mock_openai_module, create=True):
                with pytest.raises(ImageGenerationError, match="rate limited"):
                    generate_image("a cat", output_path=tmp_path / "out.png", provider="openai")

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_openai_empty_response_raises(self, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.data = []

        mock_openai_module = MagicMock()
        mock_openai_module.APIError = Exception
        mock_openai_module.OpenAI.return_value.images.generate.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            with patch("video_agent.tools.image_generation_tools.openai", mock_openai_module, create=True):
                with pytest.raises(ImageGenerationError, match="empty response"):
                    generate_image("a cat", output_path=tmp_path / "out.png", provider="openai")

    @patch("video_agent.tools.image_generation_tools.IMAGE_GENERATION_API_KEY", "sk-test")
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        import base64
        dest = tmp_path / "deep" / "nested" / "scene.png"
        fake_b64 = base64.b64encode(b"\x89PNG\r\n" + b"\x00" * 20).decode()

        mock_image_data = MagicMock()
        mock_image_data.b64_json = fake_b64
        mock_image_data.url = None

        mock_response = MagicMock()
        mock_response.data = [mock_image_data]

        mock_openai_module = MagicMock()
        mock_openai_module.APIError = Exception
        mock_openai_module.OpenAI.return_value.images.generate.return_value = mock_response

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            with patch("video_agent.tools.image_generation_tools.openai", mock_openai_module, create=True):
                generate_image("a cat", output_path=dest, provider="openai")

        assert dest.exists()
