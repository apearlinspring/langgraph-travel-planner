import json
import subprocess

from scripts import collect_backup_schedule_live_probe as backup_probe


def _runner(stdout: str, returncode: int = 0, stderr: str = ""):
    def run(args, *, input_text, timeout_seconds):
        return subprocess.CompletedProcess(
            list(args),
            returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _passing_stdout(schedule: str = "1|0|0|active") -> str:
    return "\n".join(
        [
            "deploy_dir_present\ttrue",
            "backup_dir_supplied\ttrue",
            "backup_dir_present\ttrue",
            "postgres_backup_scan\t2|2|false|.dump|2048|3600|172800|1024",
            "rag_restore_scan\t1|1|false|1800|true|true|4096|4096|172800",
            "release_backup_scan\t3|7200",
            f"schedule_scan\t{schedule}",
        ]
    )


def test_backup_schedule_live_probe_passes_with_fresh_backup_and_schedule():
    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        backup_dir="/private/backups",
        command_runner=_runner(_passing_stdout()),
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["target"]["ssh_target"] == "<server-target>"
    assert report["target"]["deploy_dir"] == "<deploy-dir>"
    assert report["target"]["backup_dir"] == "<backup-dir>"
    assert report["sections"]["postgres_backup_freshness"]["status"] == "passed"
    assert report["sections"]["backup_schedule"]["status"] == "passed"
    assert report["declaration_statuses"]["ZHIXING_BACKUP_LIVE_STATUS"] == "passed"
    assert "root@private-host" not in payload
    assert "/opt/private-app" not in payload
    assert "/private/backups" not in payload


def test_missing_schedule_degrades_not_blocks_when_backup_is_fresh():
    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        backup_dir="/private/backups",
        command_runner=_runner(_passing_stdout(schedule="0|0|0|active")),
    )

    assert report["status"] == "degraded"
    assert report["sections"]["postgres_backup_freshness"]["status"] == "passed"
    assert report["sections"]["backup_schedule"]["status"] == "degraded"
    assert any(item["key"] == "backup_schedule.missing_schedule" for item in report["degraded_reasons"])


def test_stale_postgres_backup_blocks_even_if_schedule_exists():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "backup_dir_supplied\tfalse",
            "backup_dir_present\tnot_supplied",
            "postgres_backup_scan\t1|1|false|.dump|4096|259200|172800|1024",
            "rag_restore_scan\t1|1|false|1800|true|true|4096|4096|172800",
            "release_backup_scan\t1|7200",
            "schedule_scan\t1|0|0|active",
        ]
    )

    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["postgres_backup_freshness"]["status"] == "blocked"
    assert any(
        item["key"] == "postgres_backup_freshness.backup_stale"
        for item in report["blocked_reasons"]
    )


def test_missing_rag_restore_artifact_is_degraded_not_blocked():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "backup_dir_supplied\tfalse",
            "backup_dir_present\tnot_supplied",
            "postgres_backup_scan\t1|1|false|.dump|4096|3600|172800|1024",
            "rag_restore_scan\t0|0|false|-1|false|false|0|0|172800",
            "release_backup_scan\t1|7200",
            "schedule_scan\t1|0|0|active",
        ]
    )

    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "degraded"
    assert report["sections"]["rag_restore_artifact"]["status"] == "degraded"
    assert any(
        item["key"] == "rag_restore_artifact.missing_rag_restore_artifact"
        for item in report["degraded_reasons"]
    )


def test_rag_vectorstore_archive_counts_as_restore_path_artifact():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "backup_dir_supplied\tfalse",
            "backup_dir_present\tnot_supplied",
            "postgres_backup_scan\t1|1|false|.dump|4096|3600|172800|1024",
            "rag_restore_scan\t1|1|false|1800|not_checked|not_checked|0|0|172800|vectorstore_archive|8192",
            "release_backup_scan\t1|7200",
            "schedule_scan\t1|0|0|active",
        ]
    )

    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        command_runner=_runner(stdout),
    )

    assert report["status"] == "passed"
    latest = report["sections"]["rag_restore_artifact"]["latest"]
    assert latest["artifact_kind"] == "vectorstore_archive"
    assert latest["archive_size_bytes"] == 8192
    assert latest["has_public_vectorstore"] is None


def test_ssh_failure_does_not_echo_target_or_stderr():
    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@secret-host",
        deploy_dir="/secret/path",
        backup_dir="/secret/backup",
        command_runner=_runner("", returncode=255, stderr="ssh: Could not resolve hostname secret-host"),
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["sections"]["ssh"]["stderr_redacted"] is True
    assert "root@secret-host" not in payload
    assert "/secret/path" not in payload
    assert "/secret/backup" not in payload
    assert "secret-host" not in payload


def test_supplied_backup_dir_missing_blocks_without_echoing_path():
    stdout = "\n".join(
        [
            "deploy_dir_present\ttrue",
            "backup_dir_supplied\ttrue",
            "backup_dir_present\tfalse",
            "postgres_backup_scan\t0|0|false||0|-1|172800|1024",
            "rag_restore_scan\t0|0|false|-1|false|false|0|0|172800",
            "release_backup_scan\t1|7200",
            "schedule_scan\t1|0|0|active",
        ]
    )

    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        backup_dir="/private/backups",
        command_runner=_runner(stdout),
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["sections"]["ssh"]["status"] == "blocked"
    assert "/private/backups" not in payload


def test_cron_schedule_without_active_daemon_is_degraded():
    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        backup_dir="/private/backups",
        command_runner=_runner(_passing_stdout(schedule="1|0|0|unknown")),
    )

    assert report["status"] == "degraded"
    assert report["sections"]["backup_schedule"]["status"] == "degraded"
    assert report["sections"]["backup_schedule"]["cron_daemon"] == "unknown"
    assert any(
        item["key"] == "backup_schedule.cron_daemon_not_active"
        for item in report["degraded_reasons"]
    )


def test_main_writes_json_output_without_requiring_target(tmp_path):
    output_path = tmp_path / "backup-schedule.json"

    code = backup_probe.main(["--output", str(output_path)])

    assert code == 2
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["policy"]["ssh_target_echoed"] is False


def test_main_renders_markdown_from_existing_report_json(tmp_path):
    report = backup_probe.build_backup_schedule_live_probe_report(
        ssh_target="root@private-host",
        deploy_dir="/opt/private-app",
        backup_dir="/private/backups",
        command_runner=_runner(_passing_stdout()),
    )
    report_path = tmp_path / "backup-schedule.json"
    output_path = tmp_path / "backup-schedule.md"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    code = backup_probe.main([
        "--report-json",
        str(report_path),
        "--markdown",
        "--output",
        str(output_path),
    ])

    assert code == 0
    markdown = output_path.read_text(encoding="utf-8")
    assert "Backup Schedule Live Probe Evidence" in markdown
    assert "passed" in markdown
