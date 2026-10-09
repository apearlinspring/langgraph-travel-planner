"""Check backup/restore readiness without reading .env files or touching databases."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_RESTORE_READINESS_VERSION = "backup_restore_readiness.v1"
DEFAULT_BACKUP_DIRS = {"./backups", ".\\backups", "backups"}
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
RAG_RESTORE_KEYWORDS = ("backup", "rebuild", "recreate", "重新", "重建", "备份")


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a"}:
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


def _check_present(
    *,
    checks: list[dict[str, Any]],
    env_var: str,
    value: str,
    label: str,
) -> bool:
    if not value:
        checks.append(
            {
                "key": env_var.lower(),
                "env_var": env_var,
                "label": label,
                "status": "blocked",
                "finding": "Missing required backup/restore input.",
                "value_echoed": False,
            }
        )
        return False
    if _looks_placeholder(value):
        checks.append(
            {
                "key": env_var.lower(),
                "env_var": env_var,
                "label": label,
                "status": "blocked",
                "finding": "Backup/restore input still looks like a placeholder.",
                "value_echoed": False,
            }
        )
        return False
    checks.append(
        {
            "key": env_var.lower(),
            "env_var": env_var,
            "label": label,
            "status": "passed",
            "finding": "Declared.",
            "value_echoed": False,
        }
    )
    return True


def _check_backup_dir(value: str) -> dict[str, Any]:
    payload = {
        "key": "backup_dir",
        "env_var": "ZHIXING_BACKUP_DIR",
        "label": "Backup directory",
        "value_echoed": False,
    }
    if not value:
        return {**payload, "status": "blocked", "finding": "Missing backup directory."}
    normalized = value.replace("\\", "/").strip()
    if normalized.lower() in DEFAULT_BACKUP_DIRS or normalized.startswith("./") or normalized.startswith("../"):
        return {
            **payload,
            "status": "blocked",
            "finding": "Backup directory must not use the committed local default.",
        }
    if not _is_absolute_path_text(value):
        return {**payload, "status": "blocked", "finding": "Backup directory must be an absolute path."}
    path = Path(value)
    if _repo_relative(path):
        return {
            **payload,
            "status": "blocked",
            "finding": "Backup directory must stay outside the Git workspace.",
        }
    return {**payload, "status": "passed", "finding": "Absolute backup directory outside workspace is declared."}


def _check_retention(value: str) -> dict[str, Any]:
    payload = {
        "key": "backup_retention",
        "env_var": "ZHIXING_BACKUP_RETENTION",
        "label": "Backup retention",
        "value_echoed": False,
    }
    if not value or _looks_placeholder(value):
        return {**payload, "status": "blocked", "finding": "Backup retention policy is missing or placeholder-like."}
    if not any(char.isdigit() for char in value):
        return {**payload, "status": "blocked", "finding": "Backup retention policy must include a numeric retention window."}
    return {**payload, "status": "passed", "finding": "Backup retention policy is declared."}


def _check_rag_restore(value: str) -> dict[str, Any]:
    payload = {
        "key": "rag_restore_strategy",
        "env_var": "ZHIXING_RAG_RESTORE_STRATEGY",
        "label": "RAG restore strategy",
        "value_echoed": False,
    }
    if not value or _looks_placeholder(value):
        return {**payload, "status": "blocked", "finding": "RAG restore strategy is missing or placeholder-like."}
    lowered = value.lower()
    if not any(keyword in lowered for keyword in RAG_RESTORE_KEYWORDS):
        return {**payload, "status": "blocked", "finding": "RAG restore strategy must say whether to backup or rebuild vector stores."}
    return {**payload, "status": "passed", "finding": "RAG restore strategy is declared."}


def _filesystem_probe(path_text: str, *, check: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "writes_files": check,
        "finding": "Filesystem write probe not requested.",
    }
    if not check:
        return report
    path = Path(path_text)
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".zhixing-backup-readiness-",
            suffix=".tmp",
            dir=path,
            delete=True,
        ) as handle:
            handle.write("zhixing backup readiness probe\n")
            handle.flush()
        report.update(
            {
                "status": "passed",
                "finding": "Backup directory is writable.",
            }
        )
    except OSError as exc:
        report.update(
            {
                "status": "blocked",
                "finding": f"Backup directory write probe failed: {exc.__class__.__name__}",
            }
        )
    return report


def _tool_probe(*, check: bool) -> dict[str, Any]:
    tools = {
        "docker": shutil.which("docker") is not None,
        "pg_dump": shutil.which("pg_dump") is not None,
        "pg_restore": shutil.which("pg_restore") is not None,
    }
    if not check:
        return {
            "status": "not_checked",
            "checked": False,
            "tools": tools,
            "finding": "Tool probe not requested.",
        }
    missing = [name for name, present in tools.items() if not present]
    return {
        "status": "blocked" if missing else "passed",
        "checked": True,
        "tools": tools,
        "missing": missing,
        "finding": "Missing backup tools: " + ", ".join(missing) if missing else "Backup tools are available on PATH.",
    }


def build_backup_restore_readiness_report(
    *,
    environ: Mapping[str, str] | None = None,
    check_filesystem: bool = False,
    check_tools: bool = False,
) -> dict[str, Any]:
    """Build a redacted backup/restore readiness report."""

    env = environ if environ is not None else os.environ
    checks: list[dict[str, Any]] = []
    _check_present(
        checks=checks,
        env_var="ZHIXING_BACKUP_TARGET",
        value=_value(env, "ZHIXING_BACKUP_TARGET"),
        label="Backup target",
    )
    checks.append(_check_backup_dir(_value(env, "ZHIXING_BACKUP_DIR")))
    checks.append(_check_retention(_value(env, "ZHIXING_BACKUP_RETENTION")))
    checks.append(_check_rag_restore(_value(env, "ZHIXING_RAG_RESTORE_STRATEGY")))

    filesystem_probe = _filesystem_probe(_value(env, "ZHIXING_BACKUP_DIR"), check=check_filesystem)
    tool_probe = _tool_probe(check=check_tools)
    blocked = [item for item in checks if item["status"] == "blocked"]
    if filesystem_probe["status"] == "blocked":
        blocked.append(
            {
                "key": "filesystem_probe",
                "env_var": "ZHIXING_BACKUP_DIR",
                "label": "Backup directory filesystem probe",
                "status": "blocked",
                "finding": filesystem_probe["finding"],
                "value_echoed": False,
            }
        )
    if tool_probe["status"] == "blocked":
        blocked.append(
            {
                "key": "tool_probe",
                "env_var": "PATH",
                "label": "Backup tool probe",
                "status": "blocked",
                "finding": tool_probe["finding"],
                "value_echoed": False,
            }
        )
    status = "blocked" if blocked else "passed"
    return {
        "version": BACKUP_RESTORE_READINESS_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "writes_files_by_default": False,
            "filesystem_probe_requested": check_filesystem,
            "tool_probe_requested": check_tools,
            "does_not_echo_values": True,
        },
        "checks": checks,
        "filesystem_probe": filesystem_probe,
        "tool_probe": tool_probe,
        "blocked_reasons": blocked,
        "not_proven_by_this_check": [
            "PostgreSQL backup has actually been created.",
            "pg_restore has successfully restored a dump in a non-production environment.",
            "Redis and RAG vector stores have been backed up or rebuilt.",
            "Object storage, snapshot policies, or backup encryption are correctly configured.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# Backup / Restore Readiness",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, connects_database=false",
        "",
        "## Checks",
    ]
    for item in report.get("checks") or []:
        lines.append(f"- {item.get('env_var')}: {item.get('status')} ({item.get('finding')})")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--check-filesystem", action="store_true", help="Create and delete a probe file in ZHIXING_BACKUP_DIR.")
    parser.add_argument("--check-tools", action="store_true", help="Check docker, pg_dump, and pg_restore availability on PATH.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_backup_restore_readiness_report(
        check_filesystem=args.check_filesystem,
        check_tools=args.check_tools,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
