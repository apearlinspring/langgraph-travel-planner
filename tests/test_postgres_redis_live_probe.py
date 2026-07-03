import subprocess
from pathlib import Path

from scripts import collect_postgres_redis_live_probe as live_probe


def _runner(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def _container_row(service: str, *, ports: str = "{}", mounts: str = "") -> str:
    return "\t".join(
        [
            "container",
            f"{service}|present|running|healthy|unless-stopped|{ports}|{mounts}",
        ]
    )


def test_postgres_redis_live_probe_passes_redacted_single_server_state():
    stdout = "\n".join(
        [
            "docker_version\tDocker version 26.1.4",
            "compose_version\tDocker Compose version v2.27.1",
            "deploy_dir_present\ttrue",
            _container_row(
                "postgres",
                ports='{"5432/tcp":null}',
                mounts="volume|pgdata|/var/lib/postgresql/data|true;",
            ),
            _container_row(
                "redis",
                ports='{"6379/tcp":null}',
                mounts="volume|redisdata|/data|true;",
            ),
            "postgres_pg_isready\tpassed",
            "redis_ping\tpassed",
            "redis_appendonly_declared\tpassed",
        ]
    )

    report = live_probe.build_postgres_redis_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "passed"
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["sections"]["postgres_pg_isready"]["status"] == "passed"
    assert report["sections"]["redis_ping"]["status"] == "passed"
    assert report["declaration_statuses"] == {
        "ZHIXING_POSTGRES_LIVE_STATUS": "passed",
        "ZHIXING_REDIS_LIVE_STATUS": "passed",
        "ZHIXING_POSTGRES_REDIS_LIVE_STATUS": "passed",
    }


def test_non_loopback_database_port_is_degraded_not_blocked():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            _container_row(
                "postgres",
                ports='{"5432/tcp":[{"HostIp":"0.0.0.0","HostPort":"5432"}]}',
                mounts="volume|pgdata|/var/lib/postgresql/data|true;",
            ),
            _container_row(
                "redis",
                ports='{"6379/tcp":null}',
                mounts="volume|redisdata|/data|true;",
            ),
            "postgres_pg_isready\tpassed",
            "redis_ping\tpassed",
            "redis_appendonly_declared\tpassed",
        ]
    )

    report = live_probe.build_postgres_redis_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "degraded"
    assert report["sections"]["postgres_container"]["status"] == "degraded"
    assert any(item["key"] == "postgres_container.public_port_binding" for item in report["degraded_reasons"])


def test_missing_persistent_mount_blocks_probe():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            _container_row("postgres", mounts=""),
            _container_row("redis", mounts="volume|redisdata|/data|true;"),
            "postgres_pg_isready\tpassed",
            "redis_ping\tpassed",
            "redis_appendonly_declared\tpassed",
        ]
    )

    report = live_probe.build_postgres_redis_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["postgres_container"]["status"] == "blocked"
    assert any(item["key"] == "postgres_container.missing_persistent_mount" for item in report["blocked_reasons"])


def test_redis_ping_failure_blocks_redis_status():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            _container_row("postgres", mounts="volume|pgdata|/var/lib/postgresql/data|true;"),
            _container_row("redis", mounts="volume|redisdata|/data|true;"),
            "postgres_pg_isready\tpassed",
            "redis_ping\tblocked",
            "redis_appendonly_declared\tpassed",
        ]
    )

    report = live_probe.build_postgres_redis_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["redis_ping"]["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_REDIS_LIVE_STATUS"] == "blocked"


def test_ssh_failure_does_not_echo_target():
    report = live_probe.build_postgres_redis_live_probe_report(
        ssh_target="root@secret-host",
        deploy_dir="/secret/path",
        command_runner=_runner("", returncode=255, stderr="Permission denied"),
    )

    assert report["status"] == "blocked"
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["blocked_reasons"][0]["key"] == "ssh_probe_failed"


def test_live_probe_cli_writes_utf8_json_output(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "postgres-redis-live-probe.json"

    def fake_build(**kwargs):
        return {
            "version": live_probe.POSTGRES_REDIS_LIVE_PROBE_VERSION,
            "status": "passed",
            "sections": {},
            "blocked_reasons": [],
            "degraded_reasons": [],
        }

    monkeypatch.setattr(live_probe, "build_postgres_redis_live_probe_report", fake_build)

    code = live_probe.main(
        [
            "--ssh-target",
            "root@private-host",
            "--deploy-dir",
            "/private/app",
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert '"status": "passed"' in payload
