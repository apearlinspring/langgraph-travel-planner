"""Validate private M1 live evidence before a controlled-trial signoff.

This checker reads a private workflow-report JSON produced by
run_m1_private_live_evidence_workflow.py, verifies referenced artifact hashes,
and validates that the go/no-go decision has an explicit release-owner signoff.
It does not read `.env`, run probes, connect SSH, start services, delete files,
or print private target values.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import hashlib
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

from scripts.export_acceptance_evidence import redact_text  # noqa: E402
from scripts.run_m1_private_live_evidence_workflow import (  # noqa: E402
    M1_PRIVATE_LIVE_EVIDENCE_WORKFLOW_VERSION,
)


M1_PRIVATE_EVIDENCE_SIGNOFF_VERSION = "m1_private_evidence_signoff.v1"
M1_ROLLOUT_EXECUTION_RECORD_VERSION = "m1_rollout_execution_record.v1"
M1_OPERATIONS_REVIEW_RECORD_VERSION = "m1_operations_review_record.v1"
STANDARD_REQUIRED_SECTIONS = {
    "backup_schedule_live_probe",
    "docker_disk_cleanup_plan",
    "live_concurrency_probe",
    "live_server_probe",
    "postgres_redis_live_probe",
    "probe_auth_readiness",
    "rate_limit_live_probe",
    "server_capacity_snapshot",
}
PRIVATE_REVIEW_REPORT_SECTIONS = {
    "m1_rollout_execution_record": {
        "label": "rollout_report_json",
        "version": M1_ROLLOUT_EXECUTION_RECORD_VERSION,
        "description": "M1 rollout execution validation report",
    },
    "m1_operations_review_record": {
        "label": "operations_review_report_json",
        "version": M1_OPERATIONS_REVIEW_RECORD_VERSION,
        "description": "M1 operations review validation report",
    },
}
ACCEPTABLE_GO_DECISIONS = {"go_for_m1_controlled_trial"}
CONDITIONAL_DECISIONS = {"conditional_go"}
HASHED_ARTIFACT_ROLES = {
    "private_go_no_go_json",
    "live_evidence_summary_markdown",
    "evidence_bundle_manifest",
}
FORBIDDEN_PRIVATE_REPORT_PATH_PARTS = {".env", ".runtime", ".venv", "logs", "vectorstore", "vectorstore_internal"}
PLACEHOLDER_VALUES = {"", "-", "pending", "todo", "tbd", "unknown", "n/a", "na"}
URL_PATTERN = re.compile(r"https?://[^\s`'\"<>()\[\]{}|]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
    r"\s*[:=]\s*[^&\s,;]+"
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read private M1 evidence workflow JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Private M1 evidence workflow JSON must be an object.")
    return payload


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_forbidden_private_report_path(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & FORBIDDEN_PRIVATE_REPORT_PATH_PARTS)


def _read_private_report_json(path: Path | None, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
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
        status.update({"status": "blocked", "reason": "Private report JSON must stay outside the Git workspace."})
        return {}, status
    if _is_forbidden_private_report_path(resolved):
        status.update({"status": "blocked", "reason": "Private report path points to a forbidden runtime or secret-like location."})
        return {}, status
    try:
        raw_text = resolved.read_text(encoding="utf-8-sig")
    except OSError:
        status.update({"status": "blocked", "reason": "Private report JSON file cannot be read."})
        return {}, status
    if URL_PATTERN.search(raw_text) or IPV4_PATTERN.search(raw_text) or SECRET_PATTERN.search(raw_text):
        status.update({"status": "blocked", "reason": "Private report JSON contains raw URL, IP or secret-looking text."})
        return {}, status
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        status.update({"status": "blocked", "reason": "Private report JSON is not valid JSON."})
        return {}, status
    if not isinstance(payload, dict):
        status.update({"status": "blocked", "reason": "Private report JSON must be an object."})
        return {}, status
    status["status"] = "passed"
    return payload, status


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(value: Any) -> str:
    return redact_text(str(value or "")).strip()


def _is_filled(value: Any) -> bool:
    return _normalized(value).lower() not in PLACEHOLDER_VALUES


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _blocker(check: str, key: str, finding: str) -> dict[str, str]:
    return {"check": check, "key": key, "finding": finding}


def _status_from_blockers(blockers: list[dict[str, str]]) -> str:
    return "blocked" if blockers else "passed"


def _workflow_check(report: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if report.get("version") != M1_PRIVATE_LIVE_EVIDENCE_WORKFLOW_VERSION:
        blockers.append(_blocker("workflow", "version", "Workflow report version is not recognized."))
    if report.get("status") not in {"passed", "degraded"}:
        blockers.append(_blocker("workflow", "status", "Workflow status must be passed or degraded for signoff."))
    missing_inputs = _as_list(report.get("missing_inputs_for_user"))
    if missing_inputs:
        blockers.append(_blocker("workflow", "missing_inputs", "Workflow still has missing private inputs."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "workflow_status": report.get("status"),
        "workflow_version": report.get("version"),
        "missing_input_count": len(missing_inputs),
    }


def _policy_check(report: Mapping[str, Any]) -> dict[str, Any]:
    policy = _as_mapping(report.get("policy"))
    target = _as_mapping(report.get("target"))
    expected_false = (
        "reads_dotenv",
        "starts_services",
        "deploys_code",
        "deletes_files",
        "records_public_url",
        "records_server_ip",
        "records_credentials",
    )
    blockers: list[dict[str, str]] = []
    for key in expected_false:
        if policy.get(key) is not False:
            blockers.append(_blocker("policy", key, f"Policy {key} must be false."))
    if policy.get("output_should_remain_private") is not True:
        blockers.append(_blocker("policy", "output_should_remain_private", "Evidence output must remain private."))
    if target.get("output_dir_inside_project") is not False:
        blockers.append(_blocker("policy", "output_dir_inside_project", "Private evidence output must be outside the Git workspace."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "reads_dotenv": policy.get("reads_dotenv"),
        "output_dir_inside_project": target.get("output_dir_inside_project"),
        "records_credentials": policy.get("records_credentials"),
    }


def _section_check(
    report: Mapping[str, Any],
    *,
    require_standard_live_sections: bool,
    allow_conditional_go: bool,
) -> dict[str, Any]:
    selected_sections = set(str(item) for item in _as_list(report.get("selected_sections")))
    go_no_go = _as_mapping(report.get("go_no_go"))
    section_statuses = _as_mapping(go_no_go.get("section_statuses"))
    blockers: list[dict[str, str]] = []
    if require_standard_live_sections:
        missing = sorted(STANDARD_REQUIRED_SECTIONS - selected_sections)
        if missing:
            blockers.append(
                _blocker(
                    "sections",
                    "missing_standard_sections",
                    "Standard M1 live evidence sections are incomplete.",
                )
            )
        missing_statuses = sorted(STANDARD_REQUIRED_SECTIONS - set(section_statuses))
        if missing_statuses:
            blockers.append(
                _blocker(
                    "sections",
                    "missing_section_statuses",
                    "Standard M1 live evidence section statuses are incomplete.",
                )
            )
    missing_selected_statuses = sorted(selected_sections - set(section_statuses))
    if missing_selected_statuses:
        blockers.append(
            _blocker(
                "sections",
                "missing_selected_section_statuses",
                "Selected M1 evidence sections are missing from go/no-go section statuses.",
            )
        )
    bad_statuses = {
        name: status
        for name, status in section_statuses.items()
        if str(status) in {"blocked", "failed", "unknown", "skipped", "not_checked"}
    }
    if bad_statuses:
        blockers.append(_blocker("sections", "bad_section_status", "One or more requested evidence sections block release."))
    if not allow_conditional_go:
        degraded = {name: status for name, status in section_statuses.items() if str(status) in {"degraded", "warning"}}
        if degraded:
            blockers.append(_blocker("sections", "degraded_section_requires_acceptance", "Degraded sections require explicit conditional-go risk acceptance."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "selected_section_count": len(selected_sections),
        "section_status_count": len(section_statuses),
        "standard_required_section_count": len(STANDARD_REQUIRED_SECTIONS) if require_standard_live_sections else 0,
    }


def _decision_check(
    report: Mapping[str, Any],
    *,
    signoff_owner: str | None,
    release_decision: str,
    risk_acceptance: str | None,
    allow_conditional_go: bool,
) -> dict[str, Any]:
    go_no_go = _as_mapping(report.get("go_no_go"))
    decision = str(go_no_go.get("decision") or "")
    blockers: list[dict[str, str]] = []
    if decision not in ACCEPTABLE_GO_DECISIONS:
        if decision in CONDITIONAL_DECISIONS and allow_conditional_go:
            if not _is_filled(risk_acceptance):
                blockers.append(_blocker("decision", "risk_acceptance", "Conditional go requires a filled risk acceptance note."))
        else:
            blockers.append(_blocker("decision", "go_no_go_decision", "Go/no-go decision is not approved for M1 signoff."))
    if release_decision not in ACCEPTABLE_GO_DECISIONS:
        if release_decision in CONDITIONAL_DECISIONS and allow_conditional_go:
            if not _is_filled(risk_acceptance):
                blockers.append(_blocker("decision", "release_risk_acceptance", "Conditional release signoff requires risk acceptance."))
        else:
            blockers.append(_blocker("decision", "release_decision", "Release decision must explicitly match an allowed M1 signoff decision."))
    if not _is_filled(signoff_owner):
        blockers.append(_blocker("decision", "signoff_owner", "Release-owner signoff is required."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "go_no_go_decision": decision or "unknown",
        "release_decision": release_decision,
        "signoff_owner_present": _is_filled(signoff_owner),
        "risk_acceptance_present": _is_filled(risk_acceptance),
        "value_echoed": False,
    }


def _safe_artifact_path(evidence_dir: Path, relative_path: Any) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        return None
    candidate = (evidence_dir / path).resolve()
    if not _is_relative_to(candidate, evidence_dir):
        return None
    return candidate


def _artifact_check(
    report: Mapping[str, Any],
    *,
    evidence_dir: Path | None,
    workflow_report_path: Path | None,
    allow_project_input: bool,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    artifacts = [item for item in _as_list(report.get("artifacts")) if isinstance(item, Mapping)]
    checked_hashes = 0
    checked_exists = 0
    if evidence_dir is None:
        blockers.append(_blocker("artifacts", "evidence_dir", "Evidence directory is required for artifact verification."))
    else:
        evidence_dir = evidence_dir.resolve()
        if _is_relative_to(evidence_dir, PROJECT_ROOT) and not allow_project_input:
            blockers.append(_blocker("artifacts", "project_evidence_dir", "Private evidence directory must stay outside the Git workspace."))
    roles = {str(item.get("role") or "") for item in artifacts}
    required_hash_roles = {"private_go_no_go_json", "live_evidence_summary_markdown"}
    missing_hash_roles = sorted(required_hash_roles - roles)
    if missing_hash_roles:
        blockers.append(_blocker("artifacts", "missing_artifact_roles", "Required private evidence artifacts are missing."))
    if evidence_dir is not None:
        for item in artifacts:
            role = str(item.get("role") or "")
            if role == "evidence_bundle_dir":
                target = _safe_artifact_path(evidence_dir, item.get("path"))
                if target is None or not target.is_dir():
                    blockers.append(_blocker("artifacts", role or "bundle_dir", "Evidence bundle directory is missing."))
                else:
                    checked_exists += 1
                continue
            target = _safe_artifact_path(evidence_dir, item.get("path"))
            if target is None:
                blockers.append(_blocker("artifacts", role or "artifact_path", "Artifact path is unsafe or missing."))
                continue
            if not target.exists() or not target.is_file():
                blockers.append(_blocker("artifacts", role or "artifact_file", "Artifact file is missing."))
                continue
            checked_exists += 1
            expected_hash = item.get("sha256")
            if role in HASHED_ARTIFACT_ROLES:
                if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                    blockers.append(_blocker("artifacts", role, "Artifact SHA-256 is missing."))
                    continue
                actual_hash = _sha256_file(target)
                if actual_hash != expected_hash:
                    blockers.append(_blocker("artifacts", role, "Artifact SHA-256 does not match current file."))
                else:
                    checked_hashes += 1
    if workflow_report_path is not None and evidence_dir is not None:
        if not _is_relative_to(workflow_report_path.resolve(), evidence_dir.resolve()):
            blockers.append(_blocker("artifacts", "workflow_report_location", "Workflow report must be inside the private evidence directory."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "artifact_count": len(artifacts),
        "checked_exists_count": checked_exists,
        "checked_hash_count": checked_hashes,
        "value_echoed": False,
    }


def _redaction_check(raw_text: str) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if URL_PATTERN.search(raw_text):
        blockers.append(_blocker("redaction", "url", "Workflow report contains a raw URL."))
    if IPV4_PATTERN.search(raw_text):
        blockers.append(_blocker("redaction", "ipv4", "Workflow report contains a raw IPv4 address."))
    if SECRET_PATTERN.search(raw_text):
        blockers.append(_blocker("redaction", "secret_pattern", "Workflow report contains a secret-looking value."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "raw_text_echoed": False,
    }


def _private_review_reports_check(
    workflow_report: Mapping[str, Any],
    *,
    rollout_report: Mapping[str, Any] | None,
    operations_review_report: Mapping[str, Any] | None,
    report_input_statuses: list[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    selected_sections = set(str(item) for item in _as_list(workflow_report.get("selected_sections")))
    reports = {
        "m1_rollout_execution_record": _as_mapping(rollout_report),
        "m1_operations_review_record": _as_mapping(operations_review_report),
    }
    blockers: list[dict[str, str]] = []
    source_statuses = [dict(item) for item in (report_input_statuses or [])]
    source_status_by_label = {
        str(item.get("label") or ""): str(item.get("status") or "not_provided")
        for item in source_statuses
        if isinstance(item, Mapping)
    }
    for item in source_statuses:
        if item.get("status") == "blocked":
            blockers.append(
                _blocker(
                    "private_review_reports",
                    str(item.get("label") or "private_report_json"),
                    str(item.get("reason") or "Private review report input is blocked."),
                )
            )
    for section, spec in PRIVATE_REVIEW_REPORT_SECTIONS.items():
        label = str(spec["label"])
        report = reports[section]
        required = section in selected_sections
        provided = bool(report)
        if required and not provided:
            blockers.append(
                _blocker(
                    "private_review_reports",
                    label,
                    f"{spec['description']} is required because the workflow selected {section}.",
                )
            )
            continue
        if not provided:
            continue
        if report.get("version") != spec["version"]:
            blockers.append(_blocker("private_review_reports", f"{label}.version", "Private review report version is not recognized."))
        if report.get("status") != "passed":
            blockers.append(_blocker("private_review_reports", f"{label}.status", "Private review report must be passed before final signoff."))
        if source_status_by_label.get(label, "passed") != "passed":
            blockers.append(_blocker("private_review_reports", f"{label}.input", "Private review report input did not pass safety checks."))
    return {
        "status": _status_from_blockers(blockers),
        "blocked_reasons": blockers,
        "rollout_report_required": "m1_rollout_execution_record" in selected_sections,
        "operations_review_report_required": "m1_operations_review_record" in selected_sections,
        "rollout_report_provided": bool(reports["m1_rollout_execution_record"]),
        "operations_review_report_provided": bool(reports["m1_operations_review_record"]),
        "source_statuses": source_statuses,
        "source_paths_echoed": False,
        "value_echoed": False,
    }


def _collect_blockers(checks: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name, check in checks.items():
        for item in check.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                blockers.append({"check": name, **dict(item)})
    return blockers


def build_m1_private_evidence_signoff_report(
    workflow_report: Mapping[str, Any],
    *,
    workflow_report_path: Path | None = None,
    evidence_dir: Path | None = None,
    rollout_report: Mapping[str, Any] | None = None,
    operations_review_report: Mapping[str, Any] | None = None,
    report_input_statuses: list[Mapping[str, Any]] | None = None,
    raw_text: str = "",
    signoff_owner: str | None = None,
    release_decision: str = "go_for_m1_controlled_trial",
    risk_acceptance: str | None = None,
    allow_conditional_go: bool = False,
    require_standard_live_sections: bool = True,
    allow_project_input: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted M1 private evidence signoff validation report."""

    checks = {
        "workflow": _workflow_check(workflow_report),
        "policy": _policy_check(workflow_report),
        "sections": _section_check(
            workflow_report,
            require_standard_live_sections=require_standard_live_sections,
            allow_conditional_go=allow_conditional_go,
        ),
        "decision": _decision_check(
            workflow_report,
            signoff_owner=signoff_owner,
            release_decision=release_decision,
            risk_acceptance=risk_acceptance,
            allow_conditional_go=allow_conditional_go,
        ),
        "artifacts": _artifact_check(
            workflow_report,
            evidence_dir=evidence_dir,
            workflow_report_path=workflow_report_path,
            allow_project_input=allow_project_input,
        ),
        "private_review_reports": _private_review_reports_check(
            workflow_report,
            rollout_report=rollout_report,
            operations_review_report=operations_review_report,
            report_input_statuses=report_input_statuses,
        ),
        "redaction": _redaction_check(raw_text or json.dumps(workflow_report, ensure_ascii=False)),
    }
    blockers = _collect_blockers(checks)
    status = "blocked" if blockers else "passed"
    now = generated_at or datetime.now(UTC)
    return {
        "version": M1_PRIVATE_EVIDENCE_SIGNOFF_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "runs_live_probes": False,
            "connects_ssh": False,
            "starts_services": False,
            "deletes_files": False,
            "reads_private_evidence_files": True,
            "records_source_path": False,
            "records_private_values": False,
            "raw_text_echoed": False,
        },
        "target": {
            "workflow_report_path_echoed": False,
            "evidence_dir_echoed": False,
            "evidence_dir_inside_project": bool(evidence_dir and _is_relative_to(evidence_dir.resolve(), PROJECT_ROOT)),
            "allow_project_input": allow_project_input,
        },
        "signoff": {
            "owner_present": _is_filled(signoff_owner),
            "release_decision": release_decision,
            "allow_conditional_go": allow_conditional_go,
            "risk_acceptance_present": _is_filled(risk_acceptance),
            "value_echoed": False,
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_M1_PRIVATE_EVIDENCE_SIGNOFF_STATUS": status,
            "ZHIXING_M1_PRIVATE_EVIDENCE_ARTIFACT_STATUS": checks["artifacts"]["status"],
            "ZHIXING_M1_PRIVATE_EVIDENCE_DECISION_STATUS": checks["decision"]["status"],
            "ZHIXING_M1_PRIVATE_REVIEW_REPORT_STATUS": checks["private_review_reports"]["status"],
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates a private evidence record; it does not deploy code or run live probes.",
            "A passed signoff validates the sampled M1 evidence package only.",
            "This does not prove full production-grade HA, autoscaling, long-duration soak stability, real payment, booking, inventory lock, ticketing or fulfillment.",
            "Raw operational evidence, screenshots, logs, .env files, vector stores and customer data must remain outside Git.",
        ],
    }


def build_m1_private_evidence_signoff_markdown(report: Mapping[str, Any]) -> str:
    def cell(value: Any) -> str:
        return redact_text(str(value if value not in {None, ""} else "-")).replace("|", "\\|")

    lines = [
        "# M1 Private Evidence Signoff（私有证据签核校验）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{cell(report.get('version'))}` |",
        f"| Status | `{cell(report.get('status'))}` |",
        f"| Reads `.env` | `{cell(_as_mapping(report.get('policy')).get('reads_dotenv'))}` |",
        f"| Runs live probes | `{cell(_as_mapping(report.get('policy')).get('runs_live_probes'))}` |",
        f"| Evidence dir inside project | `{cell(_as_mapping(report.get('target')).get('evidence_dir_inside_project'))}` |",
        f"| Release decision | `{cell(_as_mapping(report.get('signoff')).get('release_decision'))}` |",
        "",
        "## Checks",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    checks = _as_mapping(report.get("checks"))
    for name, check in checks.items():
        if isinstance(check, Mapping):
            lines.append(f"| {cell(name)} | `{cell(check.get('status'))}` |")
    lines.extend(["", "## Blockers", "", "| Check | Key | Finding |", "|---|---|---|"])
    blockers = _as_list(report.get("blocked_reasons"))
    if blockers:
        for item in blockers:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"| {cell(item.get('check'))} | {cell(item.get('key'))} | {cell(item.get('finding'))} |"
            )
    else:
        lines.append("| - | - | - |")
    lines.extend(["", "## Boundary", ""])
    for item in _as_list(report.get("not_proven_by_this_report")):
        lines.append(f"- {cell(item)}")
    return "\n".join(lines)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-report-json", type=_path_arg, required=True)
    parser.add_argument("--rollout-report-json", type=_path_arg, default=None)
    parser.add_argument("--operations-review-report-json", type=_path_arg, default=None)
    parser.add_argument("--signoff-owner", default=None)
    parser.add_argument("--release-decision", default="go_for_m1_controlled_trial")
    parser.add_argument("--risk-acceptance", default=None)
    parser.add_argument("--allow-conditional-go", action="store_true")
    parser.add_argument("--no-require-standard-live-sections", action="store_true")
    parser.add_argument("--allow-project-input", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw_text = args.workflow_report_json.read_text(encoding="utf-8-sig")
        workflow_report = _read_json(args.workflow_report_json)
        rollout_report, rollout_report_status = _read_private_report_json(
            args.rollout_report_json,
            label="rollout_report_json",
        )
        operations_review_report, operations_report_status = _read_private_report_json(
            args.operations_review_report_json,
            label="operations_review_report_json",
        )
        report = build_m1_private_evidence_signoff_report(
            workflow_report,
            workflow_report_path=args.workflow_report_json,
            evidence_dir=args.workflow_report_json.parent,
            rollout_report=rollout_report,
            operations_review_report=operations_review_report,
            report_input_statuses=[rollout_report_status, operations_report_status],
            raw_text=raw_text,
            signoff_owner=args.signoff_owner,
            release_decision=args.release_decision,
            risk_acceptance=args.risk_acceptance,
            allow_conditional_go=args.allow_conditional_go,
            require_standard_live_sections=not args.no_require_standard_live_sections,
            allow_project_input=args.allow_project_input,
        )
    except ValueError as exc:
        report = {
            "version": M1_PRIVATE_EVIDENCE_SIGNOFF_VERSION,
            "status": "blocked",
            "blocked_reasons": [{"check": "input", "key": "invalid_json", "finding": str(exc)}],
        }
    output_text = (
        build_m1_private_evidence_signoff_markdown(report)
        if args.markdown and not args.json
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
