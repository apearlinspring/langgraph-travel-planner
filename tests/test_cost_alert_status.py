import json

from scripts import check_cost_alert_status as cost


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_cost_alert_passes_with_zero_traffic_estimate():
    report = cost.build_cost_alert_status_report(
        daily_budget_cny="200 CNY/day",
        activity_counts={
            "message_total": 0,
            "message_user": 0,
            "message_assistant": 0,
            "tool_audit_total": 0,
        },
        owner_declared=True,
        manual_check_status="passed",
        allow_zero_traffic_estimate=True,
    )

    assert report["status"] == "passed"
    assert report["usage"]["spend_cny"] == 0
    assert report["usage"]["spend_source"] == "zero_traffic_estimate"
    assert report["declaration_statuses"]["ZHIXING_COST_ALERT_STATUS"] == "passed"


def test_cost_alert_blocks_zero_estimate_when_recent_activity_exists():
    report = cost.build_cost_alert_status_report(
        daily_budget_cny=200,
        activity_counts={"message_total": 3, "tool_audit_total": 0},
        owner_declared=True,
        manual_check_status="passed",
        allow_zero_traffic_estimate=True,
    )

    assert report["status"] == "blocked"
    assert any(item["metric"] == "cost_usage_sample" for item in report["blocked_reasons"])


def test_cost_alert_degrades_at_warning_ratio():
    report = cost.build_cost_alert_status_report(
        daily_budget_cny=100,
        estimated_spend_cny=85,
        owner_declared=True,
        manual_check_status="passed",
    )

    assert report["status"] == "degraded"
    assert report["usage"]["budget_usage_ratio"] == 0.85
    assert report["declaration_statuses"]["ZHIXING_COST_ALERT_STATUS"] == "degraded"


def test_cost_alert_blocks_at_blocking_ratio():
    report = cost.build_cost_alert_status_report(
        daily_budget_cny=100,
        actual_spend_cny=100,
        owner_declared=True,
        manual_check_status="passed",
    )

    assert report["status"] == "blocked"
    assert report["usage"]["budget_usage_ratio"] == 1.0
    assert any(item["metric"] == "budget_usage_ratio" for item in report["blocked_reasons"])


def test_cost_alert_degrades_without_owner_or_manual_check():
    report = cost.build_cost_alert_status_report(
        daily_budget_cny=100,
        estimated_spend_cny=1,
    )

    assert report["status"] == "degraded"
    assert {item["metric"] for item in report["degraded_reasons"]} == {
        "cost_owner",
        "manual_budget_check",
    }


def test_cost_alert_blocks_missing_budget():
    report = cost.build_cost_alert_status_report(
        estimated_spend_cny=1,
        owner_declared=True,
        manual_check_status="passed",
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["metric"] == "daily_budget_cny"


def test_cost_alert_blocks_missing_db_env_without_echoing_values():
    report = cost.build_cost_alert_status_report(
        environ={"POSTGRES_PASSWORD": "secret-should-not-leak"},
        daily_budget_cny=200,
        check_db_activity=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert "secret-should-not-leak" not in payload
    assert report["policy"]["reads_dotenv"] is False


def test_cost_alert_redacts_manual_status_text():
    report = cost.build_cost_alert_status_report(
        daily_budget_cny=200,
        estimated_spend_cny=1,
        owner_declared=True,
        manual_check_status="passed api_key=secret-token-123",
    )
    payload = _payload_text(report)

    assert "secret-token-123" not in payload
    assert "[REDACTED]" in payload
