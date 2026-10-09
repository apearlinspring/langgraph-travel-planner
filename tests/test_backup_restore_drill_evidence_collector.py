import json
from pathlib import Path
import subprocess

from scripts import collect_backup_restore_drill_evidence as drill


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _restore_env(backup_dir: str) -> dict[str, str]:
    return {
        "ZHIXING_BACKUP_DIR": backup_dir,
        "ZHIXING_BACKUP_TARGET": "encrypted object storage",
        "ZHIXING_BACKUP_RETENTION": "7 daily backups and 3 release backups",
        "ZHIXING_RAG_RESTORE_STRATEGY": "rebuild from curated documents",
        "ZHIXING_POSTGRES_BACKUP_STATUS": "passed",
        "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS": "passed",
        "ZHIXING_RAG_RESTORE_DRILL_STATUS": "passed",
        "ZHIXING_RESTORE_DRILL_OWNER": "ops owner",
        "ZHIXING_ACCEPTABLE_DATA_LOSS": "1 hour",
    }


def test_default_backup_restore_drill_report_is_plan_only():
    report = drill.build_backup_restore_drill_evidence_report(environ={})

    assert report["status"] == "not_checked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["connects_production_database"] is False
    assert report["section_statuses"] == {}
    assert "<backup-file>" in _payload_text(report)


def test_backup_dir_probe_blocks_missing_or_repo_relative_paths():
    report = drill.build_backup_restore_drill_evidence_report(
        environ={},
        backup_dir="./backups",
        check_backup_dir=True,
    )

    assert report["status"] == "blocked"
    assert report["sections"]["backup_artifact_probe"]["status"] == "blocked"
    assert "./backups" not in _payload_text(report)


def test_latest_dump_probe_passes_without_echoing_path_or_filename(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "postgres.dump"
    backup_file.write_bytes(b"fake custom dump bytes")

    report = drill.build_backup_restore_drill_evidence_report(
        environ={},
        backup_dir=str(backup_dir),
        check_backup_dir=True,
        check_latest_dump=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    latest = report["sections"]["backup_artifact_probe"]["latest_backup"]["latest"]
    assert latest["extension"] == ".dump"
    assert latest["size_bytes"] == len(b"fake custom dump bytes")
    assert str(backup_dir) not in payload
    assert str(backup_file) not in payload
    assert "postgres.dump" not in payload


def test_pg_restore_list_probe_passes_with_custom_dump(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "release.dump"
    backup_file.write_bytes(b"fake custom dump bytes")
    calls = []

    def fake_runner(args, *, timeout_seconds):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="table list", stderr="")

    report = drill.build_backup_restore_drill_evidence_report(
        environ={},
        backup_dir=str(backup_dir),
        check_backup_dir=True,
        check_latest_dump=True,
        check_pg_restore_list=True,
        command_runner=fake_runner,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert calls == [["pg_restore", "--list", str(backup_file)]]
    assert report["sections"]["backup_artifact_probe"]["pg_restore_list"]["status"] == "passed"
    assert str(backup_file) not in payload


def test_pg_restore_list_probe_blocks_and_redacts_stderr(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "release.dump"
    backup_file.write_bytes(b"fake custom dump bytes")

    def fake_runner(args, *, timeout_seconds):
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr=f"could not read {backup_file} with PASSWORD=secret\n",
        )

    report = drill.build_backup_restore_drill_evidence_report(
        environ={},
        backup_dir=str(backup_dir),
        check_latest_dump=True,
        check_pg_restore_list=True,
        command_runner=fake_runner,
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert str(backup_file) not in payload
    assert "secret" not in payload
    assert "<backup-file>" in payload
    assert "[REDACTED]" in payload


def test_restore_drill_declaration_passes_without_echoing_values(tmp_path: Path):
    env = _restore_env(str(tmp_path / "backups"))

    report = drill.build_backup_restore_drill_evidence_report(
        environ=env,
        require_restore_drill_declaration=True,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["sections"]["restore_drill_declaration"]["status"] == "passed"
    assert "ops owner" not in payload
    assert "1 hour" not in payload


def test_restore_drill_declaration_accepts_posix_absolute_remote_path():
    env = _restore_env("/opt/zhixing-backups")

    report = drill.build_backup_restore_drill_evidence_report(
        environ=env,
        include_readiness=True,
        require_restore_drill_declaration=True,
    )

    assert report["status"] == "passed"
    assert report["sections"]["backup_restore_readiness"]["status"] == "passed"


def test_restore_drill_declaration_blocks_missing_values():
    report = drill.build_backup_restore_drill_evidence_report(
        environ={},
        require_restore_drill_declaration=True,
    )

    assert report["status"] == "blocked"
    blockers = report["sections"]["restore_drill_declaration"]["blocked_reasons"]
    assert {item["env_var"] for item in blockers} == {
        "ZHIXING_POSTGRES_BACKUP_STATUS",
        "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
        "ZHIXING_RAG_RESTORE_DRILL_STATUS",
        "ZHIXING_RESTORE_DRILL_OWNER",
        "ZHIXING_ACCEPTABLE_DATA_LOSS",
    }


def test_backup_restore_drill_markdown_keeps_boundaries():
    report = drill.build_backup_restore_drill_evidence_report(environ={})

    markdown = drill.build_backup_restore_drill_evidence_markdown(report)

    assert "Backup Restore Drill Evidence" in markdown
    assert "Plan-only mode proves no backup or restore result" in markdown
    assert "<backup-file>" in markdown
