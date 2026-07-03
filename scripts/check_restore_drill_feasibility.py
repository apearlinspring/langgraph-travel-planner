"""Check whether it is safe to run a PostgreSQL restore drill.

This checker consumes redacted JSON reports produced by the live backup probe
and server capacity snapshot. It does not read `.env`, connect over SSH, inspect
backup file contents, start containers, create databases or restore dumps.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from math import ceil
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESTORE_DRILL_FEASIBILITY_VERSION = "restore_drill_feasibility.v1"
SUPPORTED_PG_RESTORE_EXTENSIONS = {".dump", ".backup", ".tar"}
SQL_RESTORE_EXTENSIONS = {".sql", ".sql.gz"}


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, {
            "key": f"missing_{label}",
            "finding": f"{label} JSON path is required.",
            "path_echoed": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {
            "key": f"unreadable_{label}",
            "finding": f"{label} JSON could not be read.",
            "path_echoed": False,
        }
    if not isinstance(payload, dict):
        return None, {
            "key": f"invalid_{label}",
            "finding": f"{label} JSON must be an object.",
            "path_echoed": False,
        }
    return payload, None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(_as_number(value, default))


def _status(value: Any) -> str:
    return str(value or "").strip().lower()


def _postgres_backup_check(backup_report: Mapping[str, Any] | None) -> dict[str, Any]:
    if backup_report is None:
        return {
            "status": "blocked",
            "blocked_reasons": [{"key": "missing_backup_report", "finding": "Backup schedule report is missing."}],
            "value_echoed": False,
        }
    sections = _as_mapping(backup_report.get("sections"))
    postgres = _as_mapping(sections.get("postgres_backup_freshness"))
    latest = _as_mapping(postgres.get("latest"))
    backup_status = _status(backup_report.get("status"))
    postgres_status = _status(postgres.get("status"))
    extension = str(latest.get("extension") or "").lower()
    size_bytes = _as_int(latest.get("size_bytes"))
    age_seconds = _as_int(latest.get("age_seconds"), -1)
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []

    if backup_status == "blocked" or postgres_status != "passed":
        blocked.append({"key": "postgres_backup_not_passed", "finding": "Fresh PostgreSQL backup evidence is not passed."})
    if size_bytes <= 0:
        blocked.append({"key": "postgres_backup_empty", "finding": "Latest PostgreSQL backup size is not positive."})
    if extension not in SUPPORTED_PG_RESTORE_EXTENSIONS:
        if extension in SQL_RESTORE_EXTENSIONS:
            degraded.append(
                {
                    "key": "sql_restore_plan_required",
                    "finding": "Latest backup is SQL format; use a psql restore drill instead of pg_restore catalog checks.",
                }
            )
        else:
            blocked.append({"key": "unsupported_backup_extension", "finding": "Latest backup extension is not restore-drill ready."})

    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "latest": {
            "extension": extension or "unknown",
            "size_bytes": size_bytes,
            "size_mb": ceil(size_bytes / 1024 / 1024) if size_bytes > 0 else 0,
            "age_seconds": age_seconds,
            "path_echoed": False,
            "filename_echoed": False,
        },
        "source_statuses": {
            "backup_schedule_report": backup_status or "unknown",
            "postgres_backup_freshness": postgres_status or "unknown",
        },
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "value_echoed": False,
    }


def _disk_summary(capacity_report: Mapping[str, Any] | None) -> dict[str, Any]:
    if capacity_report is None:
        return {
            "status": "blocked",
            "blocked_reasons": [{"key": "missing_capacity_report", "finding": "Server capacity report is missing."}],
            "value_echoed": False,
        }
    sections = _as_mapping(capacity_report.get("sections"))
    host = _as_mapping(sections.get("host_capacity"))
    container = _as_mapping(sections.get("container_capacity"))
    disks = _as_mapping(host.get("disk"))
    root = _as_mapping(disks.get("root"))
    deploy = _as_mapping(disks.get("deploy"))
    root_free_mb = _as_int(root.get("free_mb"))
    deploy_free_mb = _as_int(deploy.get("free_mb"))
    free_values = [value for value in (root_free_mb, deploy_free_mb) if value > 0]
    effective_free_mb = min(free_values) if free_values else 0
    blocked: list[dict[str, str]] = []
    degraded: list[dict[str, str]] = []

    if _status(capacity_report.get("status")) == "blocked" or _status(host.get("status")) == "blocked":
        blocked.append({"key": "capacity_blocked", "finding": "Server capacity report or host capacity is blocked."})
    if _status(container.get("status")) == "blocked":
        blocked.append({"key": "container_capacity_blocked", "finding": "Container capacity is blocked."})
    if effective_free_mb <= 0:
        blocked.append({"key": "disk_free_missing", "finding": "Disk free space could not be proven."})
    for key, disk in {"root": root, "deploy": deploy}.items():
        if _status(disk.get("status")) == "blocked":
            blocked.append({"key": f"{key}_disk_blocked", "finding": "Disk usage is at or above the fail threshold."})
        elif _status(disk.get("status")) == "degraded":
            degraded.append({"key": f"{key}_disk_degraded", "finding": "Disk usage is above the warning threshold."})
    if _status(container.get("status")) == "degraded":
        degraded.append({"key": "container_capacity_degraded", "finding": "Container capacity is degraded."})

    return {
        "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
        "root_free_mb": root_free_mb,
        "root_used_percent": _as_int(root.get("used_percent"), -1),
        "deploy_free_mb": deploy_free_mb,
        "deploy_used_percent": _as_int(deploy.get("used_percent"), -1),
        "effective_free_mb": effective_free_mb,
        "source_statuses": {
            "capacity_report": _status(capacity_report.get("status")) or "unknown",
            "host_capacity": _status(host.get("status")) or "unknown",
            "container_capacity": _status(container.get("status")) or "unknown",
        },
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "value_echoed": False,
    }


def _space_check(
    *,
    backup_size_bytes: int,
    effective_free_mb: int,
    min_free_mb: int,
    free_after_drill_mb: int,
    restore_size_multiplier: float,
) -> dict[str, Any]:
    backup_size_mb = ceil(backup_size_bytes / 1024 / 1024) if backup_size_bytes > 0 else 0
    estimated_restore_workspace_mb = ceil(backup_size_mb * restore_size_multiplier)
    required_free_mb = max(min_free_mb, estimated_restore_workspace_mb + free_after_drill_mb)
    blocked: list[dict[str, str]] = []
    if effective_free_mb < required_free_mb:
        blocked.append(
            {
                "key": "insufficient_restore_drill_space",
                "finding": "Effective free disk space is below the restore drill safety threshold.",
            }
        )
    return {
        "status": "blocked" if blocked else "passed",
        "backup_size_mb": backup_size_mb,
        "estimated_restore_workspace_mb": estimated_restore_workspace_mb,
        "effective_free_mb": effective_free_mb,
        "required_free_mb": required_free_mb,
        "thresholds": {
            "min_free_mb": min_free_mb,
            "free_after_drill_mb": free_after_drill_mb,
            "restore_size_multiplier": restore_size_multiplier,
        },
        "blocked_reasons": blocked,
    }


def _overall_status(sections: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    blocked: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    for section_name, section in sections.items():
        for item in section.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                blocked.append({"section": section_name, **dict(item)})
        for item in section.get("degraded_reasons") or []:
            if isinstance(item, Mapping):
                degraded.append({"section": section_name, **dict(item)})
    return ("blocked" if blocked else ("degraded" if degraded else "passed"), blocked, degraded)


def build_restore_drill_feasibility_report(
    *,
    backup_schedule_report: Mapping[str, Any] | None,
    capacity_report: Mapping[str, Any] | None,
    min_free_mb: int = 4096,
    free_after_drill_mb: int = 2048,
    restore_size_multiplier: float = 3.0,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted restore-drill feasibility report."""

    now = generated_at or datetime.now(UTC)
    backup = _postgres_backup_check(backup_schedule_report)
    disk = _disk_summary(capacity_report)
    latest = _as_mapping(backup.get("latest"))
    space = _space_check(
        backup_size_bytes=_as_int(latest.get("size_bytes")),
        effective_free_mb=_as_int(disk.get("effective_free_mb")),
        min_free_mb=min_free_mb,
        free_after_drill_mb=free_after_drill_mb,
        restore_size_multiplier=restore_size_multiplier,
    )
    sections = {
        "postgres_backup": backup,
        "disk_capacity": disk,
        "restore_workspace_space": space,
    }
    status, blocked, degraded = _overall_status(sections)
    return {
        "version": RESTORE_DRILL_FEASIBILITY_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_ssh": False,
            "connects_database": False,
            "connects_redis": False,
            "reads_backup_file_contents": False,
            "starts_containers": False,
            "creates_databases": False,
            "deletes_files": False,
            "prints_secret_values": False,
            "path_echoed": False,
        },
        "sections": sections,
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "declaration_statuses": {
            "ZHIXING_RESTORE_DRILL_FEASIBILITY_STATUS": status,
            "ZHIXING_RESTORE_DRILL_DISK_SPACE_STATUS": space["status"],
            "ZHIXING_RESTORE_DRILL_BACKUP_INPUT_STATUS": backup["status"],
        },
        "recommended_next_actions": [
            "Free disk space or attach an external restore workspace before running a live restore drill."
            if status == "blocked"
            else "Run a restore drill in a non-production target and then validate the operator record.",
            "Keep dump paths, database names, logs and screenshots in the private evidence store only.",
            "After the drill, validate the record with scripts/check_postgres_redis_recovery_record.py.",
        ],
        "not_proven_by_this_report": [
            "This report proves feasibility only; it does not restore PostgreSQL.",
            "It does not prove Redis recovery, RAG rebuild quality, PITR, multi-AZ failover or offsite backup encryption.",
            "A passed feasibility report must still be followed by a non-production restore drill and smoke checks.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_restore_drill_feasibility_markdown(report: Mapping[str, Any]) -> str:
    sections = _as_mapping(report.get("sections"))
    backup = _as_mapping(sections.get("postgres_backup"))
    disk = _as_mapping(sections.get("disk_capacity"))
    space = _as_mapping(sections.get("restore_workspace_space"))
    latest = _as_mapping(backup.get("latest"))
    lines = [
        "# Restore Drill Feasibility Evidence",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Version: `{_markdown_cell(report.get('version'))}`",
        "- Values are redacted: no server target, deploy path, backup path or filename is echoed.",
        "",
        "## Summary",
        "",
        "| Check | Status | Evidence |",
        "|---|---|---|",
        f"| PostgreSQL backup | `{_markdown_cell(backup.get('status'))}` | ext={_markdown_cell(latest.get('extension'))}, size_mb={_markdown_cell(latest.get('size_mb'))}, age_seconds={_markdown_cell(latest.get('age_seconds'))} |",
        f"| Disk capacity | `{_markdown_cell(disk.get('status'))}` | free_mb={_markdown_cell(disk.get('effective_free_mb'))}, root_used={_markdown_cell(disk.get('root_used_percent'))}%, deploy_used={_markdown_cell(disk.get('deploy_used_percent'))}% |",
        f"| Restore workspace | `{_markdown_cell(space.get('status'))}` | required_free_mb={_markdown_cell(space.get('required_free_mb'))}, effective_free_mb={_markdown_cell(space.get('effective_free_mb'))} |",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('section')}.{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Next Actions", ""])
    for item in report.get("recommended_next_actions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_report") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-schedule-json", type=_path_arg, default=None)
    parser.add_argument("--capacity-json", type=_path_arg, default=None)
    parser.add_argument("--min-free-mb", type=int, default=4096)
    parser.add_argument("--free-after-drill-mb", type=int, default=2048)
    parser.add_argument("--restore-size-multiplier", type=float, default=3.0)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    backup_report, backup_error = _read_json(args.backup_schedule_json, label="backup_schedule")
    capacity_report, capacity_error = _read_json(args.capacity_json, label="capacity")
    report = build_restore_drill_feasibility_report(
        backup_schedule_report=backup_report,
        capacity_report=capacity_report,
        min_free_mb=args.min_free_mb,
        free_after_drill_mb=args.free_after_drill_mb,
        restore_size_multiplier=args.restore_size_multiplier,
    )
    read_errors = [item for item in (backup_error, capacity_error) if item]
    if read_errors:
        report["status"] = "blocked"
        report["blocked_reasons"] = [{"section": "input", **item} for item in read_errors] + list(
            report.get("blocked_reasons") or []
        )
        report["declaration_statuses"]["ZHIXING_RESTORE_DRILL_FEASIBILITY_STATUS"] = "blocked"
    output_text = (
        build_restore_drill_feasibility_markdown(report)
        if args.markdown and not args.json
        else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
