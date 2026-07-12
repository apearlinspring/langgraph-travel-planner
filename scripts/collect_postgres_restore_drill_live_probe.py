"""Collect redacted live PostgreSQL restore-drill evidence over SSH.

This script restores the latest discovered PostgreSQL dump into an ephemeral
non-production container. It does not overwrite the production database, echo
backup paths, print dump contents, read row data, read `.env` files or print
credentials.
"""
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


POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION = "postgres_restore_drill_live_probe.v1"
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
DEFAULT_POSTGRES_IMAGE = "pgvector/pgvector:pg17"


REMOTE_RESTORE_DRILL_SCRIPT = r"""
set -u
DEPLOY_DIR="$1"
BACKUP_DIR="${2:-}"
POSTGRES_IMAGE="${3:-pgvector/pgvector:pg17}"
MAX_SCAN="${4:-5000}"
MIN_SIZE_BYTES="${5:-1024}"

if [ "$BACKUP_DIR" = "__ZHIXING_NO_BACKUP_DIR__" ]; then
  BACKUP_DIR=""
fi

CONTAINER="zhixing-postgres-restore-check-$(date +%s)-$$"
PASS="restore_check_$(date +%s)_$$"
CANDIDATES_FILE="/tmp/zhixing_restore_pg_candidates_$$.txt"
FILTERED_FILE="/tmp/zhixing_restore_pg_filtered_$$.txt"
CATALOG_OUT="/tmp/zhixing_restore_catalog_$$.txt"
CATALOG_ERR="/tmp/zhixing_restore_catalog_err_$$.txt"
RESTORE_ERR="/tmp/zhixing_restore_err_$$.txt"
TEMP_CONTAINER_CREATED="false"
TEMP_CONTAINER_CLEANED="false"

emit() {
  key="$1"
  shift || true
  printf '%s\t%s\n' "$key" "$*"
}

cleanup() {
  if [ "$TEMP_CONTAINER_CREATED" = "true" ]; then
    docker rm -f "$CONTAINER" >/dev/null 2>&1 && TEMP_CONTAINER_CLEANED="true" || true
  fi
  rm -f "$CANDIDATES_FILE" "$FILTERED_FILE" "$CATALOG_OUT" "$CATALOG_ERR" "$RESTORE_ERR"
}
trap cleanup EXIT

finish_blocked() {
  emit status blocked
  emit phase "$1"
  emit temp_container_cleaned "$TEMP_CONTAINER_CLEANED"
  exit 0
}

backup_roots() {
  if [ -n "$BACKUP_DIR" ]; then
    printf '%s\n' "$BACKUP_DIR"
    return 0
  fi
  printf '%s\n' /var/backups /opt "$DEPLOY_DIR"
}

: > "$CANDIDATES_FILE"
: > "$FILTERED_FILE"

emit deploy_dir_present "$([ -d "$DEPLOY_DIR" ] && printf true || printf false)"
if [ -n "$BACKUP_DIR" ]; then
  emit backup_dir_supplied true
  emit backup_dir_present "$([ -d "$BACKUP_DIR" ] && printf true || printf false)"
else
  emit backup_dir_supplied false
  emit backup_dir_present not_supplied
fi

if ! command -v docker >/dev/null 2>&1; then
  finish_blocked docker_missing
fi
if ! docker image inspect "$POSTGRES_IMAGE" >/dev/null 2>&1; then
  finish_blocked postgres_image_missing
fi

scanned=0
for root in $(backup_roots); do
  [ -d "$root" ] || continue
  while IFS='	' read -r mtime size path; do
    [ -n "$path" ] || continue
    scanned=$((scanned + 1))
    if [ "$scanned" -gt "$MAX_SCAN" ]; then
      emit scan_truncated true
      break 2
    fi
    printf '%s\t%s\t%s\n' "$mtime" "$size" "$path" >> "$CANDIDATES_FILE"
  done <<EOF_FIND
$(find "$root" -xdev -maxdepth 5 -type f \( -name 'postgres.dump' -o -name '*postgres*.dump' -o -name '*.dump' -o -name '*.backup' \) -size +"$MIN_SIZE_BYTES"c -printf '%T@\t%s\t%p\n' 2>/dev/null)
EOF_FIND
done

if [ -n "$BACKUP_DIR" ]; then
  sort -nr "$CANDIDATES_FILE" > "$FILTERED_FILE"
  emit backup_location_policy explicit_backup_dir
else
  awk -F '	' -v deploy="$DEPLOY_DIR" 'index($3, deploy) != 1 {print}' "$CANDIDATES_FILE" | sort -nr > "$FILTERED_FILE"
  emit backup_location_policy postgres_dump_only_outside_deploy
fi

CANDIDATE_COUNT="$(wc -l < "$FILTERED_FILE" | tr -d ' ')"
emit candidate_count "$CANDIDATE_COUNT"
emit scanned_count "$scanned"
if [ "$CANDIDATE_COUNT" = "0" ]; then
  finish_blocked find_postgres_dump
fi

LINE="$(head -n 1 "$FILTERED_FILE")"
TS="$(printf '%s' "$LINE" | awk -F '	' '{print $1}')"
SIZE="$(printf '%s' "$LINE" | awk -F '	' '{print $2}')"
BACKUP="$(printf '%s' "$LINE" | awk -F '	' '{print $3}')"
NOW="$(date +%s)"
MTIME="${TS%.*}"
AGE=$((NOW - MTIME))
BASE="$(basename "$BACKUP")"
EXT="${BASE##*.}"
if [ "$BASE" = "$EXT" ]; then
  EXT=""
fi

emit latest_size_bytes "$SIZE"
emit latest_age_seconds "$AGE"
emit latest_extension "$EXT"

if cat "$BACKUP" | docker run --rm -i "$POSTGRES_IMAGE" pg_restore --list >"$CATALOG_OUT" 2>"$CATALOG_ERR"; then
  emit catalog_status passed
  emit catalog_line_count "$(wc -l < "$CATALOG_OUT" | tr -d ' ')"
else
  emit catalog_status blocked
  finish_blocked pg_restore_catalog
fi

if docker run -d --rm --name "$CONTAINER" -e POSTGRES_PASSWORD="$PASS" -e POSTGRES_DB=restore_check "$POSTGRES_IMAGE" >/dev/null 2>"$RESTORE_ERR"; then
  TEMP_CONTAINER_CREATED="true"
else
  finish_blocked start_restore_container
fi

READY="false"
for _ in $(seq 1 45); do
  if docker exec "$CONTAINER" pg_isready -U postgres -d restore_check >/dev/null 2>&1; then
    READY="true"
    break
  fi
  sleep 1
done
if [ "$READY" != "true" ]; then
  finish_blocked restore_container_ready
fi

if cat "$BACKUP" | docker exec -i "$CONTAINER" pg_restore -U postgres -d restore_check --no-owner --no-acl >/dev/null 2>"$RESTORE_ERR"; then
  emit restore_status passed
else
  emit restore_status blocked
  finish_blocked pg_restore_replay
fi

TABLE_COUNT="$(docker exec "$CONTAINER" psql -U postgres -d restore_check -tAc "select count(*) from information_schema.tables where table_schema='public';" 2>"$RESTORE_ERR" | tr -dc '0-9')"
if [ -z "$TABLE_COUNT" ]; then
  TABLE_COUNT=0
fi
emit restored_table_count "$TABLE_COUNT"

docker rm -f "$CONTAINER" >/dev/null 2>&1 && TEMP_CONTAINER_CLEANED="true" || TEMP_CONTAINER_CLEANED="false"

if [ "$TABLE_COUNT" -gt 0 ]; then
  emit status passed
  emit phase complete
else
  emit status blocked
  emit phase restored_empty_schema
fi
emit temp_container_cleaned "$TEMP_CONTAINER_CLEANED"
exit 0
"""


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def build_postgres_restore_drill_live_probe_report_from_parsed(
    parsed: Mapping[str, list[str]],
    *,
    returncode: int = 0,
    stderr: str = "",
) -> dict[str, Any]:
    """Build a redacted report from remote restore-drill probe lines."""

    status = _first(parsed, "status", "blocked") if returncode == 0 else "blocked"
    phase = _first(parsed, "phase", "ssh_probe_failed" if returncode else "unknown")
    catalog_status = _first(parsed, "catalog_status", "not_checked")
    restore_status = _first(parsed, "restore_status", "not_checked")
    restored_table_count = _int(_first(parsed, "restored_table_count"), 0)
    temp_container_cleaned = _first(parsed, "temp_container_cleaned") == "true"
    blocked_reasons: list[dict[str, str]] = []

    if status == "blocked":
        blocked_reasons.append(
            {
                "key": phase or "restore_drill_blocked",
                "finding": "PostgreSQL non-production restore drill did not pass.",
            }
        )
    if catalog_status == "blocked":
        blocked_reasons.append(
            {
                "key": "pg_restore_catalog",
                "finding": "pg_restore --list could not read the selected PostgreSQL dump catalog.",
            }
        )
    if restore_status == "blocked":
        blocked_reasons.append(
            {
                "key": "pg_restore_replay",
                "finding": "The selected PostgreSQL dump could not be replayed into the temporary restore database.",
            }
        )
    if status == "passed" and restored_table_count <= 0:
        status = "blocked"
        blocked_reasons.append(
            {
                "key": "restored_empty_schema",
                "finding": "Restore completed but produced no public tables.",
            }
        )

    return {
        "version": POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION,
        "status": status,
        "returncode": returncode,
        "phase": phase,
        "policy": {
            "reads_env_file": False,
            "reads_backup_file_contents": True,
            "prints_backup_file_contents": False,
            "prints_backup_path": False,
            "prints_row_data": False,
            "prints_credentials": False,
            "starts_temporary_container": True,
            "modifies_production_database": False,
            "ssh_target_echoed": False,
            "deploy_dir_echoed": False,
            "backup_dir_echoed": False,
            "safe_to_commit": False,
        },
        "target": {
            "ssh_target": SERVER_TARGET_PLACEHOLDER,
            "deploy_dir": DEPLOY_DIR_PLACEHOLDER,
            "backup_dir": BACKUP_DIR_PLACEHOLDER if _first(parsed, "backup_dir_supplied") == "true" else "",
        },
        "scope": {
            "mode": "ephemeral_non_production_restore_container",
            "production_database_modified": False,
            "dump_content_echoed": False,
            "backup_path_echoed": False,
            "ssh_target_echoed": False,
            "row_data_echoed": False,
            "selected_artifact_policy": _first(parsed, "backup_location_policy", "postgres_dump_only_outside_deploy"),
        },
        "backup_artifact": {
            "candidate_count": _int(_first(parsed, "candidate_count"), 0),
            "scanned_count": _int(_first(parsed, "scanned_count"), 0),
            "latest_size_bytes": _int(_first(parsed, "latest_size_bytes"), 0),
            "latest_age_seconds": _int(_first(parsed, "latest_age_seconds"), 0),
            "latest_extension": _first(parsed, "latest_extension") or None,
            "location_policy": _first(parsed, "backup_location_policy"),
            "path_echoed": False,
            "filename_echoed": False,
        },
        "catalog_check": {
            "status": catalog_status,
            "catalog_line_count": _int(_first(parsed, "catalog_line_count"), 0),
        },
        "restore_check": {
            "status": restore_status if restore_status != "not_checked" else ("passed" if status == "passed" else "not_checked"),
            "restored_table_count": restored_table_count,
            "temp_container_cleaned": temp_container_cleaned,
        },
        "blocked_reasons": blocked_reasons,
        "stderr_line_count": len(str(stderr or "").splitlines()),
        "not_proven_by_this_probe": [
            "This probe restores one discovered PostgreSQL dump into a temporary non-production container only.",
            "This probe does not prove PITR, multi-AZ failover, offsite disaster recovery or retention policy enforcement.",
            "This probe does not inspect table rows, Redis state, RAG vector stores, application smoke checks or alert delivery.",
        ],
    }


def build_postgres_restore_drill_live_probe_report(
    *,
    ssh_target: str,
    deploy_dir: str,
    backup_dir: str = "",
    postgres_image: str = DEFAULT_POSTGRES_IMAGE,
    max_scan: int = 5000,
    min_size_bytes: int = 1024,
    timeout_seconds: float = 300,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Run the redacted remote restore drill and build an evidence report."""

    if not ssh_target or not deploy_dir:
        return {
            "version": POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION,
            "status": "blocked",
            "phase": "missing_target",
            "policy": {
                "reads_env_file": False,
                "reads_backup_file_contents": False,
                "prints_secret_values": False,
                "ssh_target_echoed": False,
                "deploy_dir_echoed": False,
            },
            "blocked_reasons": [
                {"key": "missing_target", "finding": "SSH target and deploy directory are required."}
            ],
        }

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
        postgres_image,
        str(max_scan),
        str(min_size_bytes),
    ]
    try:
        completed = command_runner(
            command,
            input_text=REMOTE_RESTORE_DRILL_SCRIPT,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "version": POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION,
            "status": "blocked",
            "phase": "ssh_probe_timeout",
            "policy": {
                "reads_env_file": False,
                "prints_secret_values": False,
                "ssh_target_echoed": False,
                "deploy_dir_echoed": False,
            },
            "blocked_reasons": [
                {"key": "ssh_probe_timeout", "finding": "SSH restore drill probe timed out."}
            ],
        }
    parsed = _parse_probe_lines(completed.stdout)
    report = build_postgres_restore_drill_live_probe_report_from_parsed(
        parsed,
        returncode=completed.returncode,
        stderr=completed.stderr,
    )
    if completed.returncode != 0:
        report["blocked_reasons"].append(
            {"key": "ssh_probe_failed", "finding": "SSH restore drill probe failed."}
        )
    return report


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_postgres_restore_drill_live_probe_markdown(report: Mapping[str, Any]) -> str:
    artifact = report.get("backup_artifact") if isinstance(report.get("backup_artifact"), Mapping) else {}
    catalog = report.get("catalog_check") if isinstance(report.get("catalog_check"), Mapping) else {}
    restore = report.get("restore_check") if isinstance(report.get("restore_check"), Mapping) else {}
    lines = [
        "# PostgreSQL Restore Drill Live Probe",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Phase: `{_markdown_cell(report.get('phase'))}`",
        "- Boundary: SSH target, deploy path, backup path, dump contents, credentials and row data are omitted.",
        "",
        "## Evidence",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
        (
            "| Backup artifact | "
            f"`{_markdown_cell(report.get('status'))}` | "
            f"count={_markdown_cell(artifact.get('candidate_count'))}, "
            f"size={_markdown_cell(artifact.get('latest_size_bytes'))}, "
            f"age={_markdown_cell(artifact.get('latest_age_seconds'))}, "
            f"extension={_markdown_cell(artifact.get('latest_extension'))} |"
        ),
        (
            "| pg_restore catalog | "
            f"`{_markdown_cell(catalog.get('status'))}` | "
            f"catalog_lines={_markdown_cell(catalog.get('catalog_line_count'))} |"
        ),
        (
            "| Temporary restore | "
            f"`{_markdown_cell(restore.get('status'))}` | "
            f"tables={_markdown_cell(restore.get('restored_table_count'))}, "
            f"container_cleaned={_markdown_cell(restore.get('temp_container_cleaned'))} |"
        ),
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{_markdown_cell(item.get('key'))}`: {_markdown_cell(item.get('finding'))}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_probe") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", required=True, help="SSH target. Redacted from output.")
    parser.add_argument("--deploy-dir", required=True, help="Remote deploy directory. Redacted from output.")
    parser.add_argument("--backup-dir", default="", help="Optional remote backup directory. Redacted from output.")
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE)
    parser.add_argument("--max-scan", type=int, default=5000)
    parser.add_argument("--min-size-bytes", type=int, default=1024)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    args = parser.parse_args(argv)

    report = build_postgres_restore_drill_live_probe_report(
        ssh_target=args.ssh_target,
        deploy_dir=args.deploy_dir,
        backup_dir=args.backup_dir,
        postgres_image=args.postgres_image,
        max_scan=args.max_scan,
        min_size_bytes=args.min_size_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        build_postgres_restore_drill_live_probe_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
