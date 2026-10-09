"""Run a non-destructive rollback rehearsal check on the target server."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import tarfile
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


try:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
except IndexError:
    PROJECT_ROOT = Path.cwd()

ROLLBACK_REHEARSAL_STATUS_VERSION = "rollback_rehearsal_status.v1"
REQUIRED_BACKUP_ENTRIES = (
    "app",
    "frontend",
    "docs",
    "deploy",
    "docker-compose.yml",
    "README.md",
)
FORBIDDEN_RUNTIME_ENTRIES = (
    ".env",
    ".runtime",
    ".venv",
    "data/vectorstore",
    "data/vectorstore_internal",
    "logs",
    "__pycache__",
)


def _is_absolute_path_text(value: str) -> bool:
    normalized = str(value or "").replace("\\", "/").strip()
    return normalized.startswith("/") or Path(value).is_absolute()


def _age_seconds(path: Path) -> int:
    return max(0, int(datetime.now(UTC).timestamp() - path.stat().st_mtime))


def _path_check(path_text: str, *, label: str, must_be_dir: bool) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "label": label,
        "path_echoed": False,
        "finding": f"{label} exists.",
    }
    if not path_text:
        return {**payload, "status": "blocked", "finding": f"{label} is missing."}
    if not _is_absolute_path_text(path_text):
        return {**payload, "status": "blocked", "finding": f"{label} must be an absolute path."}
    path = Path(path_text)
    if not path.exists():
        return {**payload, "status": "blocked", "finding": f"{label} does not exist."}
    if must_be_dir and not path.is_dir():
        return {**payload, "status": "blocked", "finding": f"{label} is not a directory."}
    if not must_be_dir and not path.is_file():
        return {**payload, "status": "blocked", "finding": f"{label} is not a file."}
    return payload


def _entry_exists(root: Path, entry: str) -> bool:
    return (root / entry).exists()


def _forbidden_present(root: Path) -> list[str]:
    present = []
    for entry in FORBIDDEN_RUNTIME_ENTRIES:
        if _entry_exists(root, entry):
            present.append(entry)
    return present


def _backup_snapshot_check(backup_dir: Path) -> dict[str, Any]:
    required = [
        {"entry": entry, "present": _entry_exists(backup_dir, entry)}
        for entry in REQUIRED_BACKUP_ENTRIES
    ]
    missing = [item["entry"] for item in required if not item["present"]]
    forbidden = _forbidden_present(backup_dir)
    status = "passed" if not missing and not forbidden else "blocked"
    return {
        "status": status,
        "age_seconds": _age_seconds(backup_dir),
        "required_entries": required,
        "forbidden_runtime_entries_present": forbidden,
        "path_echoed": False,
        "filename_echoed": False,
        "finding": "Backup snapshot contains required code entries and no forbidden runtime entries."
        if status == "passed"
        else "Backup snapshot is incomplete or contains forbidden runtime entries.",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tar_entry_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _archive_check(archive_path: Path, *, expected_sha256: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "passed",
        "size_bytes": archive_path.stat().st_size,
        "path_echoed": False,
        "filename_echoed": False,
    }
    digest = _sha256_file(archive_path)
    payload["sha256"] = digest
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        return {
            **payload,
            "status": "blocked",
            "finding": "Release archive SHA256 does not match the expected value.",
        }
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            names = [_tar_entry_name(member.name) for member in archive.getmembers()]
    except tarfile.TarError as exc:
        return {
            **payload,
            "status": "blocked",
            "finding": f"Release archive is not readable: {exc.__class__.__name__}.",
        }
    forbidden = [
        entry
        for entry in FORBIDDEN_RUNTIME_ENTRIES
        if any(name == entry or name.startswith(entry.rstrip("/") + "/") for name in names)
    ]
    payload["entry_count"] = len(names)
    payload["forbidden_runtime_entries_present"] = forbidden
    if forbidden:
        return {
            **payload,
            "status": "blocked",
            "finding": "Release archive contains forbidden runtime entries.",
        }
    return {
        **payload,
        "finding": "Release archive is readable and does not contain forbidden runtime entries.",
    }


def _default_http_get(url: str, timeout_seconds: float) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "zhixing-rollback-rehearsal/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - explicit ops probe.
            body = response.read(4096).decode("utf-8", errors="replace")
            return int(response.status), body
    except HTTPError as exc:
        body = exc.read(1024).decode("utf-8", errors="replace")
        return int(exc.code), body
    except (OSError, TimeoutError, URLError) as exc:
        raise RuntimeError(exc.__class__.__name__) from exc


def _health_check(
    *,
    base_url: str,
    timeout_seconds: float,
    http_get: Callable[[str, float], tuple[int, str]],
) -> dict[str, Any]:
    endpoints = []
    for name, path in (("live", "/health/live"), ("ready", "/health/ready")):
        item = {"endpoint": name, "url_echoed": False}
        try:
            status_code, body = http_get(base_url.rstrip("/") + path, timeout_seconds)
        except RuntimeError as exc:
            endpoints.append(
                {
                    **item,
                    "status": "blocked",
                    "http_status": None,
                    "finding": f"Health probe failed: {exc}",
                }
            )
            continue
        passed = 200 <= status_code < 400
        endpoints.append(
            {
                **item,
                "status": "passed" if passed else "blocked",
                "http_status": status_code,
                "body_status_present": '"status"' in body or "status" in body.lower(),
                "finding": "Endpoint responded successfully." if passed else f"Endpoint returned HTTP {status_code}.",
            }
        )
    blocked = [item for item in endpoints if item["status"] == "blocked"]
    return {
        "status": "blocked" if blocked else "passed",
        "base_url_echoed": False,
        "endpoints": endpoints,
        "finding": "Current health endpoints responded successfully."
        if not blocked
        else "One or more current health endpoints failed.",
    }


def _mock_checkout_check(
    *,
    base_url: str,
    timeout_seconds: float,
    http_get: Callable[[str, float], tuple[int, str]],
) -> dict[str, Any]:
    try:
        status_code, body = http_get(
            base_url.rstrip("/") + "/api/v1/mock-checkout/ORDER-ROLLBACKDRILL/status",
            timeout_seconds,
        )
    except RuntimeError as exc:
        return {
            "status": "blocked",
            "url_echoed": False,
            "finding": f"Mock checkout probe failed: {exc}",
        }
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    checks = {
        "http_2xx": 200 <= status_code < 400,
        "demo_only": payload.get("status") == "demo_only",
        "real_payment_false": payload.get("real_payment") is False,
        "real_booking_false": payload.get("real_booking") is False,
        "inventory_locked_false": payload.get("inventory_locked") is False,
        "fulfillment_triggered_false": payload.get("fulfillment_triggered") is False,
    }
    passed = all(checks.values())
    return {
        "status": "passed" if passed else "blocked",
        "http_status": status_code,
        "url_echoed": False,
        "checks": checks,
        "finding": "Mock checkout boundary remains demo-only."
        if passed
        else "Mock checkout boundary was not proven demo-only.",
    }


def _status_from_checks(checks: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    blockers = [
        {"check": key, **value}
        for key, value in checks.items()
        if value.get("status") == "blocked"
    ]
    return ("blocked" if blockers else "passed", blockers)


def build_rollback_rehearsal_status_report(
    *,
    deploy_dir: str,
    backup_dir: str,
    release_archive: str = "",
    expected_archive_sha256: str = "",
    base_url: str = "http://127.0.0.1:8000",
    timeout_seconds: float = 5,
    check_health: bool = False,
    check_mock_checkout: bool = False,
    http_get: Callable[[str, float], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Build a non-destructive rollback rehearsal report."""

    checks: dict[str, dict[str, Any]] = {
        "deploy_dir": _path_check(deploy_dir, label="Deploy directory", must_be_dir=True),
        "backup_dir": _path_check(backup_dir, label="Rollback backup directory", must_be_dir=True),
    }
    if checks["backup_dir"]["status"] == "passed":
        checks["backup_snapshot"] = _backup_snapshot_check(Path(backup_dir))
    if release_archive:
        checks["release_archive"] = _path_check(
            release_archive,
            label="Release archive",
            must_be_dir=False,
        )
        if checks["release_archive"]["status"] == "passed":
            checks["release_archive"] = _archive_check(
                Path(release_archive),
                expected_sha256=expected_archive_sha256,
            )
    if check_health:
        checks["current_health"] = _health_check(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            http_get=http_get or _default_http_get,
        )
    if check_mock_checkout:
        checks["mock_checkout_boundary"] = _mock_checkout_check(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            http_get=http_get or _default_http_get,
        )

    status, blockers = _status_from_checks(checks)
    return {
        "version": ROLLBACK_REHEARSAL_STATUS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "executes_rollback": False,
            "starts_services": False,
            "deletes_files": False,
            "path_echoed": False,
            "filename_echoed": False,
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_ROLLBACK_TARGET_STATUS": "passed"
            if checks.get("backup_snapshot", {}).get("status") == "passed"
            else "blocked",
            "ZHIXING_ROLLBACK_DATA_SAFETY_STATUS": "passed"
            if checks.get("backup_snapshot", {}).get("status") == "passed"
            else "blocked",
            "ZHIXING_ROLLBACK_DRILL_STATUS": "degraded",
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This is a non-destructive rollback rehearsal; it does not switch releases or restart services.",
            "Current health checks are not post-rollback health checks because no rollback was executed.",
            "A passed rehearsal proves rollback materials and data-safety boundaries, not full rollback recovery time.",
            "A real rollback window is still required before declaring ZHIXING_ROLLBACK_DRILL_STATUS as passed.",
        ],
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-dir", required=True, help="Absolute deployment directory.")
    parser.add_argument("--backup-dir", required=True, help="Absolute rollback backup directory.")
    parser.add_argument("--release-archive", default="", help="Optional release archive to validate.")
    parser.add_argument("--expected-archive-sha256", default="", help="Expected archive SHA256.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Internal base URL for optional probes.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="HTTP probe timeout.")
    parser.add_argument("--check-health", action="store_true", help="Probe current /health/live and /health/ready.")
    parser.add_argument("--check-mock-checkout", action="store_true", help="Probe demo-only mock checkout boundary.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_rollback_rehearsal_status_report(
        deploy_dir=args.deploy_dir,
        backup_dir=args.backup_dir,
        release_archive=args.release_archive,
        expected_archive_sha256=args.expected_archive_sha256,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        check_health=args.check_health,
        check_mock_checkout=args.check_mock_checkout,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print("wrote output")
    else:
        print(text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
