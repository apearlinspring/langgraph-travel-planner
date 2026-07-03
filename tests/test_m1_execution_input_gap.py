import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import check_m1_execution_input_gap as gap
from scripts import check_m1_launch_inputs as launch


def _complete_env() -> dict[str, str]:
    return {
        "ZHIXING_M1_AUDIENCE": "internal testers",
        "ZHIXING_REAL_PAYMENT_ORDER_DISABLED": "true",
        "ZHIXING_PUBLIC_BASE_URL": "https://m1.zhixing.example.net",
        "ZHIXING_EVAL_BASE_URL": "https://m1.zhixing.example.net",
        "ZHIXING_SERVER_PROVIDER": "cloud provider",
        "ZHIXING_SERVER_OS_VERSION": "Ubuntu 24.04",
        "ZHIXING_SERVER_CPU_RAM_DISK": "4 vCPU / 16 GB RAM / 160 GB SSD",
        "ZHIXING_DOMAIN_READY": "ready",
        "ZHIXING_SERVER_EGRESS_IP_STATUS": "fixed",
        "ZHIXING_DEPLOY_MODE": "Docker Compose",
        "ZHIXING_POSTGRES_MODE": "managed PostgreSQL",
        "ZHIXING_REDIS_MODE": "managed Redis",
        "ZHIXING_SECRET_STORE": "cloud secret manager",
        "ZHIXING_SECRET_OWNER": "deployment lead",
        "ZHIXING_SECRET_ROTATION_CADENCE": "90 days",
        "ZHIXING_LLM_PROVIDER_READY": "ready",
        "ZHIXING_MAP_API_READY": "ready",
        "ZHIXING_OPTIONAL_EXTERNAL_APIS": "tavily,variflight,aigohotel",
        "ZHIXING_DATA_SCOPE": "public docs and desensitized route templates",
        "ZHIXING_ACCEPTANCE_WINDOW": "2026-06-30 20:00-22:00",
        "ZHIXING_EVAL_ACCOUNT_READY": "true",
        "ZHIXING_BACKUP_TARGET": "encrypted object storage",
        "ZHIXING_BACKUP_DIR": "/var/backups/private-zhixing",
        "ZHIXING_BACKUP_RETENTION": "7 daily backups and 3 release backups",
        "ZHIXING_RAG_RESTORE_STRATEGY": "rebuild from curated documents",
        "ZHIXING_MONITORING_PROVIDER": "cloud monitoring",
        "ZHIXING_ALERT_CHANNEL": "ops email",
        "ZHIXING_DAILY_COST_BUDGET": "200 CNY per day",
        "ZHIXING_ROLLBACK_OWNER": "release owner",
        "ZHIXING_INCIDENT_OWNER": "incident owner",
        "ZHIXING_DEPLOY_USER": "deploy",
        "ZHIXING_DEPLOY_HOST": "203.0.113.10",
        "ZHIXING_DEPLOY_DIR": "/opt/private-zhixing",
        "ZHIXING_PROBE_ACCESS_TOKEN": "probe-token-redaction-sample",
    }


def _write_launch_inputs(path: Path, env: dict[str, str]) -> None:
    path.write_text(
        json.dumps(
            {
                "inputs": [
                    {
                        "env_var": spec.env_var,
                        "value": env[spec.env_var],
                    }
                    for spec in launch.M1_INPUT_SPECS
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_private_records(private_dir: Path) -> None:
    for filename in [
        "external-dependency-resilience-record.local.json",
        "m1-rollout-execution-record.local.json",
        "m1-operations-review-record.local.json",
    ]:
        (private_dir / filename).write_text(json.dumps({"status": "draft"}), encoding="utf-8")


def test_m1_execution_input_gap_blocks_when_everything_is_missing():
    report = gap.build_m1_execution_input_gap_report(
        environ={},
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    assert report["status"] == "blocked_missing_private_input"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["runs_live_probes"] is False
    assert report["checks"]["private_workdir"]["status"] == "blocked"
    assert report["missing_for_user"]["m1_launch_inputs"]
    assert report["missing_for_user"]["private_live_inputs"]
    assert report["missing_for_user"]["private_record_inputs"]


def test_m1_execution_input_gap_ready_with_complete_private_inputs(tmp_path: Path):
    env = _complete_env()
    private_dir = tmp_path / "m1-private"
    private_dir.mkdir()
    launch_path = private_dir / "m1-launch-inputs.local.json"
    _write_launch_inputs(launch_path, env)
    _write_private_records(private_dir)

    report = gap.build_m1_execution_input_gap_report(
        environ=env,
        private_workdir=private_dir,
        m1_input_json=launch_path,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "ready_to_execute_private_m1"
    assert report["checks"]["m1_launch_inputs"]["status"] == "passed"
    assert report["checks"]["private_live_workflow_inputs"]["status"] == "passed"
    assert report["checks"]["private_record_inputs"]["status"] == "passed"
    for raw_value in [
        "https://m1.zhixing.example.net",
        "203.0.113.10",
        "probe-token-redaction-sample",
        str(private_dir),
        "/opt/private-zhixing",
        "/var/backups/private-zhixing",
        "deployment lead",
    ]:
        assert raw_value not in payload


def test_m1_execution_input_gap_blocks_project_private_workdir():
    report = gap.build_m1_execution_input_gap_report(
        environ={},
        private_workdir=gap.PROJECT_ROOT / "m1-private",
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    assert report["status"] == "blocked_sensitive_boundary"
    assert report["checks"]["private_workdir"]["inside_project"] is True
    assert report["checks"]["private_workdir"]["path_echoed"] is False


def test_m1_execution_input_gap_blocks_project_launch_input_json(tmp_path: Path):
    env = _complete_env()
    private_dir = tmp_path / "m1-private"
    private_dir.mkdir()
    _write_private_records(private_dir)
    project_input = gap.PROJECT_ROOT / "m1-launch-inputs.local.json"

    report = gap.build_m1_execution_input_gap_report(
        environ=env,
        private_workdir=private_dir,
        m1_input_json=project_input,
        generated_at=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )

    assert report["status"] == "blocked_sensitive_boundary"
    assert report["checks"]["m1_launch_inputs"]["status"] == "blocked"
    assert report["missing_for_user"]["m1_launch_inputs"][0]["key"] == "m1_input_json"


def test_m1_execution_input_gap_cli_markdown_does_not_echo_values(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    env = _complete_env()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    private_dir = tmp_path / "m1-private"
    private_dir.mkdir()
    launch_path = private_dir / "m1-launch-inputs.local.json"
    _write_launch_inputs(launch_path, env)
    _write_private_records(private_dir)

    code = gap.main(
        [
            "--private-workdir",
            str(private_dir),
            "--m1-input-json",
            str(launch_path),
            "--markdown",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "ready_to_execute_private_m1" in output
    assert "https://m1.zhixing.example.net" not in output
    assert "203.0.113.10" not in output
    assert "probe-token-redaction-sample" not in output
    assert str(private_dir) not in output
