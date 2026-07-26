import json
import subprocess
from collections import namedtuple
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from scripts import check_server_preflight_readiness as readiness


def _valid_env() -> dict[str, str]:
    return {
        "ZHIXING_SERVER_PROVIDER": "cloud provider",
        "ZHIXING_SERVER_OS_VERSION": "Ubuntu 24.04",
        "ZHIXING_SERVER_CPU_RAM_DISK": "4 vCPU / 16 GB RAM / 160 GB SSD",
        "ZHIXING_DEPLOY_MODE": "Docker Compose",
        "ZHIXING_DEPLOY_DIR": "/opt/zhixing",
        "ZHIXING_PUBLIC_BASE_URL": "https://m1.zhixing.example.net",
        "ZHIXING_SITE_ADDRESS": "m1.zhixing.example.net",
        "ZHIXING_DOMAIN_READY": "ready",
        "ZHIXING_SERVER_EGRESS_IP_STATUS": "fixed",
        "ZHIXING_SERVER_PORTS_STATUS": "80 and 443 open",
        "ZHIXING_TLS_STATUS": "ready",
        "ZHIXING_REVERSE_PROXY_STATUS": "ready",
        "ZHIXING_DOCKER_STATUS": "ready",
    }


def test_server_preflight_blocks_missing_inputs_without_dotenv_or_probes():
    report = readiness.build_server_preflight_readiness_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["starts_services"] is False
    assert report["policy"]["writes_files"] is False
    assert report["docker_probe"]["status"] == "not_checked"
    assert report["health_probe"]["status"] == "not_checked"
    assert report["disk_probe"]["status"] == "not_checked"
    assert any(item["env_var"] == "ZHIXING_DEPLOY_DIR" for item in report["blocked_reasons"])


def test_server_preflight_passes_complete_declarations_without_echoing_values():
    env = _valid_env()

    report = readiness.build_server_preflight_readiness_report(environ=env)
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    for value in [
        "cloud provider",
        "Ubuntu 24.04",
        "/opt/zhixing",
        "https://m1.zhixing.example.net",
    ]:
        assert value not in payload
    assert all(item["value_echoed"] is False for item in report["checks"])


def test_server_preflight_blocks_local_url_default_site_and_relative_deploy_dir():
    env = _valid_env()
    env["ZHIXING_PUBLIC_BASE_URL"] = "http://127.0.0.1:8000"
    env["ZHIXING_SITE_ADDRESS"] = ":80"
    env["ZHIXING_DEPLOY_DIR"] = "deploy"

    report = readiness.build_server_preflight_readiness_report(environ=env)
    blocked_vars = {item["env_var"] for item in report["blocked_reasons"]}

    assert report["status"] == "blocked"
    assert "ZHIXING_PUBLIC_BASE_URL" in blocked_vars
    assert "ZHIXING_SITE_ADDRESS" in blocked_vars
    assert "ZHIXING_DEPLOY_DIR" in blocked_vars


def test_server_preflight_docker_probe_passes_when_commands_available(monkeypatch):
    calls = []

    def fake_run(args, *, timeout_seconds=10):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(readiness, "_run_command", fake_run)

    report = readiness.build_server_preflight_readiness_report(
        environ=_valid_env(),
        check_docker=True,
    )

    assert report["status"] == "passed"
    assert report["docker_probe"]["status"] == "passed"
    assert calls == [["docker", "--version"], ["docker", "compose", "version"]]


def test_server_preflight_deploy_dir_probe_checks_existing_dir(tmp_path):
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = str(tmp_path)

    report = readiness.build_server_preflight_readiness_report(
        environ=env,
        check_deploy_dir=True,
    )

    assert report["status"] == "passed"
    assert report["deploy_dir_probe"]["status"] == "passed"
    assert report["deploy_dir_probe"]["writes_files"] is False


def test_server_preflight_disk_probe_checks_capacity_without_echoing_path(tmp_path):
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = str(tmp_path)

    report = readiness.build_server_preflight_readiness_report(
        environ=env,
        check_disk=True,
        min_free_disk_mb=1,
        disk_warn_used_percent=101,
        disk_fail_used_percent=102,
    )
    payload = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "passed"
    assert report["disk_probe"]["status"] == "passed"
    assert report["disk_probe"]["writes_files"] is False
    assert report["disk_probe"]["value_echoed"] is False
    assert str(tmp_path) not in payload


def test_server_preflight_disk_probe_blocks_missing_target():
    report = readiness.build_server_preflight_readiness_report(
        environ={},
        check_disk=True,
    )

    assert report["status"] == "blocked"
    assert report["disk_probe"]["status"] == "blocked"
    assert report["disk_probe"]["finding"] == "Disk probe target is missing."


def test_server_preflight_disk_probe_warns_without_blocking(monkeypatch, tmp_path):
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = str(tmp_path)
    DiskUsage = namedtuple("usage", "total used free")

    monkeypatch.setattr(
        readiness.shutil,
        "disk_usage",
        lambda path: DiskUsage(total=100 * 1024 * 1024, used=91 * 1024 * 1024, free=9 * 1024 * 1024),
    )

    report = readiness.build_server_preflight_readiness_report(
        environ=env,
        check_disk=True,
        min_free_disk_mb=1,
        disk_warn_used_percent=90,
        disk_fail_used_percent=98,
    )

    assert report["status"] == "passed"
    assert report["disk_probe"]["status"] == "warning"
    assert report["warnings"][0]["key"] == "disk_probe"
    assert report["blocked_reasons"] == []


def test_server_preflight_disk_probe_blocks_low_free_space(monkeypatch, tmp_path):
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = str(tmp_path)
    DiskUsage = namedtuple("usage", "total used free")

    monkeypatch.setattr(
        readiness.shutil,
        "disk_usage",
        lambda path: DiskUsage(total=100 * 1024 * 1024, used=95 * 1024 * 1024, free=5 * 1024 * 1024),
    )

    report = readiness.build_server_preflight_readiness_report(
        environ=env,
        check_disk=True,
        min_free_disk_mb=10,
        disk_warn_used_percent=90,
        disk_fail_used_percent=98,
    )

    assert report["status"] == "blocked"
    assert report["disk_probe"]["status"] == "blocked"
    assert any(item["key"] == "disk_probe" for item in report["blocked_reasons"])


def test_server_preflight_health_probe_passes_when_public_endpoints_respond(monkeypatch):
    calls = []

    def fake_probe(url, *, timeout_seconds):
        calls.append((url, timeout_seconds))
        return 200

    monkeypatch.setattr(readiness, "_probe_url", fake_probe)

    report = readiness.build_server_preflight_readiness_report(
        environ=_valid_env(),
        check_health_url=True,
        timeout_seconds=1.5,
    )

    assert report["status"] == "passed"
    assert report["health_probe"]["status"] == "passed"
    assert calls == [
        ("https://m1.zhixing.example.net/health/live", 1.5),
        ("https://m1.zhixing.example.net/health/ready", 1.5),
    ]


def test_server_preflight_deploy_dir_inside_workspace_is_blocked():
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = str(Path.cwd())

    report = readiness.build_server_preflight_readiness_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_DEPLOY_DIR" for item in report["blocked_reasons"])


@pytest.mark.parametrize(
    ("project_root", "deploy_dir"),
    [
        (PurePosixPath("/srv/zhixing"), "/srv/zhixing/releases/2026-07-26"),
        (
            PureWindowsPath(r"C:\workspace\zhixing"),
            r"c:\WORKSPACE\ZHIXING\releases\2026-07-26",
        ),
    ],
)
def test_server_preflight_blocks_workspace_paths_for_unix_and_windows(
    monkeypatch,
    project_root,
    deploy_dir,
):
    monkeypatch.setattr(readiness, "PROJECT_ROOT", project_root)
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = deploy_dir

    report = readiness.build_server_preflight_readiness_report(environ=env)

    deploy_dir_check = next(
        item for item in report["checks"] if item["env_var"] == "ZHIXING_DEPLOY_DIR"
    )
    assert deploy_dir_check["status"] == "blocked"
    assert deploy_dir_check["finding"] == "Deployment directory must not point inside the Git workspace."


@pytest.mark.parametrize(
    ("project_root", "deploy_dir"),
    [
        (PurePosixPath("/srv/zhixing"), "/srv/zhixing-copy"),
        (PureWindowsPath(r"C:\workspace\zhixing"), r"C:\workspace\zhixing-copy"),
    ],
)
def test_server_preflight_allows_absolute_sibling_paths_for_unix_and_windows(
    monkeypatch,
    project_root,
    deploy_dir,
):
    monkeypatch.setattr(readiness, "PROJECT_ROOT", project_root)
    env = _valid_env()
    env["ZHIXING_DEPLOY_DIR"] = deploy_dir

    report = readiness.build_server_preflight_readiness_report(environ=env)

    assert report["status"] == "passed"
