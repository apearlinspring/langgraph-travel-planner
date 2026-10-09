import json
from pathlib import Path

from scripts.check_postgres_redis_ops_status import build_postgres_redis_ops_status_report
from scripts import check_postgres_redis_ops_status as ops_status


def _managed_env() -> dict[str, str]:
    return {
        "ZHIXING_POSTGRES_MODE": "managed postgresql with HA",
        "ZHIXING_REDIS_MODE": "managed redis cluster",
        "ZHIXING_DATABASE_SECRET_STATUS": "rotated and ready",
        "ZHIXING_REDIS_SECRET_STATUS": "rotated and ready",
        "ZHIXING_POSTGRES_BACKUP_STATUS": "passed",
        "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS": "passed",
        "ZHIXING_RPO_TARGET": "24h",
        "ZHIXING_RTO_TARGET": "30min",
        "ZHIXING_POSTGRES_MIGRATION_POLICY": "backup before migration, alembic migration, rollback plan",
        "ZHIXING_POSTGRES_SLOW_QUERY_POLICY": "statement timeout and slow query index review",
        "POSTGRES_CONNECT_TIMEOUT_SECONDS": "5",
        "POSTGRES_POOL_TIMEOUT_SECONDS": "5",
        "POSTGRES_STATEMENT_TIMEOUT_SECONDS": "10",
        "SESSION_LOCK_BACKEND": "redis",
        "SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL": "false",
        "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS": "0.5",
        "ZHIXING_REDIS_PERSISTENCE_STATUS": "AOF appendonly ready",
        "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS": "private internal network, not exposed",
        "ZHIXING_REDIS_RECOVERY_STRATEGY": "restore from snapshot or AOF then restart",
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_missing_ops_declarations_block_without_reading_secrets():
    report = build_postgres_redis_ops_status_report(environ={})

    assert report["status"] == "blocked"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["connects_database"] is False
    assert report["policy"]["connects_redis"] is False
    assert report["blocked_reasons"]


def test_managed_ops_declarations_pass():
    report = build_postgres_redis_ops_status_report(environ=_managed_env())

    assert report["status"] == "passed"
    assert report["blocked_reasons"] == []
    assert report["degraded_reasons"] == []
    assert report["declaration_statuses"] == {
        "ZHIXING_POSTGRES_REDIS_OPS_STATUS": "passed",
        "ZHIXING_POSTGRES_OPS_STATUS": "passed",
        "ZHIXING_REDIS_OPS_STATUS": "passed",
    }


def test_compose_modes_are_degraded_but_not_blocked_for_m1():
    env = _managed_env()
    env["ZHIXING_POSTGRES_MODE"] = "compose-postgresql single node"
    env["ZHIXING_REDIS_MODE"] = "compose-redis single node"

    report = build_postgres_redis_ops_status_report(environ=env)

    assert report["status"] == "degraded"
    assert report["blocked_reasons"] == []
    assert {item["env_var"] for item in report["degraded_reasons"]} == {
        "ZHIXING_POSTGRES_MODE",
        "ZHIXING_REDIS_MODE",
    }


def test_local_lock_fallback_blocks_production_ops():
    env = _managed_env()
    env["SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL"] = "true"

    report = build_postgres_redis_ops_status_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL" for item in report["blocked_reasons"])


def test_public_redis_exposure_blocks_ops():
    env = _managed_env()
    env["ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS"] = "public open to internet"

    report = build_postgres_redis_ops_status_report(environ=env)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS" for item in report["blocked_reasons"])


def test_secret_like_declaration_blocks_and_does_not_echo_value():
    env = _managed_env()
    sensitive_value = "pass" + "word=" + "test-value-123456"
    env["ZHIXING_REDIS_SECRET_STATUS"] = sensitive_value

    report = build_postgres_redis_ops_status_report(environ=env)
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert any(item["env_var"] == "ZHIXING_REDIS_SECRET_STATUS" for item in report["blocked_reasons"])
    assert "test-value-123456" not in payload


def test_compose_scan_passes_current_stateful_wiring():
    report = build_postgres_redis_ops_status_report(
        environ=_managed_env(),
        check_compose=True,
    )

    assert report["compose_scan"]["status"] == "passed"
    assert report["status"] == "passed"


def test_timeout_above_target_degrades_but_does_not_block():
    env = _managed_env()
    env["POSTGRES_STATEMENT_TIMEOUT_SECONDS"] = "120"

    report = build_postgres_redis_ops_status_report(environ=env)

    assert report["status"] == "degraded"
    assert any(item["env_var"] == "POSTGRES_STATEMENT_TIMEOUT_SECONDS" for item in report["degraded_reasons"])


def test_ops_status_cli_writes_utf8_json_output(tmp_path: Path, monkeypatch):
    for key, value in _managed_env().items():
        monkeypatch.setenv(key, value)
    output_path = tmp_path / "postgres-redis-ops-status.json"

    code = ops_status.main(["--json", "--check-compose", "--output", str(output_path)])
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "passed"
