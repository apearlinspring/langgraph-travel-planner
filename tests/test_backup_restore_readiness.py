from pathlib import Path
import tempfile

from scripts.check_backup_restore_readiness import build_backup_restore_readiness_report


def _env(backup_dir: str | None = None) -> dict[str, str]:
    resolved_backup_dir = backup_dir or str(Path(tempfile.gettempdir()) / "zhixing-backups")
    return {
        "ZHIXING_BACKUP_TARGET": "encrypted object storage",
        "ZHIXING_BACKUP_DIR": resolved_backup_dir,
        "ZHIXING_BACKUP_RETENTION": "7 daily backups and 3 release backups",
        "ZHIXING_RAG_RESTORE_STRATEGY": "rebuild from curated documents",
    }


def test_backup_restore_readiness_blocks_missing_inputs():
    report = build_backup_restore_readiness_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["writes_files_by_default"] is False
    assert {item["env_var"] for item in report["blocked_reasons"]} == {
        "ZHIXING_BACKUP_TARGET",
        "ZHIXING_BACKUP_DIR",
        "ZHIXING_BACKUP_RETENTION",
        "ZHIXING_RAG_RESTORE_STRATEGY",
    }


def test_backup_restore_readiness_passes_declared_absolute_outside_workspace():
    report = build_backup_restore_readiness_report(environ=_env())

    assert report["status"] == "passed"
    assert report["filesystem_probe"]["status"] == "not_checked"
    assert report["tool_probe"]["status"] == "not_checked"
    assert report["blocked_reasons"] == []
    assert all(item["value_echoed"] is False for item in report["checks"])


def test_backup_restore_readiness_accepts_posix_absolute_remote_path():
    report = build_backup_restore_readiness_report(environ=_env("/opt/zhixing-backups"))

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []


def test_backup_restore_readiness_blocks_default_or_workspace_backup_dir(tmp_path: Path):
    default_report = build_backup_restore_readiness_report(environ=_env("./backups"))
    workspace_report = build_backup_restore_readiness_report(
        environ=_env(str(Path.cwd() / "tmp-backups"))
    )

    assert default_report["status"] == "blocked"
    assert "local default" in default_report["blocked_reasons"][0]["finding"]
    assert workspace_report["status"] == "blocked"
    assert any("outside the Git workspace" in item["finding"] for item in workspace_report["blocked_reasons"])


def test_backup_restore_readiness_checks_retention_and_rag_strategy():
    env = _env()
    env["ZHIXING_BACKUP_RETENTION"] = "keep recent backups"
    env["ZHIXING_RAG_RESTORE_STRATEGY"] = "manual"

    report = build_backup_restore_readiness_report(environ=env)

    assert report["status"] == "blocked"
    findings = "\n".join(item["finding"] for item in report["blocked_reasons"])
    assert "numeric retention" in findings
    assert "backup or rebuild" in findings


def test_backup_restore_readiness_can_probe_filesystem_when_requested(tmp_path: Path):
    env = _env(str(tmp_path / "backup-target"))

    report = build_backup_restore_readiness_report(
        environ=env,
        check_filesystem=True,
    )

    assert report["status"] == "passed"
    assert report["filesystem_probe"]["status"] == "passed"
    assert not list((tmp_path / "backup-target").glob(".zhixing-backup-readiness-*.tmp"))
