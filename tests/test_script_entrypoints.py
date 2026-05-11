import importlib
from pathlib import Path


def test_init_db_script_imports_cleanly():
    module = importlib.import_module("scripts.init_db")
    assert hasattr(module, "init_database")


def test_init_rag_script_imports_cleanly():
    module = importlib.import_module("scripts.init_rag")
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


def test_ci_workflow_has_default_and_manual_gates():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "python -m compileall app tests scripts" in workflow
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
