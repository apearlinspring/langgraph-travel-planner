"""Validate post-cleanup disk remediation evidence.

This checker reads explicit JSON evidence files only. It does not connect SSH,
delete Docker images, run Docker prune, read `.env`, inspect logs, query
databases, read Redis keys or touch backups/vector stores.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISK_REMEDIATION_POST_CLEANUP_VERSION = "disk_remediation_post_cleanup.v1"


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if path is None:
        return None, {"section": "input", "key": f"missing_{label}", "finding": f"{label} JSON path is required."}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {"section": "input", "key": f"cannot_read_{label}", "finding": f"{label} JSON cannot be read."}
    if not isinstance(payload, dict):
        return None, {"section": "input", "key": f"invalid_{label}", "finding": f"{label} JSON must be an object."}
    return payload, None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return str(value or "").strip().lower() or "unknown"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _blocker(section: str, key: str, finding: str) -> dict[str, str]:
    return {"section": section, "key": key, "finding": finding}


def _disk(report: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    return _as_mapping(
        _as_mapping(_as_mapping(report.get("sections")).get("host_capacity")).get("disk")
    ).get(label) or {}


def _capacity_summary(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> dict[str, Any]:
    if after is None:
        return {
            "status": "blocked",
            "blocked_reasons": [_blocker("capacity", "missing_post_capacity", "Post-cleanup capacity snapshot is missing.")],
        }
    before_root = _disk(_as_mapping(before or {}), "root")
    before_deploy = _disk(_as_mapping(before or {}), "deploy")
    after_root = _disk(after, "root")
    after_deploy = _disk(after, "deploy")
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    for label, disk in {"root": after_root, "deploy": after_deploy}.items():
        disk_status = _status(_as_mapping(disk).get("status"))
        if disk_status == "blocked":
            blocked.append(_blocker("capacity", f"{label}_disk_blocked", "Post-cleanup disk remains blocked."))
        elif disk_status == "degraded":
            degraded.append(_blocker("capacity", f"{label}_disk_degraded", "Post-cleanup disk remains above warning threshold."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else _status(after.get("status"))),
        "before_root_free_mb": _to_int(_as_mapping(before_root).get("free_mb")),
        "after_root_free_mb": _to_int(_as_mapping(after_root).get("free_mb")),
        "root_free_delta_mb": _to_int(_as_mapping(after_root).get("free_mb")) - _to_int(_as_mapping(before_root).get("free_mb")),
        "before_deploy_free_mb": _to_int(_as_mapping(before_deploy).get("free_mb")),
        "after_deploy_free_mb": _to_int(_as_mapping(after_deploy).get("free_mb")),
        "deploy_free_delta_mb": _to_int(_as_mapping(after_deploy).get("free_mb")) - _to_int(_as_mapping(before_deploy).get("free_mb")),
        "after_root_used_percent": _to_int(_as_mapping(after_root).get("used_percent"), -1),
        "after_deploy_used_percent": _to_int(_as_mapping(after_deploy).get("used_percent"), -1),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
    }


def _execution_summary(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "status": "blocked",
            "blocked_reasons": [_blocker("execution", "missing_execution", "Docker cleanup execution report is missing.")],
        }
    counts = _as_mapping(report.get("result_counts"))
    deleted = _to_int(counts.get("deleted"))
    failed = _to_int(counts.get("failed"))
    skipped_missing = _to_int(counts.get("skipped_missing"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if _status(report.get("mode")) != "execute":
        blocked.append(_blocker("execution", "not_execute_mode", "Post-cleanup evidence must come from execute mode."))
    if _status(report.get("status")) == "blocked":
        blocked.append(_blocker("execution", "execution_not_passed", "Docker cleanup execution did not fully pass."))
    if failed > 0:
        blocked.append(_blocker("execution", "image_delete_failed", "At least one selected image deletion failed."))
    if deleted == 0:
        degraded.append(_blocker("execution", "no_deleted_images", "No selected image was deleted."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "mode": _status(report.get("mode")),
        "deleted": deleted,
        "failed": failed,
        "skipped_missing": skipped_missing,
        "approval_token_accepted": _as_mapping(report.get("approval")).get("approval_token_accepted") is True,
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
    }


def _restore_summary(report: Mapping[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {
            "status": "blocked",
            "blocked_reasons": [_blocker("restore_feasibility", "missing_restore_feasibility", "Post-cleanup restore feasibility is missing.")],
        }
    space = _as_mapping(_as_mapping(report.get("sections")).get("restore_workspace_space"))
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []
    if _status(report.get("status")) == "blocked" or _status(space.get("status")) == "blocked":
        blocked.append(_blocker("restore_feasibility", "restore_space_still_blocked", "Restore drill workspace still lacks required free space."))
    elif _status(report.get("status")) != "passed":
        degraded.append(_blocker("restore_feasibility", "restore_not_passed", "Restore feasibility has not passed."))
    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "space_status": _status(space.get("status")),
        "effective_free_mb": _to_int(space.get("effective_free_mb")),
        "required_free_mb": _to_int(space.get("required_free_mb")),
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
    }


def build_disk_remediation_post_cleanup_report(
    *,
    execution_report: Mapping[str, Any] | None,
    before_capacity: Mapping[str, Any] | None,
    after_capacity: Mapping[str, Any] | None,
    restore_feasibility: Mapping[str, Any] | None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    execution = _execution_summary(execution_report)
    capacity = _capacity_summary(before_capacity, after_capacity)
    restore = _restore_summary(restore_feasibility)
    sections = {
        "execution": execution,
        "capacity_delta": capacity,
        "restore_feasibility": restore,
    }
    blocked = [
        item
        for section_name, section in sections.items()
        for item in _as_list(_as_mapping(section).get("blocked_reasons"))
        if isinstance(item, Mapping)
    ]
    degraded = [
        item
        for section_name, section in sections.items()
        for item in _as_list(_as_mapping(section).get("degraded_reasons"))
        if isinstance(item, Mapping)
    ]
    status = "blocked" if blocked else ("degraded" if degraded else "passed")
    if restore.get("status") == "blocked" or capacity.get("status") in {"blocked", "degraded"}:
        decision = "storage_expansion_required"
    elif execution.get("status") == "blocked":
        decision = "cleanup_incomplete_manual_review_required"
    elif status == "passed":
        decision = "disk_remediation_evidence_passed"
    else:
        decision = "monitor_before_release"
    return {
        "version": DISK_REMEDIATION_POST_CLEANUP_VERSION,
        "status": status,
        "decision": decision,
        "generated_at": now.isoformat(),
        "policy": {
            "connects_ssh": False,
            "deletes_images": False,
            "runs_docker_prune": False,
            "reads_env_file": False,
            "reads_logs": False,
            "touches_database_or_redis": False,
            "touches_backups_or_vectorstores": False,
            "source_paths_echoed": False,
        },
        "sections": sections,
        "blocked_reasons": [dict(item) for item in blocked],
        "degraded_reasons": [dict(item) for item in degraded],
        "next_actions": [
            "Expand or attach disk space for the deployment host.",
            "Rerun server capacity snapshot after storage remediation.",
            "Rerun restore drill feasibility with the post-remediation capacity report.",
            "Refresh M1 go/no-go evidence before widening traffic.",
        ],
        "not_proven_by_this_report": [
            "This report does not delete images or free disk space.",
            "This report does not prove restore drill success.",
            "This report does not approve M1 release.",
        ],
    }


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_disk_remediation_post_cleanup_markdown(report: Mapping[str, Any]) -> str:
    sections = _as_mapping(report.get("sections"))
    execution = _as_mapping(sections.get("execution"))
    capacity = _as_mapping(sections.get("capacity_delta"))
    restore = _as_mapping(sections.get("restore_feasibility"))
    lines = [
        "# Disk Remediation Post-Cleanup Check",
        "",
        f"- Status: `{_cell(report.get('status'))}`",
        f"- Decision: `{_cell(report.get('decision'))}`",
        "- Policy: no SSH, no deletion, no prune, no `.env`, no logs, no database / Redis / backup / vectorstore access.",
        "",
        "| Area | Status | Evidence |",
        "|---|---|---|",
        f"| Execution | `{_cell(execution.get('status'))}` | deleted={_cell(execution.get('deleted'))}, failed={_cell(execution.get('failed'))}, skipped_missing={_cell(execution.get('skipped_missing'))} |",
        f"| Capacity delta | `{_cell(capacity.get('status'))}` | root_delta={_cell(capacity.get('root_free_delta_mb'))} MB, deploy_delta={_cell(capacity.get('deploy_free_delta_mb'))} MB, used={_cell(capacity.get('after_deploy_used_percent'))}% |",
        f"| Restore feasibility | `{_cell(restore.get('status'))}` | free={_cell(restore.get('effective_free_mb'))}/{_cell(restore.get('required_free_mb'))} MB, space={_cell(restore.get('space_status'))} |",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in _as_list(report.get("blocked_reasons")):
            if isinstance(item, Mapping):
                lines.append(f"- `{_cell(item.get('section'))}.{_cell(item.get('key'))}`: {_cell(item.get('finding'))}")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {_cell(item)}" for item in _as_list(report.get("next_actions")))
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-json", type=_path_arg, required=True)
    parser.add_argument("--before-capacity-json", type=_path_arg, default=None)
    parser.add_argument("--after-capacity-json", type=_path_arg, required=True)
    parser.add_argument("--restore-feasibility-json", type=_path_arg, required=True)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    execution, execution_error = _read_json(args.execution_json, label="execution")
    before_capacity, before_error = _read_json(args.before_capacity_json, label="before_capacity") if args.before_capacity_json else (None, None)
    after_capacity, after_error = _read_json(args.after_capacity_json, label="after_capacity")
    restore, restore_error = _read_json(args.restore_feasibility_json, label="restore_feasibility")
    report = build_disk_remediation_post_cleanup_report(
        execution_report=execution,
        before_capacity=before_capacity,
        after_capacity=after_capacity,
        restore_feasibility=restore,
    )
    read_errors = [item for item in (execution_error, before_error, after_error, restore_error) if item]
    if read_errors:
        report["status"] = "blocked"
        report["decision"] = "cannot_read_required_evidence"
        report["blocked_reasons"] = read_errors + list(report.get("blocked_reasons") or [])
    output_text = (
        build_disk_remediation_post_cleanup_markdown(report)
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
