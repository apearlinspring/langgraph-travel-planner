from datetime import UTC, datetime
import json
from pathlib import Path

from scripts import check_release_candidate_freeze_signoff as signoff
from scripts import render_release_candidate_freeze_record as record


def _freeze_report(status: str = "blocked") -> dict:
    return {
        "version": "release_candidate_freeze.v1",
        "status": status,
        "freeze_state": "not_frozen" if status == "blocked" else "frozen",
        "branch": "## main...origin/main",
        "dirty_count": 2 if status == "blocked" else 0,
        "forbidden_paths": [],
        "unknown_paths": [],
        "public_release_closure": {
            "status": "passed",
            "checked": True,
            "section_statuses": {"public_coordinate_scan": "passed"},
        },
        "workstreams": [
            {
                "key": "deployment_runtime",
                "owner": "Coordinator / Deployment",
                "changed_count": 1 if status == "blocked" else 0,
                "paths": [{"status": "M", "path": "deploy/first-deploy.sh"}]
                if status == "blocked"
                else [],
                "validation_commands": [
                    "uv run python scripts/check_m1_deployment_gate.py --json",
                ],
            },
            {
                "key": "rag_evaluation",
                "owner": "RAG / Evaluation",
                "changed_count": 1 if status == "blocked" else 0,
                "paths": [{"status": "M", "path": "app/rag/retriever.py"}]
                if status == "blocked"
                else [],
                "validation_commands": [
                    "uv run python scripts/evaluate_rag_retrieval.py --json",
                ],
            },
        ],
        "blocked_reasons": [
            {
                "key": "release_candidate_not_frozen",
                "reason": "Working tree has 2 uncommitted changes.",
            }
        ]
        if status == "blocked"
        else [],
        "required_actions": [
            "Review each changed workstream and decide include/defer for the release candidate.",
            "Commit the selected public release candidate so the worktree is clean.",
        ],
    }


def test_freeze_record_report_keeps_pending_decisions_for_dirty_worktree():
    report = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-test",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert report["version"] == "release_candidate_freeze_record.v1"
    assert report["status"] == "blocked"
    assert report["signoff_status"] == "pending"
    assert report["dirty_count"] == 2
    assert report["public_release_closure_status"] == "passed"
    assert report["public_release_closure_checked"] is True
    assert report["decision_rows"][0]["decision"] == "pending"
    assert report["decision_rows"][0]["validation_status"] == "pending"
    assert report["decision_rows"][0]["validation_evidence"] == ""
    assert report["decision_rows"][0]["risk_evidence"] == ""


def test_freeze_record_report_can_include_non_binding_suggestions():
    report = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-suggest",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
        include_suggestions=True,
    )

    deployment = report["decision_rows"][0]
    rag = report["decision_rows"][1]

    assert report["include_suggestions"] is True
    assert report["policy"]["suggestions_are_not_signoff"] is True
    assert deployment["decision"] == "pending"
    assert deployment["suggested_decision"] == "include"
    assert "check_m1_deployment_gate.py --json" in deployment["suggested_validation_evidence"]
    assert rag["decision"] == "pending"
    assert rag["suggested_decision"] == "review_include_or_defer"


def test_freeze_record_report_can_prefill_baseline_draft_without_signoff():
    report = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-draft",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
        draft_baseline_decisions=True,
    )

    deployment = report["decision_rows"][0]
    rag = report["decision_rows"][1]

    assert report["include_suggestions"] is True
    assert report["draft_baseline_decisions"] is True
    assert report["policy"]["draft_decisions_are_not_signoff"] is True
    assert report["candidate_profile"] == "m1_deployment_control_baseline"
    assert report["changed_workstream_count"] == 2
    assert report["included_workstreams"] == ["deployment_runtime"]
    assert report["deferred_workstreams"] == ["rag_evaluation"]
    assert deployment["decision"] == "include"
    assert deployment["validation_status"] == "not_run"
    assert deployment["validation_evidence"]
    assert deployment["risk_status"] == "accepted"
    assert deployment["risk_evidence"]
    assert deployment["signoff"] == ""
    assert rag["decision"] == "defer"
    assert rag["decision_reason"]
    assert rag["validation_status"] == "not_required"
    assert rag["risk_status"] == "not_required"
    assert rag["signoff"] == ""


def test_freeze_record_report_marks_clean_worktree_ready_for_signoff():
    report = record.build_release_candidate_freeze_record_report(
        _freeze_report("passed"),
        record_id="freeze-clean",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
    )

    assert report["status"] == "ready_for_freeze_signoff"
    assert report["signoff_status"] == "not_required_clean_worktree"
    assert all(row["decision"] == "not_changed" for row in report["decision_rows"])


def test_freeze_record_markdown_contains_decision_template_without_claiming_deploy():
    payload = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-md",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
    )

    markdown = record.build_release_candidate_freeze_record_markdown(payload)

    assert "Release Candidate Freeze Record" in markdown
    assert "| Freeze status | `blocked` |" in markdown
    assert "| Public release closure | `passed` |" in markdown
    assert "Decision: `pending`" in markdown
    assert "Validation evidence" in markdown
    assert "Risk evidence" in markdown
    assert "deploy/first-deploy.sh" in markdown
    assert "evaluate_rag_retrieval.py --json" in markdown
    assert "A release archive and manifest have been generated." in markdown
    assert "The release has been uploaded or deployed to a server." in markdown


def test_freeze_record_markdown_renders_suggestions_as_non_binding():
    payload = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-suggest-md",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
        include_suggestions=True,
    )

    markdown = record.build_release_candidate_freeze_record_markdown(payload)

    assert "Includes suggestions" in markdown
    assert "Suggested decision" in markdown
    assert "suggestions" in markdown.lower()
    assert "不能替代 release owner" in markdown


def test_freeze_record_markdown_renders_draft_baseline_values():
    payload = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-draft-md",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
        draft_baseline_decisions=True,
    )

    markdown = record.build_release_candidate_freeze_record_markdown(payload)

    assert "| Draft baseline decisions | `True` |" in markdown
    assert "| Candidate profile | `m1_deployment_control_baseline` |" in markdown
    assert "| Included workstreams | `deployment_runtime` |" in markdown
    assert "Decision: `include`" in markdown
    assert "Validation result: `not_run`" in markdown
    assert "Decision: `defer`" in markdown
    assert "`--draft-baseline-decisions` 只生成拟填写稿" in markdown


def test_freeze_record_cli_reads_json_and_writes_markdown(tmp_path: Path):
    freeze_path = tmp_path / "freeze.json"
    output_path = tmp_path / "freeze-record.md"
    freeze_path.write_text(json.dumps(_freeze_report("blocked")), encoding="utf-8")

    code = record.main(
        [
            "--freeze-json",
            str(freeze_path),
            "--output",
            str(output_path),
            "--record-id",
            "freeze-cli",
        ]
    )
    markdown = output_path.read_text(encoding="utf-8")

    assert code == 2
    assert "freeze-cli" in markdown
    assert "freeze_json:freeze.json" in markdown
    assert "release_candidate_not_frozen" in markdown


def test_freeze_record_cli_can_emit_suggestion_json(tmp_path: Path, capsys):
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(_freeze_report("blocked")), encoding="utf-8")

    code = record.main(["--freeze-json", str(freeze_path), "--with-suggestions", "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == 2
    assert payload["include_suggestions"] is True
    assert payload["decision_rows"][0]["decision"] == "pending"
    assert payload["decision_rows"][0]["suggested_decision"] == "include"


def test_freeze_record_cli_can_emit_baseline_draft_json(tmp_path: Path, capsys):
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(_freeze_report("blocked")), encoding="utf-8")

    code = record.main(["--freeze-json", str(freeze_path), "--draft-baseline-decisions", "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == 2
    assert payload["include_suggestions"] is True
    assert payload["draft_baseline_decisions"] is True
    assert payload["decision_rows"][0]["decision"] == "include"
    assert payload["decision_rows"][0]["signoff"] == ""
    assert payload["decision_rows"][1]["decision"] == "defer"
    assert payload["decision_rows"][1]["signoff"] == ""


def test_freeze_record_report_from_checked_freeze_keeps_public_closure_status():
    freeze = _freeze_report("blocked")
    freeze["public_release_closure"] = {
        "status": "passed",
        "checked": True,
        "section_statuses": {"public_coordinate_scan": "passed"},
    }

    payload = record.build_release_candidate_freeze_record_report(
        freeze,
        record_id="freeze-public-closure",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
        draft_baseline_decisions=True,
    )

    assert payload["public_release_closure_status"] == "passed"
    assert payload["public_release_closure_checked"] is True
    assert payload["public_release_closure_section_statuses"]["public_coordinate_scan"] == "passed"


def test_freeze_record_baseline_draft_still_blocks_signoff():
    payload = record.build_release_candidate_freeze_record_report(
        _freeze_report("blocked"),
        record_id="freeze-draft-signoff",
        generated_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        source="unit-test",
        draft_baseline_decisions=True,
    )

    report = signoff.build_release_candidate_freeze_signoff_report(payload)
    keys = {item["key"] for item in report["blocked_reasons"]}

    assert report["status"] == "blocked"
    assert report["included_workstream_count"] == 1
    assert report["deferred_workstream_count"] == 1
    assert "validation_status" in keys
    assert "signoff" in keys


def test_freeze_record_cli_accepts_utf8_bom_json(tmp_path: Path):
    freeze_path = tmp_path / "freeze-bom.json"
    freeze_path.write_text(json.dumps(_freeze_report("blocked")), encoding="utf-8-sig")

    code = record.main(["--freeze-json", str(freeze_path), "--json"])

    assert code == 2
