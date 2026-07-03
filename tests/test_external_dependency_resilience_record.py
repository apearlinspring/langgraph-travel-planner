import json
from pathlib import Path

from scripts import check_external_dependency_resilience_record as evidence


def _valid_record():
    return {
        "record_id": "external-dependency-resilience-20260624",
        "started_at": "2026-06-24T16:00:00+08:00",
        "ended_at": "2026-06-24T16:20:00+08:00",
        "scope": "M1 LLM and external API resilience evidence",
        "owners": {
            "application_owner": "app owner",
            "provider_owner": "provider owner",
            "cost_owner": "cost owner",
            "verifier": "verifier",
            "release_owner": "release owner",
        },
        "external_api_readiness": {
            "version": "external_api_readiness.v1",
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "calls_external_providers": False,
                "reads_secret_values": False,
            },
            "optional_services": [],
            "blocked_reasons": [],
        },
        "cost_alert_status": {
            "version": "cost_alert_status.v1",
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "reads_message_content": False,
                "reads_provider_invoice": False,
                "secret_values_echoed": False,
            },
            "thresholds": {"daily_budget_cny": 200, "warn_ratio": 0.8, "block_ratio": 1.0},
            "usage": {
                "spend_cny": 20,
                "budget_usage_ratio": 0.1,
                "owner_declared": True,
                "manual_check_status": "passed",
            },
            "blocked_reasons": [],
        },
        "tool_failure_monitor": {
            "version": "tool_failure_monitor_status.v1",
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "reads_tool_input_output": False,
                "database_url_echoed": False,
                "secret_values_echoed": False,
            },
            "thresholds": {"max_failure_rate": 0.5},
            "summary": {"sample_count": 8, "failure_rate": 0.125},
            "blocked_reasons": [],
        },
        "timeout_retry_policy": {
            "llm_timeout_seconds": 60,
            "external_api_timeout_seconds": 15,
            "max_retries": 1,
            "backoff_enabled": True,
            "unbounded_retry": False,
            "fallback_behavior": "Degraded response with manual verification and pending external data.",
            "user_facing_degraded_message_defined": True,
        },
        "degradation_drill": {
            "status": "passed",
            "scenarios": [
                {
                    "scenario": "provider_timeout",
                    "status": "passed",
                    "user_visible_behavior": "Degraded response with pending verification.",
                    "fabricates_inventory": False,
                    "fabricates_locked_price": False,
                    "creates_payment": False,
                    "creates_booking": False,
                    "locks_inventory": False,
                },
                {
                    "scenario": "provider_rate_limit_429",
                    "status": "passed",
                    "user_visible_behavior": "Manual verification required after rate limit.",
                    "fabricates_inventory": False,
                    "fabricates_locked_price": False,
                    "creates_payment": False,
                    "creates_booking": False,
                    "locks_inventory": False,
                },
                {
                    "scenario": "provider_5xx",
                    "status": "passed",
                    "user_visible_behavior": "Fallback itinerary with external data pending verification.",
                    "fabricates_inventory": False,
                    "fabricates_locked_price": False,
                    "creates_payment": False,
                    "creates_booking": False,
                    "locks_inventory": False,
                },
            ],
        },
        "observed_metrics": {
            "external_error_count": 0,
            "timeout_count": 0,
            "fallback_count": 1,
            "cost_budget_usage_ratio": 0.1,
        },
        "m1_scope": {
            "real_payment_enabled": False,
            "real_booking_enabled": False,
            "inventory_lock_enabled": False,
            "fulfillment_enabled": False,
            "proves_provider_sla": False,
            "proves_provider_quota_enforcement": False,
            "proves_long_duration_soak": False,
            "proves_production_ha": False,
            "residual_risk": "M1 evidence does not prove provider SLA, full HA or long-duration soak.",
            "public_claims": ["M1 controlled trial only; external provider data may degrade to pending verification."],
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_provider_response_body_included": False,
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_valid_external_dependency_record_passes_without_echoing_private_text():
    record = _valid_record()

    report = evidence.build_external_dependency_resilience_record_report(record)
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_STATUS": "passed",
        "ZHIXING_EXTERNAL_API_DEGRADATION_STATUS": "passed",
        "ZHIXING_EXTERNAL_API_READINESS_STATUS": "passed",
        "ZHIXING_LLM_COST_GUARD_STATUS": "passed",
        "ZHIXING_TOOL_FAILURE_MONITOR_STATUS": "passed",
    }
    assert report["policy"]["calls_external_providers"] is False
    assert report["record_summary"]["degradation_scenario_count"] == 3
    assert "provider owner" not in payload
    assert "M1 LLM and external API resilience evidence" not in payload


def test_external_dependency_record_blocks_unbounded_timeout_retry_policy():
    record = _valid_record()
    record["timeout_retry_policy"]["max_retries"] = 10
    record["timeout_retry_policy"]["unbounded_retry"] = True

    report = evidence.build_external_dependency_resilience_record_report(record)

    assert report["status"] == "blocked"
    fields = {item["field"] for item in report["blocked_reasons"]}
    assert "max_retries" in fields
    assert "unbounded_retry" in fields


def test_external_dependency_record_blocks_cost_guard_over_budget_or_missing_owner():
    record = _valid_record()
    record["cost_alert_status"]["usage"]["budget_usage_ratio"] = 0.9
    record["cost_alert_status"]["usage"]["owner_declared"] = False

    report = evidence.build_external_dependency_resilience_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["cost_guard"]["status"] == "blocked"
    fields = {item["field"] for item in report["blocked_reasons"]}
    assert "usage.budget_usage_ratio" in fields
    assert "usage.owner_declared" in fields


def test_external_dependency_record_blocks_fabricated_inventory_or_locked_price():
    record = _valid_record()
    record["degradation_drill"]["scenarios"][0]["fabricates_inventory"] = True
    record["degradation_drill"]["scenarios"][1]["fabricates_locked_price"] = True

    report = evidence.build_external_dependency_resilience_record_report(record)

    assert report["status"] == "blocked"
    fields = {item["field"] for item in report["blocked_reasons"]}
    assert "provider_timeout.fabricates_inventory" in fields
    assert "provider_rate_limit_429.fabricates_locked_price" in fields


def test_external_dependency_record_blocks_tool_failure_monitor_blocked():
    record = _valid_record()
    record["tool_failure_monitor"]["status"] = "blocked"
    record["tool_failure_monitor"]["blocked_reasons"] = [{"metric": "failure_rate"}]

    report = evidence.build_external_dependency_resilience_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["tool_failure_monitor"]["status"] == "blocked"


def test_external_dependency_record_blocks_scope_overclaims_provider_sla():
    record = _valid_record()
    record["m1_scope"]["proves_provider_sla"] = True
    record["m1_scope"]["public_claims"] = ["Provider SLA guaranteed for production launch."]

    report = evidence.build_external_dependency_resilience_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["m1_scope"]["status"] == "blocked"


def test_external_dependency_record_blocks_raw_url_ip_or_secret():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\nhttps://prod.example.com\n203.0.113.10\napi_key=secret-value-123456"

    report = evidence.build_external_dependency_resilience_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "prod.example.com" not in payload
    assert "203.0.113.10" not in payload
    assert "secret-value-123456" not in payload


def test_template_placeholders_do_not_validate_as_real_record():
    template = evidence._template_record()

    report = evidence.build_external_dependency_resilience_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"


def test_external_dependency_record_cli_reads_private_json(tmp_path: Path):
    record_path = tmp_path / "record.json"
    output_path = tmp_path / "report.json"
    record_path.write_text(json.dumps(_valid_record(), ensure_ascii=False), encoding="utf-8")

    code = evidence.main(["--record-json", str(record_path), "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "passed"
