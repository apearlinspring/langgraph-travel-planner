"""Render a private PostgreSQL/Redis operations env patch.

The renderer turns a validated declaration record into reviewable server env
lines. It does not read `.env`, connect to PostgreSQL, connect to Redis,
connect SSH, or write a server env file. Blocked declaration records do not
produce writable env lines.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_REDIS_OPS_ENV_PATCH_VERSION = "postgres_redis_ops_env_patch.v1"
POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION = "postgres_redis_ops_declaration_record.v1"

SAFE_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,100}$")
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
)
URL_PATTERN = re.compile(r"https?://[^\s`'\"<>()\[\]{}|]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} JSON could not be read or parsed.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object.")
    return payload


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _secret_like(value: Any) -> bool:
    text = str(value or "")
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _unsafe_text(value: Any) -> bool:
    text = str(value or "")
    return _secret_like(text) or URL_PATTERN.search(text) is not None or IPV4_PATTERN.search(text) is not None


def _quote_env_value(value: Any) -> str:
    text = str(value or "")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
    return f'"{escaped}"'


def _record_declarations(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    declarations = []
    seen: set[str] = set()
    for item in _as_list(record.get("declarations")):
        if not isinstance(item, Mapping):
            continue
        env_var = str(item.get("env_var") or "").strip()
        if not SAFE_ENV_NAME_PATTERN.fullmatch(env_var) or env_var in seen:
            continue
        seen.add(env_var)
        declarations.append(item)
    return declarations


def _report_ready_status(record_report: Mapping[str, Any]) -> str:
    statuses = _as_mapping(record_report.get("declaration_statuses"))
    return str(statuses.get("ZHIXING_POSTGRES_REDIS_DECLARATION_READY_TO_WRITE_STATUS") or "unknown")


def build_postgres_redis_ops_env_patch_report(
    *,
    record: Mapping[str, Any],
    record_report: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a private env patch report from a validated declaration record."""

    blockers = []
    degraded_reasons = []
    report_status = str(record_report.get("status") or "unknown")
    ready_status = _report_ready_status(record_report)
    if record_report.get("version") != POSTGRES_REDIS_OPS_DECLARATION_RECORD_VERSION:
        blockers.append({"check": "record_report", "finding": "Declaration record report version is not recognized."})
    if report_status == "blocked" or ready_status != "passed":
        blockers.append({"check": "record_report", "finding": "Declaration record is not ready to write."})
    if report_status == "degraded":
        degraded_reasons.extend(_as_list(record_report.get("degraded_reasons")))

    env_entries = []
    for item in _record_declarations(record):
        env_var = str(item.get("env_var") or "").strip()
        accepted_value = str(item.get("accepted_value") or "").strip()
        if item.get("owner_confirmed") is not True:
            blockers.append({"check": "record", "env_var": env_var, "finding": "Declaration is not owner-confirmed."})
            continue
        if _unsafe_text(accepted_value):
            blockers.append({"check": "record", "env_var": env_var, "finding": "Declaration value contains URL/IP/secret-looking text."})
            continue
        env_entries.append(
            {
                "env_var": env_var,
                "env_file_line": f"{env_var}={_quote_env_value(accepted_value)}",
                "source_bucket": item.get("execution_bucket"),
                "value_echoed": False,
            }
        )

    status = "blocked" if blockers else ("degraded" if report_status == "degraded" else "passed")
    if status == "blocked":
        env_entries = []

    now = generated_at or datetime.now(UTC)
    return {
        "version": POSTGRES_REDIS_OPS_ENV_PATCH_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "connects_database": False,
            "connects_redis": False,
            "connects_ssh": False,
            "writes_server_env": False,
            "echoes_secret_values": False,
            "safe_to_commit": False,
        },
        "source_status": {
            "declaration_record_report": report_status,
            "ready_to_write": ready_status,
        },
        "env_line_count": len(env_entries),
        "env_entries": env_entries,
        "blocked_reasons": blockers,
        "degraded_reasons": degraded_reasons,
        "operator_steps_after_writing": [
            "Back up the server shared env file or secret-manager version before editing.",
            "Write only the reviewed non-secret declarations; do not paste raw .env contents into Git or chat.",
            "Rerun docker compose exec -T backend python scripts/check_postgres_redis_ops_status.py --json.",
            "Regenerate postgres-redis-ops-summary and M1 go/no-go after the target runtime sees these declarations.",
        ],
        "not_proven_by_this_report": [
            "The env lines have not been written to the server by this renderer.",
            "This renderer does not prove the target runtime has loaded the values.",
            "This renderer does not execute backup, restore drill, SSH, database, Redis, or M1 go/no-go checks.",
            "Single-node Compose declarations remain degraded for full production HA.",
        ],
    }


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_postgres_redis_ops_env_patch_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL / Redis Ops Env Patch",
        "",
        f"- Status: `{_markdown_cell(report.get('status'))}`",
        f"- Env lines: `{_markdown_cell(report.get('env_line_count'))}`",
        "- Policy: no `.env` read, no SSH, no database/Redis connection, no server env writes.",
        "",
    ]
    if report.get("status") == "blocked":
        lines.extend(["## Blocked Reasons", ""])
        for item in _as_list(report.get("blocked_reasons")):
            if isinstance(item, Mapping):
                lines.append(f"- {_markdown_cell(item.get('finding'))}")
        lines.extend(["", "No writable env lines are rendered while status is blocked.", ""])
    else:
        lines.extend(["## Env File Lines", ""])
        for item in _as_list(report.get("env_entries")):
            if not isinstance(item, Mapping):
                continue
            lines.append(f"```text\n{_markdown_cell(item.get('env_file_line'))}\n```")
        lines.extend(["", "## Operator Steps After Writing", ""])
        for item in _as_list(report.get("operator_steps_after_writing")):
            lines.append(f"- {_markdown_cell(item)}")
        lines.extend(["", "## Boundary", ""])
        for item in _as_list(report.get("not_proven_by_this_report")):
            lines.append(f"- {_markdown_cell(item)}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, required=True, help="Private accepted declaration record JSON.")
    parser.add_argument("--record-report-json", type=_path_arg, required=True, help="Validation report for the accepted declaration record.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        record = _read_json(args.record_json, label="record")
        record_report = _read_json(args.record_report_json, label="record_report")
        report = build_postgres_redis_ops_env_patch_report(
            record=record,
            record_report=record_report,
        )
    except ValueError as exc:
        report = {
            "version": POSTGRES_REDIS_OPS_ENV_PATCH_VERSION,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "connects_database": False,
                "connects_redis": False,
                "connects_ssh": False,
                "writes_server_env": False,
            },
            "blocked_reasons": [{"check": "input", "finding": str(exc)}],
        }
    output_text = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.json and not args.markdown
        else build_postgres_redis_ops_env_patch_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + ("\n" if not output_text.endswith("\n") else ""), encoding="utf-8")
    else:
        print(output_text, end="" if output_text.endswith("\n") else "\n")
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
