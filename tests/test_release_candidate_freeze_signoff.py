from datetime import UTC, datetime
import json
from pathlib import Path

from scripts import check_release_candidate_freeze_signoff as signoff


def _record() -> dict:
    return {
        "version": "release_candidate_freeze_record.v1",
        "record_id": "freeze-signoff-test",
        "freeze_status": "blocked",
        "freeze_state": "not_frozen",
        "dirty_count": 2,
        "decision_rows": [
            {
                "workstream": "deployment_runtime",
                "owner": "Coordinator / Deployment",
                "changed_count": 1,
            "decision": "pending",
            "decision_reason": "",
            "validation_status": "pending",
            "validation_evidence": "",
            "risk_status": "pending",
            "risk_evidence": "",
            "remaining_risk": "",
            "signoff": "",
        },
            {
                "workstream": "rag_evaluation",
                "owner": "RAG / Evaluation",
                "changed_count": 1,
                "decision": "pending",
                "decision_reason": "",
                "validation_status": "pending",
                "risk_status": "pending",
                "remaining_risk": "",
                "signoff": "",
            },
        ],
    }


def _signed_record() -> dict:
    record = _record()
    record["candidate_profile"] = "m1_deployment_control_baseline"
    record["candidate_goal"] = "Freeze the public deployment-control baseline."
    record["decision_rows"][0].update(
        {
            "decision": "include",
            "validation_status": "passed",
            "validation_evidence": "Ran uv run python scripts/check_m1_deployment_gate.py --json; gate remains blocked only on external env.",
            "risk_status": "accepted",
            "risk_evidence": "Residual risk accepted for M1 controlled trial; no real payment or booking enabled.",
            "remaining_risk": "No known release-blocking risk.",
            "signoff": "release-owner",
        }
    )
    record["decision_rows"][1].update(
        {
            "decision": "defer",
            "decision_reason": "RAG change will ship in the next candidate.",
            "validation_status": "not_required",
            "risk_status": "not_required",
            "signoff": "release-owner",
        }
    )
    return record


def _current_freeze_report() -> dict:
    return {
        "version": "release_candidate_freeze.v1",
        "status": "blocked",
        "freeze_state": "not_frozen",
        "branch": "## main...origin/main",
        "dirty_count": 2,
        "forbidden_paths": [],
        "unknown_paths": [],
        "workstreams": [
            {
                "key": "deployment_runtime",
                "changed_count": 1,
                "paths": [{"status": "M", "path": "deploy/first-deploy.sh"}],
            },
            {
                "key": "rag_evaluation",
                "changed_count": 1,
                "paths": [{"status": "M", "path": "app/rag/retriever.py"}],
            },
        ],
    }


def _signed_record_with_paths() -> dict:
    record = _signed_record()
    record["branch"] = "## main...origin/main"
    record["decision_rows"][0]["paths"] = [
        {"status": "M", "path": "deploy/first-deploy.sh"},
    ]
    record["decision_rows"][1]["paths"] = [
        {"status": "M", "path": "app/rag/retriever.py"},
    ]
    return record


def test_freeze_signoff_blocks_pending_decisions():
    report = signoff.build_release_candidate_freeze_signoff_report(
        _record(),
        generated_at=datetime(2026, 6, 23, 13, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert report["status"] == "blocked"
    assert report["changed_workstream_count"] == 2
    assert any(item["key"] == "decision" for item in report["blocked_reasons"])
    assert any(item["key"] == "signoff" for item in report["blocked_reasons"])
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["reads_file_contents"] is False
    assert report["policy"]["starts_services"] is False


def test_freeze_signoff_passes_when_decisions_are_complete():
    report = signoff.build_release_candidate_freeze_signoff_report(
        _signed_record(),
        generated_at=datetime(2026, 6, 23, 13, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert report["status"] == "passed"
    assert report["candidate_profile"] == "m1_deployment_control_baseline"
    assert report["included_workstream_count"] == 1
    assert report["deferred_workstream_count"] == 1
    assert report["removed_workstream_count"] == 0
    assert report["blocked_reasons"] == []


def test_freeze_signoff_blocks_included_workstream_without_validation_evidence():
    record = _signed_record()
    record["decision_rows"][0]["validation_evidence"] = ""

    report = signoff.build_release_candidate_freeze_signoff_report(record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "validation_evidence" for item in report["blocked_reasons"])


def test_freeze_signoff_blocks_included_workstream_with_unexplained_residual_risk():
    record = _signed_record()
    record["decision_rows"][0]["remaining_risk"] = ""

    report = signoff.build_release_candidate_freeze_signoff_report(record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "remaining_risk" for item in report["blocked_reasons"])


def test_freeze_signoff_can_compare_against_current_worktree_snapshot():
    report = signoff.build_release_candidate_freeze_signoff_report(
        _signed_record_with_paths(),
        current_freeze_report=_current_freeze_report(),
        generated_at=datetime(2026, 6, 23, 13, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert report["status"] == "passed"
    assert report["current_worktree_checked"] is True
    assert report["current_dirty_count"] == 2
    assert report["blocked_reasons"] == []


def test_freeze_signoff_blocks_stale_record_when_current_worktree_changed():
    current = _current_freeze_report()
    current["dirty_count"] = 3
    current["workstreams"][0]["paths"].append(
        {"status": "M", "path": "docker-compose.yml"},
    )
    current["workstreams"][0]["changed_count"] = 2

    report = signoff.build_release_candidate_freeze_signoff_report(
        _signed_record_with_paths(),
        current_freeze_report=current,
        generated_at=datetime(2026, 6, 23, 13, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert report["status"] == "blocked"
    assert report["current_worktree_checked"] is True
    assert report["current_dirty_count"] == 3
    keys = {item["key"] for item in report["blocked_reasons"]}
    assert "dirty_count_mismatch" in keys
    assert "workstream_changed_count_mismatch" in keys


def test_freeze_signoff_blocks_current_forbidden_paths():
    current = _current_freeze_report()
    current["forbidden_paths"] = [".env"]

    report = signoff.build_release_candidate_freeze_signoff_report(
        _signed_record_with_paths(),
        current_freeze_report=current,
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "current_forbidden_paths" for item in report["blocked_reasons"])


def test_freeze_signoff_blocks_current_public_release_closure_failure():
    current = _current_freeze_report()
    current["public_release_closure"] = {
        "status": "blocked",
        "section_statuses": {"public_coordinate_scan": "blocked"},
    }

    report = signoff.build_release_candidate_freeze_signoff_report(
        _signed_record_with_paths(),
        current_freeze_report=current,
    )

    assert report["status"] == "blocked"
    assert report["current_public_release_closure_status"] == "blocked"
    assert report["policy"]["reads_file_contents"] is True
    assert any(item["key"] == "current_public_release_closure" for item in report["blocked_reasons"])


def test_freeze_signoff_blocks_failed_public_release_closure():
    record = _signed_record()
    record["public_release_closure_status"] = "blocked"

    report = signoff.build_release_candidate_freeze_signoff_report(record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "public_release_closure" for item in report["blocked_reasons"])


def test_freeze_signoff_blocks_included_workstream_without_validation():
    record = _signed_record()
    record["decision_rows"][0]["validation_status"] = "not_run"

    report = signoff.build_release_candidate_freeze_signoff_report(record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "validation_status" for item in report["blocked_reasons"])


def test_freeze_signoff_markdown_contains_boundary():
    report = signoff.build_release_candidate_freeze_signoff_report(
        _record(),
        current_freeze_report=_current_freeze_report(),
    )

    markdown = signoff.build_release_candidate_freeze_signoff_markdown(report)

    assert "Release Candidate Freeze Signoff" in markdown
    assert "Candidate profile" in markdown
    assert "deployment_runtime" in markdown
    assert "Current worktree checked" in markdown
    assert "Target environment secrets" in markdown


def test_freeze_signoff_cli_reads_record_json(tmp_path: Path):
    record_path = tmp_path / "record.json"
    output_path = tmp_path / "signoff.md"
    record_path.write_text(json.dumps(_signed_record()), encoding="utf-8")

    code = signoff.main(
        [
            "--record-json",
            str(record_path),
            "--output",
            str(output_path),
        ]
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "Freeze Signoff" in markdown
    assert "| Status | `passed` |" in markdown


def test_freeze_signoff_cli_accepts_utf8_bom_json(tmp_path: Path):
    record_path = tmp_path / "record-bom.json"
    record_path.write_text(json.dumps(_signed_record()), encoding="utf-8-sig")

    code = signoff.main(["--record-json", str(record_path), "--json"])

    assert code == 0
