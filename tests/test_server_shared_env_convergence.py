import subprocess

from scripts import converge_server_shared_env as converge


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


def test_shared_env_convergence_dry_run_reports_degraded_without_echoing_target():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\trelease_symlink",
            "root_env_present\ttrue",
            "shared_env_present\tfalse",
            "root_env_mode\t600",
            "root_env_size_present\ttrue",
            "action\tdry_run",
        ]
    )

    report = converge.build_server_shared_env_convergence_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )
    payload = str(report)

    assert report["status"] == "degraded"
    assert report["mode"] == "dry_run"
    assert report["policy"]["copies_env_file"] is False
    assert report["policy"]["prints_env_values"] is False
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["layout"]["root_env_present"] is True
    assert report["layout"]["shared_env_present"] is False
    assert report["action"]["result"] == "dry_run"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload


def test_shared_env_convergence_blocks_execute_without_approval_before_ssh():
    calls = []

    report = converge.build_server_shared_env_convergence_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        execute=True,
        approval_token="wrong",
        command_runner=_runner("", calls),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_approval"
    assert report["approval"]["approval_token_accepted"] is False
    assert calls == []


def test_shared_env_convergence_execute_copies_when_approved_and_missing():
    calls = []
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\trelease_symlink",
            "root_env_present\ttrue",
            "shared_env_present\tfalse",
            "root_env_mode\t600",
            "root_env_size_present\ttrue",
            "action\tcopied_root_to_shared",
            "shared_env_present_after\ttrue",
            "shared_env_mode_after\t600",
            "shared_env_size_present_after\ttrue",
        ]
    )

    report = converge.build_server_shared_env_convergence_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        execute=True,
        approval_token=converge.APPROVAL_TOKEN,
        command_runner=_runner(stdout, calls),
    )

    assert report["status"] == "passed"
    assert report["mode"] == "execute"
    assert report["policy"]["copies_env_file"] is True
    assert report["policy"]["overwrites_existing_shared_env"] is False
    assert report["action"]["copied"] is True
    assert report["layout"]["shared_env_present"] is True
    assert report["layout"]["shared_env_mode_status"] == "passed"
    assert calls[0]["args"][-2:] == ["/opt/private-app", "1"]


def test_shared_env_convergence_passes_when_shared_env_already_exists():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\trelease_symlink",
            "root_env_present\ttrue",
            "shared_env_present\ttrue",
            "root_env_mode\t600",
            "shared_env_mode\t600",
            "shared_env_size_present\ttrue",
            "action\tdry_run",
        ]
    )

    report = converge.build_server_shared_env_convergence_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "passed"
    assert report["layout"]["shared_env_present"] is True
    assert report["degraded_reasons"] == []


def test_shared_env_convergence_blocks_missing_env_files():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\trelease_symlink",
            "root_env_present\tfalse",
            "shared_env_present\tfalse",
            "action\tdry_run",
        ]
    )

    report = converge.build_server_shared_env_convergence_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "env_missing" for item in report["blocked_reasons"])
