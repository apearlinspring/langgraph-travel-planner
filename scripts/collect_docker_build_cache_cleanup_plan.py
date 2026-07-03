"""Collect a redacted Docker build-cache cleanup plan over SSH.

This script is read-only. It does not delete Docker images, containers,
volumes, logs, build cache, backups, .env files or vector stores.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


DOCKER_BUILD_CACHE_CLEANUP_PLAN_VERSION = "docker_build_cache_cleanup_plan.v1"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
DISK_WARN_USED_PERCENT = 90
DISK_FAIL_USED_PERCENT = 98


REMOTE_PLAN_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"

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

emit root_disk "$(disk_line /)"
if [ -n "$DEPLOY_DIR" ] && [ -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present true
  emit deploy_disk "$(disk_line "$DEPLOY_DIR")"
else
  emit deploy_dir_present false
  emit deploy_disk ""
fi

if ! command -v docker >/dev/null 2>&1; then
  emit docker_available false
  exit 0
fi

emit docker_available true
emit docker_version "$(timeout 5 docker --version 2>/dev/null || true)"
emit docker_system_df "$(timeout 20 docker system df 2>/dev/null | tr '\n' ';' || true)"
"""


def _run_command(
    args: Sequence[str],
    *,
    input_text: str,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    normalized_input = str(input_text).replace("\r\n", "\n").replace("\r", "\n")
    completed = subprocess.run(
        list(args),
        input=normalized_input.encode("utf-8"),
        capture_output=True,
        text=False,
        timeout=timeout_seconds,
        check=False,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        stdout=completed.stdout.decode("utf-8", "replace"),
        stderr=completed.stderr.decode("utf-8", "replace"),
    )


def _parse_probe_lines(stdout: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for raw_line in str(stdout or "").splitlines():
        if "\t" not in raw_line:
            continue
        key, value = raw_line.split("\t", 1)
        parsed.setdefault(key.strip(), []).append(value.strip())
    return parsed


def _first(values: Mapping[str, list[str]], key: str, default: str = "") -> str:
    items = values.get(key) or []
    return str(items[0]) if items else default


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
    status = "passed"
    finding = "Disk usage is below the build-cache cleanup warning threshold."
    if used >= DISK_FAIL_USED_PERCENT:
        status = "blocked"
        finding = "Disk usage is at or above the build-cache cleanup fail threshold."
    elif used >= DISK_WARN_USED_PERCENT:
        status = "degraded"
        finding = "Disk usage is above the build-cache cleanup warning threshold."
    return {
        "status": status,
        "label": label,
        "total_mb": total,
        "free_mb": free,
        "used_percent": used,
        "mount_present": bool(mount),
        "warn_used_percent": DISK_WARN_USED_PERCENT,
        "fail_used_percent": DISK_FAIL_USED_PERCENT,
        "value_echoed": False,
        "finding": finding,
    }


_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?B)\s*$", re.IGNORECASE)


def _size_to_mb(value: str) -> float | None:
    match = _SIZE_RE.match(str(value or "").strip())
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "B":
        return number / (1024 * 1024)
    if unit == "KB":
        return number / 1024
    if unit == "MB":
        return number
    if unit == "GB":
        return number * 1024
    if unit == "TB":
        return number * 1024 * 1024
    return None


def _int_or_none(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _parse_system_df(system_df: str) -> dict[str, Any]:
    text = str(system_df or "").replace(";", "\n")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("build cache"):
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) < 5:
            return {
                "status": "degraded",
                "row_present": True,
                "value_echoed": False,
                "finding": "Docker build-cache row could not be parsed.",
            }
        reclaimable_text = str(parts[4])
        percent_match = re.search(r"\((\d+)%\)", reclaimable_text)
        reclaimable_size = reclaimable_text.split(" ", 1)[0]
        size_mb = _size_to_mb(str(parts[3]))
        reclaimable_mb = _size_to_mb(reclaimable_size)
        return {
            "status": "passed",
            "row_present": True,
            "total_count": _int_or_none(str(parts[1])),
            "active_count": _int_or_none(str(parts[2])),
            "size_mb": round(size_mb, 1) if size_mb is not None else None,
            "reclaimable_mb": round(reclaimable_mb, 1) if reclaimable_mb is not None else None,
            "reclaimable_percent": int(percent_match.group(1)) if percent_match else None,
            "value_echoed": False,
        }
    return {
        "status": "not_checked",
        "row_present": False,
        "value_echoed": False,
        "finding": "Docker build-cache row is not available.",
    }


def build_docker_build_cache_cleanup_plan_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    timeout_seconds: float = 90,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a read-only build-cache cleanup plan."""

    report: dict[str, Any] = {
        "version": DOCKER_BUILD_CACHE_CLEANUP_PLAN_VERSION,
        "status": "blocked",
        "policy": {
            "read_only": True,
            "deletes_build_cache": False,
            "deletes_images": False,
            "deletes_containers": False,
            "deletes_volumes": False,
            "runs_system_prune": False,
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "prints_secret_values": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "not_proven_by_this_plan": [
            "No Docker build cache has been deleted.",
            "Docker build-cache cleanup can make future image builds slower.",
            "This plan does not inspect logs, .env files, database rows, Redis keys, volumes or vector store contents.",
            "A post-cleanup live capacity snapshot is required before changing go/no-go status.",
        ],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [
            {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
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
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_PLAN_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_probe_timeout", "finding": "SSH read-only build-cache plan timed out."}]
        return report
    if completed.returncode != 0:
        report["blocked_reasons"] = [{"key": "ssh_probe_failed", "finding": "SSH read-only build-cache plan failed."}]
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        return report

    parsed = _parse_probe_lines(completed.stdout)
    root_disk = _parse_disk_line(_first(parsed, "root_disk"), label="root")
    deploy_disk = _parse_disk_line(_first(parsed, "deploy_disk"), label="deploy")
    build_cache = _parse_system_df(_first(parsed, "docker_system_df"))
    disk_statuses = {root_disk["status"], deploy_disk["status"]}
    blocked = [status for status in disk_statuses if status == "blocked"]
    degraded = [status for status in disk_statuses if status == "degraded"]
    reclaimable_mb = build_cache.get("reclaimable_mb")
    has_reclaimable_cache = isinstance(reclaimable_mb, (int, float)) and reclaimable_mb > 0
    status = "blocked" if blocked else ("degraded" if degraded or has_reclaimable_cache else "passed")
    risk_status = "blocked" if blocked else ("attention_required" if status == "degraded" else "ok")
    report.update(
        {
            "status": status,
            "risk_status": risk_status,
            "ssh": {
                "status": "passed",
                "docker_available": _first(parsed, "docker_available") == "true",
                "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
                "docker_version_present": bool(_first(parsed, "docker_version")),
                "docker_system_df_available": bool(_first(parsed, "docker_system_df")),
                "docker_system_df_echoed": False,
            },
            "disk": {
                "root": root_disk,
                "deploy": deploy_disk,
            },
            "build_cache": build_cache,
            "blocked_reasons": [],
            "degraded_reasons": [],
            "approval_required": {
                "required_for_execution": has_reclaimable_cache,
                "suggested_scope": "Run docker builder prune -a -f only after explicit approval.",
                "destructive_action_in_this_plan": False,
            },
        }
    )
    if not report["ssh"]["docker_available"]:
        report["status"] = "blocked"
        report["risk_status"] = "blocked"
        report["blocked_reasons"].append({"key": "docker_unavailable", "finding": "Docker CLI is not available on the target."})
    if root_disk["status"] == "blocked" or deploy_disk["status"] == "blocked":
        report["blocked_reasons"].append({"key": "disk_usage_fail_threshold", "finding": "Disk usage is at or above fail threshold."})
    elif root_disk["status"] == "degraded" or deploy_disk["status"] == "degraded":
        report["degraded_reasons"].append({"key": "disk_usage_warning_threshold", "finding": "Disk usage is above warning threshold."})
    if has_reclaimable_cache:
        report["degraded_reasons"].append({"key": "build_cache_reclaimable", "finding": "Docker build cache has reclaimable space."})
    return report


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("|", "\\|")
    return text or "-"


def build_docker_build_cache_cleanup_plan_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Docker Build Cache Cleanup Plan",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Risk: `{report.get('risk_status')}`",
        "- Policy: read-only, no build-cache/image/container/volume deletion, no system prune.",
        "",
        "## Disk",
        "",
        "| Target | Status | Used | Free MB | Finding |",
        "|---|---|---:|---:|---|",
    ]
    for key, item in (report.get("disk") or {}).items():
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(key)} | "
            f"{_markdown_cell(item.get('status'))} | "
            f"{_markdown_cell(item.get('used_percent'))}% | "
            f"{_markdown_cell(item.get('free_mb'))} | "
            f"{_markdown_cell(item.get('finding'))} |"
        )
    build_cache = report.get("build_cache") or {}
    lines.extend(
        [
            "",
            "## Build Cache",
            "",
            f"- Row present: `{build_cache.get('row_present')}`",
            f"- Total entries: `{build_cache.get('total_count')}`",
            f"- Active entries: `{build_cache.get('active_count')}`",
            f"- Size: `{build_cache.get('size_mb')} MB`",
            f"- Reclaimable: `{build_cache.get('reclaimable_mb')} MB`",
            f"- Reclaimable percent: `{build_cache.get('reclaimable_percent')}%`",
        ]
    )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_plan") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def _path_arg(value: str) -> Path:
    return Path(value)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_docker_build_cache_cleanup_plan_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_docker_build_cache_cleanup_plan_markdown(report)
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
