"""Validate a private disk-remediation approval record.

This checker ties together redacted Docker cleanup plan evidence, dry-run
evidence, capacity evidence and restore-drill feasibility evidence. It does not
connect to SSH, read `.env`, delete Docker images, prune Docker resources, read
logs, inspect database rows, read Redis keys or touch backup/vectorstore files.
"""
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
    as_list as _as_list,
    as_mapping as _as_mapping,
    has_text as _has_text,
    is_ready as _is_ready,
    make_final_text_checker,
    make_path_arg,
    make_placeholder_checker,
    read_optional_json_object as _read_json,
)


DISK_REMEDIATION_APPROVAL_VERSION = "disk_remediation_approval.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
APPROVAL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{5,80}$")


_path_arg = make_path_arg(PROJECT_ROOT)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=(),
)
_has_final_text = make_final_text_checker(_looks_placeholder)


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _blocker(key: str, finding: str) -> dict[str, str]:
    return {"key": key, "finding": finding}


def _evidence_cleanup_plan(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {"status": "blocked", "blocked_reasons": [_blocker("missing_cleanup_plan", "Cleanup plan is missing.")]}
    images = _as_mapping(plan.get("images"))
    selected = _as_list(plan.get("selected_candidates"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if _status(plan.get("status")) == "blocked":
        blocked.append(_blocker("cleanup_plan_blocked", "Cleanup plan is blocked."))
    if not selected:
        blocked.append(_blocker("no_selected_candidates", "Cleanup plan has no selected candidates."))
    if not _as_mapping(plan.get("approval_required")).get("required_for_execution"):
        blocked.append(_blocker("approval_requirement_missing", "Cleanup plan must require explicit approval."))
    if _status(plan.get("status")) == "degraded":
        degraded.append(_blocker("disk_pressure", "Cleanup plan is degraded due disk pressure or operational attention."))
    protected_selected = [
        item for item in selected if isinstance(item, Mapping) and bool(item.get("protected"))
    ]
    if protected_selected:
        blocked.append(_blocker("protected_candidate_selected", "Selected candidates include protected container-referenced images."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "plan_status": _status(plan.get("status")) or "unknown",
        "risk_status": str(plan.get("risk_status") or ""),
        "total_images": _to_int(images.get("total_count")),
        "protected_images": _to_int(images.get("protected_count")),
        "candidate_images": _to_int(images.get("candidate_count")),
        "selected_images": len(selected),
        "estimated_selected_size_mb": images.get("estimated_selected_size_mb", 0),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "path_echoed": False,
    }


def _evidence_dry_run(dry_run: Mapping[str, Any] | None, *, expected_selected: int) -> dict[str, Any]:
    if dry_run is None:
        return {"status": "blocked", "blocked_reasons": [_blocker("missing_dry_run", "Docker cleanup dry-run is missing.")]}
    counts = _as_mapping(dry_run.get("result_counts"))
    dry_run_count = _to_int(counts.get("dry_run"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if _status(dry_run.get("status")) != "passed":
        blocked.append(_blocker("dry_run_not_passed", "Docker cleanup dry-run must pass before approval."))
    if _status(dry_run.get("mode")) != "dry_run":
        blocked.append(_blocker("not_dry_run", "Evidence must come from dry-run mode."))
    if _as_mapping(dry_run.get("policy")).get("deletes_images") is not False:
        blocked.append(_blocker("dry_run_deleted_images", "Dry-run evidence must not delete images."))
    if expected_selected > 0 and dry_run_count < expected_selected:
        degraded.append(_blocker("dry_run_count_below_plan", "Dry-run result count is lower than selected plan count."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "dry_run_count": dry_run_count,
        "expected_selected": expected_selected,
        "result_counts": dict(counts),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "path_echoed": False,
    }


def _evidence_capacity(capacity: Mapping[str, Any] | None) -> dict[str, Any]:
    if capacity is None:
        return {"status": "blocked", "blocked_reasons": [_blocker("missing_capacity", "Capacity snapshot is missing.")]}
    sections = _as_mapping(capacity.get("sections"))
    host = _as_mapping(sections.get("host_capacity"))
    container = _as_mapping(sections.get("container_capacity"))
    disks = _as_mapping(host.get("disk"))
    root = _as_mapping(disks.get("root"))
    deploy = _as_mapping(disks.get("deploy"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if _status(capacity.get("status")) == "blocked":
        blocked.append(_blocker("capacity_blocked", "Capacity snapshot is blocked."))
    if _status(container.get("status")) == "blocked":
        blocked.append(_blocker("container_capacity_blocked", "Container capacity is blocked."))
    for key, disk in {"root": root, "deploy": deploy}.items():
        if _status(disk.get("status")) == "blocked":
            blocked.append(_blocker(f"{key}_disk_blocked", "Disk is at or above fail threshold."))
        elif _status(disk.get("status")) == "degraded":
            degraded.append(_blocker(f"{key}_disk_degraded", "Disk is above warning threshold."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "capacity_status": _status(capacity.get("status")) or "unknown",
        "container_status": _status(container.get("status")) or "unknown",
        "root_free_mb": _to_int(root.get("free_mb")),
        "root_used_percent": _to_int(root.get("used_percent"), -1),
        "deploy_free_mb": _to_int(deploy.get("free_mb")),
        "deploy_used_percent": _to_int(deploy.get("used_percent"), -1),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "path_echoed": False,
    }


def _evidence_restore_feasibility(feasibility: Mapping[str, Any] | None) -> dict[str, Any]:
    if feasibility is None:
        return {
            "status": "blocked",
            "blocked_reasons": [_blocker("missing_restore_feasibility", "Restore-drill feasibility evidence is missing.")],
        }
    sections = _as_mapping(feasibility.get("sections"))
    backup = _as_mapping(sections.get("postgres_backup"))
    space = _as_mapping(sections.get("restore_workspace_space"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if _status(backup.get("status")) != "passed":
        blocked.append(_blocker("restore_backup_input_not_passed", "Restore feasibility lacks passed backup input evidence."))
    if _status(space.get("status")) == "blocked":
        degraded.append(_blocker("restore_space_blocked", "Restore drill is currently blocked by workspace space."))
    elif _status(feasibility.get("status")) == "blocked":
        blocked.append(_blocker("restore_feasibility_blocked", "Restore feasibility is blocked for a non-space reason."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else (_status(feasibility.get("status")) or "unknown")),
        "backup_input_status": _status(backup.get("status")) or "unknown",
        "space_status": _status(space.get("status")) or "unknown",
        "effective_free_mb": _to_int(space.get("effective_free_mb")),
        "required_free_mb": _to_int(space.get("required_free_mb")),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded + [
            dict(item) for item in feasibility.get("degraded_reasons") or [] if isinstance(item, Mapping)
        ],
        "path_echoed": False,
    }


def _approval_template(max_delete_count: int = 20) -> dict[str, Any]:
    return {
        "approval_id": "<docker-disk-remediation-YYYYMMDD>",
        "approved_by_role": "<operator role, not a personal contact>",
        "approved_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "delete only selected Docker image candidates from the latest redacted cleanup plan",
        "max_delete_count": max_delete_count,
        "evidence_review": {
            "cleanup_plan_reviewed": "passed",
            "dry_run_reviewed": "passed",
            "capacity_pressure_acknowledged": "passed",
            "restore_drill_blocker_acknowledged": "passed",
        },
        "allowed_actions": {
            "delete_selected_docker_images": True,
        },
        "forbidden_actions": {
            "docker_system_prune": True,
            "delete_containers": True,
            "delete_volumes": True,
            "delete_logs": True,
            "delete_env_files": True,
            "delete_backups": True,
            "delete_vectorstores": True,
        },
        "post_cleanup_required": {
            "rerun_capacity_snapshot": True,
            "rerun_restore_drill_feasibility": True,
            "rerun_live_health_probe": True,
        },
        "redaction_boundary": {
            "raw_paths_included": False,
            "server_ip_included": False,
            "secret_values_included": False,
            "log_lines_included": False,
        },
    }


def _approval_check(record: Mapping[str, Any] | None, *, selected_count: int) -> dict[str, Any]:
    if record is None:
        return {
            "status": "blocked",
            "finding": "Explicit private approval record is missing.",
            "blocked_reasons": [_blocker("missing_approval_record", "Explicit approval record is required before execution.")],
            "template": _approval_template(max_delete_count=selected_count or 20),
            "approval_record_echoed": False,
        }
    blocked: list[dict[str, str]] = []
    for field in ("approval_id", "approved_by_role", "approved_at", "scope"):
        if not _has_final_text(record.get(field)):
            blocked.append(_blocker(field, f"{field} is missing or placeholder-like."))
    approval_id = str(record.get("approval_id") or "")
    if _has_final_text(approval_id) and not APPROVAL_ID_PATTERN.match(approval_id):
        blocked.append(_blocker("approval_id_format", "approval_id must be short and redacted."))
    max_delete_count = _to_int(record.get("max_delete_count"), -1)
    if max_delete_count <= 0:
        blocked.append(_blocker("max_delete_count", "max_delete_count must be positive."))
    if selected_count and max_delete_count > selected_count:
        blocked.append(_blocker("max_delete_count_scope", "max_delete_count cannot exceed selected candidate count."))
    evidence = _as_mapping(record.get("evidence_review"))
    for field in (
        "cleanup_plan_reviewed",
        "dry_run_reviewed",
        "capacity_pressure_acknowledged",
        "restore_drill_blocker_acknowledged",
    ):
        if not _is_ready(evidence.get(field)):
            blocked.append(_blocker(f"evidence_review.{field}", f"{field} must be acknowledged."))
    allowed = _as_mapping(record.get("allowed_actions"))
    if allowed.get("delete_selected_docker_images") is not True:
        blocked.append(_blocker("allowed_actions.delete_selected_docker_images", "Approval must explicitly allow selected image deletion."))
    forbidden = _as_mapping(record.get("forbidden_actions"))
    for field in (
        "docker_system_prune",
        "delete_containers",
        "delete_volumes",
        "delete_logs",
        "delete_env_files",
        "delete_backups",
        "delete_vectorstores",
    ):
        if forbidden.get(field) is not True:
            blocked.append(_blocker(f"forbidden_actions.{field}", f"{field} must be explicitly forbidden."))
    post = _as_mapping(record.get("post_cleanup_required"))
    for field in ("rerun_capacity_snapshot", "rerun_restore_drill_feasibility", "rerun_live_health_probe"):
        if post.get(field) is not True:
            blocked.append(_blocker(f"post_cleanup_required.{field}", f"{field} must be required."))
    boundary = _as_mapping(record.get("redaction_boundary"))
    for field in ("raw_paths_included", "server_ip_included", "secret_values_included", "log_lines_included"):
        if boundary.get(field) is not False:
            blocked.append(_blocker(f"redaction_boundary.{field}", f"{field} must be false."))
    return {
        "status": "blocked" if blocked else "passed",
        "approval_id_present": _has_text(record.get("approval_id")),
        "max_delete_count": max_delete_count,
        "blocked_reasons": blocked,
        "approval_record_echoed": False,
    }


def _collect_blockers(sections: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocked: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    for section_name, section in sections.items():
        for item in section.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                blocked.append({"section": section_name, **dict(item)})
        for item in section.get("degraded_reasons") or []:
            if isinstance(item, Mapping):
                degraded.append({"section": section_name, **dict(item)})
    return blocked, degraded


def build_disk_remediation_approval_report(
    *,
    cleanup_plan: Mapping[str, Any] | None,
    dry_run: Mapping[str, Any] | None,
    capacity: Mapping[str, Any] | None,
    restore_feasibility: Mapping[str, Any] | None,
    approval_record: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted disk-remediation approval gate report."""

    now = generated_at or datetime.now(UTC)
    plan = _evidence_cleanup_plan(cleanup_plan)
    dry_run_evidence = _evidence_dry_run(dry_run, expected_selected=_to_int(plan.get("selected_images")))
    capacity_evidence = _evidence_capacity(capacity)
    restore = _evidence_restore_feasibility(restore_feasibility)
    approval = _approval_check(approval_record, selected_count=_to_int(plan.get("selected_images")))
    sections = {
        "cleanup_plan": plan,
        "dry_run": dry_run_evidence,
        "capacity": capacity_evidence,
        "restore_feasibility": restore,
        "approval": approval,
    }
    blocked, degraded = _collect_blockers(sections)
    evidence_blocked = any(
        item.get("section") in {"cleanup_plan", "dry_run", "capacity"} for item in blocked
    )
    approval_missing = approval.get("status") == "blocked" and not approval_record
    status = "blocked" if blocked else ("degraded" if degraded else "passed")
    if approval_missing and not evidence_blocked:
        decision = "ready_for_explicit_approval"
    elif approval.get("status") == "passed" and not evidence_blocked:
        decision = "approved_for_controlled_cleanup"
    elif evidence_blocked:
        decision = "not_ready_for_cleanup"
    else:
        decision = "approval_record_incomplete"
    return {
        "version": DISK_REMEDIATION_APPROVAL_VERSION,
        "status": status,
        "decision": decision,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_prune": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "touches_backups": False,
            "touches_vectorstores": False,
            "approval_token_recorded": False,
            "path_echoed": False,
        },
        "sections": sections,
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "declaration_statuses": {
            "ZHIXING_DISK_REMEDIATION_APPROVAL_STATUS": status,
            "ZHIXING_DOCKER_CLEANUP_EXECUTION_DECISION": decision,
        },
        "next_commands": [
            "Fill private docker-disk-remediation-approval.local.json from the generated template.",
            "Run this checker again with --approval-record-json before any execute mode.",
            "Only after explicit approval: run execute_docker_disk_cleanup.py with --execute and the one-time approval token.",
            "After execution: rerun server capacity snapshot and restore drill feasibility checks.",
        ],
        "not_proven_by_this_report": [
            "This report does not delete Docker images or free disk space.",
            "A valid approval still requires the execution script to recheck container-referenced images before deletion.",
            "A successful cleanup must be followed by capacity and restore-feasibility rechecks.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_disk_remediation_approval_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Disk Remediation Approval Gate",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Decision: `{_markdown_cell(report.get('decision'))}`",
        "- Policy: no SSH, no deletion, no prune, no `.env`, no logs, no backup/vectorstore access.",
        "",
        "## Sections",
        "",
        "| Section | Status | Key evidence |",
        "|---|---|---|",
    ]
    sections = _as_mapping(report.get("sections"))
    plan = _as_mapping(sections.get("cleanup_plan"))
    dry_run = _as_mapping(sections.get("dry_run"))
    capacity = _as_mapping(sections.get("capacity"))
    restore = _as_mapping(sections.get("restore_feasibility"))
    approval = _as_mapping(sections.get("approval"))
    rows = [
        ("cleanup_plan", plan.get("status"), f"selected={plan.get('selected_images')}, estimated_mb={plan.get('estimated_selected_size_mb')}"),
        ("dry_run", dry_run.get("status"), f"dry_run={dry_run.get('dry_run_count')}, expected={dry_run.get('expected_selected')}"),
        ("capacity", capacity.get("status"), f"root_used={capacity.get('root_used_percent')}%, deploy_used={capacity.get('deploy_used_percent')}%"),
        ("restore_feasibility", restore.get("status"), f"space={restore.get('space_status')}, free={restore.get('effective_free_mb')}/{restore.get('required_free_mb')} MB"),
        ("approval", approval.get("status"), f"approval_id_present={approval.get('approval_id_present')}"),
    ]
    for name, status, evidence in rows:
        lines.append(f"| `{name}` | `{_markdown_cell(status)}` | {_markdown_cell(evidence)} |")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Next Commands", ""])
    for item in report.get("next_commands") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup-plan-json", type=_path_arg, default=None)
    parser.add_argument("--dry-run-json", type=_path_arg, default=None)
    parser.add_argument("--capacity-json", type=_path_arg, default=None)
    parser.add_argument("--restore-feasibility-json", type=_path_arg, default=None)
    parser.add_argument("--approval-record-json", type=_path_arg, default=None)
    parser.add_argument("--template", action="store_true", help="Print a private approval-record template.")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        output_text = json.dumps(_approval_template(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output_text, encoding="utf-8")
        else:
            print(output_text, end="")
        return 0

    cleanup_plan, cleanup_error = _read_json(args.cleanup_plan_json, label="cleanup_plan")
    dry_run, dry_run_error = _read_json(args.dry_run_json, label="dry_run")
    capacity, capacity_error = _read_json(args.capacity_json, label="capacity")
    restore_feasibility, restore_error = _read_json(args.restore_feasibility_json, label="restore_feasibility")
    approval_record, approval_error = _read_json(args.approval_record_json, label="approval_record") if args.approval_record_json else (None, None)
    report = build_disk_remediation_approval_report(
        cleanup_plan=cleanup_plan,
        dry_run=dry_run,
        capacity=capacity,
        restore_feasibility=restore_feasibility,
        approval_record=approval_record,
    )
    read_errors = [
        item for item in (cleanup_error, dry_run_error, capacity_error, restore_error, approval_error) if item
    ]
    if read_errors:
        report["status"] = "blocked"
        report["decision"] = "not_ready_for_cleanup"
        report["blocked_reasons"] = [{"section": "input", **item} for item in read_errors] + list(report.get("blocked_reasons") or [])
        report["declaration_statuses"]["ZHIXING_DISK_REMEDIATION_APPROVAL_STATUS"] = "blocked"
        report["declaration_statuses"]["ZHIXING_DOCKER_CLEANUP_EXECUTION_DECISION"] = "not_ready_for_cleanup"
    output_text = (
        build_disk_remediation_approval_markdown(report)
        if args.markdown and not args.json
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
