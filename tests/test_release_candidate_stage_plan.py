import json
from pathlib import Path

from scripts import render_release_candidate_stage_plan as plan


def _record() -> dict:
    return {
        "version": "release_candidate_freeze_record.v1",
        "record_id": "stage-plan-test",
        "candidate_profile": "m1_deployment_control_baseline",
        "candidate_goal": "Freeze deployment-control baseline.",
        "public_release_closure_status": "passed",
        "decision_rows": [
            {
                "workstream": "deployment_runtime",
                "changed_count": 2,
                "decision": "include",
                "paths": [
                    {"status": "M", "path": "deploy/first-deploy.sh"},
                    {"status": "??", "path": "docs/部署与运行/m1-launch-checklist.md"},
                ],
            },
            {
                "workstream": "rag_evaluation",
                "changed_count": 1,
                "decision": "defer",
                "paths": [{"status": "M", "path": "app/rag/retriever.py"}],
            },
        ],
    }


def test_stage_plan_renders_include_and_defer_paths():
    report = plan.build_release_candidate_stage_plan(
        _record(),
        record_json_label="freeze.json",
        batch_size=1,
    )

    assert report["status"] == "ready_to_stage"
    assert report["candidate_profile"] == "m1_deployment_control_baseline"
    assert report["include_path_count"] == 2
    assert report["defer_path_count"] == 1
    assert report["include_workstreams"] == ["deployment_runtime"]
    assert report["defer_workstreams"] == ["rag_evaluation"]
    assert len(report["git_add_commands"]) == 2
    assert "git add --" in report["git_add_commands"][0]
    assert "check_release_candidate_stage_scope.py --record-json freeze.json --json" in report["follow_up_commands"][0]


def test_stage_plan_blocks_public_closure_not_passed():
    record = _record()
    record["public_release_closure_status"] = "blocked"

    report = plan.build_release_candidate_stage_plan(record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "public_release_closure" for item in report["blocked_reasons"])


def test_stage_plan_blocks_forbidden_include_path():
    record = _record()
    record["decision_rows"][0]["paths"].append({"status": "??", "path": ".env"})

    report = plan.build_release_candidate_stage_plan(record)

    assert report["status"] == "blocked"
    assert ".env" in report["forbidden_include_paths"]
    assert any(item["key"] == "forbidden_include_path" for item in report["blocked_reasons"])


def test_stage_plan_blocks_no_include_paths():
    record = _record()
    record["decision_rows"][0]["decision"] = "defer"

    report = plan.build_release_candidate_stage_plan(record)

    assert report["status"] == "blocked"
    assert any(item["key"] == "no_include_paths" for item in report["blocked_reasons"])


def test_stage_plan_markdown_contains_commands_and_boundary():
    report = plan.build_release_candidate_stage_plan(_record(), record_json_label="freeze.json")

    markdown = plan.build_markdown(report)

    assert "Release Candidate Stage Plan" in markdown
    assert "git add --" in markdown
    assert "check_release_candidate_stage_scope.py --record-json freeze.json --json" in markdown
    assert "app/rag/retriever.py" in markdown
    assert "The listed paths have actually been staged." in markdown


def test_stage_plan_cli_reads_record_json(tmp_path: Path, capsys):
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(_record()), encoding="utf-8")

    code = plan.main(["--record-json", str(record_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "ready_to_stage"
    assert payload["policy"]["stages_files"] is False
