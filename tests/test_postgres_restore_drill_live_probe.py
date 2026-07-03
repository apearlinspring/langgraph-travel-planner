import subprocess

from scripts import collect_postgres_restore_drill_live_probe as probe


def _parsed(**overrides):
    base = {
        "status": ["passed"],
        "phase": ["complete"],
        "backup_dir_supplied": ["false"],
        "backup_location_policy": ["postgres_dump_only_outside_deploy"],
        "candidate_count": ["1"],
        "scanned_count": ["3"],
        "latest_size_bytes": ["18328181"],
        "latest_age_seconds": ["3600"],
        "latest_extension": ["dump"],
        "catalog_status": ["passed"],
        "catalog_line_count": ["94"],
        "restore_status": ["passed"],
        "restored_table_count": ["13"],
        "temp_container_cleaned": ["true"],
    }
    base.update({key: [str(value)] for key, value in overrides.items()})
    return base


def test_restore_drill_report_passes_from_live_probe_lines():
    report = probe.build_postgres_restore_drill_live_probe_report_from_parsed(_parsed())

    assert report["version"] == "postgres_restore_drill_live_probe.v1"
    assert report["status"] == "passed"
    assert report["backup_artifact"]["candidate_count"] == 1
    assert report["catalog_check"] == {
        "status": "passed",
        "catalog_line_count": 94,
    }
    assert report["restore_check"] == {
        "status": "passed",
        "restored_table_count": 13,
        "temp_container_cleaned": True,
    }
    assert report["policy"]["reads_backup_file_contents"] is True
    assert report["policy"]["prints_backup_file_contents"] is False
    assert report["scope"]["production_database_modified"] is False


def test_restore_drill_report_blocks_when_catalog_fails():
    report = probe.build_postgres_restore_drill_live_probe_report_from_parsed(
        _parsed(
            status="blocked",
            phase="pg_restore_catalog",
            catalog_status="blocked",
            catalog_line_count="0",
            restore_status="not_checked",
            restored_table_count="0",
            temp_container_cleaned="false",
        )
    )

    assert report["status"] == "blocked"
    assert report["catalog_check"]["status"] == "blocked"
    assert report["restore_check"]["status"] == "not_checked"
    assert any(item["key"] == "pg_restore_catalog" for item in report["blocked_reasons"])


def test_restore_drill_cli_report_redacts_target_values(tmp_path):
    output_path = tmp_path / "restore.json"

    def fake_runner(args, *, input_text, timeout_seconds):
        assert "root@example.internal" in args
        assert "/srv/private/deploy" in args
        stdout = "\n".join(f"{key}\t{values[0]}" for key, values in _parsed().items())
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    report = probe.build_postgres_restore_drill_live_probe_report(
        ssh_target="root@example.internal",
        deploy_dir="/srv/private/deploy",
        backup_dir="/srv/private/backups",
        command_runner=fake_runner,
    )
    output_path.write_text(probe.build_postgres_restore_drill_live_probe_markdown(report), encoding="utf-8")
    text = output_path.read_text(encoding="utf-8")

    assert report["status"] == "passed"
    assert "root@example.internal" not in text
    assert "/srv/private/deploy" not in text
    assert "/srv/private/backups" not in text
    assert "<server-target>" in report["target"]["ssh_target"]
    assert "<deploy-dir>" in report["target"]["deploy_dir"]
