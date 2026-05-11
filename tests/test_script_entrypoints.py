import importlib
from pathlib import Path


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


def test_evaluation_runner_exposes_preflight_only_entrypoint():
    module = importlib.import_module("scripts.run_evaluation_scenarios")
    assert hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "--preflight-only" in source
    assert "run_acceptance_preflight" in source


def test_acceptance_comparison_script_imports_cleanly():
    module = importlib.import_module("scripts.compare_acceptance_runs")
    assert hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "compare_acceptance_summaries" in source
    assert "--fail-on-regression" in source


def test_ci_workflow_has_default_and_manual_gates():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m compileall app tests scripts" in workflow
    assert "python scripts/validate_rag_knowledge.py" in workflow
    assert "python -m pytest --collect-only -q" in workflow
    assert "python -m pytest -q" in workflow
    assert "node scripts/verify_frontend_report_renderer.js" in workflow
    assert "scripts/check_runtime_readiness.py --target development --json" in workflow
    assert "workflow_dispatch" in workflow
    assert "--preflight-only" in workflow
    assert "run_live_acceptance" in workflow


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
        "REDIS_HOST",
        "REDIS_PORT",
        "RAG_VECTORSTORE_PATH",
        "RAG_COLLECTION_NAME",
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

    for content in [deployment, runtime, evaluation]:
        assert "CI" in content
        assert "workflow_dispatch" in content
        assert "preflight" in content

    assert "--target development --json" in deployment
    assert "--target production --json" in deployment
    assert "run_live_acceptance=true" in evaluation
    assert "blocked（环境阻塞）" in runtime
    assert "Docker" in deployment
