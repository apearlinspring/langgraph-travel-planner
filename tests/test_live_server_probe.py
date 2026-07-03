import subprocess

from scripts import collect_live_server_probe as probe


def _runner(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def test_live_server_probe_parses_redacted_success():
    compose_backend = '{"Service":"backend","State":"running","Status":"Up (healthy)","Health":"healthy","Ports":"127.0.0.1:8000->8000/tcp"}'
    compose_postgres = '{"Service":"postgres","State":"running","Status":"Up (healthy)","Health":"healthy"}'
    compose_redis = '{"Service":"redis","State":"running","Status":"Up (healthy)","Health":"healthy"}'
    compose_caddy = '{"Service":"caddy","State":"running","Status":"Up","Health":""}'
    stdout = "\n".join(
        [
            "hostname\tprod-host",
            "os_pretty\tCentOS Linux 7 (Core)",
            "kernel\tLinux 3.10 x86_64",
            "cpu_count\t2",
            "memory_summary\t3.6G total, 2.4G available",
            "root_disk_summary\t59G size, 51% used",
            "docker_version\tDocker version 26.1.4",
            "docker_compose_version\tDocker Compose version v2.27.1",
            "deploy_dir_present\ttrue",
            "layout_mode\tlegacy_flat",
            "current_path_type\tabsent",
            "git_metadata\tabsent",
            "env_file_present\ttrue",
            "root_env_file_present\ttrue",
            "shared_env_file_present\tfalse",
            "vectorstore_present\ttrue",
            "vectorstore_sqlite_present\ttrue",
            "internal_vectorstore_present\ttrue",
            "internal_vectorstore_sqlite_present\ttrue",
            "legacy_vectorstore_present\ttrue",
            "legacy_vectorstore_sqlite_present\ttrue",
            "legacy_internal_vectorstore_present\ttrue",
            "legacy_internal_vectorstore_sqlite_present\ttrue",
            "shared_vectorstore_present\tfalse",
            "shared_vectorstore_sqlite_present\tfalse",
            "shared_internal_vectorstore_present\tfalse",
            "shared_internal_vectorstore_sqlite_present\tfalse",
            "backup_count\t5",
            f"compose_json\t{compose_backend}",
            f"compose_json\t{compose_postgres}",
            f"compose_json\t{compose_redis}",
            f"compose_json\t{compose_caddy}",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production","missing_required":[],"blocking_items":[]}',
            'server_side_public_health_live\t{"status":"alive"}',
            'server_side_public_health_ready\t{"status":"ready","environment":"production","missing_required":[],"blocking_items":[]}',
            'mock_checkout_status\t{"status":"demo_only","real_payment":false}',
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="release@example.invalid",
        deploy_dir="/opt/langgraph-travel-planner",
        public_base_url="https://travel.example.test",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "passed"
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["target"]["public_base_url"] == "<public-url>"
    assert report["sections"]["host"]["os_pretty"] == "CentOS Linux 7 (Core)"
    assert report["sections"]["release_layout"]["layout_mode"] == "legacy_flat"
    assert report["sections"]["release_layout"]["root_env_file_present"] is True
    assert report["sections"]["release_layout"]["shared_env_file_present"] is False
    assert report["sections"]["release_layout"]["vectorstore_sqlite_present"] is True
    assert report["sections"]["compose_services"]["status"] == "passed"
    assert report["sections"]["internal_health"]["status"] == "passed"


def test_live_server_probe_reports_mock_checkout_not_deployed():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "compose_json\t{\"Service\":\"backend\",\"State\":\"running\",\"Health\":\"healthy\"}",
            "compose_json\t{\"Service\":\"postgres\",\"State\":\"running\",\"Health\":\"healthy\"}",
            "compose_json\t{\"Service\":\"redis\",\"State\":\"running\",\"Health\":\"healthy\"}",
            "compose_json\t{\"Service\":\"caddy\",\"State\":\"running\",\"Health\":\"\"}",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production"}',
            "mock_checkout_error\t22",
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["mock_checkout_live_route"]["status"] == "blocked"
    assert "not deployed" in report["sections"]["mock_checkout_live_route"]["finding"]


def test_live_server_probe_degrades_high_disk_usage():
    stdout = "\n".join(
        [
            "hostname\tprod-host",
            "root_disk_summary\t59G size, 97% used",
            "opt_disk_summary\t59G size, 97% used",
            "deploy_dir_present\ttrue",
            "layout_mode\tlegacy_flat",
            "current_path_type\tabsent",
            "env_file_present\ttrue",
            "vectorstore_present\ttrue",
            "vectorstore_sqlite_present\ttrue",
            "internal_vectorstore_present\ttrue",
            "internal_vectorstore_sqlite_present\ttrue",
            "compose_service\tbackend|running|healthy|running|8000/tcp",
            "compose_service\tpostgres|running|healthy|running|5432/tcp",
            "compose_service\tredis|running|healthy|running|6379/tcp",
            "compose_service\tcaddy|running|healthy|running|80/tcp 443/tcp",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production"}',
            'mock_checkout_status\t{"status":"demo_only","real_payment":false}',
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "degraded"
    assert report["sections"]["host"]["status"] == "degraded"
    assert report["sections"]["host"]["disk_checks"]["root"]["used_percent"] == 97
    assert any(item["key"] == "host.root_disk_usage" for item in report["degraded_reasons"])


def test_live_server_probe_blocks_fail_threshold_disk_usage():
    stdout = "\n".join(
        [
            "hostname\tprod-host",
            "root_disk_summary\t59G size, 98% used",
            "deploy_dir_present\ttrue",
            "layout_mode\tlegacy_flat",
            "current_path_type\tabsent",
            "env_file_present\ttrue",
            "vectorstore_present\ttrue",
            "vectorstore_sqlite_present\ttrue",
            "internal_vectorstore_present\ttrue",
            "internal_vectorstore_sqlite_present\ttrue",
            "compose_service\tbackend|running|healthy|running|8000/tcp",
            "compose_service\tpostgres|running|healthy|running|5432/tcp",
            "compose_service\tredis|running|healthy|running|6379/tcp",
            "compose_service\tcaddy|running|healthy|running|80/tcp 443/tcp",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production"}',
            'mock_checkout_status\t{"status":"demo_only","real_payment":false}',
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["host"]["status"] == "blocked"
    assert any(item["key"] == "host.root_disk_usage" for item in report["blocked_reasons"])


def test_live_server_probe_blocks_ssh_failure_without_echoing_target():
    report = probe.build_live_server_probe_report(
        ssh_target="root@secret-host",
        deploy_dir="/secret/path",
        command_runner=_runner("", returncode=255, stderr="Permission denied"),
    )

    assert report["status"] == "blocked"
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["blocked_reasons"][0]["key"] == "ssh_probe_failed"


def test_live_server_probe_blocks_current_path_that_is_not_symlink():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\tblocked_current_not_symlink",
            "current_path_type\tnon_symlink",
            "compose_json\t{\"Service\":\"backend\",\"State\":\"running\",\"Health\":\"healthy\"}",
            "compose_json\t{\"Service\":\"postgres\",\"State\":\"running\",\"Health\":\"healthy\"}",
            "compose_json\t{\"Service\":\"redis\",\"State\":\"running\",\"Health\":\"healthy\"}",
            "compose_json\t{\"Service\":\"caddy\",\"State\":\"running\",\"Health\":\"\"}",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production"}',
            'mock_checkout_status\t{"status":"demo_only","real_payment":false}',
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["release_layout"]["status"] == "blocked"
    assert any(item["key"] == "release_layout" for item in report["blocked_reasons"])


def test_live_server_probe_blocks_release_symlink_without_shared_rag_chroma():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\trelease_symlink",
            "current_path_type\tsymlink",
            "env_file_present\ttrue",
            "shared_env_file_present\ttrue",
            "vectorstore_present\ttrue",
            "vectorstore_sqlite_present\ttrue",
            "internal_vectorstore_present\ttrue",
            "internal_vectorstore_sqlite_present\ttrue",
            "legacy_vectorstore_sqlite_present\ttrue",
            "legacy_internal_vectorstore_sqlite_present\ttrue",
            "shared_vectorstore_present\ttrue",
            "shared_vectorstore_sqlite_present\tfalse",
            "shared_internal_vectorstore_present\ttrue",
            "shared_internal_vectorstore_sqlite_present\tfalse",
            "compose_service\tbackend|running|healthy|running|8000/tcp",
            "compose_service\tpostgres|running|healthy|running|5432/tcp",
            "compose_service\tredis|running|healthy|running|6379/tcp",
            "compose_service\tcaddy|running|healthy|running|80/tcp 443/tcp",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production"}',
            'mock_checkout_status\t{"status":"demo_only","real_payment":false}',
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    layout = report["sections"]["release_layout"]
    assert layout["status"] == "blocked"
    assert layout["shared_vectorstore_sqlite_present"] is False
    assert layout["shared_internal_vectorstore_sqlite_present"] is False
    assert any(item["key"] == "shared_rag_chroma_missing" for item in layout["blocked_reasons"])


def test_live_server_probe_degrades_release_symlink_without_shared_env():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "layout_mode\trelease_symlink",
            "current_path_type\tsymlink",
            "env_file_present\ttrue",
            "root_env_file_present\ttrue",
            "shared_env_file_present\tfalse",
            "vectorstore_present\ttrue",
            "vectorstore_sqlite_present\ttrue",
            "internal_vectorstore_present\ttrue",
            "internal_vectorstore_sqlite_present\ttrue",
            "shared_vectorstore_present\ttrue",
            "shared_vectorstore_sqlite_present\ttrue",
            "shared_internal_vectorstore_present\ttrue",
            "shared_internal_vectorstore_sqlite_present\ttrue",
            "compose_service\tbackend|running|healthy|running|8000/tcp",
            "compose_service\tpostgres|running|healthy|running|5432/tcp",
            "compose_service\tredis|running|healthy|running|6379/tcp",
            "compose_service\tcaddy|running|healthy|running|80/tcp 443/tcp",
            'internal_health_live\t{"status":"alive"}',
            'internal_health_ready\t{"status":"ready","environment":"production"}',
            'mock_checkout_status\t{"status":"demo_only","real_payment":false}',
        ]
    )

    report = probe.build_live_server_probe_report(
        ssh_target="root@server",
        deploy_dir="/srv/app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "degraded"
    layout = report["sections"]["release_layout"]
    assert layout["status"] == "degraded"
    assert layout["shared_env_file_present"] is False
    assert any(item["key"] == "shared_env_missing" for item in layout["degraded_reasons"])
