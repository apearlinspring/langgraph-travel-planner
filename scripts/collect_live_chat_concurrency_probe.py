"""Collect redacted tiny live chat SSE concurrency evidence for M1.

The default mode is plan-only. Passing ``--execute`` performs a bounded set of
authenticated conversation creations plus chat SSE turns. This may call the
configured LLM or external provider APIs and may write runtime probe user,
conversation and message records.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_live_chat_concurrency_probe_approval import (
    LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION,
)
from scripts.collect_live_chat_probe import (
    DEFAULT_ACCESS_TOKEN_ENV,
    DEFAULT_EMAIL_ENV,
    DEFAULT_PASSWORD_ENV,
    DEFAULT_PROMPT,
    DEFAULT_USERNAME_ENV,
    PUBLIC_URL_PLACEHOLDER,
    StdlibChatProbeClient,
    _normalize_base_url,
    _secret_from_inputs,
    build_live_chat_probe_report,
)


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


LIVE_CHAT_CONCURRENCY_PROBE_VERSION = "live_chat_concurrency_probe.v1"
DEFAULT_CONVERSATION_TITLE = "M1 live chat concurrency probe"


def _path_arg(value: str) -> Path:
    return Path(value)


def _read_json_file(path: Path | None, *, label: str) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if path is None:
        return None, {"key": f"{label}_missing", "finding": f"{label} JSON path is required."}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {"key": f"{label}_unreadable", "finding": f"{label} JSON could not be read."}
    if not isinstance(payload, dict):
        return None, {"key": f"{label}_invalid", "finding": f"{label} JSON must be an object."}
    return payload, None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(float(values[0]), 3)
    ordered = sorted(float(item) for item in values)
    index = max(0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _approval_gate(
    *,
    approval_report: Mapping[str, Any] | None,
    request_count: int,
    concurrency: int,
    execute: bool,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not execute:
        return [], {
            "approval_required_for_execution": True,
            "approval_status": "not_checked",
            "approval_report_version": "",
            "approved_limits": {},
        }
    if approval_report is None:
        return [
            {"key": "approval_report_missing", "finding": "Approval report is required before live chat concurrency execution."}
        ], {
            "approval_required_for_execution": True,
            "approval_status": "missing",
            "approval_report_version": "",
            "approved_limits": {},
        }
    limits = _as_mapping(approval_report.get("approved_limits"))
    blocked: list[dict[str, str]] = []
    if approval_report.get("version") != LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION:
        blocked.append({"key": "approval_report_version", "finding": "Approval report version is not for live chat concurrency."})
    if approval_report.get("status") != "passed":
        blocked.append({"key": "approval_report_not_passed", "finding": "Approval report status must be passed before execution."})
    if approval_report.get("decision") != "approved_for_live_chat_concurrency_probe":
        blocked.append({"key": "approval_decision", "finding": "Approval decision must allow live chat concurrency probe."})
    try:
        max_probe_conversations = int(limits.get("max_probe_conversations", 0))
    except (TypeError, ValueError):
        max_probe_conversations = 0
    try:
        max_concurrency = int(limits.get("max_concurrency", 0))
    except (TypeError, ValueError):
        max_concurrency = 0
    if request_count > max_probe_conversations:
        blocked.append({"key": "request_count_exceeds_approval", "finding": "Requested probe conversations exceed approval limit."})
    if concurrency > max_concurrency:
        blocked.append({"key": "concurrency_exceeds_approval", "finding": "Requested concurrency exceeds approval limit."})
    return blocked, {
        "approval_required_for_execution": True,
        "approval_status": approval_report.get("status"),
        "approval_report_version": approval_report.get("version"),
        "approved_limits": {
            "max_probe_conversations": max_probe_conversations,
            "max_concurrency": max_concurrency,
        },
    }


def _pre_register_probe_user(
    *,
    base_url: str,
    username: str,
    password: str,
    email: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    result = {
        "registration_requested": True,
        "registration_attempted": False,
        "registration_performed": False,
        "existing_probe_user_reused": False,
        "blocked_reasons": [],
    }
    client = StdlibChatProbeClient(base_url)
    result["registration_attempted"] = True
    try:
        client.post_json(
            "/api/v1/users/register",
            {"username": username, "email": email, "password": password},
            token=None,
            timeout_seconds=timeout_seconds,
        )
        result["registration_performed"] = True
    except HTTPError as exc:
        if exc.code != 400:
            result["blocked_reasons"].append(
                {"key": "probe_registration_failed", "finding": f"Probe user registration returned HTTP {exc.code}."}
            )
        else:
            result["existing_probe_user_reused"] = True
    except (TimeoutError, URLError, OSError, RuntimeError, ValueError) as exc:
        result["blocked_reasons"].append(
            {"key": exc.__class__.__name__, "finding": "Probe user registration failed before concurrency sample."}
        )
    return result


def _probe_result_summary(index: int, report: Mapping[str, Any]) -> dict[str, Any]:
    observations = _as_mapping(report.get("observations"))
    return {
        "index": index,
        "status": report.get("status"),
        "stream_completed": observations.get("stream_completed"),
        "event_count": observations.get("event_count"),
        "first_event_seconds": observations.get("first_event_seconds"),
        "first_token_seconds": observations.get("first_token_seconds"),
        "total_seconds": observations.get("total_seconds"),
        "assistant_chars_observed": observations.get("assistant_chars_observed"),
        "blocked_reason_keys": [
            item.get("key")
            for item in report.get("blocked_reasons") or []
            if isinstance(item, Mapping)
        ],
        "degraded_reason_keys": [
            item.get("key")
            for item in report.get("degraded_reasons") or []
            if isinstance(item, Mapping)
        ],
        "credentials_echoed": False,
        "prompt_echoed": False,
        "assistant_text_echoed": False,
    }


def _status_counts(results: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in results:
        key = str(item.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build_live_chat_concurrency_probe_report(
    *,
    base_url: str,
    approval_report: Mapping[str, Any] | None = None,
    access_token: str | None = None,
    access_token_env: str = DEFAULT_ACCESS_TOKEN_ENV,
    username: str | None = None,
    username_env: str = DEFAULT_USERNAME_ENV,
    password: str | None = None,
    password_env: str = DEFAULT_PASSWORD_ENV,
    email: str | None = None,
    email_env: str = DEFAULT_EMAIL_ENV,
    register_probe_user: bool = False,
    prompt: str = DEFAULT_PROMPT,
    conversation_title: str = DEFAULT_CONVERSATION_TITLE,
    execute: bool = False,
    request_count: int = 3,
    concurrency: int = 2,
    timeout_seconds: float = 120.0,
    max_first_event_seconds: float = 30.0,
    max_first_token_seconds: float = 75.0,
    max_total_seconds: float = 120.0,
    max_p95_total_seconds: float = 120.0,
    max_blocked_rate: float = 0.34,
    environ: Mapping[str, str] | None = None,
    probe_runner: Callable[[int], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build redacted evidence for a tiny live chat SSE concurrency sample."""

    report: dict[str, Any] = {
        "version": LIVE_CHAT_CONCURRENCY_PROBE_VERSION,
        "status": "blocked" if execute else "not_checked",
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "requires_execute_flag": True,
            "requires_approval_report": True,
            "execute_requested": execute,
            "http_methods": ["POST"],
            "reads_dotenv": False,
            "parses_response_events_for_metrics": execute,
            "records_response_body": False,
            "records_credentials": False,
            "records_prompt": False,
            "records_assistant_text": False,
            "calls_llm": execute,
            "calls_external_provider_apis": execute,
            "creates_probe_conversations": request_count if execute else 0,
            "writes_runtime_messages": execute,
            "creates_real_payment": False,
            "creates_real_booking": False,
            "locks_inventory": False,
            "triggers_ticketing": False,
            "triggers_fulfillment": False,
            "load_test": False,
            "public_base_url_echoed": False,
            "credentials_echoed": False,
        },
        "target": {
            "base_url": PUBLIC_URL_PLACEHOLDER if base_url else "",
            "base_url_present": bool(base_url),
            "base_url_echoed": False,
            "chat_stream_endpoint": "/api/v1/chat/stream/<conversation-id>",
        },
        "thresholds": {
            "request_count": request_count,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
            "max_first_event_seconds": max_first_event_seconds,
            "max_first_token_seconds": max_first_token_seconds,
            "max_total_seconds": max_total_seconds,
            "max_p95_total_seconds": max_p95_total_seconds,
            "max_blocked_rate": max_blocked_rate,
        },
        "approval": {},
        "registration": {
            "registration_requested": register_probe_user,
            "registration_attempted": False,
            "registration_performed": False,
            "existing_probe_user_reused": False,
        },
        "probe_results": [],
        "not_proven_by_this_probe": [
            "This is a tiny bounded chat-path concurrency sample, not a load test.",
            "A passed result does not prove high-concurrency throughput, autoscaling, long-duration soak stability or formal SLO compliance.",
            "This probe may call LLM or external provider APIs, but it does not prove provider SLA or long-term quota sufficiency.",
            "It does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
            "It does not store or echo the public URL, access token, probe credentials, probe email, prompt, conversation id or assistant text.",
        ],
    }
    if not execute:
        report["plan"] = {
            "approval_command": (
                "python scripts/check_live_chat_concurrency_probe_approval.py "
                "--approval-json <private-workdir>\\live-chat-concurrency-probe-approval.local.json "
                "--json --output <private-workdir>\\live-chat-concurrency-probe-approval-report.json"
            ),
            "execution_command": (
                "python scripts/collect_live_chat_concurrency_probe.py --base-url <public-url> "
                "--approval-json <private-workdir>\\live-chat-concurrency-probe-approval-report.json "
                "--username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD "
                "--request-count 3 --concurrency 2 --execute"
            ),
            "may_call_llm_or_external_apis": True,
            "may_write_runtime_conversation_records": True,
            "not_a_load_test": True,
        }
        return report

    blocked_reasons, approval_summary = _approval_gate(
        approval_report=approval_report,
        request_count=request_count,
        concurrency=concurrency,
        execute=execute,
    )
    report["approval"] = approval_summary
    if request_count <= 0 or concurrency <= 0 or timeout_seconds <= 0:
        blocked_reasons.append({"key": "invalid_threshold", "finding": "Request count, concurrency and timeout must be positive."})
    if request_count > 5:
        blocked_reasons.append({"key": "request_count_too_large", "finding": "This tiny M1 probe allows at most 5 chat conversations."})
    if concurrency > 3:
        blocked_reasons.append({"key": "concurrency_too_large", "finding": "This tiny M1 probe allows at most concurrency 3."})
    if max_blocked_rate < 0 or max_blocked_rate > 1:
        blocked_reasons.append({"key": "invalid_blocked_rate", "finding": "Blocked-rate threshold must be between 0 and 1."})
    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError:
        blocked_reasons.append({"key": "invalid_target", "finding": "Base URL must be absolute HTTP(S)."})
        normalized_base_url = ""

    env = environ if environ is not None else os.environ
    token, _token_source = _secret_from_inputs(value=access_token, env_name=access_token_env, environ=env)
    probe_username, _username_source = _secret_from_inputs(value=username, env_name=username_env, environ=env)
    probe_password, _password_source = _secret_from_inputs(value=password, env_name=password_env, environ=env)
    probe_email, _email_source = _secret_from_inputs(value=email, env_name=email_env, environ=env)
    if not token and not (probe_username and probe_password):
        blocked_reasons.append({"key": "missing_auth_credentials", "finding": "Access token or probe username/password is required."})
    if register_probe_user and not (probe_username and probe_password and probe_email):
        blocked_reasons.append({"key": "missing_probe_registration_inputs", "finding": "Probe username, password and email are required when registration is requested."})

    if blocked_reasons:
        report["blocked_reasons"] = blocked_reasons
        report["degraded_reasons"] = []
        report["declaration_statuses"] = {"ZHIXING_LIVE_CHAT_CONCURRENCY_STATUS": "blocked"}
        return report

    registration = report["registration"]
    if register_probe_user:
        registration = _pre_register_probe_user(
            base_url=normalized_base_url,
            username=probe_username,
            password=probe_password,
            email=probe_email,
            timeout_seconds=timeout_seconds,
        )
        report["registration"] = registration
        blocked_reasons.extend(registration.get("blocked_reasons") or [])
        if blocked_reasons:
            report["blocked_reasons"] = blocked_reasons
            report["degraded_reasons"] = []
            report["declaration_statuses"] = {"ZHIXING_LIVE_CHAT_CONCURRENCY_STATUS": "blocked"}
            return report

    def run_one(index: int) -> Mapping[str, Any]:
        if probe_runner is not None:
            return probe_runner(index)
        return build_live_chat_probe_report(
            base_url=normalized_base_url,
            access_token=token or None,
            username=probe_username or None,
            password=probe_password or None,
            register_probe_user=False,
            prompt=prompt,
            conversation_title=f"{conversation_title} #{index}",
            execute=True,
            timeout_seconds=timeout_seconds,
            max_first_event_seconds=max_first_event_seconds,
            max_first_token_seconds=max_first_token_seconds,
            max_total_seconds=max_total_seconds,
            environ=env,
        )

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(run_one, index): index for index in range(1, request_count + 1)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                probe_report = future.result()
            except Exception as exc:  # pragma: no cover - defensive wrapper for live execution
                probe_report = {
                    "status": "blocked",
                    "observations": {},
                    "blocked_reasons": [{"key": exc.__class__.__name__, "finding": "Probe worker failed before producing a report."}],
                    "degraded_reasons": [],
                }
            results.append(_probe_result_summary(index, probe_report))
    results.sort(key=lambda item: int(item.get("index") or 0))

    counts = _status_counts(results)
    blocked_count = int(counts.get("blocked", 0))
    degraded_count = int(counts.get("degraded", 0))
    passed_count = int(counts.get("passed", 0))
    blocked_rate = blocked_count / request_count if request_count else 1.0
    first_event_values = [
        value
        for value in (_as_float(item.get("first_event_seconds")) for item in results)
        if value is not None
    ]
    first_token_values = [
        value
        for value in (_as_float(item.get("first_token_seconds")) for item in results)
        if value is not None
    ]
    total_values = [
        value
        for value in (_as_float(item.get("total_seconds")) for item in results)
        if value is not None
    ]
    p95_total_seconds = _percentile(total_values, 95)
    degraded_reasons: list[dict[str, str]] = []
    if blocked_count and blocked_rate <= max_blocked_rate:
        degraded_reasons.append({"key": "sample_blocked_under_threshold", "finding": "Some chat samples were blocked, but the blocked rate stayed within the configured threshold."})
    if degraded_count:
        degraded_reasons.append({"key": "sample_degraded", "finding": "At least one chat sample exceeded a latency threshold or missed token events."})
    if p95_total_seconds is not None and p95_total_seconds > max_p95_total_seconds:
        degraded_reasons.append({"key": "p95_total_latency", "finding": "P95 total chat latency exceeded the configured threshold."})
    if passed_count + degraded_count <= 0:
        blocked_reasons.append({"key": "no_successful_samples", "finding": "No passed or degraded chat sample completed."})
    if blocked_rate > max_blocked_rate:
        blocked_reasons.append({"key": "blocked_rate", "finding": "Blocked chat sample rate exceeded the configured threshold."})

    status = "blocked" if blocked_reasons else ("degraded" if degraded_reasons else "passed")
    report.update(
        {
            "status": status,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "observations": {
                "request_count": request_count,
                "concurrency": concurrency,
                "passed_count": passed_count,
                "degraded_count": degraded_count,
                "blocked_count": blocked_count,
                "blocked_rate": round(blocked_rate, 4),
                "stream_completed_count": sum(1 for item in results if item.get("stream_completed") is True),
                "event_count_sum": sum(int(item.get("event_count") or 0) for item in results),
                "assistant_chars_observed_sum": sum(int(item.get("assistant_chars_observed") or 0) for item in results),
                "first_event_seconds": {
                    "p50": _percentile(first_event_values, 50),
                    "p95": _percentile(first_event_values, 95),
                },
                "first_token_seconds": {
                    "p50": _percentile(first_token_values, 50),
                    "p95": _percentile(first_token_values, 95),
                },
                "total_seconds": {
                    "p50": _percentile(total_values, 50),
                    "p95": p95_total_seconds,
                    "max": round(max(total_values), 3) if total_values else None,
                },
                "status_counts": counts,
                "public_url_echoed": False,
                "credentials_echoed": False,
                "prompt_echoed": False,
                "assistant_text_echoed": False,
                "response_body_echoed": False,
            },
            "probe_results": results,
            "blocked_reasons": blocked_reasons,
            "degraded_reasons": degraded_reasons,
            "declaration_statuses": {"ZHIXING_LIVE_CHAT_CONCURRENCY_STATUS": status},
        }
    )
    return report


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_live_chat_concurrency_probe_markdown(report: Mapping[str, Any]) -> str:
    observations = _as_mapping(report.get("observations"))
    total = _as_mapping(observations.get("total_seconds"))
    first_event = _as_mapping(observations.get("first_event_seconds"))
    first_token = _as_mapping(observations.get("first_token_seconds"))
    lines = [
        "# Live Chat Concurrency Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: public URL, credentials, prompt, conversation ids, assistant text and response bodies are not echoed.",
        "- This is a tiny bounded M1 sample, not a load test.",
        "",
        "## Observations",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Request count | `{_markdown_cell(observations.get('request_count'))}` |",
        f"| Concurrency | `{_markdown_cell(observations.get('concurrency'))}` |",
        f"| Passed / degraded / blocked | `{_markdown_cell(observations.get('passed_count'))}` / `{_markdown_cell(observations.get('degraded_count'))}` / `{_markdown_cell(observations.get('blocked_count'))}` |",
        f"| Blocked rate | `{_markdown_cell(observations.get('blocked_rate'))}` |",
        f"| Stream completed count | `{_markdown_cell(observations.get('stream_completed_count'))}` |",
        f"| First event p95 seconds | `{_markdown_cell(first_event.get('p95'))}` |",
        f"| First token p95 seconds | `{_markdown_cell(first_token.get('p95'))}` |",
        f"| Total p95 seconds | `{_markdown_cell(total.get('p95'))}` |",
        f"| Total max seconds | `{_markdown_cell(total.get('max'))}` |",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            if isinstance(item, Mapping):
                lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Sample Results", ""])
    lines.extend([
        "| # | Status | Stream done | Events | First token s | Total s | Blocked keys | Degraded keys |",
        "|---:|---|---|---:|---:|---:|---|---|",
    ])
    for item in report.get("probe_results") or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('index'))} | "
            f"`{_markdown_cell(item.get('status'))}` | "
            f"`{_markdown_cell(item.get('stream_completed'))}` | "
            f"{_markdown_cell(item.get('event_count'))} | "
            f"{_markdown_cell(item.get('first_token_seconds'))} | "
            f"{_markdown_cell(item.get('total_seconds'))} | "
            f"{_markdown_cell(','.join(item.get('blocked_reason_keys') or []))} | "
            f"{_markdown_cell(','.join(item.get('degraded_reason_keys') or []))} |"
        )
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_probe") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="", help="HTTP(S) base URL. Redacted from output.")
    parser.add_argument("--approval-json", type=_path_arg, default=None, help="Redacted approval report JSON from check_live_chat_concurrency_probe_approval.py.")
    parser.add_argument("--report-json", type=_path_arg, default=None, help="Render an existing redacted probe report without executing live chat.")
    parser.add_argument("--access-token", default=None, help="Bearer token. Redacted from output; prefer --access-token-env.")
    parser.add_argument("--access-token-env", default=DEFAULT_ACCESS_TOKEN_ENV, help="Environment variable containing the bearer token.")
    parser.add_argument("--username", default=None, help="Probe username. Redacted from output; prefer --username-env.")
    parser.add_argument("--username-env", default=DEFAULT_USERNAME_ENV, help="Environment variable containing the probe username.")
    parser.add_argument("--password", default=None, help="Probe password. Redacted from output; prefer --password-env.")
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV, help="Environment variable containing the probe password.")
    parser.add_argument("--email", default=None, help="Probe email for optional registration. Redacted from output; prefer --email-env.")
    parser.add_argument("--email-env", default=DEFAULT_EMAIL_ENV, help="Environment variable containing the probe email.")
    parser.add_argument("--register-probe-user", action="store_true", help="Register the probe user once before chat when needed. Writes a runtime test user record.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Probe prompt. Not echoed in output.")
    parser.add_argument("--conversation-title", default=DEFAULT_CONVERSATION_TITLE)
    parser.add_argument("--execute", action="store_true", help="Actually create conversations and run chat SSE turns.")
    parser.add_argument("--request-count", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-first-event-seconds", type=float, default=30.0)
    parser.add_argument("--max-first-token-seconds", type=float, default=75.0)
    parser.add_argument("--max-total-seconds", type=float, default=120.0)
    parser.add_argument("--max-p95-total-seconds", type=float, default=120.0)
    parser.add_argument("--max-blocked-rate", type=float, default=0.34)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.report_json is not None:
        report, report_error = _read_json_file(args.report_json, label="probe_report")
        if report_error is not None:
            report = {
                "version": LIVE_CHAT_CONCURRENCY_PROBE_VERSION,
                "status": "blocked",
                "blocked_reasons": [report_error],
                "degraded_reasons": [],
            }
        output_text = (
            build_live_chat_concurrency_probe_markdown(report)
            if args.markdown
            else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        if args.output is None:
            print(output_text, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output_text, encoding="utf-8")
        return 2 if report["status"] == "blocked" else 0

    approval_report, approval_error = _read_json_file(args.approval_json, label="approval_report") if args.execute else (None, None)
    if approval_error is not None:
        approval_report = {
            "version": "",
            "status": "blocked",
            "decision": "not_ready_for_live_chat_concurrency_probe",
            "approved_limits": {},
            "blocked_reasons": [approval_error],
        }
    report = build_live_chat_concurrency_probe_report(
        base_url=args.base_url,
        approval_report=approval_report,
        access_token=args.access_token,
        access_token_env=args.access_token_env,
        username=args.username,
        username_env=args.username_env,
        password=args.password,
        password_env=args.password_env,
        email=args.email,
        email_env=args.email_env,
        register_probe_user=args.register_probe_user,
        prompt=args.prompt,
        conversation_title=args.conversation_title,
        execute=args.execute,
        request_count=args.request_count,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout_seconds,
        max_first_event_seconds=args.max_first_event_seconds,
        max_first_token_seconds=args.max_first_token_seconds,
        max_total_seconds=args.max_total_seconds,
        max_p95_total_seconds=args.max_p95_total_seconds,
        max_blocked_rate=args.max_blocked_rate,
    )
    if approval_error is not None:
        report.setdefault("blocked_reasons", []).append(approval_error)
        report["status"] = "blocked"
    output_text = (
        build_live_chat_concurrency_probe_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is None:
        print(output_text, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
