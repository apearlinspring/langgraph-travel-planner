"""Execute or dry-run an approved Docker build-cache cleanup over SSH.

The default mode is dry-run. Real cleanup requires both ``--execute`` and the
approval token. Execution runs only ``docker builder prune -a -f`` and never
runs ``docker system prune``.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_docker_build_cache_cleanup_plan import (
    DEPLOY_DIR_PLACEHOLDER,
    DOCKER_BUILD_CACHE_CLEANUP_PLAN_VERSION,
    SERVER_TARGET_PLACEHOLDER,
    _first,
    _markdown_cell,
    _parse_disk_line,
    _parse_probe_lines,
    _parse_system_df,
    _run_command,
)


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


DOCKER_BUILD_CACHE_CLEANUP_EXECUTION_VERSION = "docker_build_cache_cleanup_execution.v1"
APPROVAL_TOKEN = "APPROVE_DOCKER_BUILD_CACHE_CLEANUP"


REMOTE_CLEANUP_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"
EXECUTE="$2"

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
emit docker_system_df_before "$(timeout 20 docker system df 2>/dev/null | tr '\n' ';' || true)"

if [ "$EXECUTE" = "1" ]; then
  if timeout 240 docker builder prune -a -f >/tmp/zhixing-builder-prune.$$ 2>/tmp/zhixing-builder-prune-err.$$; then
    emit prune_result passed
  else
    emit prune_result failed
    emit prune_stderr_first_line "$(head -n 1 /tmp/zhixing-builder-prune-err.$$ 2>/dev/null || true)"
  fi
  rm -f /tmp/zhixing-builder-prune.$$ /tmp/zhixing-builder-prune-err.$$
else
  emit prune_result dry_run
fi

emit docker_system_df_after "$(timeout 20 docker system df 2>/dev/null | tr '\n' ';' || true)"
emit root_disk_after "$(disk_line /)"
if [ -n "$DEPLOY_DIR" ] && [ -d "$DEPLOY_DIR" ]; then
  emit deploy_disk_after "$(disk_line "$DEPLOY_DIR")"
else
  emit deploy_disk_after ""
fi
"""


def _safe_delta(before: Any, after: Any) -> float | None:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return None
    return round(float(before) - float(after), 1)


def _free_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> int | None:
    before_free = before.get("free_mb")
    after_free = after.get("free_mb")
    if not isinstance(before_free, int) or not isinstance(after_free, int):
        return None
    return after_free - before_free


def _cleanup_plan_summary(plan_data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": str(plan_data.get("version") or ""),
        "status": str(plan_data.get("status") or ""),
        "plan_is_build_cache_cleanup": plan_data.get("version") == DOCKER_BUILD_CACHE_CLEANUP_PLAN_VERSION,
        "plan_path_echoed": False,
    }


def build_docker_build_cache_cleanup_execution_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    plan_data: Mapping[str, Any] | None = None,
    execute: bool = False,
    approval_token: str = "",
    timeout_seconds: float = 300,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a dry-run or execution report for Docker build-cache cleanup."""

    report: dict[str, Any] = {
        "version": DOCKER_BUILD_CACHE_CLEANUP_EXECUTION_VERSION,
        "status": "blocked",
        "mode": "execute" if execute else "dry_run",
        "policy": {
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "deletes_build_cache": bool(execute),
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_builder_prune": bool(execute),
            "runs_system_prune": False,
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
        "plan_summary": _cleanup_plan_summary(plan_data or {}),
        "not_proven_by_this_report": [
            "Dry-run mode does not delete build cache or free disk space.",
            "Execution does not delete images, containers, volumes, logs, backups, .env files or vector stores.",
            "Build-cache cleanup can make future Docker builds slower until cache is rebuilt.",
            "A post-cleanup capacity snapshot and M1 go/no-go refresh are still required.",
        ],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [
            {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
        ]
        return report
    if plan_data is not None and plan_data.get("version") != DOCKER_BUILD_CACHE_CLEANUP_PLAN_VERSION:
        report["blocked_reasons"] = [
            {"key": "invalid_plan", "finding": "Plan JSON must be a Docker build-cache cleanup plan."}
        ]
        return report
    if execute and approval_token != APPROVAL_TOKEN:
        report["blocked_reasons"] = [
            {"key": "missing_approval", "finding": "Execution requires the explicit build-cache cleanup approval token."}
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
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_CLEANUP_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_cleanup_timeout", "finding": "SSH Docker build-cache cleanup command timed out."}]
        return report
    if completed.returncode != 0:
        report["blocked_reasons"] = [{"key": "ssh_cleanup_failed", "finding": "SSH Docker build-cache cleanup command failed."}]
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        return report

    parsed = _parse_probe_lines(completed.stdout)
    docker_available = _first(parsed, "docker_available") == "true"
    prune_result = _first(parsed, "prune_result")
    root_before = _parse_disk_line(_first(parsed, "root_disk_before"), label="root_before")
    root_after = _parse_disk_line(_first(parsed, "root_disk_after"), label="root_after")
    deploy_before = _parse_disk_line(_first(parsed, "deploy_disk_before"), label="deploy_before")
    deploy_after = _parse_disk_line(_first(parsed, "deploy_disk_after"), label="deploy_after")
    before_cache = _parse_system_df(_first(parsed, "docker_system_df_before"))
    after_cache = _parse_system_df(_first(parsed, "docker_system_df_after"))
    blocked_reasons = []
    if not docker_available:
        blocked_reasons.append({"key": "docker_unavailable", "finding": "Docker CLI is not available on the target."})
    if execute and prune_result != "passed":
        blocked_reasons.append({"key": "builder_prune_failed", "finding": "Docker builder prune did not pass."})

    reclaimable_after = after_cache.get("reclaimable_mb")
    cache_still_reclaimable = isinstance(reclaimable_after, (int, float)) and reclaimable_after > 0
    disk_still_degraded = root_after.get("status") == "degraded" or deploy_after.get("status") == "degraded"
    status = "blocked" if blocked_reasons else ("degraded" if cache_still_reclaimable or disk_still_degraded else "passed")
    report.update(
        {
            "status": status,
            "ssh": {
                "status": "passed" if not blocked_reasons else "blocked",
                "docker_available": docker_available,
                "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
            },
            "prune": {
                "result": prune_result or "not_reported",
                "stderr_first_line_present": bool(_first(parsed, "prune_stderr_first_line")),
                "stderr_value_echoed": False,
            },
            "disk": {
                "root_before": root_before,
                "deploy_before": deploy_before,
                "root_after": root_after,
                "deploy_after": deploy_after,
                "root_free_delta_mb": _free_delta(root_before, root_after),
                "deploy_free_delta_mb": _free_delta(deploy_before, deploy_after),
            },
            "build_cache": {
                "before": before_cache,
                "after": after_cache,
                "estimated_reclaimable_delta_mb": _safe_delta(
                    before_cache.get("reclaimable_mb"),
                    after_cache.get("reclaimable_mb"),
                ),
                "estimated_size_delta_mb": _safe_delta(
                    before_cache.get("size_mb"),
                    after_cache.get("size_mb"),
                ),
            },
            "blocked_reasons": blocked_reasons,
            "degraded_reasons": (
                [{"key": "post_cleanup_degraded", "finding": "Build cache or disk usage remains degraded after cleanup check."}]
                if status == "degraded"
                else []
            ),
        }
    )
    return report


def build_docker_build_cache_cleanup_execution_markdown(report: Mapping[str, Any]) -> str:
    policy = report.get("policy") or {}
    build_cache = report.get("build_cache") or {}
    before = build_cache.get("before") or {}
    after = build_cache.get("after") or {}
    disk = report.get("disk") or {}
    lines = [
        "# Docker Build Cache Cleanup Execution",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Deletes build cache: `{policy.get('deletes_build_cache')}`",
        f"- Runs system prune: `{policy.get('runs_system_prune')}`",
        "",
        "## Build Cache",
        "",
        "| Metric | Before | After |",
        "|---|---:|---:|",
        f"| Size MB | {_markdown_cell(before.get('size_mb'))} | {_markdown_cell(after.get('size_mb'))} |",
        f"| Reclaimable MB | {_markdown_cell(before.get('reclaimable_mb'))} | {_markdown_cell(after.get('reclaimable_mb'))} |",
        f"| Active entries | {_markdown_cell(before.get('active_count'))} | {_markdown_cell(after.get('active_count'))} |",
        "",
        "## Disk Delta",
        "",
        f"- Root free delta MB: `{disk.get('root_free_delta_mb')}`",
        f"- Deploy free delta MB: `{disk.get('deploy_free_delta_mb')}`",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
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
    parser.add_argument("--plan-json", type=_path_arg, default=None, help="Optional private build-cache cleanup plan JSON.")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--execute", action="store_true", help="Actually remove approved Docker build cache.")
    parser.add_argument("--approval-token", default="", help="Required with --execute. Value is never echoed.")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plan_data = json.loads(args.plan_json.read_text(encoding="utf-8")) if args.plan_json is not None else None
    report = build_docker_build_cache_cleanup_execution_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        plan_data=plan_data,
        execute=args.execute,
        approval_token=args.approval_token,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_docker_build_cache_cleanup_execution_markdown(report)
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
