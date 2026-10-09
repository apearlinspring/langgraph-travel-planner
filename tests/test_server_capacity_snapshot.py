import subprocess
from pathlib import Path

from scripts import collect_server_capacity_snapshot as snapshot


def _runner(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def _base_stdout():
    return "\n".join(
        [
            "cpu_count\t4",
            "loadavg\t0.40|0.50|0.60",
            "uptime_seconds\t86400",
            "meminfo\tMemTotal|8388608",
            "meminfo\tMemAvailable|4194304",
            "meminfo\tSwapTotal|0",
            "meminfo\tSwapFree|0",
            "root_disk\t60416|30000|50|/",
            "deploy_dir_present\ttrue",
            "deploy_disk\t60416|30000|50|/opt",
            "docker_available\ttrue",
            "docker_version_present\ttrue",
            "container_state\tzhixing-backend|running|healthy|0",
            "container_state\tzhixing-postgres|running|healthy|0",
            "container_state\tzhixing-redis|running|healthy|0",
            "container_state\tzhixing-caddy|running|healthy|0",
            "docker_stat\tzhixing-backend|2.50%|512MiB / 8GiB|6.25%|1kB / 2kB|3kB / 4kB|8",
            "docker_stat\tzhixing-postgres|1.00%|256MiB / 8GiB|3.12%|1kB / 2kB|3kB / 4kB|6",
            "docker_stat\tzhixing-redis|0.20%|64MiB / 8GiB|0.78%|1kB / 2kB|3kB / 4kB|4",
            "docker_stat\tzhixing-caddy|0.10%|32MiB / 8GiB|0.39%|1kB / 2kB|3kB / 4kB|3",
        ]
    )


def test_server_capacity_snapshot_passes_and_redacts_target():
    report = snapshot.build_server_capacity_snapshot_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(_base_stdout()),
    )
    payload = str(report)

    assert report["status"] == "passed"
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert report["sections"]["host_capacity"]["cpu_count"] == 4
    assert report["sections"]["host_capacity"]["memory"]["available_mb"] == 4096
    assert report["sections"]["container_capacity"]["status"] == "passed"
    assert report["sections"]["container_capacity"]["stats"][0]["service"] == "backend"


def test_server_capacity_snapshot_degrades_high_disk_and_restart_count():
    stdout = _base_stdout().replace("root_disk\t60416|30000|50|/", "root_disk\t60416|2048|97|/")
    stdout = stdout.replace("container_state\tzhixing-backend|running|healthy|0", "container_state\tzhixing-backend|running|healthy|2")

    report = snapshot.build_server_capacity_snapshot_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "degraded"
    assert report["sections"]["host_capacity"]["disk"]["root"]["used_percent"] == 97
    assert any(item["key"] == "root_disk" for item in report["degraded_reasons"])
    assert any(item["key"] == "backend_restart_count" for item in report["degraded_reasons"])


def test_server_capacity_snapshot_blocks_docker_unavailable():
    stdout = "\n".join(
        [
            "cpu_count\t2",
            "loadavg\t0.10|0.10|0.10",
            "meminfo\tMemTotal|2097152",
            "meminfo\tMemAvailable|1048576",
            "root_disk\t60416|30000|50|/",
            "deploy_dir_present\ttrue",
            "deploy_disk\t60416|30000|50|/opt",
            "docker_available\tfalse",
        ]
    )

    report = snapshot.build_server_capacity_snapshot_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "docker_unavailable" for item in report["blocked_reasons"])


def test_server_capacity_snapshot_blocks_missing_target_before_ssh():
    report = snapshot.build_server_capacity_snapshot_report(
        ssh_target="",
        deploy_dir="",
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "missing_target"


def test_server_capacity_snapshot_cli_writes_utf8_output(tmp_path: Path):
    output_path = tmp_path / "capacity-snapshot.json"

    code = snapshot.main(
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
