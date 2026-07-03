import json

from scripts import check_rollback_execution_record as rollback_record


def _valid_record():
    return {
        "window_id": "m1-real-rollback-20260624",
        "mode": "real_rollback",
        "started_at": "2026-06-24T13:00:00+08:00",
        "ended_at": "2026-06-24T13:20:00+08:00",
        "rollback_reason": "controlled rollback drill with private context",
        "source_release": "release-current-private",
        "target_release": "release-previous-private",
        "owners": {
            "rollback_owner": "alice private rollback owner",
            "incident_owner": "bob private incident owner",
            "verifier": "carol private verifier",
            "communications_owner": "dave private comms",
        },
        "execution": {
            "version_switch_executed": "passed",
            "service_restart_executed": "passed",
            "rollback_target_verified_before_switch": "passed",
            "release_pointer_verified_after_switch": "passed",
            "used_git_reset_hard": False,
            "used_bulk_delete": False,
            "changed_database_schema": False,
            "commands": [
                {"phase": "precheck", "summary": "verify private target release"},
                {"phase": "switch", "summary": "switch private release pointer"},
                {"phase": "restart", "summary": "restart backend and caddy"},
                {"phase": "verify", "summary": "run health and smoke"},
            ],
        },
        "data_safety": {
            "dotenv_untouched": "passed",
            "postgres_volume_untouched": "passed",
            "redis_volume_untouched": "passed",
            "vectorstore_untouched": "passed",
            "logs_untouched": "passed",
            "backup_verified_before_switch": "passed",
            "no_runtime_data_uploaded_from_local": "passed",
        },
        "post_rollback_health": {
            "live_status": "passed",
            "ready_status": "passed",
            "compose_status": "passed",
        },
        "post_rollback_smoke": {
            "m1_gate_status": "passed",
            "mock_checkout_boundary_status": "passed",
            "acceptance_smoke_status": "not_applicable",
            "acceptance_smoke_reason": "M1 rollback drill scoped to gate and mock checkout.",
        },
        "communication": {
            "stakeholders_updated": "passed",
            "rollback_window_closed": "passed",
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


def test_valid_rollback_execution_record_passes_without_echoing_private_text():
    report = rollback_record.build_rollback_execution_record_report(_valid_record())
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_ROLLBACK_DRILL_STATUS": "passed",
        "ZHIXING_ROLLBACK_TARGET_STATUS": "passed",
        "ZHIXING_POST_ROLLBACK_HEALTH_STATUS": "passed",
        "ZHIXING_POST_ROLLBACK_SMOKE_STATUS": "passed",
        "ZHIXING_ROLLBACK_DATA_SAFETY_STATUS": "passed",
    }
    assert "alice private rollback owner" not in payload
    assert "release-current-private" not in payload
    assert "controlled rollback drill with private context" not in payload
    assert report["policy"]["record_text_echoed"] is False


def test_missing_real_version_switch_blocks_rollback_drill_status():
    record = _valid_record()
    record["execution"]["version_switch_executed"] = "pending"

    report = rollback_record.build_rollback_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["execution"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_ROLLBACK_DRILL_STATUS"] == "blocked"


def test_unsafe_data_boundary_blocks_data_safety_status():
    record = _valid_record()
    record["data_safety"]["postgres_volume_untouched"] = "blocked"

    report = rollback_record.build_rollback_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["data_safety"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_ROLLBACK_DATA_SAFETY_STATUS"] == "blocked"


def test_missing_health_blocks_post_rollback_health_status():
    record = _valid_record()
    record["post_rollback_health"]["ready_status"] = "blocked"

    report = rollback_record.build_rollback_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["post_rollback_health"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_POST_ROLLBACK_HEALTH_STATUS"] == "blocked"


def test_missing_acceptance_skip_reason_blocks_smoke_status():
    record = _valid_record()
    record["post_rollback_smoke"]["acceptance_smoke_status"] = "skipped"
    record["post_rollback_smoke"]["acceptance_smoke_reason"] = ""

    report = rollback_record.build_rollback_execution_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["post_rollback_smoke"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_POST_ROLLBACK_SMOKE_STATUS"] == "blocked"


def test_secret_like_value_blocks_record_and_is_not_echoed():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\naccess_token=private-secret-token-123456"

    report = rollback_record.build_rollback_execution_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "private-secret-token-123456" not in payload


def test_template_contains_real_rollback_sections():
    template = rollback_record._template_record()

    assert template["mode"] == "real_rollback"
    assert "execution" in template
    assert "data_safety" in template
    assert "post_rollback_health" in template
    assert "post_rollback_smoke" in template


def test_template_placeholders_do_not_validate_as_real_record():
    template = rollback_record._template_record()

    report = rollback_record.build_rollback_execution_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"
