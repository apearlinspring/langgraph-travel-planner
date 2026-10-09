import json
from pathlib import Path

from scripts import render_docker_build_cache_cleanup_approval_request as renderer


def _approval_gate(decision="ready_for_explicit_approval"):
    return {
        "version": "docker_build_cache_cleanup_approval.v1",
        "status": "degraded",
        "decision": decision,
        "degraded_reasons": [{"key": "approval_record_missing"}],
        "sections": {
            "build_cache_cleanup_plan": {
                "status": "degraded",
                "reclaimable_mb": 23582.7,
                "root_used_percent": 96,
                "root_free_mb": 2464,
            },
            "build_cache_cleanup_dry_run": {
                "status": "degraded",
                "prune_result": "dry_run",
            },
            "capacity_snapshot": {
                "status": "degraded",
                "root_used_percent": 96,
                "root_free_mb": 2464,
                "deploy_used_percent": 96,
                "deploy_free_mb": 2464,
            },
            "approval_record": {
                "status": "not_checked",
                "approval_present": False,
            },
        },
    }


def _go_no_go():
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": "degraded",
        "decision": "conditional_go",
        "blockers": [],
        "degraded_reasons": [{"section": "docker_build_cache_cleanup_approval_gate"}],
    }


def test_build_cache_approval_request_summarizes_gate_without_approving_cleanup():
    report = renderer.build_docker_build_cache_cleanup_approval_request(
        approval_gate=_approval_gate(),
        go_no_go=_go_no_go(),
    )

    assert report["status"] == "needs_human_decision"
    assert report["decision"] == "request_controlled_docker_build_cache_cleanup_approval"
    assert report["policy"]["deletes_build_cache"] is False
    assert report["policy"]["runs_system_prune"] is False
    assert report["policy"]["approval_token_echoed"] is False
    assert report["evidence_summary"]["build_cache_cleanup_plan"]["reclaimable_mb"] == 23582.7
    assert report["evidence_summary"]["build_cache_cleanup_dry_run"]["prune_result"] == "dry_run"
    assert report["go_no_go_summary"]["decision"] == "conditional_go"


def test_build_cache_approval_request_blocks_when_gate_is_not_ready():
    report = renderer.build_docker_build_cache_cleanup_approval_request(
        approval_gate=_approval_gate(decision="not_ready_for_build_cache_cleanup"),
        go_no_go=_go_no_go(),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "do_not_execute_build_cache_cleanup_yet"


def test_build_cache_approval_request_markdown_keeps_paths_and_token_redacted():
    report = renderer.build_docker_build_cache_cleanup_approval_request(
        approval_gate=_approval_gate(),
        go_no_go=_go_no_go(),
    )
    markdown = renderer.render_docker_build_cache_cleanup_approval_request_markdown(report)

    assert "reclaimable=23582.7 MB" in markdown
    assert "<ssh-user>@<server-host>" in markdown
    assert "<approval-token>" in markdown
    assert "APPROVE_DOCKER_BUILD_CACHE_CLEANUP" not in markdown
    assert "D:\\Users\\Administrator" not in markdown
    forbidden_ip = ".".join(("8", "145", "46", "253"))
    assert forbidden_ip not in markdown


def test_build_cache_approval_request_cli_writes_markdown_without_echoing_paths(tmp_path: Path):
    gate_path = tmp_path / "build-cache-approval-gate.json"
    no_go_path = tmp_path / "m1-go-no-go.json"
    output_path = tmp_path / "approval-request.md"
    gate_path.write_text(json.dumps(_approval_gate()), encoding="utf-8")
    no_go_path.write_text(json.dumps(_go_no_go()), encoding="utf-8")

    code = renderer.main(
        [
            "--approval-gate-json",
            str(gate_path),
            "--go-no-go-json",
            str(no_go_path),
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "Docker Build Cache Cleanup Approval Request" in payload
    assert str(gate_path) not in payload
    assert str(no_go_path) not in payload
