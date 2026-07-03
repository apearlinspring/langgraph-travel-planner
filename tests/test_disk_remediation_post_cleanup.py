import json
from pathlib import Path

from scripts import check_disk_remediation_post_cleanup as post


def _execution_report(status="passed", failed=0):
    return {
        "version": "docker_disk_cleanup_execution.v1",
        "status": status,
        "mode": "execute",
        "approval": {"approval_token_accepted": True},
        "result_counts": {
            "deleted": 2,
            "skipped_missing": 17,
            "failed": failed,
        },
    }


def _capacity(free_mb, used_percent=97, status="degraded"):
    disk = {
        "root": {"status": status, "free_mb": free_mb, "used_percent": used_percent},
        "deploy": {"status": status, "free_mb": free_mb, "used_percent": used_percent},
    }
    return {
        "version": "server_capacity_snapshot.v1",
        "status": status,
        "sections": {
            "host_capacity": {
                "disk": disk,
            }
        },
    }


def _restore(free_mb, required_mb=4096, status="blocked"):
    return {
        "version": "restore_drill_feasibility.v1",
        "status": status,
        "sections": {
            "restore_workspace_space": {
                "status": status,
                "effective_free_mb": free_mb,
                "required_free_mb": required_mb,
            }
        },
    }


def test_post_cleanup_reports_expansion_required_when_space_still_blocked():
    report = post.build_disk_remediation_post_cleanup_report(
        execution_report=_execution_report(status="blocked", failed=1),
        before_capacity=_capacity(2266),
        after_capacity=_capacity(2287),
        restore_feasibility=_restore(2287),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "storage_expansion_required"
    assert report["sections"]["execution"]["failed"] == 1
    assert report["sections"]["capacity_delta"]["root_free_delta_mb"] == 21
    assert report["sections"]["restore_feasibility"]["required_free_mb"] == 4096
    assert report["policy"]["deletes_images"] is False


def test_post_cleanup_can_pass_when_execution_capacity_and_restore_pass():
    report = post.build_disk_remediation_post_cleanup_report(
        execution_report=_execution_report(),
        before_capacity=_capacity(2266),
        after_capacity=_capacity(8192, used_percent=70, status="passed"),
        restore_feasibility=_restore(8192, status="passed"),
    )

    assert report["status"] == "passed"
    assert report["decision"] == "disk_remediation_evidence_passed"


def test_post_cleanup_markdown_redacts_paths_and_summarizes_deltas():
    report = post.build_disk_remediation_post_cleanup_report(
        execution_report=_execution_report(status="blocked", failed=1),
        before_capacity=_capacity(2266),
        after_capacity=_capacity(2287),
        restore_feasibility=_restore(2287),
    )

    markdown = post.build_disk_remediation_post_cleanup_markdown(report)

    assert "Disk Remediation Post-Cleanup Check" in markdown
    assert "root_delta=21 MB" in markdown
    assert "free=2287/4096 MB" in markdown
    assert "203.0.113.10" not in markdown
    assert "D:\\Users\\Administrator" not in markdown


def test_post_cleanup_cli_writes_json_without_echoing_source_paths(tmp_path: Path):
    execution = tmp_path / "execution.json"
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    restore = tmp_path / "restore.json"
    output = tmp_path / "post.json"
    execution.write_text(json.dumps(_execution_report(status="blocked", failed=1)), encoding="utf-8")
    before.write_text(json.dumps(_capacity(2266)), encoding="utf-8")
    after.write_text(json.dumps(_capacity(2287)), encoding="utf-8")
    restore.write_text(json.dumps(_restore(2287)), encoding="utf-8")

    code = post.main(
        [
            "--execution-json",
            str(execution),
            "--before-capacity-json",
            str(before),
            "--after-capacity-json",
            str(after),
            "--restore-feasibility-json",
            str(restore),
            "--output",
            str(output),
        ]
    )
    payload = output.read_text(encoding="utf-8")

    assert code == 2
    assert str(execution) not in payload
    assert str(after) not in payload
    assert "storage_expansion_required" in payload
