"""Collect redacted tool failure monitoring evidence from tool audit events."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.observability import (  # noqa: E402
    TOOL_FAILURE_SEMANTIC_STATUSES,
    TOOL_FALLBACK_SEMANTIC_STATUSES,
    resolve_tool_audit_semantic_status,
)


TOOL_FAILURE_MONITOR_STATUS_VERSION = "tool_failure_monitor_status.v1"
RAW_HARD_FAILURE_STATUSES = {"failed", "failure", "timeout", "error"}
REQUIRED_DB_ENV = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)\b"
        r"\s*[:=]\s*[^&\s,;]+"
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
)


def _redact_text(value: str) -> str:
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:120]


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _db_env_check(environ: Mapping[str, str]) -> dict[str, Any]:
    checks = []
    missing = []
    for key in REQUIRED_DB_ENV:
        present = bool(_value(environ, key))
        checks.append({"env_var": key, "present": present, "value_echoed": False})
        if not present:
            missing.append(key)
    status = "passed" if not missing else "blocked"
    return {
        "status": status,
        "checks": checks,
        "blocked_reasons": [
            {
                "env_var": key,
                "value_echoed": False,
                "finding": "Missing database connection environment variable.",
            }
            for key in missing
        ],
        "finding": "Database connection environment variables are present."
        if status == "passed"
        else "Database connection environment variables are incomplete.",
    }


def _connect_kwargs(environ: Mapping[str, str]) -> dict[str, Any]:
    return {
        "host": _value(environ, "POSTGRES_HOST"),
        "port": int(_value(environ, "POSTGRES_PORT") or "5432"),
        "database": _value(environ, "POSTGRES_DB"),
        "user": _value(environ, "POSTGRES_USER"),
        "password": _value(environ, "POSTGRES_PASSWORD"),
    }


async def _query_tool_audit_rows(
    *,
    environ: Mapping[str, str],
    lookback_hours: float,
    max_rows: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    import asyncpg

    since = datetime.now(UTC) - timedelta(hours=lookback_hours)
    conn = await asyncio.wait_for(
        asyncpg.connect(**_connect_kwargs(environ)),
        timeout=timeout_seconds,
    )
    try:
        rows = await asyncio.wait_for(
            conn.fetch(
                """
                SELECT name, status, error_type, evidence_type, elapsed_seconds, started_at
                FROM tool_audit_event
                WHERE started_at >= $1
                ORDER BY started_at DESC
                LIMIT $2
                """,
                since,
                max_rows,
            ),
            timeout=timeout_seconds,
        )
    finally:
        await conn.close()
    return [dict(row) for row in rows]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = max(1, int((percentile / 100.0) * len(ordered) + 0.999999))
    return round(ordered[min(rank, len(ordered)) - 1], 3)


def _counter_payload(counter: Counter[str], *, top_n: int) -> list[dict[str, Any]]:
    return [
        {"key": _redact_text(key), "count": int(count)}
        for key, count in counter.most_common(top_n)
    ]


def _semantic_status(row: Mapping[str, Any]) -> str:
    """Normalize persisted raw audit fields with the runtime observability contract."""

    return resolve_tool_audit_semantic_status(
        str(row.get("status") or ""),
        str(row.get("error_type")) if row.get("error_type") is not None else None,
        str(row.get("semantic_status"))
        if row.get("semantic_status") is not None
        else None,
    )


def _is_hard_failure(semantic_status: str) -> bool:
    return semantic_status in TOOL_FAILURE_SEMANTIC_STATUSES


def _summarize_tool_audit_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    top_n: int,
) -> dict[str, Any]:
    total = len(rows)
    classified = [(row, _semantic_status(row)) for row in rows]
    failures = [
        row for row, semantic in classified if _is_hard_failure(semantic)
    ]
    fallbacks = [
        row
        for row, semantic in classified
        if semantic in TOOL_FALLBACK_SEMANTIC_STATUSES
    ]
    degraded = [row for row, semantic in classified if semantic != "success"]
    success_count = sum(
        1
        for _, semantic in classified
        if semantic == "success" and not _is_hard_failure(semantic)
    )
    latencies = [
        float(row.get("elapsed_seconds") or 0.0)
        for row in rows
        if isinstance(row.get("elapsed_seconds"), int | float)
    ]
    status_counts: Counter[str] = Counter(
        str(row.get("status") or "unknown").strip().lower() or "unknown"
        for row in rows
    )
    semantic_status_counts: Counter[str] = Counter(
        semantic or "needs_verification" for _, semantic in classified
    )
    tool_counts: Counter[str] = Counter(
        str(row.get("name") or "unknown_tool").strip() or "unknown_tool"
        for row in rows
    )
    failure_tool_counts: Counter[str] = Counter(
        str(row.get("name") or "unknown_tool").strip() or "unknown_tool"
        for row in failures
    )
    failure_error_counts: Counter[str] = Counter(
        _redact_text(
            str(row.get("error_type") or "unknown_error").strip() or "unknown_error"
        )
        for row in failures
    )
    failure_rate = round(len(failures) / total, 4) if total else 0.0
    return {
        "sample_count": total,
        "failure_count": len(failures),
        "failure_rate": failure_rate,
        "hard_failure_count": len(failures),
        "hard_failure_rate": failure_rate,
        "fallback_count": len(fallbacks),
        "fallback_rate": round(len(fallbacks) / total, 4) if total else 0.0,
        "degraded_count": len(degraded),
        "degraded_rate": round(len(degraded) / total, 4) if total else 0.0,
        "success_count": success_count,
        "metric_semantics": {
            "failure": "hard_failure",
            "hard_failure_raw_statuses": sorted(RAW_HARD_FAILURE_STATUSES),
            "hard_failure_semantic_statuses": sorted(TOOL_FAILURE_SEMANTIC_STATUSES),
            "fallback_semantic_statuses": sorted(TOOL_FALLBACK_SEMANTIC_STATUSES),
            "classification_precedence": "semantic_status_then_error_type_then_raw_status",
        },
        "status_counts": _counter_payload(status_counts, top_n=top_n),
        "semantic_status_counts": _counter_payload(semantic_status_counts, top_n=top_n),
        "top_tools": _counter_payload(tool_counts, top_n=top_n),
        "top_failure_tools": _counter_payload(failure_tool_counts, top_n=top_n),
        "top_failure_error_types": _counter_payload(failure_error_counts, top_n=top_n),
        "elapsed_seconds": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": round(max(latencies), 3) if latencies else None,
        },
    }


def _status_from_summary(
    summary: Mapping[str, Any],
    *,
    min_sample_count: int,
    warn_failure_rate: float,
    max_failure_rate: float,
    allow_empty_sample: bool,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    sample_count = int(summary.get("sample_count") or 0)
    failure_rate = float(
        summary.get("hard_failure_rate", summary.get("failure_rate")) or 0.0
    )
    blockers: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []

    if sample_count == 0:
        item = {
            "metric": "sample_count",
            "value": 0,
            "threshold": min_sample_count,
            "finding": "No tool audit events were found in the lookback window.",
        }
        if allow_empty_sample:
            degraded.append(item)
        else:
            blockers.append(item)
    elif sample_count < min_sample_count:
        degraded.append(
            {
                "metric": "sample_count",
                "value": sample_count,
                "threshold": min_sample_count,
                "finding": "Tool audit sample is smaller than the configured minimum.",
            }
        )

    if sample_count and failure_rate > max_failure_rate:
        blockers.append(
            {
                "metric": "failure_rate",
                "value": failure_rate,
                "threshold": max_failure_rate,
                "finding": "Hard tool failure rate exceeded the blocking threshold.",
            }
        )
    elif sample_count and failure_rate > warn_failure_rate:
        degraded.append(
            {
                "metric": "failure_rate",
                "value": failure_rate,
                "threshold": warn_failure_rate,
                "finding": "Hard tool failure rate exceeded the warning threshold.",
            }
        )

    if blockers:
        return "blocked", blockers, degraded
    if degraded and not (allow_empty_sample and sample_count == 0 and len(degraded) == 1):
        return "degraded", blockers, degraded
    return "passed", blockers, degraded


def _finite_float(value: Any, *, field_name: str, positive: bool = False) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise ValueError(f"{field_name} must be a {qualifier} number")
    return number


def _validate_monitor_thresholds(
    *,
    lookback_hours: float,
    warn_failure_rate: float,
    max_failure_rate: float,
    timeout_seconds: float,
) -> None:
    _finite_float(lookback_hours, field_name="lookback_hours", positive=True)
    warning = _finite_float(warn_failure_rate, field_name="warn_failure_rate")
    maximum = _finite_float(max_failure_rate, field_name="max_failure_rate")
    _finite_float(timeout_seconds, field_name="timeout_seconds", positive=True)
    if not 0 <= warning <= maximum <= 1:
        raise ValueError(
            "failure-rate thresholds must satisfy 0 <= warn_failure_rate <= max_failure_rate <= 1"
        )


def build_tool_failure_monitor_status_report(
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    environ: Mapping[str, str] | None = None,
    lookback_hours: float = 24,
    max_rows: int = 5000,
    min_sample_count: int = 1,
    warn_failure_rate: float = 0.2,
    max_failure_rate: float = 0.5,
    allow_empty_sample: bool = False,
    timeout_seconds: float = 5,
    top_n: int = 8,
) -> dict[str, Any]:
    """Build a redacted tool failure monitoring report."""

    _validate_monitor_thresholds(
        lookback_hours=lookback_hours,
        warn_failure_rate=warn_failure_rate,
        max_failure_rate=max_failure_rate,
        timeout_seconds=timeout_seconds,
    )
    env = environ if environ is not None else os.environ
    checks: dict[str, Any] = {}
    query_status = "not_checked"
    query_error: dict[str, Any] | None = None

    if rows is None:
        db_check = _db_env_check(env)
        checks["database_environment"] = db_check
        if db_check["status"] == "blocked":
            return {
                "version": TOOL_FAILURE_MONITOR_STATUS_VERSION,
                "status": "blocked",
                "collected_at": datetime.now(UTC).isoformat(),
                "policy": {
                    "reads_dotenv": False,
                    "reads_tool_input_output": False,
                    "database_url_echoed": False,
                    "secret_values_echoed": False,
                },
                "checks": checks,
                "blocked_reasons": db_check["blocked_reasons"],
                "degraded_reasons": [],
                "declaration_statuses": {"ZHIXING_TOOL_FAILURE_MONITOR_STATUS": "blocked"},
            }
        try:
            rows = asyncio.run(
                _query_tool_audit_rows(
                    environ=env,
                    lookback_hours=lookback_hours,
                    max_rows=max_rows,
                    timeout_seconds=timeout_seconds,
                )
            )
            query_status = "passed"
        except Exception as exc:  # noqa: BLE001 - status report must not crash with raw stack.
            query_status = "blocked"
            query_error = {
                "status": "blocked",
                "error_type": exc.__class__.__name__,
                "value_echoed": False,
                "finding": "Tool audit database query failed.",
            }
            rows = []
    else:
        query_status = "passed"

    checks["tool_audit_query"] = {
        "status": query_status,
        "lookback_hours": lookback_hours,
        "max_rows": max_rows,
        "value_echoed": False,
        "finding": "Tool audit rows were collected." if query_status == "passed" else "Tool audit query failed.",
    }
    if query_error is not None:
        checks["tool_audit_query"]["error"] = query_error
        return {
            "version": TOOL_FAILURE_MONITOR_STATUS_VERSION,
            "status": "blocked",
            "collected_at": datetime.now(UTC).isoformat(),
            "policy": {
                "reads_dotenv": False,
                "reads_tool_input_output": False,
                "database_url_echoed": False,
                "secret_values_echoed": False,
            },
            "checks": checks,
            "blocked_reasons": [query_error],
            "degraded_reasons": [],
            "declaration_statuses": {"ZHIXING_TOOL_FAILURE_MONITOR_STATUS": "blocked"},
        }

    summary = _summarize_tool_audit_rows(rows, top_n=top_n)
    status, blockers, degraded = _status_from_summary(
        summary,
        min_sample_count=min_sample_count,
        warn_failure_rate=warn_failure_rate,
        max_failure_rate=max_failure_rate,
        allow_empty_sample=allow_empty_sample,
    )
    return {
        "version": TOOL_FAILURE_MONITOR_STATUS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "reads_tool_input_output": False,
            "database_url_echoed": False,
            "secret_values_echoed": False,
            "raw_error_echoed": False,
        },
        "thresholds": {
            "lookback_hours": lookback_hours,
            "max_rows": max_rows,
            "min_sample_count": min_sample_count,
            "warn_failure_rate": warn_failure_rate,
            "max_failure_rate": max_failure_rate,
            "allow_empty_sample": allow_empty_sample,
        },
        "checks": checks,
        "summary": summary,
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
        "declaration_statuses": {
            "ZHIXING_TOOL_FAILURE_MONITOR_STATUS": "passed"
            if query_status == "passed"
            else "blocked"
        },
        "not_proven_by_this_report": [
            "This proves the tool audit monitor can query recent aggregate events; it does not read tool inputs or outputs.",
            "A passed monitor declaration does not prove every upstream tool is healthy.",
            "Empty samples mean the monitoring path works, but recent user traffic quality is not proven.",
            "High failure rate should be handled as an operations finding even when the monitor itself is wired.",
        ],
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _finite_float_arg(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite number") from exc
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError("must be a finite number")
    return number


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-hours", type=_finite_float_arg, default=24, help="Tool audit lookback window.")
    parser.add_argument("--max-rows", type=int, default=5000, help="Maximum recent rows to aggregate.")
    parser.add_argument("--min-sample-count", type=int, default=1, help="Minimum rows expected in the window.")
    parser.add_argument("--warn-failure-rate", type=_finite_float_arg, default=0.2, help="Warning failure-rate threshold.")
    parser.add_argument("--max-failure-rate", type=_finite_float_arg, default=0.5, help="Blocking failure-rate threshold.")
    parser.add_argument("--allow-empty-sample", action="store_true", help="Allow no recent tool events for M1 readiness.")
    parser.add_argument("--timeout-seconds", type=_finite_float_arg, default=5, help="Database query timeout.")
    parser.add_argument("--top-n", type=int, default=8, help="Top aggregate groups to include.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        _validate_monitor_thresholds(
            lookback_hours=args.lookback_hours,
            warn_failure_rate=args.warn_failure_rate,
            max_failure_rate=args.max_failure_rate,
            timeout_seconds=args.timeout_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_tool_failure_monitor_status_report(
        lookback_hours=args.lookback_hours,
        max_rows=args.max_rows,
        min_sample_count=args.min_sample_count,
        warn_failure_rate=args.warn_failure_rate,
        max_failure_rate=args.max_failure_rate,
        allow_empty_sample=args.allow_empty_sample,
        timeout_seconds=args.timeout_seconds,
        top_n=args.top_n,
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
