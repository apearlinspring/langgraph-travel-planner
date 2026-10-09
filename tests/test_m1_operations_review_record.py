import json
from pathlib import Path

from scripts import check_m1_operations_review_record as review


def _evidence_item(status="passed", reason=None):
    item = {"status": status, "raw_artifact_included": False}
    if reason:
        item["reason"] = reason
    return item


def _valid_record():
    return {
        "review_id": "m1-ops-review-20260624",
        "rollout_id": "m1-rollout-20260624",
        "reviewed_at": "2026-06-24T18:00:00+08:00",
        "environment": "m1_controlled_trial",
        "scope": "post-rollout operations review",
        "owners": {
            "operations_owner": "ops owner",
            "application_owner": "app owner",
            "database_owner": "db owner",
            "verifier": "verifier",
            "followup_owner": "followup owner",
        },
        "evidence_references": {
            "rollout_execution_record": _evidence_item(),
            "go_no_go_record": _evidence_item(),
            "server_capacity_snapshot": _evidence_item("degraded", "disk warning accepted for M1"),
            "postgres_redis_ops": _evidence_item(),
            "backup_restore": _evidence_item(),
            "restore_drill_feasibility": _evidence_item(),
            "external_dependency_resilience": _evidence_item(),
            "concurrency_rate_limit": _evidence_item(),
            "disk_remediation_approval_gate": _evidence_item(),
            "incident_rollback": _evidence_item(),
        },
        "issue_review": {
            "issues_observed": True,
            "items": [
                {
                    "category": "docker_disk",
                    "severity": "P2",
                    "signal": "disk guard warning during runtime image refresh",
                    "impact": "release stayed conditional until capacity was verified",
                    "root_cause": "old image layers accumulated",
                    "action_taken": "collected cleanup plan and reran capacity check",
                    "verification": "server preflight and health checks passed after mitigation",
                    "owner": "ops owner",
                    "status": "resolved",
                }
            ],
            "lessons_learned": "Keep disk cleanup plan ready before runtime image refresh.",
        },
        "ops_lessons": {
            "deployment": "Use manifest sha256 and release pointer checks.",
            "docker_disk": "Run disk guard before runtime image refresh.",
            "postgres": "Keep backup and migration ownership explicit.",
            "redis": "Keep Redis fail-closed for locks and rate limits.",
            "backup_restore": "Verify backup freshness and restore drill evidence.",
            "external_api": "Use bounded timeout, degraded response and cost guard.",
            "rate_limit": "Validate success before 429 and Retry-After headers.",
            "rollback": "Keep previous release and post-rollback smoke plan ready.",
        },
        "followups": [
            {
                "id": "OPS-001",
                "owner": "followup owner",
                "priority": "P2",
                "due_by": "2026-06-30",
                "action": "Add scheduled Docker image cleanup review.",
                "status": "open",
            }
        ],
        "m1_boundary": {
            "real_payment_enabled": False,
            "real_booking_enabled": False,
            "inventory_lock_enabled": False,
            "fulfillment_enabled": False,
            "claims_autoscaling_proven": False,
            "claims_multi_region_ha": False,
            "claims_long_duration_soak": False,
            "residual_risk": "M1 remains controlled trial, not full production HA.",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_server_paths_included": False,
            "raw_provider_response_body_included": False,
        },
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_valid_operations_review_passes_without_echoing_private_text():
    report = review.build_m1_operations_review_record_report(_valid_record())
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_M1_OPERATIONS_REVIEW_STATUS": "passed",
        "ZHIXING_M1_OPERATIONS_ISSUE_REVIEW_STATUS": "passed",
        "ZHIXING_M1_OPERATIONS_FOLLOWUP_STATUS": "passed",
        "ZHIXING_M1_OPERATIONS_BOUNDARY_STATUS": "passed",
    }
    assert report["record_summary"]["issue_count"] == 1
    assert report["record_summary"]["followup_count"] == 1
    assert report["policy"]["queries_database"] is False
    assert "disk guard warning" not in payload
    assert "ops owner" not in payload


def test_operations_review_blocks_missing_evidence_reason_for_degraded_reference():
    record = _valid_record()
    record["evidence_references"]["server_capacity_snapshot"] = _evidence_item("degraded")

    report = review.build_m1_operations_review_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["evidence_references"]["status"] == "blocked"


def test_operations_review_blocks_issue_without_risk_acceptance():
    record = _valid_record()
    record["issue_review"]["items"][0]["status"] = "monitoring"

    report = review.build_m1_operations_review_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["issue_review"]["status"] == "blocked"


def test_operations_review_blocks_missing_lessons():
    record = _valid_record()
    record["ops_lessons"]["redis"] = ""

    report = review.build_m1_operations_review_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["ops_lessons"]["status"] == "blocked"


def test_operations_review_blocks_boundary_overclaim():
    record = _valid_record()
    record["m1_boundary"]["claims_autoscaling_proven"] = True

    report = review.build_m1_operations_review_record_report(record)

    assert report["status"] == "blocked"
    assert report["checks"]["m1_boundary"]["status"] == "blocked"


def test_operations_review_blocks_raw_url_ip_secret_and_does_not_echo():
    record = _valid_record()
    raw_url = "https://" + "prod." + "example.com"
    raw_ip = "203.0." + "113.10"
    raw_secret = "secret-value-" + "123456"
    raw_text = (
        json.dumps(record, ensure_ascii=False)
        + f"\n{raw_url}\n{raw_ip}\napi_"
        + f"key={raw_secret}"
    )

    report = review.build_m1_operations_review_record_report(record, raw_text=raw_text)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["redaction_boundary"]["status"] == "blocked"
    assert raw_url not in payload
    assert raw_ip not in payload
    assert raw_secret not in payload


def test_operations_review_template_placeholders_do_not_validate_as_real_record():
    template = review._template_record()

    report = review.build_m1_operations_review_record_report(template)

    assert report["status"] == "blocked"
    assert report["checks"]["required_fields"]["status"] == "blocked"
    assert report["checks"]["owners"]["status"] == "blocked"


def test_operations_review_cli_reads_private_json(tmp_path: Path):
    record_path = tmp_path / "ops-review.json"
    output_path = tmp_path / "ops-review-report.json"
    record_path.write_text(json.dumps(_valid_record(), ensure_ascii=False), encoding="utf-8")

    code = review.main(["--record-json", str(record_path), "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "passed"


def _rollout_report(status="passed"):
    return {
        "version": "m1_rollout_execution_record.v1",
        "status": status,
        "record_summary": {
            "environment": "m1_controlled_trial",
            "issue_count": 0,
        },
    }


def _go_no_go_report(status="passed"):
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": status,
        "decision": "go_for_m1_controlled_trial",
        "section_statuses": {
            "server_capacity_snapshot": "passed",
            "postgres_redis_live_probe": "passed",
            "backup_restore_drill_evidence": "passed",
            "restore_drill_feasibility": "passed",
            "external_dependency_resilience_record": "passed",
            "live_concurrency_probe": "passed",
            "rate_limit_live_probe": "passed",
            "disk_remediation_approval_gate": "passed",
            "incident_rollback_evidence": "passed",
        },
    }


def _external_dependency_report(status="passed"):
    return {
        "version": "external_dependency_resilience_record.v1",
        "status": status,
        "record_summary": {
            "fallback_count": 2,
        },
    }


def test_operations_review_draft_backfills_evidence_statuses():
    draft = review.build_m1_operations_review_record_draft(
        rollout_report=_rollout_report(),
        go_no_go_report=_go_no_go_report(),
        external_dependency_report=_external_dependency_report(),
    )
    validation = review.build_m1_operations_review_record_report(draft)

    assert draft["draft_backfill"]["status"] == "needs_manual_completion"
    assert draft["draft_backfill"]["source_paths_echoed"] is False
    assert draft["evidence_references"]["rollout_execution_record"]["status"] == "passed"
    assert draft["evidence_references"]["go_no_go_record"]["status"] == "passed"
    assert draft["evidence_references"]["postgres_redis_ops"]["status"] == "passed"
    assert draft["evidence_references"]["restore_drill_feasibility"]["status"] == "passed"
    assert draft["evidence_references"]["external_dependency_resilience"]["status"] == "passed"
    assert draft["evidence_references"]["disk_remediation_approval_gate"]["status"] == "passed"
    assert draft["issue_review"]["issues_observed"] is False
    assert validation["status"] == "blocked"
    assert validation["checks"]["required_fields"]["status"] == "blocked"


def test_operations_review_draft_marks_non_passed_sources_blocked():
    draft = review.build_m1_operations_review_record_draft(
        rollout_report=_rollout_report(),
        go_no_go_report=_go_no_go_report(status="warning"),
        external_dependency_report=_external_dependency_report(),
    )

    assert draft["draft_backfill"]["status"] == "blocked"
    assert draft["evidence_references"]["go_no_go_record"]["status"] == "warning"
    assert draft["issue_review"]["issues_observed"] is True


def test_operations_review_draft_uses_non_passed_stateful_ops_summary():
    go_no_go = _go_no_go_report()
    go_no_go["section_statuses"]["postgres_redis_live_probe"] = "passed"
    go_no_go["section_statuses"]["postgres_redis_ops_summary"] = "blocked"

    draft = review.build_m1_operations_review_record_draft(
        rollout_report=_rollout_report(),
        go_no_go_report=go_no_go,
        external_dependency_report=_external_dependency_report(),
    )

    assert draft["draft_backfill"]["status"] == "needs_manual_completion"
    assert draft["evidence_references"]["postgres_redis_ops"]["status"] == "degraded"
    assert draft["issue_review"]["issues_observed"] is True


def test_operations_review_draft_surfaces_restore_and_disk_gate_blockers():
    go_no_go = _go_no_go_report(status="blocked")
    go_no_go["section_statuses"]["restore_drill_feasibility"] = "blocked"
    go_no_go["section_statuses"]["disk_remediation_approval_gate"] = "blocked"

    draft = review.build_m1_operations_review_record_draft(
        rollout_report=_rollout_report(),
        go_no_go_report=go_no_go,
        external_dependency_report=_external_dependency_report(),
    )

    assert draft["draft_backfill"]["status"] == "blocked"
    assert draft["evidence_references"]["restore_drill_feasibility"]["status"] == "degraded"
    assert draft["evidence_references"]["disk_remediation_approval_gate"]["status"] == "degraded"
    assert draft["evidence_references"]["restore_drill_feasibility"]["raw_artifact_included"] is False
    assert draft["evidence_references"]["disk_remediation_approval_gate"]["raw_artifact_included"] is False


def test_operations_review_draft_includes_build_cache_evidence_when_present():
    go_no_go = _go_no_go_report()
    go_no_go["section_statuses"]["docker_build_cache_cleanup_approval_gate"] = "degraded"
    go_no_go["section_statuses"]["docker_build_cache_post_cleanup"] = "passed"

    draft = review.build_m1_operations_review_record_draft(
        rollout_report=_rollout_report(),
        go_no_go_report=go_no_go,
        external_dependency_report=_external_dependency_report(),
    )

    refs = draft["evidence_references"]
    assert refs["docker_build_cache_cleanup_approval_gate"]["status"] == "degraded"
    assert refs["docker_build_cache_cleanup_approval_gate"]["raw_artifact_included"] is False
    assert refs["docker_build_cache_post_cleanup"]["status"] == "passed"
    assert draft["issue_review"]["items"][0]["category"] == "docker_disk"


def test_operations_review_draft_cli_reads_private_evidence_without_echoing_paths(tmp_path: Path):
    rollout_path = tmp_path / "rollout-report.json"
    go_no_go_path = tmp_path / "go-no-go.json"
    external_path = tmp_path / "external-dependency-report.json"
    output_path = tmp_path / "ops-review-draft.json"
    rollout_path.write_text(json.dumps(_rollout_report()), encoding="utf-8")
    go_no_go_path.write_text(json.dumps(_go_no_go_report()), encoding="utf-8")
    external_path.write_text(json.dumps(_external_dependency_report()), encoding="utf-8")

    code = review.main(
        [
            "--draft-from-evidence",
            "--rollout-report-json",
            str(rollout_path),
            "--go-no-go-json",
            str(go_no_go_path),
            "--external-dependency-json",
            str(external_path),
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")
    draft = json.loads(payload)

    assert code == 0
    assert draft["draft_backfill"]["status"] == "needs_manual_completion"
    assert "rollout-report.json" not in payload
    assert "go-no-go.json" not in payload
    assert "external-dependency-report.json" not in payload


def test_operations_review_draft_allows_missing_optional_external_dependency_report(tmp_path: Path):
    rollout_path = tmp_path / "rollout-report.json"
    go_no_go_path = tmp_path / "go-no-go.json"
    output_path = tmp_path / "ops-review-draft.json"
    go_no_go_report = _go_no_go_report()
    del go_no_go_report["section_statuses"]["external_dependency_resilience_record"]
    rollout_path.write_text(json.dumps(_rollout_report()), encoding="utf-8")
    go_no_go_path.write_text(json.dumps(go_no_go_report), encoding="utf-8")

    code = review.main(
        [
            "--draft-from-evidence",
            "--rollout-report-json",
            str(rollout_path),
            "--go-no-go-json",
            str(go_no_go_path),
            "--output",
            str(output_path),
        ]
    )
    draft = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert draft["draft_backfill"]["status"] == "needs_manual_completion"
    assert draft["evidence_references"]["external_dependency_resilience"]["status"] == "not_applicable"
    assert draft["draft_backfill"]["source_statuses"][2]["status"] == "not_provided"


def test_operations_review_draft_blocks_raw_sensitive_evidence_without_echoing(tmp_path: Path):
    rollout_path = tmp_path / "rollout-report.json"
    go_no_go_path = tmp_path / "go-no-go.json"
    external_path = tmp_path / "external-dependency-report.json"
    output_path = tmp_path / "ops-review-draft.json"
    raw_url = "https://" + "prod." + "example.com"
    rollout_path.write_text(
        json.dumps({"status": "passed", "raw": raw_url}),
        encoding="utf-8",
    )
    go_no_go_path.write_text(json.dumps(_go_no_go_report()), encoding="utf-8")
    external_path.write_text(json.dumps(_external_dependency_report()), encoding="utf-8")

    code = review.main(
        [
            "--draft-from-evidence",
            "--rollout-report-json",
            str(rollout_path),
            "--go-no-go-json",
            str(go_no_go_path),
            "--external-dependency-json",
            str(external_path),
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")
    draft = json.loads(payload)

    assert code == 2
    assert draft["draft_backfill"]["status"] == "blocked"
    assert raw_url not in payload
    assert "rollout-report.json" not in payload
