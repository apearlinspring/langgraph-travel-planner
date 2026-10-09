import hashlib
import json
from pathlib import Path

from scripts import check_m1_private_evidence_signoff as signoff


STANDARD_SECTIONS = {
    "backup_schedule_live_probe",
    "docker_disk_cleanup_plan",
    "live_concurrency_probe",
    "live_server_probe",
    "postgres_redis_live_probe",
    "probe_auth_readiness",
    "rate_limit_live_probe",
    "server_capacity_snapshot",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_private_evidence(
    tmp_path: Path,
    *,
    decision: str = "go_for_m1_controlled_trial",
    include_review_sections: bool = False,
) -> Path:
    go_no_go = tmp_path / "m1-go-no-go.private.json"
    summary = tmp_path / "m1-live-evidence-summary.md"
    bundle_dir = tmp_path / "m1-evidence-bundle"
    bundle_dir.mkdir()
    manifest = bundle_dir / "manifest.json"
    workflow_report = tmp_path / "workflow-report.json"
    go_no_go.write_text('{"status":"passed"}\n', encoding="utf-8")
    summary.write_text("# summary\n", encoding="utf-8")
    manifest.write_text('{"status":"passed"}\n', encoding="utf-8")
    report = {
        "version": "m1_private_live_evidence_workflow.v1",
        "status": "passed" if decision == "go_for_m1_controlled_trial" else "degraded",
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "deploys_code": False,
            "deletes_files": False,
            "records_public_url": False,
            "records_server_ip": False,
            "records_credentials": False,
            "output_should_remain_private": True,
        },
        "target": {
            "output_dir_inside_project": False,
        },
        "selected_sections": sorted(STANDARD_SECTIONS),
        "missing_inputs_for_user": [],
        "go_no_go": {
            "status": "passed" if decision == "go_for_m1_controlled_trial" else "degraded",
            "decision": decision,
            "section_statuses": {
                section: "passed"
                for section in STANDARD_SECTIONS
            },
        },
        "artifacts": [
            {
                "role": "private_go_no_go_json",
                "path": "m1-go-no-go.private.json",
                "sha256": _sha256(go_no_go),
            },
            {
                "role": "live_evidence_summary_markdown",
                "path": "m1-live-evidence-summary.md",
                "sha256": _sha256(summary),
            },
            {"role": "evidence_bundle_dir", "path": "m1-evidence-bundle"},
            {
                "role": "evidence_bundle_manifest",
                "path": "m1-evidence-bundle/manifest.json",
                "sha256": _sha256(manifest),
            },
            {"role": "workflow_report_json", "path": "workflow-report.json"},
        ],
    }
    if include_review_sections:
        for section in ("m1_rollout_execution_record", "m1_operations_review_record"):
            report["selected_sections"].append(section)
            report["go_no_go"]["section_statuses"][section] = "passed"
        report["selected_sections"] = sorted(set(report["selected_sections"]))
    workflow_report.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return workflow_report


def _rollout_report(status="passed"):
    return {
        "version": "m1_rollout_execution_record.v1",
        "status": status,
        "checks": {},
        "declaration_statuses": {
            "ZHIXING_M1_ROLLOUT_EXECUTION_STATUS": status,
        },
    }


def _operations_review_report(status="passed"):
    return {
        "version": "m1_operations_review_record.v1",
        "status": status,
        "checks": {},
        "declaration_statuses": {
            "ZHIXING_M1_OPERATIONS_REVIEW_STATUS": status,
        },
    }


def _report_from_path(path: Path, **kwargs):
    return signoff.build_m1_private_evidence_signoff_report(
        json.loads(path.read_text(encoding="utf-8")),
        workflow_report_path=path,
        evidence_dir=path.parent,
        raw_text=path.read_text(encoding="utf-8"),
        signoff_owner="release-owner",
        **kwargs,
    )


def test_private_evidence_signoff_passes_with_hashes_and_owner(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)

    report = _report_from_path(workflow_report)

    assert report["status"] == "passed"
    assert report["checks"]["artifacts"]["checked_hash_count"] == 3
    assert report["declaration_statuses"] == {
        "ZHIXING_M1_PRIVATE_EVIDENCE_SIGNOFF_STATUS": "passed",
        "ZHIXING_M1_PRIVATE_EVIDENCE_ARTIFACT_STATUS": "passed",
        "ZHIXING_M1_PRIVATE_EVIDENCE_DECISION_STATUS": "passed",
        "ZHIXING_M1_PRIVATE_REVIEW_REPORT_STATUS": "passed",
    }
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["runs_live_probes"] is False


def test_private_evidence_signoff_requires_review_reports_for_selected_sections(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path, include_review_sections=True)

    report = _report_from_path(workflow_report)

    assert report["status"] == "blocked"
    assert report["checks"]["private_review_reports"]["status"] == "blocked"
    keys = {item["key"] for item in report["blocked_reasons"]}
    assert {"rollout_report_json", "operations_review_report_json"} <= keys


def test_private_evidence_signoff_passes_with_review_reports_for_selected_sections(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path, include_review_sections=True)
    workflow_payload = json.loads(workflow_report.read_text(encoding="utf-8"))

    report = signoff.build_m1_private_evidence_signoff_report(
        workflow_payload,
        workflow_report_path=workflow_report,
        evidence_dir=tmp_path,
        raw_text=workflow_report.read_text(encoding="utf-8"),
        signoff_owner="release-owner",
        rollout_report=_rollout_report(),
        operations_review_report=_operations_review_report(),
    )

    assert report["status"] == "passed"
    assert report["checks"]["private_review_reports"] == {
        "status": "passed",
        "blocked_reasons": [],
        "rollout_report_required": True,
        "operations_review_report_required": True,
        "rollout_report_provided": True,
        "operations_review_report_provided": True,
        "source_statuses": [],
        "source_paths_echoed": False,
        "value_echoed": False,
    }


def test_private_evidence_signoff_passes_selected_live_chat_concurrency_section(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)
    payload = json.loads(workflow_report.read_text(encoding="utf-8"))
    payload["selected_sections"].append("live_chat_concurrency_probe")
    payload["selected_sections"] = sorted(set(payload["selected_sections"]))
    payload["go_no_go"]["section_statuses"]["live_chat_concurrency_probe"] = "passed"
    workflow_report.write_text(json.dumps(payload), encoding="utf-8")

    report = _report_from_path(workflow_report)

    assert report["status"] == "passed"
    assert report["checks"]["sections"]["status"] == "passed"


def test_private_evidence_signoff_blocks_selected_section_missing_status(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)
    payload = json.loads(workflow_report.read_text(encoding="utf-8"))
    payload["selected_sections"].append("live_chat_concurrency_probe")
    payload["selected_sections"] = sorted(set(payload["selected_sections"]))
    workflow_report.write_text(json.dumps(payload), encoding="utf-8")

    report = _report_from_path(workflow_report)

    assert report["status"] == "blocked"
    assert any(
        item["key"] == "missing_selected_section_statuses"
        for item in report["blocked_reasons"]
    )


def test_private_evidence_signoff_blocks_failed_review_report(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path, include_review_sections=True)
    workflow_payload = json.loads(workflow_report.read_text(encoding="utf-8"))

    report = signoff.build_m1_private_evidence_signoff_report(
        workflow_payload,
        workflow_report_path=workflow_report,
        evidence_dir=tmp_path,
        raw_text=workflow_report.read_text(encoding="utf-8"),
        signoff_owner="release-owner",
        rollout_report=_rollout_report(status="blocked"),
        operations_review_report=_operations_review_report(),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "rollout_report_json.status" for item in report["blocked_reasons"])


def test_private_evidence_signoff_blocks_missing_standard_section(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)
    payload = json.loads(workflow_report.read_text(encoding="utf-8"))
    payload["selected_sections"].remove("rate_limit_live_probe")
    workflow_report.write_text(json.dumps(payload), encoding="utf-8")

    report = _report_from_path(workflow_report)

    assert report["status"] == "blocked"
    assert any(item["key"] == "missing_standard_sections" for item in report["blocked_reasons"])


def test_private_evidence_signoff_blocks_tampered_artifact_hash(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)
    (tmp_path / "m1-live-evidence-summary.md").write_text("# tampered\n", encoding="utf-8")

    report = _report_from_path(workflow_report)

    assert report["status"] == "blocked"
    assert any(item["key"] == "live_evidence_summary_markdown" for item in report["blocked_reasons"])


def test_private_evidence_signoff_requires_risk_acceptance_for_conditional_go(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path, decision="conditional_go")
    payload = json.loads(workflow_report.read_text(encoding="utf-8"))
    payload["go_no_go"]["section_statuses"]["docker_disk_cleanup_plan"] = "degraded"
    workflow_report.write_text(json.dumps(payload), encoding="utf-8")

    blocked = _report_from_path(
        workflow_report,
        release_decision="conditional_go",
        allow_conditional_go=True,
    )
    passed = _report_from_path(
        workflow_report,
        release_decision="conditional_go",
        allow_conditional_go=True,
        risk_acceptance="Disk cleanup risk accepted for M1 controlled trial.",
    )

    assert blocked["status"] == "blocked"
    assert any(item["key"] == "risk_acceptance" for item in blocked["blocked_reasons"])
    assert passed["status"] == "passed"


def test_private_evidence_signoff_blocks_raw_url_ip_or_secret(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)
    raw = workflow_report.read_text(encoding="utf-8") + "\nhttps://prod.example.com\n203.0.113.10\naccess_token=secret-value-123456"

    report = signoff.build_m1_private_evidence_signoff_report(
        json.loads(workflow_report.read_text(encoding="utf-8")),
        workflow_report_path=workflow_report,
        evidence_dir=tmp_path,
        raw_text=raw,
        signoff_owner="release-owner",
    )

    assert report["status"] == "blocked"
    keys = {item["key"] for item in report["blocked_reasons"]}
    assert {"url", "ipv4", "secret_pattern"} <= keys
    payload = json.dumps(report, ensure_ascii=False)
    assert "prod.example.com" not in payload
    assert "203.0.113.10" not in payload
    assert "secret-value-123456" not in payload


def test_private_evidence_signoff_blocks_project_evidence_dir():
    payload = {
        "version": "m1_private_live_evidence_workflow.v1",
        "status": "passed",
        "policy": {
            "reads_dotenv": False,
            "starts_services": False,
            "deploys_code": False,
            "deletes_files": False,
            "records_public_url": False,
            "records_server_ip": False,
            "records_credentials": False,
            "output_should_remain_private": True,
        },
        "target": {"output_dir_inside_project": False},
        "selected_sections": sorted(STANDARD_SECTIONS),
        "missing_inputs_for_user": [],
        "go_no_go": {
            "decision": "go_for_m1_controlled_trial",
            "section_statuses": {section: "passed" for section in STANDARD_SECTIONS},
        },
        "artifacts": [],
    }

    report = signoff.build_m1_private_evidence_signoff_report(
        payload,
        evidence_dir=signoff.PROJECT_ROOT,
        signoff_owner="release-owner",
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "project_evidence_dir" for item in report["blocked_reasons"])


def test_private_evidence_signoff_cli_reads_workflow_report(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path)
    output = tmp_path / "signoff.json"

    code = signoff.main(
        [
            "--workflow-report-json",
            str(workflow_report),
            "--signoff-owner",
            "release-owner",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"


def test_private_evidence_signoff_cli_reads_review_reports_without_echoing_paths(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path, include_review_sections=True)
    rollout_report = tmp_path / "m1-rollout-execution-report.json"
    operations_report = tmp_path / "m1-operations-review-report.json"
    output = tmp_path / "signoff.json"
    rollout_report.write_text(json.dumps(_rollout_report(), ensure_ascii=False), encoding="utf-8")
    operations_report.write_text(json.dumps(_operations_review_report(), ensure_ascii=False), encoding="utf-8")

    code = signoff.main(
        [
            "--workflow-report-json",
            str(workflow_report),
            "--rollout-report-json",
            str(rollout_report),
            "--operations-review-report-json",
            str(operations_report),
            "--signoff-owner",
            "release-owner",
            "--output",
            str(output),
        ]
    )
    payload_text = output.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert code == 0
    assert payload["status"] == "passed"
    assert payload["checks"]["private_review_reports"]["status"] == "passed"
    assert "m1-rollout-execution-report.json" not in payload_text
    assert "m1-operations-review-report.json" not in payload_text


def test_private_evidence_signoff_cli_blocks_sensitive_review_report_without_echoing(tmp_path: Path):
    workflow_report = _write_private_evidence(tmp_path, include_review_sections=True)
    rollout_report = tmp_path / "m1-rollout-execution-report.json"
    operations_report = tmp_path / "m1-operations-review-report.json"
    output = tmp_path / "signoff.json"
    rollout_report.write_text(
        json.dumps({"version": "m1_rollout_execution_record.v1", "status": "passed", "raw": "https://prod.example.com"}),
        encoding="utf-8",
    )
    operations_report.write_text(json.dumps(_operations_review_report(), ensure_ascii=False), encoding="utf-8")

    code = signoff.main(
        [
            "--workflow-report-json",
            str(workflow_report),
            "--rollout-report-json",
            str(rollout_report),
            "--operations-review-report-json",
            str(operations_report),
            "--signoff-owner",
            "release-owner",
            "--output",
            str(output),
        ]
    )
    payload_text = output.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert code == 2
    assert payload["status"] == "blocked"
    assert payload["checks"]["private_review_reports"]["status"] == "blocked"
    assert "prod.example.com" not in payload_text
    assert "m1-rollout-execution-report.json" not in payload_text
