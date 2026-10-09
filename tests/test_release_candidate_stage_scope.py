import json
import subprocess
from pathlib import Path

from scripts import check_release_candidate_stage_scope as scope


def _runner_with_staged(output: str, returncode: int = 0):
    def runner(args, *, timeout_seconds=30):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=output if returncode == 0 else "",
            stderr="" if returncode == 0 else output,
        )

    return runner


def _record() -> dict:
    return {
        "version": "release_candidate_freeze_record.v1",
        "record_id": "stage-scope-test",
        "candidate_profile": "m1_deployment_control_baseline",
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
                "paths": [
                    {"status": "M", "path": "app/rag/retriever.py"},
                ],
            },
        ],
    }


def test_stage_scope_passes_when_only_included_paths_are_staged():
    report = scope.build_release_candidate_stage_scope_report(
        _record(),
        command_runner=_runner_with_staged(
            "M\tdeploy/first-deploy.sh\nA\tdocs/部署与运行/m1-launch-checklist.md\n"
        ),
    )

    assert report["status"] == "passed"
    assert report["staged_count"] == 2
    assert report["included_workstreams"] == ["deployment_runtime"]
    assert report["blocked_reasons"] == []


def test_stage_scope_blocks_deferred_path_staged():
    report = scope.build_release_candidate_stage_scope_report(
        _record(),
        command_runner=_runner_with_staged(
            "M\tdeploy/first-deploy.sh\n"
            "A\tdocs/部署与运行/m1-launch-checklist.md\n"
            "M\tapp/rag/retriever.py\n"
        ),
    )

    keys = {item["key"] for item in report["blocked_reasons"]}
    assert report["status"] == "blocked"
    assert "deferred_staged_path" in keys
    assert "not_included_workstream" in keys


def test_stage_scope_blocks_missing_included_path():
    report = scope.build_release_candidate_stage_scope_report(
        _record(),
        command_runner=_runner_with_staged("M\tdeploy/first-deploy.sh\n"),
    )

    assert report["status"] == "blocked"
    assert report["missing_included_paths"] == ["docs/部署与运行/m1-launch-checklist.md"]
    assert any(item["key"] == "included_path_not_staged" for item in report["blocked_reasons"])


def test_stage_scope_blocks_unknown_path_staged():
    report = scope.build_release_candidate_stage_scope_report(
        _record(),
        command_runner=_runner_with_staged(
            "M\tdeploy/first-deploy.sh\n"
            "A\tdocs/部署与运行/m1-launch-checklist.md\n"
            "A\tscratch/private-note.md\n"
        ),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "unknown_staged_path" for item in report["blocked_reasons"])


def test_stage_scope_blocks_forbidden_path_staged():
    report = scope.build_release_candidate_stage_scope_report(
        _record(),
        command_runner=_runner_with_staged(
            "M\tdeploy/first-deploy.sh\n"
            "A\tdocs/部署与运行/m1-launch-checklist.md\n"
            "A\t.env\n"
        ),
    )

    keys = {item["key"] for item in report["blocked_reasons"]}
    assert report["status"] == "blocked"
    assert "forbidden_staged_path" in keys


def test_stage_scope_blocks_no_staged_paths():
    report = scope.build_release_candidate_stage_scope_report(
        _record(),
        command_runner=_runner_with_staged(""),
    )

    keys = {item["key"] for item in report["blocked_reasons"]}
    assert report["status"] == "blocked"
    assert "no_staged_paths" in keys
    assert "included_path_not_staged" in keys


def test_stage_scope_blocks_public_closure_not_passed():
    record = _record()
    record["public_release_closure_status"] = "blocked"

    report = scope.build_release_candidate_stage_scope_report(
        record,
        command_runner=_runner_with_staged(
            "M\tdeploy/first-deploy.sh\nA\tdocs/部署与运行/m1-launch-checklist.md\n"
        ),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "public_release_closure" for item in report["blocked_reasons"])


def test_stage_scope_cli_reads_record_json(tmp_path: Path, capsys):
    record_path = tmp_path / "record.json"
    record_path.write_text(json.dumps(_record()), encoding="utf-8")

    code = scope.main(["--record-json", str(record_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "blocked"
    assert payload["policy"]["reads_changed_file_contents"] is False
