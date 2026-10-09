import json
from pathlib import Path

from scripts import check_docker_build_cache_cleanup_approval as approval


def _plan():
    return {
        "version": "docker_build_cache_cleanup_plan.v1",
        "status": "degraded",
        "policy": {
            "read_only": True,
            "deletes_build_cache": False,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_system_prune": False,
        },
        "disk": {"root": {"free_mb": 2464, "used_percent": 96}},
        "build_cache": {"reclaimable_mb": 23582.7},
        "approval_required": {"required_for_execution": True},
    }


def _dry_run():
    return {
        "version": "docker_build_cache_cleanup_execution.v1",
        "status": "degraded",
        "mode": "dry_run",
        "policy": {
            "deletes_build_cache": False,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_system_prune": False,
        },
        "prune": {"result": "dry_run"},
    }


def _capacity():
    return {
        "version": "server_capacity_snapshot.v1",
        "status": "degraded",
        "sections": {
            "host_capacity": {
                "disk": {
                    "root": {"status": "degraded", "free_mb": 2464, "used_percent": 96},
                    "deploy": {"status": "degraded", "free_mb": 2464, "used_percent": 96},
                }
            }
        },
    }


def _approval_record():
    return {
        "approval_id": "docker-build-cache-cleanup-20260625",
        "approved_by_role": "release operator",
        "approved_at": "2026-06-25T02:30:00+08:00",
        "scope": "delete Docker build cache only using docker builder prune -a -f",
        "reason": "Disk pressure remains after image cleanup.",
        "evidence_reviewed": {
            "build_cache_cleanup_plan": True,
            "build_cache_cleanup_dry_run": True,
            "capacity_snapshot": True,
            "future_build_slowdown_accepted": True,
        },
        "allowed_actions": {"delete_docker_build_cache": True},
        "forbidden_actions_confirmed": {
            "docker_system_prune": True,
            "delete_images": True,
            "delete_containers": True,
            "delete_volumes": True,
            "delete_logs": True,
            "delete_env_files": True,
            "delete_backups": True,
            "delete_vectorstores": True,
            "read_env_files": True,
            "read_logs": True,
            "query_database_rows": True,
            "read_redis_keys": True,
        },
        "post_execution_required_checks": {
            "capacity_snapshot_rerun": True,
            "restore_drill_feasibility_rerun": True,
            "m1_go_no_go_rerun": True,
        },
        "notes": "M1 controlled trial needs enough disk headroom.",
    }


def test_build_cache_cleanup_approval_ready_without_approval_record():
    report = approval.build_docker_build_cache_cleanup_approval_report(
        plan=_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
    )

    assert report["status"] == "degraded"
    assert report["decision"] == "ready_for_explicit_approval"
    assert report["sections"]["approval_record"]["status"] == "not_checked"
    assert report["policy"]["deletes_build_cache"] is False


def test_build_cache_cleanup_approval_passes_with_valid_record():
    report = approval.build_docker_build_cache_cleanup_approval_report(
        plan=_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
        approval=_approval_record(),
    )

    assert report["status"] == "passed"
    assert report["decision"] == "approved_for_controlled_build_cache_cleanup"
    assert report["sections"]["approval_record"]["status"] == "passed"


def test_build_cache_cleanup_approval_blocks_system_prune_scope():
    record = _approval_record()
    record["forbidden_actions_confirmed"]["docker_system_prune"] = False

    report = approval.build_docker_build_cache_cleanup_approval_report(
        plan=_plan(),
        dry_run=_dry_run(),
        capacity=_capacity(),
        approval=record,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "not_ready_for_build_cache_cleanup"
    assert any(item["key"] == "forbidden_docker_system_prune_not_confirmed" for item in report["blocked_reasons"])


def test_build_cache_cleanup_approval_template_cli_writes_utf8(tmp_path: Path):
    output = tmp_path / "approval-template.json"

    code = approval.main(["--template", "--output", str(output)])

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["allowed_actions"]["delete_docker_build_cache"] is True
    assert payload["forbidden_actions_confirmed"]["delete_images"] is True


def test_build_cache_cleanup_approval_cli_redacts_paths(tmp_path: Path):
    plan = tmp_path / "plan.json"
    dry_run = tmp_path / "dry-run.json"
    capacity = tmp_path / "capacity.json"
    output = tmp_path / "approval-gate.json"
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    dry_run.write_text(json.dumps(_dry_run()), encoding="utf-8")
    capacity.write_text(json.dumps(_capacity()), encoding="utf-8")

    code = approval.main(
        [
            "--plan-json",
            str(plan),
            "--dry-run-json",
            str(dry_run),
            "--capacity-json",
            str(capacity),
            "--output",
            str(output),
        ]
    )
    payload = output.read_text(encoding="utf-8")

    assert code == 0
    assert str(plan) not in payload
    assert "ready_for_explicit_approval" in payload
