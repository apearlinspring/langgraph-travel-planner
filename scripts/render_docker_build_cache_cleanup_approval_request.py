"""Render a redacted human approval request for Docker build-cache cleanup.

The renderer reads explicit JSON evidence files only. It does not connect SSH,
read `.env`, delete build cache, prune Docker resources, inspect logs, query
databases or print private paths.
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
DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_REQUEST_VERSION = "docker_build_cache_cleanup_approval_request.v1"


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("evidence JSON must be an object")
    return payload


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return str(value or "").strip().lower() or "unknown"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _section(report: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(report.get("sections")).get(key))


def _finding_count(items: Any) -> int:
    return len([item for item in _as_list(items) if isinstance(item, Mapping)])


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return text.replace("|", "\\|") or "-"


def build_docker_build_cache_cleanup_approval_request(
    *,
    approval_gate: Mapping[str, Any],
    go_no_go: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted build-cache cleanup approval request."""

    now = generated_at or datetime.now(UTC)
    gate = _as_mapping(approval_gate)
    no_go = _as_mapping(go_no_go or {})
    plan = _section(gate, "build_cache_cleanup_plan")
    dry_run = _section(gate, "build_cache_cleanup_dry_run")
    capacity = _section(gate, "capacity_snapshot")
    approval = _section(gate, "approval_record")
    gate_status = _status(gate.get("status"))
    gate_decision = _status(gate.get("decision"))
    request_status = (
        "needs_human_decision"
        if gate_decision == "ready_for_explicit_approval"
        else "blocked"
    )
    request_decision = (
        "request_controlled_docker_build_cache_cleanup_approval"
        if request_status == "needs_human_decision"
        else "do_not_execute_build_cache_cleanup_yet"
    )
    reclaimable_mb = _number(plan.get("reclaimable_mb"))
    root_used_percent = _int(plan.get("root_used_percent"), -1)
    capacity_root_used_percent = _int(capacity.get("root_used_percent"), root_used_percent)
    evidence_summary = {
        "build_cache_cleanup_plan": {
            "status": _status(plan.get("status")),
            "reclaimable_mb": reclaimable_mb,
            "root_used_percent": root_used_percent,
            "root_free_mb": _int(plan.get("root_free_mb")),
        },
        "build_cache_cleanup_dry_run": {
            "status": _status(dry_run.get("status")),
            "prune_result": _status(dry_run.get("prune_result")),
        },
        "capacity_snapshot": {
            "status": _status(capacity.get("status")),
            "root_used_percent": capacity_root_used_percent,
            "root_free_mb": _int(capacity.get("root_free_mb")),
            "deploy_used_percent": _int(capacity.get("deploy_used_percent"), -1),
            "deploy_free_mb": _int(capacity.get("deploy_free_mb")),
        },
        "approval_gate": {
            "status": gate_status,
            "decision": gate_decision,
            "approval_record_present": approval.get("approval_present") is True,
            "approval_status": _status(approval.get("status")),
        },
    }
    return {
        "version": DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_REQUEST_VERSION,
        "status": request_status,
        "decision": request_decision,
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
            "approval_token_echoed": False,
        },
        "gate_summary": {
            "status": gate_status,
            "decision": gate_decision,
            "blocked_reason_count": _finding_count(gate.get("blocked_reasons")),
            "degraded_reason_count": _finding_count(gate.get("degraded_reasons")),
        },
        "go_no_go_summary": {
            "status": _status(no_go.get("status")) if no_go else "not_provided",
            "decision": _status(no_go.get("decision")) if no_go else "not_provided",
            "blocker_count": _finding_count(no_go.get("blockers")),
            "degraded_reason_count": _finding_count(no_go.get("degraded_reasons")),
        },
        "evidence_summary": evidence_summary,
        "human_decision_options": [
            {
                "option": "approve_controlled_build_cache_cleanup",
                "meaning": "Approve deleting Docker build cache only with docker builder prune -a -f.",
                "requires": [
                    "Fill the private build-cache approval record.",
                    "Rerun the approval gate with the filled record.",
                    "Run execute mode only if the decision becomes approved_for_controlled_build_cache_cleanup.",
                ],
            },
            {
                "option": "expand_or_attach_disk",
                "meaning": "Avoid build-cache deletion and increase available disk space before rerunning capacity and restore checks.",
                "requires": [
                    "Apply the infrastructure change outside this script.",
                    "Rerun capacity snapshot and restore feasibility checks.",
                ],
            },
            {
                "option": "postpone_release",
                "meaning": "Keep M1 as no-go or conditional until disk and restore evidence are resolved.",
                "requires": ["Record the decision in the rollout and operations review records."],
            },
        ],
        "pre_execution_commands": [
            "python scripts/check_docker_build_cache_cleanup_approval.py --approval-record-json <private-workdir>/docker-build-cache-cleanup-approval.local.json ...",
            "python scripts/execute_docker_build_cache_cleanup.py --plan-json <private-workdir>/docker-build-cache-cleanup-plan.json --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --execute --approval-token <approval-token> --output <private-workdir>/docker-build-cache-cleanup-execution.json",
        ],
        "post_execution_required_checks": [
            "python scripts/collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --output <private-workdir>/server-capacity-snapshot-post-build-cache-cleanup.json",
            "python scripts/check_restore_drill_feasibility.py --backup-schedule-json <private-workdir>/backup-schedule-live-probe.json --capacity-json <private-workdir>/server-capacity-snapshot-post-build-cache-cleanup.json --output <private-workdir>/restore-drill-feasibility-post-build-cache-cleanup.json",
            "python scripts/check_docker_build_cache_post_cleanup.py --execution-json <private-workdir>/docker-build-cache-cleanup-execution.json --before-capacity-json <private-workdir>/server-capacity-snapshot-post-image-cleanup.json --after-capacity-json <private-workdir>/server-capacity-snapshot-post-build-cache-cleanup.json --restore-feasibility-json <private-workdir>/restore-drill-feasibility-post-build-cache-cleanup.json --output <private-workdir>/docker-build-cache-post-cleanup.json",
            "python scripts/collect_m1_go_no_go_evidence.py --include-docker-build-cache-cleanup-approval --docker-build-cache-cleanup-approval-json <private-workdir>/docker-build-cache-cleanup-approval-gate.json --include-docker-build-cache-post-cleanup --docker-build-cache-post-cleanup-json <private-workdir>/docker-build-cache-post-cleanup.json --output <private-workdir>/m1-current-go-no-go.json",
        ],
        "not_proven_by_this_request": [
            "Human approval has been granted.",
            "Docker build cache has been deleted or disk space has been freed.",
            "Restore drill feasibility has passed after cleanup.",
            "M1 release is allowed to proceed.",
        ],
    }


def render_docker_build_cache_cleanup_approval_request_markdown(report: Mapping[str, Any]) -> str:
    evidence = _as_mapping(report.get("evidence_summary"))
    plan = _as_mapping(evidence.get("build_cache_cleanup_plan"))
    dry_run = _as_mapping(evidence.get("build_cache_cleanup_dry_run"))
    capacity = _as_mapping(evidence.get("capacity_snapshot"))
    gate = _as_mapping(evidence.get("approval_gate"))
    go_no_go = _as_mapping(report.get("go_no_go_summary"))
    lines = [
        "# Docker Build Cache Cleanup Approval Request",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Decision: `{_markdown_cell(report.get('decision'))}`",
        "- Boundary: this request does not connect SSH, delete build cache, run `docker system prune`, read `.env`, read logs, or touch database / Redis / backups / vector stores.",
        "",
        "## Current Release Gate",
        "",
        f"- M1 go/no-go: `{_markdown_cell(go_no_go.get('status'))}` / `{_markdown_cell(go_no_go.get('decision'))}`",
        f"- Blockers: `{_markdown_cell(go_no_go.get('blocker_count'))}`",
        f"- Degraded reasons: `{_markdown_cell(go_no_go.get('degraded_reason_count'))}`",
        f"- Build-cache approval gate: `{_markdown_cell(gate.get('status'))}` / `{_markdown_cell(gate.get('decision'))}`",
        f"- Approval record: `{_markdown_cell(gate.get('approval_status'))}`, present=`{_markdown_cell(gate.get('approval_record_present'))}`",
        "",
        "## Evidence Summary",
        "",
        "| Area | Status | Redacted Evidence |",
        "|---|---|---|",
        (
            "| Build-cache plan | "
            f"`{_markdown_cell(plan.get('status'))}` | "
            f"reclaimable={_markdown_cell(plan.get('reclaimable_mb'))} MB, "
            f"root={_markdown_cell(plan.get('root_used_percent'))}% used / "
            f"{_markdown_cell(plan.get('root_free_mb'))} MB free |"
        ),
        (
            "| Dry-run | "
            f"`{_markdown_cell(dry_run.get('status'))}` | "
            f"prune_result={_markdown_cell(dry_run.get('prune_result'))} |"
        ),
        (
            "| Capacity | "
            f"`{_markdown_cell(capacity.get('status'))}` | "
            f"root={_markdown_cell(capacity.get('root_used_percent'))}% used / "
            f"{_markdown_cell(capacity.get('root_free_mb'))} MB free, "
            f"deploy={_markdown_cell(capacity.get('deploy_used_percent'))}% used / "
            f"{_markdown_cell(capacity.get('deploy_free_mb'))} MB free |"
        ),
        "",
        "## Human Decision Needed",
        "",
    ]
    for item in _as_list(report.get("human_decision_options")):
        option = _as_mapping(item)
        lines.append(f"- `{_markdown_cell(option.get('option'))}`: {_markdown_cell(option.get('meaning'))}")
    lines.extend(["", "## Execution Boundary", ""])
    lines.extend(
        [
            "- Approval can only cover Docker build cache cleanup.",
            "- Approval must not authorize `docker system prune`, image deletion, container deletion, volume deletion, log deletion, `.env` deletion, backup deletion or vectorstore deletion.",
            "- Execute mode is allowed only after the approval gate decision becomes `approved_for_controlled_build_cache_cleanup`.",
            "- After cleanup, capacity, restore feasibility, post-cleanup report and M1 go/no-go must be rerun.",
            "- Future Docker builds may be slower until cache is rebuilt.",
            "",
            "## Command Skeleton",
            "",
            "```powershell",
        ]
    )
    lines.extend(str(command) for command in _as_list(report.get("pre_execution_commands")))
    lines.extend(["", "# After cleanup", *[str(command) for command in _as_list(report.get("post_execution_required_checks"))]])
    lines.extend(["```", "", "## Not Proven", ""])
    lines.extend(f"- {_markdown_cell(item)}" for item in _as_list(report.get("not_proven_by_this_request")))
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-gate-json", type=_path_arg, required=True)
    parser.add_argument("--go-no-go-json", type=_path_arg, default=None)
    parser.add_argument("--output", type=_path_arg, default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        approval_gate = _read_json(args.approval_gate_json)
        go_no_go = _read_json(args.go_no_go_json) if args.go_no_go_json else None
        report = build_docker_build_cache_cleanup_approval_request(
            approval_gate=approval_gate,
            go_no_go=go_no_go,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        report = {
            "version": DOCKER_BUILD_CACHE_CLEANUP_APPROVAL_REQUEST_VERSION,
            "status": "blocked",
            "decision": "cannot_read_evidence",
            "policy": {"source_paths_echoed": False},
            "blocked_reasons": [{"key": "evidence_read_failed", "finding": "Evidence JSON could not be read."}],
        }
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.json
        else render_docker_build_cache_cleanup_approval_request_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
