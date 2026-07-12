"""Execute or dry-run an approved Docker image cleanup plan over SSH.

The default mode is dry-run. Real image deletion requires both ``--execute``
and the approval token. The remote script rechecks container-referenced images
before deleting any image and never prunes containers, volumes, logs or data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._remote_probe_helpers import (  # noqa: E402
    first_value as _first,
    parse_tabbed_probe_lines as _parse_probe_lines,
    run_utf8_command as _run_command,
)


DOCKER_DISK_CLEANUP_EXECUTION_VERSION = "docker_disk_cleanup_execution.v1"
APPROVAL_TOKEN = "APPROVE_DOCKER_IMAGE_CLEANUP"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
IMAGE_ID_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{12,}$")


REMOTE_CLEANUP_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"
EXECUTE="$2"
shift 2

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

disk_line() {
  target="$1"
  if df -Pm "$target" >/dev/null 2>&1; then
    df -Pm "$target" 2>/dev/null | awk 'NR==2 {gsub("%", "", $5); print $2 "|" $4 "|" $5 "|" $6}'
  fi
}

emit root_disk_before "$(disk_line /)"
if [ -n "$DEPLOY_DIR" ] && [ -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present true
  emit deploy_disk_before "$(disk_line "$DEPLOY_DIR")"
else
  emit deploy_dir_present false
  emit deploy_disk_before ""
fi

if ! command -v docker >/dev/null 2>&1; then
  emit docker_available false
  exit 0
fi
emit docker_available true

protected_file="/tmp/zhixing-cleanup-protected.$$"
rm -f "$protected_file"
if timeout 10 docker ps -aq >/tmp/zhixing-cleanup-containers.$$ 2>/dev/null; then
  while IFS= read -r container_id; do
    [ -n "$container_id" ] || continue
    image_id="$(timeout 5 docker inspect -f '{{.Image}}' "$container_id" 2>/dev/null || true)"
    [ -n "$image_id" ] && printf '%s\n' "$image_id" >> "$protected_file"
  done </tmp/zhixing-cleanup-containers.$$
fi
rm -f /tmp/zhixing-cleanup-containers.$$
touch "$protected_file"

for image_ref in "$@"; do
  case "$image_ref" in
    sha256:[0-9a-fA-F]*|[0-9a-fA-F]*) ;;
    *)
      emit image_result "$image_ref|skipped_invalid"
      continue
      ;;
  esac

  inspect_id="$(timeout 10 docker image inspect -f '{{.Id}}' "$image_ref" 2>/dev/null || true)"
  if [ -z "$inspect_id" ]; then
    emit image_result "$image_ref|skipped_missing"
    continue
  fi

  if grep -Fx "$inspect_id" "$protected_file" >/dev/null 2>&1; then
    emit image_result "$inspect_id|skipped_protected"
    continue
  fi

  if [ "$EXECUTE" = "1" ]; then
    if timeout 90 docker image rm "$inspect_id" >/dev/null 2>&1; then
      emit image_result "$inspect_id|deleted"
    else
      emit image_result "$inspect_id|failed"
    fi
  else
    emit image_result "$inspect_id|dry_run"
  fi
done

rm -f "$protected_file"
emit root_disk_after "$(disk_line /)"
if [ -n "$DEPLOY_DIR" ] && [ -d "$DEPLOY_DIR" ]; then
  emit deploy_disk_after "$(disk_line "$DEPLOY_DIR")"
else
  emit deploy_disk_after ""
fi
"""


def _parse_disk_line(value: str, *, label: str) -> dict[str, Any]:
    parts = str(value or "").split("|")
    if len(parts) < 4:
        return {
            "status": "not_checked",
            "label": label,
            "summary_present": False,
            "value_echoed": False,
            "finding": "Disk summary is not available.",
        }
    total_mb, free_mb, used_percent, mount = parts[:4]
    try:
        total = int(total_mb)
        free = int(free_mb)
        used = int(used_percent)
    except ValueError:
        return {
            "status": "degraded",
            "label": label,
            "summary_present": True,
            "value_echoed": False,
            "finding": "Disk summary could not be parsed.",
        }
    return {
        "status": "passed",
        "label": label,
        "total_mb": total,
        "free_mb": free,
        "used_percent": used,
        "mount_present": bool(mount),
        "value_echoed": False,
    }


def _image_id_short(image_id: str) -> str:
    text = str(image_id or "")
    return text.replace("sha256:", "")[:12]


def _candidate_ids_from_plan(plan_data: Mapping[str, Any], *, max_delete_count: int) -> list[str]:
    selected = plan_data.get("selected_candidates") or []
    if not isinstance(selected, list):
        return []
    image_ids: list[str] = []
    seen: set[str] = set()
    for item in selected:
        if not isinstance(item, Mapping):
            continue
        image_id = str(item.get("image_id") or "").strip()
        if not image_id or not IMAGE_ID_PATTERN.match(image_id):
            continue
        if image_id in seen:
            continue
        seen.add(image_id)
        image_ids.append(image_id)
        if len(image_ids) >= max(0, int(max_delete_count)):
            break
    return image_ids


def _cleanup_plan_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload.get("selected_candidates"), list):
        return payload
    sections = payload.get("sections")
    if isinstance(sections, Mapping):
        cleanup_plan = sections.get("docker_disk_cleanup_plan")
        if isinstance(cleanup_plan, Mapping):
            return cleanup_plan
    return payload


def _parse_image_results(rows: Sequence[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in rows:
        image_ref, _, action = str(row or "").partition("|")
        results.append(
            {
                "image_id_prefix": _image_id_short(image_ref),
                "action": action or "unknown",
                "value_echoed": False,
            }
        )
    return results


def build_docker_disk_cleanup_execution_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    plan_data: Mapping[str, Any],
    execute: bool = False,
    approval_token: str = "",
    max_delete_count: int = 20,
    timeout_seconds: float = 120,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a dry-run or execution report for a Docker cleanup plan."""

    report: dict[str, Any] = {
        "version": DOCKER_DISK_CLEANUP_EXECUTION_VERSION,
        "status": "blocked",
        "mode": "execute" if execute else "dry_run",
        "policy": {
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "deletes_images": bool(execute),
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_prune": False,
            "protects_running_images": True,
            "protects_container_images": True,
            "requires_execute_flag": True,
            "requires_approval_token": True,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "approval": {
            "execute_requested": bool(execute),
            "approval_token_accepted": bool(execute and approval_token == APPROVAL_TOKEN),
            "approval_token_echoed": False,
        },
        "not_proven_by_this_report": [
            "Dry-run mode does not delete images or free disk space.",
            "Actual deletion does not prune containers, volumes, logs, backups, .env files or vector stores.",
            "A post-cleanup live server probe is still required before changing a disk-related conditional go.",
        ],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [
            {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
        ]
        return report
    if execute and approval_token != APPROVAL_TOKEN:
        report["blocked_reasons"] = [
            {"key": "missing_approval", "finding": "Execution requires the explicit cleanup approval token."}
        ]
        return report

    cleanup_plan = _cleanup_plan_payload(plan_data)
    image_ids = _candidate_ids_from_plan(cleanup_plan, max_delete_count=max_delete_count)
    report["plan_summary"] = {
        "version": str(cleanup_plan.get("version") or ""),
        "status": str(cleanup_plan.get("status") or ""),
        "selected_candidates_seen": len(cleanup_plan.get("selected_candidates") or []),
        "requested_image_count": len(image_ids),
        "max_delete_count": int(max_delete_count),
        "plan_path_echoed": False,
    }
    if not image_ids:
        report["blocked_reasons"] = [
            {"key": "missing_candidates", "finding": "No valid image candidates were found in the cleanup plan."}
        ]
        return report

    command = [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        ssh_target,
        "bash",
        "-s",
        "--",
        deploy_dir,
        "1" if execute else "0",
        *image_ids,
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_CLEANUP_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_cleanup_timeout", "finding": "SSH Docker cleanup command timed out."}]
        return report
    if completed.returncode != 0:
        report["blocked_reasons"] = [{"key": "ssh_cleanup_failed", "finding": "SSH Docker cleanup command failed."}]
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        return report

    parsed = _parse_probe_lines(completed.stdout)
    results = _parse_image_results(parsed.get("image_result") or [])
    action_counts: dict[str, int] = {}
    for item in results:
        action = str(item.get("action") or "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1

    failed_count = action_counts.get("failed", 0)
    blocked_reasons = []
    if _first(parsed, "docker_available") != "true":
        blocked_reasons.append({"key": "docker_unavailable", "finding": "Docker CLI is not available on the target."})
    if failed_count:
        blocked_reasons.append({"key": "image_delete_failed", "finding": "At least one Docker image deletion failed."})

    skipped_count = sum(
        count for action, count in action_counts.items() if action.startswith("skipped_")
    )
    status = "blocked" if blocked_reasons else ("degraded" if skipped_count else "passed")
    report.update(
        {
            "status": status,
            "ssh": {
                "status": "passed" if not blocked_reasons else "blocked",
                "docker_available": _first(parsed, "docker_available") == "true",
                "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
            },
            "disk": {
                "root_before": _parse_disk_line(_first(parsed, "root_disk_before"), label="root_before"),
                "deploy_before": _parse_disk_line(_first(parsed, "deploy_disk_before"), label="deploy_before"),
                "root_after": _parse_disk_line(_first(parsed, "root_disk_after"), label="root_after"),
                "deploy_after": _parse_disk_line(_first(parsed, "deploy_disk_after"), label="deploy_after"),
            },
            "results": results,
            "result_counts": action_counts,
            "blocked_reasons": blocked_reasons,
            "degraded_reasons": (
                [{"key": "candidate_skipped", "finding": "At least one candidate was skipped safely."}]
                if skipped_count and not blocked_reasons
                else []
            ),
        }
    )
    return report


def build_docker_disk_cleanup_execution_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Docker Disk Cleanup Execution",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Deletes images: `{(report.get('policy') or {}).get('deletes_images')}`",
        f"- Runs prune: `{(report.get('policy') or {}).get('runs_prune')}`",
        "",
        "## Results",
        "",
        "| Action | Count |",
        "|---|---:|",
    ]
    counts = report.get("result_counts") or {}
    if isinstance(counts, Mapping) and counts:
        for action, count in sorted(counts.items()):
            lines.append(f"| {action} | {count} |")
    else:
        lines.append("| - | 0 |")

    lines.extend(["", "## Boundaries", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {str(item)}")
    return "\n".join(lines) + "\n"


def _path_arg(value: str) -> Path:
    return Path(value)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--plan-json", type=_path_arg, required=True, help="Private cleanup plan JSON.")
    parser.add_argument("--max-delete-count", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--execute", action="store_true", help="Actually remove approved image candidates.")
    parser.add_argument("--approval-token", default="", help="Required with --execute. Value is never echoed.")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plan_data = json.loads(args.plan_json.read_text(encoding="utf-8"))
    report = build_docker_disk_cleanup_execution_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        plan_data=plan_data,
        execute=args.execute,
        approval_token=args.approval_token,
        max_delete_count=args.max_delete_count,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_docker_disk_cleanup_execution_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
