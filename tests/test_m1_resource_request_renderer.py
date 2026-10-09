import json

from scripts import render_m1_resource_request as request


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
        "ZHIXING_POSTGRES_MODE": "managed PostgreSQL",
        "ZHIXING_REDIS_MODE": "managed Redis",
        "ZHIXING_SECRET_STORE": "cloud secret manager",
        "ZHIXING_SECRET_OWNER": "deployment lead",
        "ZHIXING_SECRET_ROTATION_CADENCE": "90 days",
        "ZHIXING_LLM_PROVIDER_READY": "yes",
        "ZHIXING_MAP_API_READY": "yes",
        "ZHIXING_OPTIONAL_EXTERNAL_APIS": "none",
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
        "DASHSCOPE_API_KEY": "dashscope-secret-should-not-appear",
        "JWT_SECRET_KEY": "jwt-secret-should-not-appear",
        "POSTGRES_PASSWORD": "postgres-secret-should-not-appear",
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_default_resource_request_is_sendable_and_redacted():
    report = request.build_m1_resource_request_report(environ={})
    payload = _payload_text(report)

    assert report["version"] == "m1_resource_request.v1"
    assert report["status"] == "ready_to_collect_resources"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["does_not_echo_values"] is True
    assert report["policy"]["requests_secret_values_in_chat_or_git"] is False
    assert report["current_env_summary"]["status"] == "blocked"
    assert report["current_env_summary"]["category_statuses"]["secrets"] == "blocked"
    assert "server_domain_tls" in payload
    assert "DASHSCOPE_API_KEY" in payload
    assert "真实值" not in payload or "不要" in payload


def test_resource_request_uses_current_env_status_without_echoing_values():
    env = _complete_m1_env()

    report = request.build_m1_resource_request_report(environ=env)
    payload = _payload_text(report)

    assert report["current_env_summary"]["status"] == "passed"
    assert report["current_env_summary"]["missing_or_blocked_env_vars"] == []
    assert all(item["value_echoed"] is False for item in report["non_secret_inputs"])
    assert all(item["value_echoed"] is False for item in report["secret_inputs"])
    for secret_or_value in [
        "internal testers",
        "https://m1.zhixing.example.net",
        "deployment lead",
        "release owner",
        "incident owner",
        "dashscope-secret-should-not-appear",
        "jwt-secret-should-not-appear",
        "postgres-secret-should-not-appear",
    ]:
        assert secret_or_value not in payload


def test_resource_request_markdown_contains_operator_sections():
    report = request.build_m1_resource_request_report(
        environ={},
        include_current_env_status=False,
    )

    markdown = request.build_m1_resource_request_markdown(report)

    assert "M1 Resource Request Pack" in markdown
    assert "资源组" in markdown
    assert "非密钥环境声明" in markdown
    assert "密钥变量" in markdown
    assert "真实值只放到服务器环境" in markdown
    assert "check_m1_launch_inputs.py --template" in markdown
    assert "check_m1_launch_inputs.py --input-json" in markdown
    assert "check_m1_first_deploy_dry_run.py" in markdown
    assert "render_server_env_checklist.py" in markdown
    assert "check_server_env_file.py" in markdown
    assert "build_release_artifact.py" in markdown
    assert "deploy/first-deploy.sh" in markdown
    assert "--archive-sha256" in markdown
    assert "collect_m1_go_no_go_evidence.py" in markdown


def test_resource_request_cli_writes_markdown(tmp_path):
    output = tmp_path / "request.md"

    code = request.main(["--no-current-env-status", "--output", str(output)])

    assert code == 0
    content = output.read_text(encoding="utf-8")
    assert "M1 Resource Request Pack" in content
    assert "DASHSCOPE_API_KEY" in content
