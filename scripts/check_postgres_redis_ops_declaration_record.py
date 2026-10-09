"""Validate a private PostgreSQL/Redis operations declaration record.

The checker validates operator-accepted non-secret declarations before they are
written to a server shared env file or secret manager. It does not read `.env`,
connect to PostgreSQL, connect to Redis, connect SSH, write server env files or
echo private values.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION = "postgres_redis_ops_declaration_record.v1"
POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION = "postgres_redis_ops_declaration_request.v1"

READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done", "configured", "rotated"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
SAFE_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,100}$")
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
)
URL_PATTERN = re.compile(r"https?://[^\s`'\"<>()\[\]{}|]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} JSON could not be read or parsed.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object.")
    return payload


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _looks_placeholder(value: Any) -> bool:
    lowered = str(value or "").strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _has_final_text(value: Any) -> bool:
    return _has_text(value) and not _looks_placeholder(value)


def _is_ready(value: Any) -> bool:
    return str(value or "").strip().lower() in READY_VALUES


def _secret_like(value: Any) -> bool:
    text = str(value or "")
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _blocker(check: str, field: str, finding: str) -> dict[str, str]:
    return {"check": check, "field": field, "finding": finding}


def _request_env_vars(request: Mapping[str, Any]) -> list[str]:
    env_vars: list[str] = []
    seen: set[str] = set()
    for item in _as_list(request.get("declarations")):
        if not isinstance(item, Mapping):
            continue
        env_var = str(item.get("env_var") or "").strip()
        if SAFE_ENV_NAME_PATTERN.fullmatch(env_var) and env_var not in seen:
            seen.add(env_var)
            env_vars.append(env_var)
    return env_vars


def _request_by_env(request: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("env_var")): item
        for item in _as_list(request.get("declarations"))
        if isinstance(item, Mapping) and SAFE_ENV_NAME_PATTERN.fullmatch(str(item.get("env_var") or ""))
    }


def _record_by_env(record: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in _as_list(record.get("declarations")):
        if not isinstance(item, Mapping):
            continue
        env_var = str(item.get("env_var") or "").strip()
        if SAFE_ENV_NAME_PATTERN.fullmatch(env_var):
            result[env_var] = item
    return result


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = ("record_id", "accepted_at", "scope", "owner")
    missing = [field for field in required if not _has_final_text(record.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "value_echoed": False,
    }


def _request_check(request: Mapping[str, Any]) -> dict[str, Any]:
    blockers = []
    if request.get("version") != POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION:
        blockers.append(_blocker("source_request", "version", "Declaration request version is not recognized."))
    if not _request_env_vars(request):
        blockers.append(_blocker("source_request", "declarations", "Declaration request has no missing declarations."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "missing_count": len(_request_env_vars(request)),
        "value_echoed": False,
    }


def _value_check(env_var: str, value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    lowered = text.lower()
    if not _has_final_text(text):
        return "blocked", "Accepted declaration value is missing or placeholder-like."
    if _secret_like(text):
        return "blocked", "Accepted declaration contains a secret-looking value pattern."
    if env_var == "ZHIXING_POSTGRES_MODE":
        if "postgres" not in lowered:
            return "blocked", "PostgreSQL mode must mention postgres."
        if "compose" in lowered or "single" in lowered:
            return "degraded", "PostgreSQL mode is M1 acceptable but still single-node / Compose scoped."
        if any(word in lowered for word in ("managed", "ha", "high availability", "cluster", "cloud")):
            return "passed", "PostgreSQL mode declares managed or HA shape."
        return "degraded", "PostgreSQL mode is declared but HA shape is not proven."
    if env_var == "ZHIXING_REDIS_MODE":
        if "redis" not in lowered:
            return "blocked", "Redis mode must mention redis."
        if "compose" in lowered or "single" in lowered:
            return "degraded", "Redis mode is M1 acceptable but still single-node / Compose scoped."
        if any(word in lowered for word in ("managed", "ha", "high availability", "cluster", "cloud")):
            return "passed", "Redis mode declares managed or HA shape."
        return "degraded", "Redis mode is declared but HA shape is not proven."
    if env_var in {"ZHIXING_DATABASE_SECRET_STATUS", "ZHIXING_REDIS_SECRET_STATUS", "ZHIXING_POSTGRES_BACKUP_STATUS", "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"}:
        if lowered in READY_VALUES or any(word in lowered for word in ("ready", "passed", "configured", "verified", "rotated", "completed")):
            return "passed", "Ready/passed declaration is accepted."
        return "blocked", "Expected passed/ready/configured declaration."
    if env_var in {"ZHIXING_RPO_TARGET", "ZHIXING_RTO_TARGET"}:
        if not any(char.isdigit() for char in lowered):
            return "blocked", "RPO/RTO target must include a numeric window."
        if not any(unit in lowered for unit in ("m", "min", "minute", "h", "hour", "小时", "分钟")):
            return "blocked", "RPO/RTO target must include a time unit."
        return "passed", "RPO/RTO target is accepted."
    if env_var == "ZHIXING_POSTGRES_MIGRATION_POLICY":
        if any(keyword in lowered for keyword in ("migration", "migrate", "alembic", "backup", "rollback", "迁移", "备份", "回滚")):
            return "passed", "Migration policy boundary is accepted."
        return "blocked", "Migration policy must mention migration/backup/rollback boundary."
    if env_var == "ZHIXING_POSTGRES_SLOW_QUERY_POLICY":
        if any(keyword in lowered for keyword in ("slow", "timeout", "statement", "index", "explain", "慢", "索引", "超时")):
            return "passed", "Slow-query policy boundary is accepted."
        return "blocked", "Slow-query policy must mention slow query, timeout or index review."
    if env_var == "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS":
        try:
            seconds = float(text)
        except ValueError:
            return "blocked", "Redis lock operation timeout must be numeric seconds."
        if seconds <= 0:
            return "blocked", "Redis lock operation timeout must be greater than zero."
        if seconds > 5:
            return "degraded", "Redis lock operation timeout is higher than 5s M1 target."
        return "passed", "Redis lock operation timeout is within M1 target."
    if env_var == "ZHIXING_REDIS_PERSISTENCE_STATUS":
        if any(keyword in lowered for keyword in ("appendonly", "aof", "snapshot", "rdb", "passed", "ready", "持久", "快照")):
            return "passed", "Redis persistence declaration is accepted."
        return "blocked", "Redis persistence must mention appendonly/AOF/snapshot."
    if env_var == "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS":
        unsafe_markers = ("0.0.0.0", "public open", "open to internet", "公网开放")
        safe_markers = ("private", "internal", "not exposed", "not public", "firewall", "blocked", "no public", "内网", "不暴露")
        if any(marker in lowered for marker in unsafe_markers):
            return "blocked", "Redis must not be exposed to the public internet."
        if any(marker in lowered for marker in safe_markers):
            return "passed", "Redis public exposure boundary is accepted."
        return "blocked", "Redis exposure declaration must explicitly say private/not exposed/firewalled."
    if env_var == "ZHIXING_REDIS_RECOVERY_STRATEGY":
        if any(keyword in lowered for keyword in ("restart", "restore", "snapshot", "aof", "rebuild", "恢复", "重启", "快照")):
            return "passed", "Redis recovery strategy is accepted."
        return "blocked", "Redis recovery strategy must mention restart/restore/snapshot/AOF/rebuild."
    return "passed", "Declaration value is accepted."


def _declarations_check(request: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    request_items = _request_by_env(request)
    record_items = _record_by_env(record)
    blockers = []
    degraded = []
    summaries = []
    for env_var, request_item in request_items.items():
        item = record_items.get(env_var)
        if item is None:
            blockers.append(_blocker("declarations", env_var, "Missing accepted declaration."))
            continue
        if item.get("owner_confirmed") is not True:
            blockers.append(_blocker("declarations", env_var, "Declaration must be explicitly owner_confirmed=true."))
        if not _has_final_text(item.get("evidence_ref")):
            blockers.append(_blocker("declarations", env_var, "Declaration evidence_ref is missing or placeholder-like."))
        status, finding = _value_check(env_var, item.get("accepted_value"))
        if status == "blocked":
            blockers.append(_blocker("declarations", env_var, finding))
        elif status == "degraded":
            degraded.append({"env_var": env_var, "finding": finding, "value_echoed": False})
        summaries.append(
            {
                "env_var": env_var,
                "category": request_item.get("category"),
                "execution_bucket": request_item.get("execution_bucket"),
                "value_status": status,
                "owner_confirmed": item.get("owner_confirmed") is True,
                "value_echoed": False,
            }
        )
    extras = sorted(set(record_items) - set(request_items))
    return {
        "status": "blocked" if blockers else ("degraded" if degraded else "passed"),
        "accepted_count": len(record_items),
        "required_count": len(request_items),
        "extra_declarations": extras,
        "summaries": summaries,
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
        "value_echoed": False,
    }


def _write_plan_check(record: Mapping[str, Any]) -> dict[str, Any]:
    plan = _as_mapping(record.get("write_plan"))
    blockers = []
    if str(plan.get("target") or "").strip().lower() not in {"server_shared_env", "secret_manager", "server_shared_env_or_secret_manager"}:
        blockers.append(_blocker("write_plan", "target", "Write target must be server_shared_env or secret_manager."))
    for key in ("will_not_commit_to_git", "requires_rerun_ops_status", "requires_rerun_ops_summary", "requires_rerun_m1_go_no_go"):
        if plan.get(key) is not True:
            blockers.append(_blocker("write_plan", key, "Write plan must explicitly require this safety step."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blockers = []
    for key in ("secret_values_included", "raw_urls_included", "raw_ips_included", "dotenv_content_included", "server_paths_included"):
        if boundary.get(key) is not False:
            blockers.append(_blocker("redaction_boundary", key, "Redaction boundary must explicitly be false."))
    for pattern in SECRET_PATTERNS:
        if pattern.search(raw_text):
            blockers.append(_blocker("redaction_boundary", "record_text", "Record contains a secret-looking value pattern."))
            break
    if URL_PATTERN.search(raw_text):
        blockers.append(_blocker("redaction_boundary", "record_text", "Record contains a raw URL."))
    if IPV4_PATTERN.search(raw_text):
        blockers.append(_blocker("redaction_boundary", "record_text", "Record contains a raw IPv4 address."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "record_text_echoed": False,
    }


def _status_from_checks(checks: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    blockers = []
    degraded = []
    for name, check in checks.items():
        if check.get("status") == "blocked":
            for item in check.get("blocked_reasons") or []:
                if isinstance(item, Mapping):
                    blockers.append({"check": name, **dict(item)})
            if not check.get("blocked_reasons"):
                blockers.append({"check": name, "finding": "blocked"})
        if check.get("status") == "degraded":
            for item in check.get("degraded_reasons") or []:
                if isinstance(item, Mapping):
                    degraded.append({"check": name, **dict(item)})
            if not check.get("degraded_reasons"):
                degraded.append({"check": name, "finding": "degraded"})
    if blockers:
        return "blocked", blockers, degraded
    if degraded:
        return "degraded", blockers, degraded
    return "passed", blockers, degraded


def build_postgres_redis_ops_declaration_record_report(
    *,
    request: Mapping[str, Any],
    record: Mapping[str, Any],
    raw_text: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a validation report for accepted PostgreSQL/Redis declarations."""

    checks = {
        "source_request": _request_check(request),
        "required_fields": _required_fields_check(record),
        "declarations": _declarations_check(request, record),
        "write_plan": _write_plan_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers, degraded = _status_from_checks(checks)
    now = generated_at or datetime.now(UTC)
    return {
        "version": POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "connects_ssh": False,
            "writes_server_env": False,
            "echoes_secret_values": False,
            "safe_to_commit": False,
        },
        "record_summary": {
            "record_id_present": _has_text(record.get("record_id")),
            "owner_present": _has_text(record.get("owner")),
            "required_declarations": checks["declarations"].get("required_count"),
            "accepted_declarations": checks["declarations"].get("accepted_count"),
            "extra_declarations": checks["declarations"].get("extra_declarations"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_POSTGRES_REDIS_DECLARATION_ACCEPTANCE_STATUS": status,
            "ZHIXING_POSTGRES_REDIS_DECLARATION_READY_TO_WRITE_STATUS": "passed" if status in {"passed", "degraded"} else "blocked",
        },
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
        "not_proven_by_this_report": [
            "The accepted declarations have not been written to the server by this checker.",
            "This checker does not prove PostgreSQL backup, restore drill, managed HA, PITR, multi-AZ failover or long-duration stability.",
            "After writing declarations, rerun ops status, ops summary and M1 go/no-go against the target runtime.",
            "Raw .env contents, paths, URLs, IP addresses and secret values must stay outside Git and chat.",
        ],
    }


def _draft_value(item: Mapping[str, Any]) -> str:
    if item.get("confidence") == "suggested_from_live_probe":
        return str(item.get("suggested_value") or "")
    if item.get("confidence") == "safe_default_requires_owner_acceptance":
        return str(item.get("suggested_value") or "")
    return f"<owner-confirmed-value-for-{item.get('env_var')}>"


def build_postgres_redis_ops_declaration_record_draft(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a private draft record from a declaration request."""

    now = datetime.now(UTC)
    declarations = []
    for item in _as_list(request.get("declarations")):
        if not isinstance(item, Mapping):
            continue
        env_var = str(item.get("env_var") or "").strip()
        if not SAFE_ENV_NAME_PATTERN.fullmatch(env_var):
            continue
        declarations.append(
            {
                "env_var": env_var,
                "accepted_value": _draft_value(item),
                "source_confidence": item.get("confidence"),
                "execution_bucket": item.get("execution_bucket"),
                "owner_confirmed": False,
                "evidence_ref": "<private-evidence-ref>",
                "value_echoed": False,
            }
        )
    return {
        "record_id": f"postgres-redis-ops-declaration-draft-{now.strftime('%Y%m%d')}",
        "accepted_at": now.isoformat(),
        "scope": "M1 PostgreSQL/Redis non-secret operations declarations",
        "owner": "<operations-owner-role>",
        "source_request": {
            "version": request.get("version"),
            "status": request.get("status"),
            "missing_count": request.get("missing_count"),
            "execution_bucket_counts": request.get("execution_bucket_counts"),
        },
        "declarations": declarations,
        "write_plan": {
            "target": "server_shared_env_or_secret_manager",
            "will_not_commit_to_git": True,
            "requires_rerun_ops_status": True,
            "requires_rerun_ops_summary": True,
            "requires_rerun_m1_go_no_go": True,
        },
        "redaction_boundary": {
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_ips_included": False,
            "dotenv_content_included": False,
            "server_paths_included": False,
        },
        "manual_fields_remaining": [
            "owner",
            "declarations[].owner_confirmed",
            "declarations[].evidence_ref",
            "declarations with <owner-confirmed-value-for-...>",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "record_id": "<postgres-redis-ops-declaration-YYYYMMDD>",
        "accepted_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "M1 PostgreSQL/Redis non-secret operations declarations",
        "owner": "<operations-owner-role>",
        "declarations": [
            {
                "env_var": "ZHIXING_POSTGRES_MODE",
                "accepted_value": "compose-postgresql single node for M1",
                "source_confidence": "suggested_from_live_probe",
                "execution_bucket": "can_prepare_from_live_probe",
                "owner_confirmed": True,
                "evidence_ref": "<private-live-probe-json>",
                "value_echoed": False,
            }
        ],
        "write_plan": {
            "target": "server_shared_env_or_secret_manager",
            "will_not_commit_to_git": True,
            "requires_rerun_ops_status": True,
            "requires_rerun_ops_summary": True,
            "requires_rerun_m1_go_no_go": True,
        },
        "redaction_boundary": {
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_ips_included": False,
            "dotenv_content_included": False,
            "server_paths_included": False,
        },
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", type=_path_arg, default=None, help="Private declaration request JSON.")
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private accepted declaration record JSON.")
    parser.add_argument("--draft-from-request", action="store_true", help="Build a private draft record from request JSON.")
    parser.add_argument("--template", action="store_true", help="Print a private accepted declaration record template.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report: Mapping[str, Any] = _template_record()
    elif args.draft_from_request:
        if args.request_json is None:
            report = {
                "version": POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [{"check": "input", "finding": "--request-json is required."}],
            }
        else:
            try:
                report = build_postgres_redis_ops_declaration_record_draft(
                    _read_json(args.request_json, label="request")
                )
            except ValueError as exc:
                report = {
                    "version": POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION,
                    "status": "blocked",
                    "blocked_reasons": [{"check": "input", "finding": str(exc)}],
                }
    else:
        if args.request_json is None or args.record_json is None:
            report = {
                "version": POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [
                    {"check": "input", "finding": "--request-json and --record-json are required."}
                ],
            }
        else:
            try:
                request = _read_json(args.request_json, label="request")
                raw_text = args.record_json.read_text(encoding="utf-8-sig")
                record = _read_json(args.record_json, label="record")
                report = build_postgres_redis_ops_declaration_record_report(
                    request=request,
                    record=record,
                    raw_text=raw_text,
                )
            except ValueError as exc:
                report = {
                    "version": POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION,
                    "status": "blocked",
                    "blocked_reasons": [{"check": "input", "finding": str(exc)}],
                }
    output_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
