import importlib
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_init_db_script_imports_cleanly():
    module = importlib.import_module("scripts.init_db")
    assert hasattr(module, "init_database")


def test_init_rag_script_imports_cleanly():
    module = importlib.import_module("scripts.init_rag")
    assert hasattr(module, "main")


def test_validate_rag_knowledge_script_imports_cleanly():
    module = importlib.import_module("scripts.validate_rag_knowledge")
    assert hasattr(module, "main")


def test_runtime_readiness_script_imports_cleanly():
    module = importlib.import_module("scripts.check_runtime_readiness")
    assert hasattr(module, "build_runtime_readiness_report")
    assert hasattr(module, "build_database_migration_readiness_report")
    assert hasattr(module, "build_docker_compose_readiness_report")


def test_init_db_script_exposes_migration_modes_without_running_database():
    module = importlib.import_module("scripts.init_db")
    assert hasattr(module, "run_business_migrations")
    assert hasattr(module, "build_alembic_config")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "--mode" in source
    assert "--legacy-create-all" in source
    assert "_BOOTSTRAP_IMPORT_ERROR" in source
    assert "Docker Desktop 是否正在运行" in source
    assert "staging/production 不允许使用 legacy create_all" in source


def test_init_db_unreachable_postgres_failure_is_actionable(monkeypatch):
    module = importlib.import_module("scripts.init_db")

    async def fail_probe():
        raise RuntimeError("PostgreSQL TCP 连接不可用：localhost:6543 在 0.1s 内未连通。")

    monkeypatch.setattr(module, "_ensure_runtime_imports", lambda: None)
    monkeypatch.setattr(module, "_probe_postgres_tcp", fail_probe)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            database_url="postgresql://travel_user:secret@localhost:6543/travel_planner_db",
            postgres_host="localhost",
            postgres_port=6543,
            postgres_db="travel_planner_db",
        ),
    )

    with pytest.raises(RuntimeError, match="PostgreSQL TCP 连接不可用"):
        asyncio.run(module.init_database())

    guidance = module._actionable_database_error(RuntimeError("connection refused"))
    assert "docker compose up -d postgres" in guidance
    assert "POSTGRES_HOST/PORT/DB/USER/PASSWORD" in guidance


def test_init_db_bootstrap_sequence_runs_when_dependencies_are_reachable(monkeypatch):
    module = importlib.import_module("scripts.init_db")
    events = []

    async def ok_probe():
        events.append("probe")

    def run_migrations(revision="head"):
        events.append(("migrate", revision))

    async def init_langgraph(db_url):
        events.append(("langgraph", db_url))

    async def enable_pgvector(db_url):
        events.append(("pgvector", db_url))

    monkeypatch.setattr(module, "_ensure_runtime_imports", lambda: None)
    monkeypatch.setattr(module, "_probe_postgres_tcp", ok_probe)
    monkeypatch.setattr(module, "run_business_migrations", run_migrations)
    monkeypatch.setattr(module, "_init_langgraph_tables", init_langgraph)
    monkeypatch.setattr(module, "_enable_pgvector", enable_pgvector)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            database_url="postgresql://travel_user:secret@localhost:5432/travel_planner_db",
            postgres_host="localhost",
            postgres_port=5432,
            postgres_db="travel_planner_db",
        ),
    )

    asyncio.run(module.init_database(revision="head"))

    assert events == [
        "probe",
        ("migrate", "head"),
        ("langgraph", "postgresql://travel_user:secret@localhost:5432/travel_planner_db"),
        ("pgvector", "postgresql://travel_user:secret@localhost:5432/travel_planner_db"),
    ]


def test_init_rag_script_exposes_actionable_failure_guidance():
    module = importlib.import_module("scripts.init_rag")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "_RAG_IMPORT_ERROR" in source
    assert "RAG_INTERNAL_VECTORSTORE_PATH" in source
    assert "validate_rag_knowledge.py --json" in source
    assert "DASHSCOPE_API_KEY" in source
    assert "sentence-transformers" in source


def test_alembic_business_migration_covers_owned_tables_only():
    revision = Path("alembic/versions/20260511_0001_initial_business_schema.py").read_text(
        encoding="utf-8"
    )
    env = Path("alembic/env.py").read_text(encoding="utf-8")

    for table_name in [
        "user",
        "conversation",
        "message",
        "approval_request",
        "approval_event",
        "tool_audit_event",
    ]:
        assert f'"{table_name}"' in revision

    for langgraph_table in [
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "store_migrations",
        "store_vectors",
    ]:
        assert langgraph_table not in revision

    assert "settings.database_url" in env
    assert "Base.metadata" in env
    assert "postgresql+psycopg" in env


def test_evaluation_runner_exposes_preflight_only_entrypoint():
    module = importlib.import_module("scripts.run_evaluation_scenarios")
    assert hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "--scenario" in source
    assert "--scenario-timeout" in source
    assert "--global-timeout" in source
    assert "--preflight-only" in source
    assert "partial_reason" in source
    assert "run_acceptance_preflight" in source


def test_acceptance_comparison_script_imports_cleanly():
    module = importlib.import_module("scripts.compare_acceptance_runs")
    assert hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "compare_acceptance_summaries" in source
    assert "--fail-on-regression" in source


def test_ci_workflow_has_default_gate_and_staging_smoke_dispatch():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    staging_smoke = Path(".github/workflows/staging-smoke.yml").read_text(encoding="utf-8")

    assert "python -m compileall app tests scripts" in workflow
    assert "python scripts/validate_rag_knowledge.py" in workflow
    assert "python -m pytest --collect-only -q" in workflow
    assert "python -m pytest tests/test_ci_workflows.py -q" in workflow
    assert "python -m pytest -q" in workflow
    assert "node scripts/verify_frontend_report_renderer.js" in workflow
    assert "scripts/check_runtime_readiness.py --target development --json" in workflow
    assert "workflow_dispatch" in workflow
    assert "workflow_dispatch" in staging_smoke
    assert "--acceptance-smoke" in staging_smoke
    assert "actions/upload-artifact@v4" in staging_smoke


def test_ci_default_gate_uses_only_non_real_placeholder_values():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "DASHSCOPE_API_KEY: test-key-dashscope" in workflow
    assert "LANGSMITH_API_KEY: test-key-langsmith" in workflow
    assert "JWT_SECRET_KEY: dev-only-ci-jwt-secret-change-me" in workflow
    assert "your-" not in workflow


def test_docker_compose_exposes_runtime_readiness_contract():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for env_name in [
        "DASHSCOPE_API_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST_PORT",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_HOST_PORT",
        "RAG_VECTORSTORE_PATH",
        "RAG_COLLECTION_NAME",
        "RAG_INTERNAL_VECTORSTORE_PATH",
        "RAG_INTERNAL_COLLECTION_NAME",
        "AMAP_API_KEY",
        "VARIFLIGHT_API_KEY",
        "AIGOHOTEL_API_KEY",
        "JWT_SECRET_KEY",
        "LANGGRAPH_RECURSION_LIMIT",
    ]:
        assert env_name in compose

    assert "/health/ready" in compose
    assert "SESSION_LOCK_BACKEND" in compose
    assert "SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL" in compose
    assert "service_healthy" in compose
    assert '"${POSTGRES_HOST_PORT:-5432}:5432"' in compose
    assert '"${REDIS_HOST_PORT:-6379}:6379"' in compose


def test_container_files_keep_liveness_and_proxy_configurable():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    runtime_dockerfile = Path("deploy/Dockerfile.runtime").read_text(encoding="utf-8")
    caddyfile = Path("deploy/Caddyfile").read_text(encoding="utf-8")

    for content in [dockerfile, runtime_dockerfile]:
        assert "APP_ENV=production" in content
        assert "/health/live" in content
        assert "python\", \"-m\", \"app.run" in content

    assert "{$ZHIXING_SITE_ADDRESS:travel.403edr.cn}" in caddyfile
    assert "/health/*" in caddyfile
    assert "reverse_proxy backend:8000" in caddyfile


def test_readiness_docs_cover_ci_staging_and_production_layers():
    deployment = Path("docs/deployment-readiness.md").read_text(encoding="utf-8")
    runtime = Path("docs/runtime-environment.md").read_text(encoding="utf-8")
    evaluation = Path("docs/evaluation-system.md").read_text(encoding="utf-8")
    db_migration = Path("docs/db-migration-readiness.md").read_text(encoding="utf-8")

    for content in [deployment, runtime, evaluation]:
        assert "CI" in content
        assert "workflow_dispatch" in content
        assert "preflight" in content

    assert "--target development --json" in deployment
    assert "--target production --json" in deployment
    assert "alembic upgrade head" in deployment
    assert "默认不连接真实 PostgreSQL" in db_migration
    assert "AsyncPostgresSaver.setup()" in db_migration
    assert "tool_audit_event" in db_migration
    assert "staging-smoke.yml" in evaluation
    assert "acceptance-smoke" in evaluation
    assert "blocked（环境阻塞）" in runtime
    assert "Docker" in deployment
