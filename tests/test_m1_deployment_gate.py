import json
import subprocess
from pathlib import Path

from scripts import check_m1_deployment_gate as gate


def _complete_m1_env() -> dict[str, str]:
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
        "ZHIXING_DEPLOY_DIR": "/opt/zhixing",
        "ZHIXING_SITE_ADDRESS": "m1.zhixing.example.net",
        "ZHIXING_DOCKER_STATUS": "ready",
        "ZHIXING_SERVER_PORTS_STATUS": "80 and 443 open",
        "ZHIXING_TLS_STATUS": "ready",
        "ZHIXING_REVERSE_PROXY_STATUS": "ready",
        "ZHIXING_POSTGRES_MODE": "managed PostgreSQL",
        "ZHIXING_REDIS_MODE": "managed Redis",
        "ZHIXING_SECRET_STORE": "cloud secret manager",
        "ZHIXING_SECRET_OWNER": "deployment lead",
        "ZHIXING_SECRET_ROTATION_CADENCE": "90 days",
        "ZHIXING_LLM_PROVIDER_READY": "yes",
        "ZHIXING_MAP_API_READY": "yes",
        "ZHIXING_OPTIONAL_EXTERNAL_APIS": "tavily,variflight,aigohotel",
        "ZHIXING_EXTERNAL_API_QUOTA_BUDGET": "LLM 200 CNY/day, map 10000 calls/day",
        "ZHIXING_PROVIDER_CONSOLE_OWNER": "provider owner",
        "ZHIXING_PROVIDER_SUPPORT_CHANNEL": "provider ticket and ops email",
        "ZHIXING_EXTERNAL_API_DEGRADATION_POLICY": "search can degrade; flight and hotel stay pending verification",
        "ZHIXING_EXTERNAL_API_TIMEOUT_RETRY_POLICY": "timeout 15 seconds, retry 1 time with backoff",
        "ZHIXING_TAVILY_SERVICE_STATUS": "ready",
        "ZHIXING_VARIFLIGHT_SERVICE_STATUS": "ready",
        "ZHIXING_AIGOHOTEL_SERVICE_STATUS": "ready",
        "ZHIXING_DATA_SCOPE": "public docs and desensitized route templates",
        "ZHIXING_ACCEPTANCE_WINDOW": "2026-06-30 20:00-22:00",
        "ZHIXING_EVAL_ACCOUNT_READY": "true",
        "ZHIXING_BACKUP_TARGET": "encrypted object storage",
        "ZHIXING_BACKUP_DIR": "/var/backups/zhixing",
        "ZHIXING_BACKUP_RETENTION": "7 daily backups and 3 release backups",
        "ZHIXING_RAG_RESTORE_STRATEGY": "rebuild from curated documents",
        "ZHIXING_MONITORING_PROVIDER": "cloud monitoring",
        "ZHIXING_ALERT_CHANNEL": "ops email",
        "ZHIXING_DAILY_COST_BUDGET": "200 CNY per day",
        "ZHIXING_ROLLBACK_OWNER": "release owner",
        "ZHIXING_INCIDENT_OWNER": "incident owner",
        "ZHIXING_LEAK_RESPONSE_OWNER": "security owner",
        "ZHIXING_JWT_SECRET_STATUS": "ready in secret store",
        "ZHIXING_PROVIDER_KEY_STATUS": "ready with budget caps",
        "ZHIXING_DATABASE_SECRET_STATUS": "managed and ready",
        "ZHIXING_REDIS_SECRET_STATUS": "rotated and ready",
        "ZHIXING_ALLOWED_ORIGINS_STATUS": "restricted to production domain",
    }


def test_m1_deployment_gate_blocks_missing_inputs_without_reading_dotenv():
    report = gate.build_m1_deployment_gate_report(
        environ={},
        check_public_boundary=False,
        check_release_freeze=False,
        check_compose_config=False,
        check_runtime=False,
    )

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["starts_services"] is False
    assert report["section_statuses"]["m1_launch_inputs"] == "blocked"
    assert any(item.get("env_var") == "ZHIXING_M1_AUDIENCE" for item in report["blocked_reasons"])


def test_m1_deployment_gate_passes_when_sections_pass_and_does_not_echo_inputs(monkeypatch):
    monkeypatch.setattr(
        gate,
        "build_public_release_boundary_report",
        lambda: {"status": "passed", "blocked_reasons": []},
    )
    monkeypatch.setattr(
        gate,
        "build_release_candidate_freeze_report",
        lambda: {"status": "passed", "blocked_reasons": []},
    )
    monkeypatch.setattr(
        gate,
        "build_compose_config_gate_report",
        lambda check=True: {"status": "passed", "checked": check, "blocked_reasons": []},
    )
    monkeypatch.setattr(
        gate,
        "build_runtime_readiness_report_without_dotenv",
        lambda **kwargs: {"status": "passed", "blocked_reasons": [], "received": kwargs},
    )
    monkeypatch.setattr(
        gate,
        "build_backup_restore_readiness_report",
        lambda **kwargs: {"status": "passed", "blocked_reasons": [], "received": kwargs},
    )
    monkeypatch.setattr(
        gate,
        "build_monitoring_alerting_readiness_report",
        lambda **kwargs: {"status": "passed", "blocked_reasons": [], "received": kwargs},
    )
    monkeypatch.setattr(
        gate,
        "build_security_release_readiness_report",
        lambda **kwargs: {"status": "passed", "blocked_reasons": [], "received": kwargs},
    )
    monkeypatch.setattr(
        gate,
        "build_external_api_readiness_report",
        lambda **kwargs: {"status": "passed", "blocked_reasons": [], "received": kwargs},
    )
    monkeypatch.setattr(
        gate,
        "build_server_preflight_readiness_report",
        lambda **kwargs: {"status": "passed", "blocked_reasons": [], "received": kwargs},
    )

    report = gate.build_m1_deployment_gate_report(environ=_complete_m1_env())
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["section_statuses"] == {
        "public_release_boundary": "passed",
        "release_candidate_freeze": "passed",
        "m1_launch_inputs": "passed",
        "server_preflight_readiness": "passed",
        "compose_config": "passed",
        "backup_restore_readiness": "passed",
        "external_api_readiness": "passed",
        "monitoring_alerting_readiness": "passed",
        "security_release_readiness": "passed",
        "runtime_readiness": "passed",
    }
    for value in [
        "internal testers",
        "https://m1.zhixing.example.net",
        "deployment lead",
        "200 CNY per day",
        "release owner",
        "incident owner",
        "security owner",
        "restricted to production domain",
        "provider owner",
        "provider ticket and ops email",
        "/opt/zhixing",
    ]:
        assert value not in payload


def test_m1_deployment_gate_can_use_non_secret_input_json(monkeypatch, tmp_path):
    for name in [
        "build_public_release_boundary_report",
        "build_release_candidate_freeze_report",
        "build_compose_config_gate_report",
        "build_backup_restore_readiness_report",
        "build_monitoring_alerting_readiness_report",
        "build_security_release_readiness_report",
        "build_external_api_readiness_report",
        "build_server_preflight_readiness_report",
        "build_runtime_readiness_report_without_dotenv",
    ]:
        monkeypatch.setattr(gate, name, lambda **kwargs: {"status": "passed", "blocked_reasons": []})

    input_path = tmp_path / "m1-launch-inputs.local.json"
    env = _complete_m1_env()
    input_path.write_text(
        json.dumps(
            {
                "inputs": [
                    {
                        "env_var": spec.env_var,
                        "value": env[spec.env_var],
                    }
                    for spec in gate.build_m1_launch_inputs_report.__globals__["M1_INPUT_SPECS"]
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    code = gate.main(["--m1-input-json", str(input_path), "--json"])

    assert code == 0


def test_m1_deployment_gate_treats_server_disk_warning_as_degraded(monkeypatch):
    for name in [
        "build_public_release_boundary_report",
        "build_release_candidate_freeze_report",
        "build_compose_config_gate_report",
        "build_backup_restore_readiness_report",
        "build_monitoring_alerting_readiness_report",
        "build_security_release_readiness_report",
        "build_external_api_readiness_report",
        "build_runtime_readiness_report_without_dotenv",
    ]:
        monkeypatch.setattr(gate, name, lambda **kwargs: {"status": "passed", "blocked_reasons": []})

    captured = {}

    def fake_server_preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": "warning",
            "warnings": [{"key": "disk_probe", "finding": "disk warning"}],
        }

    monkeypatch.setattr(gate, "build_server_preflight_readiness_report", fake_server_preflight)

    report = gate.build_m1_deployment_gate_report(
        environ=_complete_m1_env(),
        check_server_disk=True,
    )

    assert report["status"] == "degraded"
    assert report["section_statuses"]["server_preflight_readiness"] == "warning"
    assert captured["check_disk"] is True


def test_m1_deployment_gate_blocks_forbidden_m1_input_json(capsys, tmp_path):
    input_path = tmp_path / ".env"
    input_path.write_text(json.dumps({"inputs": {}}), encoding="utf-8")

    code = gate.main(
        [
            "--m1-input-json",
            str(input_path),
            "--skip-public-boundary",
            "--skip-release-freeze",
            "--skip-compose-config",
            "--skip-runtime",
            "--skip-server-preflight",
            "--skip-backup-readiness",
            "--skip-monitoring-readiness",
            "--skip-security-readiness",
            "--skip-external-api-readiness",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "blocked"
    assert payload["section_statuses"]["m1_launch_inputs"] == "blocked"
    assert payload["policy"]["uses_m1_input_json"] is True
    assert payload["blocked_reasons"][0]["key"] == "input_json"


def test_m1_deployment_gate_passes_no_dotenv_path_to_runtime(monkeypatch):
    captured = {}

    monkeypatch.setattr(gate, "build_public_release_boundary_report", lambda: {"status": "passed"})
    monkeypatch.setattr(gate, "build_release_candidate_freeze_report", lambda: {"status": "passed"})
    monkeypatch.setattr(gate, "build_compose_config_gate_report", lambda check=True: {"status": "passed"})
    monkeypatch.setattr(gate, "build_backup_restore_readiness_report", lambda **kwargs: {"status": "passed"})
    monkeypatch.setattr(gate, "build_monitoring_alerting_readiness_report", lambda **kwargs: {"status": "passed"})
    monkeypatch.setattr(gate, "build_security_release_readiness_report", lambda **kwargs: {"status": "passed"})
    monkeypatch.setattr(gate, "build_external_api_readiness_report", lambda **kwargs: {"status": "passed"})
    monkeypatch.setattr(gate, "build_server_preflight_readiness_report", lambda **kwargs: {"status": "passed"})

    def fake_runtime(**kwargs):
        captured.update(kwargs)
        return {"status": "passed", "blocked_reasons": []}

    monkeypatch.setattr(gate, "build_runtime_readiness_report_without_dotenv", fake_runtime)

    report = gate.build_m1_deployment_gate_report(
        environ=_complete_m1_env(),
        include_acceptance=True,
        check_backend=True,
        base_url="https://m1.zhixing.example.net",
    )

    assert report["status"] == "passed"
    assert captured["targets"] == ["production", "acceptance"]
    assert captured["check_backend"] is True
    assert captured["base_url"] == "https://m1.zhixing.example.net"
    assert isinstance(captured["dotenv_path"], Path)
    assert captured["dotenv_path"].name == "__m1_gate_does_not_read_dotenv__.env"


def test_m1_deployment_gate_blocks_when_release_candidate_is_not_frozen(monkeypatch):
    monkeypatch.setattr(gate, "build_public_release_boundary_report", lambda: {"status": "passed"})
    monkeypatch.setattr(
        gate,
        "build_release_candidate_freeze_report",
        lambda: {
            "status": "blocked",
            "blocked_reasons": [
                {
                    "key": "release_candidate_not_frozen",
                    "reason": "Working tree has uncommitted changes.",
                }
            ],
        },
    )

    report = gate.build_m1_deployment_gate_report(
        environ=_complete_m1_env(),
        check_compose_config=False,
        check_runtime=False,
        check_server_preflight=False,
        check_backup_readiness=False,
        check_monitoring_readiness=False,
        check_security_readiness=False,
        check_external_api_readiness=False,
    )

    assert report["status"] == "blocked"
    assert report["section_statuses"]["release_candidate_freeze"] == "blocked"
    assert any(item["key"] == "release_candidate_not_frozen" for item in report["blocked_reasons"])


def test_compose_config_gate_uses_env_example_without_starting_services(monkeypatch):
    calls = []

    def fake_run(args, *, timeout_seconds=30):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(gate, "_run_command", fake_run)

    report = gate.build_compose_config_gate_report()

    assert report["status"] == "passed"
    assert report["starts_services"] is False
    assert calls == [["docker", "compose", "--env-file", ".env.example", "config", "--quiet"]]


def test_compose_config_gate_blocks_on_render_error(monkeypatch):
    def fake_run(args, *, timeout_seconds=30):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="bad compose")

    monkeypatch.setattr(gate, "_run_command", fake_run)

    report = gate.build_compose_config_gate_report()

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "docker_compose_config"
    assert "bad compose" in report["findings"][0]
