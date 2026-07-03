import json
from pathlib import Path

from scripts import render_m1_deployment_evidence_matrix as matrix


def _launch_inputs_report(status="passed"):
    return {
        "version": "m1_launch_inputs.v1",
        "status": status,
        "input_count": 10,
        "passed_count": 10 if status == "passed" else 8,
        "blocked_count": 0 if status == "passed" else 1,
        "degraded_count": 0 if status == "passed" else 1,
        "category_statuses": {"server": status},
    }


def _go_no_go_report(status="passed", decision="go_for_m1_controlled_trial"):
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": status,
        "decision": decision,
        "section_statuses": {
            "live_server_probe": "passed",
            "postgres_redis_live_probe": "passed",
            "m1_rollout_execution_record": "passed",
            "m1_operations_review_record": "passed",
        },
    }


def _supplemental_go_no_go_report(status="passed", decision="go_for_m1_controlled_trial"):
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": status,
        "decision": decision,
        "section_statuses": {
            "live_chat_concurrency_probe": status,
        },
        "not_proven_by_this_report": [
            "Supplemental evidence is not covered by the older private signoff.",
        ],
    }


def _rollout_report(status="passed"):
    return {
        "version": "m1_rollout_execution_record.v1",
        "status": status,
        "record_summary": {
            "environment": "m1_controlled_trial",
            "deployment_phase_count": 7,
            "issue_count": 0,
        },
    }


def _operations_review_report(status="passed"):
    return {
        "version": "m1_operations_review_record.v1",
        "status": status,
        "record_summary": {
            "issues_observed": False,
            "issue_count": 0,
            "followup_count": 1,
        },
    }


def _signoff_report(status="passed", release_decision="go_for_m1_controlled_trial"):
    return {
        "version": "m1_private_evidence_signoff.v1",
        "status": status,
        "signoff": {
            "release_decision": release_decision,
        },
        "checks": {
            "private_review_reports": {"status": "passed"},
        },
    }


def _all_reports(**overrides):
    reports = {
        "launch_inputs_report": _launch_inputs_report(),
        "go_no_go_report": _go_no_go_report(),
        "rollout_report": _rollout_report(),
        "operations_review_report": _operations_review_report(),
        "signoff_report": _signoff_report(),
    }
    reports.update(overrides)
    return reports


def _write_report(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_deployment_evidence_matrix_passes_with_complete_private_reports():
    report = matrix.build_m1_deployment_evidence_matrix_report(**_all_reports())

    assert report["status"] == "passed"
    assert report["summary"]["passed_count"] == 5
    assert report["summary"]["can_claim_m1_controlled_trial_ready"] is True
    assert report["summary"]["can_claim_full_production_ready"] is False
    assert report["policy"]["reads_dotenv"] is False
    assert [row["key"] for row in report["matrix"]] == [
        "launch_inputs",
        "go_no_go",
        "rollout_execution",
        "operations_review",
        "private_signoff",
    ]


def test_deployment_evidence_matrix_degrades_for_conditional_go():
    report = matrix.build_m1_deployment_evidence_matrix_report(
        **_all_reports(
            go_no_go_report=_go_no_go_report(status="degraded", decision="conditional_go"),
            signoff_report=_signoff_report(release_decision="conditional_go"),
        )
    )

    assert report["status"] == "degraded"
    assert report["summary"]["go_no_go_decision"] == "conditional_go"
    go_row = next(row for row in report["matrix"] if row["key"] == "go_no_go")
    assert go_row["status"] == "degraded"


def test_deployment_evidence_matrix_includes_supplemental_go_no_go_without_extending_signoff():
    report = matrix.build_m1_deployment_evidence_matrix_report(
        **_all_reports(),
        supplemental_go_no_go_reports=[_supplemental_go_no_go_report()],
    )

    assert report["status"] == "passed"
    assert report["summary"]["supplemental_report_count"] == 1
    assert report["summary"]["supplemental_evidence_extends_signoff"] is False
    assert report["summary"]["can_claim_m1_controlled_trial_ready"] is True
    row = report["supplemental_evidence"][0]
    assert row["status"] == "passed"
    assert row["covered_by_private_signoff"] is False
    assert row["signal"] == "decision=go_for_m1_controlled_trial, sections=1"


def test_deployment_evidence_matrix_blocks_failed_supplemental_go_no_go():
    report = matrix.build_m1_deployment_evidence_matrix_report(
        **_all_reports(),
        supplemental_go_no_go_reports=[
            _supplemental_go_no_go_report(status="blocked", decision="no_go")
        ],
    )

    assert report["status"] == "blocked"
    assert report["summary"]["supplemental_blocked_count"] == 1
    assert report["summary"]["can_claim_m1_controlled_trial_ready"] is False
    assert any(item["key"] == "supplemental_go_no_go_1" for item in report["blocked_reasons"])


def test_deployment_evidence_matrix_blocks_missing_required_report():
    report = matrix.build_m1_deployment_evidence_matrix_report(
        **_all_reports(operations_review_report={})
    )

    assert report["status"] == "blocked"
    keys = {item["key"] for item in report["blocked_reasons"]}
    assert "operations_review" in keys


def test_deployment_evidence_matrix_markdown_summarizes_rows():
    report = matrix.build_m1_deployment_evidence_matrix_report(**_all_reports())
    markdown = matrix.build_m1_deployment_evidence_matrix_markdown(report)

    assert "M1 Deployment Evidence Matrix" in markdown
    assert "M1 launch inputs" in markdown
    assert "Private evidence signoff" in markdown
    assert "Supplemental Evidence" not in markdown
    assert "Can claim full production ready | `False`" in markdown


def test_deployment_evidence_matrix_markdown_shows_supplemental_evidence():
    report = matrix.build_m1_deployment_evidence_matrix_report(
        **_all_reports(),
        supplemental_go_no_go_reports=[_supplemental_go_no_go_report()],
    )
    markdown = matrix.build_m1_deployment_evidence_matrix_markdown(report)

    assert "Supplemental Evidence" in markdown
    assert "Supplemental go/no-go #1" in markdown
    assert "`False`" in markdown


def test_deployment_evidence_matrix_cli_reads_private_reports_without_echoing_paths(tmp_path: Path):
    paths = {
        "launch": tmp_path / "launch-inputs-report.json",
        "go": tmp_path / "go-no-go.json",
        "rollout": tmp_path / "rollout-report.json",
        "ops": tmp_path / "operations-report.json",
        "signoff": tmp_path / "signoff-report.json",
        "supplemental": tmp_path / "supplemental-go-no-go.json",
        "output": tmp_path / "matrix.json",
    }
    _write_report(paths["launch"], _launch_inputs_report())
    _write_report(paths["go"], _go_no_go_report())
    _write_report(paths["rollout"], _rollout_report())
    _write_report(paths["ops"], _operations_review_report())
    _write_report(paths["signoff"], _signoff_report())
    _write_report(paths["supplemental"], _supplemental_go_no_go_report())

    code = matrix.main(
        [
            "--launch-inputs-report-json",
            str(paths["launch"]),
            "--go-no-go-json",
            str(paths["go"]),
            "--rollout-report-json",
            str(paths["rollout"]),
            "--operations-review-report-json",
            str(paths["ops"]),
            "--signoff-report-json",
            str(paths["signoff"]),
            "--supplemental-go-no-go-json",
            str(paths["supplemental"]),
            "--output",
            str(paths["output"]),
        ]
    )
    payload_text = paths["output"].read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert code == 0
    assert payload["status"] == "passed"
    assert payload["summary"]["supplemental_report_count"] == 1
    assert "launch-inputs-report.json" not in payload_text
    assert "signoff-report.json" not in payload_text
    assert "supplemental-go-no-go.json" not in payload_text


def test_deployment_evidence_matrix_cli_blocks_sensitive_report_without_echoing(tmp_path: Path):
    launch_path = tmp_path / "launch-inputs-report.json"
    output_path = tmp_path / "matrix.json"
    _write_report(
        launch_path,
        {
            "version": "m1_launch_inputs.v1",
            "status": "passed",
            "raw": "https://prod.example.com",
        },
    )

    code = matrix.main(
        [
            "--launch-inputs-report-json",
            str(launch_path),
            "--go-no-go-json",
            str(tmp_path / "missing-go-no-go.json"),
            "--rollout-report-json",
            str(tmp_path / "missing-rollout.json"),
            "--operations-review-report-json",
            str(tmp_path / "missing-ops.json"),
            "--signoff-report-json",
            str(tmp_path / "missing-signoff.json"),
            "--output",
            str(output_path),
        ]
    )
    payload_text = output_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert code == 2
    assert payload["status"] == "blocked"
    assert "prod.example.com" not in payload_text
    assert "launch-inputs-report.json" not in payload_text
