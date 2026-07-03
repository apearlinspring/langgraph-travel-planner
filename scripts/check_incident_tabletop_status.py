"""Validate a redacted incident tabletop drill record for M1 operations."""
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
INCIDENT_TABLETOP_STATUS_VERSION = "incident_tabletop_status.v1"
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
VALID_SEVERITIES = {"P0", "P1", "P2", "P3"}
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
)


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("Incident tabletop record must be a JSON object.")
    return payload


def _is_ready(value: Any) -> bool:
    return str(value or "").strip().lower() in READY_VALUES


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = record.get("redaction_boundary") or {}
    if not isinstance(boundary, Mapping):
        boundary = {}
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


def _required_text_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "drill_id",
        "scenario",
        "started_at",
        "detected_by",
        "customer_impact",
        "rollback_decision",
    )
    missing = [field for field in required if not _has_text(record.get(field))]
    severity = str(record.get("severity") or "").strip().upper()
    if severity not in VALID_SEVERITIES:
        missing.append("severity")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "severity": severity if severity in VALID_SEVERITIES else "unknown",
        "finding": "Required incident scenario fields are present."
        if not missing
        else "Required incident scenario fields are missing.",
        "value_echoed": False,
    }


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = record.get("owners") or {}
    if not isinstance(owners, Mapping):
        owners = {}
    required = ("incident_commander", "rollback_owner", "communications_owner", "scribe")
    missing = [field for field in required if not _has_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "finding": "Required incident roles are assigned."
        if not missing
        else "Required incident roles are missing.",
        "value_echoed": False,
    }


def _timeline_check(record: Mapping[str, Any]) -> dict[str, Any]:
    events = [item for item in _as_list(record.get("timeline")) if isinstance(item, Mapping)]
    phases = {str(item.get("phase") or "").strip().lower() for item in events}
    required_phases = {"detect", "triage", "mitigate", "validate", "communicate"}
    missing = sorted(required_phases - phases)
    incomplete = [
        index
        for index, item in enumerate(events)
        if not _has_text(item.get("action")) or not _has_text(item.get("owner_role"))
    ]
    blocked = []
    if missing:
        blocked.append({"field": "timeline.phase", "missing": missing, "finding": "Required incident phases are missing."})
    if incomplete:
        blocked.append({"field": "timeline", "missing_indexes": incomplete, "finding": "Timeline events require action and owner_role."})
    return {
        "status": "blocked" if blocked else "passed",
        "event_count": len(events),
        "phase_count": len(phases),
        "blocked_reasons": blocked,
        "finding": "Timeline covers detection, triage, mitigation, validation and communication."
        if not blocked
        else "Timeline is incomplete.",
        "value_echoed": False,
    }


def _response_check(record: Mapping[str, Any]) -> dict[str, Any]:
    actions = [item for item in _as_list(record.get("response_actions")) if isinstance(item, Mapping)]
    completed = [item for item in actions if _is_ready(item.get("status"))]
    if len(completed) < 3:
        return {
            "status": "blocked",
            "action_count": len(actions),
            "completed_action_count": len(completed),
            "blocked_reasons": [{"field": "response_actions", "finding": "At least three response actions must be completed."}],
            "finding": "Incident response actions are incomplete.",
            "value_echoed": False,
        }
    return {
        "status": "passed",
        "action_count": len(actions),
        "completed_action_count": len(completed),
        "finding": "Incident response actions are completed.",
        "value_echoed": False,
    }


def _communication_check(record: Mapping[str, Any]) -> dict[str, Any]:
    communication = record.get("communication") or {}
    if not isinstance(communication, Mapping):
        communication = {}
    channels = _as_list(communication.get("channels"))
    blocked = []
    if not channels:
        blocked.append({"field": "communication.channels", "finding": "At least one communication channel is required."})
    if not _has_text(communication.get("cadence")):
        blocked.append({"field": "communication.cadence", "finding": "Communication cadence is required."})
    if not _has_text(communication.get("holding_statement")):
        blocked.append({"field": "communication.holding_statement", "finding": "A holding statement is required."})
    return {
        "status": "blocked" if blocked else "passed",
        "channel_count": len(channels),
        "has_cadence": _has_text(communication.get("cadence")),
        "has_holding_statement": _has_text(communication.get("holding_statement")),
        "blocked_reasons": blocked,
        "finding": "Incident communication plan is recorded."
        if not blocked
        else "Incident communication plan is incomplete.",
        "value_echoed": False,
    }


def _review_check(record: Mapping[str, Any]) -> dict[str, Any]:
    review = record.get("review") or {}
    if not isinstance(review, Mapping):
        review = {}
    required = ("root_cause_hypothesis", "impact_summary", "what_went_well", "gaps", "remaining_risks")
    missing = [field for field in required if not review.get(field)]
    followups = [item for item in _as_list(review.get("follow_up_items")) if isinstance(item, Mapping)]
    incomplete_followups = [
        index
        for index, item in enumerate(followups)
        if not _has_text(item.get("action")) or not _has_text(item.get("owner_role")) or not _has_text(item.get("due_by"))
    ]
    blocked = []
    if missing:
        blocked.append({"field": "review", "missing": missing, "finding": "Review summary fields are missing."})
    if not followups:
        blocked.append({"field": "review.follow_up_items", "finding": "At least one follow-up item is required."})
    if incomplete_followups:
        blocked.append({"field": "review.follow_up_items", "missing_indexes": incomplete_followups, "finding": "Follow-ups need action, owner_role and due_by."})
    return {
        "status": "blocked" if blocked else "passed",
        "follow_up_count": len(followups),
        "blocked_reasons": blocked,
        "finding": "Incident review and follow-up items are recorded."
        if not blocked
        else "Incident review is incomplete.",
        "value_echoed": False,
    }


def _severity_policy_check(record: Mapping[str, Any]) -> dict[str, Any]:
    severity_policy = record.get("severity_policy") or {}
    if not isinstance(severity_policy, Mapping):
        severity_policy = {}
    required = ("severity_matrix_used", "escalation_owner_declared", "trial_pause_rule_checked")
    missing = [field for field in required if not _is_ready(severity_policy.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Severity policy and escalation boundary are checked."
        if not missing
        else "Severity policy check is incomplete.",
        "value_echoed": False,
    }


def _status_from_checks(checks: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    blockers = []
    for name, check in checks.items():
        if check.get("status") != "blocked":
            continue
        for item in check.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                blockers.append({"check": name, **dict(item)})
        if not check.get("blocked_reasons"):
            blockers.append({"check": name, "finding": check.get("finding") or "blocked"})
    return ("blocked" if blockers else "passed", blockers)


def build_incident_tabletop_status_report(record: Mapping[str, Any], *, raw_text: str = "") -> dict[str, Any]:
    """Build a redacted validation report for one incident tabletop record."""

    checks = {
        "required_fields": _required_text_check(record),
        "owners": _owners_check(record),
        "timeline": _timeline_check(record),
        "response_actions": _response_check(record),
        "communication": _communication_check(record),
        "review": _review_check(record),
        "severity_policy": _severity_policy_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    return {
        "version": INCIDENT_TABLETOP_STATUS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "executes_rollback": False,
            "starts_services": False,
            "sends_notifications": False,
            "record_text_echoed": False,
            "raw_logs_allowed": False,
            "screenshots_allowed": False,
        },
        "record_summary": {
            "drill_id_present": _has_text(record.get("drill_id")),
            "scenario_present": _has_text(record.get("scenario")),
            "severity": checks["required_fields"].get("severity"),
            "timeline_event_count": checks["timeline"].get("event_count"),
            "response_action_count": checks["response_actions"].get("action_count"),
            "follow_up_count": checks["review"].get("follow_up_count"),
            "communication_channel_count": checks["communication"].get("channel_count"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_INCIDENT_RESPONSE_STATUS": "passed" if checks["response_actions"]["status"] == "passed" and checks["timeline"]["status"] == "passed" else "blocked",
            "ZHIXING_INCIDENT_REVIEW_STATUS": "passed" if checks["review"]["status"] == "passed" else "blocked",
            "ZHIXING_INCIDENT_SEVERITY_POLICY_STATUS": "passed" if checks["severity_policy"]["status"] == "passed" else "blocked",
            "ZHIXING_INCIDENT_COMMUNICATION_STATUS": "passed" if checks["communication"]["status"] == "passed" else "blocked",
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates a tabletop drill record; it is not evidence of a real production incident.",
            "The script does not send notifications, execute rollback, restart services, or read raw logs.",
            "Raw tickets, logs, screenshots and chat transcripts must stay outside Git.",
            "A passed tabletop drill does not replace a real rollback drill or post-rollback smoke.",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "drill_id": "m1-tabletop-YYYYMMDD",
        "scenario": "health/readiness alert indicates M1 backend degradation",
        "severity": "P1",
        "started_at": "YYYY-MM-DDTHH:MM:SS+08:00",
        "detected_by": "health/readiness alert drill",
        "customer_impact": "M1 controlled-trial users may see degraded planning responses; no real payment or booking impact.",
        "rollback_decision": "evaluate rollback after health, logs and current release check",
        "owners": {
            "incident_commander": "ops role",
            "rollback_owner": "release owner role",
            "communications_owner": "communication owner role",
            "scribe": "record keeper role",
        },
        "timeline": [
            {"phase": "detect", "minute": 0, "owner_role": "incident_commander", "action": "acknowledge alert"},
            {"phase": "triage", "minute": 5, "owner_role": "release owner", "action": "check health and latest release"},
            {"phase": "mitigate", "minute": 15, "owner_role": "release owner", "action": "prepare rollback or config fix"},
            {"phase": "validate", "minute": 25, "owner_role": "incident_commander", "action": "rerun health and M1 smoke"},
            {"phase": "communicate", "minute": 30, "owner_role": "communications_owner", "action": "send status update"},
        ],
        "response_actions": [
            {"action": "pause M1 trial traffic if health is blocked", "owner_role": "incident_commander", "status": "passed"},
            {"action": "verify rollback backup and release archive", "owner_role": "rollback_owner", "status": "passed"},
            {"action": "rerun health/readiness after mitigation", "owner_role": "incident_commander", "status": "passed"},
        ],
        "communication": {
            "channels": ["internal ops note"],
            "cadence": "initial update within 15 minutes, follow-up every 30 minutes for P1",
            "holding_statement": "M1 trial is degraded; no real payment, booking, inventory lock or fulfillment is affected.",
        },
        "review": {
            "root_cause_hypothesis": "release/config/external dependency degradation, to be confirmed by evidence",
            "impact_summary": "M1 controlled-trial traffic only; no real transaction impact",
            "what_went_well": ["health endpoint and rollback material can be checked quickly"],
            "gaps": ["real rollback window still not executed"],
            "remaining_risks": ["post-rollback smoke remains pending until a real rollback drill"],
            "follow_up_items": [
                {"action": "schedule real rollback window", "owner_role": "release owner", "due_by": "YYYY-MM-DD"}
            ],
        },
        "severity_policy": {
            "severity_matrix_used": "passed",
            "escalation_owner_declared": "passed",
            "trial_pause_rule_checked": "passed",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
        },
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private tabletop drill JSON record.")
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
        report = build_incident_tabletop_status_report(_read_json(args.record_json), raw_text=raw_text)
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
