"""Unit tests for src.metrics — rolling metrics_summary.json writer."""

import json
from pathlib import Path

import pytest

from src.metrics import update_metrics_summary


@pytest.fixture
def metrics_path(tmp_path: Path) -> Path:
    return tmp_path / "metrics_summary.json"


def test_creates_file_if_missing(metrics_path: Path):
    result = update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_001",
        run_duration_s=120.5,
        stage_timings={"generate_audio": 50.1, "fetch_assets": 40.3},
        passed=True,
        mode="mcp-parallel",
    )
    assert metrics_path.exists()
    assert result["total_runs"] == 1
    assert result["successful_runs"] == 1
    assert result["avg_pipeline_duration_s"] == 120.5
    assert len(result["runs"]) == 1
    entry = result["runs"][0]
    assert entry["run_id"] == "run_001"
    assert entry["passed"] is True
    assert entry["mode"] == "mcp-parallel"
    assert entry["stage_timings"]["generate_audio"] == 50.1


def test_appends_multiple_runs(metrics_path: Path):
    update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_001",
        run_duration_s=100.0,
        stage_timings={},
        passed=True,
    )
    result = update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_002",
        run_duration_s=200.0,
        stage_timings={},
        passed=False,
    )
    assert result["total_runs"] == 2
    assert result["successful_runs"] == 1
    assert result["avg_pipeline_duration_s"] == 150.0
    assert result["runs"][0]["run_id"] == "run_001"
    assert result["runs"][1]["run_id"] == "run_002"


def test_handles_corrupt_file(metrics_path: Path):
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text("NOT VALID JSON {{{", encoding="utf-8")
    result = update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_after_corrupt",
        run_duration_s=80.0,
        stage_timings={"render": 30.0},
        passed=True,
    )
    assert result["total_runs"] == 1
    assert result["runs"][0]["run_id"] == "run_after_corrupt"


def test_handles_missing_runs_key(metrics_path: Path):
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps({"schema_version": "1.0.0"}), encoding="utf-8")
    result = update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_fresh",
        run_duration_s=50.0,
        stage_timings={},
        passed=True,
    )
    assert result["total_runs"] == 1


def test_atomic_write_produces_valid_json(metrics_path: Path):
    update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_atomic",
        run_duration_s=99.9,
        stage_timings={"production_total": 80.0},
        passed=True,
    )
    raw = metrics_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["schema_version"] == "1.0.0"
    assert not metrics_path.with_suffix(".tmp").exists()


def test_stage_timings_rounded(metrics_path: Path):
    result = update_metrics_summary(
        metrics_path=metrics_path,
        run_id="run_round",
        run_duration_s=123.456789,
        stage_timings={"generate_audio": 50.12345},
        passed=True,
    )
    entry = result["runs"][0]
    assert entry["duration_s"] == 123.46
    assert entry["stage_timings"]["generate_audio"] == 50.12
