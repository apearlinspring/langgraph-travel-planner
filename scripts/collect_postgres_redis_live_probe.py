"""Collect redacted live PostgreSQL/Redis runtime probe evidence over SSH."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


POSTGRES_REDIS_LIVE_PROBE_VERSION = "postgres_redis_live_probe.v1"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"


REMOTE_PROBE_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

emit docker_version "$(timeout 5 docker --version 2>/dev/null || true)"
emit compose_version "$(timeout 5 docker compose version 2>/dev/null || timeout 5 docker-compose --version 2>/dev/null || true)"

if [ -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present "true"
  cd "$DEPLOY_DIR"
else
  emit deploy_dir_present "false"
  exit 0
fi

inspect_container() {
  service="$1"
  container="$2"
  if timeout 5 docker inspect "$container" >/dev/null 2>&1; then
    state="$(timeout 5 docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(timeout 5 docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container" 2>/dev/null || true)"
    restart="$(timeout 5 docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$container" 2>/dev/null || true)"
    ports="$(timeout 5 docker inspect -f '{{json .NetworkSettings.Ports}}' "$container" 2>/dev/null || true)"
    mounts="$(timeout 5 docker inspect -f '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}}|{{.RW}};{{end}}' "$container" 2>/dev/null || true)"
    emit container "$service|present|$state|$health|$restart|$ports|$mounts"
  else
    emit container "$service|missing|||||"
  fi
}

inspect_container postgres zhixing-postgres
inspect_container redis zhixing-redis

if timeout 5 docker exec zhixing-postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1' >/dev/null 2>&1; then
  emit postgres_pg_isready "passed"
else
  emit postgres_pg_isready "blocked"
fi

if timeout 5 docker exec zhixing-redis sh -lc 'if [ -n "${REDIS_PASSWORD:-}" ]; then redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping >/dev/null 2>&1; else redis-cli ping >/dev/null 2>&1; fi' >/dev/null 2>&1; then
  emit redis_ping "passed"
else
  emit redis_ping "blocked"
fi

if timeout 5 docker inspect -f '{{json .Config.Cmd}}' zhixing-redis 2>/dev/null | grep -q -- '--appendonly yes'; then
  emit redis_appendonly_declared "passed"
else
  emit redis_appendonly_declared "blocked"
fi
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


def _safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _ports_summary(raw_ports: str) -> dict[str, Any]:
    payload = _safe_json_loads(raw_ports)
    if not isinstance(payload, dict):
        return {
            "published": False,
            "public_bindings": [],
            "loopback_bindings": [],
            "raw_echoed": False,
        }
    public_bindings: list[str] = []
    loopback_bindings: list[str] = []
    published_ports: list[str] = []
    for container_port, bindings in payload.items():
        if not bindings:
            continue
        published_ports.append(str(container_port))
        if not isinstance(bindings, list):
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            host_ip = str(binding.get("HostIp") or "")
            host_port = str(binding.get("HostPort") or "")
            label = f"{container_port}->{host_ip or '*'}:{host_port or '*'}"
            if host_ip in {"127.0.0.1", "::1"}:
                loopback_bindings.append(label)
            else:
                public_bindings.append(label)
    return {
        "published": bool(published_ports),
        "published_ports": sorted(set(published_ports)),
        "public_bindings": public_bindings,
        "loopback_bindings": loopback_bindings,
        "raw_echoed": False,
    }


def _mounts_summary(raw_mounts: str, *, expected_destination: str) -> dict[str, Any]:
    mounts = []
    expected_present = False
    for chunk in str(raw_mounts or "").split(";"):
        if not chunk:
            continue
        parts = chunk.split("|")
        if len(parts) != 4:
            continue
        mount_type, name, destination, rw = parts
        expected_present = expected_present or destination == expected_destination
        mounts.append(
            {
                "type": mount_type,
                "name_present": bool(name),
                "destination": destination,
                "rw": rw == "true",
            }
        )
    return {
        "expected_destination": expected_destination,
        "expected_destination_present": expected_present,
        "mount_count": len(mounts),
        "mounts": mounts,
        "raw_echoed": False,
    }


def _container_section(row: str, *, expected_destination: str, port_policy: str) -> dict[str, Any]:
    parts = str(row or "").split("|", 6)
    if len(parts) < 7:
        return {
            "status": "blocked",
            "present": False,
            "finding": "Container probe row is incomplete.",
        }
    service, present, state, health, restart_policy, ports_raw, mounts_raw = parts
    ports = _ports_summary(ports_raw)
    mounts = _mounts_summary(mounts_raw, expected_destination=expected_destination)
    blocked_reasons = []
    degraded_reasons = []
    if present != "present":
        blocked_reasons.append({"key": "container_missing", "finding": f"{service} container is missing."})
    if state != "running":
        blocked_reasons.append({"key": "container_not_running", "finding": f"{service} container is not running."})
    if health and health != "healthy":
        blocked_reasons.append({"key": "container_not_healthy", "finding": f"{service} health is not healthy."})
    if not mounts["expected_destination_present"]:
        blocked_reasons.append({"key": "missing_persistent_mount", "finding": f"{service} persistent mount is missing."})
    if restart_policy not in {"unless-stopped", "always", "on-failure"}:
        degraded_reasons.append({"key": "restart_policy", "finding": f"{service} restart policy is not production-friendly."})
    if port_policy == "no_public_bindings" and ports["public_bindings"]:
        degraded_reasons.append({"key": "public_port_binding", "finding": f"{service} has non-loopback published port bindings."})
    status = "blocked" if blocked_reasons else ("degraded" if degraded_reasons else "passed")
    return {
        "status": status,
        "service": service,
        "present": present == "present",
        "state": state,
        "health": health,
        "restart_policy": restart_policy,
        "ports": ports,
        "mounts": mounts,
        "blocked_reasons": blocked_reasons,
        "degraded_reasons": degraded_reasons,
        "value_echoed": False,
    }


def _simple_probe_section(value: str, *, label: str) -> dict[str, Any]:
    passed = value == "passed"
    return {
        "status": "passed" if passed else "blocked",
        "finding": f"{label} passed." if passed else f"{label} failed.",
        "value_echoed": False,
    }


def build_postgres_redis_live_probe_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    timeout_seconds: float = 60,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build redacted PostgreSQL/Redis live runtime probe evidence."""

    report: dict[str, Any] = {
        "version": POSTGRES_REDIS_LIVE_PROBE_VERSION,
        "status": "blocked",
        "policy": {
            "read_only": True,
            "reads_env_file": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "reads_logs": False,
            "starts_services": False,
            "prints_secret_values": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
        },
        "sections": {},
        "not_proven_by_this_probe": [
            "This probe does not prove backup restore success; use the restore drill evidence for that.",
            "This probe does not inspect database contents, Redis keys, logs, dumps, or secret values.",
            "A passed single-server probe does not prove high availability, PITR, automatic failover, or multi-AZ resilience.",
            "Published Docker ports may still be protected by firewall rules; verify network exposure separately.",
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
            input_text=REMOTE_PROBE_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        report["sections"]["ssh"] = {
            "status": "blocked",
            "finding": "SSH read-only PostgreSQL/Redis probe timed out.",
            "value_echoed": False,
        }
        report["blocked_reasons"] = [{"key": "ssh_probe_timeout", "finding": "SSH read-only probe timed out."}]
        return report
    if completed.returncode != 0:
        report["sections"]["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_first_line": str(completed.stderr or "").splitlines()[:1],
            "value_echoed": False,
        }
        report["blocked_reasons"] = [{"key": "ssh_probe_failed", "finding": "SSH read-only probe failed."}]
        return report

    parsed = _parse_probe_lines(completed.stdout)
    containers = parsed.get("container") or []
    container_by_service = {row.split("|", 1)[0]: row for row in containers if "|" in row}
    postgres = _container_section(
        container_by_service.get("postgres", ""),
        expected_destination="/var/lib/postgresql/data",
        port_policy="no_public_bindings",
    )
    redis = _container_section(
        container_by_service.get("redis", ""),
        expected_destination="/data",
        port_policy="no_public_bindings",
    )
    sections = {
        "ssh": {
            "status": "passed",
            "docker_version_present": bool(_first(parsed, "docker_version")),
            "compose_version_present": bool(_first(parsed, "compose_version")),
            "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
        },
        "postgres_container": postgres,
        "postgres_pg_isready": _simple_probe_section(_first(parsed, "postgres_pg_isready"), label="pg_isready"),
        "redis_container": redis,
        "redis_ping": _simple_probe_section(_first(parsed, "redis_ping"), label="Redis PING"),
        "redis_appendonly": _simple_probe_section(_first(parsed, "redis_appendonly_declared"), label="Redis appendonly declaration"),
    }
    if not sections["ssh"]["deploy_dir_present"]:
        sections["ssh"]["status"] = "blocked"
        sections["ssh"]["finding"] = "Deployment directory is missing."
    report["sections"] = sections
    blocked = []
    degraded = []
    for key, section in sections.items():
        if section.get("status") == "blocked":
            blocked.append({"key": key, "finding": section.get("finding") or "Section did not pass."})
            for item in section.get("blocked_reasons") or []:
                blocked.append({"key": f"{key}.{item.get('key')}", "finding": item.get("finding")})
        elif section.get("status") == "degraded":
            degraded.append({"key": key, "finding": section.get("finding") or "Section is degraded."})
            for item in section.get("degraded_reasons") or []:
                degraded.append({"key": f"{key}.{item.get('key')}", "finding": item.get("finding")})
    report["blocked_reasons"] = blocked
    report["degraded_reasons"] = degraded
    report["declaration_statuses"] = {
        "ZHIXING_POSTGRES_LIVE_STATUS": "passed" if postgres["status"] in {"passed", "degraded"} and sections["postgres_pg_isready"]["status"] == "passed" else "blocked",
        "ZHIXING_REDIS_LIVE_STATUS": "passed" if redis["status"] in {"passed", "degraded"} and sections["redis_ping"]["status"] == "passed" and sections["redis_appendonly"]["status"] == "passed" else "blocked",
        "ZHIXING_POSTGRES_REDIS_LIVE_STATUS": "blocked" if blocked else ("degraded" if degraded else "passed"),
    }
    report["status"] = "blocked" if blocked else ("degraded" if degraded else "passed")
    return report


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("|", "\\|")
    return text or "-"


def build_postgres_redis_live_probe_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL / Redis Live Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: SSH target and deploy directory are not echoed.",
        "",
        "## Sections",
        "",
        "| Section | Status | Key evidence |",
        "|---|---|---|",
    ]
    for key, section in (report.get("sections") or {}).items():
        if not isinstance(section, Mapping):
            continue
        evidence = ""
        if key.endswith("_container"):
            ports = section.get("ports") or {}
            mounts = section.get("mounts") or {}
            evidence = (
                f"state={section.get('state')}, health={section.get('health')}, "
                f"mount={mounts.get('expected_destination_present')}, "
                f"public_ports={len(ports.get('public_bindings') or [])}"
            )
        else:
            evidence = section.get("finding") or json.dumps(section, ensure_ascii=False)[:120]
        lines.append(f"| `{key}` | `{section.get('status')}` | {_markdown_cell(evidence)} |")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_probe") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target, e.g. user@host. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    args = parser.parse_args(argv)

    report = build_postgres_redis_live_probe_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_postgres_redis_live_probe_markdown(report)
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
