import json
import subprocess

from scripts import check_m1_first_deploy_dry_run as dry_run


TARGET_ENV = {
    "ZHIXING_DEPLOY_USER": "deploy-user",
    "ZHIXING_DEPLOY_HOST": "prod.example.net",
    "ZHIXING_DEPLOY_DIR": "/opt/zhixing",
    "ZHIXING_PUBLIC_BASE_URL": "https://m1.zhixing.example.net",
}


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _clean_command_runner(args, *, timeout_seconds=20):
    command = list(args)
    if command[:3] == ["git", "status", "--short"]:
        return subprocess.CompletedProcess(command, 0, stdout="## main...origin/main\n", stderr="")
    return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")


def _dirty_command_runner(args, *, timeout_seconds=20):
    command = list(args)
    if command[:3] == ["git", "status", "--short"]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="## main...origin/main\n M app/main.py\n?? local.txt\n",
            stderr="",
        )
    return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")


def _windows_scp_command_runner(args, *, timeout_seconds=20):
    command = list(args)
    if command == ["scp", "-V"]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unknown option -- V\n")
    if command[:3] == ["git", "status", "--short"]:
        return subprocess.CompletedProcess(command, 0, stdout="## main...origin/main\n", stderr="")
    return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")


def test_first_deploy_dry_run_blocks_missing_target_inputs():
    report = dry_run.build_m1_first_deploy_dry_run_report(
        environ={},
        check_local_tools=False,
        check_git_worktree=False,
        check_compose_config=False,
        check_public_boundary=False,
    )

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["connects_ssh"] is False
    assert report["policy"]["uploads_files"] is False
    assert report["section_statuses"]["target_inputs"] == "blocked"
    assert {item["env_var"] for item in report["sections"]["target_inputs"]["checks"]} == {
        "ZHIXING_DEPLOY_USER",
        "ZHIXING_DEPLOY_HOST",
        "ZHIXING_DEPLOY_DIR",
        "ZHIXING_PUBLIC_BASE_URL",
    }


def test_first_deploy_dry_run_passes_clean_plan_without_echoing_target(monkeypatch):
    monkeypatch.setattr(
        dry_run,
        "build_public_release_boundary_report",
        lambda: {"status": "passed", "candidate_count": 1, "content_findings": []},
    )

    report = dry_run.build_m1_first_deploy_dry_run_report(
        environ=TARGET_ENV,
        command_runner=_clean_command_runner,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["section_statuses"] == {
        "target_inputs": "passed",
        "local_tools": "passed",
        "git_worktree": "passed",
        "compose_config": "passed",
        "public_release_boundary": "passed",
    }
    assert "deploy-user" not in payload
    assert "prod.example.net" not in payload
    assert "/opt/zhixing" not in payload
    assert "https://m1.zhixing.example.net" not in payload
    assert "<ssh-user>@<server-host>" in payload
    assert "<deploy-dir>" in payload


def test_first_deploy_dry_run_blocks_dirty_worktree(monkeypatch):
    monkeypatch.setattr(
        dry_run,
        "build_public_release_boundary_report",
        lambda: {"status": "passed", "candidate_count": 1, "content_findings": []},
    )

    report = dry_run.build_m1_first_deploy_dry_run_report(
        environ=TARGET_ENV,
        command_runner=_dirty_command_runner,
    )

    assert report["status"] == "blocked"
    assert report["sections"]["git_worktree"]["dirty_count"] == 2
    assert any(item["section"] == "git_worktree" for item in report["blockers"])


def test_first_deploy_dry_run_accepts_windows_scp_version_behavior(monkeypatch):
    monkeypatch.setattr(
        dry_run,
        "build_public_release_boundary_report",
        lambda: {"status": "passed", "candidate_count": 1, "content_findings": []},
    )

    report = dry_run.build_m1_first_deploy_dry_run_report(
        environ=TARGET_ENV,
        command_runner=_windows_scp_command_runner,
    )

    assert report["status"] == "passed"
    scp_check = next(item for item in report["sections"]["local_tools"]["checks"] if item["key"] == "scp")
    assert scp_check["status"] == "passed"
    assert "unknown option" in scp_check["finding"]


def test_first_deploy_dry_run_blocks_localhost_and_relative_dir():
    env = {
        **TARGET_ENV,
        "ZHIXING_DEPLOY_DIR": "deploy",
        "ZHIXING_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
    }

    report = dry_run.build_m1_first_deploy_dry_run_report(
        environ=env,
        check_local_tools=False,
        check_git_worktree=False,
        check_compose_config=False,
        check_public_boundary=False,
    )
    blocked = {item["env_var"] for item in report["blockers"] if "env_var" in item}

    assert report["status"] == "blocked"
    assert "ZHIXING_DEPLOY_DIR" in blocked
    assert "ZHIXING_PUBLIC_BASE_URL" in blocked


def test_first_deploy_dry_run_markdown_contains_boundaries(monkeypatch):
    monkeypatch.setattr(
        dry_run,
        "build_public_release_boundary_report",
        lambda: {"status": "passed", "candidate_count": 1, "content_findings": []},
    )
    report = dry_run.build_m1_first_deploy_dry_run_report(
        environ=TARGET_ENV,
        command_runner=_clean_command_runner,
    )

    markdown = dry_run.build_m1_first_deploy_dry_run_markdown(report)

    assert "M1 First Deploy Dry Run" in markdown
    assert "Connects SSH" in markdown
    assert "<ssh-user>@<server-host>" in markdown
    assert "SSH authentication works" in markdown
    assert "prod.example.net" not in markdown
    assert "build_release_artifact.py" in markdown
    assert "deploy/first-deploy.sh" in markdown
    assert "--archive-sha256" in markdown
    assert "--execute --start-services" in markdown


def test_first_deploy_dry_run_main_returns_blocked_code(monkeypatch):
    monkeypatch.setattr(
        dry_run,
        "build_m1_first_deploy_dry_run_report",
        lambda **kwargs: {
            "version": "m1_first_deploy_dry_run.v1",
            "status": "blocked",
            "policy": {"reads_dotenv": False, "connects_ssh": False, "uploads_files": False},
            "section_statuses": {},
            "blockers": [],
            "command_plan": [],
            "not_proven_by_this_dry_run": [],
        },
    )

    assert dry_run.main(["--json"]) == 2
