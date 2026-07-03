import json
from pathlib import Path
import time

from scripts import check_backup_alert_status as backup_alert


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _dump_bytes() -> bytes:
    return b"fake custom dump bytes\n" * 80


def test_fresh_postgres_backup_passes_without_echoing_path_or_filename(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "zhixing-postgres.dump"
    backup_file.write_bytes(_dump_bytes())

    report = backup_alert.build_backup_alert_status_report(backup_dir=str(backup_dir))
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["declaration_statuses"]["ZHIXING_BACKUP_ALERT_STATUS"] == "passed"
    latest = report["checks"]["postgres_backup"]["latest"]
    assert latest["extension"] == ".dump"
    assert latest["size_bytes"] == len(_dump_bytes())
    assert str(backup_dir) not in payload
    assert str(backup_file) not in payload
    assert "zhixing-postgres.dump" not in payload


def test_missing_or_repo_relative_backup_dir_blocks():
    report = backup_alert.build_backup_alert_status_report(backup_dir="./backups")
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["checks"]["backup_dir"]["status"] == "blocked"
    assert "./backups" not in payload


def test_stale_postgres_backup_blocks(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "zhixing-postgres.dump"
    backup_file.write_bytes(_dump_bytes())
    stale_time = time.time() - 72 * 3600
    backup_file.touch()
    backup_file.chmod(0o600)
    backup_file_stat_time = stale_time
    import os

    os.utime(backup_file, (backup_file_stat_time, backup_file_stat_time))

    report = backup_alert.build_backup_alert_status_report(
        backup_dir=str(backup_dir),
        max_age_hours=24,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["postgres_backup"]["status"] == "blocked"
    assert "older than the freshness threshold" in report["checks"]["postgres_backup"]["finding"]


def test_release_tar_is_not_counted_as_postgres_backup(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "zhixing-release-abcd1234.tar").write_bytes(b"release bytes")

    report = backup_alert.build_backup_alert_status_report(backup_dir=str(backup_dir))

    assert report["status"] == "blocked"
    assert report["checks"]["postgres_backup"]["candidate_count"] == 0


def test_rag_restore_artifact_required_passes_with_both_vectorstores(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "zhixing-postgres.dump").write_bytes(_dump_bytes())
    rag_dir = backup_dir / "rag-restore-drill-20260624032001"
    public = rag_dir / "vectorstore"
    internal = rag_dir / "vectorstore_internal"
    public.mkdir(parents=True)
    internal.mkdir(parents=True)
    (public / "chroma.sqlite3").write_bytes(b"public")
    (internal / "chroma.sqlite3").write_bytes(b"internal")

    report = backup_alert.build_backup_alert_status_report(
        backup_dir=str(backup_dir),
        require_rag_restore_artifact=True,
    )

    assert report["status"] == "passed"
    assert report["checks"]["rag_restore_artifact"]["status"] == "passed"


def test_rag_restore_artifact_required_blocks_missing_internal_store(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "zhixing-postgres.dump").write_bytes(_dump_bytes())
    public = backup_dir / "rag-restore-drill-20260624032001" / "vectorstore"
    public.mkdir(parents=True)
    (public / "chroma.sqlite3").write_bytes(b"public")

    report = backup_alert.build_backup_alert_status_report(
        backup_dir=str(backup_dir),
        require_rag_restore_artifact=True,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["rag_restore_artifact"]["status"] == "blocked"


def test_truncated_scan_blocks_because_latest_cannot_be_proven(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "zhixing-postgres.dump").write_bytes(_dump_bytes())
    (backup_dir / "extra.txt").write_text("extra", encoding="utf-8")

    report = backup_alert.build_backup_alert_status_report(
        backup_dir=str(backup_dir),
        max_scan=1,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["postgres_backup"]["scan_truncated"] is True
