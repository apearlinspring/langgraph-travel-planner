"""Validate a private Docker build-cache cleanup approval record.

This checker reads explicit JSON evidence files only. It does not connect SSH,
delete build cache, run Docker prune, read `.env`, inspect logs, query
databases, read Redis keys or touch backups/vector stores.
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
DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_VERSION = "docker_build_cache_cleanup_approval.v1"
PLAN_VERSION = "docker_build_cache_cleanup_plan.v1"
DRY_RUN_VERSION = "docker_build_cache_cleanup_execution.v1"
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "ok", "done"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
APPROVAL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{5,80}$")


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, {"key": f"missing_{label}", "finding": f"{label} JSON path is required.", "path_echoed": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {"key": f"unreadable_{label}", "finding": f"{label} JSON could not be read.", "path_echoed": False}
    if not isinstance(payload, dict):
        return None, {"key": f"invalid_{label}", "finding": f"{label} JSON must be an object.", "path_echoed": False}
    return payload, None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _looks_placeholder(value: Any) -> bool:
    text = str(value or "").strip().strip("'\"").lower()
    if text in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(text.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _has_final_text(value: Any) -> bool:
    return bool(str(value or "").strip()) and not _looks_placeholder(value)


def _is_ready(value: Any) -> bool:
    return str(value or "").strip().lower() in READY_VALUES


def _blocker(key: str, finding: str) -> dict[str, str]:
    return {"key": key, "finding": finding}


def _approval_template() -> dict[str, Any]:
    return {
        "approval_id": "<docker-build-cache-cleanup-YYYYMMDD>",
        "approved_by_role": "<operator role, not a personal contact>",
        "approved_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "delete Docker build cache only using docker builder prune -a -f",
        "reason": "Image cleanup has already removed reclaimable images, but disk usage remains high and build cache is reclaimable.",
        "evidence_reviewed": {
            "build_cache_cleanup_plan": True,
            "build_cache_cleanup_dry_run": True,
            "capacity_snapshot": True,
            "future_build_slowdown_accepted": True,
        },
        "allowed_actions": {
            "delete_docker_build_cache": True,
        },
        "forbidden_actions_confirmed": {
            "docker_system_prune": True,
            "delete_images": True,
            "delete_containers": True,
            "delete_volumes": True,
            "delete_logs": True,
            "delete_env_files": True,
            "delete_backups": True,
            "delete_vectorstores": True,
            "read_env_files": True,
            "read_logs": True,
            "query_database_rows": True,
            "read_redis_keys": True,
        },
        "post_execution_required_checks": {
            "capacity_snapshot_rerun": True,
            "restore_drill_feasibility_rerun": True,
            "m1_go_no_go_rerun": True,
        },
        "notes": "<why this is safe enough for M1 controlled trial>",
    }


def _evidence_plan(plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {"status": "blocked", "blocked_reasons": [_blocker("missing_plan", "Build-cache cleanup plan is missing.")]}
    policy = _as_mapping(plan.get("policy"))
    build_cache = _as_mapping(plan.get("build_cache"))
    approval = _as_mapping(plan.get("approval_required"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if plan.get("version") != PLAN_VERSION:
        blocked.append(_blocker("invalid_plan_version", "Build-cache cleanup plan version is invalid."))
    if _status(plan.get("status")) == "blocked":
        blocked.append(_blocker("plan_blocked", "Build-cache cleanup plan is blocked."))
    if policy.get("read_only") is not True:
        blocked.append(_blocker("plan_not_read_only", "Build-cache cleanup plan must be read-only."))
    if policy.get("deletes_build_cache") is not False:
        blocked.append(_blocker("plan_deletes_cache", "Build-cache cleanup plan must not delete cache."))
    if policy.get("runs_system_prune") is not False:
        blocked.append(_blocker("plan_runs_system_prune", "Build-cache cleanup plan must not run docker system prune."))
    for key in ("deletes_images", "deletes_containers", "deletes_volumes"):
        if policy.get(key) is not False:
            blocked.append(_blocker(f"plan_{key}", f"Build-cache cleanup plan must not set {key}."))
    reclaimable_mb = _to_float(build_cache.get("reclaimable_mb"))
    if reclaimable_mb <= 0:
        blocked.append(_blocker("no_reclaimable_build_cache", "Build-cache cleanup plan has no reclaimable build cache."))
    if approval.get("required_for_execution") is not True:
        blocked.append(_blocker("approval_not_required", "Build-cache cleanup plan must require explicit approval."))
    if _status(plan.get("status")) == "degraded":
        degraded.append(_blocker("build_cache_or_disk_degraded", "Build-cache cleanup plan is degraded and needs operator attention."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "plan_status": _status(plan.get("status")) or "unknown",
        "reclaimable_mb": reclaimable_mb,
        "root_free_mb": _to_int(_as_mapping(_as_mapping(plan.get("disk")).get("root")).get("free_mb")),
        "root_used_percent": _to_int(_as_mapping(_as_mapping(plan.get("disk")).get("root")).get("used_percent"), -1),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "path_echoed": False,
    }


def _evidence_dry_run(dry_run: Mapping[str, Any] | None) -> dict[str, Any]:
    if dry_run is None:
        return {"status": "blocked", "blocked_reasons": [_blocker("missing_dry_run", "Build-cache cleanup dry-run is missing.")]}
    policy = _as_mapping(dry_run.get("policy"))
    prune = _as_mapping(dry_run.get("prune"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if dry_run.get("version") != DRY_RUN_VERSION:
        blocked.append(_blocker("invalid_dry_run_version", "Build-cache cleanup dry-run version is invalid."))
    if _status(dry_run.get("mode")) != "dry_run":
        blocked.append(_blocker("not_dry_run", "Evidence must come from dry-run mode."))
    if _status(prune.get("result")) != "dry_run":
        blocked.append(_blocker("prune_not_dry_run", "Prune result must be dry_run before approval."))
    if policy.get("deletes_build_cache") is not False:
        blocked.append(_blocker("dry_run_deleted_cache", "Dry-run evidence must not delete build cache."))
    if policy.get("runs_system_prune") is not False:
        blocked.append(_blocker("dry_run_system_prune", "Dry-run evidence must not run docker system prune."))
    if _status(dry_run.get("status")) == "blocked":
        blocked.append(_blocker("dry_run_blocked", "Build-cache cleanup dry-run is blocked."))
    elif _status(dry_run.get("status")) == "degraded":
        degraded.append(_blocker("dry_run_degraded", "Dry-run remains degraded because cache or disk is still high."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "dry_run_status": _status(dry_run.get("status")) or "unknown",
        "prune_result": _status(prune.get("result")) or "unknown",
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "path_echoed": False,
    }


def _evidence_capacity(capacity: Mapping[str, Any] | None) -> dict[str, Any]:
    if capacity is None:
        return {"status": "blocked", "blocked_reasons": [_blocker("missing_capacity", "Capacity snapshot is missing.")]}
    host = _as_mapping(_as_mapping(capacity.get("sections")).get("host_capacity"))
    disks = _as_mapping(host.get("disk"))
    root = _as_mapping(disks.get("root"))
    deploy = _as_mapping(disks.get("deploy"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    for key, disk in {"root": root, "deploy": deploy}.items():
        disk_status = _status(disk.get("status"))
        if disk_status == "blocked":
            blocked.append(_blocker(f"{key}_disk_blocked", "Disk is at or above fail threshold."))
        elif disk_status == "degraded":
            degraded.append(_blocker(f"{key}_disk_degraded", "Disk is above warning threshold."))
    if _status(capacity.get("status")) == "blocked":
        blocked.append(_blocker("capacity_blocked", "Capacity snapshot is blocked."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else (_status(capacity.get("status")) or "unknown")),
        "root_free_mb": _to_int(root.get("free_mb")),
        "root_used_percent": _to_int(root.get("used_percent"), -1),
        "deploy_free_mb": _to_int(deploy.get("free_mb")),
        "deploy_used_percent": _to_int(deploy.get("used_percent"), -1),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "path_echoed": False,
    }


def _approval_status(approval: Mapping[str, Any] | None) -> dict[str, Any]:
    if approval is None:
        return {
            "status": "not_checked",
            "decision": "ready_for_explicit_approval",
            "blocked_reasons": [],
            "degraded_reasons": [_blocker("approval_record_missing", "Approval record has not been supplied yet.")],
            "approval_present": False,
        }
    blocked: list[dict[str, str]] = []
    if not APPROVAL_ID_PATTERN.match(str(approval.get("approval_id") or "")):
        blocked.append(_blocker("invalid_approval_id", "approval_id must be a stable non-placeholder identifier."))
    for key in ("approved_by_role", "approved_at", "scope", "reason", "notes"):
        if not _has_final_text(approval.get(key)):
            blocked.append(_blocker(f"missing_{key}", f"{key} must be filled with non-placeholder text."))
    allowed = _as_mapping(approval.get("allowed_actions"))
    if allowed.get("delete_docker_build_cache") is not True:
        blocked.append(_blocker("build_cache_cleanup_not_allowed", "Approval must explicitly allow Docker build-cache cleanup."))
    forbidden = _as_mapping(approval.get("forbidden_actions_confirmed"))
    for key in (
        "docker_system_prune",
        "delete_images",
        "delete_containers",
        "delete_volumes",
        "delete_logs",
        "delete_env_files",
        "delete_backups",
        "delete_vectorstores",
        "read_env_files",
        "read_logs",
        "query_database_rows",
        "read_redis_keys",
    ):
        if forbidden.get(key) is not True:
            blocked.append(_blocker(f"forbidden_{key}_not_confirmed", f"Approval must explicitly forbid {key}."))
    reviewed = _as_mapping(approval.get("evidence_reviewed"))
    for key in ("build_cache_cleanup_plan", "build_cache_cleanup_dry_run", "capacity_snapshot", "future_build_slowdown_accepted"):
        if reviewed.get(key) is not True:
            blocked.append(_blocker(f"evidence_{key}_not_reviewed", f"Approval must confirm {key}."))
    post = _as_mapping(approval.get("post_execution_required_checks"))
    for key in ("capacity_snapshot_rerun", "restore_drill_feasibility_rerun", "m1_go_no_go_rerun"):
        if post.get(key) is not True:
            blocked.append(_blocker(f"post_check_{key}_missing", f"Approval must require {key}."))
    return {
        "status": "blocked" if blocked else "passed",
        "decision": "approval_invalid" if blocked else "approval_passed",
        "blocked_reasons": blocked,
        "degraded_reasons": [],
        "approval_present": True,
    }


def build_docker_build_cache_cleanup_approval_report(
    *,
    plan: Mapping[str, Any] | None,
    dry_run: Mapping[str, Any] | None,
    capacity: Mapping[str, Any] | None,
    approval: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    plan_evidence = _evidence_plan(plan)
    dry_run_evidence = _evidence_dry_run(dry_run)
    capacity_evidence = _evidence_capacity(capacity)
    approval_evidence = _approval_status(approval)
    sections = {
        "build_cache_cleanup_plan": plan_evidence,
        "build_cache_cleanup_dry_run": dry_run_evidence,
        "capacity_snapshot": capacity_evidence,
        "approval_record": approval_evidence,
    }
    blockers = [
        dict(item)
        for section in sections.values()
        for item in _as_list(_as_mapping(section).get("blocked_reasons"))
        if isinstance(item, Mapping)
    ]
    degraded = [
        dict(item)
        for section in sections.values()
        for item in _as_list(_as_mapping(section).get("degraded_reasons"))
        if isinstance(item, Mapping)
    ]
    if blockers:
        status = "blocked"
        decision = "not_ready_for_build_cache_cleanup"
    elif approval is None:
        status = "degraded"
        decision = "ready_for_explicit_approval"
    else:
        status = "passed"
        decision = "approved_for_controlled_build_cache_cleanup"
    return {
        "version": DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_VERSION,
        "status": status,
        "decision": decision,
        "generated_at": now.isoformat(),
        "policy": {
            "connects_ssh": False,
            "deletes_build_cache": False,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_system_prune": False,
            "reads_env_file": False,
            "reads_logs": False,
            "touches_database_or_redis": False,
            "touches_backups_or_vectorstores": False,
            "source_paths_echoed": False,
        },
        "sections": sections,
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
        "execution_command_after_approval": (
            "python scripts/execute_docker_build_cache_cleanup.py --plan-json "
            "<private-workdir>/docker-build-cache-cleanup-plan.json --ssh-target "
            "<ssh-user>@<server-host> --deploy-dir <deploy-dir> --execute "
            "--approval-token APPROVE_DOCKER_BUILD_CACHE_CLEANUP"
        ),
        "not_proven_by_this_report": [
            "This report does not approve execution unless a valid approval record is supplied.",
            "This report does not connect SSH or delete build cache.",
            "Build-cache cleanup can make future Docker builds slower until cache is rebuilt.",
            "Post-cleanup capacity, restore feasibility and M1 go/no-go must still be rerun.",
        ],
    }


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_docker_build_cache_cleanup_approval_markdown(report: Mapping[str, Any]) -> str:
    sections = _as_mapping(report.get("sections"))
    plan = _as_mapping(sections.get("build_cache_cleanup_plan"))
    dry_run = _as_mapping(sections.get("build_cache_cleanup_dry_run"))
    capacity = _as_mapping(sections.get("capacity_snapshot"))
    approval = _as_mapping(sections.get("approval_record"))
    lines = [
        "# Docker Build Cache Cleanup Approval Gate",
        "",
        f"- Status: `{_cell(report.get('status'))}`",
        f"- Decision: `{_cell(report.get('decision'))}`",
        "- Policy: no SSH, no deletion, no system prune, no `.env`, no logs, no database / Redis / backup / vectorstore access.",
        "",
        "| Area | Status | Evidence |",
        "|---|---|---|",
        f"| Plan | `{_cell(plan.get('status'))}` | reclaimable={_cell(plan.get('reclaimable_mb'))} MB, root_used={_cell(plan.get('root_used_percent'))}% |",
        f"| Dry-run | `{_cell(dry_run.get('status'))}` | result={_cell(dry_run.get('prune_result'))} |",
        f"| Capacity | `{_cell(capacity.get('status'))}` | free={_cell(capacity.get('root_free_mb'))} MB, used={_cell(capacity.get('root_used_percent'))}% |",
        f"| Approval record | `{_cell(approval.get('status'))}` | present={_cell(approval.get('approval_present'))} |",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in _as_list(report.get("blocked_reasons")):
            if isinstance(item, Mapping):
                lines.append(f"- `{_cell(item.get('key'))}`: {_cell(item.get('finding'))}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in _as_list(report.get("degraded_reasons")):
            if isinstance(item, Mapping):
                lines.append(f"- `{_cell(item.get('key'))}`: {_cell(item.get('finding'))}")
    lines.extend(["", "## Not Proven", ""])
    for item in _as_list(report.get("not_proven_by_this_report")):
        lines.append(f"- {_cell(item)}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", action="store_true", help="Write a private approval record template.")
    parser.add_argument("--plan-json", type=_path_arg, default=None)
    parser.add_argument("--dry-run-json", type=_path_arg, default=None)
    parser.add_argument("--capacity-json", type=_path_arg, default=None)
    parser.add_argument("--approval-record-json", type=_path_arg, default=None)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        output = json.dumps(_approval_template(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0
    plan, plan_error = _read_json(args.plan_json, label="plan")
    dry_run, dry_run_error = _read_json(args.dry_run_json, label="dry_run")
    capacity, capacity_error = _read_json(args.capacity_json, label="capacity")
    approval, approval_error = _read_json(args.approval_record_json, label="approval") if args.approval_record_json else (None, None)
    report = build_docker_build_cache_cleanup_approval_report(
        plan=plan,
        dry_run=dry_run,
        capacity=capacity,
        approval=approval,
    )
    read_errors = [item for item in (plan_error, dry_run_error, capacity_error, approval_error) if item]
    if read_errors:
        report["status"] = "blocked"
        report["decision"] = "cannot_read_required_evidence"
        report["blocked_reasons"] = read_errors + list(report.get("blocked_reasons") or [])
    output_text = (
        build_docker_build_cache_cleanup_approval_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
