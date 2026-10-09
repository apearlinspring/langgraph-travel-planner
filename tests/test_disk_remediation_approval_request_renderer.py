import json
from pathlib import Path

from scripts import render_disk_remediation_approval_request as renderer


def _approval_gate(decision="ready_for_explicit_approval"):
    return {
        "version": "disk_remediation_approval.v1",
        "status": "blocked",
        "decision": decision,
        "blocked_reasons": [{"section": "approval", "key": "missing_approval_record"}],
        "degraded_reasons": [{"section": "capacity", "key": "root_disk_degraded"}],
        "sections": {
            "cleanup_plan": {
                "status": "degraded",
                "selected_images": 20,
                "candidate_images": 639,
                "protected_images": 4,
                "estimated_selected_size_mb": 150449.7,
            },
            "dry_run": {
                "status": "passed",
                "dry_run_count": 20,
                "expected_selected": 20,
            },
            "capacity": {
                "status": "degraded",
                "root_used_percent": 97,
                "root_free_mb": 2266,
                "deploy_used_percent": 97,
                "deploy_free_mb": 2266,
            },
            "restore_feasibility": {
                "status": "degraded",
                "space_status": "blocked",
                "effective_free_mb": 2266,
                "required_free_mb": 4096,
            },
            "approval": {
                "status": "blocked",
                "approval_id_present": False,
            },
        },
    }


def _go_no_go():
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": "blocked",
        "decision": "no_go",
        "blockers": [{"section": "disk_remediation_approval_gate"}],
        "degraded_reasons": [{"section": "server_capacity_snapshot"}],
    }


def test_approval_request_summarizes_gate_without_approving_cleanup():
    report = renderer.build_disk_remediation_approval_request(
        approval_gate=_approval_gate(),
        go_no_go=_go_no_go(),
    )

    assert report["status"] == "needs_human_decision"
    assert report["decision"] == "request_controlled_docker_image_cleanup_approval"
    assert report["policy"]["deletes_images"] is False
    assert report["policy"]["approval_token_echoed"] is False
    assert report["evidence_summary"]["cleanup_plan"]["selected_images"] == 20
    assert report["evidence_summary"]["restore_feasibility"]["required_free_mb"] == 4096
    assert report["go_no_go_summary"]["decision"] == "no_go"


def test_approval_request_blocks_when_gate_is_not_ready_for_approval():
    report = renderer.build_disk_remediation_approval_request(
        approval_gate=_approval_gate(decision="not_ready_for_cleanup"),
        go_no_go=_go_no_go(),
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "do_not_execute_cleanup_yet"


def test_approval_request_markdown_keeps_paths_and_token_redacted():
    report = renderer.build_disk_remediation_approval_request(
        approval_gate=_approval_gate(),
        go_no_go=_go_no_go(),
    )
    markdown = renderer.render_disk_remediation_approval_request_markdown(report)

    assert "selected=20" in markdown
    assert "<ssh-user>@<server-host>" in markdown
    assert "<approval-token>" in markdown
    assert "APPROVE_DOCKER_IMAGE_CLEANUP" not in markdown
    assert "D:\\Users\\Administrator" not in markdown
    assert "203.0.113.10" not in markdown


def test_approval_request_cli_writes_markdown_without_echoing_source_paths(tmp_path: Path):
    gate_path = tmp_path / "disk-remediation-approval-gate.json"
    no_go_path = tmp_path / "m1-current-go-no-go.json"
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
    assert "Disk Remediation Approval Request" in payload
    assert str(gate_path) not in payload
    assert str(no_go_path) not in payload
