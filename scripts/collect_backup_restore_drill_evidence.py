"""Collect redacted backup and restore-drill evidence for M1 operations."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_backup_restore_readiness import build_backup_restore_readiness_report  # noqa: E402
from scripts.export_acceptance_evidence import redact_data, redact_text  # noqa: E402


BACKUP_RESTORE_DRILL_EVIDENCE_VERSION = "backup_restore_drill_evidence.v1"
BACKUP_PATH_PLACEHOLDER = "<backup-path>"
BACKUP_FILE_PLACEHOLDER = "<backup-file>"
BACKUP_EXTENSIONS = (".dump", ".backup", ".sql", ".sql.gz", ".tar", ".tar.gz")
CUSTOM_DUMP_EXTENSIONS = (".dump", ".backup", ".tar")
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "completed", "verified", "done"}


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().strip("'\"").lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a", "na"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _repo_relative(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return False
    return True


def _is_absolute_path_text(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    return normalized.startswith("/") or Path(value).is_absolute()


def _safe_payload(value: Any, *, backup_dir: str = "", backup_file: str = "") -> Any:
    def sanitize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): sanitize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [sanitize(value) for value in item]
        if isinstance(item, tuple):
            return [sanitize(value) for value in item]
        if isinstance(item, str):
            text = item
            if backup_file:
                text = text.replace(backup_file, BACKUP_FILE_PLACEHOLDER)
            if backup_dir:
                text = text.replace(backup_dir, BACKUP_PATH_PLACEHOLDER)
            return redact_text(text)
        return item

    return redact_data(sanitize(value))


def _resolve_backup_dir(
    *,
    environ: Mapping[str, str],
    backup_dir: str | None,
) -> tuple[str, str]:
    if backup_dir and backup_dir.strip():
        return backup_dir.strip(), "argument"
    env_value = _value(environ, "ZHIXING_BACKUP_DIR")
    if env_value:
        return env_value, "environment"
    return "", "missing"


def _backup_dir_check(path_text: str, *, require_exists: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "blocked",
        "value_echoed": False,
        "finding": "Missing backup directory.",
    }
    if not path_text:
        return report
    if _looks_placeholder(path_text):
        report["finding"] = "Backup directory still looks like a placeholder."
        return report
    normalized = path_text.replace("\\", "/").strip()
    if normalized.startswith("./") or normalized.startswith("../") or normalized.lower() in {"backups", "./backups"}:
        report["finding"] = "Backup directory must not use a committed local default."
        return report
    if not _is_absolute_path_text(path_text):
        report["finding"] = "Backup directory must be an absolute path."
        return report
    path = Path(path_text)
    if _repo_relative(path):
        report["finding"] = "Backup directory must stay outside the Git workspace."
        return report
    if require_exists and not path.exists():
        report["finding"] = "Backup directory does not exist."
        return report
    if require_exists and not path.is_dir():
        report["finding"] = "Backup path is not a directory."
        return report
    report.update({"status": "passed", "finding": "Backup directory policy passed."})
    return report


def _backup_extension(path: Path) -> str:
    name = path.name.lower()
    for extension in sorted(BACKUP_EXTENSIONS, key=len, reverse=True):
        if name.endswith(extension):
            return extension
    return path.suffix.lower()


def _is_backup_candidate(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and any(name.endswith(extension) for extension in BACKUP_EXTENSIONS)


def _find_latest_backup(path: Path, *, max_candidates: int = 5000) -> dict[str, Any]:
    candidates: list[Path] = []
    scanned_count = 0
    try:
        iterator = path.rglob("*")
        for item in iterator:
            scanned_count += 1
            if scanned_count > max_candidates:
                break
            if _is_backup_candidate(item):
                candidates.append(item)
    except OSError as exc:
        return {
            "status": "blocked",
            "finding": f"Backup directory scan failed: {exc.__class__.__name__}",
            "candidate_count": 0,
            "scanned_count": scanned_count,
        }
    if not candidates:
        return {
            "status": "blocked",
            "finding": "No PostgreSQL backup artifact was found.",
            "candidate_count": 0,
            "scanned_count": scanned_count,
        }
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    stat = latest.stat()
    age_seconds = max(0, int(datetime.now(UTC).timestamp() - stat.st_mtime))
    return {
        "status": "passed" if stat.st_size > 0 else "blocked",
        "finding": "Latest backup artifact is non-empty." if stat.st_size > 0 else "Latest backup artifact is empty.",
        "candidate_count": len(candidates),
        "scanned_count": scanned_count,
        "latest": {
            "extension": _backup_extension(latest),
            "size_bytes": int(stat.st_size),
            "age_seconds": age_seconds,
            "path_echoed": False,
            "filename_echoed": False,
        },
        "_latest_path": latest,
    }


def _run_command(
    args: Sequence[str],
    *,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )


def _pg_restore_list_probe(
    backup_path: Path | None,
    *,
    check: bool,
    timeout_seconds: float,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "command": f"pg_restore --list {BACKUP_FILE_PLACEHOLDER}",
        "path_echoed": False,
        "finding": "pg_restore --list probe not requested.",
    }
    if not check:
        return report
    if backup_path is None:
        report.update({"status": "blocked", "finding": "No latest backup artifact is available."})
        return report
    extension = _backup_extension(backup_path)
    report["extension"] = extension
    if extension not in CUSTOM_DUMP_EXTENSIONS:
        report.update(
            {
                "status": "blocked",
                "finding": "Latest artifact is not a custom/tar PostgreSQL dump that pg_restore --list can inspect.",
            }
        )
        return report
    try:
        result = command_runner(
            ["pg_restore", "--list", str(backup_path)],
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError:
        report.update({"status": "blocked", "finding": "pg_restore command is not available."})
        return report
    except subprocess.TimeoutExpired:
        report.update({"status": "blocked", "finding": "pg_restore --list timed out."})
        return report

    report["exit_code"] = int(result.returncode)
    if result.returncode == 0:
        report.update({"status": "passed", "finding": "pg_restore can read the backup catalog."})
    else:
        output = result.stderr or result.stdout or ""
        first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
        report.update(
            {
                "status": "blocked",
                "finding": "pg_restore --list returned non-zero.",
                "stderr_first_line": _safe_payload(
                    first_line,
                    backup_file=str(backup_path),
                    backup_dir=str(backup_path.parent),
                ),
            }
        )
    return report


def build_backup_artifact_probe(
    *,
    backup_dir: str,
    check_backup_dir: bool,
    check_latest_dump: bool,
    check_pg_restore_list: bool,
    timeout_seconds: float = 30,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    require_exists = bool(check_backup_dir or check_latest_dump or check_pg_restore_list)
    dir_check = _backup_dir_check(backup_dir, require_exists=require_exists)
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": bool(check_backup_dir or check_latest_dump or check_pg_restore_list),
        "value_echoed": False,
        "backup_dir_check": dir_check,
        "latest_backup": {"status": "not_checked", "checked": check_latest_dump},
        "pg_restore_list": {"status": "not_checked", "checked": check_pg_restore_list},
    }
    if not report["checked"]:
        report["finding"] = "Backup artifact probe not requested."
        return report
    if dir_check["status"] == "blocked":
        report.update({"status": "blocked", "finding": dir_check["finding"]})
        return _safe_payload(report, backup_dir=backup_dir)

    latest_path: Path | None = None
    if check_latest_dump or check_pg_restore_list:
        latest = _find_latest_backup(Path(backup_dir))
        latest_path = latest.pop("_latest_path", None)
        report["latest_backup"] = {**latest, "checked": True}
    if check_pg_restore_list:
        report["pg_restore_list"] = _pg_restore_list_probe(
            latest_path,
            check=True,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )

    statuses = [dir_check["status"]]
    if check_latest_dump or check_pg_restore_list:
        statuses.append(str(report["latest_backup"].get("status") or "unknown"))
    if check_pg_restore_list:
        statuses.append(str(report["pg_restore_list"].get("status") or "unknown"))
    if any(status in {"blocked", "failed", "unknown"} for status in statuses):
        status = "blocked"
    elif any(status in {"not_checked", "degraded"} for status in statuses):
        status = "degraded"
    else:
        status = "passed"
    report.update({"status": status, "finding": "Backup artifact probe completed."})
    return _safe_payload(report, backup_dir=backup_dir)


def _declaration_check(
    *,
    env_var: str,
    value: str,
    label: str,
    expect_ready: bool,
) -> dict[str, Any]:
    item = {
        "env_var": env_var,
        "label": label,
        "value_echoed": False,
    }
    if not value or _looks_placeholder(value):
        return {**item, "status": "blocked", "finding": "Missing or placeholder declaration."}
    if expect_ready and value.lower() not in READY_VALUES:
        return {**item, "status": "blocked", "finding": "Expected passed/ready/completed declaration."}
    return {**item, "status": "passed", "finding": "Declared."}


def build_restore_drill_declaration(
    *,
    environ: Mapping[str, str],
    require: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": require,
        "value_echoed": False,
        "checks": [],
        "finding": "Restore drill declaration not requested.",
    }
    if not require:
        return report
    checks = [
        _declaration_check(
            env_var="ZHIXING_POSTGRES_BACKUP_STATUS",
            value=_value(environ, "ZHIXING_POSTGRES_BACKUP_STATUS"),
            label="PostgreSQL backup status",
            expect_ready=True,
        ),
        _declaration_check(
            env_var="ZHIXING_POSTGRES_RESTORE_DRILL_STATUS",
            value=_value(environ, "ZHIXING_POSTGRES_RESTORE_DRILL_STATUS"),
            label="PostgreSQL restore drill status",
            expect_ready=True,
        ),
        _declaration_check(
            env_var="ZHIXING_RAG_RESTORE_DRILL_STATUS",
            value=_value(environ, "ZHIXING_RAG_RESTORE_DRILL_STATUS"),
            label="RAG restore drill status",
            expect_ready=True,
        ),
        _declaration_check(
            env_var="ZHIXING_RESTORE_DRILL_OWNER",
            value=_value(environ, "ZHIXING_RESTORE_DRILL_OWNER"),
            label="Restore drill owner",
            expect_ready=False,
        ),
        _declaration_check(
            env_var="ZHIXING_ACCEPTABLE_DATA_LOSS",
            value=_value(environ, "ZHIXING_ACCEPTABLE_DATA_LOSS"),
            label="Acceptable data loss window",
            expect_ready=False,
        ),
    ]
    blocked = [item for item in checks if item["status"] == "blocked"]
    report.update(
        {
            "status": "blocked" if blocked else "passed",
            "checks": checks,
            "blocked_reasons": blocked,
            "finding": "Restore drill declaration is incomplete." if blocked else "Restore drill declaration is complete.",
        }
    )
    return report


def _command_plan() -> list[dict[str, Any]]:
    return [
        {
            "key": "backup_readiness",
            "command": "python scripts/check_backup_restore_readiness.py --check-filesystem --check-tools --json",
            "runs_when": "before backup",
        },
        {
            "key": "postgres_dump",
            "command": "docker compose exec -T postgres pg_dump --format=custom > <backup-file>",
            "runs_when": "release backup",
        },
        {
            "key": "backup_catalog",
            "command": f"pg_restore --list {BACKUP_FILE_PLACEHOLDER}",
            "runs_when": "--check-pg-restore-list",
        },
        {
            "key": "restore_drill",
            "command": "restore <backup-file> into a non-production PostgreSQL target, then run readiness and smoke",
            "runs_when": "manual restore drill",
        },
    ]


def _overall_status(sections: Mapping[str, Mapping[str, Any]], *, any_requested: bool) -> str:
    if not any_requested:
        return "not_checked"
    statuses = [str(section.get("status") or "unknown") for section in sections.values()]
    if any(status in {"blocked", "failed", "unknown"} for status in statuses):
        return "blocked"
    if any(status in {"degraded", "not_checked"} for status in statuses):
        return "degraded"
    return "passed"


def build_backup_restore_drill_evidence_report(
    *,
    environ: Mapping[str, str] | None = None,
    backup_dir: str | None = None,
    check_backup_dir: bool = False,
    check_latest_dump: bool = False,
    check_pg_restore_list: bool = False,
    require_restore_drill_declaration: bool = False,
    include_readiness: bool = False,
    timeout_seconds: float = 30,
    command_runner: Any = _run_command,
) -> dict[str, Any]:
    """Build a redacted backup/restore drill evidence report."""

    env = environ if environ is not None else os.environ
    resolved_dir, dir_source = _resolve_backup_dir(environ=env, backup_dir=backup_dir)
    sections: dict[str, dict[str, Any]] = {}

    if include_readiness:
        readiness = build_backup_restore_readiness_report(
            environ=env,
            check_filesystem=check_backup_dir,
            check_tools=check_pg_restore_list,
        )
        sections["backup_restore_readiness"] = _safe_payload(readiness, backup_dir=resolved_dir)
    if check_backup_dir or check_latest_dump or check_pg_restore_list:
        sections["backup_artifact_probe"] = build_backup_artifact_probe(
            backup_dir=resolved_dir,
            check_backup_dir=check_backup_dir,
            check_latest_dump=check_latest_dump,
            check_pg_restore_list=check_pg_restore_list,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
    if require_restore_drill_declaration:
        sections["restore_drill_declaration"] = build_restore_drill_declaration(
            environ=env,
            require=True,
        )

    any_requested = bool(
        include_readiness
        or check_backup_dir
        or check_latest_dump
        or check_pg_restore_list
        or require_restore_drill_declaration
    )
    report = {
        "version": BACKUP_RESTORE_DRILL_EVIDENCE_VERSION,
        "status": _overall_status(sections, any_requested=any_requested),
        "policy": {
            "reads_dotenv": False,
            "connects_production_database": False,
            "does_not_echo_values": True,
            "reads_backup_file_contents": False,
            "pg_restore_catalog_probe_requested": check_pg_restore_list,
            "restore_drill_declaration_required": require_restore_drill_declaration,
        },
        "target": {
            "backup_dir_present": bool(resolved_dir),
            "backup_dir_source": dir_source,
            "backup_dir_echoed": False,
        },
        "command_plan": _command_plan(),
        "section_statuses": {
            name: str(section.get("status") or "unknown")
            for name, section in sections.items()
        },
        "sections": sections,
        "not_proven_by_this_report": [
            "Plan-only mode proves no backup or restore result.",
            "A latest dump probe proves only that a backup-shaped file exists and is non-empty.",
            "pg_restore --list proves catalog readability, not a completed restore into a clean environment.",
            "A restore drill declaration is operator evidence; keep the real dump and logs outside Git.",
            "This report does not prove Redis, RAG vector stores, object storage, encryption, or production data recovery unless those drills are separately executed and recorded.",
        ],
    }
    return _safe_payload(report, backup_dir=resolved_dir)


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else redact_text(str(value))
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_backup_restore_drill_evidence_markdown(report: Mapping[str, Any]) -> str:
    safe_report = redact_data(dict(report))
    if not isinstance(safe_report, Mapping):
        safe_report = {}
    lines = [
        "# Backup Restore Drill Evidence（备份恢复演练证据）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| Version | `{_markdown_cell(safe_report.get('version'))}` |",
        f"| Status | `{_markdown_cell(safe_report.get('status'))}` |",
        f"| Reads `.env` | `{_markdown_cell((safe_report.get('policy') or {}).get('reads_dotenv'))}` |",
        f"| Connects production DB | `{_markdown_cell((safe_report.get('policy') or {}).get('connects_production_database'))}` |",
        f"| Backup dir echoed | `{_markdown_cell((safe_report.get('target') or {}).get('backup_dir_echoed'))}` |",
        "",
        "## Section 状态",
        "",
        "| Section | Status |",
        "|---|---|",
    ]
    statuses = safe_report.get("section_statuses") or {}
    if isinstance(statuses, Mapping) and statuses:
        for section, status in sorted(statuses.items()):
            lines.append(f"| {_markdown_cell(section)} | {_markdown_cell(status)} |")
    else:
        lines.append("| - | not_checked |")

    lines.extend(["", "## 执行计划", "", "| Key | Command | Runs when |", "|---|---|---|"])
    for item in safe_report.get("command_plan") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('key'))} | "
            f"`{_markdown_cell(item.get('command'))}` | "
            f"{_markdown_cell(item.get('runs_when'))} |"
        )

    lines.extend(["", "## 边界", ""])
    for item in safe_report.get("not_proven_by_this_report") or []:
        lines.append(f"- {_markdown_cell(item)}")
    return redact_text("\n".join(lines))


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is human Markdown.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output path.")
    parser.add_argument("--backup-dir", default=None, help="Backup directory. Falls back to ZHIXING_BACKUP_DIR.")
    parser.add_argument("--include-readiness", action="store_true", help="Embed backup/restore readiness summary.")
    parser.add_argument("--check-backup-dir", action="store_true", help="Check backup directory exists and stays outside Git.")
    parser.add_argument("--check-latest-dump", action="store_true", help="Scan backup directory for a non-empty PostgreSQL backup artifact.")
    parser.add_argument("--check-pg-restore-list", action="store_true", help="Run pg_restore --list against the latest custom/tar dump.")
    parser.add_argument("--require-restore-drill-declaration", action="store_true", help="Require restore drill status declarations in environment variables.")
    parser.add_argument("--timeout-seconds", type=float, default=30, help="Timeout for pg_restore --list.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_backup_restore_drill_evidence_report(
        backup_dir=args.backup_dir,
        include_readiness=args.include_readiness,
        check_backup_dir=args.check_backup_dir,
        check_latest_dump=args.check_latest_dump,
        check_pg_restore_list=args.check_pg_restore_list,
        require_restore_drill_declaration=args.require_restore_drill_declaration,
        timeout_seconds=args.timeout_seconds,
    )
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json and not args.markdown
        else build_backup_restore_drill_evidence_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(output_text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
