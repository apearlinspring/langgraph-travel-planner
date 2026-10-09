import json

from scripts import check_incident_tabletop_status as tabletop


def _valid_record():
    return {
        "drill_id": "m1-tabletop-20260624",
        "scenario": "health readiness degraded after M1 release",
        "severity": "P1",
        "started_at": "2026-06-24T12:30:00+08:00",
        "detected_by": "health/readiness alert drill",
        "customer_impact": "M1 trial only; no real payment or booking.",
        "rollback_decision": "prepare rollback if health remains blocked",
        "owners": {
            "incident_commander": "ops owner private name",
            "rollback_owner": "release owner private name",
            "communications_owner": "communication owner private name",
            "scribe": "scribe private name",
        },
        "timeline": [
            {"phase": "detect", "minute": 0, "owner_role": "incident", "action": "ack"},
            {"phase": "triage", "minute": 5, "owner_role": "release", "action": "check"},
            {"phase": "mitigate", "minute": 15, "owner_role": "release", "action": "fix"},
            {"phase": "validate", "minute": 25, "owner_role": "incident", "action": "verify"},
            {"phase": "communicate", "minute": 30, "owner_role": "comm", "action": "update"},
        ],
        "response_actions": [
            {"action": "pause M1", "owner_role": "incident", "status": "passed"},
            {"action": "check rollback", "owner_role": "release", "status": "passed"},
            {"action": "rerun health", "owner_role": "incident", "status": "passed"},
        ],
        "communication": {
            "channels": ["internal ops note"],
            "cadence": "15 minutes then 30 minutes",
            "holding_statement": "M1 trial degraded; no real transaction impact.",
        },
        "review": {
            "root_cause_hypothesis": "release or dependency degradation",
            "impact_summary": "M1 trial only",
            "what_went_well": ["health check exists"],
            "gaps": ["real rollback not executed"],
            "remaining_risks": ["post rollback smoke pending"],
            "follow_up_items": [
                {"action": "schedule rollback drill", "owner_role": "release", "due_by": "2026-06-30"}
            ],
        },
        "severity_policy": {
            "severity_matrix_used": "passed",
            "escalation_owner_declared": "passed",
            "trial_pause_rule_checked": "passed",
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


def test_valid_incident_tabletop_record_passes_without_echoing_private_text():
    record = _valid_record()

    report = tabletop.build_incident_tabletop_status_report(record)
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_INCIDENT_RESPONSE_STATUS": "passed",
        "ZHIXING_INCIDENT_REVIEW_STATUS": "passed",
        "ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS": "passed",
        "ZHIXING_INCIDENT_COMMUNICATION_STATUS": "passed",
    }
    assert "ops owner private name" not in payload
    assert "release or dependency degradation" not in payload
    assert report["policy"]["record_text_echoed"] is False


def test_missing_communication_blocks_record():
    record = _valid_record()
    record["communication"] = {"channels": []}

    report = tabletop.build_incident_tabletop_status_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["communication"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_INCIDENT_COMMUNICATION_STATUS"] == "blocked"


def test_incomplete_review_blocks_record():
    record = _valid_record()
    record["review"]["follow_up_items"] = []

    report = tabletop.build_incident_tabletop_status_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["review"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_INCIDENT_REVIEW_STATUS"] == "blocked"


def test_secret_like_value_blocks_record_and_is_not_echoed():
    record = _valid_record()
    raw_text = json.dumps(record, ensure_ascii=False) + "\napi_key=secret-value-123456"

    report = tabletop.build_incident_tabletop_status_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "secret-value-123456" not in payload


def test_template_contains_required_sections():
    template = tabletop._template_record()

    assert "timeline" in template
    assert "review" in template
    assert "redaction_boundary" in template
