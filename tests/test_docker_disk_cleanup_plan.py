import subprocess
from pathlib import Path

from scripts import collect_docker_disk_cleanup_plan as plan


def _runner(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def test_docker_disk_cleanup_plan_is_read_only_and_redacted():
    stdout = "\n".join(
        [
            "root_disk\t60416|2048|97|/",
            "deploy_dir_present\ttrue",
            "deploy_disk\t60416|2048|97|/opt",
            "docker_available\ttrue",
            "docker_version\tDocker version 26.1.4",
            "docker_system_df\tImages 70 10 50GB 40GB;",
            "running_image\tsha256:111111111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|zhixing-backend",
            "container_image\tsha256:111111111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|zhixing-backend|running",
            "container_image\tsha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|old-debug|exited",
            'image\tsha256:111111111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|["langgraph-travel-planner-backend:latest"]|[]|2026-06-24T00:00:00Z|500000000',
            'image\tsha256:222222222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb|["old-runtime:latest"]|[]|2026-06-20T00:00:00Z|700000000',
            'image\tsha256:333333333333cccccccccccccccccccccccccccccccccccccccccccc|["<none>:<none>"]|[]|2026-06-18T00:00:00Z|300000000',
        ]
    )

    report = plan.build_docker_disk_cleanup_plan_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        max_candidates=2,
        command_runner=_runner(stdout),
    )

    payload = str(report)
    assert report["status"] == "degraded"
    assert report["risk_status"] == "attention_required"
    assert report["policy"]["read_only"] is True
    assert report["policy"]["deletes_images"] is False
    assert report["policy"]["runs_prune"] is False
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert report["images"]["total_count"] == 3
    assert report["images"]["protected_count"] == 2
    assert report["images"]["candidate_count"] == 1
    assert [item["image_id_prefix"] for item in report["selected_candidates"]] == [
        "333333333333",
    ]
    assert all(item["repo_tags_echoed"] is False for item in report["selected_candidates"])
    assert report["selected_candidates"][0]["repo_tags_count"] == 1
    assert report["selected_candidates"][0]["reason"] == "not_used_by_any_container"
    assert all(item["protected"] is False for item in report["selected_candidates"])
    assert report["approval_required"]["required_for_execution"] is True
    assert report["approval_required"]["destructive_action_in_this_plan"] is False
    assert "old-runtime:latest" not in payload


def test_docker_disk_cleanup_plan_blocks_missing_target():
    report = plan.build_docker_disk_cleanup_plan_report(
        ssh_target="",
        deploy_dir="",
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_target"


def test_docker_disk_cleanup_plan_cli_writes_utf8_output(tmp_path: Path):
    output_path = tmp_path / "cleanup-plan.json"

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


def test_docker_disk_cleanup_plan_blocks_fail_threshold():
    stdout = "\n".join(
        [
            "root_disk\t60416|512|98|/",
            "deploy_dir_present\ttrue",
            "deploy_disk\t60416|512|98|/opt",
            "docker_available\ttrue",
        ]
    )

    report = plan.build_docker_disk_cleanup_plan_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["risk_status"] == "blocked"
    assert any(item["key"] == "disk_usage_fail_threshold" for item in report["blocked_reasons"])
