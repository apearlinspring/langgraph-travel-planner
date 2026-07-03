import json
from pathlib import Path

from scripts import check_restore_drill_feasibility as feasibility


def _backup_report(*, status="passed", postgres_status="passed", extension=".dump", size_bytes=20_000_000):
    return {
        "version": "backup_schedule_live_probe.v1",
        "status": status,
        "sections": {
            "postgres_backup_freshness": {
                "status": postgres_status,
                "latest": {
                    "extension": extension,
                    "size_bytes": size_bytes,
                    "age_seconds": 3600,
                    "path_echoed": False,
                    "filename_echoed": False,
                },
            },
            "backup_schedule": {"status": "passed"},
        },
    }


def _capacity_report(*, status="passed", free_mb=8192, used_percent=50, container_status="passed"):
    return {
        "version": "server_capacity_snapshot.v1",
        "status": status,
        "sections": {
            "host_capacity": {
                "status": status,
                "disk": {
                    "root": {
                        "status": "passed" if used_percent < 90 else "degraded",
                        "free_mb": free_mb,
                        "used_percent": used_percent,
                    },
                    "deploy": {
                        "status": "passed" if used_percent < 90 else "degraded",
                        "free_mb": free_mb,
                        "used_percent": used_percent,
                    },
                },
            },
            "container_capacity": {
                "status": container_status,
            },
        },
    }


def _payload(report):
    return json.dumps(report, ensure_ascii=False)


def test_restore_drill_feasibility_passes_with_fresh_dump_and_space():
    report = feasibility.build_restore_drill_feasibility_report(
        backup_schedule_report=_backup_report(),
        capacity_report=_capacity_report(),
    )

    assert report["status"] == "passed"
    assert report["sections"]["postgres_backup"]["status"] == "passed"
    assert report["sections"]["restore_workspace_space"]["status"] == "passed"
    assert report["declaration_statuses"]["ZHIXING_RESTORE_DRILL_FEASIBILITY_STATUS"] == "passed"


def test_restore_drill_feasibility_blocks_when_disk_space_is_low():
    report = feasibility.build_restore_drill_feasibility_report(
        backup_schedule_report=_backup_report(size_bytes=18_000_000),
        capacity_report=_capacity_report(status="degraded", free_mb=2266, used_percent=97),
    )

    assert report["status"] == "blocked"
    assert report["sections"]["restore_workspace_space"]["required_free_mb"] == 4096
    assert any(
        item["key"] == "insufficient_restore_drill_space"
        for item in report["blocked_reasons"]
    )


def test_restore_drill_feasibility_degrades_sql_dump_for_psql_plan():
    report = feasibility.build_restore_drill_feasibility_report(
        backup_schedule_report=_backup_report(extension=".sql.gz"),
        capacity_report=_capacity_report(),
    )

    assert report["status"] == "degraded"
    assert any(
        item["key"] == "sql_restore_plan_required"
        for item in report["degraded_reasons"]
    )


def test_restore_drill_feasibility_blocks_missing_reports():
    report = feasibility.build_restore_drill_feasibility_report(
        backup_schedule_report=None,
        capacity_report=None,
    )

    assert report["status"] == "blocked"
    assert any(item["section"] == "postgres_backup" for item in report["blocked_reasons"])
    assert any(item["section"] == "disk_capacity" for item in report["blocked_reasons"])


def test_restore_drill_feasibility_markdown_is_redacted():
    report = feasibility.build_restore_drill_feasibility_report(
        backup_schedule_report=_backup_report(),
        capacity_report=_capacity_report(),
    )

    markdown = feasibility.build_restore_drill_feasibility_markdown(report)

    assert "Restore Drill Feasibility Evidence" in markdown
    assert "backup path" in markdown
    assert "server target" in markdown


def test_restore_drill_feasibility_cli_writes_output(tmp_path: Path):
    backup_path = tmp_path / "backup.json"
    capacity_path = tmp_path / "capacity.json"
    output_path = tmp_path / "restore-feasibility.json"
    backup_path.write_text(json.dumps(_backup_report(), ensure_ascii=False), encoding="utf-8")
    capacity_path.write_text(json.dumps(_capacity_report(), ensure_ascii=False), encoding="utf-8")

    code = feasibility.main(
        [
            "--backup-schedule-json",
            str(backup_path),
            "--capacity-json",
            str(capacity_path),
            "--output",
            str(output_path),
        ]
    )

    assert code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["status"] == "passed"


def test_restore_drill_feasibility_cli_blocks_unreadable_input(tmp_path: Path):
    output_path = tmp_path / "restore-feasibility.md"

    code = feasibility.main(
        [
            "--backup-schedule-json",
            str(tmp_path / "missing-backup.json"),
            "--capacity-json",
            str(tmp_path / "missing-capacity.json"),
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    markdown = output_path.read_text(encoding="utf-8")
    assert "blocked" in markdown
