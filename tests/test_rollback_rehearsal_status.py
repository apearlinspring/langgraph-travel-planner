import json
from pathlib import Path
import tarfile

from scripts import check_rollback_rehearsal_status as rehearsal


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def _build_backup(root: Path) -> Path:
    backup = root / "backup"
    for entry in ("app", "frontend", "docs", "deploy"):
        (backup / entry).mkdir(parents=True)
    (backup / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (backup / "README.md").write_text("readme\n", encoding="utf-8")
    return backup


def _build_archive(path: Path, root: Path, entries: list[str]) -> None:
    with tarfile.open(path, "w") as archive:
        for entry in entries:
            item = root / entry
            item.parent.mkdir(parents=True, exist_ok=True)
            item.write_text(entry, encoding="utf-8")
            archive.add(item, arcname=entry)


def test_rollback_rehearsal_passes_without_echoing_paths_or_filenames(tmp_path: Path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    backup = _build_backup(tmp_path)
    archive = tmp_path / "release.tar"
    _build_archive(archive, tmp_path, ["app/main.py", "README.md"])

    def fake_get(url: str, timeout_seconds: float):
        if url.endswith("/api/v1/mock-checkout/ORDER-ROLLBACKDRILL/status"):
            return 200, json.dumps(
                {
                    "status": "demo_only",
                    "real_payment": False,
                    "real_booking": False,
                    "inventory_locked": False,
                    "fulfillment_triggered": False,
                }
            )
        return 200, '{"status":"ready"}'

    report = rehearsal.build_rollback_rehearsal_status_report(
        deploy_dir=str(deploy),
        backup_dir=str(backup),
        release_archive=str(archive),
        check_health=True,
        check_mock_checkout=True,
        http_get=fake_get,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["policy"]["executes_rollback"] is False
    assert report["checks"]["backup_snapshot"]["status"] == "passed"
    assert report["checks"]["current_health"]["status"] == "passed"
    assert report["checks"]["mock_checkout_boundary"]["status"] == "passed"
    assert report["declaration_statuses"]["ZHIXING_ROLLBACK_TARGET_STATUS"] == "passed"
    assert report["declaration_statuses"]["ZHIXING_ROLLBACK_DRILL_STATUS"] == "degraded"
    assert str(deploy) not in payload
    assert str(backup) not in payload
    assert "release.tar" not in payload


def test_backup_with_env_is_blocked(tmp_path: Path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    backup = _build_backup(tmp_path)
    (backup / ".env").write_text("SECRET=should-not-ship\n", encoding="utf-8")

    report = rehearsal.build_rollback_rehearsal_status_report(
        deploy_dir=str(deploy),
        backup_dir=str(backup),
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert ".env" in report["checks"]["backup_snapshot"]["forbidden_runtime_entries_present"]
    assert "should-not-ship" not in payload


def test_release_archive_with_env_is_blocked(tmp_path: Path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    backup = _build_backup(tmp_path)
    archive = tmp_path / "release.tar"
    _build_archive(archive, tmp_path, [".env"])

    report = rehearsal.build_rollback_rehearsal_status_report(
        deploy_dir=str(deploy),
        backup_dir=str(backup),
        release_archive=str(archive),
    )

    assert report["status"] == "blocked"
    assert report["checks"]["release_archive"]["forbidden_runtime_entries_present"] == [".env"]


def test_mock_checkout_probe_blocks_when_real_payment_flag_is_true(tmp_path: Path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    backup = _build_backup(tmp_path)

    def fake_get(url: str, timeout_seconds: float):
        return 200, json.dumps(
            {
                "status": "demo_only",
                "real_payment": True,
                "real_booking": False,
                "inventory_locked": False,
                "fulfillment_triggered": False,
            }
        )

    report = rehearsal.build_rollback_rehearsal_status_report(
        deploy_dir=str(deploy),
        backup_dir=str(backup),
        check_mock_checkout=True,
        http_get=fake_get,
    )

    assert report["status"] == "blocked"
    assert report["checks"]["mock_checkout_boundary"]["checks"]["real_payment_false"] is False


def test_relative_paths_are_blocked():
    report = rehearsal.build_rollback_rehearsal_status_report(
        deploy_dir="relative/deploy",
        backup_dir="relative/backup",
    )

    assert report["status"] == "blocked"
    assert report["checks"]["deploy_dir"]["status"] == "blocked"
    assert report["checks"]["backup_dir"]["status"] == "blocked"
