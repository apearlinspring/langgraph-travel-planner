from pathlib import Path
import sqlite3
import subprocess

import pytest

from app.config import (
    RUNTIME_ENVIRONMENTS,
    normalize_runtime_environment,
    runtime_configuration_snapshot,
    runtime_dependency_matrix,
)
from app.evaluation.preflight import run_acceptance_preflight
from app.evaluation.scenarios import EvaluationScenario
from scripts.check_runtime_readiness import (
    build_docker_compose_readiness_report,
    build_database_migration_readiness_report,
    build_runtime_readiness_report,
)


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


def _required_runtime_env(
    vectorstore_path: Path | None = None,
    internal_vectorstore_path: Path | None = None,
) -> dict[str, str]:
    env = {
        "DASHSCOPE_API_KEY": "real-ish-dashscope",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "travel_planner_db",
        "POSTGRES_USER": "travel_user",
        "POSTGRES_PASSWORD": "real-ish-password",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "REDIS_DB": "0",
        "AMAP_API_KEY": "real-ish-amap",
        "JWT_SECRET_KEY": "real-ish-jwt-secret-with-enough-entropy",
        "JWT_ALGORITHM": "HS256",
    }
    if vectorstore_path is not None:
        env["RAG_VECTORSTORE_PATH"] = str(vectorstore_path)
    if internal_vectorstore_path is not None:
        env["RAG_INTERNAL_VECTORSTORE_PATH"] = str(internal_vectorstore_path)
    return env


def _write_minimal_chroma_metadata(path: Path, collection_name: str = "travel_guides") -> None:
    path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path / "chroma.sqlite3")
    try:
        connection.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO collections (id, name) VALUES (?, ?)",
            ("collection-id", collection_name),
        )
        connection.commit()
    finally:
        connection.close()


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
    assert "POSTGRES_HOST" in production["postgresql"]["env_vars"]
    assert "POSTGRES_PORT" in production["postgresql"]["env_vars"]
    assert production["redis"]["requirement"] == "required"
    assert production["llm"]["requirement"] == "required"
    assert production["map"]["requirement"] == "required"
    assert production["auth_jwt"]["requirement"] == "required"
    assert development["auth_jwt"]["requirement"] == "optional"
    assert production["hotel"]["requirement"] == "optional"
    assert development["redis"]["requirement"] == "optional"
    assert test["llm"]["requirement"] == "optional"


def test_runtime_configuration_allows_test_mocks_but_blocks_production_placeholders(tmp_path: Path):
    env = {
        "APP_ENV": "production",
        "DASHSCOPE_API_KEY": "test-key-dashscope",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "travel_planner_db",
        "POSTGRES_USER": "travel_user",
        "POSTGRES_PASSWORD": "change-me",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "REDIS_DB": "0",
        "AMAP_API_KEY": "your-amap-api-key",
        "JWT_SECRET_KEY": "dev-only-jwt-secret-change-me",
        "JWT_ALGORITHM": "HS256",
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
    assert "auth_jwt" in production_snapshot["missing_required"]
    assert production_snapshot["dependencies"]["llm"]["value_policy"] == "real"


def test_staging_and_production_block_empty_or_placeholder_jwt_secret(tmp_path: Path):
    env = _required_runtime_env()
    env["JWT_SECRET_KEY"] = ""

    empty_secret = runtime_configuration_snapshot(
        app_env="staging",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )
    env["JWT_SECRET_KEY"] = "placeholder-jwt-secret"
    placeholder_secret = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    assert "auth_jwt" in empty_secret["missing_required"]
    assert "auth_jwt" in placeholder_secret["missing_required"]
    assert empty_secret["dependencies"]["auth_jwt"]["status"] == "blocked"


def test_rag_vectorstore_requires_readable_chroma_collection(tmp_path: Path):
    broken_vectorstore = tmp_path / "broken-vectorstore"
    broken_vectorstore.mkdir()
    env = _required_runtime_env(broken_vectorstore)

    broken_snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    assert "rag_vector_store" in broken_snapshot["missing_required"]
    assert broken_snapshot["dependencies"]["rag_vector_store"]["status"] == "blocked"
    assert "metadata file chroma.sqlite3 is missing" in (
        broken_snapshot["dependencies"]["rag_vector_store"]["findings"][0]
    )

    valid_vectorstore = tmp_path / "valid-vectorstore"
    valid_internal_vectorstore = tmp_path / "valid-internal-vectorstore"
    _write_minimal_chroma_metadata(valid_vectorstore)
    _write_minimal_chroma_metadata(
        valid_internal_vectorstore,
        collection_name="agency_internal_knowledge",
    )
    env["RAG_VECTORSTORE_PATH"] = str(valid_vectorstore)
    env["RAG_INTERNAL_VECTORSTORE_PATH"] = str(valid_internal_vectorstore)
    valid_snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    assert "rag_vector_store" not in valid_snapshot["missing_required"]
    assert valid_snapshot["dependencies"]["rag_vector_store"]["status"] == "configured"
    assert (
        valid_snapshot["dependencies"]["rag_vector_store"]["details"]["collection_name"]
        == "travel_guides"
    )
    assert (
        valid_snapshot["dependencies"]["rag_vector_store"]["details"]["stores"]["internal"][
            "collection_name"
        ]
        == "agency_internal_knowledge"
    )


def test_rag_vectorstore_requires_internal_chroma_collection(tmp_path: Path):
    public_vectorstore = tmp_path / "public-vectorstore"
    missing_internal_vectorstore = tmp_path / "missing-internal-vectorstore"
    valid_internal_vectorstore = tmp_path / "valid-internal-vectorstore"
    _write_minimal_chroma_metadata(public_vectorstore)

    env = _required_runtime_env(public_vectorstore, missing_internal_vectorstore)
    blocked_snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    assert "rag_vector_store" in blocked_snapshot["missing_required"]
    assert blocked_snapshot["dependencies"]["rag_vector_store"]["status"] == "blocked"
    assert any(
        "Internal RAG vector store directory does not exist" in finding
        for finding in blocked_snapshot["dependencies"]["rag_vector_store"]["findings"]
    )

    _write_minimal_chroma_metadata(
        valid_internal_vectorstore,
        collection_name="agency_internal_knowledge",
    )
    env["RAG_INTERNAL_VECTORSTORE_PATH"] = str(valid_internal_vectorstore)
    configured_snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    assert "rag_vector_store" not in configured_snapshot["missing_required"]
    assert configured_snapshot["dependencies"]["rag_vector_store"]["status"] == "configured"


def test_acceptance_preflight_blocks_missing_real_external_credentials(tmp_path: Path):
    env = _required_runtime_env()
    env.pop("AMAP_API_KEY")
    preflight = run_acceptance_preflight(
        [_scenario()],
        base_url="http://127.0.0.1:8000",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    assert preflight.status == "blocked"
    assert "external_api:amap" in preflight.missing_required
    assert "external_api:variflight" in preflight.missing_required
    assert "external_api:aigohotel" in preflight.missing_required
    assert "report_quality" in preflight.skipped_metrics


def test_runtime_readiness_report_covers_development_staging_acceptance_and_production(tmp_path: Path):
    report = build_runtime_readiness_report(
        environ={},
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    assert report["status"] == "blocked"
    assert set(report["targets"]) == {"development", "staging", "acceptance", "production"}
    assert report["targets"]["development"]["status"] == "blocked"
    assert report["targets"]["staging"]["status"] == "blocked"
    assert report["targets"]["acceptance"]["status"] == "blocked"
    assert report["targets"]["production"]["status"] == "blocked"
    assert "dependency_matrix" in report
    assert report["blocked_reasons"]
    assert report["repair_suggestions"]
    assert any(item["key"] == "postgresql" for item in report["blocked_reasons"])
    assert any("scripts.init_db" in item["command"] for item in report["repair_suggestions"])
    assert report["database_migrations"]["status"] == "passed"
    assert report["docker_compose"]["status"] == "not_checked"


def test_database_migration_readiness_is_static_and_separates_langgraph():
    report = build_database_migration_readiness_report()

    assert report["status"] == "passed"
    assert report["requires_database_connection"] is False
    assert set(report["managed_tables"]["business"]) == {
        "user",
        "conversation",
        "message",
        "approval_request",
        "approval_event",
        "tool_audit_event",
    }
    assert "checkpoints" in report["managed_tables"]["langgraph_checkpointer"]
    assert "store_vectors" in report["managed_tables"]["langgraph_store"]
    assert "alembic upgrade head" in report["commands"]["incremental_migration"]
    assert "AsyncPostgresSaver.setup()" in report["boundaries"]["langgraph"]


def test_runtime_readiness_report_rejects_unknown_target(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown readiness targets"):
        build_runtime_readiness_report(
            targets=["moonbase"],
            dotenv_path=tmp_path / "missing.env",
        )


def test_docker_compose_readiness_is_not_checked_by_default():
    report = build_docker_compose_readiness_report()

    assert report["status"] == "not_checked"
    assert report["checked"] is False
    assert "docker compose up -d postgres redis" in report["commands"]["start_dependencies"]


def test_docker_compose_readiness_passes_when_cli_and_daemon_are_available(monkeypatch):
    def fake_run(args, *, timeout_seconds=8):
        if args[:3] == ["docker", "compose", "version"]:
            return subprocess.CompletedProcess(args, 0, stdout="2.29.1\n", stderr="")
        if args[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(args, 0, stdout="27.3.1\n", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr("scripts.check_runtime_readiness._run_command", fake_run)

    report = build_docker_compose_readiness_report(check=True)

    assert report["status"] == "passed"
    assert report["compose_version"] == "2.29.1"
    assert report["server_version"] == "27.3.1"


def test_docker_compose_readiness_blocks_when_docker_desktop_is_not_running(monkeypatch):
    def fake_run(args, *, timeout_seconds=8):
        if args[:3] == ["docker", "compose", "version"]:
            return subprocess.CompletedProcess(args, 0, stdout="2.29.1\n", stderr="")
        if args[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(
                args,
                1,
                stdout="",
                stderr="error during connect: open //./pipe/docker_engine: The system cannot find the file specified.",
            )
        raise AssertionError(args)

    monkeypatch.setattr("scripts.check_runtime_readiness._run_command", fake_run)

    report = build_runtime_readiness_report(
        targets=["staging"],
        environ=_required_runtime_env(),
        dotenv_path=Path("missing.env"),
        check_docker=True,
    )

    assert report["status"] == "blocked"
    assert report["docker_compose"]["status"] == "blocked"
    assert "Docker daemon" in report["docker_compose"]["findings"][0]
    assert "Docker Desktop" in report["docker_compose"]["findings"][0]
    assert report["docker_compose"]["blocked_reasons"][0]["key"] == "docker_daemon"
    assert "docker compose up -d postgres redis" in report["docker_compose"]["repair_suggestions"][0]["command"]
    assert any(item["target"] == "docker_compose" for item in report["blocked_reasons"])
