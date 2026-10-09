from pathlib import Path


RUN_BACKUP = Path("deploy/run-backup.sh")
INSTALL_CRON = Path("deploy/install-backup-cron.sh")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_run_backup_defaults_to_dry_run_and_requires_execute_for_real_backup():
    source = _read(RUN_BACKUP)

    assert 'MODE="dry_run"' in source
    assert "--execute" in source
    assert 'if [ "$MODE" != "execute" ]' in source
    assert "dry_run=true" in source
    assert "would_run_pg_dump=true" in source
    assert "would_trigger_redis_bgsave=true" in source


def test_run_backup_uses_compose_without_printing_runtime_secret_values():
    source = _read(RUN_BACKUP)

    assert 'docker compose --env-file "$RUNTIME_ENV_FILE"' in source
    assert 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' in source
    assert 'REDIS_PASSWORD' in source
    assert "runtime_env_file_echoed=false" in source
    assert "backup_root_echoed=false" in source
    assert "POSTGRES_PASSWORD" not in source
    assert "cat .env" not in source
    assert "printenv" not in source


def test_run_backup_writes_redacted_summary_and_limits_pruning_to_own_artifacts():
    source = _read(RUN_BACKUP)

    assert "backup-summary.json" in source
    assert '"path_echoed": false' in source
    assert '"filename_echoed": false' in source
    assert "find \"$BACKUP_ROOT\" -maxdepth 1 -type d -name 'm1-backup-*'" in source
    assert "--prune-old" in source
    assert 'PRUNE_OLD="${ZHIXING_BACKUP_PRUNE_OLD:-0}"' in source


def test_install_backup_cron_defaults_to_dry_run_and_requires_execute_to_write_cron():
    source = _read(INSTALL_CRON)

    assert 'MODE="dry_run"' in source
    assert "--execute" in source
    assert 'if [ "$MODE" != "execute" ]' in source
    assert "dry_run=true" in source
    assert "would_install_cron=true" in source
    assert "mv \"$tmp_file\" \"$CRON_FILE\"" in source


def test_install_backup_cron_keeps_schedule_under_etc_cron_d_and_redacts_paths():
    source = _read(INSTALL_CRON)

    assert '/etc/cron.d/zhixing-backup' in source
    assert "/etc/cron.d/*" in source
    assert "cron file must stay under /etc/cron.d" in source
    assert "deploy_dir_echoed=false" in source
    assert "runtime_env_file_echoed=false" in source
    assert "backup_root_echoed=false" in source
    assert "cron_file_echoed=false" in source
    assert "log_file_echoed=false" in source


def test_install_backup_cron_invokes_run_backup_with_execute():
    source = _read(INSTALL_CRON)

    assert "deploy/run-backup.sh" in source
    assert "--execute$env_arg --backup-root" in source
    assert "ZHIXING_DEPLOY_DIR=" in source
    assert "ZHIXING_BACKUP_ROOT=" in source
    assert "Do not place secrets in this file" in source
