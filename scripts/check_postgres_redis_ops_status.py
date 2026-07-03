"""Check PostgreSQL and Redis operations evidence without reading secrets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_REDIS_OPS_STATUS_VERSION = "postgres_redis_ops_status.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done", "configured", "rotated"}
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
)


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _secret_like(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _base_check(*, key: str, env_var: str, label: str) -> dict[str, Any]:
    return {
        "key": key,
        "env_var": env_var,
        "label": label,
        "value_echoed": False,
    }


def _require_declared(
    *,
    environ: Mapping[str, str],
    env_var: str,
    key: str,
    label: str,
) -> dict[str, Any]:
    value = _value(environ, env_var)
    item = _base_check(key=key, env_var=env_var, label=label)
    if not value or _looks_placeholder(value):
        return {**item, "status": "blocked", "finding": "Required operations declaration is missing or placeholder-like."}
    if _secret_like(value):
        return {**item, "status": "blocked", "finding": "Declaration contains a secret-looking value pattern."}
    return {**item, "status": "passed", "finding": "Declared."}


def _require_ready(
    *,
    environ: Mapping[str, str],
    env_var: str,
    key: str,
    label: str,
) -> dict[str, Any]:
    item = _require_declared(environ=environ, env_var=env_var, key=key, label=label)
    if item["status"] == "blocked":
        return item
    value = _value(environ, env_var).lower()
    if value in READY_VALUES or any(word in value for word in ("ready", "passed", "configured", "verified", "rotated")):
        return {**item, "status": "passed", "finding": "Declared as passed/ready."}
    return {**item, "status": "blocked", "finding": "Expected passed/ready/configured declaration."}


def _service_mode_check(environ: Mapping[str, str], *, env_var: str, key: str, label: str, service: str) -> dict[str, Any]:
    item = _require_declared(environ=environ, env_var=env_var, key=key, label=label)
    if item["status"] == "blocked":
        return item
    value = _value(environ, env_var).lower()
    if service not in value:
        return {**item, "status": "blocked", "finding": f"{label} must mention {service}."}
    if "compose" in value or "single" in value:
        return {
            **item,
            "status": "degraded",
            "finding": f"{label} is acceptable for M1 but still single-node / Compose scoped.",
        }
    if any(word in value for word in ("managed", "ha", "high availability", "cluster", "cloud")):
        return {**item, "status": "passed", "finding": f"{label} declares managed or HA shape."}
    return {**item, "status": "degraded", "finding": f"{label} is declared but HA shape is not proven."}


def _session_lock_backend_check(environ: Mapping[str, str]) -> dict[str, Any]:
    item = _require_declared(
        environ=environ,
        env_var="SESSION_LOCK_BACKEND",
        key="session_lock_backend",
        label="Session lock backend",
    )
    if item["status"] == "blocked":
        return item
    if _value(environ, "SESSION_LOCK_BACKEND").lower() != "redis":
        return {**item, "status": "blocked", "finding": "Production session lock backend must be redis."}
    return {**item, "status": "passed", "finding": "Session lock backend is redis."}


def _redis_fallback_check(environ: Mapping[str, str]) -> dict[str, Any]:
    item = _require_declared(
        environ=environ,
        env_var="SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL",
        key="redis_fallback",
        label="Redis fallback to local lock",
    )
    if item["status"] == "blocked":
        return item
    if _value(environ, "SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL").lower() != "false":
        return {**item, "status": "blocked", "finding": "Production must not silently fall back to local locks."}
    return {**item, "status": "passed", "finding": "Redis fallback to local locks is disabled."}


def _numeric_timeout_check(
    environ: Mapping[str, str],
    *,
    env_var: str,
    key: str,
    label: str,
    max_seconds: float,
) -> dict[str, Any]:
    item = _require_declared(environ=environ, env_var=env_var, key=key, label=label)
    if item["status"] == "blocked":
        return item
    value = _value(environ, env_var)
    try:
        seconds = float(value)
    except ValueError:
        return {**item, "status": "blocked", "finding": "Timeout must be numeric seconds."}
    if seconds <= 0:
        return {**item, "status": "blocked", "finding": "Timeout must be greater than zero."}
    if seconds > max_seconds:
        return {**item, "status": "degraded", "finding": f"Timeout is declared but higher than {max_seconds:g}s M1 target."}
    return {**item, "status": "passed", "finding": "Timeout is within M1 target."}


def _window_check(environ: Mapping[str, str], *, env_var: str, key: str, label: str) -> dict[str, Any]:
    item = _require_declared(environ=environ, env_var=env_var, key=key, label=label)
    if item["status"] == "blocked":
        return item
    value = _value(environ, env_var).lower()
    if not any(char.isdigit() for char in value):
        return {**item, "status": "blocked", "finding": "RPO/RTO target must include a numeric window."}
    if not any(unit in value for unit in ("m", "min", "minute", "h", "hour", "小时", "分钟")):
        return {**item, "status": "blocked", "finding": "RPO/RTO target must include a time unit."}
    return {**item, "status": "passed", "finding": "RPO/RTO target is declared."}


def _keyword_policy_check(
    environ: Mapping[str, str],
    *,
    env_var: str,
    key: str,
    label: str,
    keywords: tuple[str, ...],
) -> dict[str, Any]:
    item = _require_declared(environ=environ, env_var=env_var, key=key, label=label)
    if item["status"] == "blocked":
        return item
    value = _value(environ, env_var).lower()
    if not any(keyword in value for keyword in keywords):
        return {**item, "status": "blocked", "finding": f"{label} does not mention required operations boundary."}
    return {**item, "status": "passed", "finding": f"{label} is declared."}


def _redis_exposure_check(environ: Mapping[str, str]) -> dict[str, Any]:
    item = _require_declared(
        environ=environ,
        env_var="ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS",
        key="redis_public_exposure",
        label="Redis public exposure status",
    )
    if item["status"] == "blocked":
        return item
    value = _value(environ, "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS").lower()
    safe_markers = ("private", "internal", "not exposed", "not public", "firewall", "blocked", "no public", "内网", "不暴露")
    unsafe_markers = ("0.0.0.0", "public open", "open to internet", "公网开放")
    if any(marker in value for marker in unsafe_markers):
        return {**item, "status": "blocked", "finding": "Redis must not be exposed to the public internet."}
    if any(marker in value for marker in safe_markers):
        return {**item, "status": "passed", "finding": "Redis public exposure boundary is safe."}
    return {**item, "status": "blocked", "finding": "Redis exposure declaration must explicitly say private/not exposed/firewalled."}


def _compose_scan(compose_path: Path, *, check: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "reads_dotenv": False,
        "starts_services": False,
        "path_echoed": False,
        "finding": "Compose scan not requested.",
    }
    if not check:
        return report
    try:
        text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {**report, "status": "blocked", "finding": f"Compose file scan failed: {exc.__class__.__name__}"}

    checks = [
        {
            "key": "postgres_volume",
            "status": "passed" if "postgres_data:/var/lib/postgresql/data" in text else "blocked",
            "finding": "PostgreSQL data volume is declared.",
        },
        {
            "key": "redis_volume",
            "status": "passed" if "redis_data:/data" in text else "blocked",
            "finding": "Redis data volume is declared.",
        },
        {
            "key": "redis_appendonly",
            "status": "passed" if "--appendonly yes" in text else "blocked",
            "finding": "Redis appendonly persistence is declared.",
        },
        {
            "key": "backend_depends_on_stateful_services",
            "status": "passed" if "postgres:" in text and "redis:" in text and "condition: service_healthy" in text else "blocked",
            "finding": "Backend depends on healthy PostgreSQL/Redis services.",
        },
        {
            "key": "session_lock_env",
            "status": "passed" if "SESSION_LOCK_BACKEND" in text and "SESSION_LOCK_REDIS_FALLBACK_TO_LOCAL" in text else "blocked",
            "finding": "Session lock production env vars are wired.",
        },
    ]
    blocked = [item for item in checks if item["status"] == "blocked"]
    report.update(
        {
            "status": "blocked" if blocked else "passed",
            "checks": checks,
            "blocked_reasons": blocked,
            "finding": "Compose stateful service scan passed." if not blocked else "Compose stateful service scan found gaps.",
        }
    )
    return report


def _overall_status(checks: Iterable[Mapping[str, Any]], compose_scan: Mapping[str, Any]) -> str:
    statuses = [str(item.get("status") or "unknown") for item in checks]
    if compose_scan.get("status") not in {None, "not_checked"}:
        statuses.append(str(compose_scan.get("status") or "unknown"))
    if any(status in {"blocked", "failed", "unknown"} for status in statuses):
        return "blocked"
    if any(status in {"degraded", "not_checked"} for status in statuses):
        return "degraded"
    return "passed"


def build_postgres_redis_ops_status_report(
    *,
    environ: Mapping[str, str] | None = None,
    check_compose: bool = False,
    compose_path: Path | None = None,
) -> dict[str, Any]:
    """Build a redacted PostgreSQL/Redis operations status report."""

    env = environ if environ is not None else os.environ
    checks = [
        _service_mode_check(env, env_var="ZHIXING_POSTGRES_MODE", key="postgres_mode", label="PostgreSQL mode", service="postgres"),
        _service_mode_check(env, env_var="ZHIXING_REDIS_MODE", key="redis_mode", label="Redis mode", service="redis"),
        _require_ready(environ=env, env_var="ZHIXING_DATABASE_SECRET_STATUS", key="database_secret", label="Database secret status"),
        _require_ready(environ=env, env_var="ZHIXING_REDIS_SECRET_STATUS", key="redis_secret", label="Redis secret status"),
        _require_ready(environ=env, env_var="ZHIXING_POSTGRES_BACKUP_STATUS", key="postgres_backup", label="PostgreSQL backup status"),
        _require_ready(environ=env, env_var="ZHIXING_POSTGRES_RESTORE_DRILL_STATUS", key="postgres_restore_drill", label="PostgreSQL restore drill status"),
        _window_check(env, env_var="ZHIXING_RPO_TARGET", key="rpo_target", label="RPO target"),
        _window_check(env, env_var="ZHIXING_RTO_TARGET", key="rto_target", label="RTO target"),
        _keyword_policy_check(
            env,
            env_var="ZHIXING_POSTGRES_MIGRATION_POLICY",
            key="postgres_migration_policy",
            label="PostgreSQL migration policy",
            keywords=("migration", "migrate", "alembic", "backup", "rollback", "迁移", "备份", "回滚"),
        ),
        _keyword_policy_check(
            env,
            env_var="ZHIXING_POSTGRES_SLOW_QUERY_POLICY",
            key="postgres_slow_query_policy",
            label="PostgreSQL slow query policy",
            keywords=("slow", "timeout", "statement", "index", "explain", "慢", "索引", "超时"),
        ),
        _numeric_timeout_check(env, env_var="POSTGRES_CONNECT_TIMEOUT_SECONDS", key="postgres_connect_timeout", label="PostgreSQL connect timeout", max_seconds=10),
        _numeric_timeout_check(env, env_var="POSTGRES_POOL_TIMEOUT_SECONDS", key="postgres_pool_timeout", label="PostgreSQL pool timeout", max_seconds=10),
        _numeric_timeout_check(env, env_var="POSTGRES_STATEMENT_TIMEOUT_SECONDS", key="postgres_statement_timeout", label="PostgreSQL statement timeout", max_seconds=60),
        _session_lock_backend_check(env),
        _redis_fallback_check(env),
        _numeric_timeout_check(env, env_var="SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS", key="redis_operation_timeout", label="Redis lock operation timeout", max_seconds=5),
        _keyword_policy_check(
            env,
            env_var="ZHIXING_REDIS_PERSISTENCE_STATUS",
            key="redis_persistence",
            label="Redis persistence status",
            keywords=("appendonly", "aof", "snapshot", "rdb", "passed", "ready", "持久", "快照"),
        ),
        _redis_exposure_check(env),
        _keyword_policy_check(
            env,
            env_var="ZHIXING_REDIS_RECOVERY_STRATEGY",
            key="redis_recovery_strategy",
            label="Redis recovery strategy",
            keywords=("restart", "restore", "snapshot", "aof", "rebuild", "恢复", "重启", "快照"),
        ),
    ]
    compose = _compose_scan(compose_path or PROJECT_ROOT / "docker-compose.yml", check=check_compose)
    blocked = [item for item in checks if item["status"] == "blocked"]
    degraded = [item for item in checks if item["status"] == "degraded"]
    if compose.get("status") == "blocked":
        blocked.extend({**item, "env_var": "docker-compose.yml", "value_echoed": False} for item in compose.get("blocked_reasons") or [])
    elif compose.get("status") == "degraded":
        degraded.append({"key": "compose_scan", "env_var": "docker-compose.yml", "label": "Compose scan", "status": "degraded", "finding": compose.get("finding"), "value_echoed": False})

    status = _overall_status(checks, compose)
    return {
        "version": POSTGRES_REDIS_OPS_STATUS_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "starts_services": False,
            "does_not_echo_values": True,
            "compose_scan_requested": check_compose,
        },
        "checks": checks,
        "compose_scan": compose,
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "declaration_statuses": {
            "ZHIXING_POSTGRES_REDIS_OPS_STATUS": status,
            "ZHIXING_POSTGRES_OPS_STATUS": "blocked" if any(item["key"].startswith("postgres") or item["key"] in {"database_secret", "rpo_target", "rto_target"} for item in blocked) else ("degraded" if any(item["key"].startswith("postgres") or item["key"] in {"rpo_target", "rto_target"} for item in degraded) else "passed"),
            "ZHIXING_REDIS_OPS_STATUS": "blocked" if any(item["key"].startswith("redis") or item["key"].startswith("session_lock") for item in blocked) else ("degraded" if any(item["key"].startswith("redis") for item in degraded) else "passed"),
        },
        "not_proven_by_this_report": [
            "This report does not read .env files, database rows, Redis keys, logs, dumps, or secret values.",
            "Declaration checks do not prove managed HA, automatic failover, PITR, or a full disaster recovery drill.",
            "Compose scan proves repository wiring only; it does not prove the current target server is running these services.",
            "Single-node Compose PostgreSQL/Redis can be acceptable for M1 but remains degraded for full production HA.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL / Redis Ops Status",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, connects_database=false, connects_redis=false",
        "",
        "## Checks",
    ]
    for item in report.get("checks") or []:
        lines.append(f"- {item.get('env_var')}: {item.get('status')} ({item.get('finding')})")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded"])
        for item in report["degraded_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    return "\n".join(lines)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--check-compose", action="store_true", help="Scan docker-compose.yml for stateful service wiring.")
    parser.add_argument("--compose-path", type=_path_arg, default=None, help="Optional compose file path.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_postgres_redis_ops_status_report(
        check_compose=args.check_compose,
        compose_path=args.compose_path,
    )
    if args.json:
        output_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    else:
        output_text = _render_human(report) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
