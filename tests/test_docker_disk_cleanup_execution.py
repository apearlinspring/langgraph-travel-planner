import json
import subprocess
from pathlib import Path

from scripts import execute_docker_disk_cleanup as cleanup


def _plan():
    return {
        "version": "docker_disk_cleanup_plan.v1",
        "status": "degraded",
        "selected_candidates": [
            {
                "image_id": "sha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "protected": False,
                "cleanup_candidate": True,
            },
            {
                "image_id": "sha256:333333333333cccccccccccccccccccccccccccccccccccccccccccc",
                "protected": False,
                "cleanup_candidate": True,
            },
        ],
    }


def _runner(stdout: str, calls: list | None = None, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        if calls is not None:
            calls.append(
                {
                    "args": list(args),
                    "input_text": input_text,
                    "timeout_seconds": timeout_seconds,
                }
            )
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def test_cleanup_execution_defaults_to_dry_run_and_redacts_target():
    calls = []
    stdout = "\n".join(
        [
            "root_disk_before\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk_before\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "image_result\tsha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|dry_run",
            "image_result\tsha256:333333333333cccccccccccccccccccccccccccccccccccccccccccc|dry_run",
            "root_disk_after\t60416|2048|97|/",
            "deploy_disk_after\t60416|2048|97|/opt",
        ]
    )

    report = cleanup.build_docker_disk_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data=_plan(),
        command_runner=_runner(stdout, calls),
    )
    payload = str(report)

    assert report["status"] == "passed"
    assert report["mode"] == "dry_run"
    assert report["policy"]["deletes_images"] is False
    assert report["policy"]["runs_prune"] is False
    assert report["approval"]["execute_requested"] is False
    assert report["result_counts"]["dry_run"] == 2
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert calls[0]["args"][-4] == "/opt/private-app"
    assert calls[0]["args"][-3] == "0"


def test_cleanup_execution_blocks_execute_without_approval_before_ssh():
    calls = []

    report = cleanup.build_docker_disk_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data=_plan(),
        execute=True,
        approval_token="wrong",
        command_runner=_runner("", calls),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_approval"
    assert report["approval"]["approval_token_accepted"] is False
    assert calls == []


def test_cleanup_execution_reports_deleted_and_protected_candidates():
    stdout = "\n".join(
        [
            "root_disk_before\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk_before\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "image_result\tsha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|deleted",
            "image_result\tsha256:333333333333cccccccccccccccccccccccccccccccccccccccccccc|skipped_protected",
            "root_disk_after\t60416|4096|93|/",
            "deploy_disk_after\t60416|4096|93|/opt",
        ]
    )

    report = cleanup.build_docker_disk_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data=_plan(),
        execute=True,
        approval_token=cleanup.APPROVAL_TOKEN,
        command_runner=_runner(stdout),
    )

    assert report["status"] == "degraded"
    assert report["mode"] == "execute"
    assert report["policy"]["deletes_images"] is True
    assert report["policy"]["protects_container_images"] is True
    assert report["approval"]["approval_token_accepted"] is True
    assert report["result_counts"]["deleted"] == 1
    assert report["result_counts"]["skipped_protected"] == 1
    assert report["degraded_reasons"][0]["key"] == "candidate_skipped"


def test_cleanup_execution_blocks_invalid_plan():
    report = cleanup.build_docker_disk_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data={"selected_candidates": [{"image_id": "not-an-image"}]},
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_candidates"


def test_cleanup_execution_cli_writes_utf8_output(tmp_path: Path):
    plan_path = tmp_path / "cleanup-plan.json"
    output_path = tmp_path / "cleanup-execution.json"
    plan_path.write_text(json.dumps(_plan(), ensure_ascii=False), encoding="utf-8")

    code = cleanup.main(
        [
            "--ssh-target",
            "",
            "--deploy-dir",
            "",
            "--plan-json",
            str(plan_path),
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    text = output_path.read_text(encoding="utf-8")
    assert '"status": "blocked"' in text
    assert "missing_target" in text


def test_cleanup_execution_accepts_nested_go_no_go_payload():
    calls = []
    stdout = "\n".join(
        [
            "root_disk_before\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk_before\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "image_result\tsha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|dry_run",
            "root_disk_after\t60416|2048|97|/",
            "deploy_disk_after\t60416|2048|97|/opt",
        ]
    )

    report = cleanup.build_docker_disk_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data={"sections": {"docker_disk_cleanup_plan": _plan()}},
        max_delete_count=1,
        command_runner=_runner(stdout, calls),
    )

    assert report["status"] == "passed"
    assert report["plan_summary"]["version"] == "docker_disk_cleanup_plan.v1"
    assert report["plan_summary"]["requested_image_count"] == 1
    assert calls[0]["args"][-1].startswith("sha256:222222222222")
