import json

from scripts import check_monitoring_alerting_readiness as readiness


def _valid_env() -> dict[str, str]:
    return {
        "ZHIXING_MONITORING_PROVIDER": "cloud monitoring",
        "ZHIXING_ALERT_CHANNEL": "ops email",
        "ZHIXING_DAILY_COST_BUDGET": "200 CNY per day",
        "ZHIXING_PUBLIC_BASE_URL": "https://m1.zhixing.example.net",
    }


def test_monitoring_readiness_blocks_missing_inputs_without_dotenv_or_network():
    report = readiness.build_monitoring_alerting_readiness_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["network_probe_requested"] is False
    assert report["health_probe"]["status"] == "not_checked"
    assert any(item["env_var"] == "ZHIXING_MONITORING_PROVIDER" for item in report["blocked_reasons"])


def test_monitoring_readiness_passes_declared_inputs_without_health_probe():
    report = readiness.build_monitoring_alerting_readiness_report(environ=_valid_env())
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["health_probe"]["status"] == "not_checked"
    assert "cloud monitoring" not in payload
    assert "ops email" not in payload
    assert "200 CNY per day" not in payload
    assert "https://m1.zhixing.example.net" not in payload


def test_monitoring_readiness_blocks_budget_without_number():
    env = _valid_env()
    env["ZHIXING_DAILY_COST_BUDGET"] = "daily budget set"

    report = readiness.build_monitoring_alerting_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_DAILY_COST_BUDGET" for item in report["blocked_reasons"])


def test_monitoring_health_probe_blocks_localhost_without_echoing_value():
    env = _valid_env()
    env["ZHIXING_PUBLIC_BASE_URL"] = "http://127.0.0.1:8000"

    report = readiness.build_monitoring_alerting_readiness_report(
        environ=env,
        check_health_url=True,
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "blocked"
    assert report["health_probe"]["status"] == "blocked"
    assert "localhost" in report["health_probe"]["finding"].lower()
    assert "127.0.0.1" not in payload


def test_monitoring_health_probe_passes_when_public_endpoints_respond(monkeypatch):
    calls = []

    def fake_probe(url, *, timeout_seconds):
        calls.append((url, timeout_seconds))
        return 200

    monkeypatch.setattr(readiness, "_probe_url", fake_probe)

    report = readiness.build_monitoring_alerting_readiness_report(
        environ=_valid_env(),
        check_health_url=True,
        timeout_seconds=1.5,
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["health_probe"]["status"] == "passed"
    assert [item["endpoint"] for item in report["health_probe"]["endpoints"]] == [
        "health/live",
        "health/ready",
    ]
    assert calls == [
        ("https://m1.zhixing.example.net/health/live", 1.5),
        ("https://m1.zhixing.example.net/health/ready", 1.5),
    ]
    assert "https://m1.zhixing.example.net" not in payload
