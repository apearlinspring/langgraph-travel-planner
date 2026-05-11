from pathlib import Path

import pytest

from app.config import (
    RUNTIME_ENVIRONMENTS,
    normalize_runtime_environment,
    runtime_configuration_snapshot,
    runtime_dependency_matrix,
)
from app.evaluation.preflight import run_acceptance_preflight
from app.evaluation.scenarios import EvaluationScenario
from scripts.check_runtime_readiness import build_runtime_readiness_report


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id="runtime_acceptance",
        name="Runtime acceptance",
        category="agency_plan",
        prompt="Plan a trip",
        expected_mode="agency_plan",
        min_score=80,
        focus=["contract"],
        tags=["acceptance-core"],
        requirements={
            "real_llm": True,
            "real_mcp": True,
            "mcp_servers": ["amap", "VariFlight-Aviation", "aigohotel-mcp"],
            "external_apis": ["amap", "variflight", "aigohotel"],
        },
    )


def test_runtime_environment_aliases_resolve_to_four_tiers():
    assert RUNTIME_ENVIRONMENTS == ("development", "test", "staging", "production")
    assert normalize_runtime_environment("dev") == "development"
    assert normalize_runtime_environment("testing") == "test"
    assert normalize_runtime_environment("prod") == "production"
    assert normalize_runtime_environment("unknown") == "development"


def test_dependency_matrix_marks_core_and_optional_boundaries():
    production = runtime_dependency_matrix("production")
    development = runtime_dependency_matrix("development")
    test = runtime_dependency_matrix("test")

    assert production["postgresql"]["requirement"] == "required"
    assert production["redis"]["requirement"] == "required"
    assert production["llm"]["requirement"] == "required"
    assert production["map"]["requirement"] == "required"
    assert production["hotel"]["requirement"] == "optional"
    assert development["redis"]["requirement"] == "optional"
    assert test["llm"]["requirement"] == "optional"


def test_runtime_configuration_allows_test_mocks_but_blocks_production_placeholders(tmp_path: Path):
    env = {
        "APP_ENV": "production",
        "DASHSCOPE_API_KEY": "test-key-dashscope",
        "POSTGRES_DB": "travel_planner_db",
        "POSTGRES_USER": "travel_user",
        "POSTGRES_PASSWORD": "change-me",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "REDIS_DB": "0",
        "AMAP_API_KEY": "your-amap-api-key",
    }

    test_snapshot = runtime_configuration_snapshot(
        app_env="test",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=False,
    )
    production_snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    assert test_snapshot["missing_required"] == []
    assert "llm" in production_snapshot["missing_required"]
    assert "postgresql" in production_snapshot["missing_required"]
    assert "map" in production_snapshot["missing_required"]
    assert production_snapshot["dependencies"]["llm"]["value_policy"] == "real"


def test_acceptance_preflight_blocks_missing_real_external_credentials(tmp_path: Path):
    preflight = run_acceptance_preflight(
        [_scenario()],
        base_url="http://127.0.0.1:8000",
        environ={
            "DASHSCOPE_API_KEY": "real-ish-dashscope",
            "POSTGRES_DB": "travel_planner_db",
            "POSTGRES_USER": "travel_user",
            "POSTGRES_PASSWORD": "real-ish-password",
            "REDIS_HOST": "localhost",
            "REDIS_PORT": "6379",
            "REDIS_DB": "0",
        },
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    assert preflight.status == "blocked"
    assert "external_api:amap" in preflight.missing_required
    assert "external_api:variflight" in preflight.missing_required
    assert "external_api:aigohotel" in preflight.missing_required
    assert "report_quality" in preflight.skipped_metrics


def test_runtime_readiness_report_covers_development_acceptance_and_production(tmp_path: Path):
    report = build_runtime_readiness_report(
        environ={},
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    assert report["status"] == "blocked"
    assert set(report["targets"]) == {"development", "acceptance", "production"}
    assert report["targets"]["development"]["status"] == "blocked"
    assert report["targets"]["acceptance"]["status"] == "blocked"
    assert report["targets"]["production"]["status"] == "blocked"
    assert "dependency_matrix" in report


def test_runtime_readiness_report_rejects_unknown_target(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown readiness targets"):
        build_runtime_readiness_report(
            targets=["moonbase"],
            dotenv_path=tmp_path / "missing.env",
        )
