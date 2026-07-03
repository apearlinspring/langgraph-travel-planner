"""Render a redacted storage expansion request from private evidence.

The renderer reads explicit JSON reports only. It does not connect SSH, expand
disks, mount filesystems, migrate Docker data, read `.env`, inspect logs, query
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
STORAGE_EXPANSION_REQUEST_VERSION = "storage_expansion_request.v1"


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON evidence must be an object")
    return payload


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


def _section(report: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(_as_mapping(report.get("sections")).get(key))


def _disk(storage_readiness: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _as_mapping(_section(storage_readiness, "disk_usage").get(key))


def build_storage_expansion_request(
    *,
    storage_readiness: Mapping[str, Any],
    post_cleanup: Mapping[str, Any] | None = None,
    go_no_go: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    storage = _as_mapping(storage_readiness)
    post = _as_mapping(post_cleanup or {})
    no_go = _as_mapping(go_no_go or {})
    recommendation = _section(storage, "recommendation")
    restore = _section(storage, "restore_workspace")
    topology = _section(storage, "block_topology")
    sharing = _section(storage, "mount_sharing")
    root = _disk(storage, "root")
    deploy = _disk(storage, "deploy")
    docker_root = _disk(storage, "docker_data_root")
    post_capacity = _section(post, "capacity_delta")
    post_execution = _section(post, "execution")
    strategy = str(recommendation.get("strategy") or "storage_expansion_required")
    request_status = "ready_for_infra_change" if _status(storage.get("decision")) == "storage_expansion_required" else "not_required"
    min_additional_free_mb = _to_int(recommendation.get("min_additional_free_mb"))
    suggested_new_free_mb = _to_int(recommendation.get("suggested_new_free_mb"))
    return {
        "version": STORAGE_EXPANSION_REQUEST_VERSION,
        "status": request_status,
        "decision": strategy,
        "generated_at": now.isoformat(),
        "policy": {
            "connects_ssh": False,
            "expands_disk": False,
            "mounts_filesystem": False,
            "migrates_docker_data": False,
            "reads_env_file": False,
            "reads_logs": False,
            "touches_database_or_redis": False,
            "touches_backups_or_vectorstores": False,
            "source_paths_echoed": False,
            "server_target_echoed": False,
            "device_names_echoed": False,
            "mountpoints_echoed": False,
        },
        "current_blocker_summary": {
            "go_no_go_status": _status(no_go.get("status")) if no_go else "not_provided",
            "go_no_go_decision": _status(no_go.get("decision")) if no_go else "not_provided",
            "storage_status": _status(storage.get("status")),
            "storage_decision": _status(storage.get("decision")),
            "post_cleanup_status": _status(post.get("status")) if post else "not_provided",
            "post_cleanup_decision": _status(post.get("decision")) if post else "not_provided",
        },
        "capacity_evidence": {
            "root_used_percent": _to_int(root.get("used_percent"), -1),
            "root_free_mb": _to_int(root.get("free_mb")),
            "deploy_used_percent": _to_int(deploy.get("used_percent"), -1),
            "deploy_free_mb": _to_int(deploy.get("free_mb")),
            "docker_data_root_used_percent": _to_int(docker_root.get("used_percent"), -1),
            "docker_data_root_free_mb": _to_int(docker_root.get("free_mb")),
            "cleanup_root_free_delta_mb": _to_int(post_capacity.get("root_free_delta_mb")),
            "cleanup_deploy_free_delta_mb": _to_int(post_capacity.get("deploy_free_delta_mb")),
            "cleanup_deleted_images": _to_int(post_execution.get("deleted")),
            "cleanup_failed_images": _to_int(post_execution.get("failed")),
        },
        "topology_evidence": {
            "root_deploy_same_mount": sharing.get("root_deploy_same_mount") is True,
            "root_docker_same_mount": sharing.get("root_docker_same_mount") is True,
            "deploy_docker_same_mount": sharing.get("deploy_docker_same_mount") is True,
            "disk_count": _to_int(topology.get("disk_count")),
            "block_node_count": _to_int(topology.get("block_node_count")),
            "unmounted_block_count": _to_int(topology.get("unmounted_block_count")),
            "largest_unmounted_mb": _to_int(topology.get("largest_unmounted_mb")),
        },
        "restore_workspace_requirement": {
            "status": _status(restore.get("status")),
            "effective_free_mb": _to_int(restore.get("effective_free_mb")),
            "required_free_mb": _to_int(restore.get("required_free_mb")),
            "gap_mb": _to_int(restore.get("gap_mb")),
            "min_additional_free_mb": min_additional_free_mb,
            "suggested_new_free_mb": suggested_new_free_mb,
        },
        "requested_change": {
            "preferred_path": (
                "expand root volume online, then grow filesystem"
                if strategy == "expand_root_volume_or_attach_new_disk_for_docker_data"
                else "mount available block device and place Docker data or restore workspace there"
            ),
            "acceptable_alternatives": [
                "Attach a new disk and migrate Docker data-root during a maintenance window.",
                "Attach a new disk for restore drill workspace and backup staging.",
                "Increase root filesystem capacity through the cloud console and grow the filesystem in the OS.",
            ],
            "minimum_success_condition": (
                "Post-change capacity and restore feasibility must both pass before M1 can move past no-go."
            ),
        },
        "post_change_validation_commands": [
            "python scripts/collect_server_capacity_snapshot.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --output <private-workdir>/server-capacity-snapshot-post-expansion.json",
            "python scripts/check_restore_drill_feasibility.py --backup-schedule-json <private-workdir>/backup-schedule-live-probe.json --capacity-json <private-workdir>/server-capacity-snapshot-post-expansion.json --output <private-workdir>/restore-drill-feasibility-post-expansion.json",
            "python scripts/collect_storage_expansion_readiness.py --ssh-target <ssh-user>@<server-host> --deploy-dir <deploy-dir> --required-free-mb 4096 --output <private-workdir>/storage-expansion-readiness-post-expansion.json",
            "python scripts/collect_m1_go_no_go_evidence.py --include-storage-expansion-readiness --storage-expansion-readiness-json <private-workdir>/storage-expansion-readiness-post-expansion.json --include-restore-drill-feasibility --restore-drill-feasibility-json <private-workdir>/restore-drill-feasibility-post-expansion.json --json",
        ],
        "not_proven_by_this_request": [
            "The cloud disk has been expanded.",
            "A new disk has been attached or mounted.",
            "Docker data-root has been migrated.",
            "Restore drill feasibility has passed after expansion.",
            "M1 release can proceed.",
        ],
    }


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_storage_expansion_request_markdown(report: Mapping[str, Any]) -> str:
    capacity = _as_mapping(report.get("capacity_evidence"))
    topology = _as_mapping(report.get("topology_evidence"))
    restore = _as_mapping(report.get("restore_workspace_requirement"))
    requested = _as_mapping(report.get("requested_change"))
    blocker = _as_mapping(report.get("current_blocker_summary"))
    lines = [
        "# Storage Expansion Request",
        "",
        f"- Status: `{_cell(report.get('status'))}`",
        f"- Decision: `{_cell(report.get('decision'))}`",
        "- Boundary: this request does not connect SSH, expand disks, mount filesystems, migrate Docker data, read `.env`, read logs, or touch runtime data.",
        "",
        "## Why This Is Needed",
        "",
        f"- Current M1 gate: `{_cell(blocker.get('go_no_go_status'))}` / `{_cell(blocker.get('go_no_go_decision'))}`",
        f"- Storage evidence: `{_cell(blocker.get('storage_status'))}` / `{_cell(blocker.get('storage_decision'))}`",
        f"- Post-cleanup evidence: `{_cell(blocker.get('post_cleanup_status'))}` / `{_cell(blocker.get('post_cleanup_decision'))}`",
        "",
        "## Capacity Evidence",
        "",
        "| Target | Used % | Free MB |",
        "|---|---:|---:|",
        f"| root | {_cell(capacity.get('root_used_percent'))} | {_cell(capacity.get('root_free_mb'))} |",
        f"| deploy | {_cell(capacity.get('deploy_used_percent'))} | {_cell(capacity.get('deploy_free_mb'))} |",
        f"| Docker data-root | {_cell(capacity.get('docker_data_root_used_percent'))} | {_cell(capacity.get('docker_data_root_free_mb'))} |",
        "",
        "## Topology Evidence",
        "",
        f"- root / deploy same mount: `{_cell(topology.get('root_deploy_same_mount'))}`",
        f"- root / Docker same mount: `{_cell(topology.get('root_docker_same_mount'))}`",
        f"- disk count: `{_cell(topology.get('disk_count'))}`",
        f"- unmounted block count: `{_cell(topology.get('unmounted_block_count'))}`",
        f"- largest unmounted MB: `{_cell(topology.get('largest_unmounted_mb'))}`",
        "",
        "## Requested Change",
        "",
        f"- Preferred path: {_cell(requested.get('preferred_path'))}",
        f"- Minimum success condition: {_cell(requested.get('minimum_success_condition'))}",
        f"- Restore workspace gap: `{_cell(restore.get('gap_mb'))}` MB",
        f"- Suggested post-change free space: `{_cell(restore.get('suggested_new_free_mb'))}` MB",
        "",
        "## Post-Change Validation",
        "",
        "```powershell",
    ]
    lines.extend(str(command) for command in _as_list(report.get("post_change_validation_commands")))
    lines.extend(["```", "", "## Not Proven", ""])
    lines.extend(f"- {_cell(item)}" for item in _as_list(report.get("not_proven_by_this_request")))
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-readiness-json", type=_path_arg, required=True)
    parser.add_argument("--post-cleanup-json", type=_path_arg, default=None)
    parser.add_argument("--go-no-go-json", type=_path_arg, default=None)
    parser.add_argument("--output", type=_path_arg, default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_storage_expansion_request(
            storage_readiness=_read_json(args.storage_readiness_json) or {},
            post_cleanup=_read_json(args.post_cleanup_json),
            go_no_go=_read_json(args.go_no_go_json),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "version": STORAGE_EXPANSION_REQUEST_VERSION,
            "status": "blocked",
            "decision": "cannot_read_evidence",
            "policy": {"source_paths_echoed": False},
            "blocked_reasons": [{"key": "evidence_read_failed", "finding": str(exc).splitlines()[0]}],
        }
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.json
        else build_storage_expansion_request_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
