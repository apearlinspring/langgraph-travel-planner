import json
from pathlib import Path

from scripts import check_postgres_redis_recovery_record as recovery


def _valid_record():
    return {
        "record_id": "stateful-recovery-20260624",
        "mode": "combined_stateful_recovery_drill",
        "started_at": "2026-06-24T14:00:00+08:00",
        "ended_at": "2026-06-24T14:18:00+08:00",
        "trigger": "controlled stateful dependency drill",
        "scope": "M1 backend readiness and stateful dependency recovery",
        "affected_services": ["postgres", "redis"],
        "owners": {
            "database_owner": "database owner",
            "application_owner": "application owner",
            "verifier": "verifier",
            "communications_owner": "communications owner",
        },
        "actions": [
            {"phase": "detect", "summary": "confirm readiness degradation"},
            {"phase": "isolate", "summary": "pause traffic expansion and preserve data"},
            {"phase": "recover", "summary": "restart service from approved runbook"},
            {"phase": "verify", "summary": "run health and M1 gate"},
        ],
        "data_safety": {
            "dotenv_untouched": "passed",
            "postgres_volume_untouched": "passed",
            "redis_volume_untouched": "passed",
            "vectorstore_untouched": "passed",
            "no_database_drop": "passed",
            "no_redis_flushall": "passed",
            "backup_point_checked": "passed",
        },
        "post_recovery_health": {
            "backend_ready": "passed",
            "postgres_ready": "passed",
            "redis_ready": "passed",
            "m1_gate_status": "passed",
        },
        "observed_metrics": {
            "downtime_minutes": 2,
            "recovery_time_minutes": 12,
            "data_loss_detected": False,
        },
        "communication": {
            "stakeholders_updated": "passed",
            "incident_window_closed": "passed",
            "remaining_risks_recorded": "passed",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_valid_recovery_record_passes_without_echoing_private_text():
    record = _valid_record()
    report = recovery.build_postgres_redis_recovery_record_report(record)
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_POSTGRES_REDIS_RECOVERY_RECORD_STATUS": "passed",
        "ZHIXING_POSTGRES_RECOVERY_STATUS": "passed",
        "ZHIXING_REDIS_RECOVERY_STATUS": "passed",
        "ZHIXING_STATEFUL_DATA_SAFETY_STATUS": "passed",
    }
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["connects_database"] is False
    assert report["policy"]["connects_redis"] is False
    assert "controlled stateful dependency drill" not in payload
    assert "database owner" not in payload


def test_recovery_record_blocks_missing_action_phase():
    record = _valid_record()
    record["actions"] = [item for item in record["actions"] if item["phase"] != "verify"]

    report = recovery.build_postgres_redis_recovery_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["actions"]["status"] == "blocked"
    assert any(item["check"] == "actions" for item in report["blocked_reasons"])


def test_recovery_record_blocks_destructive_action_summary():
    record = _valid_record()
    record["actions"][2]["summary"] = "run redis-cli flushall and restart"

    report = recovery.build_postgres_redis_recovery_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["actions"]["status"] == "blocked"


def test_recovery_record_blocks_incomplete_data_safety():
    record = _valid_record()
    record["data_safety"]["postgres_volume_untouched"] = "blocked"

    report = recovery.build_postgres_redis_recovery_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["data_safety"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_STATEFUL_DATA_SAFETY_STATUS"] == "blocked"


def test_recovery_record_blocks_data_loss_detected():
    record = _valid_record()
    record["observed_metrics"]["data_loss_detected"] = True

    report = recovery.build_postgres_redis_recovery_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["observed_metrics"]["status"] == "blocked"


def test_recovery_record_marks_unaffected_service_not_applicable():
    record = _valid_record()
    record["mode"] = "redis_restart_drill"
    record["affected_services"] = ["redis"]

    report = recovery.build_postgres_redis_recovery_record_report(record)

    assert report["status"] == "passed"
    assert report["declaration_statuses"]["ZHIXING_POSTGRES_RECOVERY_STATUS"] == "not_applicable"
    assert report["declaration_statuses"]["ZHIXING_REDIS_RECOVERY_STATUS"] == "passed"


def test_recovery_record_blocks_raw_url_ip_or_secret():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\nhttps://prod.example.com\n203.0.113.10\npassword=secret-value-123456"

    report = recovery.build_postgres_redis_recovery_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "prod.example.com" not in payload
    assert "203.0.113.10" not in payload
    assert "secret-value-123456" not in payload


def test_template_placeholders_do_not_validate_as_real_record():
    template = recovery._template_record()

    report = recovery.build_postgres_redis_recovery_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"


def test_recovery_record_cli_reads_private_json(tmp_path: Path):
    record_path = tmp_path / "recovery.json"
    output_path = tmp_path / "report.json"
    record_path.write_text(json.dumps(_valid_record(), ensure_ascii=False), encoding="utf-8")

    code = recovery.main(["--record-json", str(record_path), "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "passed"
