from pathlib import Path

import yaml


WORKFLOW_DIR = Path(".github/workflows")
CI_WORKFLOW = WORKFLOW_DIR / "ci.yml"
STAGING_SMOKE_WORKFLOW = WORKFLOW_DIR / "staging-smoke.yml"

REQUIRED_STAGING_SMOKE_SECRETS = [
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "DASHSCOPE_API_KEY",
    "AMAP_API_KEY",
    "TAVILY_API_KEY",
    "JWT_SECRET_KEY",
    "ZHIXING_EVAL_USERNAME",
    "ZHIXING_EVAL_PASSWORD",
]


class WorkflowLoader(yaml.SafeLoader):
    pass


WorkflowLoader.yaml_implicit_resolvers = yaml.SafeLoader.yaml_implicit_resolvers.copy()
for first_char, resolvers in list(WorkflowLoader.yaml_implicit_resolvers.items()):
    WorkflowLoader.yaml_implicit_resolvers[first_char] = [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]


def _load_workflow(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=WorkflowLoader)


def test_staging_smoke_workflow_is_manual_only_and_starts_local_stack():
    workflow = _load_workflow(STAGING_SMOKE_WORKFLOW)
    text = STAGING_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    step_names = [step["name"] for step in workflow["jobs"]["staging-smoke"]["steps"]]

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert "pull_request" not in workflow["on"]
    assert "push" not in workflow["on"]
    assert "Ensure Evaluation User" in step_names
    assert step_names.index("Wait For Backend Readiness") < step_names.index("Ensure Evaluation User")
    assert step_names.index("Ensure Evaluation User") < step_names.index("Run Acceptance Smoke")

    for expected in [
        "docker run -d",
        "pgvector/pgvector:pg17",
        "redis:7-alpine",
        "python -m scripts.init_db --mode bootstrap",
        "python -m scripts.init_rag",
        "python -m uvicorn app.main:app",
        "python scripts/check_runtime_readiness.py",
        "/api/v1/users/login",
        "/api/v1/users/register",
        "users.noreply.github.com",
        "username_exists",
        "email_exists",
        "--acceptance-smoke",
    ]:
        assert expected in text


def test_staging_smoke_requires_github_secrets_without_hardcoded_credentials():
    workflow = _load_workflow(STAGING_SMOKE_WORKFLOW)
    text = STAGING_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    env = workflow["env"]
    for secret_name in REQUIRED_STAGING_SMOKE_SECRETS:
        assert env[secret_name] == f"${{{{ secrets.{secret_name} }}}}"
        assert f'"{secret_name}"' in text

    for marker in [
        "test / 000000",
        '"username": "test"',
        "'username': 'test'",
        "ZHIXING_EVAL_USERNAME: test",
        "ZHIXING_EVAL_PASSWORD: 000000",
        "test-key",
        "dev-only",
        "change-me",
        "your-",
        "dummy",
        "000000",
    ]:
        assert marker not in text


def test_staging_smoke_uploads_runtime_artifact_without_committing_outputs():
    text = STAGING_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "actions/upload-artifact@v4" in text
    assert "path: .runtime/acceptance-smoke" in text
    assert "blocked-secrets.txt" in text
    assert "if-no-files-found: error" in text
    assert ".runtime/" in gitignore


def test_ci_workflow_keeps_default_gate_separate_from_staging_smoke():
    workflow = _load_workflow(CI_WORKFLOW)
    text = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request" in workflow["on"]
    assert "push" in workflow["on"]
    assert "workflow_dispatch" in workflow["on"]
    assert "python -m compileall app tests scripts" in text
    assert "python scripts/validate_rag_knowledge.py" in text
    assert "python -m pytest --collect-only -q" in text
    assert "python -m pytest tests/test_ci_workflows.py -q" in text
    assert "python -m pytest -q" in text
    assert "scripts/check_runtime_readiness.py --target development --json" in text

    assert "acceptance-preflight" not in text
    assert "live-acceptance" not in text
    assert "run_live_acceptance" not in text
    assert "acceptance_base_url" not in text
    assert "${{ secrets.DASHSCOPE_API_KEY }}" not in text


def test_ci_runs_transaction_integration_against_disposable_postgres():
    workflow = _load_workflow(CI_WORKFLOW)
    job = workflow["jobs"]["postgres-integration"]
    postgres = job["services"]["postgres"]
    step_commands = "\n".join(str(step.get("run", "")) for step in job["steps"])

    assert job["runs-on"] == "ubuntu-latest"
    assert postgres["image"] == "postgres:17-alpine"
    assert postgres["env"] == {
        "POSTGRES_DB": "zhixing_ci",
        "POSTGRES_USER": "zhixing_ci",
        "POSTGRES_PASSWORD": "ci-only-password",
    }
    assert "5432:5432" in [str(port) for port in postgres["ports"]]
    assert "pg_isready -U zhixing_ci -d zhixing_ci" in postgres["options"]

    assert job["env"]["ZHIXING_DISABLE_DOTENV"] == "1"
    assert job["env"]["ZHIXING_TEST_POSTGRES_DSN"] == (
        "postgresql://zhixing_ci:ci-only-password@127.0.0.1:5432/zhixing_ci"
    )
    assert 'test -n "$ZHIXING_TEST_POSTGRES_DSN"' in step_commands
    assert (
        "python -m pytest --run-integration -q \\\n"
        "  tests/test_agency_transaction_postgres_integration.py \\\n"
        "  tests/test_agency_customer_lifecycle_postgres_integration.py \\\n"
        "  tests/test_agency_customer_claim_postgres_integration.py \\\n"
        "  tests/test_agency_branch_permissions_postgres_integration.py"
    ) in step_commands
    assert "scripts.init_db" not in step_commands
    assert "${{ secrets." not in str(job)
