import json
from pathlib import Path

from scripts import check_concurrency_rate_limit_evidence_record as evidence


def _valid_record():
    return {
        "record_id": "concurrency-rate-limit-20260624",
        "started_at": "2026-06-24T15:00:00+08:00",
        "ended_at": "2026-06-24T15:10:00+08:00",
        "scope": "M1 low-risk GET endpoints and API rate-limit probe",
        "owners": {
            "application_owner": "app owner",
            "test_owner": "test owner",
            "verifier": "verifier",
            "release_owner": "release owner",
        },
        "concurrency_probe": {
            "version": "live_concurrency_probe.v1",
            "status": "passed",
            "policy": {
                "http_methods": ["GET"],
                "reads_dotenv": False,
                "reads_response_body": False,
                "calls_llm": False,
                "calls_external_provider_apis": False,
                "creates_real_payment": False,
                "creates_real_booking": False,
                "locks_inventory": False,
                "url_echoed": False,
            },
            "thresholds": {"requests_per_endpoint": 30, "concurrency": 10, "max_p95_ms": 2000, "max_error_rate": 0},
            "endpoints": [
                {"status": "passed", "endpoint_key": "health_live", "request_count": 30, "success_count": 30, "error_rate": 0, "latency_ms": {"p95": 120}},
                {"status": "passed", "endpoint_key": "health_ready", "request_count": 30, "success_count": 30, "error_rate": 0, "latency_ms": {"p95": 180}},
                {"status": "passed", "endpoint_key": "mock_checkout_status", "request_count": 30, "success_count": 30, "error_rate": 0, "latency_ms": {"p95": 240}},
            ],
        },
        "rate_limit_probe": {
            "version": "rate_limit_live_probe.v1",
            "status": "passed",
            "policy": {
                "http_methods": ["GET"],
                "reads_dotenv": False,
                "reads_response_body": False,
                "calls_llm": False,
                "calls_external_provider_apis": False,
                "creates_real_payment": False,
                "creates_real_booking": False,
                "locks_inventory": False,
                "url_echoed": False,
            },
            "request_count": 130,
            "status_counts": {"200": 120, "429": 10},
            "rate_limit_headers_seen": {
                "x-ratelimit-limit": True,
                "x-ratelimit-reset": True,
                "retry-after": True,
            },
        },
        "rate_limit_config": {
            "api_rate_limit_enabled": True,
            "api_rate_limit_backend": "redis",
            "api_rate_limit_local_fallback": False,
            "redis_unavailable_behavior": "fail_closed_429",
            "protects_api_v1": True,
        },
        "m1_scope": {
            "calls_llm": False,
            "calls_external_provider_apis": False,
            "creates_real_payment": False,
            "creates_real_booking": False,
            "locks_inventory": False,
            "proves_chat_throughput": False,
            "proves_autoscaling": False,
            "proves_long_duration_soak": False,
            "residual_risk": "Low-risk probes do not prove chat throughput or autoscaling.",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_valid_concurrency_rate_limit_record_passes_without_echoing_private_text():
    record = _valid_record()

    report = evidence.build_concurrency_rate_limit_evidence_record_report(record)
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_CONCURRENCY_EVIDENCE_STATUS": "passed",
        "ZHIXING_RATE_LIMIT_EVIDENCE_STATUS": "passed",
        "ZHIXING_RATE_LIMIT_FAIL_CLOSED_STATUS": "passed",
        "ZHIXING_M1_CONCURRENCY_RATE_LIMIT_RECORD_STATUS": "passed",
    }
    assert report["record_summary"]["concurrency_total_requests"] == 90
    assert report["record_summary"]["worst_p95_ms"] == 240
    assert report["policy"]["runs_load_test"] is False
    assert "app owner" not in payload
    assert "M1 low-risk GET endpoints" not in payload


def test_record_blocks_missing_429_or_retry_after():
    record = _valid_record()
    record["rate_limit_probe"]["status_counts"] = {"200": 130}
    record["rate_limit_probe"]["rate_limit_headers_seen"]["retry-after"] = False

    report = evidence.build_concurrency_rate_limit_evidence_record_report(record)

    assert report["status"] == "blocked"
    keys = {item["field"] for item in report["blocked_reasons"]}
    assert "status_counts.429" in keys
    assert "headers.retry-after" in keys


def test_record_blocks_local_fallback_or_non_redis_backend():
    record = _valid_record()
    record["rate_limit_config"]["api_rate_limit_backend"] = "local"
    record["rate_limit_config"]["api_rate_limit_local_fallback"] = True

    report = evidence.build_concurrency_rate_limit_evidence_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["rate_limit_config"]["status"] == "blocked"
    fields = {item["field"] for item in report["blocked_reasons"]}
    assert "api_rate_limit_backend" in fields
    assert "api_rate_limit_local_fallback" in fields


def test_record_blocks_concurrency_endpoint_errors():
    record = _valid_record()
    record["concurrency_probe"]["endpoints"][1]["error_rate"] = 0.1

    report = evidence.build_concurrency_rate_limit_evidence_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["concurrency_probe"]["status"] == "blocked"


def test_record_blocks_scope_overclaiming_chat_throughput():
    record = _valid_record()
    record["m1_scope"]["proves_chat_throughput"] = True

    report = evidence.build_concurrency_rate_limit_evidence_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["m1_scope"]["status"] == "blocked"


def test_record_blocks_raw_url_ip_or_secret():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\nhttps://prod.example.com\n203.0.113.10\napi_key=secret-value-123456"

    report = evidence.build_concurrency_rate_limit_evidence_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "prod.example.com" not in payload
    assert "203.0.113.10" not in payload
    assert "secret-value-123456" not in payload


def test_template_placeholders_do_not_validate_as_real_record():
    template = evidence._template_record()

    report = evidence.build_concurrency_rate_limit_evidence_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"


def test_concurrency_rate_limit_record_cli_reads_private_json(tmp_path: Path):
    record_path = tmp_path / "record.json"
    output_path = tmp_path / "report.json"
    record_path.write_text(json.dumps(_valid_record(), ensure_ascii=False), encoding="utf-8")

    code = evidence.main(["--record-json", str(record_path), "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "passed"


def test_concurrency_rate_limit_record_cli_drafts_from_probe_json(tmp_path: Path):
    concurrency_path = tmp_path / "live-concurrency.json"
    rate_limit_path = tmp_path / "rate-limit.json"
    draft_path = tmp_path / "draft.json"
    record = _valid_record()
    concurrency_path.write_text(json.dumps(record["concurrency_probe"], ensure_ascii=False), encoding="utf-8")
    rate_limit_probe = dict(record["rate_limit_probe"])
    rate_limit_probe["rate_limit_header_observations"] = {
        "backend_values_seen": ["redis"],
        "limit_values_seen": [120],
    }
    rate_limit_path.write_text(json.dumps(rate_limit_probe, ensure_ascii=False), encoding="utf-8")

    code = evidence.main(
        [
            "--draft-from-probes",
            "--concurrency-probe-json",
            str(concurrency_path),
            "--rate-limit-probe-json",
            str(rate_limit_path),
            "--output",
            str(draft_path),
        ]
    )
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    report = evidence.build_concurrency_rate_limit_evidence_record_report(draft)

    assert code == 0
    assert draft["concurrency_probe"]["version"] == "live_concurrency_probe.v1"
    assert draft["rate_limit_probe"]["status_counts"] == {"200": 120, "429": 10}
    assert draft["rate_limit_config"]["api_rate_limit_backend"] == "redis"
    assert "rate_limit_config.redis_unavailable_behavior" in draft["manual_fields_remaining"]
    assert report["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"
