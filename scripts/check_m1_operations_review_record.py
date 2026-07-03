"""Validate a private M1 operations review record.

The checker validates an operator-provided post-rollout operations review. It
does not read `.env`, connect SSH, query databases, read Redis keys, inspect
logs, call providers, restart services or print private values.
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
M1_OPERATIONS_REVIEW_RECORD_VERSION = "m1_operations_review_record.v1"
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
VALID_ENVIRONMENTS = {"staging", "production", "m1_controlled_trial"}
VALID_SEVERITIES = {"P0", "P1", "P2", "P3"}
VALID_ISSUE_STATUSES = {"resolved", "degraded_accepted", "monitoring", "backlog_accepted"}
VALID_FOLLOWUP_STATUSES = {"open", "in_progress", "done", "deferred"}
VALID_CATEGORIES = {
    "docker_disk",
    "postgres",
    "redis",
    "backup_restore",
    "rate_limit",
    "external_api",
    "live_chat",
    "rag",
    "security",
    "rollback",
    "frontend",
    "monitoring",
}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy-", "owner role", "review id", "rollout id", "private")
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
FORBIDDEN_EVIDENCE_PATH_PARTS = {".env", ".runtime", ".venv", "logs", "vectorstore", "vectorstore_internal"}


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read M1 operations review record JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("M1 operations review record must be a JSON object.")
    return payload


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _looks_placeholder(value: Any) -> bool:
    lowered = str(value or "").strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES) or any(
        fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS
    )


def _has_final_text(value: Any) -> bool:
    return _has_text(value) and not _looks_placeholder(value)


def _is_ready(value: Any) -> bool:
    return str(value or "").strip().lower() in READY_VALUES


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(check: str, field: str, finding: str) -> dict[str, str]:
    return {"check": check, "field": field, "finding": finding}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_forbidden_evidence_path(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_EVIDENCE_PATH_PARTS)


def _read_evidence_json(path: Path | None, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    status = {
        "label": label,
        "provided": path is not None,
        "path_echoed": False,
        "status": "not_provided",
    }
    if path is None:
        return {}, status
    resolved = path.resolve()
    if _is_relative_to(resolved, PROJECT_ROOT):
        status.update({"status": "blocked", "reason": "Evidence JSON must stay outside the Git workspace."})
        return {}, status
    if _is_forbidden_evidence_path(resolved):
        status.update({"status": "blocked", "reason": "Evidence JSON path points to a forbidden runtime or secret-like location."})
        return {}, status
    try:
        raw_text = resolved.read_text(encoding="utf-8-sig")
    except OSError:
        status.update({"status": "blocked", "reason": "Evidence JSON file cannot be read."})
        return {}, status
    if any(pattern.search(raw_text) for pattern in SECRET_PATTERNS) or URL_PATTERN.search(raw_text) or IPV4_PATTERN.search(raw_text):
        status.update({"status": "blocked", "reason": "Evidence JSON contains raw URL, IP or secret-looking text."})
        return {}, status
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        status.update({"status": "blocked", "reason": "Evidence JSON is not valid JSON."})
        return {}, status
    if not isinstance(payload, dict):
        status.update({"status": "blocked", "reason": "Evidence JSON must be an object."})
        return {}, status
    status["status"] = "passed"
    return payload, status


def _status_value(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in READY_VALUES:
        return "passed"
    if text in {"warning", "degraded", "blocked", "failed", "not_checked", "not_applicable"}:
        return text
    return "not_checked"


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = ("review_id", "rollout_id", "reviewed_at", "environment", "scope")
    missing = [field for field in required if not _has_final_text(record.get(field))]
    environment = str(record.get("environment") or "").strip()
    if environment not in VALID_ENVIRONMENTS:
        missing.append("environment")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": sorted(set(missing)),
        "environment": environment if environment in VALID_ENVIRONMENTS else "unknown",
        "value_echoed": False,
    }


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = _as_mapping(record.get("owners"))
    required = ("operations_owner", "application_owner", "database_owner", "verifier", "followup_owner")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "value_echoed": False,
    }


def _evidence_references_check(record: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _as_mapping(record.get("evidence_references"))
    required = (
        "rollout_execution_record",
        "go_no_go_record",
        "server_capacity_snapshot",
        "postgres_redis_ops",
        "backup_restore",
        "restore_drill_feasibility",
        "external_dependency_resilience",
        "concurrency_rate_limit",
        "disk_remediation_approval_gate",
        "incident_rollback",
    )
    optional = (
        "docker_build_cache_cleanup_approval_gate",
        "docker_build_cache_post_cleanup",
    )
    blockers = []

    def validate_item(key: str, *, required_item: bool) -> None:
        item = _as_mapping(evidence.get(key))
        if not item and not required_item:
            return
        status = str(item.get("status") or "").strip().lower()
        if status not in {"passed", "degraded", "warning", "not_applicable"}:
            blockers.append(_blocker("evidence_references", key, "Evidence reference status must be passed/degraded/warning/not_applicable."))
        if status in {"degraded", "warning", "not_applicable"} and not _has_final_text(item.get("reason")):
            blockers.append(_blocker("evidence_references", f"{key}.reason", "Non-passed evidence references must include a reason."))
        if item.get("raw_artifact_included") is not False:
            blockers.append(_blocker("evidence_references", f"{key}.raw_artifact_included", "Raw artifacts must not be embedded in the review record."))

    for key in required:
        validate_item(key, required_item=True)
    for key in optional:
        validate_item(key, required_item=False)
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "reference_count": len(required) + sum(1 for key in optional if key in evidence),
        "value_echoed": False,
    }


def _issue_review_check(record: Mapping[str, Any]) -> dict[str, Any]:
    issue_review = _as_mapping(record.get("issue_review"))
    blockers = []
    issues_observed = issue_review.get("issues_observed")
    if issues_observed is not True and issues_observed is not False:
        blockers.append(_blocker("issue_review", "issues_observed", "Issue observed flag must be true or false."))
    issues = [item for item in _as_list(issue_review.get("items")) if isinstance(item, Mapping)]
    if issues_observed is True and not issues:
        blockers.append(_blocker("issue_review", "items", "Observed operations issues must be recorded."))
    if issues_observed is False and not _has_final_text(issue_review.get("no_issue_summary")):
        blockers.append(_blocker("issue_review", "no_issue_summary", "No-issue review must still record a summary."))
    category_counts: dict[str, int] = {}
    for index, item in enumerate(issues):
        prefix = f"items[{index}]"
        category = str(item.get("category") or "").strip()
        category_counts[category] = category_counts.get(category, 0) + 1
        if category not in VALID_CATEGORIES:
            blockers.append(_blocker("issue_review", f"{prefix}.category", "Issue category is not recognized."))
        if str(item.get("severity") or "").strip() not in VALID_SEVERITIES:
            blockers.append(_blocker("issue_review", f"{prefix}.severity", "Issue severity must be P0/P1/P2/P3."))
        for field in ("signal", "impact", "root_cause", "action_taken", "verification", "owner"):
            if not _has_final_text(item.get(field)):
                blockers.append(_blocker("issue_review", f"{prefix}.{field}", "Issue item is incomplete."))
        status = str(item.get("status") or "").strip()
        if status not in VALID_ISSUE_STATUSES:
            blockers.append(_blocker("issue_review", f"{prefix}.status", "Issue status is not accepted."))
        if status != "resolved" and not _has_final_text(item.get("risk_acceptance")):
            blockers.append(_blocker("issue_review", f"{prefix}.risk_acceptance", "Unresolved or degraded issue needs risk acceptance."))
    if not _has_final_text(issue_review.get("lessons_learned")):
        blockers.append(_blocker("issue_review", "lessons_learned", "Operations lessons learned must be recorded."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "issue_count": len(issues),
        "issues_observed": issues_observed,
        "category_counts": category_counts,
        "value_echoed": False,
    }


def _lessons_check(record: Mapping[str, Any]) -> dict[str, Any]:
    lessons = _as_mapping(record.get("ops_lessons"))
    required = ("deployment", "docker_disk", "postgres", "redis", "backup_restore", "external_api", "rate_limit", "rollback")
    missing = [field for field in required if not _has_final_text(lessons.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "value_echoed": False,
    }


def _followups_check(record: Mapping[str, Any]) -> dict[str, Any]:
    followups = [item for item in _as_list(record.get("followups")) if isinstance(item, Mapping)]
    blockers = []
    if not followups:
        blockers.append(_blocker("followups", "followups", "At least one follow-up or explicit closure item must be recorded."))
    for index, item in enumerate(followups):
        prefix = f"followups[{index}]"
        for field in ("id", "owner", "priority", "due_by", "action", "status"):
            if not _has_final_text(item.get(field)):
                blockers.append(_blocker("followups", f"{prefix}.{field}", "Follow-up item is incomplete."))
        if str(item.get("status") or "").strip() not in VALID_FOLLOWUP_STATUSES:
            blockers.append(_blocker("followups", f"{prefix}.status", "Follow-up status is not recognized."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "followup_count": len(followups),
        "value_echoed": False,
    }


def _m1_boundary_check(record: Mapping[str, Any]) -> dict[str, Any]:
    boundary = _as_mapping(record.get("m1_boundary"))
    required_false = (
        "real_payment_enabled",
        "real_booking_enabled",
        "inventory_lock_enabled",
        "fulfillment_enabled",
        "claims_autoscaling_proven",
        "claims_multi_region_ha",
        "claims_long_duration_soak",
    )
    blockers = [
        _blocker("m1_boundary", key, f"M1 review must explicitly set {key}=false.")
        for key in required_false
        if boundary.get(key) is not False
    ]
    if not _has_final_text(boundary.get("residual_risk")):
        blockers.append(_blocker("m1_boundary", "residual_risk", "Residual risk must be recorded."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blocked = []
    for key in (
        "raw_logs_included",
        "screenshots_included",
        "customer_pii_included",
        "secret_values_included",
        "raw_urls_included",
        "raw_server_paths_included",
        "raw_provider_response_body_included",
    ):
        if boundary.get(key) is not False:
            blocked.append({"field": f"redaction_boundary.{key}", "finding": "Redaction boundary must explicitly be false."})
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
        "record_text_echoed": False,
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


def build_m1_operations_review_record_report(
    record: Mapping[str, Any],
    *,
    raw_text: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted validation report for one post-rollout operations review."""

    checks = {
        "required_fields": _required_fields_check(record),
        "owners": _owners_check(record),
        "evidence_references": _evidence_references_check(record),
        "issue_review": _issue_review_check(record),
        "ops_lessons": _lessons_check(record),
        "followups": _followups_check(record),
        "m1_boundary": _m1_boundary_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    now = generated_at or datetime.now(UTC)
    return {
        "version": M1_OPERATIONS_REVIEW_RECORD_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "queries_database": False,
            "reads_redis_keys": False,
            "reads_raw_logs": False,
            "calls_external_providers": False,
            "restarts_services": False,
            "record_text_echoed": False,
        },
        "record_summary": {
            "review_id_present": _has_text(record.get("review_id")),
            "environment": checks["required_fields"].get("environment"),
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "evidence_reference_count": checks["evidence_references"].get("reference_count"),
            "issue_count": checks["issue_review"].get("issue_count"),
            "issues_observed": checks["issue_review"].get("issues_observed"),
            "followup_count": checks["followups"].get("followup_count"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_M1_OPERATIONS_REVIEW_STATUS": status,
            "ZHIXING_M1_OPERATIONS_ISSUE_REVIEW_STATUS": checks["issue_review"]["status"],
            "ZHIXING_M1_OPERATIONS_FOLLOWUP_STATUS": checks["followups"]["status"],
            "ZHIXING_M1_OPERATIONS_BOUNDARY_STATUS": checks["m1_boundary"]["status"],
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided operations review; it does not inspect live infrastructure itself.",
            "A passed review does not prove autoscaling, multi-region HA, long-duration soak stability or real transaction fulfillment.",
            "Raw logs, screenshots, URLs, IP addresses, server paths, .env files and secret values must stay outside Git.",
        ],
    }


def _template_record() -> dict[str, Any]:
    evidence_item = {"status": "passed", "raw_artifact_included": False}
    return {
        "review_id": "<m1-ops-review-YYYYMMDD>",
        "rollout_id": "<m1-rollout-id>",
        "reviewed_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "environment": "m1_controlled_trial",
        "scope": "<post-rollout operations review>",
        "owners": {
            "operations_owner": "<operations owner role>",
            "application_owner": "<application owner role>",
            "database_owner": "<database owner role>",
            "verifier": "<verifier role>",
            "followup_owner": "<followup owner role>",
        },
        "evidence_references": {
            "rollout_execution_record": dict(evidence_item),
            "go_no_go_record": dict(evidence_item),
            "server_capacity_snapshot": dict(evidence_item),
            "postgres_redis_ops": dict(evidence_item),
            "backup_restore": dict(evidence_item),
            "external_dependency_resilience": dict(evidence_item),
            "concurrency_rate_limit": dict(evidence_item),
            "docker_build_cache_cleanup_approval_gate": dict(evidence_item),
            "docker_build_cache_post_cleanup": dict(evidence_item),
            "incident_rollback": dict(evidence_item),
        },
        "issue_review": {
            "issues_observed": True,
            "items": [
                {
                    "category": "docker_disk",
                    "severity": "P2",
                    "signal": "<disk guard warning during runtime image refresh>",
                    "impact": "<release kept conditional until capacity was verified>",
                    "root_cause": "<old image layers accumulated>",
                    "action_taken": "<collected cleanup plan and reran capacity check>",
                    "verification": "<server preflight and health checks passed after mitigation>",
                    "owner": "<operations owner role>",
                    "status": "resolved",
                }
            ],
            "lessons_learned": "<what changed after this rollout>",
        },
        "ops_lessons": {
            "deployment": "<release archive and rollout notes>",
            "docker_disk": "<disk guard, image cleanup and build cache cleanup lesson>",
            "postgres": "<backup, restore and migration lesson>",
            "redis": "<lock/rate-limit backend and fail-closed lesson>",
            "backup_restore": "<backup freshness and restore evidence lesson>",
            "external_api": "<timeout, degradation and cost guard lesson>",
            "rate_limit": "<low-risk concurrency and 429 validation lesson>",
            "rollback": "<rollback readiness and post-rollback smoke lesson>",
        },
        "followups": [
            {
                "id": "<OPS-001>",
                "owner": "<followup owner role>",
                "priority": "P2",
                "due_by": "<YYYY-MM-DD>",
                "action": "<capacity cleanup or monitoring hardening action>",
                "status": "open",
            }
        ],
        "m1_boundary": {
            "real_payment_enabled": False,
            "real_booking_enabled": False,
            "inventory_lock_enabled": False,
            "fulfillment_enabled": False,
            "claims_autoscaling_proven": False,
            "claims_multi_region_ha": False,
            "claims_long_duration_soak": False,
            "residual_risk": "<M1 remains controlled trial, not full production HA>",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_server_paths_included": False,
            "raw_provider_response_body_included": False,
        },
    }


def _section_status(report: Mapping[str, Any], *keys: str) -> str:
    candidates = [
        _as_mapping(report.get("section_statuses")),
        _as_mapping(_as_mapping(report.get("go_no_go")).get("section_statuses")),
        _as_mapping(_as_mapping(report.get("sections")).get("section_statuses")),
    ]
    for statuses in candidates:
        for key in keys:
            if key in statuses:
                return _status_value(statuses.get(key))
    return "not_checked"


def _best_status(*statuses: str) -> str:
    normalized = [_status_value(status) for status in statuses]
    if any(status in {"blocked", "failed"} for status in normalized):
        return "blocked"
    if "degraded" in normalized:
        return "degraded"
    if "warning" in normalized:
        return "warning"
    if "passed" in normalized:
        return "passed"
    if normalized and all(status == "not_applicable" for status in normalized):
        return "not_applicable"
    return "not_checked"


def _evidence_item_from_status(status: Any, *, reason: str) -> dict[str, Any]:
    normalized = _status_value(status)
    if normalized == "passed":
        return {"status": "passed", "raw_artifact_included": False}
    if normalized in {"degraded", "warning"}:
        return {"status": normalized, "reason": reason, "raw_artifact_included": False}
    if normalized in {"blocked", "failed"}:
        return {"status": "degraded", "reason": reason, "raw_artifact_included": False}
    return {
        "status": "not_applicable",
        "reason": reason,
        "raw_artifact_included": False,
    }


def _report_status_item(label: str, report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": label,
        "status": _status_value(report.get("status")),
        "value_echoed": False,
    }


def _issue_category_for_evidence(key: str) -> str:
    if key == "postgres_redis_ops":
        return "postgres"
    if key == "backup_restore":
        return "backup_restore"
    if key == "restore_drill_feasibility":
        return "backup_restore"
    if key == "external_dependency_resilience":
        return "external_api"
    if key == "concurrency_rate_limit":
        return "rate_limit"
    if key == "disk_remediation_approval_gate":
        return "docker_disk"
    if key == "docker_build_cache_cleanup_approval_gate":
        return "docker_disk"
    if key == "docker_build_cache_post_cleanup":
        return "docker_disk"
    if key == "incident_rollback":
        return "rollback"
    return "monitoring"


def build_m1_operations_review_record_draft(
    *,
    rollout_report: Mapping[str, Any] | None = None,
    go_no_go_report: Mapping[str, Any] | None = None,
    external_dependency_report: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
    source_statuses: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a private operations review draft from redacted evidence reports."""

    record = _template_record()
    now = generated_at or datetime.now(UTC)
    rollout = _as_mapping(rollout_report or {})
    go_no_go = _as_mapping(go_no_go_report or {})
    external_dependency = _as_mapping(external_dependency_report or {})

    rollout_status = _status_value(rollout.get("status"))
    go_no_go_status = _status_value(go_no_go.get("status"))
    external_dependency_status = _status_value(external_dependency.get("status"))
    evidence = {
        "rollout_execution_record": _evidence_item_from_status(
            rollout_status,
            reason="M1 rollout execution report was not passed; review the private rollout record before signoff.",
        ),
        "go_no_go_record": _evidence_item_from_status(
            go_no_go_status,
            reason="M1 go/no-go report was not passed; review blockers or degraded reasons before signoff.",
        ),
        "server_capacity_snapshot": _evidence_item_from_status(
            _best_status(
                _section_status(go_no_go, "server_capacity_snapshot"),
                _section_status(go_no_go, "live_server_probe"),
            ),
            reason="Server capacity evidence was not passed or was not included in the provided go/no-go report.",
        ),
        "postgres_redis_ops": _evidence_item_from_status(
            _best_status(
                _section_status(go_no_go, "postgres_redis_ops_summary"),
                _section_status(go_no_go, "postgres_redis_live_probe"),
                _section_status(go_no_go, "postgres_redis_ops_evidence"),
                _section_status(go_no_go, "postgres_redis_ops"),
                _section_status(go_no_go, "postgres_redis_recovery_record"),
            ),
            reason="PostgreSQL / Redis operations evidence was not passed or was not included in the provided go/no-go report.",
        ),
        "backup_restore": _evidence_item_from_status(
            _best_status(
                _section_status(go_no_go, "backup_restore_drill_evidence"),
                _section_status(go_no_go, "backup_alert_status"),
                _section_status(go_no_go, "postgres_redis_recovery_record"),
            ),
            reason="Backup and restore evidence was not passed or was not included in the provided go/no-go report.",
        ),
        "restore_drill_feasibility": _evidence_item_from_status(
            _section_status(go_no_go, "restore_drill_feasibility"),
            reason="Restore drill feasibility evidence was not passed or was not included in the provided go/no-go report.",
        ),
        "external_dependency_resilience": _evidence_item_from_status(
            _best_status(
                external_dependency_status,
                _section_status(go_no_go, "external_dependency_resilience_record"),
            ),
            reason="External dependency resilience evidence was not passed or was not included in the provided reports.",
        ),
        "concurrency_rate_limit": _evidence_item_from_status(
            _best_status(
                _section_status(go_no_go, "live_concurrency_probe"),
                _section_status(go_no_go, "rate_limit_live_probe"),
                _section_status(go_no_go, "concurrency_rate_limit_record"),
                _section_status(go_no_go, "concurrency_rate_limit_evidence_record"),
            ),
            reason="Concurrency or rate-limit evidence was not passed or was not included in the provided go/no-go report.",
        ),
        "disk_remediation_approval_gate": _evidence_item_from_status(
            _section_status(go_no_go, "disk_remediation_approval_gate"),
            reason="Docker disk remediation approval evidence was not passed or was not included in the provided go/no-go report.",
        ),
        "incident_rollback": _evidence_item_from_status(
            _best_status(
                _section_status(go_no_go, "incident_rollback_evidence"),
                _section_status(go_no_go, "rollback_rehearsal_status"),
                _section_status(go_no_go, "rollback_execution_record"),
                _section_status(go_no_go, "incident_tabletop_status"),
            ),
            reason="Incident or rollback evidence was not passed or was not included in the provided go/no-go report.",
        ),
    }
    build_cache_approval_status = _section_status(go_no_go, "docker_build_cache_cleanup_approval_gate")
    if build_cache_approval_status != "not_checked":
        evidence["docker_build_cache_cleanup_approval_gate"] = _evidence_item_from_status(
            build_cache_approval_status,
            reason="Docker build-cache cleanup approval evidence was not passed in the provided go/no-go report.",
        )
    build_cache_post_cleanup_status = _section_status(go_no_go, "docker_build_cache_post_cleanup")
    if build_cache_post_cleanup_status != "not_checked":
        evidence["docker_build_cache_post_cleanup"] = _evidence_item_from_status(
            build_cache_post_cleanup_status,
            reason="Docker build-cache post-cleanup evidence was not passed in the provided go/no-go report.",
        )
    record["evidence_references"] = evidence
    non_passed_evidence = [
        key for key, item in evidence.items()
        if _as_mapping(item).get("status") != "passed"
    ]
    if non_passed_evidence:
        first_key = non_passed_evidence[0]
        record["issue_review"] = {
            "issues_observed": True,
            "items": [
                {
                    "category": _issue_category_for_evidence(first_key),
                    "severity": "P2",
                    "signal": "One or more provided M1 operations evidence references were not passed.",
                    "impact": "Operations review stays blocked until the private evidence is reviewed and risk is accepted or resolved.",
                    "root_cause": "<fill root cause after reviewing private evidence>",
                    "action_taken": "<fill mitigation or follow-up action>",
                    "verification": "<fill verification result>",
                    "owner": "<operations owner role>",
                    "status": "monitoring",
                    "risk_acceptance": "<fill risk acceptance if this remains unresolved>",
                }
            ],
            "lessons_learned": "Review the non-passed evidence, then replace this draft text before final signoff.",
        }
    else:
        record["issue_review"] = {
            "issues_observed": False,
            "items": [],
            "no_issue_summary": "No non-passed evidence status was derived from the provided reports; operator must confirm before signoff.",
            "lessons_learned": "Confirm the post-rollout observations, then replace this draft text before final signoff.",
        }
    record["reviewed_at"] = now.isoformat()
    record["scope"] = "post-rollout operations review draft from redacted private evidence"
    record["ops_lessons"] = {
        "deployment": "Confirm release artifact, rollout phases and health checks against the private execution record.",
        "docker_disk": "Confirm disk headroom, Docker image cleanup and build-cache cleanup readiness before the next runtime refresh.",
        "postgres": "Confirm PostgreSQL health, backup freshness and migration ownership from private evidence.",
        "redis": "Confirm Redis health, rate-limit backend behavior and fail-closed boundaries from private evidence.",
        "backup_restore": "Confirm backup schedule, restore drill and rollback data boundary before widening traffic.",
        "external_api": "Confirm external API timeout, degradation and cost guard behavior before widening traffic.",
        "rate_limit": "Confirm concurrency and 429 behavior under M1 traffic limits.",
        "rollback": "Confirm rollback command, owner, archive and post-rollback smoke evidence remain ready.",
    }
    record["followups"] = [
        {
            "id": "OPS-DRAFT-001",
            "owner": "<followup owner role>",
            "priority": "P2",
            "due_by": "<YYYY-MM-DD>",
            "action": "Replace this draft with concrete post-rollout follow-up actions after reviewing private evidence.",
            "status": "open",
        }
    ]
    source_report_statuses = [
        _report_status_item("rollout_report_json", rollout),
        _report_status_item("go_no_go_json", go_no_go),
        _report_status_item("external_dependency_json", external_dependency),
    ]
    required_sources = {"rollout_report_json", "go_no_go_json"}
    blocked_by_read = any(
        item.get("status") != "passed"
        and (
            item.get("label") in required_sources
            or item.get("status") != "not_provided"
        )
        for item in (source_statuses or [])
    )
    blocked_by_report = any(
        item.get("status") != "passed"
        and (
            item.get("label") in required_sources
            or bool(external_dependency)
        )
        for item in source_report_statuses
    )
    record["draft_backfill"] = {
        "version": "m1_operations_review_record_draft.v1",
        "generated_at": now.isoformat(),
        "status": "blocked" if blocked_by_read or blocked_by_report else "needs_manual_completion",
        "source_statuses": [dict(item) for item in (source_statuses or [])],
        "source_report_statuses": source_report_statuses,
        "source_paths_echoed": False,
        "manual_completion_required": [
            "review_id",
            "rollout_id",
            "owners",
            "issue_review",
            "ops_lessons",
            "followups",
            "risk_acceptance",
        ],
        "not_proven_by_this_draft": [
            "The rollout was healthy enough for expanded production traffic.",
            "All non-passed evidence was resolved or risk-accepted.",
            "Raw private evidence is safe to commit.",
        ],
    }
    return record


def build_m1_operations_review_record_draft_from_files(
    *,
    rollout_report_json: Path | None = None,
    go_no_go_json: Path | None = None,
    external_dependency_json: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    rollout, rollout_status = _read_evidence_json(rollout_report_json, label="rollout_report_json")
    go_no_go, go_no_go_status = _read_evidence_json(go_no_go_json, label="go_no_go_json")
    external_dependency, external_status = _read_evidence_json(
        external_dependency_json,
        label="external_dependency_json",
    )
    return build_m1_operations_review_record_draft(
        rollout_report=rollout,
        go_no_go_report=go_no_go,
        external_dependency_report=external_dependency,
        generated_at=generated_at,
        source_statuses=[rollout_status, go_no_go_status, external_status],
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private M1 operations review JSON record.")
    parser.add_argument("--template", action="store_true", help="Print a private operations review template.")
    parser.add_argument("--draft-from-evidence", action="store_true", help="Draft an operations review record from redacted evidence JSON reports.")
    parser.add_argument("--rollout-report-json", type=_path_arg, default=None, help="Private M1 rollout execution report JSON.")
    parser.add_argument("--go-no-go-json", type=_path_arg, default=None, help="Private M1 go/no-go report JSON.")
    parser.add_argument("--external-dependency-json", type=_path_arg, default=None, help="Private external dependency resilience report JSON.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report: Mapping[str, Any] = _template_record()
    elif args.draft_from_evidence:
        report = build_m1_operations_review_record_draft_from_files(
            rollout_report_json=args.rollout_report_json,
            go_no_go_json=args.go_no_go_json,
            external_dependency_json=args.external_dependency_json,
        )
    else:
        if args.record_json is None:
            report = {
                "version": M1_OPERATIONS_REVIEW_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [{"check": "input", "finding": "--record-json or --template is required."}],
            }
        else:
            try:
                raw_text = args.record_json.read_text(encoding="utf-8-sig")
                record = _read_json(args.record_json)
                report = build_m1_operations_review_record_report(record, raw_text=raw_text)
            except ValueError as exc:
                report = {
                    "version": M1_OPERATIONS_REVIEW_RECORD_VERSION,
                    "status": "blocked",
                    "blocked_reasons": [{"check": "input", "finding": str(exc)}],
                }
    output_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    draft = report.get("draft_backfill") if isinstance(report.get("draft_backfill"), Mapping) else {}
    return 2 if report.get("status") == "blocked" or draft.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
