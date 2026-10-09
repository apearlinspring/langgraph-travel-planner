import subprocess

from scripts import prepare_production_image_build_execution as prep


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
        return subprocess.CompletedProcess(list(args), returncode, stdout=stdout, stderr=stderr)

    return run


def test_image_build_execution_prep_dry_run_does_not_connect_or_echo_target():
    calls = []

    report = prep.build_production_image_build_execution_prep_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        build_id="build-20260703",
        release_label="private-release-label",
        command_runner=_runner("", calls),
    )
    payload = str(report)

    assert report["status"] == "ready_for_explicit_approval"
    assert report["mode"] == "dry_run"
    assert report["policy"]["connects_ssh"] is False
    assert report["policy"]["runs_docker"] is False
    assert report["policy"]["starts_services"] is False
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["plan"]["runs_runtime_dependency_scope_gate_first"] is True
    assert calls == []
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert "private-release-label" not in payload


def test_image_build_execution_execute_blocks_without_approval_before_ssh():
    calls = []

    report = prep.build_production_image_build_execution_prep_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        build_id="build-20260703",
        execute=True,
        approval_token="wrong",
        command_runner=_runner("", calls),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_approval"
    assert report["approval"]["approval_token_accepted"] is False
    assert calls == []


def test_image_build_execution_execute_starts_background_job_when_approved():
    calls = []
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "current_release_present\ttrue",
            "update_script_present\ttrue",
            "runtime_requirements_present\ttrue",
            "docker_available\ttrue",
            "background_job_started\ttrue",
            "pid_recorded\ttrue",
            "log_file_recorded\ttrue",
            "record_file_recorded\ttrue",
            "record_path\t/opt/private-app/shared/build-records/build-20260703/execution.tsv",
            "log_path\t/opt/private-app/shared/build-records/build-20260703/build.log",
            "pid\t12345",
        ]
    )

    report = prep.build_production_image_build_execution_prep_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        build_id="build-20260703",
        release_label="private-release-label",
        execute=True,
        approval_token=prep.APPROVAL_TOKEN,
        command_runner=_runner(stdout, calls),
    )
    payload = str(report)

    assert report["status"] == "background_job_started"
    assert report["policy"]["connects_ssh"] is True
    assert report["policy"]["runs_docker"] is True
    assert report["policy"]["starts_services"] is True
    assert report["background_job"]["pid_recorded"] is True
    assert report["background_job"]["log_path_echoed"] is False
    assert report["background_job"]["record_path_echoed"] is False
    assert calls[0]["args"][-4:] == [
        "/opt/private-app",
        "build-20260703",
        "private-release-label",
        "1800",
    ]
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert "private-release-label" not in payload
    assert "12345" not in payload


def test_image_build_execution_execute_blocks_remote_precheck_failure():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "current_release_present\ttrue",
            "update_script_present\tfalse",
            "runtime_requirements_present\ttrue",
            "docker_available\ttrue",
        ]
    )

    report = prep.build_production_image_build_execution_prep_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        build_id="build-20260703",
        execute=True,
        approval_token=prep.APPROVAL_TOKEN,
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "remote_precheck_failed"
    assert report["remote_precheck"]["update_script_present"] is False


def test_image_build_execution_blocks_invalid_build_id():
    report = prep.build_production_image_build_execution_prep_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        build_id="../bad",
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "invalid_build_id" for item in report["blocked_reasons"])


def test_image_build_execution_prep_cli_writes_markdown_output(tmp_path):
    output_path = tmp_path / "prep.md"

    exit_code = prep.main(
        [
            "--ssh-target",
            "root@private-host",
            "--deploy-dir",
            "/opt/private-app",
            "--build-id",
            "build-20260703",
            "--release-label",
            "private-release-label",
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    text = output_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "ready_for_explicit_approval" in text
    assert "root@private-host" not in text
    assert "/opt/private-app" not in text
    assert "private-release-label" not in text
