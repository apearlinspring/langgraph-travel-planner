import json
from pathlib import Path

from scripts import render_postgres_redis_backup_declaration_candidates as candidates


def _backup_schedule(status="passed"):
    return {
        "version": "backup_schedule_live_probe.v1",
        "status": status,
        "declaration_statuses": {
            "ZHIXING_BACKUP_FRESHNESS_LIVE_STATUS": "passed",
            "ZHIXING_BACKUP_SCHEDULE_LIVE_STATUS": "passed",
        },
        "sections": {
            "postgres_backup_freshness": {
                "status": "passed",
                "latest": {
                    "extension": ".dump",
                    "size_bytes": 18_328_181,
                    "age_seconds": 3600,
                    "path_echoed": False,
                    "filename_echoed": False,
                },
            },
            "backup_schedule": {"status": "passed"},
        },
    }


def _backup_restore(status="passed", pg_restore="passed", declaration="passed"):
    return {
        "version": "backup_restore_drill_evidence.v1",
        "status": status,
        "sections": {
            "backup_artifact_probe": {
                "status": pg_restore,
                "pg_restore_list": {"status": pg_restore},
            },
            "restore_drill_declaration": {
                "status": declaration,
            },
        },
    }


def _live_restore_probe(status="passed", catalog="passed", restore="passed"):
    return {
        "version": "postgres_restore_drill_live_probe.v1",
        "status": status,
        "catalog_check": {
            "status": catalog,
            "catalog_line_count": 94,
        },
        "restore_check": {
            "status": restore,
            "restored_table_count": 13,
            "temp_container_cleaned": True,
        },
        "scope": {
            "mode": "ephemeral_non_production_restore_container",
            "production_database_modified": False,
            "row_data_echoed": False,
        },
    }


def _feasibility(status="passed"):
    return {
        "version": "restore_drill_feasibility.v1",
        "status": status,
        "declaration_statuses": {
            "ZHIXING_RESTORE_DRILL_FEASIBILITY_STATUS": status,
        },
    }


def test_backup_and_restore_candidates_ready_when_evidence_passes():
    report = candidates.build_postgres_redis_backup_declaration_candidates(
        backup_schedule=_backup_schedule(),
        backup_restore=_backup_restore(),
        restore_feasibility=_feasibility(),
    )
    by_env = {item["env_var"]: item for item in report["candidates"]}

    assert report["status"] == "action_required"
    assert report["candidate_ready_count"] == 2
    assert by_env["ZHIXING_POSTGRES_BACKUP_STATUS"]["status"] == "candidate_ready"
    assert by_env["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["status"] == "candidate_ready"
    assert all(
        item["owner_confirmed"] is False
        for item in report["record_patch_skeleton"]["declarations"]
    )


def test_restore_candidate_accepts_live_non_production_restore_probe():
    report = candidates.build_postgres_redis_backup_declaration_candidates(
        backup_schedule=_backup_schedule(),
        backup_restore=_live_restore_probe(),
        restore_feasibility=_feasibility(),
    )
    by_env = {item["env_var"]: item for item in report["candidates"]}

    assert report["status"] == "action_required"
    assert by_env["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["status"] == "candidate_ready"
    assert by_env["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["source_statuses"] == {
        "pg_restore_catalog": "passed",
        "restore_declaration": "passed",
        "restore_feasibility": "passed",
    }
    assert by_env["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["evidence_ref"] == (
        "postgres-restore-drill-live-probe.json + restore-drill-feasibility.json"
    )


def test_restore_candidate_blocks_when_feasibility_or_catalog_is_blocked():
    report = candidates.build_postgres_redis_backup_declaration_candidates(
        backup_schedule=_backup_schedule(),
        backup_restore=_backup_restore(status="blocked", pg_restore="not_checked", declaration="blocked"),
        restore_feasibility=_feasibility(status="blocked"),
    )
    by_env = {item["env_var"]: item for item in report["candidates"]}

    assert report["status"] == "blocked"
    assert by_env["ZHIXING_POSTGRES_BACKUP_STATUS"]["status"] == "candidate_ready"
    assert by_env["ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"]["status"] == "blocked"
    assert report["candidate_ready_count"] == 1
    assert any(
        item["env_var"] == "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"
        for item in report["blocked_reasons"]
    )


def test_backup_candidate_blocks_when_freshness_is_not_passed():
    backup = _backup_schedule()
    backup["declaration_statuses"]["ZHIXING_BACKUP_FRESHNESS_LIVE_STATUS"] = "blocked"

    report = candidates.build_postgres_redis_backup_declaration_candidates(
        backup_schedule=backup,
        backup_restore=_backup_restore(),
        restore_feasibility=_feasibility(),
    )
    by_env = {item["env_var"]: item for item in report["candidates"]}

    assert report["status"] == "blocked"
    assert by_env["ZHIXING_POSTGRES_BACKUP_STATUS"]["status"] == "blocked"


def test_candidates_markdown_contains_boundary_and_skeleton():
    report = candidates.build_postgres_redis_backup_declaration_candidates(
        backup_schedule=_backup_schedule(),
        backup_restore=_backup_restore(status="blocked", pg_restore="not_checked", declaration="blocked"),
        restore_feasibility=_feasibility(status="blocked"),
    )

    markdown = candidates.build_postgres_redis_backup_declaration_candidates_markdown(report)

    assert "PostgreSQL Backup / Restore Declaration Candidates" in markdown
    assert "ZHIXING_POSTGRES_BACKUP_STATUS" in markdown
    assert "owner_confirmed: `false`" in markdown
    assert "does not write server env files" in markdown


def test_candidates_cli_writes_blocked_markdown(tmp_path: Path):
    backup_path = tmp_path / "backup.json"
    restore_path = tmp_path / "restore.json"
    feasibility_path = tmp_path / "feasibility.json"
    output_path = tmp_path / "candidates.md"
    backup_path.write_text(json.dumps(_backup_schedule(), ensure_ascii=False), encoding="utf-8")
    restore_path.write_text(
        json.dumps(_backup_restore(status="blocked", pg_restore="not_checked", declaration="blocked"), ensure_ascii=False),
        encoding="utf-8",
    )
    feasibility_path.write_text(json.dumps(_feasibility(status="blocked"), ensure_ascii=False), encoding="utf-8")

    code = candidates.main(
        [
            "--backup-schedule-json",
            str(backup_path),
            "--backup-restore-json",
            str(restore_path),
            "--restore-feasibility-json",
            str(feasibility_path),
            "--markdown",
            "--output",
            str(output_path),
        ]
    )

    assert code == 2
    assert "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS" in output_path.read_text(encoding="utf-8")
