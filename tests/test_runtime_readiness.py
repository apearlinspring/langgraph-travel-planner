from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.config import (
    RUNTIME_ENVIRONMENTS,
    Settings,
    normalize_runtime_environment,
    runtime_configuration_snapshot,
    runtime_dependency_matrix,
)
from app.rag.contracts import CONTRACT_VERSION
from app.evaluation.preflight import run_acceptance_preflight
from app.evaluation.scenarios import EvaluationScenario
from scripts.check_runtime_readiness import (
    build_docker_compose_readiness_report,
    build_database_migration_readiness_report,
    build_rag_mixed_corpus_safety_readiness_report,
    build_rag_multimodal_e2e_readiness_report,
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


def _write_minimal_chroma_metadata(
    path: Path,
    collection_name: str = "travel_guides",
    *,
    visibility: str = "public",
    bad_metadata: bool = False,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path / "chroma.sqlite3")
    try:
        connection.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("CREATE TABLE segments (id TEXT PRIMARY KEY, collection TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT, embedding_id TEXT)"
        )
        connection.execute(
            """
            CREATE TABLE embedding_metadata (
                id INTEGER,
                key TEXT,
                string_value TEXT,
                int_value INTEGER,
                float_value REAL,
                bool_value INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO collections (id, name) VALUES (?, ?)",
            ("collection-id", collection_name),
        )
        connection.execute(
            "INSERT INTO segments (id, collection) VALUES (?, ?)",
            ("segment-id", "collection-id"),
        )
        if visibility == "internal":
            documents = [
                ("products", "data/documents/internal/products/route_templates.md", "产品路线模板 适合人群 成熟路线"),
                ("sop", "data/documents/internal/sop/service_sop.md", "顾问服务流程 交付 SOP"),
                ("pricing", "data/documents/internal/pricing/pricing_rules.md", "报价预算必须标记待核验"),
                ("risk", "data/documents/internal/risk/risk_playbook.md", "风险避坑 Plan B"),
                ("report", "data/documents/internal/report/report_standard.md", "最终报告章节和交付标准"),
            ]
        else:
            documents = [
                ("destinations", "data/documents/destinations/xian.md", "西安兵马俑攻略和回民街美食肉夹馍"),
            ]
        for index, (category, source, content) in enumerate(documents, start=1):
            connection.execute(
                "INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?)",
                (index, "segment-id", f"embedding-{index}"),
            )
            metadata = {
                "contract_version": CONTRACT_VERSION,
                "knowledge_base": (
                    "agency_internal_knowledge"
                    if visibility == "internal"
                    else "public_destination_guides"
                ),
                "source": source,
                "source_type": "agency_internal" if visibility == "internal" else "destination_guide",
                "category": category,
                "visibility": visibility,
                "evidence_level": "rule" if visibility == "internal" else "guide",
                "applicable_modes": "agency_plan|free_planning",
                "constraints": "必须标记待核验",
                "last_reviewed": "2026-05-11",
                "freshness_status": "current",
                "requires_verification": "false",
                "chroma:document": content,
            }
            if visibility == "internal" and category == "products":
                metadata.update(
                    {
                        "product_id": "ZX-PROD-XIAN-FAMILY-3D",
                        "source_kind": "demo_catalog",
                        "inventory_status": "demo_only",
                        "destination": "西安",
                        "theme": "亲子省心轻定制",
                        "duration": "3天2晚",
                        "audience": "family|child",
                        "persona_tags": "price_sensitivity|parent_child",
                        "service_level": "light_custom",
                        "price_band": "comfort",
                        "evidence_type": "fictional_product_template",
                    }
                )
            if bad_metadata:
                metadata.pop("contract_version")
                metadata["visibility"] = "public" if visibility == "internal" else "internal"
            for key, value in metadata.items():
                connection.execute(
                    """
                    INSERT INTO embedding_metadata
                        (id, key, string_value, int_value, float_value, bool_value)
                    VALUES (?, ?, ?, NULL, NULL, NULL)
                    """,
                    (index, key, value),
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


def test_runtime_mcp_startup_timeout_default_matches_live_acceptance_baseline(monkeypatch):
    monkeypatch.delenv("RUNTIME_MCP_STARTUP_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.runtime_mcp_startup_timeout_seconds == 25.0


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
        visibility="internal",
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
        visibility="internal",
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


def test_rag_vectorstore_blocks_missing_collection_and_bad_metadata(tmp_path: Path):
    public_vectorstore = tmp_path / "public-vectorstore"
    internal_vectorstore = tmp_path / "internal-vectorstore"
    _write_minimal_chroma_metadata(public_vectorstore, collection_name="wrong_collection")
    _write_minimal_chroma_metadata(
        internal_vectorstore,
        collection_name="agency_internal_knowledge",
        visibility="internal",
        bad_metadata=True,
    )
    env = _required_runtime_env(public_vectorstore, internal_vectorstore)

    snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    findings = "\n".join(snapshot["dependencies"]["rag_vector_store"]["findings"])
    assert "rag_vector_store" in snapshot["missing_required"]
    assert "collection 'travel_guides' is missing" in findings
    assert "missing metadata" in findings or "invalid metadata" in findings
    assert (
        snapshot["dependencies"]["rag_vector_store"]["details"]["stores"]["public"][
            "finding_code"
        ]
        == "collection_missing"
    )


def test_rag_vectorstore_blocks_runtime_probe_without_hits(tmp_path: Path):
    public_vectorstore = tmp_path / "public-vectorstore"
    internal_vectorstore = tmp_path / "internal-vectorstore"
    _write_minimal_chroma_metadata(public_vectorstore)
    _write_minimal_chroma_metadata(
        internal_vectorstore,
        collection_name="agency_internal_knowledge",
        visibility="internal",
    )
    connection = sqlite3.connect(public_vectorstore / "chroma.sqlite3")
    try:
        connection.execute(
            "UPDATE embedding_metadata SET string_value = ? WHERE key = ?",
            ("西安兵马俑攻略但没有餐饮场景词", "chroma:document"),
        )
        connection.commit()
    finally:
        connection.close()

    env = _required_runtime_env(public_vectorstore, internal_vectorstore)
    snapshot = runtime_configuration_snapshot(
        app_env="production",
        environ=env,
        dotenv_path=tmp_path / "missing.env",
        require_real_values=True,
    )

    public_details = snapshot["dependencies"]["rag_vector_store"]["details"]["stores"]["public"]
    assert "rag_vector_store" in snapshot["missing_required"]
    assert public_details["finding_code"] == "retrieval_no_hit"
    assert public_details["retrieval_probe_gap"]["probe"]["name"] == "food_recommendations"


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


def test_acceptance_preflight_includes_rag_mixed_corpus_safety_gate(tmp_path: Path):
    preflight = run_acceptance_preflight(
        [],
        base_url="http://127.0.0.1:8000",
        environ=_required_runtime_env(),
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    safety_check = next(
        check for check in preflight.checks if check.key == "rag_mixed_corpus_safety"
    )
    assert safety_check.status == "passed"
    assert safety_check.required is True
    assert safety_check.details["scenario_count"] >= 1


def test_runtime_readiness_report_covers_development_staging_acceptance_and_production(tmp_path: Path):
    report = build_runtime_readiness_report(
        environ={},
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    assert report["status"] == "blocked"
    assert report["readiness_status"] == "not_ready"
    assert set(report["targets"]) == {"development", "staging", "acceptance", "production"}
    assert report["targets"]["development"]["status"] == "blocked"
    assert report["targets"]["staging"]["status"] == "blocked"
    assert report["targets"]["acceptance"]["status"] == "blocked"
    assert report["targets"]["production"]["status"] == "blocked"
    assert report["target_readiness_statuses"]["staging"] == "not_ready"
    assert set(report["targets"]["staging"]["component_readiness"]) == {
        "postgresql",
        "redis",
        "rag_vector_store",
        "mcp",
        "llm",
    }
    assert report["targets"]["staging"]["component_readiness"]["postgresql"]["status"] == "not_ready"
    assert "dependency_matrix" in report
    assert report["blocked_reasons"]
    assert report["repair_suggestions"]
    assert any(item["key"] == "postgresql" for item in report["blocked_reasons"])
    assert any("scripts.init_db" in item["command"] for item in report["repair_suggestions"])
    assert report["database_migrations"]["status"] == "passed"
    assert report["docker_compose"]["status"] == "not_checked"
    assert report["rag_mixed_corpus_safety"]["status"] == "passed"
    assert report["rag_mixed_corpus_safety"]["checked"] is True
    assert not any(item["target"] == "rag_mixed_corpus_safety" for item in report["blocked_reasons"])
    assert report["rag_multimodal_e2e"]["status"] == "not_checked"
    assert report["rag_multimodal_e2e"]["checked"] is False
    assert not any(item["target"] == "rag_multimodal_e2e" for item in report["blocked_reasons"])


def test_runtime_readiness_report_accepts_local_alias(tmp_path: Path):
    report = build_runtime_readiness_report(
        targets=["local"],
        environ={},
        dotenv_path=tmp_path / "missing.env",
        check_backend=False,
    )

    assert set(report["targets"]) == {"local"}
    assert report["targets"]["local"]["resolved_environment"] == "development"
    assert report["target_readiness_statuses"]["local"] == "not_ready"
    assert report["targets"]["local"]["component_readiness"]["mcp"]["status"] == "degraded"


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
        "agency",
        "agency_membership",
        "agency_branch",
        "agency_branch_role_grant",
        "agency_customer",
        "agency_customer_invitation",
        "agency_customer_consent_record",
        "agency_customer_event",
        "agency_customer_advisor_assignment",
        "supplier_product",
        "agency_quote",
        "agency_order",
        "agency_order_event",
        "agency_order_review",
        "agency_order_cancellation_case",
        "agency_order_cancellation_event",
        "agency_order_compensation_record",
        "agency_order_reconciliation_record",
        "idempotency_record",
        "payment_attempt",
        "fulfillment_record",
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


def test_rag_multimodal_e2e_readiness_is_not_checked_by_default():
    report = build_rag_multimodal_e2e_readiness_report()

    assert report["status"] == "not_checked"
    assert report["checked"] is False
    assert "check_rag_multimodal_readiness.py --json --check-e2e" in report["commands"]["check"]


def test_rag_mixed_corpus_safety_readiness_passes_by_default():
    report = build_rag_mixed_corpus_safety_readiness_report()

    assert report["status"] == "passed"
    assert report["checked"] is True
    assert report["scenario_count"] >= 1
    assert report["document_count"] >= 1
    assert "--mixed-corpus-safety --top-k 3 --json" in report["commands"]["check"]
    assert not report["blocked_reasons"]


def test_rag_mixed_corpus_safety_readiness_can_be_skipped():
    report = build_rag_mixed_corpus_safety_readiness_report(check=False)

    assert report["status"] == "not_checked"
    assert report["checked"] is False
    assert "evaluate_rag_retrieval.py" in report["commands"]["check"]


def test_rag_mixed_corpus_safety_blocks_runtime_report_when_default_gate_fails(monkeypatch):
    summary = SimpleNamespace(
        to_dict=lambda: {
            "strategy": "metadata_aware_bm25",
            "top_k": 3,
            "source_recall": 1.0,
            "category_recall": 1.0,
            "source_type_recall": 1.0,
            "visibility_recall": 1.0,
            "hit_rate": 1.0,
            "safety_pass_rate": 0.0,
            "mrr": 1.0,
        }
    )
    fake_result = SimpleNamespace(
        scenario_count=1,
        document_count=2,
        top_k_values=[3],
        summaries=[summary],
    )

    def fake_eval(*, top_k_values=(3,)):
        assert tuple(top_k_values) == (3,)
        return fake_result

    def fake_failures(result):
        assert result is fake_result
        return [
            {
                "scenario_id": "public_internal_leak",
                "reasons": ["forbidden_hits"],
                "forbidden_hits": ["internal-policy.md"],
            }
        ]

    monkeypatch.setitem(
        sys.modules,
        "app.evaluation.rag_retrieval",
        SimpleNamespace(
            evaluate_rag_mixed_corpus_safety=fake_eval,
            rag_mixed_corpus_safety_failures=fake_failures,
        ),
    )

    report = build_runtime_readiness_report(
        targets=["development"],
        environ=_required_runtime_env(),
        dotenv_path=Path("missing.env"),
    )

    assert report["status"] == "blocked"
    assert report["rag_mixed_corpus_safety"]["status"] == "blocked"
    assert report["rag_mixed_corpus_safety"]["failed_scenarios"][0]["scenario_id"] == "public_internal_leak"
    assert any(item["target"] == "rag_mixed_corpus_safety" for item in report["blocked_reasons"])


def test_rag_multimodal_e2e_readiness_passes_when_deep_check_passes(monkeypatch):
    def fake_readiness(*, check_e2e=False):
        assert check_e2e is True
        return {
            "status": "passed",
            "findings": [],
            "e2e_acceptance": {
                "status": "passed",
                "passed": True,
                "loaded_from_disk": True,
            },
        }

    monkeypatch.setitem(
        sys.modules,
        "scripts.check_rag_multimodal_readiness",
        SimpleNamespace(build_rag_multimodal_readiness_report=fake_readiness),
    )

    report = build_runtime_readiness_report(
        targets=["development"],
        environ=_required_runtime_env(),
        dotenv_path=Path("missing.env"),
        check_rag_multimodal_e2e=True,
    )

    assert report["rag_multimodal_e2e"]["status"] == "passed"
    assert report["rag_multimodal_e2e"]["e2e_acceptance"]["loaded_from_disk"] is True
    assert not any(item["target"] == "rag_multimodal_e2e" for item in report["blocked_reasons"])


def test_rag_multimodal_e2e_readiness_blocks_runtime_report_when_requested(monkeypatch):
    def fake_readiness(*, check_e2e=False):
        assert check_e2e is True
        return {
            "status": "degraded",
            "findings": ["sample image missing"],
            "e2e_acceptance": {
                "status": "blocked",
                "passed": False,
                "error": "required sample files are missing",
            },
        }

    monkeypatch.setitem(
        sys.modules,
        "scripts.check_rag_multimodal_readiness",
        SimpleNamespace(build_rag_multimodal_readiness_report=fake_readiness),
    )

    report = build_runtime_readiness_report(
        targets=["development"],
        environ=_required_runtime_env(),
        dotenv_path=Path("missing.env"),
        check_rag_multimodal_e2e=True,
    )

    assert report["status"] == "blocked"
    assert report["rag_multimodal_e2e"]["status"] == "blocked"
    assert report["rag_multimodal_e2e"]["blocked_reasons"][0]["key"] == "rag_multimodal_e2e"
    assert any(item["target"] == "rag_multimodal_e2e" for item in report["blocked_reasons"])


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
