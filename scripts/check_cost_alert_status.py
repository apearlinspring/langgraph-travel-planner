"""Check M1 cost alert status without reading secrets or provider invoices."""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COST_ALERT_STATUS_VERSION = "cost_alert_status.v1"
READY_VALUES = {"1", "true", "yes", "y", "ready", "passed", "verified", "ok", "done"}
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
    return text[:160]


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _parse_cny_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        amount = float(value)
        return amount if amount >= 0 else None
    text = str(value).replace(",", "").strip()
    match = re.search(r"(?<![\w.])-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    amount = float(match.group(0))
    return amount if amount >= 0 else None


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


async def _query_activity_counts(
    *,
    environ: Mapping[str, str],
    lookback_hours: float,
    timeout_seconds: float,
) -> dict[str, int]:
    import asyncpg

    since_aware = datetime.now(UTC) - timedelta(hours=lookback_hours)
    since_naive = since_aware.replace(tzinfo=None)
    conn = await asyncio.wait_for(
        asyncpg.connect(**_connect_kwargs(environ)),
        timeout=timeout_seconds,
    )
    try:
        message_row = await asyncio.wait_for(
            conn.fetchrow(
                """
                SELECT
                  count(*) AS total,
                  count(*) FILTER (WHERE role = 'user') AS users,
                  count(*) FILTER (WHERE role = 'assistant') AS assistants
                FROM message
                WHERE created_at >= $1
                """,
                since_naive,
            ),
            timeout=timeout_seconds,
        )
        audit_row = await asyncio.wait_for(
            conn.fetchrow(
                """
                SELECT count(*) AS total
                FROM tool_audit_event
                WHERE started_at >= $1
                """,
                since_aware,
            ),
            timeout=timeout_seconds,
        )
    finally:
        await conn.close()
    return {
        "message_total": int(message_row["total"] or 0),
        "message_user": int(message_row["users"] or 0),
        "message_assistant": int(message_row["assistants"] or 0),
        "tool_audit_total": int(audit_row["total"] or 0),
    }


def _activity_has_traffic(activity: Mapping[str, Any] | None) -> bool:
    if not activity:
        return False
    return any(int(activity.get(key) or 0) > 0 for key in ("message_total", "tool_audit_total"))


def _usage_payload(
    *,
    actual_spend_cny: float | None,
    estimated_spend_cny: float | None,
    activity_counts: Mapping[str, Any] | None,
    allow_zero_traffic_estimate: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    spend = actual_spend_cny if actual_spend_cny is not None else estimated_spend_cny
    spend_source = "actual" if actual_spend_cny is not None else "estimated"
    if spend is None and allow_zero_traffic_estimate and activity_counts is not None:
        if _activity_has_traffic(activity_counts):
            blockers.append(
                {
                    "metric": "cost_usage_sample",
                    "finding": "Recent app activity exists, so zero-cost estimate requires a bill or usage estimate.",
                }
            )
        else:
            spend = 0.0
            spend_source = "zero_traffic_estimate"
    if spend is None:
        blockers.append(
            {
                "metric": "cost_usage_sample",
                "finding": "Missing actual spend, estimated spend, or zero-traffic activity evidence.",
            }
        )
        spend = 0.0
        spend_source = "missing"
    return {
        "spend_cny": round(float(spend), 4),
        "spend_source": spend_source,
        "has_actual_spend": actual_spend_cny is not None,
        "has_estimated_spend": estimated_spend_cny is not None,
        "activity_counts": dict(activity_counts or {}),
    }, blockers


def _status_from_budget(
    *,
    budget_cny: float | None,
    spend_cny: float,
    warn_ratio: float,
    block_ratio: float,
    owner_declared: bool,
    manual_check_status: str,
    usage_blockers: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], float | None]:
    blockers = list(usage_blockers)
    degraded: list[dict[str, Any]] = []
    if budget_cny is None or budget_cny <= 0:
        blockers.append(
            {
                "metric": "daily_budget_cny",
                "finding": "Daily cost budget must be a positive CNY amount.",
            }
        )
        ratio = None
    else:
        ratio = round(float(spend_cny) / float(budget_cny), 4)
        if ratio >= block_ratio:
            blockers.append(
                {
                    "metric": "budget_usage_ratio",
                    "value": ratio,
                    "threshold": block_ratio,
                    "finding": "Estimated or actual spend reached the blocking threshold.",
                }
            )
        elif ratio >= warn_ratio:
            degraded.append(
                {
                    "metric": "budget_usage_ratio",
                    "value": ratio,
                    "threshold": warn_ratio,
                    "finding": "Estimated or actual spend reached the warning threshold.",
                }
            )
    if not owner_declared:
        degraded.append(
            {
                "metric": "cost_owner",
                "finding": "Cost or quota owner is not declared.",
            }
        )
    if str(manual_check_status or "").strip().lower() not in READY_VALUES:
        degraded.append(
            {
                "metric": "manual_budget_check",
                "finding": "Manual cost/budget check is not declared as passed.",
            }
        )
    if blockers:
        return "blocked", blockers, degraded, ratio
    if degraded:
        return "degraded", blockers, degraded, ratio
    return "passed", blockers, degraded, ratio


def build_cost_alert_status_report(
    *,
    environ: Mapping[str, str] | None = None,
    daily_budget_cny: float | str | None = None,
    actual_spend_cny: float | str | None = None,
    estimated_spend_cny: float | str | None = None,
    activity_counts: Mapping[str, Any] | None = None,
    check_db_activity: bool = False,
    lookback_hours: float = 24,
    warn_ratio: float = 0.8,
    block_ratio: float = 1.0,
    owner_declared: bool = False,
    manual_check_status: str = "",
    allow_zero_traffic_estimate: bool = False,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Build a redacted cost alert status report."""

    env = environ if environ is not None else os.environ
    checks: dict[str, Any] = {}
    activity = dict(activity_counts or {})
    if check_db_activity:
        db_check = _db_env_check(env)
        checks["database_environment"] = db_check
        if db_check["status"] == "blocked":
            return {
                "version": COST_ALERT_STATUS_VERSION,
                "status": "blocked",
                "collected_at": datetime.now(UTC).isoformat(),
                "policy": {
                    "reads_dotenv": False,
                    "reads_message_content": False,
                    "reads_provider_invoice": False,
                    "database_url_echoed": False,
                    "secret_values_echoed": False,
                },
                "checks": checks,
                "blocked_reasons": db_check["blocked_reasons"],
                "degraded_reasons": [],
                "declaration_statuses": {"ZHIXING_COST_ALERT_STATUS": "blocked"},
            }
        try:
            activity = _query_result = asyncio.run(
                _query_activity_counts(
                    environ=env,
                    lookback_hours=lookback_hours,
                    timeout_seconds=timeout_seconds,
                )
            )
            checks["activity_query"] = {
                "status": "passed",
                "lookback_hours": lookback_hours,
                "value_echoed": False,
                "finding": "Recent app activity counts were collected without reading message content.",
            }
            activity = _query_result
        except Exception as exc:  # noqa: BLE001 - redacted evidence report.
            error = {
                "status": "blocked",
                "error_type": exc.__class__.__name__,
                "value_echoed": False,
                "finding": "Cost activity query failed.",
            }
            checks["activity_query"] = error
            return {
                "version": COST_ALERT_STATUS_VERSION,
                "status": "blocked",
                "collected_at": datetime.now(UTC).isoformat(),
                "policy": {
                    "reads_dotenv": False,
                    "reads_message_content": False,
                    "reads_provider_invoice": False,
                    "database_url_echoed": False,
                    "secret_values_echoed": False,
                },
                "checks": checks,
                "blocked_reasons": [error],
                "degraded_reasons": [],
                "declaration_statuses": {"ZHIXING_COST_ALERT_STATUS": "blocked"},
            }

    budget = _parse_cny_amount(
        daily_budget_cny
        if daily_budget_cny is not None
        else _value(env, "ZHIXING_DAILY_COST_BUDGET")
    )
    actual = _parse_cny_amount(actual_spend_cny)
    estimated = _parse_cny_amount(estimated_spend_cny)
    usage, usage_blockers = _usage_payload(
        actual_spend_cny=actual,
        estimated_spend_cny=estimated,
        activity_counts=activity,
        allow_zero_traffic_estimate=allow_zero_traffic_estimate,
    )
    status, blockers, degraded, ratio = _status_from_budget(
        budget_cny=budget,
        spend_cny=float(usage["spend_cny"]),
        warn_ratio=warn_ratio,
        block_ratio=block_ratio,
        owner_declared=owner_declared,
        manual_check_status=manual_check_status,
        usage_blockers=usage_blockers,
    )
    return {
        "version": COST_ALERT_STATUS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "reads_message_content": False,
            "reads_provider_invoice": False,
            "database_url_echoed": False,
            "secret_values_echoed": False,
            "raw_bill_echoed": False,
        },
        "thresholds": {
            "daily_budget_cny": budget,
            "warn_ratio": warn_ratio,
            "block_ratio": block_ratio,
            "lookback_hours": lookback_hours,
            "allow_zero_traffic_estimate": allow_zero_traffic_estimate,
        },
        "checks": checks,
        "usage": {
            **usage,
            "budget_usage_ratio": ratio,
            "owner_declared": owner_declared,
            "manual_check_status": _redact_text(manual_check_status),
        },
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
        "declaration_statuses": {
            "ZHIXING_COST_ALERT_STATUS": "passed" if status == "passed" else status
        },
        "not_proven_by_this_report": [
            "This M1 check does not read provider invoices or billing console pages.",
            "Project token counts are approximations and do not equal provider bills.",
            "A passed M1 check does not prove hard provider-side budget caps or automatic quota enforcement.",
            "Before M2, replace zero-traffic estimates with provider billing export or API-backed spend collection.",
        ],
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-budget-cny", default=None, help="Daily CNY budget. Falls back to ZHIXING_DAILY_COST_BUDGET.")
    parser.add_argument("--actual-spend-cny", default=None, help="Actual spend from a private provider bill summary.")
    parser.add_argument("--estimated-spend-cny", default=None, help="Manual estimated spend for the window.")
    parser.add_argument("--check-db-activity", action="store_true", help="Read only message/tool-audit counts from PostgreSQL.")
    parser.add_argument("--lookback-hours", type=float, default=24, help="Activity lookback window.")
    parser.add_argument("--warn-ratio", type=float, default=0.8, help="Warning budget usage ratio.")
    parser.add_argument("--block-ratio", type=float, default=1.0, help="Blocking budget usage ratio.")
    parser.add_argument("--owner-declared", action="store_true", help="Declare that a cost/quota owner exists.")
    parser.add_argument("--manual-check-status", default="", help="Manual budget check status, e.g. passed.")
    parser.add_argument("--allow-zero-traffic-estimate", action="store_true", help="Allow 0 CNY estimate when DB activity count is zero.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Database query timeout.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_cost_alert_status_report(
        daily_budget_cny=args.daily_budget_cny,
        actual_spend_cny=args.actual_spend_cny,
        estimated_spend_cny=args.estimated_spend_cny,
        check_db_activity=args.check_db_activity,
        lookback_hours=args.lookback_hours,
        warn_ratio=args.warn_ratio,
        block_ratio=args.block_ratio,
        owner_declared=args.owner_declared,
        manual_check_status=args.manual_check_status,
        allow_zero_traffic_estimate=args.allow_zero_traffic_estimate,
        timeout_seconds=args.timeout_seconds,
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
