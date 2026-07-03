import json
import subprocess
from pathlib import Path

from scripts import execute_docker_build_cache_cleanup as cleanup


def _plan():
    return {
        "version": "docker_build_cache_cleanup_plan.v1",
        "status": "degraded",
        "build_cache": {
            "reclaimable_mb": 23582.7,
        },
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


def test_build_cache_cleanup_defaults_to_dry_run_and_redacts_target():
    calls = []
    stdout = "\n".join(
        [
            "root_disk_before\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk_before\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "docker_system_df_before\tTYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE;Build Cache     157       0         23.03GB   23.03GB;",
            "prune_result\tdry_run",
            "docker_system_df_after\tTYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE;Build Cache     157       0         23.03GB   23.03GB;",
            "root_disk_after\t60416|2048|97|/",
            "deploy_disk_after\t60416|2048|97|/opt",
        ]
    )

    report = cleanup.build_docker_build_cache_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data=_plan(),
        command_runner=_runner(stdout, calls),
    )
    payload = str(report)

    assert report["status"] == "degraded"
    assert report["mode"] == "dry_run"
    assert report["policy"]["deletes_build_cache"] is False
    assert report["policy"]["runs_system_prune"] is False
    assert report["prune"]["result"] == "dry_run"
    assert report["build_cache"]["before"]["reclaimable_mb"] == 23582.7
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert calls[0]["args"][-2] == "/opt/private-app"
    assert calls[0]["args"][-1] == "0"


def test_build_cache_cleanup_blocks_execute_without_approval_before_ssh():
    calls = []

    report = cleanup.build_docker_build_cache_cleanup_execution_report(
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


def test_build_cache_cleanup_reports_passed_execution_delta():
    stdout = "\n".join(
        [
            "root_disk_before\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk_before\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "docker_system_df_before\tTYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE;Build Cache     157       0         23.03GB   23.03GB;",
            "prune_result\tpassed",
            "docker_system_df_after\tTYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE;Build Cache     0         0         0B   0B;",
            "root_disk_after\t60416|25600|58|/",
            "deploy_disk_after\t60416|25600|58|/opt",
        ]
    )

    report = cleanup.build_docker_build_cache_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data=_plan(),
        execute=True,
        approval_token=cleanup.APPROVAL_TOKEN,
        command_runner=_runner(stdout),
    )

    assert report["status"] == "passed"
    assert report["mode"] == "execute"
    assert report["policy"]["deletes_build_cache"] is True
    assert report["policy"]["runs_builder_prune"] is True
    assert report["policy"]["runs_system_prune"] is False
    assert report["approval"]["approval_token_accepted"] is True
    assert report["build_cache"]["estimated_reclaimable_delta_mb"] == 23582.7
    assert report["disk"]["root_free_delta_mb"] == 23552


def test_build_cache_cleanup_blocks_invalid_plan():
    report = cleanup.build_docker_build_cache_cleanup_execution_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        plan_data={"version": "docker_disk_cleanup_plan.v1"},
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "invalid_plan"


def test_build_cache_cleanup_cli_writes_utf8_output(tmp_path: Path):
    plan_path = tmp_path / "build-cache-plan.json"
    output_path = tmp_path / "build-cache-execution.json"
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
