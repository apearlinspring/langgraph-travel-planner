"""Render evidence-backed PostgreSQL backup/restore declaration candidates.

The renderer consumes redacted backup evidence reports and produces candidate
answers for the two PostgreSQL/Redis ops declarations that require backup or
restore artifacts. It does not read `.env`, connect SSH, connect databases,
read backup file contents, write server env files or mark owners confirmed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_REDIS_BACKUP_DECLARATION_CANDIDATES_VERSION = "postgres_redis_backup_declaration_candidates.v1"
BACKUP_SCHEDULE_LIVE_PROBE_VERSION = "backup_schedule_live_probe.v1"
BACKUP_RESTORE_DRILL_EVIDENCE_VERSION = "backup_restore_drill_evidence.v1"
POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION = "postgres_restore_drill_live_probe.v1"
RESTORE_DRILL_FEASIBILITY_VERSION = "restore_drill_feasibility.v1"


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, {"check": label, "finding": f"{label} JSON path is required.", "path_echoed": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {"check": label, "finding": f"{label} JSON could not be read.", "path_echoed": False}
    if not isinstance(payload, dict):
        return None, {"check": label, "finding": f"{label} JSON must be an object.", "path_echoed": False}
    return payload, None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return str(value or "unknown").strip().lower() or "unknown"


def _backup_candidate(backup_schedule: Mapping[str, Any] | None) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not isinstance(backup_schedule, Mapping):
        blockers.append({"key": "missing_backup_schedule", "finding": "Backup schedule live probe is missing."})
    else:
        if backup_schedule.get("version") != BACKUP_SCHEDULE_LIVE_PROBE_VERSION:
            blockers.append({"key": "backup_schedule_version", "finding": "Backup schedule live probe version is not recognized."})
        declarations = _as_mapping(backup_schedule.get("declaration_statuses"))
        sections = _as_mapping(backup_schedule.get("sections"))
        postgres = _as_mapping(sections.get("postgres_backup_freshness"))
        schedule = _as_mapping(sections.get("backup_schedule"))
        if _status(backup_schedule.get("status")) == "blocked":
            blockers.append({"key": "backup_schedule_blocked", "finding": "Backup schedule live probe is blocked."})
        if _status(declarations.get("ZHIXING_BACKUP_FRESHNESS_LIVE_STATUS")) != "passed":
            blockers.append({"key": "backup_freshness_not_passed", "finding": "Fresh PostgreSQL backup evidence is not passed."})
        if _status(postgres.get("status")) != "passed":
            blockers.append({"key": "postgres_backup_section_not_passed", "finding": "PostgreSQL backup freshness section is not passed."})
        if _status(schedule.get("status")) == "degraded":
            warnings.append({"key": "backup_schedule_degraded", "finding": "Backup freshness passed, but schedule evidence is degraded."})
        elif _status(schedule.get("status")) == "blocked":
            blockers.append({"key": "backup_schedule_not_passed", "finding": "Backup schedule section is blocked."})
    status = "blocked" if blockers else ("degraded" if warnings else "candidate_ready")
    return {
        "env_var": "ZHIXING_POSTGRES_BACKUP_STATUS",
        "status": status,
        "candidate_value": "passed: PostgreSQL backup freshness live probe passed for M1"
        if status in {"candidate_ready", "degraded"}
        else "<blocked-until-fresh-postgres-backup-evidence>",
        "owner_confirmed": False,
        "evidence_ref": "backup-schedule-live-probe.json",
        "evidence_required": "Fresh non-empty PostgreSQL backup artifact and backup schedule/live probe evidence.",
        "blocked_reasons": blockers,
        "degraded_reasons": warnings,
        "value_echoed": False,
    }


def _restore_pg_restore_catalog_status(backup_restore: Mapping[str, Any] | None) -> str:
    if not isinstance(backup_restore, Mapping):
        return "missing"
    if backup_restore.get("version") == POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION:
        catalog = _as_mapping(backup_restore.get("catalog_check"))
        return _status(catalog.get("status"))
    sections = _as_mapping(backup_restore.get("sections"))
    artifact_probe = _as_mapping(sections.get("backup_artifact_probe"))
    pg_restore = _as_mapping(artifact_probe.get("pg_restore_list"))
    return _status(pg_restore.get("status"))


def _restore_declaration_status(backup_restore: Mapping[str, Any] | None) -> str:
    if not isinstance(backup_restore, Mapping):
        return "missing"
    if backup_restore.get("version") == POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION:
        restore_check = _as_mapping(backup_restore.get("restore_check"))
        return _status(restore_check.get("status"))
    sections = _as_mapping(backup_restore.get("sections"))
    declaration = _as_mapping(sections.get("restore_drill_declaration"))
    return _status(declaration.get("status"))


def _restore_evidence_ref(backup_restore: Mapping[str, Any] | None) -> str:
    if isinstance(backup_restore, Mapping) and backup_restore.get("version") == POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION:
        return "postgres-restore-drill-live-probe.json + restore-drill-feasibility.json"
    return "backup-restore-drill-evidence.json + restore-drill-feasibility.json"


def _restore_candidate(
    backup_restore: Mapping[str, Any] | None,
    feasibility: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    pg_restore_status = _restore_pg_restore_catalog_status(backup_restore)
    restore_declaration_status = _restore_declaration_status(backup_restore)
    feasibility_status = _status(feasibility.get("status")) if isinstance(feasibility, Mapping) else "missing"

    if not isinstance(backup_restore, Mapping):
        blockers.append({"key": "missing_backup_restore_evidence", "finding": "Backup/restore drill evidence report is missing."})
    else:
        if backup_restore.get("version") not in {
            BACKUP_RESTORE_DRILL_EVIDENCE_VERSION,
            POSTGRES_RESTORE_DRILL_LIVE_PROBE_VERSION,
        }:
            blockers.append({"key": "backup_restore_version", "finding": "Backup/restore evidence version is not recognized."})
        if _status(backup_restore.get("status")) == "blocked":
            blockers.append({"key": "backup_restore_evidence_blocked", "finding": "Backup/restore drill evidence report is blocked."})

    if not isinstance(feasibility, Mapping):
        warnings.append({"key": "missing_restore_feasibility", "finding": "Restore feasibility report is missing."})
    else:
        if feasibility.get("version") != RESTORE_DRILL_FEASIBILITY_VERSION:
            blockers.append({"key": "restore_feasibility_version", "finding": "Restore feasibility version is not recognized."})
        if feasibility_status == "blocked":
            blockers.append({"key": "restore_feasibility_blocked", "finding": "Restore drill feasibility is blocked."})
        elif feasibility_status == "degraded":
            warnings.append({"key": "restore_feasibility_degraded", "finding": "Restore drill feasibility is degraded."})

    if pg_restore_status != "passed":
        blockers.append({"key": "pg_restore_catalog_not_passed", "finding": "pg_restore --list/catalog evidence is not passed."})
    if restore_declaration_status != "passed":
        blockers.append({"key": "restore_declaration_not_passed", "finding": "Restore drill declaration evidence is not passed."})

    status = "blocked" if blockers else ("degraded" if warnings else "candidate_ready")
    return {
        "env_var": "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
        "status": status,
        "candidate_value": "passed: PostgreSQL restore drill/catalog evidence passed for M1"
        if status in {"candidate_ready", "degraded"}
        else "<blocked-until-pg-restore-catalog-or-restore-drill-evidence>",
        "owner_confirmed": False,
        "evidence_ref": _restore_evidence_ref(backup_restore),
        "evidence_required": "pg_restore --list/catalog evidence plus restore drill declaration, or a completed non-production restore record.",
        "source_statuses": {
            "pg_restore_catalog": pg_restore_status,
            "restore_declaration": restore_declaration_status,
            "restore_feasibility": feasibility_status,
        },
        "blocked_reasons": blockers,
        "degraded_reasons": warnings,
        "value_echoed": False,
    }


def _overall_status(candidates: list[Mapping[str, Any]], input_errors: list[Mapping[str, Any]]) -> str:
    if input_errors:
        return "blocked"
    statuses = {_status(item.get("status")) for item in candidates}
    if "blocked" in statuses:
        return "blocked"
    if "degraded" in statuses:
        return "degraded"
    if "candidate_ready" in statuses:
        return "action_required"
    return "not_checked"


def build_postgres_redis_backup_declaration_candidates(
    *,
    backup_schedule: Mapping[str, Any] | None,
    backup_restore: Mapping[str, Any] | None,
    restore_feasibility: Mapping[str, Any] | None,
    input_errors: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build candidate owner answers for PostgreSQL backup/restore declarations."""

    errors = list(input_errors or [])
    candidates = [
        _backup_candidate(backup_schedule),
        _restore_candidate(backup_restore, restore_feasibility),
    ]
    blocked = [
        {"env_var": candidate.get("env_var"), **dict(item)}
        for candidate in candidates
        for item in _as_list(candidate.get("blocked_reasons"))
        if isinstance(item, Mapping)
    ]
    for item in errors:
        blocked.append(dict(item))
    degraded = [
        {"env_var": candidate.get("env_var"), **dict(item)}
        for candidate in candidates
        for item in _as_list(candidate.get("degraded_reasons"))
        if isinstance(item, Mapping)
    ]
    return {
        "version": POSTGRES_REDIS_BACKUP_DECLARATION_CANDIDATES_VERSION,
        "status": _overall_status(candidates, errors),
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "connects_ssh": False,
            "reads_backup_file_contents": False,
            "writes_server_env": False,
            "echoes_secret_values": False,
            "safe_to_commit": False,
        },
        "candidate_count": len(candidates),
        "candidate_ready_count": sum(1 for item in candidates if item["status"] == "candidate_ready"),
        "blocked_candidate_count": sum(1 for item in candidates if item["status"] == "blocked"),
        "candidates": candidates,
        "record_patch_skeleton": {
            "declarations": [
                {
                    "env_var": item["env_var"],
                    "accepted_value": item["candidate_value"],
                    "owner_confirmed": False,
                    "evidence_ref": item["evidence_ref"],
                    "value_echoed": False,
                }
                for item in candidates
            ]
        },
        "blocked_reasons": blocked,
        "degraded_reasons": degraded,
        "not_proven_by_this_report": [
            "Candidate values are not owner-confirmed.",
            "This report does not write server env files or prove the runtime loaded declarations.",
            "A fresh backup artifact does not prove full restore unless pg_restore/catalog or non-production restore evidence passed.",
            "M1 backup/restore evidence does not prove PITR, offsite encryption, automatic failover or multi-AZ HA.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_postgres_redis_backup_declaration_candidates_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL Backup / Restore Declaration Candidates",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Candidate ready: `{_markdown_cell(report.get('candidate_ready_count'))}`",
        f"- Blocked candidates: `{_markdown_cell(report.get('blocked_candidate_count'))}`",
        "- Policy: no `.env`, no SSH, no database/Redis connection, no backup content reads, no server env writes.",
        "",
        "## Candidates",
        "",
        "| Env Var | Status | Candidate Value | Evidence Ref | Evidence Required |",
        "|---|---|---|---|---|",
    ]
    for item in _as_list(report.get("candidates")):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('env_var'))}` | "
            f"`{_markdown_cell(item.get('status'))}` | "
            f"`{_markdown_cell(item.get('candidate_value'))}` | "
            f"{_markdown_cell(item.get('evidence_ref'))} | "
            f"{_markdown_cell(item.get('evidence_required'))} |"
        )
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in _as_list(report.get("blocked_reasons")):
            if isinstance(item, Mapping):
                lines.append(
                    f"- `{_markdown_cell(item.get('env_var'))}` `{_markdown_cell(item.get('key') or item.get('check'))}`: "
                    f"{_markdown_cell(item.get('finding'))}"
                )
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in _as_list(report.get("degraded_reasons")):
            if isinstance(item, Mapping):
                lines.append(
                    f"- `{_markdown_cell(item.get('env_var'))}` `{_markdown_cell(item.get('key'))}`: "
                    f"{_markdown_cell(item.get('finding'))}"
                )
    lines.extend(["", "## Record Patch Skeleton", ""])
    for item in _as_list(_as_mapping(report.get("record_patch_skeleton")).get("declarations")):
        if not isinstance(item, Mapping):
            continue
        lines.append(f"```text\n{_markdown_cell(item.get('env_var'))}={_markdown_cell(item.get('accepted_value'))}\n```")
        lines.append("- owner_confirmed: `false`")
        lines.append(f"- evidence_ref: `{_markdown_cell(item.get('evidence_ref'))}`")
    lines.extend(["", "## Boundary", ""])
    for item in _as_list(report.get("not_proven_by_this_report")):
        lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-schedule-json", type=_path_arg, required=True)
    parser.add_argument("--backup-restore-json", type=_path_arg, required=True)
    parser.add_argument("--restore-feasibility-json", type=_path_arg, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    backup_schedule, backup_error = _read_json(args.backup_schedule_json, label="backup_schedule")
    backup_restore, restore_error = _read_json(args.backup_restore_json, label="backup_restore")
    feasibility, feasibility_error = _read_json(args.restore_feasibility_json, label="restore_feasibility")
    input_errors = [item for item in (backup_error, restore_error, feasibility_error) if item]
    report = build_postgres_redis_backup_declaration_candidates(
        backup_schedule=backup_schedule,
        backup_restore=backup_restore,
        restore_feasibility=feasibility,
        input_errors=input_errors,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.json and not args.markdown
        else build_postgres_redis_backup_declaration_candidates_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + ("\n" if not output_text.endswith("\n") else ""), encoding="utf-8")
    else:
        print(output_text, end="" if output_text.endswith("\n") else "\n")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
