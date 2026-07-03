import json
from pathlib import Path

from scripts import check_server_env_file as checker
from scripts.render_server_env_checklist import build_server_env_checklist_report


def _required_records():
    return [
        item
        for item in build_server_env_checklist_report()["env_vars"]
        if item["required_for_m1"]
    ]


def _value_for(item):
    env_var = item["env_var"]
    if item["secret"]:
        return "secret-value-123456"
    if env_var == "APP_ENV":
        return "staging"
    if env_var == "ZHIXING_REAL_PAYMENT_ORDER_DISABLED":
        return "true"
    if env_var.endswith("_BASE_URL") or env_var.endswith("_URL"):
        return "https://m1.zhixing.local"
    if env_var.endswith("_DIR") or env_var.endswith("_PATH"):
        return "/opt/zhixing/shared/data"
    if env_var.endswith("_READY") or env_var.endswith("_STATUS"):
        return "ready"
    if "BUDGET" in env_var:
        return "100 CNY per day"
    return "configured"


def _write_env_file(path: Path, overrides=None, omit=None):
    overrides = overrides or {}
    omit = set(omit or [])
    lines = []
    for item in _required_records():
        env_var = item["env_var"]
        if env_var in omit:
            continue
        lines.append(f"{env_var}={overrides.get(env_var, _value_for(item))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _payload(report):
    return json.dumps(report, ensure_ascii=False)


def test_complete_temp_server_env_passes_without_echoing_values(tmp_path):
    env_file = tmp_path / "server.env"
    _write_env_file(env_file)

    report = checker.build_server_env_file_check_report(env_file=env_file)
    payload = _payload(report)

    assert report["version"] == "server_env_file_check.v1"
    assert report["status"] == "passed"
    assert report["checked"] is True
    assert report["env_file_path_echoed"] is False
    assert report["missing_required_vars"] == []
    assert report["empty_required_vars"] == []
    assert report["placeholder_required_vars"] == []
    assert report["duplicate_vars"] == []
    assert "secret-value-123456" not in payload
    assert str(env_file) not in payload


def test_missing_empty_and_placeholder_required_vars_block(tmp_path):
    env_file = tmp_path / "server.env"
    _write_env_file(
        env_file,
        overrides={
            "JWT_SECRET_KEY": "",
            "APP_ENV": "<set-me>",
        },
        omit={"DASHSCOPE_API_KEY"},
    )

    report = checker.build_server_env_file_check_report(env_file=env_file)

    assert report["status"] == "blocked"
    assert "DASHSCOPE_API_KEY" in report["missing_required_vars"]
    assert "JWT_SECRET_KEY" in report["empty_required_vars"]
    assert "APP_ENV" in report["placeholder_required_vars"]
    assert {item["key"] for item in report["blocked_reasons"]} >= {
        "missing_required_vars",
        "empty_required_vars",
        "placeholder_required_vars",
    }


def test_duplicate_vars_block_without_echoing_values(tmp_path):
    env_file = tmp_path / "server.env"
    _write_env_file(env_file)
    with env_file.open("a", encoding="utf-8") as handle:
        handle.write("APP_ENV=production\n")

    report = checker.build_server_env_file_check_report(env_file=env_file)

    assert report["status"] == "blocked"
    assert report["duplicate_vars"] == ["APP_ENV"]
    assert "production" not in _payload(report)


def test_repo_local_env_is_refused_even_when_missing():
    report = checker.build_server_env_file_check_report(
        env_file=checker.PROJECT_ROOT / ".env",
    )

    assert report["status"] == "blocked"
    assert report["checked"] is False
    assert report["blocked_reasons"][0]["key"] == "refused_project_env"


def test_no_env_file_argument_is_blocked_plan_only():
    report = checker.build_server_env_file_check_report()

    assert report["status"] == "blocked"
    assert report["checked"] is False
    assert report["blocked_reasons"][0]["key"] == "env_file_required"


def test_cli_json_passes_for_complete_temp_env(tmp_path, capsys):
    env_file = tmp_path / "server.env"
    _write_env_file(env_file)

    code = checker.main(["--env-file", str(env_file), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == 0
    assert payload["status"] == "passed"
    assert str(env_file) not in output
    assert "secret-value-123456" not in output
