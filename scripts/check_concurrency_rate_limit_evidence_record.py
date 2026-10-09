"""Validate a private M1 concurrency and rate-limit evidence record.

The checker validates operator-provided evidence from the low-risk live
concurrency probe and rate-limit live probe. It does not read `.env`, run load
tests, call live services, connect Redis, connect SSH, start services or print
private target values.
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


CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION = "concurrency_rate_limit_evidence_record.v1"
LIVE_CONCURRENCY_PROBE_VERSION = "live_concurrency_probe.v1"
RATE_LIMIT_LIVE_PROBE_VERSION = "rate_limit_live_probe.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
PLACEHOLDER_FRAGMENTS = ("yyyy-", "owner role", "record id", "private")
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


_path_arg = make_path_arg(PROJECT_ROOT)
_read_json = make_json_object_reader(
    read_error="Cannot read concurrency/rate-limit evidence record JSON: {path}",
    object_error="Concurrency/rate-limit evidence record must be a JSON object.",
)
_looks_placeholder = make_placeholder_checker(
    prefixes=PLACEHOLDER_PREFIXES,
    fragments=PLACEHOLDER_FRAGMENTS,
)
_has_final_text = make_final_text_checker(_looks_placeholder)


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
    required = ("application_owner", "test_owner", "verifier", "release_owner")
    missing = [field for field in required if not _has_final_text(owners.get(field))]
    return {
        "status": "blocked" if missing else "passed",
        "owner_roles_present": len(required) - len(missing),
        "missing_owner_roles": missing,
        "finding": "Required load and release owner roles are assigned."
        if not missing
        else "Required owner roles are missing.",
        "value_echoed": False,
    }


def _concurrency_probe_check(record: Mapping[str, Any]) -> dict[str, Any]:
    probe = _as_mapping(record.get("concurrency_probe"))
    blockers = []
    if probe.get("version") != LIVE_CONCURRENCY_PROBE_VERSION:
        blockers.append(_blocker("concurrency_probe", "version", "Concurrency probe version is not recognized."))
    if probe.get("status") != "passed":
        blockers.append(_blocker("concurrency_probe", "status", "Concurrency probe must be passed for M1 signoff."))
    policy = _as_mapping(probe.get("policy"))
    expected_false = (
        "reads_dotenv",
        "reads_response_body",
        "calls_llm",
        "calls_external_provider_apis",
        "creates_real_payment",
        "creates_real_booking",
        "locks_inventory",
        "url_echoed",
    )
    for key in expected_false:
        if policy.get(key) is not False:
            blockers.append(_blocker("concurrency_probe", f"policy.{key}", f"Concurrency probe policy {key} must be false."))
    if policy.get("http_methods") != ["GET"]:
        blockers.append(_blocker("concurrency_probe", "policy.http_methods", "Concurrency probe must use GET-only endpoints."))
    endpoints = [item for item in _as_list(probe.get("endpoints")) if isinstance(item, Mapping)]
    if not endpoints:
        blockers.append(_blocker("concurrency_probe", "endpoints", "Concurrency probe endpoints are missing."))
    endpoint_summaries = []
    worst_p95 = None
    total_requests = 0
    for endpoint in endpoints:
        status = str(endpoint.get("status") or "")
        if status != "passed":
            blockers.append(_blocker("concurrency_probe", str(endpoint.get("endpoint_key") or "endpoint"), "Endpoint did not pass concurrency probe."))
        request_count = int(endpoint.get("request_count") or 0)
        success_count = int(endpoint.get("success_count") or 0)
        error_rate = float(endpoint.get("error_rate") or 0)
        latency = _as_mapping(endpoint.get("latency_ms"))
        p95 = latency.get("p95")
        if request_count <= 0 or success_count <= 0:
            blockers.append(_blocker("concurrency_probe", str(endpoint.get("endpoint_key") or "endpoint"), "Endpoint request/success count is missing."))
        if error_rate != 0:
            blockers.append(_blocker("concurrency_probe", str(endpoint.get("endpoint_key") or "endpoint"), "Endpoint error rate must be zero for M1 low-risk signoff."))
        if p95 is not None:
            try:
                worst_p95 = max(float(p95), float(worst_p95 or 0))
            except (TypeError, ValueError):
                blockers.append(_blocker("concurrency_probe", str(endpoint.get("endpoint_key") or "endpoint"), "Endpoint P95 latency must be numeric."))
        total_requests += request_count
        endpoint_summaries.append(
            {
                "endpoint_key": endpoint.get("endpoint_key"),
                "request_count": request_count,
                "success_count": success_count,
                "error_rate": error_rate,
                "p95_ms": p95,
            }
        )
    thresholds = _as_mapping(probe.get("thresholds"))
    if int(thresholds.get("concurrency") or 0) <= 0:
        blockers.append(_blocker("concurrency_probe", "thresholds.concurrency", "Concurrency threshold must be recorded."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "endpoint_count": len(endpoints),
        "total_requests": total_requests,
        "worst_p95_ms": worst_p95,
        "endpoint_summaries": endpoint_summaries,
        "value_echoed": False,
    }


def _rate_limit_probe_check(record: Mapping[str, Any]) -> dict[str, Any]:
    probe = _as_mapping(record.get("rate_limit_probe"))
    blockers = []
    if probe.get("version") != RATE_LIMIT_LIVE_PROBE_VERSION:
        blockers.append(_blocker("rate_limit_probe", "version", "Rate-limit probe version is not recognized."))
    if probe.get("status") != "passed":
        blockers.append(_blocker("rate_limit_probe", "status", "Rate-limit probe must be passed for M1 signoff."))
    policy = _as_mapping(probe.get("policy"))
    expected_false = (
        "reads_dotenv",
        "reads_response_body",
        "calls_llm",
        "calls_external_provider_apis",
        "creates_real_payment",
        "creates_real_booking",
        "locks_inventory",
        "url_echoed",
    )
    for key in expected_false:
        if policy.get(key) is not False:
            blockers.append(_blocker("rate_limit_probe", f"policy.{key}", f"Rate-limit probe policy {key} must be false."))
    if policy.get("http_methods") != ["GET"]:
        blockers.append(_blocker("rate_limit_probe", "policy.http_methods", "Rate-limit probe must use GET-only endpoint."))
    status_counts = _as_mapping(probe.get("status_counts"))
    saw_success = any(int(status_counts.get(str(code)) or 0) > 0 for code in range(200, 300))
    saw_429 = int(status_counts.get("429") or 0) > 0
    if not saw_success:
        blockers.append(_blocker("rate_limit_probe", "status_counts", "No successful response was recorded before limiting."))
    if not saw_429:
        blockers.append(_blocker("rate_limit_probe", "status_counts.429", "No HTTP 429 response was recorded."))
    headers = _as_mapping(probe.get("rate_limit_headers_seen"))
    for header in ("x-ratelimit-limit", "x-ratelimit-reset", "retry-after"):
        if headers.get(header) is not True:
            blockers.append(_blocker("rate_limit_probe", f"headers.{header}", f"{header} header was not observed."))
    if int(probe.get("request_count") or 0) <= 0:
        blockers.append(_blocker("rate_limit_probe", "request_count", "Rate-limit request count is missing."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "request_count": probe.get("request_count"),
        "status_counts": dict(status_counts),
        "value_echoed": False,
    }


def _rate_limit_config_check(record: Mapping[str, Any]) -> dict[str, Any]:
    config = _as_mapping(record.get("rate_limit_config"))
    blockers = []
    if config.get("api_rate_limit_enabled") is not True:
        blockers.append(_blocker("rate_limit_config", "api_rate_limit_enabled", "API rate limit must be enabled."))
    if str(config.get("api_rate_limit_backend") or "").strip().lower() != "redis":
        blockers.append(_blocker("rate_limit_config", "api_rate_limit_backend", "API rate limit backend must be redis."))
    if config.get("api_rate_limit_local_fallback") is not False:
        blockers.append(_blocker("rate_limit_config", "api_rate_limit_local_fallback", "API rate limit local fallback must be false."))
    if str(config.get("redis_unavailable_behavior") or "").strip().lower() not in {"fail_closed_429", "fail closed 429", "fail_closed"}:
        blockers.append(_blocker("rate_limit_config", "redis_unavailable_behavior", "Redis-unavailable behavior must be fail closed with 429."))
    if config.get("protects_api_v1") is not True:
        blockers.append(_blocker("rate_limit_config", "protects_api_v1", "Rate limit must protect /api/v1."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "backend": "redis" if str(config.get("api_rate_limit_backend") or "").strip().lower() == "redis" else "unknown",
        "local_fallback": config.get("api_rate_limit_local_fallback"),
        "value_echoed": False,
    }


def _scope_check(record: Mapping[str, Any]) -> dict[str, Any]:
    scope = _as_mapping(record.get("m1_scope"))
    required_false = (
        "calls_llm",
        "calls_external_provider_apis",
        "creates_real_payment",
        "creates_real_booking",
        "locks_inventory",
        "proves_chat_throughput",
        "proves_autoscaling",
        "proves_long_duration_soak",
    )
    blockers = []
    for key in required_false:
        if scope.get(key) is not False:
            blockers.append(_blocker("m1_scope", key, f"M1 low-risk concurrency scope must explicitly set {key}=false."))
    if not _has_final_text(scope.get("residual_risk")):
        blockers.append(_blocker("m1_scope", "residual_risk", "Residual risk must be recorded."))
    return {
        "status": "blocked" if blockers else "passed",
        "blocked_reasons": blockers,
        "value_echoed": False,
    }


def _redaction_boundary_check(record: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
    boundary = _as_mapping(record.get("redaction_boundary"))
    blocked = []
    for key in ("raw_logs_included", "screenshots_included", "customer_pii_included", "secret_values_included", "raw_urls_included"):
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


def build_concurrency_rate_limit_evidence_record_report(
    record: Mapping[str, Any],
    *,
    raw_text: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a redacted validation report for M1 concurrency/rate-limit evidence."""

    checks = {
        "required_fields": _required_fields_check(record),
        "owners": _owners_check(record),
        "concurrency_probe": _concurrency_probe_check(record),
        "rate_limit_probe": _rate_limit_probe_check(record),
        "rate_limit_config": _rate_limit_config_check(record),
        "m1_scope": _scope_check(record),
        "redaction_boundary": _redaction_boundary_check(record, raw_text or json.dumps(record, ensure_ascii=False)),
    }
    status, blockers = _status_from_checks(checks)
    now = generated_at or datetime.now(UTC)
    return {
        "version": CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION,
        "status": status,
        "generated_at": now.isoformat(),
        "policy": {
            "reads_dotenv": False,
            "runs_load_test": False,
            "calls_live_services": False,
            "connects_redis": False,
            "connects_ssh": False,
            "starts_services": False,
            "record_text_echoed": False,
        },
        "record_summary": {
            "record_id_present": _has_text(record.get("record_id")),
            "owner_roles_present": checks["owners"].get("owner_roles_present"),
            "concurrency_endpoint_count": checks["concurrency_probe"].get("endpoint_count"),
            "concurrency_total_requests": checks["concurrency_probe"].get("total_requests"),
            "worst_p95_ms": checks["concurrency_probe"].get("worst_p95_ms"),
            "rate_limit_request_count": checks["rate_limit_probe"].get("request_count"),
            "rate_limit_backend": checks["rate_limit_config"].get("backend"),
        },
        "checks": checks,
        "declaration_statuses": {
            "ZHIXING_CONCURRENCY_EVIDENCE_STATUS": checks["concurrency_probe"]["status"],
            "ZHIXING_RATE_LIMIT_EVIDENCE_STATUS": checks["rate_limit_probe"]["status"],
            "ZHIXING_RATE_LIMIT_FAIL_CLOSED_STATUS": checks["rate_limit_config"]["status"],
            "ZHIXING_M1_CONCURRENCY_RATE_LIMIT_RECORD_STATUS": status,
        },
        "blocked_reasons": blockers,
        "not_proven_by_this_report": [
            "This validates an operator-provided evidence record; it does not run a load test itself.",
            "Passed low-risk probes do not prove chat throughput, LLM latency, autoscaling, WAF protection or long-duration soak stability.",
            "This does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
            "Raw logs, screenshots, public URLs, IP addresses, .env files and secret values must stay outside Git.",
        ],
    }


def _template_record() -> dict[str, Any]:
    return {
        "record_id": "<concurrency-rate-limit-YYYYMMDD>",
        "started_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "ended_at": "<YYYY-MM-DDTHH:MM:SS+08:00>",
        "scope": "<M1 low-risk GET endpoints and API rate-limit probe>",
        "owners": {
            "application_owner": "<application owner role>",
            "test_owner": "<test owner role>",
            "verifier": "<verifier role>",
            "release_owner": "<release owner role>",
        },
        "concurrency_probe": {
            "version": LIVE_CONCURRENCY_PROBE_VERSION,
            "status": "passed",
            "policy": {
                "http_methods": ["GET"],
                "reads_dotenv": False,
                "reads_response_body": False,
                "calls_llm": False,
                "calls_external_provider_apis": False,
                "creates_real_payment": False,
                "creates_real_booking": False,
                "locks_inventory": False,
                "url_echoed": False,
            },
            "thresholds": {"requests_per_endpoint": 30, "concurrency": 10, "max_p95_ms": 2000, "max_error_rate": 0},
            "endpoints": [
                {"status": "passed", "endpoint_key": "health_live", "request_count": 30, "success_count": 30, "error_rate": 0, "latency_ms": {"p95": 0}},
                {"status": "passed", "endpoint_key": "health_ready", "request_count": 30, "success_count": 30, "error_rate": 0, "latency_ms": {"p95": 0}},
                {"status": "passed", "endpoint_key": "mock_checkout_status", "request_count": 30, "success_count": 30, "error_rate": 0, "latency_ms": {"p95": 0}},
            ],
        },
        "rate_limit_probe": {
            "version": RATE_LIMIT_LIVE_PROBE_VERSION,
            "status": "passed",
            "policy": {
                "http_methods": ["GET"],
                "reads_dotenv": False,
                "reads_response_body": False,
                "calls_llm": False,
                "calls_external_provider_apis": False,
                "creates_real_payment": False,
                "creates_real_booking": False,
                "locks_inventory": False,
                "url_echoed": False,
            },
            "request_count": 130,
            "status_counts": {"200": 120, "429": 10},
            "rate_limit_headers_seen": {
                "x-ratelimit-limit": True,
                "x-ratelimit-reset": True,
                "retry-after": True,
            },
        },
        "rate_limit_config": {
            "api_rate_limit_enabled": True,
            "api_rate_limit_backend": "redis",
            "api_rate_limit_local_fallback": False,
            "redis_unavailable_behavior": "fail_closed_429",
            "protects_api_v1": True,
        },
        "m1_scope": {
            "calls_llm": False,
            "calls_external_provider_apis": False,
            "creates_real_payment": False,
            "creates_real_booking": False,
            "locks_inventory": False,
            "proves_chat_throughput": False,
            "proves_autoscaling": False,
            "proves_long_duration_soak": False,
            "residual_risk": "<low-risk probes do not prove full chat throughput or autoscaling>",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
        },
    }


def _draft_record_from_probes(
    *,
    concurrency_probe: Mapping[str, Any],
    rate_limit_probe: Mapping[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    observations = _as_mapping(rate_limit_probe.get("rate_limit_header_observations"))
    backends = [str(item) for item in _as_list(observations.get("backend_values_seen")) if item]
    backend = backends[0] if backends else "<confirm-rate-limit-backend>"
    return {
        "record_id": f"concurrency-rate-limit-draft-{now.strftime('%Y%m%d')}",
        "started_at": str(concurrency_probe.get("collected_at") or "<fill-started-at>"),
        "ended_at": str(rate_limit_probe.get("collected_at") or now.isoformat()),
        "scope": "M1 low-risk GET endpoints and API rate-limit probe",
        "owners": {
            "application_owner": "<application owner role>",
            "test_owner": "<test owner role>",
            "verifier": "<verifier role>",
            "release_owner": "<release owner role>",
        },
        "concurrency_probe": dict(concurrency_probe),
        "rate_limit_probe": dict(rate_limit_probe),
        "rate_limit_config": {
            "api_rate_limit_enabled": rate_limit_probe.get("status") == "passed",
            "api_rate_limit_backend": backend,
            "api_rate_limit_local_fallback": False,
            "redis_unavailable_behavior": "<confirm-fail-closed-429>",
            "protects_api_v1": True,
        },
        "m1_scope": {
            "calls_llm": False,
            "calls_external_provider_apis": False,
            "creates_real_payment": False,
            "creates_real_booking": False,
            "locks_inventory": False,
            "proves_chat_throughput": False,
            "proves_autoscaling": False,
            "proves_long_duration_soak": False,
            "residual_risk": "Low-risk GET probes do not prove chat throughput, autoscaling or long-duration soak stability.",
        },
        "redaction_boundary": {
            "raw_logs_included": False,
            "screenshots_included": False,
            "customer_pii_included": False,
            "secret_values_included": False,
            "raw_urls_included": False,
        },
        "manual_fields_remaining": [
            "owners.application_owner",
            "owners.test_owner",
            "owners.verifier",
            "owners.release_owner",
            "rate_limit_config.redis_unavailable_behavior",
        ],
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-json", type=_path_arg, default=None, help="Private concurrency/rate-limit evidence JSON record.")
    parser.add_argument("--draft-from-probes", action="store_true", help="Build a private draft record from existing probe JSON files.")
    parser.add_argument("--concurrency-probe-json", type=_path_arg, default=None, help="Existing live concurrency probe JSON.")
    parser.add_argument("--rate-limit-probe-json", type=_path_arg, default=None, help="Existing rate-limit probe JSON.")
    parser.add_argument("--template", action="store_true", help="Print a private evidence-record template.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional output JSON path.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.template:
        report: Mapping[str, Any] = _template_record()
    elif args.draft_from_probes:
        if args.concurrency_probe_json is None or args.rate_limit_probe_json is None:
            report = {
                "version": CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [
                    {
                        "check": "input",
                        "finding": "--concurrency-probe-json and --rate-limit-probe-json are required.",
                    }
                ],
            }
        else:
            try:
                concurrency_probe = _read_json(args.concurrency_probe_json)
                rate_limit_probe = _read_json(args.rate_limit_probe_json)
                report = _draft_record_from_probes(
                    concurrency_probe=concurrency_probe,
                    rate_limit_probe=rate_limit_probe,
                )
            except ValueError as exc:
                report = {
                    "version": CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION,
                    "status": "blocked",
                    "blocked_reasons": [{"check": "input", "finding": str(exc)}],
                }
    else:
        if args.record_json is None:
            report = {
                "version": CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION,
                "status": "blocked",
                "blocked_reasons": [{"check": "input", "finding": "--record-json or --template is required."}],
            }
        else:
            try:
                raw_text = args.record_json.read_text(encoding="utf-8-sig")
                record = _read_json(args.record_json)
                report = build_concurrency_rate_limit_evidence_record_report(record, raw_text=raw_text)
            except ValueError as exc:
                report = {
                    "version": CONCURRENCY_RATE_LIMIT_EVIDENCE_RECORD_VERSION,
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
