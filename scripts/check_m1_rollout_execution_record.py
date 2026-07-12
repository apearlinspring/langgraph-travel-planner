"""Validate a private M1 rollout execution record.

The checker validates an operator-provided record for one production or M1
controlled-trial rollout. It does not deploy code, connect SSH, read `.env`,
start services, restart containers, run smoke tests or print private values.
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
    READY_VALUES,
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


M1_ROLLOUT_EXECUTION_RECORD_VERSION = "m1_rollout_execution_record.v1"
RELEASE_ARTIFACT_VERSION = "release_artifact.v1"
VALID_ENVIRONMENTS = {"staging", "production", "m1_controlled_trial"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy-", "owner role", "release id", "rollout id", "private")
REQUIRED_PHASES = {
    "release_freeze",
    "artifact_upload",
    "pre_deploy_backup",
    "release_extract",
    "runtime_refresh",
    "health_check",
    "post_deploy_smoke",
}
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
UNSAFE_COMMAND_TOKENS = (
    "git reset --hard",
    "rm -rf",
    "docker volume rm",
    "docker system prune",
    "drop database",
    "truncate",
    "flushall",
)
FORBIDDEN_EVIDENCE_PATH_PARTS = {".env", ".runtime", ".venv", "logs", "vectorstore", "vectorstore_internal"}


_path_arg = make_path_arg(PROJECT_ROOT)
_read_json = make_json_object_reader(
    read_error="Cannot read M1 rollout execution record JSON: {path}",
    object_error="M1 rollout execution record must be a JSON object.",
)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=PLACEHOLDER_FRAGMENTS,
)
_has_final_text = make_final_text_checker(_looks_placeholder)


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = ("rollout_id", "started_at", "ended_at", "environment", "release_id", "scope")
    missing = [field for field in required if not _has_final_text(record.get(field))]
    environment = str(record.get("environment") or "").strip()
    if environment not in VALID_ENVIRONMENTS:
        missing.append("environment")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": sorted(set(missing)),
        "environment": environment if environment in VALID_ENVIRONMENTS else "unknown",
        "finding": "Required rollout fields are present."
        if not missing
        else "Required rollout fields are missing.",
        "value_echoed": False,
    }


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = _as_mapping(record.get("owners"))
    required = ("release_owner", "deployment_owner", "verifier", "rollback_owner", "communications_owner")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "finding": "Required rollout owner roles are assigned."
        if not missing
        else "Required rollout owner roles are missing.",
        "value_echoed": False,
    }


def _release_artifact_check(record: Mapping[str, Any]) -> dict[str, Any]:
    artifact = _as_mapping(record.get("release_artifact"))
    blockers = []
    if artifact.get("version") != RELEASE_ARTIFACT_VERSION:
        blockers.append(_blocker("release_artifact", "version", "Release artifact version is not recognized."))
    if artifact.get("status") not in {"passed", "ready_to_build"}:
        blockers.append(_blocker("release_artifact", "status", "Release artifact status must be passed for rollout execution."))
    artifact_payload = _as_mapping(artifact.get("artifact"))
    archive_sha = str(artifact_payload.get("archive_sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", archive_sha):
        blockers.append(_blocker("release_artifact", "artifact.archive_sha256", "Archive SHA-256 must be recorded."))
    for field in ("archive_written", "manifest_written"):
        if artifact_payload.get(field) is not True:
            blockers.append(_blocker("release_artifact", f"artifact.{field}", f"{field} must be true."))
    if artifact_payload.get("archive_path_echoed") is not False:
        blockers.append(_blocker("release_artifact", "artifact.archive_path_echoed", "Archive path must not be echoed."))
    if artifact_payload.get("manifest_path_echoed") is not False:
        blockers.append(_blocker("release_artifact", "artifact.manifest_path_echoed", "Manifest path must not be echoed."))
    section_statuses = _as_mapping(artifact.get("section_statuses"))
    for section in ("git_worktree", "git_identity", "public_release_boundary", "artifact_write"):
        if section_statuses.get(section) != "passed":
            blockers.append(_blocker("release_artifact", f"section_statuses.{section}", f"{section} must be passed."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "archive_sha256_present": bool(archive_sha),
        "tracked_file_count": _as_mapping(_as_mapping(artifact.get("sections")).get("git_identity")).get("tracked_file_count"),
        "value_echoed": False,
    }


def _deployment_steps_check(record: Mapping[str, Any]) -> dict[str, Any]:
    steps = [item for item in _as_list(record.get("deployment_steps")) if isinstance(item, Mapping)]
    phases = {str(item.get("phase") or "").strip().lower() for item in steps}
    missing_phases = sorted(REQUIRED_PHASES - phases)
    blockers = []
    if missing_phases:
        blockers.append(_blocker("deployment_steps", "deployment_steps", "Required rollout phases are missing."))
    for item in steps:
        phase = str(item.get("phase") or "phase").strip().lower()
        if item.get("status") != "passed":
            blockers.append(_blocker("deployment_steps", phase, "Deployment phase must be passed."))
        if not _has_final_text(item.get("summary")):
            blockers.append(_blocker("deployment_steps", f"{phase}.summary", "Deployment phase summary is missing."))
        summary = str(item.get("summary") or "").lower()
        if any(token in summary for token in UNSAFE_COMMAND_TOKENS):
            blockers.append(_blocker("deployment_steps", f"{phase}.summary", "Deployment summary contains unsafe command text."))
    rag = _as_mapping(record.get("rag_rebuild_decision"))
    if rag.get("required") is True and rag.get("executed") is not True:
        blockers.append(_blocker("rag_rebuild_decision", "executed", "RAG rebuild was required but not executed."))
    if "required" not in rag or not _has_final_text(rag.get("reason")):
        blockers.append(_blocker("rag_rebuild_decision", "reason", "RAG rebuild decision and reason must be recorded."))
    return {
        "status": "blocked" if blockers else "passed",
        "phase_count": len(steps),
        "missing_phases": missing_phases,
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _server_preflight_check(record: Mapping[str, Any]) -> dict[str, Any]:
    preflight = _as_mapping(record.get("server_preflight"))
    blockers = []
    if preflight.get("status") != "passed":
        blockers.append(_blocker("server_preflight", "status", "Server preflight must be passed before rollout signoff."))
    for key in ("docker_ready", "deploy_dir_ready", "disk_status", "health_url_ready"):
        if not _is_ready(preflight.get(key)):
            blockers.append(_blocker("server_preflight", key, f"{key} must be passed."))
    if preflight.get("server_target_echoed") is not False:
        blockers.append(_blocker("server_preflight", "server_target_echoed", "Server target must not be echoed."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _runtime_services_check(record: Mapping[str, Any]) -> dict[str, Any]:
    services = _as_mapping(record.get("runtime_services"))
    required = ("backend", "caddy", "postgres", "redis")
    missing = [service for service in required if not _is_ready(services.get(service))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_services": missing,
        "finding": "Required runtime services are healthy."
        if not missing
        else "Required runtime service health is incomplete.",
        "value_echoed": False,
    }


def _post_deploy_checks_check(record: Mapping[str, Any]) -> dict[str, Any]:
    checks = _as_mapping(record.get("post_deploy_checks"))
    required = ("internal_live", "internal_ready", "public_live", "public_ready", "m1_gate", "mock_checkout_boundary")
    missing = [field for field in required if not _is_ready(checks.get(field))]
    acceptance = str(checks.get("acceptance_smoke") or "").strip().lower()
    if acceptance and acceptance not in READY_VALUES and acceptance not in {"not_applicable", "not applicable", "skipped"}:
        missing.append("acceptance_smoke")
    if acceptance in {"not_applicable", "not applicable", "skipped"} and not _has_final_text(checks.get("acceptance_smoke_reason")):
        missing.append("acceptance_smoke_reason")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "acceptance_smoke_recorded": bool(acceptance),
        "finding": "Post-deploy health and smoke checks passed or are explicitly scoped."
        if not missing
        else "Post-deploy health or smoke checks are incomplete.",
        "value_echoed": False,
    }


def _issue_log_check(record: Mapping[str, Any]) -> dict[str, Any]:
    issue_log = _as_mapping(record.get("issue_log"))
    blockers = []
    issues_observed = issue_log.get("issues_observed")
    if issues_observed is not True and issues_observed is not False:
        blockers.append(_blocker("issue_log", "issues_observed", "Issue observed flag must be true or false."))
    items = [item for item in _as_list(issue_log.get("items")) if isinstance(item, Mapping)]
    if issues_observed is True and not items:
        blockers.append(_blocker("issue_log", "items", "Observed rollout issues must be recorded."))
    if issues_observed is False and not _has_final_text(issue_log.get("no_issue_summary")):
        blockers.append(_blocker("issue_log", "no_issue_summary", "No-issue rollout must still record a summary."))
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        for field in ("severity", "symptom", "root_cause", "action_taken", "verification", "status"):
            if not _has_final_text(item.get(field)):
                blockers.append(_blocker("issue_log", f"{prefix}.{field}", "Issue item is incomplete."))
        if str(item.get("status") or "").strip().lower() not in {"resolved", "degraded_accepted", "monitoring"}:
            blockers.append(_blocker("issue_log", f"{prefix}.status", "Issue status must be resolved, degraded_accepted or monitoring."))
    if not _has_final_text(issue_log.get("lessons_learned")):
        blockers.append(_blocker("issue_log", "lessons_learned", "Rollout lessons learned must be recorded."))
    return {
        "status": "blocked" if blockers else "passed",
        "issue_count": len(items),
        "issues_observed": issues_observed,
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _rollback_readiness_check(record: Mapping[str, Any]) -> dict[str, Any]:
    rollback = _as_mapping(record.get("rollback_readiness"))
    required_true = (
        "previous_release_preserved",
        "rollback_command_documented",
        "rollback_owner_confirmed",
        "post_rollback_smoke_plan_ready",
        "backup_point_verified",
    )
    missing = [field for field in required_true if not _is_ready(rollback.get(field))]
    if rollback.get("database_migration_rollback_plan") not in {"not_needed", "documented", "tested"}:
        missing.append("database_migration_rollback_plan")
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Rollback readiness is recorded."
        if not missing
        else "Rollback readiness is incomplete.",
        "value_echoed": False,
    }


def _data_safety_check(record: Mapping[str, Any]) -> dict[str, Any]:
    safety = _as_mapping(record.get("data_safety"))
    required_true = (
        "dotenv_untouched",
        "postgres_volume_untouched",
        "redis_volume_untouched",
        "vectorstore_runtime_untouched_or_rebuilt_safely",
        "logs_not_committed",
        "no_runtime_data_uploaded_from_local",
    )
    missing = [field for field in required_true if not _is_ready(safety.get(field))]
    required_false = ("used_git_reset_hard", "used_bulk_delete", "deleted_volumes", "printed_env_values")
    unsafe = [field for field in required_false if safety.get(field) is not False]
    blocked = []
    if missing:
        blocked.append({"field": "data_safety", "missing_ready": missing, "finding": "Data safety confirmations are missing."})
    if unsafe:
        blocked.append({"field": "data_safety", "unsafe_fields": unsafe, "finding": "Unsafe rollout flags must be false."})
    return {
        "status": "blocked" if blocked else "passed",
        "blocked_reasons": blocked,
        "finding": "Runtime data safety boundary is recorded."
        if not blocked
        else "Runtime data safety boundary is incomplete.",
        "value_echoed": False,
    }


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blocked = []
    for key in ("raw_logs_included", "screenshots_included", "customer_pii_included", "secret_values_included", "raw_urls_included", "raw_server_paths_included"):
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


def build_m1_rollout_execution_record_report(
    record: Mapping[str, Any],
    *,
    raw_text: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted validation report for one M1 rollout execution record."""

    checks = {
        "required_fields": _required_fields_check(record),
        "owners": _owners_check(record),
        "release_artifact": _release_artifact_check(record),
        "deployment_steps": _deployment_steps_check(record),
        "server_preflight": _server_preflight_check(record),
        "runtime_services": _runtime_services_check(record),
        "post_deploy_checks": _post_deploy_checks_check(record),
        "issue_log": _issue_log_check(record),
        "rollback_readiness": _rollback_readiness_check(record),
        "data_safety": _data_safety_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    now = generated_at or datetime.now(UTC)
    return {
        "version": M1_ROLLOUT_EXECUTION_RECORD_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "deploys_code": False,
            "connects_ssh": False,
            "starts_services": False,
            "restarts_containers": False,
            "runs_smoke_tests": False,
            "record_text_echoed": False,
        },
        "record_summary": {
            "rollout_id_present": _has_text(record.get("rollout_id")),
            "environment": checks["required_fields"].get("environment"),
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "deployment_phase_count": checks["deployment_steps"].get("phase_count"),
            "issue_count": checks["issue_log"].get("issue_count"),
            "issues_observed": checks["issue_log"].get("issues_observed"),
            "archive_sha256_present": checks["release_artifact"].get("archive_sha256_present"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_M1_ROLLOUT_EXECUTION_STATUS": status,
            "ZHIXING_RELEASE_ARTIFACT_USED_STATUS": checks["release_artifact"]["status"],
            "ZHIXING_POST_DEPLOY_HEALTH_STATUS": checks["post_deploy_checks"]["status"],
            "ZHIXING_ROLLOUT_ROLLBACK_READY_STATUS": checks["rollback_readiness"]["status"],
            "ZHIXING_ROLLOUT_DATA_SAFETY_STATUS": checks["data_safety"]["status"],
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided rollout record; it does not deploy code itself.",
            "A passed record does not prove autoscaling, multi-region HA or long-duration soak stability.",
            "This does not permit real payment, booking, inventory lock, ticketing or fulfillment.",
            "Raw URLs, IP addresses, server paths, logs, screenshots, .env files and secret values must stay outside Git.",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "rollout_id": "<m1-rollout-YYYYMMDD>",
        "started_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "ended_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "environment": "m1_controlled_trial",
        "release_id": "<release id>",
        "scope": "<M1 controlled trial rollout>",
        "owners": {
            "release_owner": "<release owner role>",
            "deployment_owner": "<deployment owner role>",
            "verifier": "<verifier role>",
            "rollback_owner": "<rollback owner role>",
            "communications_owner": "<communications owner role>",
        },
        "release_artifact": {
            "version": RELEASE_ARTIFACT_VERSION,
            "status": "passed",
            "section_statuses": {
                "git_worktree": "passed",
                "git_identity": "passed",
                "public_release_boundary": "passed",
                "artifact_write": "passed",
            },
            "artifact": {
                "archive_written": True,
                "manifest_written": True,
                "archive_sha256": "<64-char-sha256>",
                "archive_path_echoed": False,
                "manifest_path_echoed": False,
            },
            "sections": {"git_identity": {"tracked_file_count": 0}},
        },
        "deployment_steps": [
            {"phase": "release_freeze", "status": "passed", "summary": "<release candidate freeze signed off>"},
            {"phase": "artifact_upload", "status": "passed", "summary": "<release archive uploaded and sha256 verified>"},
            {"phase": "pre_deploy_backup", "status": "passed", "summary": "<backup point verified before rollout>"},
            {"phase": "release_extract", "status": "passed", "summary": "<release extracted without touching runtime data>"},
            {"phase": "runtime_refresh", "status": "passed", "summary": "<backend and caddy refreshed>"},
            {"phase": "health_check", "status": "passed", "summary": "<live and ready checks passed>"},
            {"phase": "post_deploy_smoke", "status": "passed", "summary": "<M1 smoke checks passed>"},
        ],
        "rag_rebuild_decision": {
            "required": False,
            "executed": False,
            "reason": "<RAG docs unchanged, rebuild not required>",
        },
        "server_preflight": {
            "status": "passed",
            "docker_ready": "passed",
            "deploy_dir_ready": "passed",
            "disk_status": "passed",
            "health_url_ready": "passed",
            "server_target_echoed": False,
        },
        "runtime_services": {
            "backend": "passed",
            "caddy": "passed",
            "postgres": "passed",
            "redis": "passed",
        },
        "post_deploy_checks": {
            "internal_live": "passed",
            "internal_ready": "passed",
            "public_live": "passed",
            "public_ready": "passed",
            "m1_gate": "passed",
            "mock_checkout_boundary": "passed",
            "acceptance_smoke": "not_applicable",
            "acceptance_smoke_reason": "<M1 rollout scoped to health, gate and mock checkout>",
        },
        "issue_log": {
            "issues_observed": False,
            "no_issue_summary": "<no rollout incident observed>",
            "items": [],
            "lessons_learned": "<record operational lessons>",
        },
        "rollback_readiness": {
            "previous_release_preserved": "passed",
            "rollback_command_documented": "passed",
            "rollback_owner_confirmed": "passed",
            "post_rollback_smoke_plan_ready": "passed",
            "backup_point_verified": "passed",
            "database_migration_rollback_plan": "not_needed",
        },
        "data_safety": {
            "dotenv_untouched": "passed",
            "postgres_volume_untouched": "passed",
            "redis_volume_untouched": "passed",
            "vectorstore_runtime_untouched_or_rebuilt_safely": "passed",
            "logs_not_committed": "passed",
            "no_runtime_data_uploaded_from_local": "passed",
            "used_git_reset_hard": False,
            "used_bulk_delete": False,
            "deleted_volumes": False,
            "printed_env_values": False,
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_server_paths_included": False,
        },
    }


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


def _check_status_by_key(report: Mapping[str, Any], key: str) -> str:
    for item in _as_list(report.get("checks")):
        if isinstance(item, Mapping) and item.get("key") == key:
            return _status_value(item.get("status"))
    return "not_checked"


def _probe_status(report: Mapping[str, Any], key: str) -> str:
    value = _as_mapping(report.get(key))
    return _status_value(value.get("status"))


def _section_status(report: Mapping[str, Any], key: str) -> str:
    section_statuses = _as_mapping(report.get("section_statuses"))
    if key in section_statuses:
        return _status_value(section_statuses.get(key))
    go_no_go = _as_mapping(report.get("go_no_go"))
    nested_statuses = _as_mapping(go_no_go.get("section_statuses"))
    if key in nested_statuses:
        return _status_value(nested_statuses.get(key))
    return "not_checked"


def _derived_server_preflight(server_preflight: Mapping[str, Any]) -> dict[str, Any]:
    docker_ready = _probe_status(server_preflight, "docker_probe")
    if docker_ready == "not_checked":
        docker_ready = _check_status_by_key(server_preflight, "docker_status")
    deploy_dir_ready = _probe_status(server_preflight, "deploy_dir_probe")
    if deploy_dir_ready == "not_checked":
        deploy_dir_ready = _check_status_by_key(server_preflight, "deploy_dir")
    disk_status = _probe_status(server_preflight, "disk_probe")
    health_url_ready = _probe_status(server_preflight, "health_probe")
    overall = _status_value(server_preflight.get("status"))
    if all(value == "passed" for value in (docker_ready, deploy_dir_ready, disk_status, health_url_ready)):
        status = "passed"
    elif "blocked" in {docker_ready, deploy_dir_ready, disk_status, health_url_ready, overall}:
        status = "blocked"
    elif "warning" in {docker_ready, deploy_dir_ready, disk_status, health_url_ready, overall}:
        status = "warning"
    else:
        status = overall
    return {
        "status": status,
        "docker_ready": docker_ready,
        "deploy_dir_ready": deploy_dir_ready,
        "disk_status": disk_status,
        "health_url_ready": health_url_ready,
        "server_target_echoed": False,
    }


def _derived_runtime_services(
    postgres_redis: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> dict[str, str]:
    declarations = _as_mapping(postgres_redis.get("declaration_statuses"))
    live_server_status = _section_status(workflow, "live_server_probe")
    return {
        "backend": "passed" if live_server_status == "passed" else live_server_status,
        "caddy": "passed" if live_server_status == "passed" else live_server_status,
        "postgres": _status_value(declarations.get("ZHIXING_POSTGRES_LIVE_STATUS")),
        "redis": _status_value(declarations.get("ZHIXING_REDIS_LIVE_STATUS")),
    }


def _derived_post_deploy_checks(workflow: Mapping[str, Any]) -> dict[str, Any]:
    live_server_status = _section_status(workflow, "live_server_probe")
    gate_status = _section_status(workflow, "m1_deployment_gate")
    if gate_status == "not_checked":
        decision = str(_as_mapping(workflow.get("go_no_go")).get("decision") or workflow.get("decision") or "")
        gate_status = "passed" if decision == "go_for_m1_controlled_trial" else "not_checked"
    smoke_status = _section_status(workflow, "m1_smoke_evidence")
    acceptance = smoke_status if smoke_status != "not_checked" else "not_applicable"
    checks = {
        "internal_live": live_server_status,
        "internal_ready": live_server_status,
        "public_live": live_server_status,
        "public_ready": live_server_status,
        "m1_gate": gate_status,
        "mock_checkout_boundary": live_server_status,
        "acceptance_smoke": acceptance,
    }
    if acceptance == "not_applicable":
        checks["acceptance_smoke_reason"] = "M1 workflow report did not include acceptance smoke evidence; confirm scope manually."
    return checks


def build_m1_rollout_execution_record_draft(
    *,
    server_preflight_report: Mapping[str, Any] | None = None,
    postgres_redis_report: Mapping[str, Any] | None = None,
    workflow_report: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
    source_statuses: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a private rollout record draft from redacted evidence reports."""

    record = _template_record()
    now = generated_at or datetime.now(UTC)
    server_preflight = _as_mapping(server_preflight_report or {})
    postgres_redis = _as_mapping(postgres_redis_report or {})
    workflow = _as_mapping(workflow_report or {})
    record["server_preflight"] = _derived_server_preflight(server_preflight)
    record["runtime_services"] = _derived_runtime_services(postgres_redis, workflow)
    record["post_deploy_checks"] = _derived_post_deploy_checks(workflow)
    workflow_status = _status_value(workflow.get("status"))
    postgres_redis_status = _status_value(postgres_redis.get("status"))
    server_status = _status_value(server_preflight.get("status"))
    issue_observed = any(status not in {"passed", "not_checked"} for status in (workflow_status, postgres_redis_status, server_status))
    record["issue_log"] = {
        "issues_observed": issue_observed,
        "no_issue_summary": "No rollout issue was derived from provided evidence; operator must confirm before signoff."
        if not issue_observed
        else "",
        "items": [
            {
                "severity": "P2",
                "symptom": "One or more provided rollout evidence reports were not passed.",
                "root_cause": "<fill root cause after reviewing private evidence>",
                "action_taken": "<fill action taken>",
                "verification": "<fill verification result>",
                "status": "monitoring",
            }
        ]
        if issue_observed
        else [],
        "lessons_learned": "Review evidence, record operational lessons, then replace this draft text before final signoff.",
    }
    record["draft_backfill"] = {
        "version": "m1_rollout_execution_record_draft.v1",
        "generated_at": now.isoformat(),
        "status": "blocked"
        if any(item.get("status") != "passed" for item in (source_statuses or []))
        else "needs_manual_completion",
        "source_statuses": [dict(item) for item in (source_statuses or [])],
        "source_paths_echoed": False,
        "manual_completion_required": [
            "rollout_id",
            "started_at",
            "ended_at",
            "release_id",
            "owners",
            "release_artifact.archive_sha256",
            "deployment_steps",
            "rag_rebuild_decision",
            "issue_log",
            "rollback_readiness",
            "data_safety",
        ],
        "not_proven_by_this_draft": [
            "The current release was deployed successfully.",
            "Release artifact, backup point, rollback owner and issue review are complete.",
            "Raw private evidence is safe to commit.",
        ],
    }
    return record


def build_m1_rollout_execution_record_draft_from_files(
    *,
    server_preflight_json: Path | None = None,
    postgres_redis_json: Path | None = None,
    workflow_report_json: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    server_preflight, server_status = _read_evidence_json(server_preflight_json, label="server_preflight_json")
    postgres_redis, postgres_status = _read_evidence_json(postgres_redis_json, label="postgres_redis_json")
    workflow, workflow_status = _read_evidence_json(workflow_report_json, label="workflow_report_json")
    return build_m1_rollout_execution_record_draft(
        server_preflight_report=server_preflight,
        postgres_redis_report=postgres_redis,
        workflow_report=workflow,
        generated_at=generated_at,
        source_statuses=[server_status, postgres_status, workflow_status],
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private M1 rollout execution JSON record.")
    parser.add_argument("--template", action="store_true", help="Print a private rollout record template.")
    parser.add_argument("--draft-from-evidence", action="store_true", help="Draft a rollout record from redacted evidence JSON reports.")
    parser.add_argument("--server-preflight-json", type=_path_arg, default=None, help="Private server preflight JSON report.")
    parser.add_argument("--postgres-redis-json", type=_path_arg, default=None, help="Private PostgreSQL/Redis live probe JSON report.")
    parser.add_argument("--workflow-report-json", type=_path_arg, default=None, help="Private M1 live evidence workflow report JSON.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report: Mapping[str, Any] = _template_record()
    elif args.draft_from_evidence:
        report = build_m1_rollout_execution_record_draft_from_files(
            server_preflight_json=args.server_preflight_json,
            postgres_redis_json=args.postgres_redis_json,
            workflow_report_json=args.workflow_report_json,
        )
    else:
        if args.record_json is None:
            report = {
                "version": M1_ROLLOUT_EXECUTION_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [{"check": "input", "finding": "--record-json or --template is required."}],
            }
        else:
            try:
                raw_text = args.record_json.read_text(encoding="utf-8-sig")
                record = _read_json(args.record_json)
                report = build_m1_rollout_execution_record_report(record, raw_text=raw_text)
            except ValueError as exc:
                report = {
                    "version": M1_ROLLOUT_EXECUTION_RECORD_VERSION,
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
