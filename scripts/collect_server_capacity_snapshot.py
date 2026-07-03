"""Collect a redacted read-only server capacity snapshot over SSH.

This script records host CPU, memory, load, disk and Docker container resource
signals for M1 operations. It does not read `.env`, logs, database rows, Redis
keys, backups, vector stores or response bodies.
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


SERVER_CAPACITY_SNAPSHOT_VERSION = "server_capacity_snapshot.v1"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
DISK_WARN_USED_PERCENT = 90
DISK_FAIL_USED_PERCENT = 98
DEFAULT_MIN_CPU_COUNT = 2
DEFAULT_MIN_MEM_AVAILABLE_MB = 1024
DEFAULT_MAX_LOAD_PER_CPU = 2.0
DEFAULT_MAX_CONTAINER_MEM_PERCENT = 85.0
KNOWN_CONTAINER_SERVICES = {
    "zhixing-backend": "backend",
    "zhixing-postgres": "postgres",
    "zhixing-redis": "redis",
    "zhixing-caddy": "caddy",
}


REMOTE_CAPACITY_SCRIPT = r"""
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

emit cpu_count "$(nproc 2>/dev/null || true)"
emit loadavg "$(awk '{print $1 "|" $2 "|" $3}' /proc/loadavg 2>/dev/null || true)"
emit uptime_seconds "$(awk '{printf "%.0f", $1}' /proc/uptime 2>/dev/null || true)"
awk '
  /^(MemTotal|MemAvailable|SwapTotal|SwapFree):/ {gsub(":", "", $1); print "meminfo\t" $1 "|" $2}
' /proc/meminfo 2>/dev/null || true
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
emit docker_version_present "$(docker --version >/dev/null 2>&1 && echo true || echo false)"

for container in zhixing-backend zhixing-postgres zhixing-redis zhixing-caddy; do
  if timeout 5 docker inspect "$container" >/dev/null 2>&1; then
    state="$(timeout 5 docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(timeout 5 docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container" 2>/dev/null || true)"
    restarts="$(timeout 5 docker inspect -f '{{.RestartCount}}' "$container" 2>/dev/null || true)"
    emit container_state "$container|$state|$health|$restarts"
  else
    emit container_state "$container|missing||0"
  fi
done

if timeout 20 docker stats --no-stream \
  --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}|{{.PIDs}}' \
  >/tmp/zhixing-docker-stats.$$ 2>/dev/null; then
  while IFS= read -r line; do
    [ -n "$line" ] && emit docker_stat "$line"
  done </tmp/zhixing-docker-stats.$$
fi
rm -f /tmp/zhixing-docker-stats.$$
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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_percent(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", str(value or ""))
    if not match:
        return None
    return round(float(match.group(1)), 3)


def _meminfo(rows: Sequence[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for row in rows:
        key, _, value = str(row or "").partition("|")
        if key:
            parsed[key] = _to_int(value)
    return parsed


def _disk_line(value: str, *, label: str) -> dict[str, Any]:
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
        "total_mb": total,
        "free_mb": free,
        "used_percent": used,
        "mount_present": bool(mount),
        "warn_used_percent": DISK_WARN_USED_PERCENT,
        "fail_used_percent": DISK_FAIL_USED_PERCENT,
        "value_echoed": False,
        "finding": finding,
    }


def _host_capacity(
    parsed: Mapping[str, list[str]],
    *,
    min_cpu_count: int,
    min_mem_available_mb: int,
    max_load_per_cpu: float,
) -> dict[str, Any]:
    cpu_count = _to_int(_first(parsed, "cpu_count"))
    load_parts = str(_first(parsed, "loadavg")).split("|")
    load_1m = _to_float(load_parts[0]) if len(load_parts) > 0 else 0.0
    load_5m = _to_float(load_parts[1]) if len(load_parts) > 1 else 0.0
    load_per_cpu = round(load_1m / cpu_count, 3) if cpu_count > 0 else None
    mem = _meminfo(parsed.get("meminfo") or [])
    mem_total_mb = round((mem.get("MemTotal") or 0) / 1024)
    mem_available_mb = round((mem.get("MemAvailable") or 0) / 1024)
    mem_used_percent = (
        round(((mem_total_mb - mem_available_mb) / mem_total_mb) * 100, 2)
        if mem_total_mb > 0
        else None
    )
    root_disk = _disk_line(_first(parsed, "root_disk"), label="root")
    deploy_disk = _disk_line(_first(parsed, "deploy_disk"), label="deploy")

    blockers: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    if cpu_count <= 0:
        blockers.append({"key": "cpu_count_missing", "finding": "CPU count could not be collected."})
    elif cpu_count < min_cpu_count:
        degraded.append({"key": "cpu_count", "finding": "CPU count is below the M1 recommendation."})
    if mem_available_mb <= 0:
        degraded.append({"key": "memory_available_missing", "finding": "Available memory could not be collected."})
    elif mem_available_mb < min_mem_available_mb:
        degraded.append({"key": "memory_available", "finding": "Available memory is below the M1 recommendation."})
    if load_per_cpu is not None and load_per_cpu > max_load_per_cpu:
        degraded.append({"key": "load_per_cpu", "finding": "1-minute load per CPU is above the target."})
    for disk in (root_disk, deploy_disk):
        if disk["status"] == "blocked":
            blockers.append({"key": f"{disk['label']}_disk", "finding": disk["finding"]})
        elif disk["status"] == "degraded":
            degraded.append({"key": f"{disk['label']}_disk", "finding": disk["finding"]})
    return {
        "status": "blocked" if blockers else ("degraded" if degraded else "passed"),
        "cpu_count": cpu_count,
        "load_1m": load_1m,
        "load_5m": load_5m,
        "load_per_cpu_1m": load_per_cpu,
        "uptime_seconds": _to_int(_first(parsed, "uptime_seconds")),
        "memory": {
            "total_mb": mem_total_mb,
            "available_mb": mem_available_mb,
            "used_percent": mem_used_percent,
            "swap_total_mb": round((mem.get("SwapTotal") or 0) / 1024),
            "swap_free_mb": round((mem.get("SwapFree") or 0) / 1024),
        },
        "disk": {
            "root": root_disk,
            "deploy": deploy_disk,
        },
        "thresholds": {
            "min_cpu_count": min_cpu_count,
            "min_mem_available_mb": min_mem_available_mb,
            "max_load_per_cpu": max_load_per_cpu,
        },
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
    }


def _container_service(name: str) -> str:
    clean = str(name or "").strip().lstrip("/")
    return KNOWN_CONTAINER_SERVICES.get(clean, "other")


def _container_states(rows: Sequence[str]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for row in rows:
        name, state, health, restarts = (str(row or "").split("|", 3) + ["", "", "", ""])[:4]
        states.append(
            {
                "service": _container_service(name),
                "state": state or "unknown",
                "health": health or "",
                "restart_count": _to_int(restarts),
                "container_name_echoed": False,
            }
        )
    return states


def _docker_stats(rows: Sequence[str]) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for row in rows:
        parts = (str(row or "").split("|", 6) + ["", "", "", "", "", "", ""])[:7]
        name, cpu, mem_usage, mem_percent, net_io, block_io, pids = parts
        stats.append(
            {
                "service": _container_service(name),
                "cpu_percent": _parse_percent(cpu),
                "memory_usage": mem_usage,
                "memory_percent": _parse_percent(mem_percent),
                "net_io": net_io,
                "block_io": block_io,
                "pids": _to_int(pids),
                "container_name_echoed": False,
            }
        )
    return stats


def _container_capacity(
    parsed: Mapping[str, list[str]],
    *,
    max_container_mem_percent: float,
) -> dict[str, Any]:
    states = _container_states(parsed.get("container_state") or [])
    stats = _docker_stats(parsed.get("docker_stat") or [])
    blockers: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    required = {"backend", "postgres", "redis", "caddy"}
    seen = {item["service"] for item in states}
    for service in sorted(required - seen):
        blockers.append({"key": f"{service}_missing", "finding": "Required container state was not found."})
    for item in states:
        service = item["service"]
        if service == "other":
            continue
        if item["state"] != "running":
            blockers.append({"key": f"{service}_not_running", "finding": "Required container is not running."})
        if item["health"] in {"unhealthy", "starting"}:
            blockers.append({"key": f"{service}_health", "finding": "Required container health is not ready."})
        if item["restart_count"] > 0:
            degraded.append({"key": f"{service}_restart_count", "finding": "Container has restarted since creation."})
    for item in stats:
        service = item["service"]
        mem_percent = item.get("memory_percent")
        if service != "other" and isinstance(mem_percent, int | float) and mem_percent > max_container_mem_percent:
            degraded.append({"key": f"{service}_memory_percent", "finding": "Container memory percentage is above the target."})
    return {
        "status": "blocked" if blockers else ("degraded" if degraded else "passed"),
        "docker_available": _first(parsed, "docker_available") == "true",
        "docker_version_present": _first(parsed, "docker_version_present") == "true",
        "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
        "states": states,
        "stats": stats,
        "thresholds": {
            "max_container_mem_percent": max_container_mem_percent,
        },
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
    }


def build_server_capacity_snapshot_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    timeout_seconds: float = 90,
    min_cpu_count: int = DEFAULT_MIN_CPU_COUNT,
    min_mem_available_mb: int = DEFAULT_MIN_MEM_AVAILABLE_MB,
    max_load_per_cpu: float = DEFAULT_MAX_LOAD_PER_CPU,
    max_container_mem_percent: float = DEFAULT_MAX_CONTAINER_MEM_PERCENT,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a redacted server capacity snapshot."""

    report: dict[str, Any] = {
        "version": SERVER_CAPACITY_SNAPSHOT_VERSION,
        "status": "blocked",
        "policy": {
            "read_only": True,
            "reads_env_file": False,
            "reads_logs": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "starts_services": False,
            "stops_services": False,
            "prints_secret_values": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "not_proven_by_this_snapshot": [
            "This is a point-in-time resource snapshot, not a load test or soak test.",
            "It does not prove chat throughput, LLM latency, external API quotas, autoscaling, or formal SLO compliance.",
            "Container memory and CPU stats are sampled once and can change quickly under traffic.",
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
            input_text=REMOTE_CAPACITY_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["blocked_reasons"] = [{"key": "ssh_snapshot_timeout", "finding": "SSH capacity snapshot timed out."}]
        return report
    if completed.returncode != 0:
        report["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        report["blocked_reasons"] = [{"key": "ssh_snapshot_failed", "finding": "SSH capacity snapshot failed."}]
        return report
    parsed = _parse_probe_lines(completed.stdout)
    host = _host_capacity(
        parsed,
        min_cpu_count=min_cpu_count,
        min_mem_available_mb=min_mem_available_mb,
        max_load_per_cpu=max_load_per_cpu,
    )
    containers = _container_capacity(
        parsed,
        max_container_mem_percent=max_container_mem_percent,
    )
    blockers = []
    degraded = []
    for section_name, section in {"host_capacity": host, "container_capacity": containers}.items():
        for item in section.get("blocked_reasons") or []:
            blockers.append({"section": section_name, **item})
        for item in section.get("degraded_reasons") or []:
            degraded.append({"section": section_name, **item})
    if _first(parsed, "docker_available") != "true":
        blockers.append({"section": "container_capacity", "key": "docker_unavailable", "finding": "Docker CLI is not available."})
    report.update(
        {
            "status": "blocked" if blockers else ("degraded" if degraded else "passed"),
            "sections": {
                "host_capacity": host,
                "container_capacity": containers,
            },
            "blocked_reasons": blockers,
            "degraded_reasons": degraded,
            "interview_talking_points": [
                "Capacity evidence separates host resource pressure from application health.",
                "Disk high-water is treated as a release risk even when containers and health checks pass.",
                "M1 capacity claims stay scoped to point-in-time evidence plus low-risk concurrency probes.",
            ],
        }
    )
    return report


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_server_capacity_snapshot_markdown(report: Mapping[str, Any]) -> str:
    host = ((report.get("sections") or {}).get("host_capacity") or {})
    containers = ((report.get("sections") or {}).get("container_capacity") or {})
    lines = [
        "# Server Capacity Snapshot",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: SSH target, deploy directory and container names are not echoed.",
        "",
        "## Host",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| CPU count | {_markdown_cell(host.get('cpu_count'))} |",
        f"| Load 1m | {_markdown_cell(host.get('load_1m'))} |",
        f"| Load per CPU | {_markdown_cell(host.get('load_per_cpu_1m'))} |",
        f"| Memory available MB | {_markdown_cell((host.get('memory') or {}).get('available_mb'))} |",
        f"| Memory used % | {_markdown_cell((host.get('memory') or {}).get('used_percent'))} |",
        "",
        "## Disk",
        "",
        "| Target | Status | Used % | Free MB |",
        "|---|---|---:|---:|",
    ]
    for key, disk in (host.get("disk") or {}).items():
        if isinstance(disk, Mapping):
            lines.append(
                f"| {key} | `{_markdown_cell(disk.get('status'))}` | "
                f"{_markdown_cell(disk.get('used_percent'))} | {_markdown_cell(disk.get('free_mb'))} |"
            )
    lines.extend(
        [
            "",
            "## Containers",
            "",
            "| Service | State | Health | Restarts | CPU % | Mem % | PIDs |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    stats_by_service = {
        str(item.get("service")): item
        for item in containers.get("stats") or []
        if isinstance(item, Mapping)
    }
    for state in containers.get("states") or []:
        if not isinstance(state, Mapping):
            continue
        service = str(state.get("service") or "")
        stat = stats_by_service.get(service, {})
        lines.append(
            "| "
            f"`{_markdown_cell(service)}` | "
            f"`{_markdown_cell(state.get('state'))}` | "
            f"`{_markdown_cell(state.get('health') or 'no-health')}` | "
            f"{_markdown_cell(state.get('restart_count'))} | "
            f"{_markdown_cell(stat.get('cpu_percent'))} | "
            f"{_markdown_cell(stat.get('memory_percent'))} | "
            f"{_markdown_cell(stat.get('pids'))} |"
        )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_snapshot") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--min-cpu-count", type=int, default=DEFAULT_MIN_CPU_COUNT)
    parser.add_argument("--min-mem-available-mb", type=int, default=DEFAULT_MIN_MEM_AVAILABLE_MB)
    parser.add_argument("--max-load-per-cpu", type=float, default=DEFAULT_MAX_LOAD_PER_CPU)
    parser.add_argument("--max-container-mem-percent", type=float, default=DEFAULT_MAX_CONTAINER_MEM_PERCENT)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    args = parser.parse_args(argv)

    report = build_server_capacity_snapshot_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        timeout_seconds=args.timeout_seconds,
        min_cpu_count=args.min_cpu_count,
        min_mem_available_mb=args.min_mem_available_mb,
        max_load_per_cpu=args.max_load_per_cpu,
        max_container_mem_percent=args.max_container_mem_percent,
    )
    output_text = (
        build_server_capacity_snapshot_markdown(report)
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
