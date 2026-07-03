import json

from scripts import collect_monitoring_alerting_evidence as evidence


PUBLIC_URL = "https://m1.zhixing.com"


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _valid_env() -> dict[str, str]:
    return {
        "ZHIXING_PUBLIC_BASE_URL": PUBLIC_URL,
        "ZHIXING_MONITORING_PROVIDER": "cloud monitoring",
        "ZHIXING_ALERT_CHANNEL": "ops email",
        "ZHIXING_DAILY_COST_BUDGET": "200 CNY per day",
        "ZHIXING_HEALTH_ALERT_DELIVERY_STATUS": "passed",
        "ZHIXING_READINESS_ALERT_DELIVERY_STATUS": "passed",
        "ZHIXING_ALERT_DRILL_OWNER": "ops owner",
        "ZHIXING_ALERT_DRILL_WINDOW": "2026-06-30 20:00",
        "ZHIXING_ERROR_RATE_MONITOR_STATUS": "passed",
        "ZHIXING_P95_LATENCY_MONITOR_STATUS": "passed",
        "ZHIXING_TOOL_FAILURE_MONITOR_STATUS": "passed",
        "ZHIXING_COST_ALERT_STATUS": "passed",
        "ZHIXING_BACKUP_ALERT_STATUS": "passed",
        "ZHIXING_LOG_REDACTION_SAMPLE_STATUS": "passed",
    }


def test_default_monitoring_alerting_evidence_is_plan_only():
    report = evidence.build_monitoring_alerting_evidence_report(environ={})

    assert report["status"] == "not_checked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["sends_alerts"] is False
    assert report["sections"] == {}
    assert "manual alert drill" in _payload_text(report)


def test_alert_delivery_declaration_blocks_missing_values():
    report = evidence.build_monitoring_alerting_evidence_report(
        environ={},
        require_alert_delivery_declaration=True,
    )

    assert report["status"] == "blocked"
    blockers = report["sections"]["alert_delivery_declaration"]["blocked_reasons"]
    assert {item["env_var"] for item in blockers} == {
        "ZHIXING_HEALTH_ALERT_DELIVERY_STATUS",
        "ZHIXING_READINESS_ALERT_DELIVERY_STATUS",
        "ZHIXING_ALERT_DRILL_OWNER",
        "ZHIXING_ALERT_DRILL_WINDOW",
    }


def test_alert_and_metric_declarations_pass_without_echoing_values():
    report = evidence.build_monitoring_alerting_evidence_report(
        environ=_valid_env(),
        require_alert_delivery_declaration=True,
        require_metric_declaration=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["sections"]["alert_delivery_declaration"]["status"] == "passed"
    assert report["sections"]["metric_monitoring_declaration"]["status"] == "passed"
    assert "ops owner" not in payload
    assert "ops email" not in payload
    assert "200 CNY per day" not in payload
    assert PUBLIC_URL not in payload


def test_metric_declaration_can_be_degraded_for_not_measured_values():
    env = _valid_env()
    env["ZHIXING_P95_LATENCY_MONITOR_STATUS"] = "not measured"

    report = evidence.build_monitoring_alerting_evidence_report(
        environ=env,
        require_alert_delivery_declaration=True,
        require_metric_declaration=True,
    )

    assert report["status"] == "degraded"
    metric = report["sections"]["metric_monitoring_declaration"]
    assert metric["status"] == "degraded"
    assert any(item["env_var"] == "ZHIXING_P95_LATENCY_MONITOR_STATUS" for item in metric["degraded_reasons"])


def test_include_readiness_embeds_redacted_readiness(monkeypatch):
    captured = {}

    def fake_readiness(**kwargs):
        captured.update(kwargs)
        return {
            "status": "passed",
            "checks": [{"status": "passed", "finding": "ok"}],
            "base_url": kwargs["environ"]["ZHIXING_PUBLIC_BASE_URL"],
        }

    monkeypatch.setattr(evidence, "build_monitoring_alerting_readiness_report", fake_readiness)

    report = evidence.build_monitoring_alerting_evidence_report(
        environ=_valid_env(),
        include_readiness=True,
        check_health_url=True,
        timeout_seconds=1.5,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert captured["check_health_url"] is True
    assert captured["timeout_seconds"] == 1.5
    assert report["sections"]["monitoring_alerting_readiness"]["base_url"] == "<public-url>"
    assert PUBLIC_URL not in payload


def test_monitoring_alerting_evidence_markdown_keeps_boundary():
    report = evidence.build_monitoring_alerting_evidence_report(environ={})

    markdown = evidence.build_monitoring_alerting_evidence_markdown(report)

    assert "Monitoring Alerting Evidence" in markdown
    assert "Plan-only mode proves no alert delivery" in markdown
    assert "Sends alerts" in markdown
