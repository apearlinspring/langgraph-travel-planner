"""Collect redacted live server deployment probe evidence.

This probe is intentionally read-only. It connects through SSH, checks service
status and health endpoints, and reports only sanitized operational facts. It
does not read `.env`, logs, database dumps, vector store contents or secrets.
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


LIVE_SERVER_PROBE_VERSION = "live_server_probe.v1"
SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
DISK_WARN_USED_PERCENT = 90
DISK_FAIL_USED_PERCENT = 98
DISK_USED_PATTERN = re.compile(r"(?P<used>\d+)%\s+used")


REMOTE_PROBE_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"
PUBLIC_URL="$2"

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

emit hostname "$(hostname 2>/dev/null || true)"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  emit os_pretty "${PRETTY_NAME:-unknown}"
else
  emit os_pretty "unknown"
fi
emit kernel "$(uname -srmo 2>/dev/null || true)"
emit cpu_count "$(nproc 2>/dev/null || true)"
emit memory_summary "$(free -h 2>/dev/null | awk '/Mem:/ {print $2 " total, " $7 " available"}')"
emit root_disk_summary "$(df -h / 2>/dev/null | awk 'NR==2 {print $2 " size, " $5 " used"}')"
emit opt_disk_summary "$(df -h /opt 2>/dev/null | awk 'NR==2 {print $2 " size, " $5 " used"}')"
emit docker_version "$(timeout 5 docker --version 2>/dev/null || true)"
emit docker_compose_version "$(timeout 5 docker compose version 2>/dev/null || timeout 5 docker-compose --version 2>/dev/null || true)"

if [ -d "$DEPLOY_DIR" ]; then
  emit deploy_dir_present "true"
  cd "$DEPLOY_DIR"
else
  emit deploy_dir_present "false"
  exit 0
fi

if [ -d .git ]; then
  emit git_metadata "present"
  emit git_head "$(git rev-parse --short HEAD 2>/dev/null || true)"
  emit git_branch "$(git status --short --branch 2>/dev/null | head -n 1 || true)"
else
  emit git_metadata "absent"
fi

if [ -L current ]; then
  emit layout_mode "release_symlink"
  emit current_path_type "symlink"
elif [ -e current ]; then
  emit layout_mode "blocked_current_not_symlink"
  emit current_path_type "non_symlink"
elif [ -f docker-compose.yml ] || [ -d app ]; then
  emit layout_mode "legacy_flat"
  emit current_path_type "absent"
else
  emit layout_mode "empty_or_unknown"
  emit current_path_type "absent"
fi

test -f .env && emit root_env_file_present "true" || emit root_env_file_present "false"
test -f shared/.env && emit shared_env_file_present "true" || emit shared_env_file_present "false"
if [ -f .env ] || [ -f shared/.env ]; then
  emit env_file_present "true"
else
  emit env_file_present "false"
fi
test -d data/vectorstore && emit legacy_vectorstore_present "true" || emit legacy_vectorstore_present "false"
test -f data/vectorstore/chroma.sqlite3 && emit legacy_vectorstore_sqlite_present "true" || emit legacy_vectorstore_sqlite_present "false"
test -d data/vectorstore_internal && emit legacy_internal_vectorstore_present "true" || emit legacy_internal_vectorstore_present "false"
test -f data/vectorstore_internal/chroma.sqlite3 && emit legacy_internal_vectorstore_sqlite_present "true" || emit legacy_internal_vectorstore_sqlite_present "false"
test -d shared/data/vectorstore && emit shared_vectorstore_present "true" || emit shared_vectorstore_present "false"
test -f shared/data/vectorstore/chroma.sqlite3 && emit shared_vectorstore_sqlite_present "true" || emit shared_vectorstore_sqlite_present "false"
test -d shared/data/vectorstore_internal && emit shared_internal_vectorstore_present "true" || emit shared_internal_vectorstore_present "false"
test -f shared/data/vectorstore_internal/chroma.sqlite3 && emit shared_internal_vectorstore_sqlite_present "true" || emit shared_internal_vectorstore_sqlite_present "false"
if [ -d data/vectorstore ] || [ -d shared/data/vectorstore ]; then
  emit vectorstore_present "true"
else
  emit vectorstore_present "false"
fi
if [ -f data/vectorstore/chroma.sqlite3 ] || [ -f shared/data/vectorstore/chroma.sqlite3 ]; then
  emit vectorstore_sqlite_present "true"
else
  emit vectorstore_sqlite_present "false"
fi
if [ -d data/vectorstore_internal ] || [ -d shared/data/vectorstore_internal ]; then
  emit internal_vectorstore_present "true"
else
  emit internal_vectorstore_present "false"
fi
if [ -f data/vectorstore_internal/chroma.sqlite3 ] || [ -f shared/data/vectorstore_internal/chroma.sqlite3 ]; then
  emit internal_vectorstore_sqlite_present "true"
else
  emit internal_vectorstore_sqlite_present "false"
fi
emit backup_count "$(ls -dt /opt/zhixing-backup-* 2>/dev/null | wc -l | tr -d ' ')"

for pair in backend:zhixing-backend postgres:zhixing-postgres redis:zhixing-redis caddy:zhixing-caddy; do
  service="${pair%%:*}"
  container="${pair#*:}"
  if timeout 5 docker inspect "$container" >/dev/null 2>&1; then
    state="$(timeout 5 docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    health="$(timeout 5 docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container" 2>/dev/null || true)"
    status="$(timeout 5 docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
    ports="$(timeout 5 docker inspect -f '{{range $p, $conf := .NetworkSettings.Ports}}{{$p}} {{end}}' "$container" 2>/dev/null || true)"
    emit compose_service "$service|$state|$health|$status|$ports"
  else
    emit compose_service "$service|missing||missing|"
  fi
done

if body="$(timeout 10 curl -fsS --max-time 8 http://127.0.0.1:8000/health/live 2>/dev/null)"; then
  emit internal_health_live "$body"
else
  emit internal_health_live_error "$?"
fi

if body="$(timeout 10 curl -fsS --max-time 8 http://127.0.0.1:8000/health/ready 2>/dev/null)"; then
  emit internal_health_ready "$body"
else
  emit internal_health_ready_error "$?"
fi

if [ -n "$PUBLIC_URL" ]; then
  if body="$(timeout 10 curl -k -fsS --max-time 8 "$PUBLIC_URL/health/live" 2>/dev/null)"; then
    emit server_side_public_health_live "$body"
  else
    emit server_side_public_health_live_error "$?"
  fi

  if body="$(timeout 10 curl -k -fsS --max-time 8 "$PUBLIC_URL/health/ready" 2>/dev/null)"; then
    emit server_side_public_health_ready "$body"
  else
    emit server_side_public_health_ready_error "$?"
  fi
fi

if body="$(timeout 10 curl -fsS --max-time 8 http://127.0.0.1:8000/api/v1/mock-checkout/ORDER-DEMO12345678/status 2>/dev/null)"; then
  emit mock_checkout_status "$body"
else
  emit mock_checkout_error "$?"
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


def _json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _status_from_health(payload_text: str, error_text: str = "") -> dict[str, Any]:
    if error_text:
        return {
            "status": "blocked",
            "checked": True,
            "http_error_code": error_text,
            "finding": "Health endpoint probe failed.",
            "value_echoed": False,
        }
    payload = _json_loads(payload_text)
    if not isinstance(payload, dict):
        return {
            "status": "blocked",
            "checked": True,
            "finding": "Health endpoint did not return JSON.",
            "value_echoed": False,
        }
    health_status = str(payload.get("status") or "").lower()
    blocked = health_status not in {"alive", "ready"}
    return {
        "status": "blocked" if blocked else "passed",
        "checked": True,
        "reported_status": health_status,
        "environment": payload.get("environment"),
        "missing_required": payload.get("missing_required") or [],
        "blocking_items": payload.get("blocking_items") or [],
        "value_echoed": False,
        "finding": "Health endpoint returned acceptable status." if not blocked else "Health endpoint returned a blocking status.",
    }


def _status_from_mock_checkout(payload_text: str, error_text: str = "") -> dict[str, Any]:
    if error_text:
        report = {
            "status": "blocked",
            "checked": True,
            "http_error_code": error_text,
            "finding": "Mock checkout route probe failed.",
            "value_echoed": False,
        }
        if error_text == "22":
            report["finding"] = "Mock checkout route is not deployed on the live server yet."
        return report

    payload = _json_loads(payload_text)
    if not isinstance(payload, dict):
        return {
            "status": "blocked",
            "checked": True,
            "finding": "Mock checkout route did not return JSON.",
            "value_echoed": False,
        }
    demo_only = str(payload.get("status") or "").lower() == "demo_only"
    no_real_actions = all(
        payload.get(key) is False
        for key in ("real_payment", "real_booking", "inventory_locked", "fulfillment_triggered")
        if key in payload
    )
    passed = demo_only and no_real_actions
    return {
        "status": "passed" if passed else "blocked",
        "checked": True,
        "reported_status": payload.get("status"),
        "real_payment": payload.get("real_payment"),
        "real_booking": payload.get("real_booking"),
        "inventory_locked": payload.get("inventory_locked"),
        "fulfillment_triggered": payload.get("fulfillment_triggered"),
        "value_echoed": False,
        "finding": "Mock checkout route is deployed and remains demo-only." if passed else "Mock checkout route returned an unsafe or unexpected payload.",
    }


def _compose_services(lines: Sequence[str]) -> tuple[list[dict[str, Any]], str]:
    services: list[dict[str, Any]] = []
    for line in lines:
        payload = _json_loads(line)
        if not isinstance(payload, dict):
            continue
        services.append(
            {
                "service": payload.get("Service") or payload.get("Name") or "unknown",
                "state": payload.get("State"),
                "status": payload.get("Status"),
                "health": payload.get("Health") or "",
                "ports": payload.get("Ports") or "",
            }
        )
    required = {"backend", "postgres", "redis", "caddy"}
    seen = {str(item.get("service") or "") for item in services}
    missing = sorted(required - seen)
    unhealthy = [
        item
        for item in services
        if item.get("service") in required
        and (
            str(item.get("state") or "").lower() != "running"
            or str(item.get("health") or "").lower() in {"unhealthy", "starting"}
        )
    ]
    if missing or unhealthy:
        status = "blocked"
    else:
        status = "passed"
    return services, status


def _compose_services_from_rows(rows: Sequence[str]) -> tuple[list[dict[str, Any]], str]:
    services: list[dict[str, Any]] = []
    for row in rows:
        parts = str(row).split("|", 4)
        if len(parts) < 5:
            continue
        service, state, health, status_text, ports = parts
        services.append(
            {
                "service": service,
                "state": state,
                "status": status_text,
                "health": health,
                "ports": ports,
            }
        )
    return _compose_services(
        [
            json.dumps(
                {
                    "Service": item["service"],
                    "State": item["state"],
                    "Status": item["status"],
                    "Health": item["health"],
                    "Ports": item["ports"],
                },
                ensure_ascii=False,
            )
            for item in services
        ]
    )


def _disk_guard_from_summary(*, label: str, summary: str) -> dict[str, Any]:
    if not summary:
        return {
            "status": "not_checked",
            "label": label,
            "summary_present": False,
            "value_echoed": False,
            "finding": "Disk summary is not available.",
        }
    match = DISK_USED_PATTERN.search(summary)
    if not match:
        return {
            "status": "degraded",
            "label": label,
            "summary_present": True,
            "value_echoed": False,
            "finding": "Disk usage summary could not be parsed.",
        }
    used_percent = int(match.group("used"))
    payload = {
        "status": "passed",
        "label": label,
        "summary_present": True,
        "used_percent": used_percent,
        "warn_used_percent": DISK_WARN_USED_PERCENT,
        "fail_used_percent": DISK_FAIL_USED_PERCENT,
        "value_echoed": False,
        "finding": "Disk usage is within the runtime-build threshold.",
    }
    if used_percent >= DISK_FAIL_USED_PERCENT:
        payload["status"] = "blocked"
        payload["finding"] = "Disk usage is at or above the runtime-build fail threshold."
    elif used_percent >= DISK_WARN_USED_PERCENT:
        payload["status"] = "degraded"
        payload["finding"] = "Disk usage is above the runtime-build warning threshold."
    return payload


def build_live_server_probe_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    public_base_url: str = "",
    timeout_seconds: float = 30,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "version": LIVE_SERVER_PROBE_VERSION,
        "status": "blocked",
        "policy": {
            "read_only": True,
            "reads_env_file": False,
            "reads_logs": False,
            "starts_services": False,
            "prints_secret_values": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "public_base_url_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
            "public_base_url": PUBLIC_URL_PLACEHOLDER if public_base_url else "",
        },
        "sections": {},
        "not_proven_by_this_probe": [
            "The current local release has been deployed to the server.",
            "Real payment, booking, inventory lock, ticketing, or fulfillment works.",
            "Backups are restorable unless a separate restore drill has run.",
            "Public HTTPS works from every client network path.",
            "Secrets are current or rotated.",
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
        public_base_url,
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
            "finding": "SSH read-only probe timed out.",
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
    if parsed.get("compose_service"):
        compose_services, compose_status = _compose_services_from_rows(parsed.get("compose_service") or [])
    else:
        compose_services, compose_status = _compose_services(parsed.get("compose_json") or [])
    internal_live = _status_from_health(
        _first(parsed, "internal_health_live"),
        _first(parsed, "internal_health_live_error"),
    )
    internal_ready = _status_from_health(
        _first(parsed, "internal_health_ready"),
        _first(parsed, "internal_health_ready_error"),
    )
    public_live = _status_from_health(
        _first(parsed, "server_side_public_health_live"),
        _first(parsed, "server_side_public_health_live_error"),
    ) if public_base_url else {"status": "not_checked", "checked": False}
    public_ready = _status_from_health(
        _first(parsed, "server_side_public_health_ready"),
        _first(parsed, "server_side_public_health_ready_error"),
    ) if public_base_url else {"status": "not_checked", "checked": False}
    mock_status = _status_from_mock_checkout(
        _first(parsed, "mock_checkout_status"),
        _first(parsed, "mock_checkout_error"),
    )

    layout_mode = _first(parsed, "layout_mode")
    release_layout_blocked_reasons: list[dict[str, Any]] = []
    release_layout_degraded_reasons: list[dict[str, Any]] = []
    release_layout_status = "passed" if _first(parsed, "deploy_dir_present") == "true" else "blocked"
    if layout_mode == "blocked_current_not_symlink":
        release_layout_status = "blocked"
        release_layout_blocked_reasons.append(
            {
                "key": "current_not_symlink",
                "finding": "Deployment current path exists but is not a symlink.",
            }
        )
    if _first(parsed, "deploy_dir_present") != "true":
        release_layout_blocked_reasons.append(
            {"key": "deploy_dir_missing", "finding": "Deployment directory is missing."}
        )
    shared_public_sqlite = _first(parsed, "shared_vectorstore_sqlite_present") == "true"
    shared_internal_sqlite = _first(parsed, "shared_internal_vectorstore_sqlite_present") == "true"
    shared_env_file_present = _first(parsed, "shared_env_file_present") == "true"
    any_public_sqlite = _first(parsed, "vectorstore_sqlite_present") == "true"
    any_internal_sqlite = _first(parsed, "internal_vectorstore_sqlite_present") == "true"
    if layout_mode == "release_symlink" and (not shared_public_sqlite or not shared_internal_sqlite):
        release_layout_status = "blocked"
        release_layout_blocked_reasons.append(
            {
                "key": "shared_rag_chroma_missing",
                "finding": "Release-symlink layout requires shared public and internal RAG Chroma stores before service start.",
            }
        )
    elif not any_public_sqlite or not any_internal_sqlite:
        if release_layout_status != "blocked":
            release_layout_status = "degraded"
        release_layout_degraded_reasons.append(
            {
                "key": "rag_chroma_not_confirmed",
                "finding": "RAG Chroma store files were not both confirmed; runtime readiness must verify or rebuild them.",
            }
        )
    if layout_mode == "release_symlink" and not shared_env_file_present:
        if release_layout_status != "blocked":
            release_layout_status = "degraded"
        release_layout_degraded_reasons.append(
            {
                "key": "shared_env_missing",
                "finding": "Release-symlink layout should converge runtime configuration into shared/.env before the next default deploy.",
            }
        )
    root_disk = _disk_guard_from_summary(
        label="root",
        summary=_first(parsed, "root_disk_summary"),
    )
    opt_disk = _disk_guard_from_summary(
        label="opt",
        summary=_first(parsed, "opt_disk_summary"),
    )
    disk_checks = {
        "root": root_disk,
        "opt": opt_disk,
    }
    host_blocked_reasons = [
        {
            "key": f"{label}_disk_usage",
            "finding": disk.get("finding"),
        }
        for label, disk in disk_checks.items()
        if disk.get("status") == "blocked"
    ]
    host_degraded_reasons = [
        {
            "key": f"{label}_disk_usage",
            "finding": disk.get("finding"),
        }
        for label, disk in disk_checks.items()
        if disk.get("status") == "degraded"
    ]
    host_status = "blocked" if host_blocked_reasons else ("degraded" if host_degraded_reasons else "passed")

    sections = {
        "host": {
            "status": host_status,
            "hostname_present": bool(_first(parsed, "hostname")),
            "os_pretty": _first(parsed, "os_pretty"),
            "kernel": _first(parsed, "kernel"),
            "cpu_count": _first(parsed, "cpu_count"),
            "memory_summary": _first(parsed, "memory_summary"),
            "root_disk_summary": _first(parsed, "root_disk_summary"),
            "opt_disk_summary": _first(parsed, "opt_disk_summary"),
            "disk_checks": disk_checks,
            "blocked_reasons": host_blocked_reasons,
            "degraded_reasons": host_degraded_reasons,
            "docker_version": _first(parsed, "docker_version"),
            "docker_compose_version": _first(parsed, "docker_compose_version"),
        },
        "release_layout": {
            "status": release_layout_status,
            "deploy_dir_present": _first(parsed, "deploy_dir_present") == "true",
            "layout_mode": layout_mode,
            "current_path_type": _first(parsed, "current_path_type"),
            "git_metadata": _first(parsed, "git_metadata"),
            "env_file_present": _first(parsed, "env_file_present") == "true",
            "root_env_file_present": _first(parsed, "root_env_file_present") == "true",
            "shared_env_file_present": shared_env_file_present,
            "vectorstore_present": _first(parsed, "vectorstore_present") == "true",
            "vectorstore_sqlite_present": _first(parsed, "vectorstore_sqlite_present") == "true",
            "internal_vectorstore_present": _first(parsed, "internal_vectorstore_present") == "true",
            "internal_vectorstore_sqlite_present": _first(parsed, "internal_vectorstore_sqlite_present") == "true",
            "legacy_vectorstore_present": _first(parsed, "legacy_vectorstore_present") == "true",
            "legacy_vectorstore_sqlite_present": _first(parsed, "legacy_vectorstore_sqlite_present") == "true",
            "legacy_internal_vectorstore_present": _first(parsed, "legacy_internal_vectorstore_present") == "true",
            "legacy_internal_vectorstore_sqlite_present": _first(parsed, "legacy_internal_vectorstore_sqlite_present") == "true",
            "shared_vectorstore_present": _first(parsed, "shared_vectorstore_present") == "true",
            "shared_vectorstore_sqlite_present": shared_public_sqlite,
            "shared_internal_vectorstore_present": _first(parsed, "shared_internal_vectorstore_present") == "true",
            "shared_internal_vectorstore_sqlite_present": shared_internal_sqlite,
            "backup_count": _first(parsed, "backup_count", "0"),
            "blocked_reasons": release_layout_blocked_reasons,
            "degraded_reasons": release_layout_degraded_reasons,
            "finding": "Deployment directory is present."
            if release_layout_status == "passed"
            else (
                "Deployment layout blocks release-symlink deployment; inspect current path or shared RAG mount before deploying."
                if release_layout_status == "blocked"
                else "Deployment layout is present but has release-symlink convergence warnings."
            ),
        },
        "compose_services": {
            "status": compose_status,
            "services": compose_services,
        },
        "internal_health": {
            "status": "passed"
            if internal_live["status"] == "passed" and internal_ready["status"] == "passed"
            else "blocked",
            "live": internal_live,
            "ready": internal_ready,
        },
        "server_side_public_health": {
            "status": "passed"
            if public_live["status"] == "passed" and public_ready["status"] == "passed"
            else ("not_checked" if not public_base_url else "blocked"),
            "live": public_live,
            "ready": public_ready,
        },
        "mock_checkout_live_route": mock_status,
    }
    report["sections"] = sections
    blocked = [
        {"key": key, "finding": section.get("finding") or "Section did not pass."}
        for key, section in sections.items()
        if section.get("status") == "blocked"
    ]
    degraded = [
        {"key": key, "finding": section.get("finding") or "Section is degraded."}
        for key, section in sections.items()
        if section.get("status") == "degraded"
    ]
    for key, section in sections.items():
        if not isinstance(section, Mapping):
            continue
        if section.get("status") == "blocked":
            for item in section.get("blocked_reasons") or []:
                blocked.append({"key": f"{key}.{item.get('key')}", "finding": item.get("finding")})
        elif section.get("status") == "degraded":
            for item in section.get("degraded_reasons") or []:
                degraded.append({"key": f"{key}.{item.get('key')}", "finding": item.get("finding")})
    report["blocked_reasons"] = blocked
    report["degraded_reasons"] = degraded
    report["status"] = "blocked" if blocked else ("degraded" if degraded else "passed")
    return report


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("|", "\\|")
    return text or "-"


def build_live_server_probe_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Live Server Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: SSH target, deploy directory and public URL are not echoed.",
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
        if key == "host":
            evidence = f"{section.get('os_pretty')} / {section.get('cpu_count')} CPU / {section.get('memory_summary')}"
        elif key == "compose_services":
            services = section.get("services") or []
            evidence = ", ".join(
                f"{item.get('service')}:{item.get('state')}/{item.get('health') or 'no-health'}"
                for item in services
                if isinstance(item, Mapping)
            )
        elif key == "internal_health":
            evidence = f"live={((section.get('live') or {}).get('reported_status'))}, ready={((section.get('ready') or {}).get('reported_status'))}"
        elif key == "mock_checkout_live_route":
            evidence = section.get("finding") or section.get("reported_status") or ""
        elif key == "release_layout":
            evidence = (
                f"layout={section.get('layout_mode')}, "
                f"env=root:{section.get('root_env_file_present')}/shared:{section.get('shared_env_file_present')}, "
                f"vectorstore={section.get('vectorstore_present')}/sqlite:{section.get('vectorstore_sqlite_present')}, "
                f"shared_sqlite=public:{section.get('shared_vectorstore_sqlite_present')}/internal:{section.get('shared_internal_vectorstore_sqlite_present')}"
            )
        else:
            evidence = json.dumps(section, ensure_ascii=False)[:160]
        lines.append(f"| `{key}` | `{section.get('status')}` | {_markdown_cell(evidence)} |")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_probe") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target, e.g. user@host. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--public-base-url", default="", help="Public HTTPS base URL. Redacted from output.")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)

    report = build_live_server_probe_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        public_base_url=args.public_base_url,
        timeout_seconds=args.timeout_seconds,
    )
    if args.markdown:
        print(build_live_server_probe_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
