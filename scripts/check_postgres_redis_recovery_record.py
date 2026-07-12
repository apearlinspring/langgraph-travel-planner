"""Validate a private PostgreSQL/Redis recovery or drill record.

The checker validates an operator-provided record for M1 stateful-service
recovery. It does not read `.env`, connect to PostgreSQL, connect to Redis,
connect SSH, start services, restart containers, delete files or print private
values.
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._evidence_record_helpers import (  # noqa: E402
    as_list as _as_list,
    as_mapping as _as_mapping,
    blocker as _blocker,
    has_text as _has_text,
    is_ready as _is_ready,
    make_final_text_checker,
    make_json_object_reader,
    make_path_arg,
    make_placeholder_checker,
    status_from_checks as _status_from_checks,
)


POSTGRES_REDIS_RECOVERY_RECORD_VERSION = "postgres_redis_recovery_record.v1"
VALID_MODES = {
    "postgres_restore_drill",
    "postgres_connection_failure_drill",
    "redis_restart_drill",
    "redis_unavailable_drill",
    "combined_stateful_recovery_drill",
}
VALID_SERVICES = {"postgres", "redis"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy-", "owner role", "record id", "drill id", "private")
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


_path_arg = make_path_arg(PROJECT_ROOT)
_read_json = make_json_object_reader(
    read_error="Cannot read PostgreSQL/Redis recovery record JSON: {path}",
    object_error="PostgreSQL/Redis recovery record must be a JSON object.",
)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=PLACEHOLDER_FRAGMENTS,
)
_has_final_text = make_final_text_checker(_looks_placeholder)


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = ("record_id", "mode", "started_at", "ended_at", "trigger", "scope")
    missing = [field for field in required if not _has_final_text(record.get(field))]
    mode = str(record.get("mode") or "").strip()
    if mode not in VALID_MODES:
        missing.append("mode")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": sorted(set(missing)),
        "mode": mode if mode in VALID_MODES else "unknown",
        "finding": "Required recovery record fields are present."
        if not missing
        else "Required recovery record fields are missing.",
        "value_echoed": False,
    }


def _service_scope_check(record: Mapping[str, Any]) -> dict[str, Any]:
    services = [str(item).strip().lower() for item in _as_list(record.get("affected_services"))]
    invalid = sorted(service for service in services if service not in VALID_SERVICES)
    missing = not services
    return {
        "status": "blocked" if missing or invalid else "passed",
        "affected_services": sorted(set(service for service in services if service in VALID_SERVICES)),
        "invalid_services": invalid,
        "finding": "Affected stateful services are recorded."
        if not missing and not invalid
        else "Affected services must include postgres and/or redis.",
        "value_echoed": False,
    }


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = _as_mapping(record.get("owners"))
    required = ("database_owner", "application_owner", "verifier", "communications_owner")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "finding": "Required recovery owner roles are assigned."
        if not missing
        else "Required recovery owner roles are missing.",
        "value_echoed": False,
    }


def _actions_check(record: Mapping[str, Any]) -> dict[str, Any]:
    actions = [item for item in _as_list(record.get("actions")) if isinstance(item, Mapping)]
    phases = {str(item.get("phase") or "").strip().lower() for item in actions}
    required_phases = {"detect", "isolate", "recover", "verify"}
    missing_phases = sorted(required_phases - phases)
    unsafe = []
    for item in actions:
        summary = str(item.get("summary") or "").lower()
        if any(token in summary for token in ("rm -rf", "docker volume rm", "drop database", "flushall", "truncate")):
            unsafe.append(str(item.get("phase") or "unknown"))
    blocked = []
    if missing_phases:
        blocked.append({"field": "actions", "missing_phases": missing_phases, "finding": "Recovery actions miss required phases."})
    if unsafe:
        blocked.append({"field": "actions", "unsafe_phases": unsafe, "finding": "Recovery actions contain unsafe destructive command summaries."})
    return {
        "status": "blocked" if blocked else "passed",
        "action_count": len(actions),
        "blocked_reasons": blocked,
        "finding": "Recovery action phases are recorded."
        if not blocked
        else "Recovery actions are incomplete or unsafe.",
        "value_echoed": False,
    }


def _data_safety_check(record: Mapping[str, Any]) -> dict[str, Any]:
    safety = _as_mapping(record.get("data_safety"))
    required_true = (
        "dotenv_untouched",
        "postgres_volume_untouched",
        "redis_volume_untouched",
        "vectorstore_untouched",
        "no_database_drop",
        "no_redis_flushall",
        "backup_point_checked",
    )
    missing = [field for field in required_true if not _is_ready(safety.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Stateful data safety boundary is recorded."
        if not missing
        else "Stateful data safety boundary is incomplete.",
        "value_echoed": False,
    }


def _health_check(record: Mapping[str, Any]) -> dict[str, Any]:
    health = _as_mapping(record.get("post_recovery_health"))
    required = ("backend_ready", "postgres_ready", "redis_ready", "m1_gate_status")
    missing = [field for field in required if not _is_ready(health.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Post-recovery health checks passed."
        if not missing
        else "Post-recovery health checks are incomplete.",
        "value_echoed": False,
    }


def _metrics_check(record: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _as_mapping(record.get("observed_metrics"))
    required = ("downtime_minutes", "data_loss_detected", "recovery_time_minutes")
    missing = [field for field in required if field not in metrics]
    blocked = []
    if missing:
        blocked.append({"field": "observed_metrics", "missing_fields": missing, "finding": "Required recovery metrics are missing."})
    if metrics.get("data_loss_detected") is not False:
        blocked.append({"field": "observed_metrics.data_loss_detected", "finding": "M1 recovery record must explicitly state no data loss was detected."})
    for field in ("downtime_minutes", "recovery_time_minutes"):
        if field not in metrics:
            continue
        try:
            value = float(metrics[field])
        except (TypeError, ValueError):
            blocked.append({"field": f"observed_metrics.{field}", "finding": "Recovery metric must be numeric."})
            continue
        if value < 0:
            blocked.append({"field": f"observed_metrics.{field}", "finding": "Recovery metric cannot be negative."})
    return {
        "status": "blocked" if blocked else "passed",
        "blocked_reasons": blocked,
        "finding": "Recovery metrics are recorded."
        if not blocked
        else "Recovery metrics are incomplete or unsafe.",
        "value_echoed": False,
    }


def _communication_check(record: Mapping[str, Any]) -> dict[str, Any]:
    communication = _as_mapping(record.get("communication"))
    required_true = ("stakeholders_updated", "incident_window_closed", "remaining_risks_recorded")
    missing = [field for field in required_true if not _is_ready(communication.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Recovery communication closure is recorded."
        if not missing
        else "Recovery communication closure is incomplete.",
        "value_echoed": False,
    }


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blocked = []
    for key in ("raw_logs_included", "screenshots_included", "customer_pii_included", "secret_values_included"):
        if boundary.get(key) is not False:
            blocked.append(
                {
                    "field": f"redaction_boundary.{key}",
                    "finding": "Redaction boundary must explicitly be false.",
                }
            )
    for pattern in SECRET_PATTERNS:
        if pattern.search(raw_text):
            blocked.append({"field": "record_text", "finding": "Record contains a secret-looking value pattern."})
            break
    if URL_PATTERN.search(raw_text):
        blocked.append({"field": "record_text", "finding": "Record contains a raw URL."})
    if IPV4_PATTERN.search(raw_text):
        blocked.append({"field": "record_text", "finding": "Record contains a raw IPv4 address."})
    return {
        "status": "blocked" if blocked else "passed",
        "blocked_reasons": blocked,
        "finding": "Record declares no raw logs, screenshots, PII or secret values."
        if not blocked
        else "Record redaction boundary is incomplete.",
        "record_text_echoed": False,
    }


def _service_declaration_status(status: str, affected_services: list[str], service: str) -> str:
    if service not in affected_services:
        return "not_applicable"
    return status


def build_postgres_redis_recovery_record_report(
    record: Mapping[str, Any],
    *,
    raw_text: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted validation report for a PostgreSQL/Redis recovery record."""

    checks = {
        "required_fields": _required_fields_check(record),
        "service_scope": _service_scope_check(record),
        "owners": _owners_check(record),
        "actions": _actions_check(record),
        "data_safety": _data_safety_check(record),
        "post_recovery_health": _health_check(record),
        "observed_metrics": _metrics_check(record),
        "communication": _communication_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    affected_services = checks["service_scope"].get("affected_services", [])
    now = generated_at or datetime.now(UTC)
    return {
        "version": POSTGRES_REDIS_RECOVERY_RECORD_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "connects_ssh": False,
            "starts_services": False,
            "restarts_services": False,
            "deletes_files": False,
            "record_text_echoed": False,
            "raw_logs_allowed": False,
            "screenshots_allowed": False,
        },
        "record_summary": {
            "record_id_present": _has_text(record.get("record_id")),
            "mode": checks["required_fields"].get("mode"),
            "affected_services": affected_services,
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "action_count": checks["actions"].get("action_count"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_POSTGRES_REDIS_RECOVERY_RECORD_STATUS": status,
            "ZHIXING_POSTGRES_RECOVERY_STATUS": _service_declaration_status(status, affected_services, "postgres"),
            "ZHIXING_REDIS_RECOVERY_STATUS": _service_declaration_status(status, affected_services, "redis"),
            "ZHIXING_STATEFUL_DATA_SAFETY_STATUS": "passed"
            if status == "passed" and checks["data_safety"]["status"] == "passed"
            else "blocked",
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided PostgreSQL/Redis recovery record; it does not execute recovery itself.",
            "A passed record proves M1 recovery evidence for the sampled incident or drill only.",
            "It does not prove managed HA, automatic failover, PITR, multi-AZ resilience or long-duration soak stability.",
            "Raw logs, screenshots, database dumps, Redis key dumps, .env files and secret values must stay outside Git.",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "record_id": "<postgres-redis-recovery-YYYYMMDD>",
        "mode": "combined_stateful_recovery_drill",
        "started_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "ended_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "trigger": "<controlled stateful service recovery drill>",
        "scope": "<M1 backend readiness and stateful dependency recovery>",
        "affected_services": ["postgres", "redis"],
        "owners": {
            "database_owner": "<database owner role>",
            "application_owner": "<application owner role>",
            "verifier": "<post-recovery verifier role>",
            "communications_owner": "<communication owner role>",
        },
        "actions": [
            {"phase": "detect", "summary": "confirm readiness degradation and affected service"},
            {"phase": "isolate", "summary": "stop traffic expansion and preserve stateful data boundary"},
            {"phase": "recover", "summary": "restart service or restore from approved backup/snapshot"},
            {"phase": "verify", "summary": "run health, M1 gate and PostgreSQL/Redis readiness checks"},
        ],
        "data_safety": {
            "dotenv_untouched": "passed",
            "postgres_volume_untouched": "passed",
            "redis_volume_untouched": "passed",
            "vectorstore_untouched": "passed",
            "no_database_drop": "passed",
            "no_redis_flushall": "passed",
            "backup_point_checked": "passed",
        },
        "post_recovery_health": {
            "backend_ready": "passed",
            "postgres_ready": "passed",
            "redis_ready": "passed",
            "m1_gate_status": "passed",
        },
        "observed_metrics": {
            "downtime_minutes": 0,
            "recovery_time_minutes": 0,
            "data_loss_detected": False,
        },
        "communication": {
            "stakeholders_updated": "passed",
            "incident_window_closed": "passed",
            "remaining_risks_recorded": "passed",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
        },
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private PostgreSQL/Redis recovery record.")
    parser.add_argument("--template", action="store_true", help="Print a private recovery-record template.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report: Mapping[str, Any] = _template_record()
    else:
        if args.record_json is None:
            report = {
                "version": POSTGRES_REDIS_RECOVERY_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [{"check": "input", "finding": "--record-json or --template is required."}],
            }
        else:
            try:
                raw_text = args.record_json.read_text(encoding="utf-8-sig")
                record = _read_json(args.record_json)
                report = build_postgres_redis_recovery_record_report(record, raw_text=raw_text)
            except ValueError as exc:
                report = {
                    "version": POSTGRES_REDIS_RECOVERY_RECORD_VERSION,
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
