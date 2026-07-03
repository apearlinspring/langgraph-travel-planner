import json
from pathlib import Path

from scripts import check_disk_remediation_approval as approval


def _cleanup_plan(status="degraded"):
    return {
        "version": "docker_disk_cleanup_plan.v1",
        "status": status,
        "risk_status": "attention_required",
        "approval_required": {
            "required_for_execution": True,
        },
        "images": {
            "total_count": 10,
            "protected_count": 2,
            "candidate_count": 8,
            "selected_count": 2,
            "estimated_selected_size_mb": 2048,
        },
        "selected_candidates": [
            {"image_id": "sha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "protected": False},
            {"image_id": "sha256:333333333333cccccccccccccccccccccccccccccccccccccccccccc", "protected": False},
        ],
    }


def _dry_run(status="passed", mode="dry_run"):
    return {
        "version": "docker_disk_cleanup_execution.v1",
        "status": status,
        "mode": mode,
        "policy": {
            "deletes_images": False,
        },
        "result_counts": {
            "dry_run": 2,
        },
        "plan_summary": {
            "requested_image_count": 2,
            "max_delete_count": 2,
        },
    }


def _capacity(status="degraded"):
    return {
        "version": "server_capacity_snapshot.v1",
        "status": status,
        "sections": {
            "host_capacity": {
                "status": status,
                "disk": {
                    "root": {"status": "degraded", "free_mb": 2266, "used_percent": 97},
                    "deploy": {"status": "degraded", "free_mb": 2266, "used_percent": 97},
                },
            },
            "container_capacity": {"status": "passed"},
        },
    }


def _restore_feasibility(status="blocked"):
    return {
        "version": "restore_drill_feasibility.v1",
        "status": status,
        "sections": {
            "postgres_backup": {"status": "passed"},
            "restore_workspace_space": {
                "status": "blocked",
                "effective_free_mb": 2266,
                "required_free_mb": 4096,
            },
        },
        "blocked_reasons": [
            {"section": "restore_workspace_space", "key": "insufficient_restore_drill_space"},
        ],
    }


def _approval_record(max_delete_count=2):
    return {
        "approval_id": "docker-disk-remediation-20260625",
        "approved_by_role": "operator",
        "approved_at": "2026-06-25T10:00:00+08:00",
        "scope": "delete only selected Docker image candidates from the latest redacted cleanup plan",
        "max_delete_count": max_delete_count,
        "evidence_review": {
            "cleanup_plan_reviewed": "passed",
            "dry_run_reviewed": "passed",
            "capacity_pressure_acknowledged": "passed",
            "restore_drill_blocker_acknowledged": "passed",
        },
        "allowed_actions": {
            "delete_selected_docker_images": True,
        },
        "forbidden_actions": {
            "docker_system_prune": True,
            "delete_containers": True,
            "delete_volumes": True,
            "delete_logs": True,
            "delete_env_files": True,
            "delete_backups": True,
            "delete_vectorstores": True,
        },
        "post_cleanup_required": {
            "rerun_capacity_snapshot": True,
            "rerun_restore_drill_feasibility": True,
            "rerun_live_health_probe": True,
        },
        "redaction_boundary": {
            "raw_paths_included": False,
            "server_ip_included": False,
            "secret_values_included": False,
            "log_lines_included": False,
        },
    }


def test_disk_remediation_gate_ready_for_explicit_approval_without_record():
    report = approval.build_disk_remediation_approval_report(
        cleanup_plan=_cleanup_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
        restore_feasibility=_restore_feasibility(),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "ready_for_explicit_approval"
    assert report["sections"]["approval"]["template"]["forbidden_actions"]["delete_volumes"] is True
    assert report["policy"]["deletes_images"] is False


def test_disk_remediation_gate_passes_with_complete_private_approval():
    report = approval.build_disk_remediation_approval_report(
        cleanup_plan=_cleanup_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
        restore_feasibility=_restore_feasibility(),
        approval_record=_approval_record(),
    )

    assert report["status"] == "degraded"
    assert report["decision"] == "approved_for_controlled_cleanup"
    assert any(item["section"] == "capacity" for item in report["degraded_reasons"])


def test_disk_remediation_gate_reaches_approved_when_capacity_is_clean():
    clean_capacity = _capacity(status="passed")
    clean_capacity["sections"]["host_capacity"]["disk"]["root"] = {
        "status": "passed",
        "free_mb": 8192,
        "used_percent": 70,
    }
    clean_capacity["sections"]["host_capacity"]["disk"]["deploy"] = {
        "status": "passed",
        "free_mb": 8192,
        "used_percent": 70,
    }
    clean_restore = _restore_feasibility(status="passed")
    clean_restore["sections"]["restore_workspace_space"] = {
        "status": "passed",
        "effective_free_mb": 8192,
        "required_free_mb": 4096,
    }
    clean_restore["blocked_reasons"] = []

    report = approval.build_disk_remediation_approval_report(
        cleanup_plan=_cleanup_plan(status="passed"),
        dry_run=_dry_run(),
        capacity=clean_capacity,
        restore_feasibility=clean_restore,
        approval_record=_approval_record(),
    )

    assert report["status"] == "passed"
    assert report["decision"] == "approved_for_controlled_cleanup"


def test_disk_remediation_gate_blocks_unsafe_approval_scope():
    record = _approval_record()
    record["forbidden_actions"]["docker_system_prune"] = False

    report = approval.build_disk_remediation_approval_report(
        cleanup_plan=_cleanup_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
        restore_feasibility=_restore_feasibility(),
        approval_record=record,
    )

    assert report["status"] == "blocked"
    assert any(
        item["key"] == "forbidden_actions.docker_system_prune"
        for item in report["blocked_reasons"]
    )


def test_disk_remediation_gate_blocks_dry_run_that_deleted_images():
    dry_run = _dry_run()
    dry_run["policy"]["deletes_images"] = True

    report = approval.build_disk_remediation_approval_report(
        cleanup_plan=_cleanup_plan(),
        dry_run=dry_run,
        capacity=_capacity(),
        restore_feasibility=_restore_feasibility(),
        approval_record=_approval_record(),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "not_ready_for_cleanup"
    assert any(item["key"] == "dry_run_deleted_images" for item in report["blocked_reasons"])


def test_disk_remediation_gate_markdown_mentions_no_deletion_policy():
    report = approval.build_disk_remediation_approval_report(
        cleanup_plan=_cleanup_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
        restore_feasibility=_restore_feasibility(),
    )

    markdown = approval.build_disk_remediation_approval_markdown(report)

    assert "Disk Remediation Approval Gate" in markdown
    assert "no SSH, no deletion" in markdown
    assert "ready_for_explicit_approval" in markdown


def test_disk_remediation_gate_cli_writes_template(tmp_path: Path):
    output_path = tmp_path / "approval-template.json"

    code = approval.main(["--template", "--output", str(output_path)])

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["forbidden_actions"]["delete_backups"] is True


def test_disk_remediation_gate_cli_writes_report(tmp_path: Path):
    cleanup_path = tmp_path / "cleanup.json"
    dry_path = tmp_path / "dry.json"
    capacity_path = tmp_path / "capacity.json"
    restore_path = tmp_path / "restore.json"
    output_path = tmp_path / "report.json"
    cleanup_path.write_text(json.dumps(_cleanup_plan(), ensure_ascii=False), encoding="utf-8")
    dry_path.write_text(json.dumps(_dry_run(), ensure_ascii=False), encoding="utf-8")
    capacity_path.write_text(json.dumps(_capacity(), ensure_ascii=False), encoding="utf-8")
    restore_path.write_text(json.dumps(_restore_feasibility(), ensure_ascii=False), encoding="utf-8")

    code = approval.main(
        [
            "--cleanup-plan-json",
            str(cleanup_path),
            "--dry-run-json",
            str(dry_path),
            "--capacity-json",
            str(capacity_path),
            "--restore-feasibility-json",
            str(restore_path),
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["decision"] == "ready_for_explicit_approval"
