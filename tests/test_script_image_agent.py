"""Tests for script-image retrieval agent."""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.script_image_agent import ScriptImageConfig, ScriptImageRetrievalAgent


@pytest.fixture
def sample_script_package() -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "script_package_id": "sg_test_123",
        "topic_id": "star_wars",
        "subtopic_id": "facts",
        "script": {
            "beats": [
                {
                    "t_start_s": 0.0,
                    "t_end_s": 4.5,
                    "on_screen_text": "R2-D2 Secret",
                    "vo_line": "R2-D2 was repaired countless times in the saga.",
                },
                {
                    "t_start_s": 4.5,
                    "t_end_s": 9.0,
                    "on_screen_text": "Lightsaber Lore",
                    "vo_line": "Jedi lightsabers used practical glowing props on set.",
                },
            ]
        },
    }


def test_generate_script_image_manifest_returns_beat_candidates(
    tmp_path: Path,
    sample_script_package: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_search(query: str, per_page: int, orientation: str) -> List[Dict[str, Any]]:
        return [
            {
                "source": "pexels",
                "url": f"https://images.example/{query.replace(' ', '_')}/1.jpg",
                "resolution": [1080, 1920],
                "attribution": {
                    "required": True,
                    "text": "Photo by Example",
                    "license": "Pexels License",
                },
                "metadata": {"search_query": query},
            },
            {
                "source": "pexels",
                "url": f"https://images.example/{query.replace(' ', '_')}/2.jpg",
                "resolution": [1080, 1920],
                "attribution": {
                    "required": True,
                    "text": "Photo by Example",
                    "license": "Pexels License",
                },
                "metadata": {"search_query": query},
            },
        ]

    monkeypatch.setattr("src.script_image_agent.search_pexels_images", _fake_search)

    agent = ScriptImageRetrievalAgent(
        config=ScriptImageConfig(
            output_dir=tmp_path,
            min_candidates_per_segment=1,
            max_candidates_per_segment=5,
            max_queries_per_segment=2,
        )
    )

    manifest = agent.generate_script_image_manifest(sample_script_package)

    assert manifest["schema_version"] == "1.0.0"
    assert manifest["script_package_ref"] == "sg_test_123"
    assert manifest["total_segments"] == 2

    first = manifest["segments"][0]
    assert first["script_ref"]["on_screen_text"] == "R2-D2 Secret"
    assert first["object_of_interest"] in {"R2-D2", "R2-D2 was", "R2D2"}
    assert first["candidate_count"] >= 1
    assert len(first["candidates"]) <= 5

    artifact_path = tmp_path / "script_image_manifest.json"
    assert artifact_path.exists()


def test_insufficient_candidates_status_when_provider_returns_empty(
    tmp_path: Path,
    sample_script_package: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.script_image_agent.search_pexels_images", lambda query, per_page, orientation: [])
    monkeypatch.setattr("src.script_image_agent.search_wikimedia_images", lambda query, per_page, orientation: [])

    agent = ScriptImageRetrievalAgent(
        config=ScriptImageConfig(
            output_dir=tmp_path,
            min_candidates_per_segment=1,
            max_candidates_per_segment=3,
        )
    )

    manifest = agent.generate_script_image_manifest(sample_script_package)
    assert manifest["total_segments"] == 2
    assert all(segment["status"] == "insufficient_candidates" for segment in manifest["segments"])


def test_world_war_tanks_fixture_queries_are_tank_focused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_path = Path("tests/fixtures/script_package_world_war_1_tanks.json")
    script_package = json.loads(fixture_path.read_text(encoding="utf-8"))

    def _fake_search(query: str, per_page: int, orientation: str) -> List[Dict[str, Any]]:
        return [
            {
                "source": "pexels",
                "url": f"https://images.example/{query.replace(' ', '_')}/tank.jpg",
                "resolution": [1080, 1920],
                "attribution": {
                    "required": True,
                    "text": "Photo by Example",
                    "license": "Pexels License",
                },
                "metadata": {"search_query": query},
            }
        ]

    monkeypatch.setattr("src.script_image_agent.search_pexels_images", _fake_search)

    agent = ScriptImageRetrievalAgent(
        config=ScriptImageConfig(
            output_dir=tmp_path,
            min_candidates_per_segment=1,
            max_candidates_per_segment=5,
            max_queries_per_segment=3,
        )
    )

    manifest = agent.generate_script_image_manifest(script_package)
    assert manifest["total_segments"] == 7
    assert all(segment["candidate_count"] >= 1 for segment in manifest["segments"])
    assert all("tank" in (segment["queries"][0].lower()) for segment in manifest["segments"])


def test_candidates_reranked_by_alt_relevance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_package = {
        "script_package_id": "sg_rank_test",
        "topic_id": "world_war_1_tanks",
        "subtopic_id": "facts",
        "script": {
            "beats": [
                {
                    "t_start_s": 0.0,
                    "t_end_s": 4.0,
                    "on_screen_text": "Fact 1",
                    "vo_line": "The British Mark I was one of the first combat tanks.",
                }
            ]
        },
    }

    def _fake_search(query: str, per_page: int, orientation: str) -> List[Dict[str, Any]]:
        return [
            {
                "source": "pexels",
                "url": "https://images.example/weak.jpg",
                "resolution": [4000, 5000],
                "attribution": {"required": True, "text": "weak", "license": "Pexels License"},
                "metadata": {"search_query": query, "alt": "Unknown soldier grave marker from World War I"},
            },
            {
                "source": "pexels",
                "url": "https://images.example/strong.jpg",
                "resolution": [1000, 1200],
                "attribution": {"required": True, "text": "strong", "license": "Pexels License"},
                "metadata": {"search_query": query, "alt": "Vintage British Mark I tank in military museum"},
            },
        ]

    monkeypatch.setattr("src.script_image_agent.search_pexels_images", _fake_search)
    monkeypatch.setattr("src.script_image_agent.search_wikimedia_images", lambda query, per_page, orientation: [])

    agent = ScriptImageRetrievalAgent(
        config=ScriptImageConfig(
            output_dir=tmp_path,
            min_candidates_per_segment=1,
            max_candidates_per_segment=5,
            max_queries_per_segment=1,
        )
    )

    manifest = agent.generate_script_image_manifest(script_package)
    segment = manifest["segments"][0]

    assert segment["candidates"][0]["url"] == "https://images.example/strong.jpg"
    assert "relevance" in segment["candidates"][0]["metadata"]
    assert segment["retrieval_notes"]["reranked_by_alt_relevance"] is True


def test_multi_source_fallback_uses_next_provider_when_first_is_unavailable(
    tmp_path: Path,
    sample_script_package: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_search(query: str, per_page: int, orientation: str) -> List[Dict[str, Any]]:
        return [
            {
                "source": "pexels",
                "url": "https://images.example/fallback.jpg",
                "resolution": [1200, 1800],
                "attribution": {
                    "required": True,
                    "text": "Photo by Example",
                    "license": "Pexels License",
                },
                "metadata": {"search_query": query, "alt": "A sci-fi robot in a workshop"},
            }
        ]

    monkeypatch.setattr("src.script_image_agent.search_pexels_images", _fake_search)

    agent = ScriptImageRetrievalAgent(
        config=ScriptImageConfig(
            output_dir=tmp_path,
            image_sources=("future_source", "pexels"),
            min_candidates_per_segment=1,
            max_candidates_per_segment=3,
            max_queries_per_segment=1,
        )
    )

    manifest = agent.generate_script_image_manifest(sample_script_package)
    first_segment = manifest["segments"][0]

    assert first_segment["candidate_count"] >= 1
    notes = first_segment["retrieval_notes"]
    assert notes["configured_sources"] == ["future_source", "pexels"]
    assert "future_source" in notes["sources_attempted"]
    assert "pexels" in notes["sources_attempted"]
    assert notes["candidate_sources"] == ["pexels"]
    assert notes["source_fallback_strategy"] == "ordered_provider_chain"
    assert notes["source_fallback_used"] is True
    assert any("future_source" in error and "not implemented" in error for error in notes["provider_errors"])
