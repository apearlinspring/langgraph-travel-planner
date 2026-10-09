"""Collect redacted storage expansion readiness evidence over SSH.

The probe is read-only. It inspects filesystem capacity, mount sharing, Docker
data-root placement and block-device topology. It does not read `.env`, logs,
database rows, Redis keys, backups, vector stores or file contents, and it does
not delete Docker images or run Docker prune.
"""
from __future__ import annotations

import argparse
import base64
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


STORAGE_EXPANSION_READINESS_VERSION = "storage_expansion_readiness.v1"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
DISK_WARN_USED_PERCENT = 90
DISK_FAIL_USED_PERCENT = 98
DEFAULT_REQUIRED_FREE_MB = 4096

REMOTE_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"

emit() {
  key="$1"
  shift || true
  printf '__ZHIXING_STORAGE__%s=%s\n' "$key" "$*"
}

df_line() {
  target="$1"
  if [ -n "$target" ] && df -PmT "$target" >/dev/null 2>&1; then
    df -PmT "$target" 2>/dev/null | awk 'NR==2 {gsub("%", "", $6); print $2 "|" $3 "|" $5 "|" $6}'
  fi
}

mount_target() {
  target="$1"
  if [ -n "$target" ]; then
    findmnt -T "$target" -no TARGET 2>/dev/null | head -n 1 || true
  fi
}

fstype_for() {
  target="$1"
  if [ -n "$target" ]; then
    findmnt -T "$target" -no FSTYPE 2>/dev/null | head -n 1 || true
  fi
}

emit root_df "$(df_line /)"
emit root_mount_token "$(mount_target /)"
emit root_fstype "$(fstype_for /)"

if [ -n "$DEPLOY_DIR" ] && [ -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present true
  emit deploy_df "$(df_line "$DEPLOY_DIR")"
  emit deploy_mount_token "$(mount_target "$DEPLOY_DIR")"
  emit deploy_fstype "$(fstype_for "$DEPLOY_DIR")"
else
  emit deploy_dir_present false
  emit deploy_df ""
  emit deploy_mount_token ""
  emit deploy_fstype ""
fi

docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
if [ -n "$docker_root" ] && [ -d "$docker_root" ]; then
  emit docker_root_present true
  emit docker_root_df "$(df_line "$docker_root")"
  emit docker_root_mount_token "$(mount_target "$docker_root")"
  emit docker_root_fstype "$(fstype_for "$docker_root")"
else
  emit docker_root_present false
  emit docker_root_df ""
  emit docker_root_mount_token ""
  emit docker_root_fstype ""
fi

if command -v lsblk >/dev/null 2>&1; then
  lsblk_json="$(lsblk -J -b -o TYPE,SIZE,MOUNTPOINT,FSTYPE 2>/dev/null || true)"
  if [ -n "$lsblk_json" ]; then
    emit lsblk_json_b64 "$(printf '%s' "$lsblk_json" | base64 | tr -d '\n')"
  else
    emit lsblk_json_b64 ""
  fi
  lsblk_kv="$(lsblk -b -P -o TYPE,SIZE,MOUNTPOINT,FSTYPE 2>/dev/null || true)"
  if [ -n "$lsblk_kv" ]; then
    emit lsblk_kv_b64 "$(printf '%s' "$lsblk_kv" | base64 | tr -d '\n')"
  else
    emit lsblk_kv_b64 ""
  fi
else
  emit lsblk_json_b64 ""
  emit lsblk_kv_b64 ""
fi

if docker system df --format '{{.Type}}|{{.TotalCount}}|{{.Active}}|{{.Size}}|{{.Reclaimable}}' >/tmp/zhixing-docker-df.$$ 2>/dev/null; then
  base64 /tmp/zhixing-docker-df.$$ | tr -d '\n' | while read encoded; do emit docker_df_b64 "$encoded"; done
  rm -f /tmp/zhixing-docker-df.$$
else
  rm -f /tmp/zhixing-docker-df.$$ || true
  emit docker_df_b64 ""
fi
"""


def _run_command(
    args: Sequence[str],
    *,
    input_text: str | None = None,
    timeout_seconds: float = 90,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        input=input_text.encode("utf-8") if input_text is not None else None,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return subprocess.CompletedProcess(
        args=completed.args,
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )


def _parse_probe_lines(stdout: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for raw_line in str(stdout or "").splitlines():
        if not raw_line.startswith("__ZHIXING_STORAGE__") or "=" not in raw_line:
            continue
        key, value = raw_line[len("__ZHIXING_STORAGE__") :].split("=", 1)
        parsed.setdefault(key, []).append(value)
    return parsed


def _first(parsed: Mapping[str, list[str]], key: str, default: str = "") -> str:
    values = parsed.get(key) or []
    return str(values[0]) if values else default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _decode_b64_json(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        raw = base64.b64decode(value).decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _decode_b64_text(value: str) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value).decode("utf-8", errors="replace")
    except ValueError:
        return ""


def _parse_lsblk_kv(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        row: dict[str, Any] = {}
        for chunk in line.split():
            if "=" not in chunk:
                continue
            key, value = chunk.split("=", 1)
            row[key.lower()] = value.strip('"')
        if row:
            rows.append(row)
    return rows


def _disk_line(value: str, *, label: str) -> dict[str, Any]:
    parts = str(value or "").split("|")
    if len(parts) < 4:
        return {
            "status": "blocked",
            "label": label,
            "finding": "Disk summary is not available.",
            "value_echoed": False,
        }
    fstype, total_mb, free_mb, used_percent = parts[:4]
    total = _to_int(total_mb)
    free = _to_int(free_mb)
    used = _to_int(used_percent)
    status = "passed"
    finding = "Disk usage is below the warning threshold."
    if used >= DISK_FAIL_USED_PERCENT:
        status = "blocked"
        finding = "Disk usage is at or above the fail threshold."
    elif used >= DISK_WARN_USED_PERCENT:
        status = "degraded"
        finding = "Disk usage is above the warning threshold."
    return {
        "status": status,
        "label": label,
        "fstype": fstype or "unknown",
        "total_mb": total,
        "free_mb": free,
        "used_percent": used,
        "warn_used_percent": DISK_WARN_USED_PERCENT,
        "fail_used_percent": DISK_FAIL_USED_PERCENT,
        "value_echoed": False,
        "finding": finding,
    }


def _flatten_lsblk(nodes: Sequence[Any]) -> list[Mapping[str, Any]]:
    flattened: list[Mapping[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        flattened.append(node)
        children = node.get("children")
        if isinstance(children, list):
            flattened.extend(_flatten_lsblk(children))
    return flattened


def _mount_category(mountpoint: Any) -> str:
    mount = str(mountpoint or "").strip()
    if not mount:
        return "unmounted"
    if mount == "/":
        return "root"
    if mount.startswith("/var/lib/docker"):
        return "docker"
    if mount.startswith("/opt"):
        return "application"
    if mount.startswith("/boot"):
        return "boot"
    return "other"


def _lsblk_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    nodes = _flatten_lsblk(payload.get("blockdevices") if isinstance(payload.get("blockdevices"), list) else [])
    disks = [node for node in nodes if str(node.get("type") or "").lower() == "disk"]
    unmounted = [
        node for node in nodes
        if str(node.get("type") or "").lower() in {"disk", "part", "lvm"}
        and not str(node.get("mountpoint") or "").strip()
        and not isinstance(node.get("children"), list)
    ]
    mount_categories: dict[str, int] = {}
    for node in nodes:
        category = _mount_category(node.get("mountpoint"))
        mount_categories[category] = mount_categories.get(category, 0) + 1
    largest_unmounted_mb = 0
    for node in unmounted:
        largest_unmounted_mb = max(largest_unmounted_mb, _to_int(node.get("size")) // (1024 * 1024))
    return {
        "status": "passed" if nodes else "not_checked",
        "disk_count": len(disks),
        "block_node_count": len(nodes),
        "unmounted_block_count": len(unmounted),
        "largest_unmounted_mb": largest_unmounted_mb,
        "mount_categories": mount_categories,
        "device_names_echoed": False,
        "mountpoints_echoed": False,
    }


def _lsblk_summary_from_kv(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    disks = [row for row in rows if str(row.get("type") or "").lower() == "disk"]
    parts_or_lvm = [row for row in rows if str(row.get("type") or "").lower() in {"part", "lvm"}]
    unmounted = [
        row for row in parts_or_lvm
        if not str(row.get("mountpoint") or "").strip()
    ]
    if not parts_or_lvm and not any(str(row.get("mountpoint") or "").strip() for row in disks):
        unmounted.extend(disks)
    mount_categories: dict[str, int] = {}
    for row in rows:
        category = _mount_category(row.get("mountpoint"))
        mount_categories[category] = mount_categories.get(category, 0) + 1
    largest_unmounted_mb = 0
    for row in unmounted:
        largest_unmounted_mb = max(largest_unmounted_mb, _to_int(row.get("size")) // (1024 * 1024))
    return {
        "status": "passed" if rows else "not_checked",
        "disk_count": len(disks),
        "block_node_count": len(rows),
        "unmounted_block_count": len(unmounted),
        "largest_unmounted_mb": largest_unmounted_mb,
        "mount_categories": mount_categories,
        "device_names_echoed": False,
        "mountpoints_echoed": False,
    }


def _lsblk_summary_from_parsed(parsed: Mapping[str, list[str]]) -> dict[str, Any]:
    payload = _decode_b64_json(_first(parsed, "lsblk_json_b64"))
    if payload:
        return _lsblk_summary(payload)
    rows = _parse_lsblk_kv(_decode_b64_text(_first(parsed, "lsblk_kv_b64")))
    return _lsblk_summary_from_kv(rows)


def _docker_df_summary(text: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "type": parts[0],
                "total_count": _to_int(parts[1]),
                "active_count": _to_int(parts[2]),
                "size": parts[3],
                "reclaimable": parts[4],
                "value_echoed": False,
            }
        )
    return {
        "status": "passed" if rows else "not_checked",
        "rows": rows,
        "names_echoed": False,
    }


def _mount_sharing(parsed: Mapping[str, list[str]]) -> dict[str, Any]:
    root = _first(parsed, "root_mount_token")
    deploy = _first(parsed, "deploy_mount_token")
    docker = _first(parsed, "docker_root_mount_token")
    return {
        "root_deploy_same_mount": bool(root and deploy and root == deploy),
        "root_docker_same_mount": bool(root and docker and root == docker),
        "deploy_docker_same_mount": bool(deploy and docker and deploy == docker),
        "mount_tokens_echoed": False,
    }


def build_storage_expansion_readiness_report_from_parsed(
    parsed: Mapping[str, list[str]],
    *,
    required_free_mb: int = DEFAULT_REQUIRED_FREE_MB,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    root = _disk_line(_first(parsed, "root_df"), label="root")
    deploy = _disk_line(_first(parsed, "deploy_df"), label="deploy")
    docker = _disk_line(_first(parsed, "docker_root_df"), label="docker_data_root")
    lsblk = _lsblk_summary_from_parsed(parsed)
    docker_df = _docker_df_summary(_decode_b64_text(_first(parsed, "docker_df_b64")))
    sharing = _mount_sharing(parsed)
    free_values = [disk.get("free_mb") for disk in (root, deploy, docker) if isinstance(disk.get("free_mb"), int)]
    effective_free_mb = min(free_values) if free_values else 0
    gap_mb = max(0, required_free_mb - effective_free_mb)
    restore_workspace = {
        "status": "blocked" if gap_mb > 0 else "passed",
        "effective_free_mb": effective_free_mb,
        "required_free_mb": required_free_mb,
        "gap_mb": gap_mb,
    }
    degraded_reasons: list[dict[str, str]] = []
    blocked_reasons: list[dict[str, str]] = []
    for key, disk in {"root": root, "deploy": deploy, "docker_data_root": docker}.items():
        if disk.get("status") == "blocked":
            blocked_reasons.append({"section": "disk_usage", "key": key, "finding": str(disk.get("finding"))})
        elif disk.get("status") == "degraded":
            degraded_reasons.append({"section": "disk_usage", "key": key, "finding": str(disk.get("finding"))})
    if restore_workspace["status"] == "blocked":
        blocked_reasons.append(
            {
                "section": "restore_workspace",
                "key": "insufficient_free_space",
                "finding": "Effective free space is below the restore drill threshold.",
            }
        )
    unmounted_mb = _to_int(lsblk.get("largest_unmounted_mb"))
    if gap_mb <= 0:
        strategy = "no_storage_expansion_required"
    elif unmounted_mb >= gap_mb:
        strategy = "mount_available_block_device"
    elif sharing.get("root_docker_same_mount"):
        strategy = "expand_root_volume_or_attach_new_disk_for_docker_data"
    else:
        strategy = "expand_filesystem_with_lowest_free_space"
    status = "blocked" if blocked_reasons else ("degraded" if degraded_reasons else "passed")
    return {
        "version": STORAGE_EXPANSION_READINESS_VERSION,
        "status": status,
        "decision": "storage_expansion_required" if gap_mb > 0 else "no_expansion_required",
        "generated_at": now.isoformat(),
        "policy": {
            "connects_ssh": False,
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "touches_backups_or_vectorstores": False,
            "deletes_images": False,
            "runs_docker_prune": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "device_names_echoed": False,
            "mountpoints_echoed": False,
        },
        "sections": {
            "disk_usage": {
                "status": "blocked"
                if any(disk.get("status") == "blocked" for disk in (root, deploy, docker))
                else ("degraded" if any(disk.get("status") == "degraded" for disk in (root, deploy, docker)) else "passed"),
                "root": root,
                "deploy": deploy,
                "docker_data_root": docker,
            },
            "mount_sharing": sharing,
            "block_topology": lsblk,
            "docker_storage": docker_df,
            "restore_workspace": restore_workspace,
            "recommendation": {
                "strategy": strategy,
                "min_additional_free_mb": gap_mb,
                "suggested_new_free_mb": max(required_free_mb * 2, effective_free_mb + gap_mb),
                "reason": (
                    "Cleanup did not leave enough free space for restore drill safety."
                    if gap_mb > 0
                    else "Free space already satisfies restore drill threshold."
                ),
            },
        },
        "blocked_reasons": blocked_reasons,
        "degraded_reasons": degraded_reasons,
        "not_proven_by_this_report": [
            "This report does not expand a disk, mount a new filesystem or migrate Docker data.",
            "This report does not prove restore drill success.",
            "This report does not approve M1 release.",
        ],
    }


def build_storage_expansion_readiness_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    timeout_seconds: float = 90,
    required_free_mb: int = DEFAULT_REQUIRED_FREE_MB,
) -> dict[str, Any]:
    report = {
        "version": STORAGE_EXPANSION_READINESS_VERSION,
        "status": "blocked",
        "decision": "not_checked",
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": {
            "connects_ssh": bool(ssh_target and deploy_dir),
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "touches_backups_or_vectorstores": False,
            "deletes_images": False,
            "runs_docker_prune": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "device_names_echoed": False,
            "mountpoints_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "blocked_reasons": [],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [{"section": "input", "key": "missing_target", "finding": "SSH target and deploy directory are required."}]
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
        remote_script = REMOTE_SCRIPT.replace("\r\n", "\n").replace("\r", "\n")
        completed = _run_command(command, input_text=remote_script, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"section": "ssh", "key": "storage_probe_timeout", "finding": "SSH storage probe timed out."}]
        return report
    if completed.returncode != 0:
        report["ssh"] = {"status": "blocked", "returncode": completed.returncode, "stderr_echoed": False}
        report["blocked_reasons"] = [{"section": "ssh", "key": "storage_probe_failed", "finding": "SSH storage probe failed."}]
        return report
    parsed = _parse_probe_lines(completed.stdout)
    built = build_storage_expansion_readiness_report_from_parsed(
        parsed,
        required_free_mb=required_free_mb,
    )
    built["policy"]["connects_ssh"] = True
    built["target"] = report["target"]
    return built


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_storage_expansion_readiness_markdown(report: Mapping[str, Any]) -> str:
    sections = report.get("sections") if isinstance(report.get("sections"), Mapping) else {}
    disk = sections.get("disk_usage") if isinstance(sections.get("disk_usage"), Mapping) else {}
    restore = sections.get("restore_workspace") if isinstance(sections.get("restore_workspace"), Mapping) else {}
    recommendation = sections.get("recommendation") if isinstance(sections.get("recommendation"), Mapping) else {}
    topology = sections.get("block_topology") if isinstance(sections.get("block_topology"), Mapping) else {}
    sharing = sections.get("mount_sharing") if isinstance(sections.get("mount_sharing"), Mapping) else {}
    lines = [
        "# Storage Expansion Readiness",
        "",
        f"- Status: `{_cell(report.get('status'))}`",
        f"- Decision: `{_cell(report.get('decision'))}`",
        "- Policy: read-only SSH probe; no `.env`, logs, database rows, Redis keys, backups, vector stores, deletion or prune.",
        "",
        "## Disk Usage",
        "",
        "| Target | Status | Used % | Free MB | Filesystem |",
        "|---|---|---:|---:|---|",
    ]
    for key in ("root", "deploy", "docker_data_root"):
        item = disk.get(key) if isinstance(disk.get(key), Mapping) else {}
        lines.append(
            f"| `{key}` | `{_cell(item.get('status'))}` | {_cell(item.get('used_percent'))} | "
            f"{_cell(item.get('free_mb'))} | {_cell(item.get('fstype'))} |"
        )
    lines.extend(
        [
            "",
            "## Topology",
            "",
            f"- Root / deploy same mount: `{_cell(sharing.get('root_deploy_same_mount'))}`",
            f"- Root / Docker same mount: `{_cell(sharing.get('root_docker_same_mount'))}`",
            f"- Block disks: `{_cell(topology.get('disk_count'))}`",
            f"- Unmounted block nodes: `{_cell(topology.get('unmounted_block_count'))}`",
            f"- Largest unmounted block MB: `{_cell(topology.get('largest_unmounted_mb'))}`",
            "",
            "## Restore Workspace",
            "",
            f"- Status: `{_cell(restore.get('status'))}`",
            f"- Effective free: `{_cell(restore.get('effective_free_mb'))}` MB",
            f"- Required free: `{_cell(restore.get('required_free_mb'))}` MB",
            f"- Gap: `{_cell(restore.get('gap_mb'))}` MB",
            "",
            "## Recommendation",
            "",
            f"- Strategy: `{_cell(recommendation.get('strategy'))}`",
            f"- Minimum additional free MB: `{_cell(recommendation.get('min_additional_free_mb'))}`",
            f"- Suggested new free MB: `{_cell(recommendation.get('suggested_new_free_mb'))}`",
            f"- Reason: {_cell(recommendation.get('reason'))}",
        ]
    )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{_cell(item.get('section'))}.{_cell(item.get('key'))}`: {_cell(item.get('finding'))}")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--required-free-mb", type=int, default=DEFAULT_REQUIRED_FREE_MB)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_storage_expansion_readiness_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        timeout_seconds=args.timeout_seconds,
        required_free_mb=args.required_free_mb,
    )
    output_text = (
        build_storage_expansion_readiness_markdown(report)
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
