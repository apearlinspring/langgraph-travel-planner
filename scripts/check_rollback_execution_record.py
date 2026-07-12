"""Validate a redacted real rollback execution record for M1 operations."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
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

from scripts._evidence_record_helpers import (  # noqa: E402
    READY_VALUES,
    as_list as _as_list,
    as_mapping as _as_mapping,
    has_text as _has_text,
    is_ready as _is_ready,
    make_final_text_checker,
    make_json_object_reader,
    make_path_arg,
    make_placeholder_checker,
    status_from_checks as _status_from_checks,
)


ROLLBACK_EXECUTION_RECORD_VERSION = "rollback_execution_record.v1"
VALID_MODES = {"real_rollback"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy-", "release id", "owner role", "previous release", "backup id")
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
)


_path_arg = make_path_arg(PROJECT_ROOT)
_read_json = make_json_object_reader(
    object_error="Rollback execution record must be a JSON object.",
    encoding="utf-8",
)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=PLACEHOLDER_FRAGMENTS,
)
_has_final_text = make_final_text_checker(_looks_placeholder)


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "window_id",
        "mode",
        "started_at",
        "ended_at",
        "rollback_reason",
        "source_release",
        "target_release",
    )
    missing = [field for field in required if not _has_final_text(record.get(field))]
    mode = str(record.get("mode") or "").strip()
    if mode not in VALID_MODES:
        missing.append("mode")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "mode": mode if mode in VALID_MODES else "unknown",
        "finding": "Required rollback execution fields are present."
        if not missing
        else "Required rollback execution fields are missing.",
        "value_echoed": False,
    }


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = _as_mapping(record.get("owners"))
    required = ("rollback_owner", "incident_owner", "verifier", "communications_owner")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "finding": "Required rollback roles are assigned."
        if not missing
        else "Required rollback roles are missing.",
        "value_echoed": False,
    }


def _execution_check(record: Mapping[str, Any]) -> dict[str, Any]:
    execution = _as_mapping(record.get("execution"))
    required_true = (
        "version_switch_executed",
        "service_restart_executed",
        "rollback_target_verified_before_switch",
        "release_pointer_verified_after_switch",
    )
    required_false = ("used_git_reset_hard", "used_bulk_delete", "changed_database_schema")
    missing_true = [field for field in required_true if not _is_ready(execution.get(field))]
    unsafe_true = [field for field in required_false if execution.get(field) is not False]
    commands = [item for item in _as_list(execution.get("commands")) if isinstance(item, Mapping)]
    command_phases = {str(item.get("phase") or "").strip().lower() for item in commands}
    missing_phases = sorted({"precheck", "switch", "restart", "verify"} - command_phases)
    blocked = []
    if missing_true:
        blocked.append({"field": "execution", "missing_ready": missing_true, "finding": "Required execution confirmations are missing."})
    if unsafe_true:
        blocked.append({"field": "execution", "unsafe_fields": unsafe_true, "finding": "Unsafe execution flags must be false."})
    if missing_phases:
        blocked.append({"field": "execution.commands", "missing_phases": missing_phases, "finding": "Rollback command phases are incomplete."})
    return {
        "status": "blocked" if blocked else "passed",
        "command_count": len(commands),
        "blocked_reasons": blocked,
        "finding": "Rollback execution steps are recorded."
        if not blocked
        else "Rollback execution record is incomplete or unsafe.",
        "value_echoed": False,
    }


def _data_safety_check(record: Mapping[str, Any]) -> dict[str, Any]:
    safety = _as_mapping(record.get("data_safety"))
    required_true = (
        "dotenv_untouched",
        "postgres_volume_untouched",
        "redis_volume_untouched",
        "vectorstore_untouched",
        "logs_untouched",
        "backup_verified_before_switch",
        "no_runtime_data_uploaded_from_local",
    )
    missing = [field for field in required_true if not _is_ready(safety.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Runtime data safety boundary is recorded."
        if not missing
        else "Runtime data safety boundary is incomplete.",
        "value_echoed": False,
    }


def _health_check(record: Mapping[str, Any]) -> dict[str, Any]:
    health = _as_mapping(record.get("post_rollback_health"))
    required = ("live_status", "ready_status", "compose_status")
    missing = [field for field in required if not _is_ready(health.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Post-rollback health checks passed."
        if not missing
        else "Post-rollback health checks are incomplete.",
        "value_echoed": False,
    }


def _smoke_check(record: Mapping[str, Any]) -> dict[str, Any]:
    smoke = _as_mapping(record.get("post_rollback_smoke"))
    required = ("m1_gate_status", "mock_checkout_boundary_status")
    missing = [field for field in required if not _is_ready(smoke.get(field))]
    acceptance = str(smoke.get("acceptance_smoke_status") or "").strip().lower()
    acceptance_reason_present = _has_text(smoke.get("acceptance_smoke_reason"))
    if acceptance and acceptance not in READY_VALUES and acceptance not in {"not_applicable", "not applicable", "skipped"}:
        missing.append("acceptance_smoke_status")
    if acceptance in {"not_applicable", "not applicable", "skipped"} and not acceptance_reason_present:
        missing.append("acceptance_smoke_reason")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "acceptance_smoke_recorded": bool(acceptance),
        "finding": "Post-rollback smoke checks passed or are explicitly scoped."
        if not missing
        else "Post-rollback smoke checks are incomplete.",
        "value_echoed": False,
    }


def _communication_check(record: Mapping[str, Any]) -> dict[str, Any]:
    communication = _as_mapping(record.get("communication"))
    required_true = ("stakeholders_updated", "rollback_window_closed", "remaining_risks_recorded")
    missing = [field for field in required_true if not _is_ready(communication.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Rollback communication closure is recorded."
        if not missing
        else "Rollback communication closure is incomplete.",
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
            blocked.append(
                {
                    "field": "record_text",
                    "finding": "Record contains a secret-looking value pattern.",
                }
            )
            break
    return {
        "status": "blocked" if blocked else "passed",
        "blocked_reasons": blocked,
        "finding": "Record declares no raw logs, screenshots, PII or secret values."
        if not blocked
        else "Record redaction boundary is incomplete.",
        "record_text_echoed": False,
    }


def build_rollback_execution_record_report(record: Mapping[str, Any], *, raw_text: str = "") -> dict[str, Any]:
    """Build a redacted validation report for one real rollback execution record."""

    checks = {
        "required_fields": _required_fields_check(record),
        "owners": _owners_check(record),
        "execution": _execution_check(record),
        "data_safety": _data_safety_check(record),
        "post_rollback_health": _health_check(record),
        "post_rollback_smoke": _smoke_check(record),
        "communication": _communication_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    return {
        "version": ROLLBACK_EXECUTION_RECORD_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "executes_rollback": False,
            "starts_services": False,
            "deletes_files": False,
            "record_text_echoed": False,
            "raw_logs_allowed": False,
            "screenshots_allowed": False,
        },
        "record_summary": {
            "window_id_present": _has_text(record.get("window_id")),
            "mode": checks["required_fields"].get("mode"),
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "command_count": checks["execution"].get("command_count"),
            "acceptance_smoke_recorded": checks["post_rollback_smoke"].get("acceptance_smoke_recorded"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_ROLLBACK_DRILL_STATUS": "passed"
            if checks["required_fields"]["status"] == "passed" and checks["execution"]["status"] == "passed"
            else "blocked",
            "ZHIXING_ROLLBACK_TARGET_STATUS": "passed"
            if checks["required_fields"]["status"] == "passed" and checks["execution"]["status"] == "passed"
            else "blocked",
            "ZHIXING_POST_ROLLBACK_HEALTH_STATUS": "passed"
            if checks["post_rollback_health"]["status"] == "passed"
            else "blocked",
            "ZHIXING_POST_ROLLBACK_SMOKE_STATUS": "passed"
            if checks["post_rollback_smoke"]["status"] == "passed"
            else "blocked",
            "ZHIXING_ROLLBACK_DATA_SAFETY_STATUS": "passed"
            if checks["data_safety"]["status"] == "passed" and checks["redaction_boundary"]["status"] == "passed"
            else "blocked",
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided rollback execution record; it does not execute rollback itself.",
            "Raw commands may be summarized by phase, but raw logs, screenshots, tickets and secret values must stay outside Git.",
            "A passed record proves M1 rollback-window evidence, not long-term HA, automatic failover or disaster recovery.",
            "A passed M1 mock checkout boundary still does not permit real payment, booking, price lock, ticketing or fulfillment.",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "window_id": "<m1-real-rollback-YYYYMMDD>",
        "mode": "real_rollback",
        "started_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "ended_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "rollback_reason": "<controlled rollback drill or release regression>",
        "source_release": "<release id before rollback>",
        "target_release": "<previous release id or backup id>",
        "owners": {
            "rollback_owner": "<release owner role>",
            "incident_owner": "<incident owner role>",
            "verifier": "<post-rollback verifier role>",
            "communications_owner": "<communication owner role>",
        },
        "execution": {
            "version_switch_executed": "passed",
            "service_restart_executed": "passed",
            "rollback_target_verified_before_switch": "passed",
            "release_pointer_verified_after_switch": "passed",
            "used_git_reset_hard": False,
            "used_bulk_delete": False,
            "changed_database_schema": False,
            "commands": [
                {"phase": "precheck", "summary": "verify target release and backup boundary"},
                {"phase": "switch", "summary": "switch code release pointer or restore approved code backup"},
                {"phase": "restart", "summary": "restart backend/caddy without recreating data volumes"},
                {"phase": "verify", "summary": "run health, smoke and demo-only checkout boundary checks"},
            ],
        },
        "data_safety": {
            "dotenv_untouched": "passed",
            "postgres_volume_untouched": "passed",
            "redis_volume_untouched": "passed",
            "vectorstore_untouched": "passed",
            "logs_untouched": "passed",
            "backup_verified_before_switch": "passed",
            "no_runtime_data_uploaded_from_local": "passed",
        },
        "post_rollback_health": {
            "live_status": "passed",
            "ready_status": "passed",
            "compose_status": "passed",
        },
        "post_rollback_smoke": {
            "m1_gate_status": "passed",
            "mock_checkout_boundary_status": "passed",
            "acceptance_smoke_status": "not_applicable",
            "acceptance_smoke_reason": "M1 rollback drill scoped to health, gate and demo-only checkout boundary.",
        },
        "communication": {
            "stakeholders_updated": "passed",
            "rollback_window_closed": "passed",
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
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private rollback execution JSON record.")
    parser.add_argument("--template", action="store_true", help="Print a private-record template.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report = _template_record()
    else:
        if args.record_json is None:
            raise SystemExit("--record-json is required unless --template is used")
        raw_text = args.record_json.read_text(encoding="utf-8")
        report = build_rollback_execution_record_report(_read_json(args.record_json), raw_text=raw_text)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print("wrote output")
    else:
        print(text)
    return 2 if isinstance(report, Mapping) and report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
