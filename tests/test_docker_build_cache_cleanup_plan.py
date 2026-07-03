import subprocess
from pathlib import Path

from scripts import collect_docker_build_cache_cleanup_plan as plan


def _runner(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def test_docker_build_cache_cleanup_plan_is_read_only_and_redacted():
    stdout = "\n".join(
        [
            "root_disk\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "docker_version\tDocker version 26.1.4",
            "docker_system_df\tTYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE;Images          4         4         6.906GB   0B (0%);Build Cache     157       0         23.03GB   23.03GB;",
        ]
    )

    report = plan.build_docker_build_cache_cleanup_plan_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )
    payload = str(report)

    assert report["status"] == "degraded"
    assert report["risk_status"] == "attention_required"
    assert report["policy"]["read_only"] is True
    assert report["policy"]["deletes_build_cache"] is False
    assert report["policy"]["runs_system_prune"] is False
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert report["build_cache"]["total_count"] == 157
    assert report["build_cache"]["active_count"] == 0
    assert report["build_cache"]["size_mb"] == 23582.7
    assert report["build_cache"]["reclaimable_mb"] == 23582.7
    assert report["approval_required"]["required_for_execution"] is True


def test_docker_build_cache_cleanup_plan_blocks_missing_target():
    report = plan.build_docker_build_cache_cleanup_plan_report(
        ssh_target="",
        deploy_dir="",
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_target"


def test_docker_build_cache_cleanup_plan_cli_writes_utf8_output(tmp_path: Path):
    output_path = tmp_path / "build-cache-plan.json"

    code = plan.main(
        [
            "--ssh-target",
            "",
            "--deploy-dir",
            "",
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    text = output_path.read_text(encoding="utf-8")
    assert '"status": "blocked"' in text
    assert "missing_target" in text
