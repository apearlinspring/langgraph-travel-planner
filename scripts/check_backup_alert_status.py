"""Check M1 backup alert status without reading backup contents."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _discover_project_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name == "scripts" and len(script_path.parents) > 1:
        return script_path.parents[1]
    return Path.cwd().resolve()


PROJECT_ROOT = _discover_project_root()
BACKUP_ALERT_STATUS_VERSION = "backup_alert_status.v1"
BACKUP_EXTENSIONS = (".dump", ".backup", ".sql", ".sql.gz")


def _is_absolute_path_text(value: str) -> bool:
    normalized = value.replace("\\", "/").strip()
    return normalized.startswith("/") or Path(value).is_absolute()


def _repo_relative(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return False
    return True


def _backup_extension(path: Path) -> str:
    name = path.name.lower()
    for extension in sorted(BACKUP_EXTENSIONS, key=len, reverse=True):
        if name.endswith(extension):
            return extension
    return path.suffix.lower()


def _is_backup_file(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and any(name.endswith(extension) for extension in BACKUP_EXTENSIONS)


def _age_seconds(path: Path) -> int:
    return max(0, int(datetime.now(UTC).timestamp() - path.stat().st_mtime))


def _backup_dir_check(path_text: str) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "path_echoed": False,
        "finding": "Backup directory exists and is outside the Git workspace.",
    }
    if not path_text:
        return {**payload, "status": "blocked", "finding": "Missing backup directory."}
    if not _is_absolute_path_text(path_text):
        return {**payload, "status": "blocked", "finding": "Backup directory must be absolute."}
    path = Path(path_text)
    if _repo_relative(path):
        return {**payload, "status": "blocked", "finding": "Backup directory must stay outside Git workspace."}
    if not path.exists():
        return {**payload, "status": "blocked", "finding": "Backup directory does not exist."}
    if not path.is_dir():
        return {**payload, "status": "blocked", "finding": "Backup path is not a directory."}
    return payload


def _iter_files(root: Path, *, max_scan: int) -> tuple[list[Path], int, bool]:
    files: list[Path] = []
    scanned = 0
    truncated = False
    for item in root.rglob("*"):
        scanned += 1
        if scanned > max_scan:
            truncated = True
            break
        if item.is_file():
            files.append(item)
    return files, scanned, truncated


def _postgres_backup_check(
    backup_dir: Path,
    *,
    max_age_hours: float,
    min_size_bytes: int,
    max_scan: int,
) -> dict[str, Any]:
    files, scanned, truncated = _iter_files(backup_dir, max_scan=max_scan)
    candidates = [path for path in files if _is_backup_file(path)]
    payload: dict[str, Any] = {
        "status": "passed",
        "candidate_count": len(candidates),
        "scanned_count": scanned,
        "scan_truncated": truncated,
        "path_echoed": False,
        "filename_echoed": False,
    }
    if not candidates:
        return {**payload, "status": "blocked", "finding": "No PostgreSQL backup artifact found."}
    if truncated:
        return {
            **payload,
            "status": "blocked",
            "finding": "Backup scan reached the maximum path limit before proving freshness.",
        }
    latest = max(candidates, key=lambda item: item.stat().st_mtime)
    stat = latest.stat()
    age = _age_seconds(latest)
    max_age_seconds = int(max_age_hours * 3600)
    latest_payload = {
        "extension": _backup_extension(latest),
        "size_bytes": int(stat.st_size),
        "age_seconds": age,
        "max_age_seconds": max_age_seconds,
        "path_echoed": False,
        "filename_echoed": False,
    }
    if stat.st_size < min_size_bytes:
        return {
            **payload,
            "status": "blocked",
            "latest": latest_payload,
            "finding": "Latest PostgreSQL backup artifact is smaller than the minimum size threshold.",
        }
    if age > max_age_seconds:
        return {
            **payload,
            "status": "blocked",
            "latest": latest_payload,
            "finding": "Latest PostgreSQL backup artifact is older than the freshness threshold.",
        }
    return {
        **payload,
        "latest": latest_payload,
        "finding": "Latest PostgreSQL backup artifact is fresh and non-empty.",
    }


def _rag_restore_artifact_check(
    backup_dir: Path,
    *,
    max_age_hours: float,
) -> dict[str, Any]:
    candidates = sorted(
        [item for item in backup_dir.glob("rag-restore-drill-*") if item.is_dir()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    payload: dict[str, Any] = {
        "status": "passed",
        "candidate_count": len(candidates),
        "path_echoed": False,
        "filename_echoed": False,
    }
    if not candidates:
        return {**payload, "status": "blocked", "finding": "No RAG restore drill artifact found."}
    latest = candidates[0]
    age = _age_seconds(latest)
    max_age_seconds = int(max_age_hours * 3600)
    public_sqlite = latest / "vectorstore" / "chroma.sqlite3"
    internal_sqlite = latest / "vectorstore_internal" / "chroma.sqlite3"
    latest_payload = {
        "age_seconds": age,
        "max_age_seconds": max_age_seconds,
        "has_public_vectorstore": public_sqlite.is_file(),
        "has_internal_vectorstore": internal_sqlite.is_file(),
        "public_size_bytes": public_sqlite.stat().st_size if public_sqlite.is_file() else 0,
        "internal_size_bytes": internal_sqlite.stat().st_size if internal_sqlite.is_file() else 0,
        "path_echoed": False,
        "filename_echoed": False,
    }
    if age > max_age_seconds:
        return {
            **payload,
            "status": "blocked",
            "latest": latest_payload,
            "finding": "Latest RAG restore drill artifact is older than the freshness threshold.",
        }
    if not latest_payload["has_public_vectorstore"] or not latest_payload["has_internal_vectorstore"]:
        return {
            **payload,
            "status": "blocked",
            "latest": latest_payload,
            "finding": "Latest RAG restore drill artifact is missing one or more Chroma stores.",
        }
    if latest_payload["public_size_bytes"] <= 0 or latest_payload["internal_size_bytes"] <= 0:
        return {
            **payload,
            "status": "blocked",
            "latest": latest_payload,
            "finding": "Latest RAG restore drill artifact contains an empty Chroma store.",
        }
    return {
        **payload,
        "latest": latest_payload,
        "finding": "Latest RAG restore drill artifact is fresh and contains both Chroma stores.",
    }


def _status_from_checks(checks: dict[str, dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    blockers = [
        {"check": key, **value}
        for key, value in checks.items()
        if value.get("status") == "blocked"
    ]
    return ("blocked" if blockers else "passed", blockers)


def build_backup_alert_status_report(
    *,
    backup_dir: str,
    max_age_hours: float = 48,
    min_size_bytes: int = 1024,
    max_scan: int = 10000,
    require_rag_restore_artifact: bool = False,
) -> dict[str, Any]:
    """Build a redacted backup alert status report."""

    dir_check = _backup_dir_check(backup_dir)
    checks: dict[str, dict[str, Any]] = {"backup_dir": dir_check}
    if dir_check["status"] == "passed":
        root = Path(backup_dir)
        checks["postgres_backup"] = _postgres_backup_check(
            root,
            max_age_hours=max_age_hours,
            min_size_bytes=min_size_bytes,
            max_scan=max_scan,
        )
        if require_rag_restore_artifact:
            checks["rag_restore_artifact"] = _rag_restore_artifact_check(
                root,
                max_age_hours=max_age_hours,
            )
    status, blockers = _status_from_checks(checks)
    return {
        "version": BACKUP_ALERT_STATUS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "reads_backup_file_contents": False,
            "path_echoed": False,
            "filename_echoed": False,
        },
        "thresholds": {
            "max_age_hours": max_age_hours,
            "min_size_bytes": min_size_bytes,
            "max_scan": max_scan,
            "require_rag_restore_artifact": require_rag_restore_artifact,
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_BACKUP_ALERT_STATUS": "passed" if status == "passed" else "blocked"
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This checks backup freshness and artifact shape only; it does not read backup contents.",
            "A passed report does not prove encrypted offsite backup, retention enforcement, or full restore.",
            "PostgreSQL and RAG restore drills still need their dedicated evidence records.",
        ],
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True, help="Absolute backup directory.")
    parser.add_argument("--max-age-hours", type=float, default=48, help="Maximum age for latest artifacts.")
    parser.add_argument("--min-size-bytes", type=int, default=1024, help="Minimum latest PostgreSQL artifact size.")
    parser.add_argument("--max-scan", type=int, default=10000, help="Maximum paths to scan under backup dir.")
    parser.add_argument("--require-rag-restore-artifact", action="store_true", help="Require latest RAG drill artifact.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_backup_alert_status_report(
        backup_dir=args.backup_dir,
        max_age_hours=args.max_age_hours,
        min_size_bytes=args.min_size_bytes,
        max_scan=args.max_scan,
        require_rag_restore_artifact=args.require_rag_restore_artifact,
    )
    output_text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print("wrote output")
    else:
        print(output_text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
