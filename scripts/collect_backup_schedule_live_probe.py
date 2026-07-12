"""Collect redacted live backup schedule and freshness evidence over SSH."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


BACKUP_SCHEDULE_LIVE_PROBE_VERSION = "backup_schedule_live_probe.v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._remote_probe_helpers import (  # noqa: E402
    first_value as _first,
    parse_tabbed_probe_lines as _parse_probe_lines,
    run_utf8_command as _run_command,
)


SERVER_TARGET_PLACEHOLDER = "<server-target>"
DEPLOY_DIR_PLACEHOLDER = "<deploy-dir>"
BACKUP_DIR_PLACEHOLDER = "<backup-dir>"


REMOTE_PROBE_SCRIPT = r"""
set -eu
DEPLOY_DIR="$1"
BACKUP_DIR="${2:-}"
MAX_AGE_SECONDS="$3"
MIN_SIZE_BYTES="$4"
MAX_SCAN="$5"
NOW="$(date +%s)"

if [ "$BACKUP_DIR" = "__ZHIXING_NO_BACKUP_DIR__" ]; then
  BACKUP_DIR=""
fi

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

bool_file() {
  if [ -f "$1" ]; then
    printf true
  else
    printf false
  fi
}

file_size() {
  if [ -f "$1" ]; then
    wc -c < "$1" 2>/dev/null | tr -d ' '
  else
    printf 0
  fi
}

extension_for() {
  case "$1" in
    *.sql.gz) printf '.sql.gz' ;;
    *.dump) printf '.dump' ;;
    *.backup) printf '.backup' ;;
    *.sql) printf '.sql' ;;
    *) printf '' ;;
  esac
}

backup_roots() {
  if [ -n "$BACKUP_DIR" ]; then
    printf '%s\n' "$BACKUP_DIR"
    return 0
  fi
  printf '%s\n' "$DEPLOY_DIR" /opt /var/backups
}

emit deploy_dir_present "$([ -d "$DEPLOY_DIR" ] && printf true || printf false)"
if [ -n "$BACKUP_DIR" ]; then
  emit backup_dir_supplied true
  emit backup_dir_present "$([ -d "$BACKUP_DIR" ] && printf true || printf false)"
else
  emit backup_dir_supplied false
  emit backup_dir_present not_supplied
fi

scan_postgres_backups() {
  count=0
  scanned=0
  truncated=false
  latest_mtime=0
  latest_size=0
  latest_ext=""
  while IFS= read -r root; do
    [ -d "$root" ] || continue
    while IFS='|' read -r mtime size path; do
      [ -n "$path" ] || continue
      scanned=$((scanned + 1))
      if [ "$scanned" -gt "$MAX_SCAN" ]; then
        truncated=true
        break 2
      fi
      count=$((count + 1))
      mtime_int="${mtime%.*}"
      if [ "${mtime_int:-0}" -gt "$latest_mtime" ]; then
        latest_mtime="$mtime_int"
        latest_size="${size:-0}"
        latest_ext="$(extension_for "$path")"
      fi
    done < <(
      find "$root" -xdev -maxdepth 5 -type f \
        \( -name '*.dump' -o -name '*.backup' -o -name '*.sql' -o -name '*.sql.gz' \) \
        -printf '%T@|%s|%p\n' 2>/dev/null
    )
  done < <(backup_roots)
  latest_age=-1
  if [ "$latest_mtime" -gt 0 ]; then
    latest_age=$((NOW - latest_mtime))
  fi
  emit postgres_backup_scan "$count|$scanned|$truncated|$latest_ext|$latest_size|$latest_age|$MAX_AGE_SECONDS|$MIN_SIZE_BYTES"
}

scan_rag_restore_artifacts() {
  count=0
  scanned=0
  truncated=false
  latest_mtime=0
  latest_kind=""
  latest_public=false
  latest_internal=false
  latest_public_size=0
  latest_internal_size=0
  latest_archive_size=0
  while IFS= read -r root; do
    [ -d "$root" ] || continue
    while IFS='|' read -r mtime path; do
      [ -n "$path" ] || continue
      scanned=$((scanned + 1))
      if [ "$scanned" -gt "$MAX_SCAN" ]; then
        truncated=true
        break 2
      fi
      count=$((count + 1))
      mtime_int="${mtime%.*}"
      if [ "${mtime_int:-0}" -gt "$latest_mtime" ]; then
        latest_mtime="$mtime_int"
        if [ -d "$path" ]; then
          latest_kind="restore_drill_dir"
          public_sqlite="$path/vectorstore/chroma.sqlite3"
          internal_sqlite="$path/vectorstore_internal/chroma.sqlite3"
          latest_public="$(bool_file "$public_sqlite")"
          latest_internal="$(bool_file "$internal_sqlite")"
          latest_public_size="$(file_size "$public_sqlite")"
          latest_internal_size="$(file_size "$internal_sqlite")"
          latest_archive_size=0
        else
          latest_kind="vectorstore_archive"
          latest_public=not_checked
          latest_internal=not_checked
          latest_public_size=0
          latest_internal_size=0
          latest_archive_size="$(file_size "$path")"
        fi
      fi
    done < <(
      find "$root" -xdev -maxdepth 5 \
        \( -type d -name 'rag-restore-drill-*' -o -type f -name 'rag-vectorstores.tgz' \) \
        -printf '%T@|%p\n' 2>/dev/null
    )
  done < <(backup_roots)
  latest_age=-1
  if [ "$latest_mtime" -gt 0 ]; then
    latest_age=$((NOW - latest_mtime))
  fi
  emit rag_restore_scan "$count|$scanned|$truncated|$latest_age|$latest_public|$latest_internal|$latest_public_size|$latest_internal_size|$MAX_AGE_SECONDS|$latest_kind|$latest_archive_size"
}

scan_release_backups() {
  count=0
  latest_mtime=0
  while IFS='|' read -r mtime path; do
    [ -n "$path" ] || continue
    count=$((count + 1))
    mtime_int="${mtime%.*}"
    if [ "${mtime_int:-0}" -gt "$latest_mtime" ]; then
      latest_mtime="$mtime_int"
    fi
  done < <(find /opt -maxdepth 1 -type d -name 'zhixing-backup-*' -printf '%T@|%p\n' 2>/dev/null)
  latest_age=-1
  if [ "$latest_mtime" -gt 0 ]; then
    latest_age=$((NOW - latest_mtime))
  fi
  emit release_backup_scan "$count|$latest_age"
}

scan_schedules() {
  user_cron=0
  system_cron=0
  systemd_timers=0
  cron_daemon=unknown
  if command -v crontab >/dev/null 2>&1; then
    user_cron="$(
      crontab -l 2>/dev/null \
        | awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*#/ {next} /(zhixing|backup|pg_dump|postgres|rag-restore|init_rag)/ {c++} END{print c+0}'
    )"
  fi
  if [ -f /etc/crontab ] || [ -d /etc/cron.d ]; then
    system_cron="$(
      grep -RIEi '(zhixing|backup|pg_dump|postgres|rag-restore|init_rag)' /etc/crontab /etc/cron.d 2>/dev/null \
        | grep -Ev '^[[:space:]]*#' \
        | wc -l \
        | tr -d ' '
    )"
  fi
  for service in cron crond; do
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$service" 2>/dev/null; then
      cron_daemon=active
      break
    fi
    if pgrep -x "$service" >/dev/null 2>&1; then
      cron_daemon=active
      break
    fi
  done
  if command -v systemctl >/dev/null 2>&1; then
    timer_list="$(systemctl list-timers --all --no-legend 2>/dev/null || true)"
    timer_files="$(systemctl list-unit-files --type=timer --no-legend 2>/dev/null || true)"
    systemd_timers="$(
      printf '%s\n%s\n' "$timer_list" "$timer_files" \
        | grep -Ei '(zhixing|backup|postgres|pg|rag)' \
        | wc -l \
        | tr -d ' '
    )"
  fi
  emit schedule_scan "${user_cron:-0}|${system_cron:-0}|${systemd_timers:-0}|$cron_daemon"
}

scan_postgres_backups
scan_rag_restore_artifacts
scan_release_backups
scan_schedules
"""


def _parts(value: str, expected: int) -> list[str]:
    pieces = str(value or "").split("|")
    if len(pieces) < expected:
        pieces.extend([""] * (expected - len(pieces)))
    return pieces[:expected]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _postgres_backup_section(row: str) -> dict[str, Any]:
    count, scanned, truncated, extension, size, age, max_age, min_size = _parts(row, 8)
    candidate_count = _int(count)
    scanned_count = _int(scanned)
    size_bytes = _int(size)
    age_seconds = _int(age, -1)
    max_age_seconds = _int(max_age)
    min_size_bytes = _int(min_size)
    blocked_reasons: list[dict[str, str]] = []
    if truncated == "true":
        blocked_reasons.append(
            {"key": "scan_truncated", "finding": "Backup scan reached the maximum candidate limit."}
        )
    if candidate_count <= 0:
        blocked_reasons.append({"key": "missing_backup", "finding": "No PostgreSQL backup artifact was found."})
    if candidate_count > 0 and size_bytes < min_size_bytes:
        blocked_reasons.append(
            {"key": "backup_too_small", "finding": "Latest PostgreSQL backup artifact is too small."}
        )
    if candidate_count > 0 and age_seconds > max_age_seconds:
        blocked_reasons.append(
            {"key": "backup_stale", "finding": "Latest PostgreSQL backup artifact is older than the freshness target."}
        )
    status = "blocked" if blocked_reasons else "passed"
    return {
        "status": status,
        "candidate_count": candidate_count,
        "scanned_count": scanned_count,
        "scan_truncated": truncated == "true",
        "latest": {
            "extension": extension,
            "size_bytes": size_bytes,
            "age_seconds": age_seconds,
            "max_age_seconds": max_age_seconds,
            "min_size_bytes": min_size_bytes,
            "path_echoed": False,
            "filename_echoed": False,
        },
        "blocked_reasons": blocked_reasons,
        "finding": (
            "Latest PostgreSQL backup artifact is fresh and non-empty."
            if status == "passed"
            else "PostgreSQL backup freshness could not be proven."
        ),
        "value_echoed": False,
    }


def _rag_restore_section(row: str) -> dict[str, Any]:
    (
        count,
        scanned,
        truncated,
        age,
        public,
        internal,
        public_size,
        internal_size,
        max_age,
        artifact_kind,
        archive_size,
    ) = _parts(row, 11)
    candidate_count = _int(count)
    age_seconds = _int(age, -1)
    max_age_seconds = _int(max_age)
    public_size_bytes = _int(public_size)
    internal_size_bytes = _int(internal_size)
    archive_size_bytes = _int(archive_size)
    degraded_reasons: list[dict[str, str]] = []
    if truncated == "true":
        degraded_reasons.append({"key": "scan_truncated", "finding": "RAG restore artifact scan was truncated."})
    if candidate_count <= 0:
        degraded_reasons.append({"key": "missing_rag_restore_artifact", "finding": "No RAG restore drill or vectorstore backup artifact was found."})
    if candidate_count > 0 and age_seconds > max_age_seconds:
        degraded_reasons.append({"key": "rag_restore_stale", "finding": "Latest RAG restore artifact is stale."})
    if candidate_count > 0 and artifact_kind != "vectorstore_archive" and (public != "true" or internal != "true"):
        degraded_reasons.append({"key": "missing_vectorstore", "finding": "Latest RAG restore artifact is missing a Chroma store."})
    if candidate_count > 0 and artifact_kind != "vectorstore_archive" and (public_size_bytes <= 0 or internal_size_bytes <= 0):
        degraded_reasons.append({"key": "empty_vectorstore", "finding": "Latest RAG restore artifact contains an empty Chroma store."})
    if candidate_count > 0 and artifact_kind == "vectorstore_archive" and archive_size_bytes <= 0:
        degraded_reasons.append({"key": "empty_vectorstore_archive", "finding": "Latest RAG vectorstore backup archive is empty."})
    status = "degraded" if degraded_reasons else "passed"
    return {
        "status": status,
        "candidate_count": candidate_count,
        "scanned_count": _int(scanned),
        "scan_truncated": truncated == "true",
        "latest": {
            "artifact_kind": artifact_kind or "unknown",
            "age_seconds": age_seconds,
            "max_age_seconds": max_age_seconds,
            "has_public_vectorstore": public == "true" if artifact_kind != "vectorstore_archive" else None,
            "has_internal_vectorstore": internal == "true" if artifact_kind != "vectorstore_archive" else None,
            "public_size_bytes": public_size_bytes,
            "internal_size_bytes": internal_size_bytes,
            "archive_size_bytes": archive_size_bytes,
            "path_echoed": False,
            "filename_echoed": False,
        },
        "degraded_reasons": degraded_reasons,
        "finding": (
            "Latest RAG restore or backup artifact is fresh."
            if status == "passed"
            else "RAG restore artifact evidence is incomplete."
        ),
        "value_echoed": False,
    }


def _release_backup_section(row: str) -> dict[str, Any]:
    count, latest_age = _parts(row, 2)
    candidate_count = _int(count)
    degraded_reasons = []
    if candidate_count <= 0:
        degraded_reasons.append({"key": "missing_release_backup", "finding": "No code rollback backup directory was found."})
    status = "degraded" if degraded_reasons else "passed"
    return {
        "status": status,
        "candidate_count": candidate_count,
        "latest_age_seconds": _int(latest_age, -1),
        "path_echoed": False,
        "filename_echoed": False,
        "degraded_reasons": degraded_reasons,
        "finding": (
            "At least one code rollback backup directory exists."
            if status == "passed"
            else "Code rollback backup directory evidence is missing."
        ),
    }


def _schedule_section(row: str, *, require_schedule: bool) -> dict[str, Any]:
    user_cron, system_cron, systemd_timers, cron_daemon = _parts(row, 4)
    counts = {
        "user_crontab_matches": _int(user_cron),
        "system_cron_matches": _int(system_cron),
        "systemd_timer_matches": _int(systemd_timers),
    }
    total = sum(counts.values())
    if total > 0:
        status = "passed"
        finding = "Backup-related cron or systemd timer evidence exists."
        degraded_reasons: list[dict[str, str]] = []
        if counts["systemd_timer_matches"] <= 0 and cron_daemon != "active":
            status = "degraded"
            finding = "Backup schedule exists, but cron daemon status is not active."
            degraded_reasons.append({"key": "cron_daemon_not_active", "finding": finding})
    elif require_schedule:
        status = "degraded"
        finding = "No backup-related cron or systemd timer evidence was found."
        degraded_reasons = [{"key": "missing_schedule", "finding": finding}]
    else:
        status = "not_checked"
        finding = "Backup schedule evidence was not required."
        degraded_reasons = []
    return {
        "status": status,
        **counts,
        "total_matches": total,
        "cron_daemon": cron_daemon or "unknown",
        "raw_lines_echoed": False,
        "degraded_reasons": degraded_reasons,
        "finding": finding,
    }


def build_backup_schedule_live_probe_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    backup_dir: str = "",
    max_age_hours: float = 48,
    min_size_bytes: int = 1024,
    max_scan: int = 5000,
    require_schedule: bool = True,
    timeout_seconds: float = 90,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build redacted live backup schedule and freshness evidence."""

    report: dict[str, Any] = {
        "version": BACKUP_SCHEDULE_LIVE_PROBE_VERSION,
        "status": "blocked",
        "policy": {
            "read_only": True,
            "reads_env_file": False,
            "reads_database_rows": False,
            "reads_redis_keys": False,
            "reads_logs": False,
            "reads_backup_file_contents": False,
            "reads_directory_metadata": True,
            "starts_services": False,
            "prints_secret_values": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "backup_dir_echoed": False,
            "backup_filename_echoed": False,
            "schedule_lines_echoed": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER if ssh_target else "",
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER if deploy_dir else "",
            "backup_dir": BACKUP_DIR_PLACEHOLDER if backup_dir else "",
            "backup_dir_supplied": bool(backup_dir),
        },
        "thresholds": {
            "max_age_hours": max_age_hours,
            "min_size_bytes": min_size_bytes,
            "max_scan": max_scan,
            "require_schedule": require_schedule,
        },
        "sections": {},
        "not_proven_by_this_probe": [
            "This probe checks live backup metadata only; it does not read dump contents.",
            "A fresh backup artifact does not prove a completed restore into a clean non-production environment.",
            "Schedule evidence proves cron or systemd configuration is present, not that future backups will always succeed.",
            "This probe does not prove encrypted offsite backup, PITR, retention pruning, automatic failover, or multi-AZ resilience.",
        ],
    }
    if not ssh_target or not deploy_dir:
        report["blocked_reasons"] = [
            {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
        ]
        return report

    max_age_seconds = int(max_age_hours * 3600)
    backup_dir_arg = backup_dir or "__ZHIXING_NO_BACKUP_DIR__"
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
        backup_dir_arg,
        str(max_age_seconds),
        str(min_size_bytes),
        str(max_scan),
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
            "finding": "SSH read-only backup probe timed out.",
            "value_echoed": False,
        }
        report["blocked_reasons"] = [{"key": "ssh_probe_timeout", "finding": "SSH read-only backup probe timed out."}]
        return report
    if completed.returncode != 0:
        report["sections"]["ssh"] = {
            "status": "blocked",
            "returncode": completed.returncode,
            "stderr_redacted": True,
            "value_echoed": False,
            "finding": "SSH read-only backup probe failed.",
        }
        report["blocked_reasons"] = [{"key": "ssh_probe_failed", "finding": "SSH read-only backup probe failed."}]
        return report

    parsed = _parse_probe_lines(completed.stdout)
    deploy_dir_present = _first(parsed, "deploy_dir_present") == "true"
    backup_dir_supplied = _first(parsed, "backup_dir_supplied") == "true"
    backup_dir_present_raw = _first(parsed, "backup_dir_present")
    ssh_section: dict[str, Any] = {
        "status": "passed",
        "deploy_dir_present": deploy_dir_present,
        "backup_dir_supplied": backup_dir_supplied,
        "backup_dir_present": backup_dir_present_raw == "true" if backup_dir_supplied else None,
        "path_echoed": False,
    }
    if not deploy_dir_present:
        ssh_section.update({"status": "blocked", "finding": "Deployment directory is missing."})
    elif backup_dir_supplied and backup_dir_present_raw != "true":
        ssh_section.update({"status": "blocked", "finding": "Supplied backup directory is missing."})

    sections = {
        "ssh": ssh_section,
        "postgres_backup_freshness": _postgres_backup_section(_first(parsed, "postgres_backup_scan")),
        "rag_restore_artifact": _rag_restore_section(_first(parsed, "rag_restore_scan")),
        "release_code_backup": _release_backup_section(_first(parsed, "release_backup_scan")),
        "backup_schedule": _schedule_section(_first(parsed, "schedule_scan"), require_schedule=require_schedule),
    }
    report["sections"] = sections
    blocked = []
    degraded = []
    for key, section in sections.items():
        status = section.get("status")
        if status == "blocked":
            blocked.append({"key": key, "finding": section.get("finding") or "Section did not pass."})
            for item in section.get("blocked_reasons") or []:
                blocked.append({"key": f"{key}.{item.get('key')}", "finding": item.get("finding")})
        elif status == "degraded":
            degraded.append({"key": key, "finding": section.get("finding") or "Section is degraded."})
            for item in section.get("degraded_reasons") or []:
                degraded.append({"key": f"{key}.{item.get('key')}", "finding": item.get("finding")})
    report["blocked_reasons"] = blocked
    report["degraded_reasons"] = degraded
    report["declaration_statuses"] = {
        "ZHIXING_BACKUP_FRESHNESS_LIVE_STATUS": (
            "passed" if sections["postgres_backup_freshness"]["status"] == "passed" else "blocked"
        ),
        "ZHIXING_BACKUP_SCHEDULE_LIVE_STATUS": sections["backup_schedule"]["status"],
        "ZHIXING_RAG_RESTORE_ARTIFACT_LIVE_STATUS": sections["rag_restore_artifact"]["status"],
        "ZHIXING_RELEASE_BACKUP_LIVE_STATUS": sections["release_code_backup"]["status"],
        "ZHIXING_BACKUP_LIVE_STATUS": "blocked" if blocked else ("degraded" if degraded else "passed"),
    }
    report["status"] = "blocked" if blocked else ("degraded" if degraded else "passed")
    return report


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("|", "\\|")
    return text or "-"


def build_backup_schedule_live_probe_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Backup Schedule Live Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: SSH target, deploy directory, backup directory, filenames and schedule lines are not echoed.",
        "",
        "## Sections",
        "",
        "| Section | Status | Key evidence |",
        "|---|---|---|",
    ]
    for key, section in (report.get("sections") or {}).items():
        if not isinstance(section, Mapping):
            continue
        if key == "postgres_backup_freshness":
            latest = section.get("latest") or {}
            evidence = (
                f"count={section.get('candidate_count')}, "
                f"age={latest.get('age_seconds')}, size={latest.get('size_bytes')}"
            )
        elif key == "backup_schedule":
            evidence = f"matches={section.get('total_matches')}"
        elif key == "rag_restore_artifact":
            latest = section.get("latest") or {}
            evidence = (
                f"count={section.get('candidate_count')}, "
                f"public={latest.get('has_public_vectorstore')}, "
                f"internal={latest.get('has_internal_vectorstore')}"
            )
        elif key == "release_code_backup":
            evidence = f"count={section.get('candidate_count')}"
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


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", default="", help="SSH target, e.g. user@host. Redacted from output.")
    parser.add_argument("--deploy-dir", default="", help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--backup-dir", default="", help="Optional remote backup directory. Redacted from output.")
    parser.add_argument("--max-age-hours", type=float, default=48)
    parser.add_argument("--min-size-bytes", type=int, default=1024)
    parser.add_argument("--max-scan", type=int, default=5000)
    parser.add_argument("--allow-missing-schedule", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--report-json", type=_path_arg, default=None, help="Render an existing UTF-8 report without probing.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    args = parser.parse_args(argv)

    if args.report_json is not None:
        try:
            loaded = json.loads(args.report_json.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            loaded = {
                "version": BACKUP_SCHEDULE_LIVE_PROBE_VERSION,
                "status": "blocked",
                "blocked_reasons": [
                    {"key": "report_json", "finding": "Existing report JSON could not be read."}
                ],
            }
        report = loaded if isinstance(loaded, Mapping) else {
            "version": BACKUP_SCHEDULE_LIVE_PROBE_VERSION,
            "status": "blocked",
            "blocked_reasons": [
                {"key": "report_json", "finding": "Existing report JSON must be an object."}
            ],
        }
    else:
        report = build_backup_schedule_live_probe_report(
            ssh_target=args.ssh_target,
            deploy_dir=args.deploy_dir,
            backup_dir=args.backup_dir,
            max_age_hours=args.max_age_hours,
            min_size_bytes=args.min_size_bytes,
            max_scan=args.max_scan,
            require_schedule=not args.allow_missing_schedule,
            timeout_seconds=args.timeout_seconds,
        )
    output_text = (
        build_backup_schedule_live_probe_markdown(report)
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
