import json
from pathlib import Path

from scripts import check_docker_build_cache_post_cleanup as post


def _execution(status="passed", after_reclaimable=0.0):
    return {
        "version": "docker_build_cache_cleanup_execution.v1",
        "status": status,
        "mode": "execute",
        "approval": {"approval_token_accepted": True},
        "policy": {
            "deletes_build_cache": True,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_system_prune": False,
        },
        "prune": {"result": "passed"},
        "build_cache": {
            "before": {"reclaimable_mb": 23582.7},
            "after": {"reclaimable_mb": after_reclaimable},
            "estimated_reclaimable_delta_mb": 23582.7 - after_reclaimable,
        },
    }


def _capacity(free_mb, used_percent=58, status="passed"):
    return {
        "version": "server_capacity_snapshot.v1",
        "status": status,
        "sections": {
            "host_capacity": {
                "disk": {
                    "root": {"status": status, "free_mb": free_mb, "used_percent": used_percent},
                    "deploy": {"status": status, "free_mb": free_mb, "used_percent": used_percent},
                }
            }
        },
    }


def _restore(free_mb, required_mb=4096, status="passed"):
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


def test_build_cache_post_cleanup_can_pass_when_execution_capacity_and_restore_pass():
    report = post.build_docker_build_cache_post_cleanup_report(
        execution_report=_execution(),
        before_capacity=_capacity(2464, used_percent=96, status="degraded"),
        after_capacity=_capacity(26000),
        restore_feasibility=_restore(26000),
    )

    assert report["status"] == "passed"
    assert report["decision"] == "build_cache_remediation_evidence_passed"
    assert report["sections"]["execution"]["estimated_reclaimable_delta_mb"] == 23582.7
    assert report["sections"]["capacity_delta"]["root_free_delta_mb"] == 23536
    assert report["policy"]["deletes_build_cache"] is False


def test_build_cache_post_cleanup_requires_expansion_when_space_still_blocked():
    report = post.build_docker_build_cache_post_cleanup_report(
        execution_report=_execution(),
        before_capacity=_capacity(2464, used_percent=96, status="degraded"),
        after_capacity=_capacity(3000, used_percent=94, status="degraded"),
        restore_feasibility=_restore(3000, status="blocked"),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "storage_expansion_required"
    assert report["sections"]["restore_feasibility"]["required_free_mb"] == 4096


def test_build_cache_post_cleanup_blocks_wrong_execution_mode():
    execution = _execution()
    execution["mode"] = "dry_run"

    report = post.build_docker_build_cache_post_cleanup_report(
        execution_report=execution,
        before_capacity=_capacity(2464, used_percent=96, status="degraded"),
        after_capacity=_capacity(26000),
        restore_feasibility=_restore(26000),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "not_execute_mode" for item in report["blocked_reasons"])


def test_build_cache_post_cleanup_markdown_redacts_paths_and_summarizes_deltas():
    report = post.build_docker_build_cache_post_cleanup_report(
        execution_report=_execution(),
        before_capacity=_capacity(2464, used_percent=96, status="degraded"),
        after_capacity=_capacity(26000),
        restore_feasibility=_restore(26000),
    )

    markdown = post.build_docker_build_cache_post_cleanup_markdown(report)

    assert "Docker Build Cache Post-Cleanup Check" in markdown
    assert "root_delta=23536 MB" in markdown
    assert "reclaimed=23582.7 MB" in markdown
    assert "D:\\Users\\Administrator" not in markdown


def test_build_cache_post_cleanup_cli_writes_json_without_echoing_source_paths(tmp_path: Path):
    execution = tmp_path / "execution.json"
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    restore = tmp_path / "restore.json"
    output = tmp_path / "post.json"
    execution.write_text(json.dumps(_execution()), encoding="utf-8")
    before.write_text(json.dumps(_capacity(2464, used_percent=96, status="degraded")), encoding="utf-8")
    after.write_text(json.dumps(_capacity(26000)), encoding="utf-8")
    restore.write_text(json.dumps(_restore(26000)), encoding="utf-8")

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

    assert code == 0
    assert str(execution) not in payload
    assert str(after) not in payload
    assert "build_cache_remediation_evidence_passed" in payload
