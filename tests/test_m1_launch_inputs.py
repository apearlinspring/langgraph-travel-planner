import json

from scripts import check_m1_launch_inputs as launch
from scripts.check_m1_launch_inputs import build_m1_launch_inputs_report


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
        "ZHIXING_OPTIONAL_EXTERNAL_APIS": "tavily,variflight,aigohotel",
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
    }


def test_m1_launch_inputs_block_when_missing():
    report = build_m1_launch_inputs_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_env_files"] is False
    assert report["policy"]["does_not_echo_values"] is True
    assert "ZHIXING_M1_AUDIENCE" in report["missing_or_blocked_env_vars"]
    assert "ZHIXING_REAL_PAYMENT_ORDER_DISABLED" in report["missing_or_blocked_env_vars"]
    assert report["blocked_count"] == report["input_count"]


def test_m1_launch_inputs_pass_with_complete_non_secret_env():
    env = _complete_m1_env()

    report = build_m1_launch_inputs_report(environ=env)
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    assert report["missing_or_blocked_env_vars"] == []
    assert report["passed_count"] == report["input_count"]
    for value in [
        "internal testers",
        "https://m1.zhixing.example.net",
        "deployment lead",
        "200 CNY per day",
        "release owner",
        "incident owner",
    ]:
        assert value not in payload
    assert all(item["value_echoed"] is False for item in report["checks"])


def test_m1_launch_inputs_template_is_blank_and_lists_all_inputs():
    template = launch.build_m1_launch_inputs_template()

    assert template["version"] == "m1_launch_inputs_template.v1"
    assert template["policy"]["do_not_put_real_secrets_here"] is True
    assert len(template["inputs"]) == len(launch.M1_INPUT_SPECS)
    assert all(item["value"] == "" for item in template["inputs"])
    assert any(item["env_var"] == "ZHIXING_PUBLIC_BASE_URL" for item in template["inputs"])


def test_m1_launch_inputs_can_validate_filled_json_values_without_echoing():
    env = _complete_m1_env()
    values = {spec.key: env[spec.env_var] for spec in launch.M1_INPUT_SPECS}

    report = build_m1_launch_inputs_report(input_values=values, source="unit-json")
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["source"] == "unit-json"
    assert report["policy"]["reads_input_json"] is True
    for value in [
        "internal testers",
        "https://m1.zhixing.example.net",
        "deployment lead",
        "200 CNY per day",
        "release owner",
        "incident owner",
    ]:
        assert value not in payload


def test_m1_launch_inputs_block_localhost_and_default_backup_dir():
    env = _complete_m1_env()
    env["ZHIXING_PUBLIC_BASE_URL"] = "http://127.0.0.1:8000"
    env["ZHIXING_EVAL_BASE_URL"] = "http://localhost:8000"
    env["ZHIXING_BACKUP_DIR"] = "./backups"

    report = build_m1_launch_inputs_report(environ=env)

    assert report["status"] == "blocked"
    assert "ZHIXING_PUBLIC_BASE_URL" in report["missing_or_blocked_env_vars"]
    assert "ZHIXING_EVAL_BASE_URL" in report["missing_or_blocked_env_vars"]
    assert "ZHIXING_BACKUP_DIR" in report["missing_or_blocked_env_vars"]


def test_m1_launch_inputs_block_if_payment_or_order_actions_are_enabled():
    env = _complete_m1_env()
    env["ZHIXING_REAL_PAYMENT_ORDER_DISABLED"] = "false"

    report = build_m1_launch_inputs_report(environ=env)

    assert report["status"] == "blocked"
    payment_check = next(
        item for item in report["checks"] if item["env_var"] == "ZHIXING_REAL_PAYMENT_ORDER_DISABLED"
    )
    assert "payment" in payment_check["finding"]


def test_m1_launch_inputs_cli_can_write_template(tmp_path, capsys):
    output_path = tmp_path / "m1-launch-inputs.template.json"

    code = launch.main(["--template", "--output", str(output_path)])
    captured = capsys.readouterr().out
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert "wrote" in captured
    assert payload["version"] == "m1_launch_inputs_template.v1"
    assert all(item["value"] == "" for item in payload["inputs"])


def test_m1_launch_inputs_cli_validates_input_json_without_echoing(tmp_path, capsys):
    env = _complete_m1_env()
    input_path = tmp_path / "m1-launch-inputs.local.json"
    input_path.write_text(
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

    code = launch.main(["--input-json", str(input_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    raw = json.dumps(payload, ensure_ascii=False)

    assert code == 0
    assert payload["status"] == "passed"
    assert payload["source"] == "input_json:m1-launch-inputs.local.json"
    assert "https://m1.zhixing.example.net" not in raw
    assert "deployment lead" not in raw


def test_m1_launch_inputs_cli_blocks_forbidden_input_file(tmp_path, capsys):
    input_path = tmp_path / ".env"
    input_path.write_text(json.dumps({"inputs": {}}), encoding="utf-8")

    code = launch.main(["--input-json", str(input_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "blocked"
    assert payload["blocked_reasons"][0]["key"] == "input_json"
    assert "Refusing to read" in payload["blocked_reasons"][0]["reason"]
