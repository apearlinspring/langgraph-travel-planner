import json
from pathlib import Path

from scripts import check_postgres_redis_ops_declaration_record as record


def _request():
    return {
        "version": "postgres_redis_ops_declaration_request.v1",
        "status": "blocked",
        "missing_count": 4,
        "execution_bucket_counts": {
            "can_prepare_from_live_probe": 2,
            "requires_backup_or_restore_artifact": 1,
            "requires_operator_confirmation": 1,
        },
        "declarations": [
            {
                "env_var": "ZHIXING_POSTGRES_MODE",
                "category": "service_mode",
                "suggested_value": "compose-postgresql single node for M1",
                "confidence": "suggested_from_live_probe",
                "execution_bucket": "can_prepare_from_live_probe",
            },
            {
                "env_var": "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS",
                "category": "redis_network",
                "suggested_value": "private internal network, not exposed",
                "confidence": "suggested_from_live_probe",
                "execution_bucket": "can_prepare_from_live_probe",
            },
            {
                "env_var": "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
                "category": "backup_restore",
                "suggested_value": "passed only after restore drill or pg_restore catalog check",
                "confidence": "requires_operator_confirmation",
                "execution_bucket": "requires_backup_or_restore_artifact",
            },
            {
                "env_var": "ZHIXING_RPO_TARGET",
                "category": "rpo_rto",
                "suggested_value": "24h for M1 controlled trial",
                "confidence": "requires_operator_confirmation",
                "execution_bucket": "requires_operator_confirmation",
            },
        ],
    }


def _accepted_record():
    return {
        "record_id": "postgres-redis-ops-declaration-20260625",
        "accepted_at": "2026-06-25T10:00:00+08:00",
        "scope": "M1 PostgreSQL/Redis non-secret operations declarations",
        "owner": "operations owner",
        "declarations": [
            {
                "env_var": "ZHIXING_POSTGRES_MODE",
                "accepted_value": "compose-postgresql single node for M1",
                "owner_confirmed": True,
                "evidence_ref": "postgres-redis-live-probe redacted json",
            },
            {
                "env_var": "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS",
                "accepted_value": "private internal network, not exposed",
                "owner_confirmed": True,
                "evidence_ref": "postgres-redis-live-probe redacted json",
            },
            {
                "env_var": "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
                "accepted_value": "passed after pg_restore catalog check completed",
                "owner_confirmed": True,
                "evidence_ref": "private restore drill report",
            },
            {
                "env_var": "ZHIXING_RPO_TARGET",
                "accepted_value": "24h for M1 controlled trial",
                "owner_confirmed": True,
                "evidence_ref": "owner accepted M1 RPO window",
            },
        ],
        "write_plan": {
            "target": "server_shared_env_or_secret_manager",
            "will_not_commit_to_git": True,
            "requires_rerun_ops_status": True,
            "requires_rerun_ops_summary": True,
            "requires_rerun_m1_go_no_go": True,
        },
        "redaction_boundary": {
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_ips_included": False,
            "dotenv_content_included": False,
            "server_paths_included": False,
        },
    }


def _payload_text(payload):
    return json.dumps(payload, ensure_ascii=False)


def test_declaration_record_passes_with_m1_degraded_compose_boundary():
    report = record.build_postgres_redis_ops_declaration_record_report(
        request=_request(),
        record=_accepted_record(),
    )
    payload = _payload_text(report)

    assert report["status"] == "degraded"
    assert report["checks"]["declarations"]["status"] == "degraded"
    assert report["declaration_statuses"][
        "ZHIXING_POSTGRES_REDIS_DECLARATION_READY_TO_WRITE_STATUS"
    ] == "passed"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["writes_server_env"] is False
    assert "24h for M1 controlled trial" not in payload
    assert "operations owner" not in payload


def test_declaration_record_blocks_unconfirmed_declaration():
    accepted = _accepted_record()
    accepted["declarations"][0]["owner_confirmed"] = False

    report = record.build_postgres_redis_ops_declaration_record_report(
        request=_request(),
        record=accepted,
    )

    assert report["status"] == "blocked"
    assert any(item["field"] == "ZHIXING_POSTGRES_MODE" for item in report["blocked_reasons"])


def test_declaration_record_blocks_invalid_rpo_window():
    accepted = _accepted_record()
    accepted["declarations"][3]["accepted_value"] = "daily"

    report = record.build_postgres_redis_ops_declaration_record_report(
        request=_request(),
        record=accepted,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["declarations"]["status"] == "blocked"


def test_declaration_record_blocks_raw_url_ip_or_secret():
    raw_secret = "secret-value-" + "123456"
    secret_assignment = "POSTGRES_" + "PASSWORD" + "=" + raw_secret
    raw_text = (
        json.dumps(_accepted_record(), ensure_ascii=False)
        + "\n"
        + "https://prod.example.com\n203.0.113.10\n"
        + secret_assignment
    )

    report = record.build_postgres_redis_ops_declaration_record_report(
        request=_request(),
        record=_accepted_record(),
        raw_text=raw_text,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert "prod.example.com" not in payload
    assert "203.0.113.10" not in payload
    assert raw_secret not in payload


def test_draft_from_request_keeps_manual_confirmation_blocked():
    draft = record.build_postgres_redis_ops_declaration_record_draft(_request())

    report = record.build_postgres_redis_ops_declaration_record_report(
        request=_request(),
        record=draft,
    )

    assert len(draft["declarations"]) == 4
    assert draft["declarations"][0]["accepted_value"] == "compose-postgresql single node for M1"
    assert draft["declarations"][0]["owner_confirmed"] is False
    assert draft["declarations"][2]["accepted_value"].startswith("<owner-confirmed-value-for-")
    assert report["status"] == "blocked"


def test_declaration_record_cli_writes_draft_and_report(tmp_path: Path):
    request_path = tmp_path / "request.json"
    record_path = tmp_path / "record.json"
    draft_path = tmp_path / "draft.json"
    report_path = tmp_path / "report.json"
    request_path.write_text(json.dumps(_request(), ensure_ascii=False), encoding="utf-8")
    record_path.write_text(json.dumps(_accepted_record(), ensure_ascii=False), encoding="utf-8")

    draft_code = record.main(
        [
            "--request-json",
            str(request_path),
            "--draft-from-request",
            "--output",
            str(draft_path),
        ]
    )
    report_code = record.main(
        [
            "--request-json",
            str(request_path),
            "--record-json",
            str(record_path),
            "--output",
            str(report_path),
        ]
    )

    assert draft_code == 0
    assert report_code == 0
    assert json.loads(draft_path.read_text(encoding="utf-8"))["declarations"]
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "degraded"
