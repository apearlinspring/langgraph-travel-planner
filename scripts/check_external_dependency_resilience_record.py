"""Validate a private M1 external dependency resilience record.

The checker validates operator-provided evidence for LLM and external API
readiness, timeout/retry policy, degradation drills, tool failure monitoring
and cost guardrails. It does not read `.env`, call providers, connect network,
connect SSH, start services or print private target values.
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
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts._evidence_record_helpers import (  # noqa: E402
    as_list as _as_list,
    as_mapping as _as_mapping,
    blocker as _blocker,
    has_text as _has_text,
    is_ready as _is_ready,
    make_final_text_checker,
    make_json_object_reader,
    make_path_arg,
    make_placeholder_checker,
    status_from_checks as _status_from_checks,
)


EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION = "external_dependency_resilience_record.v1"
EXTERNAL_API_READINESS_VERSION = "external_api_readiness.v1"
COST_ALERT_STATUS_VERSION = "cost_alert_status.v1"
TOOL_FAILURE_MONITOR_STATUS_VERSION = "tool_failure_monitor_status.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy", "owner role", "record id", "private-workdir", "to fill")
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
DEGRADED_KEYWORDS = ("degrad", "fallback", "manual", "disabled", "pending", "待核验", "降级", "人工", "关闭")
FORBIDDEN_CLAIM_KEYWORDS = (
    "real payment",
    "real booking",
    "inventory lock",
    "locked price",
    "provider sla guaranteed",
    "hard quota guaranteed",
    "正式生产全量",
    "真实支付",
    "真实预订",
    "真实库存",
    "锁价",
    "出票成功",
)


_path_arg = make_path_arg(PROJECT_ROOT)
_read_json = make_json_object_reader(
    read_error="Cannot read external dependency resilience record JSON: {path}",
    object_error="External dependency resilience record must be a JSON object.",
)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=PLACEHOLDER_FRAGMENTS,
)
_has_final_text = make_final_text_checker(_looks_placeholder)


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _required_fields_check(record: Mapping[str, Any]) -> dict[str, Any]:
    required = ("record_id", "started_at", "ended_at", "scope")
    missing = [field for field in required if not _has_final_text(record.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "missing_fields": missing,
        "finding": "Required evidence record fields are present."
        if not missing
        else "Required evidence record fields are missing.",
        "value_echoed": False,
    }


def _owners_check(record: Mapping[str, Any]) -> dict[str, Any]:
    owners = _as_mapping(record.get("owners"))
    required = ("application_owner", "provider_owner", "cost_owner", "verifier", "release_owner")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "finding": "Required provider, cost and release owner roles are assigned."
        if not missing
        else "Required owner roles are missing.",
        "value_echoed": False,
    }


def _external_api_readiness_check(record: Mapping[str, Any]) -> dict[str, Any]:
    readiness = _as_mapping(record.get("external_api_readiness"))
    blockers = []
    if readiness.get("version") != EXTERNAL_API_READINESS_VERSION:
        blockers.append(_blocker("external_api_readiness", "version", "External API readiness version is not recognized."))
    if readiness.get("status") != "passed":
        blockers.append(_blocker("external_api_readiness", "status", "External API readiness must be passed for M1 signoff."))
    if readiness.get("blocked_reasons"):
        blockers.append(_blocker("external_api_readiness", "blocked_reasons", "External API readiness still has blockers."))
    policy = _as_mapping(readiness.get("policy"))
    for key in ("reads_dotenv", "calls_external_providers", "reads_secret_values"):
        if policy.get(key) is not False:
            blockers.append(_blocker("external_api_readiness", f"policy.{key}", f"External API readiness policy {key} must be false."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "readiness_status": readiness.get("status"),
        "optional_service_count": len(_as_list(readiness.get("optional_services"))),
        "value_echoed": False,
    }


def _cost_guard_check(record: Mapping[str, Any]) -> dict[str, Any]:
    cost = _as_mapping(record.get("cost_alert_status"))
    blockers = []
    if cost.get("version") != COST_ALERT_STATUS_VERSION:
        blockers.append(_blocker("cost_guard", "version", "Cost alert status version is not recognized."))
    if cost.get("status") != "passed":
        blockers.append(_blocker("cost_guard", "status", "Cost guard must be passed for M1 signoff."))
    if cost.get("blocked_reasons"):
        blockers.append(_blocker("cost_guard", "blocked_reasons", "Cost guard still has blockers."))
    policy = _as_mapping(cost.get("policy"))
    for key in ("reads_dotenv", "reads_message_content", "reads_provider_invoice", "secret_values_echoed"):
        if policy.get(key) is not False:
            blockers.append(_blocker("cost_guard", f"policy.{key}", f"Cost guard policy {key} must be false."))
    thresholds = _as_mapping(cost.get("thresholds"))
    daily_budget = _to_float(thresholds.get("daily_budget_cny"))
    if daily_budget is None or daily_budget <= 0:
        blockers.append(_blocker("cost_guard", "thresholds.daily_budget_cny", "Daily cost budget must be positive."))
    usage = _as_mapping(cost.get("usage"))
    if usage.get("owner_declared") is not True:
        blockers.append(_blocker("cost_guard", "usage.owner_declared", "Cost owner must be declared."))
    if not _is_ready(usage.get("manual_check_status")):
        blockers.append(_blocker("cost_guard", "usage.manual_check_status", "Manual cost check must be passed."))
    ratio = _to_float(usage.get("budget_usage_ratio"))
    warn_ratio = _to_float(thresholds.get("warn_ratio")) or 0.8
    if ratio is None:
        blockers.append(_blocker("cost_guard", "usage.budget_usage_ratio", "Budget usage ratio must be recorded."))
    elif ratio > warn_ratio:
        blockers.append(_blocker("cost_guard", "usage.budget_usage_ratio", "Budget usage ratio exceeds the warning threshold."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "budget_usage_ratio": ratio,
        "daily_budget_recorded": daily_budget is not None and daily_budget > 0,
        "value_echoed": False,
    }


def _tool_failure_monitor_check(record: Mapping[str, Any]) -> dict[str, Any]:
    monitor = _as_mapping(record.get("tool_failure_monitor"))
    blockers = []
    if monitor.get("version") != TOOL_FAILURE_MONITOR_STATUS_VERSION:
        blockers.append(_blocker("tool_failure_monitor", "version", "Tool failure monitor version is not recognized."))
    if monitor.get("status") != "passed":
        blockers.append(_blocker("tool_failure_monitor", "status", "Tool failure monitor must be passed for M1 signoff."))
    if monitor.get("blocked_reasons"):
        blockers.append(_blocker("tool_failure_monitor", "blocked_reasons", "Tool failure monitor still has blockers."))
    policy = _as_mapping(monitor.get("policy"))
    for key in ("reads_dotenv", "reads_tool_input_output", "database_url_echoed", "secret_values_echoed"):
        if policy.get(key) is not False:
            blockers.append(_blocker("tool_failure_monitor", f"policy.{key}", f"Tool monitor policy {key} must be false."))
    summary = _as_mapping(monitor.get("summary"))
    failure_rate = _to_float(summary.get("failure_rate"))
    max_failure_rate = _to_float(_as_mapping(monitor.get("thresholds")).get("max_failure_rate")) or 0.5
    if failure_rate is None:
        blockers.append(_blocker("tool_failure_monitor", "summary.failure_rate", "Tool failure rate must be recorded."))
    elif failure_rate > max_failure_rate:
        blockers.append(_blocker("tool_failure_monitor", "summary.failure_rate", "Tool failure rate exceeds the blocking threshold."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "sample_count": summary.get("sample_count"),
        "failure_rate": failure_rate,
        "value_echoed": False,
    }


def _timeout_retry_policy_check(record: Mapping[str, Any]) -> dict[str, Any]:
    policy = _as_mapping(record.get("timeout_retry_policy"))
    blockers = []
    llm_timeout = _to_float(policy.get("llm_timeout_seconds"))
    external_timeout = _to_float(policy.get("external_api_timeout_seconds"))
    max_retries = _to_float(policy.get("max_retries"))
    if llm_timeout is None or not 1 <= llm_timeout <= 120:
        blockers.append(_blocker("timeout_retry_policy", "llm_timeout_seconds", "LLM timeout must be bounded between 1 and 120 seconds."))
    if external_timeout is None or not 1 <= external_timeout <= 60:
        blockers.append(_blocker("timeout_retry_policy", "external_api_timeout_seconds", "External API timeout must be bounded between 1 and 60 seconds."))
    if max_retries is None or not 0 <= max_retries <= 3 or int(max_retries) != max_retries:
        blockers.append(_blocker("timeout_retry_policy", "max_retries", "Max retries must be an integer between 0 and 3."))
    if policy.get("unbounded_retry") is not False:
        blockers.append(_blocker("timeout_retry_policy", "unbounded_retry", "Unbounded retry must be explicitly false."))
    if policy.get("backoff_enabled") is not True:
        blockers.append(_blocker("timeout_retry_policy", "backoff_enabled", "Retry backoff must be enabled."))
    fallback = str(policy.get("fallback_behavior") or "").strip().lower()
    if not _has_final_text(policy.get("fallback_behavior")) or not any(keyword in fallback for keyword in DEGRADED_KEYWORDS):
        blockers.append(_blocker("timeout_retry_policy", "fallback_behavior", "Fallback behavior must describe degraded/manual/pending handling."))
    if policy.get("user_facing_degraded_message_defined") is not True:
        blockers.append(_blocker("timeout_retry_policy", "user_facing_degraded_message_defined", "User-facing degraded message must be defined."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "llm_timeout_seconds": llm_timeout,
        "external_api_timeout_seconds": external_timeout,
        "max_retries": max_retries,
        "value_echoed": False,
    }


def _scenario_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "timeout" in text or "超时" in text:
        return "timeout"
    if "429" in text or "rate" in text or "limit" in text or "限流" in text:
        return "rate_limit"
    if "5xx" in text or "500" in text or "upstream" in text or "供应商故障" in text:
        return "provider_5xx"
    return text


def _degradation_drill_check(record: Mapping[str, Any]) -> dict[str, Any]:
    drill = _as_mapping(record.get("degradation_drill"))
    blockers = []
    if drill.get("status") != "passed":
        blockers.append(_blocker("degradation_drill", "status", "External API degradation drill must be passed."))
    scenarios = [item for item in _as_list(drill.get("scenarios")) if isinstance(item, Mapping)]
    scenario_types = {_scenario_type(item.get("scenario") or item.get("type")) for item in scenarios}
    for required in ("timeout", "rate_limit", "provider_5xx"):
        if required not in scenario_types:
            blockers.append(_blocker("degradation_drill", "scenarios", f"Missing {required} degradation scenario."))
    for item in scenarios:
        scenario_name = str(item.get("scenario") or item.get("type") or "scenario")
        if item.get("status") != "passed":
            blockers.append(_blocker("degradation_drill", scenario_name, "Degradation scenario did not pass."))
        behavior = str(item.get("user_visible_behavior") or "").lower()
        if not _has_final_text(item.get("user_visible_behavior")) or not any(keyword in behavior for keyword in DEGRADED_KEYWORDS):
            blockers.append(_blocker("degradation_drill", scenario_name, "Scenario must record user-visible degraded/manual/pending behavior."))
        for field in ("fabricates_inventory", "fabricates_locked_price", "creates_payment", "creates_booking", "locks_inventory"):
            if item.get(field) is not False:
                blockers.append(_blocker("degradation_drill", f"{scenario_name}.{field}", f"Scenario must set {field}=false."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "scenario_count": len(scenarios),
        "scenario_types": sorted(scenario_types),
        "value_echoed": False,
    }


def _observed_metrics_check(record: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _as_mapping(record.get("observed_metrics"))
    blockers = []
    for field in ("external_error_count", "timeout_count", "fallback_count"):
        value = _to_float(metrics.get(field))
        if value is None or value < 0 or int(value) != value:
            blockers.append(_blocker("observed_metrics", field, "Metric must be a non-negative integer."))
    ratio = _to_float(metrics.get("cost_budget_usage_ratio"))
    if ratio is None:
        daily_budget = _to_float(metrics.get("daily_budget_cny"))
        spend = _to_float(metrics.get("estimated_or_actual_spend_cny"))
        if daily_budget is not None and daily_budget > 0 and spend is not None:
            ratio = round(spend / daily_budget, 4)
    if ratio is None:
        blockers.append(_blocker("observed_metrics", "cost_budget_usage_ratio", "Cost budget usage ratio must be recorded or derivable."))
    elif not 0 <= ratio <= 0.8:
        blockers.append(_blocker("observed_metrics", "cost_budget_usage_ratio", "Cost budget usage ratio must be between 0 and 0.8 for M1 signoff."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "cost_budget_usage_ratio": ratio,
        "value_echoed": False,
    }


def _scope_check(record: Mapping[str, Any]) -> dict[str, Any]:
    scope = _as_mapping(record.get("m1_scope"))
    required_false = (
        "real_payment_enabled",
        "real_booking_enabled",
        "inventory_lock_enabled",
        "fulfillment_enabled",
        "proves_provider_sla",
        "proves_provider_quota_enforcement",
        "proves_long_duration_soak",
        "proves_production_ha",
    )
    blockers = []
    for key in required_false:
        if scope.get(key) is not False:
            blockers.append(_blocker("m1_scope", key, f"M1 external dependency scope must explicitly set {key}=false."))
    if not _has_final_text(scope.get("residual_risk")):
        blockers.append(_blocker("m1_scope", "residual_risk", "Residual risk must be recorded."))
    for index, claim in enumerate(_as_list(scope.get("public_claims"))):
        lowered = str(claim or "").lower()
        if any(keyword in lowered for keyword in FORBIDDEN_CLAIM_KEYWORDS):
            blockers.append(_blocker("m1_scope", f"public_claims[{index}]", "Public claim overstates M1 external dependency guarantees."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blocked = []
    for key in (
        "raw_logs_included",
        "screenshots_included",
        "customer_pii_included",
        "secret_values_included",
        "raw_urls_included",
        "raw_provider_response_body_included",
    ):
        if boundary.get(key) is not False:
            blocked.append({"field": f"redaction_boundary.{key}", "finding": "Redaction boundary must explicitly be false."})
    for pattern in SECRET_PATTERNS:
        if pattern.search(raw_text):
            blocked.append({"field": "record_text", "finding": "Record contains a secret-looking value pattern."})
            break
    if URL_PATTERN.search(raw_text):
        blocked.append({"field": "record_text", "finding": "Record contains a raw URL."})
    if IPV4_PATTERN.search(raw_text):
        blocked.append({"field": "record_text", "finding": "Record contains a raw IPv4 address."})
    return {
        "status": "blocked" if blocked else "passed",
        "blocked_reasons": blocked,
        "record_text_echoed": False,
    }


def build_external_dependency_resilience_record_report(
    record: Mapping[str, Any],
    *,
    raw_text: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted validation report for external dependency resilience evidence."""

    checks = {
        "required_fields": _required_fields_check(record),
        "owners": _owners_check(record),
        "external_api_readiness": _external_api_readiness_check(record),
        "cost_guard": _cost_guard_check(record),
        "tool_failure_monitor": _tool_failure_monitor_check(record),
        "timeout_retry_policy": _timeout_retry_policy_check(record),
        "degradation_drill": _degradation_drill_check(record),
        "observed_metrics": _observed_metrics_check(record),
        "m1_scope": _scope_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    now = generated_at or datetime.now(UTC)
    return {
        "version": EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "calls_external_providers": False,
            "connects_network": False,
            "connects_ssh": False,
            "starts_services": False,
            "reads_raw_logs": False,
            "record_text_echoed": False,
        },
        "record_summary": {
            "record_id_present": _has_text(record.get("record_id")),
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "optional_service_count": checks["external_api_readiness"].get("optional_service_count"),
            "tool_sample_count": checks["tool_failure_monitor"].get("sample_count"),
            "tool_failure_rate": checks["tool_failure_monitor"].get("failure_rate"),
            "budget_usage_ratio": checks["cost_guard"].get("budget_usage_ratio"),
            "degradation_scenario_count": checks["degradation_drill"].get("scenario_count"),
            "llm_timeout_seconds": checks["timeout_retry_policy"].get("llm_timeout_seconds"),
            "external_api_timeout_seconds": checks["timeout_retry_policy"].get("external_api_timeout_seconds"),
            "max_retries": checks["timeout_retry_policy"].get("max_retries"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_STATUS": status,
            "ZHIXING_EXTERNAL_API_DEGRADATION_STATUS": checks["degradation_drill"]["status"],
            "ZHIXING_EXTERNAL_API_READINESS_STATUS": checks["external_api_readiness"]["status"],
            "ZHIXING_LLM_COST_GUARD_STATUS": checks["cost_guard"]["status"],
            "ZHIXING_TOOL_FAILURE_MONITOR_STATUS": checks["tool_failure_monitor"]["status"],
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided evidence record; it does not call providers itself.",
            "Passed M1 resilience evidence does not prove provider SLA, hard quota enforcement, production HA or long-duration soak stability.",
            "This does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
            "Raw logs, screenshots, public URLs, IP addresses, .env files, provider response bodies and secret values must stay outside Git.",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "record_id": "<external-dependency-resilience-YYYYMMDD>",
        "started_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "ended_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "<M1 LLM and external API resilience evidence>",
        "owners": {
            "application_owner": "<application owner role>",
            "provider_owner": "<provider console owner role>",
            "cost_owner": "<cost owner role>",
            "verifier": "<verifier role>",
            "release_owner": "<release owner role>",
        },
        "external_api_readiness": {
            "version": EXTERNAL_API_READINESS_VERSION,
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "calls_external_providers": False,
                "reads_secret_values": False,
            },
            "optional_services": [],
            "blocked_reasons": [],
        },
        "cost_alert_status": {
            "version": COST_ALERT_STATUS_VERSION,
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "reads_message_content": False,
                "reads_provider_invoice": False,
                "secret_values_echoed": False,
            },
            "thresholds": {"daily_budget_cny": 200, "warn_ratio": 0.8, "block_ratio": 1.0},
            "usage": {
                "spend_cny": 0,
                "budget_usage_ratio": 0,
                "owner_declared": True,
                "manual_check_status": "passed",
            },
            "blocked_reasons": [],
        },
        "tool_failure_monitor": {
            "version": TOOL_FAILURE_MONITOR_STATUS_VERSION,
            "status": "passed",
            "policy": {
                "reads_dotenv": False,
                "reads_tool_input_output": False,
                "database_url_echoed": False,
                "secret_values_echoed": False,
            },
            "thresholds": {"max_failure_rate": 0.5},
            "summary": {"sample_count": 0, "failure_rate": 0},
            "blocked_reasons": [],
        },
        "timeout_retry_policy": {
            "llm_timeout_seconds": 60,
            "external_api_timeout_seconds": 15,
            "max_retries": 1,
            "backoff_enabled": True,
            "unbounded_retry": False,
            "fallback_behavior": "Degraded response with manual verification and pending external data.",
            "user_facing_degraded_message_defined": True,
        },
        "degradation_drill": {
            "status": "passed",
            "scenarios": [
                {
                    "scenario": "provider_timeout",
                    "status": "passed",
                    "user_visible_behavior": "Degraded response with pending verification.",
                    "fabricates_inventory": False,
                    "fabricates_locked_price": False,
                    "creates_payment": False,
                    "creates_booking": False,
                    "locks_inventory": False,
                },
                {
                    "scenario": "provider_rate_limit_429",
                    "status": "passed",
                    "user_visible_behavior": "Manual verification required after rate limit.",
                    "fabricates_inventory": False,
                    "fabricates_locked_price": False,
                    "creates_payment": False,
                    "creates_booking": False,
                    "locks_inventory": False,
                },
                {
                    "scenario": "provider_5xx",
                    "status": "passed",
                    "user_visible_behavior": "Fallback itinerary with external data pending verification.",
                    "fabricates_inventory": False,
                    "fabricates_locked_price": False,
                    "creates_payment": False,
                    "creates_booking": False,
                    "locks_inventory": False,
                },
            ],
        },
        "observed_metrics": {
            "external_error_count": 0,
            "timeout_count": 0,
            "fallback_count": 0,
            "cost_budget_usage_ratio": 0,
        },
        "m1_scope": {
            "real_payment_enabled": False,
            "real_booking_enabled": False,
            "inventory_lock_enabled": False,
            "fulfillment_enabled": False,
            "proves_provider_sla": False,
            "proves_provider_quota_enforcement": False,
            "proves_long_duration_soak": False,
            "proves_production_ha": False,
            "residual_risk": "<M1 evidence does not prove provider SLA, full HA or long-duration soak>",
            "public_claims": ["M1 controlled trial only; external provider data may degrade to pending verification."],
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
            "raw_provider_response_body_included": False,
        },
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private external dependency resilience JSON record.")
    parser.add_argument("--template", action="store_true", help="Print a private evidence-record template.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report: Mapping[str, Any] = _template_record()
    else:
        if args.record_json is None:
            report = {
                "version": EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [{"check": "input", "finding": "--record-json or --template is required."}],
            }
        else:
            try:
                raw_text = args.record_json.read_text(encoding="utf-8-sig")
                record = _read_json(args.record_json)
                report = build_external_dependency_resilience_record_report(record, raw_text=raw_text)
            except ValueError as exc:
                report = {
                    "version": EXTERNAL_DEPENDENCY_RESILIENCE_RECORD_VERSION,
                    "status": "blocked",
                    "blocked_reasons": [{"check": "input", "finding": str(exc)}],
                }
    output_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)
    return 2 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
