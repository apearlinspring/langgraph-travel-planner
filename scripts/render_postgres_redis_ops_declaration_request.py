"""Render a redacted PostgreSQL/Redis operations declaration request.

The request is meant to help an operator fill non-secret stateful-service
declarations after live probes run. It never reads `.env`, never connects to
PostgreSQL or Redis, and never writes a server env file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION = "postgres_redis_ops_declaration_request.v1"
SAFE_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,100}$")


DECLARATION_SPECS: dict[str, dict[str, str]] = {
    "ZHIXING_POSTGRES_MODE": {
        "category": "service_mode",
        "purpose": "Declare whether PostgreSQL is single-node Compose or managed/HA.",
        "suggestion": "compose-postgresql single node for M1",
        "evidence_needed": "Live probe or managed database evidence.",
    },
    "ZHIXING_REDIS_MODE": {
        "category": "service_mode",
        "purpose": "Declare whether Redis is single-node Compose or managed/cluster.",
        "suggestion": "compose-redis single node for M1",
        "evidence_needed": "Live probe or managed Redis evidence.",
    },
    "ZHIXING_DATABASE_SECRET_STATUS": {
        "category": "secret_status",
        "purpose": "Declare that database credential storage and rotation ownership are ready.",
        "suggestion": "ready: stored in server shared env or secret manager, not committed",
        "evidence_needed": "Secret owner confirms real value is stored outside Git.",
    },
    "ZHIXING_REDIS_SECRET_STATUS": {
        "category": "secret_status",
        "purpose": "Declare that Redis credential storage and rotation ownership are ready.",
        "suggestion": "ready: stored in server shared env or secret manager if Redis auth is enabled",
        "evidence_needed": "Secret owner confirms Redis auth boundary.",
    },
    "ZHIXING_POSTGRES_BACKUP_STATUS": {
        "category": "backup_restore",
        "purpose": "Declare PostgreSQL backup freshness for M1.",
        "suggestion": "passed after backup evidence is collected",
        "evidence_needed": "Backup schedule/live probe or latest dump metadata.",
    },
    "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS": {
        "category": "backup_restore",
        "purpose": "Declare PostgreSQL restore drill or catalog-readiness status.",
        "suggestion": "passed only after restore drill or pg_restore catalog check",
        "evidence_needed": "Private restore drill record or pg_restore --list evidence.",
    },
    "ZHIXING_RPO_TARGET": {
        "category": "rpo_rto",
        "purpose": "Declare acceptable recovery point objective.",
        "suggestion": "24h for M1 controlled trial",
        "evidence_needed": "Owner accepts M1 data-loss window.",
    },
    "ZHIXING_RTO_TARGET": {
        "category": "rpo_rto",
        "purpose": "Declare recovery time objective.",
        "suggestion": "30min for M1 controlled trial",
        "evidence_needed": "Owner accepts recovery time target.",
    },
    "ZHIXING_POSTGRES_MIGRATION_POLICY": {
        "category": "migration",
        "purpose": "Declare database migration and rollback boundary.",
        "suggestion": "backup before migration, alembic migration, rollback plan",
        "evidence_needed": "Migration owner and rollback policy.",
    },
    "ZHIXING_POSTGRES_SLOW_QUERY_POLICY": {
        "category": "database_performance",
        "purpose": "Declare slow-query and timeout handling.",
        "suggestion": "statement timeout, slow query review and index review",
        "evidence_needed": "Owner confirms slow-query policy.",
    },
    "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS": {
        "category": "redis_lock",
        "purpose": "Bound Redis lock operation latency.",
        "suggestion": "0.5",
        "evidence_needed": "M1 latency budget accepts this timeout.",
    },
    "ZHIXING_REDIS_PERSISTENCE_STATUS": {
        "category": "redis_persistence",
        "purpose": "Declare Redis persistence mode.",
        "suggestion": "AOF appendonly ready",
        "evidence_needed": "Live probe confirms appendonly or managed Redis snapshot policy.",
    },
    "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS": {
        "category": "redis_network",
        "purpose": "Declare Redis public exposure boundary.",
        "suggestion": "private internal network, not exposed",
        "evidence_needed": "Live probe/security group/firewall evidence.",
    },
    "ZHIXING_REDIS_RECOVERY_STRATEGY": {
        "category": "redis_recovery",
        "purpose": "Declare Redis recovery strategy for locks/cache.",
        "suggestion": "restore from AOF/RDB snapshot or restart; active session loss accepted for M1 if documented",
        "evidence_needed": "Owner confirms Redis data-loss and session-lock impact.",
    },
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return str(value or "unknown").strip() or "unknown"


def _missing_env_vars(ops_status: Mapping[str, Any]) -> list[str]:
    env_vars: list[str] = []
    seen: set[str] = set()
    for item in _as_list(ops_status.get("blocked_reasons")):
        if not isinstance(item, Mapping):
            continue
        env_var = _safe_env_var_name(item.get("env_var"))
        if not env_var or env_var in seen:
            continue
        seen.add(env_var)
        env_vars.append(env_var)
    return env_vars


def _safe_env_var_name(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    candidate = raw.split("=", 1)[0].split(":", 1)[0].strip()
    if SAFE_ENV_NAME_PATTERN.fullmatch(candidate):
        return candidate
    return redact_text(raw)


def _live_signal(live_probe: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(live_probe, Mapping):
        return {
            "status": "not_checked",
            "postgres_live": "not_checked",
            "redis_live": "not_checked",
            "redis_appendonly": "not_checked",
            "postgres_public_bindings": None,
            "redis_public_bindings": None,
        }
    sections = _as_mapping(live_probe.get("sections"))
    postgres_container = _as_mapping(sections.get("postgres_container"))
    redis_container = _as_mapping(sections.get("redis_container"))
    postgres_ports = _as_mapping(postgres_container.get("ports"))
    redis_ports = _as_mapping(redis_container.get("ports"))
    declarations = _as_mapping(live_probe.get("declaration_statuses"))
    return {
        "status": _status(live_probe.get("status")),
        "postgres_live": _status(declarations.get("ZHIXING_POSTGRES_LIVE_STATUS")),
        "redis_live": _status(declarations.get("ZHIXING_REDIS_LIVE_STATUS")),
        "redis_appendonly": _status(_as_mapping(sections.get("redis_appendonly")).get("status")),
        "postgres_public_bindings": len(_as_list(postgres_ports.get("public_bindings"))),
        "redis_public_bindings": len(_as_list(redis_ports.get("public_bindings"))),
    }


def _confidence_for(env_var: str, live: Mapping[str, Any]) -> str:
    if env_var in {"ZHIXING_POSTGRES_MODE", "ZHIXING_REDIS_MODE"} and live.get("status") == "passed":
        return "suggested_from_live_probe"
    if env_var == "ZHIXING_REDIS_PERSISTENCE_STATUS" and live.get("redis_appendonly") == "passed":
        return "suggested_from_live_probe"
    if env_var == "ZHIXING_REDIS_PUBLIC_EXPOSURE_STATUS" and live.get("redis_public_bindings") == 0:
        return "suggested_from_live_probe"
    if env_var == "SESSION_LOCK_REDIS_OPERATION_TIMEOUT_SECONDS":
        return "safe_default_requires_owner_acceptance"
    return "requires_operator_confirmation"


def _execution_bucket_for(env_var: str, confidence: str) -> str:
    if env_var in {"ZHIXING_POSTGRES_BACKUP_STATUS", "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"}:
        return "requires_backup_or_restore_artifact"
    if confidence == "suggested_from_live_probe":
        return "can_prepare_from_live_probe"
    if confidence == "safe_default_requires_owner_acceptance":
        return "requires_owner_acceptance"
    return "requires_operator_confirmation"


def build_postgres_redis_ops_declaration_request(
    *,
    ops_status: Mapping[str, Any],
    live_probe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a redacted declaration request from status evidence."""

    missing_env_vars = _missing_env_vars(ops_status)
    live = _live_signal(live_probe)
    declarations = []
    for env_var in missing_env_vars:
        spec = DECLARATION_SPECS.get(
            env_var,
            {
                "category": "unknown",
                "purpose": "Missing PostgreSQL/Redis operations declaration.",
                "suggestion": "<set-after-operator-review>",
                "evidence_needed": "Operator review required.",
            },
        )
        confidence = _confidence_for(env_var, live)
        declarations.append(
            {
                "env_var": env_var,
                "category": spec["category"],
                "purpose": spec["purpose"],
                "suggested_value": spec["suggestion"],
                "evidence_needed": spec["evidence_needed"],
                "confidence": confidence,
                "execution_bucket": _execution_bucket_for(env_var, confidence),
                "secret_value": False,
                "value_echoed": False,
            }
        )

    status = "passed" if not declarations else "blocked"
    report = {
        "version": POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "connects_ssh": False,
            "writes_server_env": False,
            "echoes_secret_values": False,
            "safe_to_commit": False,
        },
        "source_status": {
            "ops_status": _status(ops_status.get("status")),
            "live_probe": live,
        },
        "missing_count": len(declarations),
        "suggested_from_live_probe_count": sum(
            1 for item in declarations if item["confidence"] == "suggested_from_live_probe"
        ),
        "requires_operator_confirmation_count": sum(
            1 for item in declarations if item["confidence"] == "requires_operator_confirmation"
        ),
        "execution_bucket_counts": {
            bucket: sum(1 for item in declarations if item["execution_bucket"] == bucket)
            for bucket in sorted({item["execution_bucket"] for item in declarations})
        },
        "declarations": declarations,
        "server_env_template_lines": [
            f"{item['env_var']}={item['suggested_value']}"
            for item in declarations
        ],
        "operator_steps": [
            "Review each suggested declaration against private operational evidence.",
            "Write accepted declarations to the server shared .env or secret manager only.",
            "Do not paste real secret values into Git, docs, chat, or this request file.",
            "Rerun docker compose exec -T backend python scripts/check_postgres_redis_ops_status.py --json.",
            "Regenerate postgres-redis-ops-summary and M1 go/no-go after declarations are present.",
        ],
        "not_proven_by_this_request": [
            "The declarations have been written to the server.",
            "PostgreSQL backup or restore drill has passed.",
            "Redis recovery impact has been accepted by the owner.",
            "Managed HA, PITR, multi-AZ failover, or long-duration stability.",
        ],
    }
    safe_report = redact_data(report)
    return safe_report if isinstance(safe_report, dict) else report


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_postgres_redis_ops_declaration_request_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL / Redis Ops Declaration Request",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Missing declarations: `{_markdown_cell(report.get('missing_count'))}`",
        f"- Suggested from live probe: `{_markdown_cell(report.get('suggested_from_live_probe_count'))}`",
        "- Policy: no `.env`, no database rows, no Redis keys, no SSH, no server env writes.",
        "",
        "## Execution Buckets",
        "",
    ]
    bucket_counts = _as_mapping(report.get("execution_bucket_counts"))
    if bucket_counts:
        for bucket, count in bucket_counts.items():
            lines.append(f"- `{_markdown_cell(bucket)}`: `{_markdown_cell(count)}`")
    else:
        lines.append("- No missing declarations.")
    lines.extend(
        [
            "",
            "## Missing Declarations",
            "",
            "| Env Var | Category | Suggested Value | Confidence | Bucket | Evidence Needed |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in _as_list(report.get("declarations")):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"{_markdown_cell(item.get('category'))} | "
            f"`{_markdown_cell(item.get('suggested_value'))}` | "
            f"{_markdown_cell(item.get('confidence'))} | "
            f"{_markdown_cell(item.get('execution_bucket'))} | "
            f"{_markdown_cell(item.get('evidence_needed'))} |"
        )
    lines.extend(["", "## Server Env Template Lines", ""])
    for item in _as_list(report.get("server_env_template_lines")):
        lines.append(f"```text\n{_markdown_cell(item)}\n```")
    lines.extend(["", "## Operator Steps", ""])
    for item in _as_list(report.get("operator_steps")):
        lines.append(f"- {_markdown_cell(item)}")
    lines.extend(["", "## Boundary", ""])
    for item in _as_list(report.get("not_proven_by_this_request")):
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} JSON could not be read or parsed.") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} JSON must be an object.")
    return payload


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops-status-json", type=_path_arg, required=True)
    parser.add_argument("--live-probe-json", type=_path_arg, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        ops_status = _read_json(args.ops_status_json, label="ops_status")
        live_probe = _read_json(args.live_probe_json, label="live_probe") if args.live_probe_json else None
        report = build_postgres_redis_ops_declaration_request(
            ops_status=ops_status,
            live_probe=live_probe,
        )
    except ValueError as exc:
        report = {
            "version": POSTGRES_REDIS_OPS_DECLARATION_REQUEST_VERSION,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "connects_database": False,
                "connects_redis": False,
                "connects_ssh": False,
                "writes_server_env": False,
            },
            "blocked_reasons": [{"key": "input_json", "finding": str(exc), "value_echoed": False}],
        }
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_postgres_redis_ops_declaration_request_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + ("\n" if not output_text.endswith("\n") else ""), encoding="utf-8")
    else:
        print(output_text, end="" if output_text.endswith("\n") else "\n")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
