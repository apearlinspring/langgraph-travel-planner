"""Collect redacted live chat SSE probe evidence.

The default mode is plan-only. Passing ``--execute`` performs one authenticated
conversation creation plus one chat SSE turn, which may call the configured LLM
or external provider APIs and may write runtime conversation/message records.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
import sys
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


LIVE_CHAT_PROBE_VERSION = "live_chat_probe.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
CONVERSATION_ID_PLACEHOLDER = "<conversation-id>"
DEFAULT_ACCESS_TOKEN_ENV = "ZHIXING_PROBE_ACCESS_TOKEN"
DEFAULT_USERNAME_ENV = "ZHIXING_PROBE_USERNAME"
DEFAULT_PASSWORD_ENV = "ZHIXING_PROBE_PASSWORD"
DEFAULT_EMAIL_ENV = "ZHIXING_PROBE_EMAIL"
DEFAULT_PROMPT = (
    "M1 live chat probe: please confirm receipt in one short sentence. "
    "Do not query real payment, booking, inventory lock, ticketing or fulfillment."
)
DEFAULT_CONVERSATION_TITLE = "M1 live chat probe"


class ChatProbeClient(Protocol):
    def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        ...

    def stream_json_events(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None,
        timeout_seconds: float,
    ) -> Iterable[Mapping[str, Any]]:
        ...


@dataclass(frozen=True)
class ChatProbeThresholds:
    max_first_event_seconds: float = 20.0
    max_first_token_seconds: float = 45.0
    max_total_seconds: float = 90.0


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be absolute HTTP(S)")
    return value.rstrip("/")


def parse_sse_event_line(line: bytes | str) -> dict[str, Any] | None:
    text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
    text = text.strip()
    if not text.startswith("data:"):
        return None
    payload = text.removeprefix("data:").strip()
    if not payload:
        return None
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else None


class StdlibChatProbeClient:
    """Small stdlib HTTP client for the live chat probe."""

    def __init__(self, base_url: str):
        self.base_url = _normalize_base_url(base_url)

    def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None = None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        request = self._request(path, payload, token=token)
        with urlopen(request, timeout=timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, Mapping):
            raise RuntimeError("JSON response is not an object")
        return parsed

    def stream_json_events(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None,
        timeout_seconds: float,
    ) -> Iterable[Mapping[str, Any]]:
        request = self._request(path, payload, token=token)
        with urlopen(request, timeout=timeout_seconds) as response:
            for line in response:
                event = parse_sse_event_line(line)
                if event is not None:
                    yield event

    def _request(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None,
    ) -> Request:
        if not path.startswith("/") or "://" in path:
            raise ValueError("path must be an absolute relative path")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "zhixing-live-chat-probe/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return Request(
            f"{self.base_url}{path}",
            data=json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )


def _secret_from_inputs(
    *,
    value: str | None,
    env_name: str,
    environ: Mapping[str, str],
) -> tuple[str, str]:
    if value:
        return value, "argument"
    normalized_env_name = str(env_name or "").strip()
    if normalized_env_name:
        env_value = str(environ.get(normalized_env_name) or "").strip()
        if env_value:
            return env_value, "environment"
    return "", "missing"


def _base_report(
    *,
    base_url: str,
    execute: bool,
    access_token_source: str,
    access_token_present: bool,
    username_source: str,
    username_present: bool,
    password_source: str,
    password_present: bool,
    email_source: str,
    email_present: bool,
    register_probe_user: bool,
    thresholds: ChatProbeThresholds,
) -> dict[str, Any]:
    auth_strategy = "bearer_token" if access_token_present else (
        "probe_login" if username_present and password_present else "missing"
    )
    return {
        "version": LIVE_CHAT_PROBE_VERSION,
        "status": "blocked" if execute else "not_checked",
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "requires_execute_flag": True,
            "execute_requested": execute,
            "register_probe_user_requested": register_probe_user,
            "http_methods": ["POST"],
            "reads_dotenv": False,
            "parses_response_events_for_metrics": execute,
            "records_response_body": False,
            "records_credentials": False,
            "records_prompt": False,
            "records_assistant_text": False,
            "calls_llm": execute,
            "calls_external_provider_apis": execute,
            "creates_probe_conversation": execute,
            "creates_probe_user": bool(execute and register_probe_user),
            "writes_runtime_user_record": bool(execute and register_probe_user),
            "writes_runtime_messages": execute,
            "creates_real_payment": False,
            "creates_real_booking": False,
            "locks_inventory": False,
            "triggers_ticketing": False,
            "triggers_fulfillment": False,
            "access_token_echoed": False,
            "username_echoed": False,
            "password_echoed": False,
            "email_echoed": False,
            "public_base_url_echoed": False,
            "conversation_id_echoed": False,
        },
        "target": {
            "base_url": PUBLIC_URL_PLACEHOLDER if base_url else "",
            "base_url_present": bool(base_url),
            "base_url_echoed": False,
            "register_endpoint": "/api/v1/users/register",
            "conversation_endpoint": "/api/v1/conversations",
            "chat_stream_endpoint": "/api/v1/chat/stream/<conversation-id>",
            "auth_strategy": auth_strategy,
            "access_token_source": access_token_source,
            "access_token_present": access_token_present,
            "access_token_echoed": False,
            "username_source": username_source,
            "username_present": username_present,
            "username_echoed": False,
            "password_source": password_source,
            "password_present": password_present,
            "password_echoed": False,
            "email_source": email_source,
            "email_present": email_present,
            "email_echoed": False,
        },
        "thresholds": {
            "max_first_event_seconds": thresholds.max_first_event_seconds,
            "max_first_token_seconds": thresholds.max_first_token_seconds,
            "max_total_seconds": thresholds.max_total_seconds,
        },
        "not_proven_by_this_probe": [
            "Plan-only mode proves no live chat result.",
            "A passed result proves only one authenticated SSE chat turn in the sampled window.",
            "It does not prove high-concurrency chat throughput, autoscaling, long-duration soak stability or formal SLO compliance.",
            "It does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
            "It does not prove that current local code is deployed to the target server.",
            "It does not store or echo the public URL, access token, probe credentials, probe email, prompt, conversation id or assistant text.",
        ],
    }


def _status_from_exception(exc: BaseException) -> tuple[str, dict[str, str]]:
    if isinstance(exc, HTTPError):
        if exc.code in {401, 403}:
            return "blocked", {
                "key": "auth_failed",
                "finding": "Authenticated chat probe was rejected.",
            }
        if exc.code == 404:
            return "blocked", {
                "key": "endpoint_not_found",
                "finding": "Chat probe endpoint was not found.",
            }
        if exc.code == 429:
            return "blocked", {
                "key": "rate_limited",
                "finding": "Chat probe was rate limited before a successful turn.",
            }
        return "blocked", {
            "key": "http_error",
            "finding": f"Chat probe returned HTTP {exc.code}.",
        }
    if isinstance(exc, TimeoutError):
        return "blocked", {
            "key": "timeout",
            "finding": "Chat probe timed out before completion.",
        }
    if isinstance(exc, URLError):
        return "blocked", {
            "key": "network_error",
            "finding": "Chat probe could not reach the target.",
        }
    return "blocked", {
        "key": exc.__class__.__name__,
        "finding": "Chat probe failed before completion.",
    }


def _event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or "unknown")


def build_live_chat_probe_report(
    *,
    base_url: str,
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
    timeout_seconds: float = 90.0,
    max_first_event_seconds: float = 20.0,
    max_first_token_seconds: float = 45.0,
    max_total_seconds: float = 90.0,
    environ: Mapping[str, str] | None = None,
    client: ChatProbeClient | None = None,
) -> dict[str, Any]:
    """Build redacted evidence for one live chat SSE turn."""

    env = environ if environ is not None else os.environ
    token, token_source = _secret_from_inputs(
        value=access_token,
        env_name=access_token_env,
        environ=env,
    )
    probe_username, username_source = _secret_from_inputs(
        value=username,
        env_name=username_env,
        environ=env,
    )
    probe_password, password_source = _secret_from_inputs(
        value=password,
        env_name=password_env,
        environ=env,
    )
    probe_email, email_source = _secret_from_inputs(
        value=email,
        env_name=email_env,
        environ=env,
    )
    thresholds = ChatProbeThresholds(
        max_first_event_seconds=max_first_event_seconds,
        max_first_token_seconds=max_first_token_seconds,
        max_total_seconds=max_total_seconds,
    )
    report = _base_report(
        base_url=base_url,
        execute=execute,
        access_token_source=token_source,
        access_token_present=bool(token),
        username_source=username_source,
        username_present=bool(probe_username),
        password_source=password_source,
        password_present=bool(probe_password),
        email_source=email_source,
        email_present=bool(probe_email),
        register_probe_user=register_probe_user,
        thresholds=thresholds,
    )
    if not execute:
        report["plan"] = {
            "command": (
                "python scripts/collect_live_chat_probe.py --base-url <public-url> "
                "--access-token-env ZHIXING_PROBE_ACCESS_TOKEN --execute --markdown"
            ),
            "alternative_command": (
                "python scripts/collect_live_chat_probe.py --base-url <public-url> "
                "--username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD "
                "--execute --markdown"
            ),
            "registration_command": (
                "python scripts/collect_live_chat_probe.py --base-url <public-url> "
                "--username-env ZHIXING_PROBE_USERNAME --password-env ZHIXING_PROBE_PASSWORD "
                "--email-env ZHIXING_PROBE_EMAIL --register-probe-user --execute --markdown"
            ),
            "requires_private_auth": True,
            "supports_private_access_token": True,
            "supports_probe_login": True,
            "supports_probe_registration": True,
            "probe_registration_requires_execute_flag": True,
            "may_call_llm_or_external_apis": True,
            "may_write_runtime_conversation_records": True,
            "may_write_runtime_user_record_when_registration_enabled": True,
        }
        return report

    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError:
        report["blocked_reasons"] = [
            {"key": "invalid_target", "finding": "Base URL must be absolute HTTP(S)."}
        ]
        return report
    has_login_credentials = bool(probe_username and probe_password)
    has_registration_inputs = bool(probe_username and probe_password and probe_email)
    if not token and not has_login_credentials:
        report["blocked_reasons"] = [
            {
                "key": "missing_auth_credentials",
                "finding": "An access token or probe username/password is required for chat probe execution.",
            }
        ]
        return report
    if register_probe_user and not token and not has_registration_inputs:
        report["blocked_reasons"] = [
            {
                "key": "missing_probe_registration_inputs",
                "finding": "Probe username, password and email are required when --register-probe-user is used.",
            }
        ]
        return report
    if timeout_seconds <= 0:
        report["blocked_reasons"] = [
            {"key": "invalid_timeout", "finding": "Timeout seconds must be positive."}
        ]
        return report

    http_client = client or StdlibChatProbeClient(normalized_base_url)
    started = time.perf_counter()
    event_counts: dict[str, int] = {}
    first_event_seconds: float | None = None
    first_token_seconds: float | None = None
    assistant_chars_observed = 0
    completed = False
    blocked_reasons: list[dict[str, str]] = []
    degraded_reasons: list[dict[str, str]] = []
    conversation_created = False
    login_performed = False
    registration_attempted = False
    registration_performed = False
    existing_probe_user_reused = False

    try:
        if not token:
            if register_probe_user:
                registration_attempted = True
                try:
                    login_payload = http_client.post_json(
                        "/api/v1/users/register",
                        {
                            "username": probe_username,
                            "email": probe_email,
                            "password": probe_password,
                        },
                        token=None,
                        timeout_seconds=timeout_seconds,
                    )
                    registration_performed = True
                    report["target"]["access_token_source"] = "registration"
                except HTTPError as exc:
                    if exc.code != 400:
                        raise
                    existing_probe_user_reused = True
                    login_payload = http_client.post_json(
                        "/api/v1/users/login",
                        {"username": probe_username, "password": probe_password},
                        token=None,
                        timeout_seconds=timeout_seconds,
                    )
                    login_performed = True
                    report["target"]["access_token_source"] = "login_after_registration_conflict"
            else:
                login_payload = http_client.post_json(
                    "/api/v1/users/login",
                    {"username": probe_username, "password": probe_password},
                    token=None,
                    timeout_seconds=timeout_seconds,
                )
                login_performed = True
                report["target"]["access_token_source"] = "login"
            token = str(login_payload.get("access_token") or "").strip()
            if not token:
                report["blocked_reasons"] = [
                    {
                        "key": "login_token_missing",
                        "finding": "Login response did not contain an access token.",
                    }
                ]
                return report
            report["target"]["access_token_present"] = True
            report["target"]["auth_strategy"] = "probe_login"
        conversation = http_client.post_json(
            "/api/v1/conversations",
            {"title": conversation_title},
            token=token,
            timeout_seconds=timeout_seconds,
        )
        conversation_id = str(conversation.get("id") or "").strip()
        if not conversation_id:
            report["blocked_reasons"] = [
                {
                    "key": "conversation_id_missing",
                    "finding": "Conversation creation response did not contain an id.",
                }
            ]
            return report
        conversation_created = True
        for event in http_client.stream_json_events(
            f"/api/v1/chat/stream/{conversation_id}",
            {"content": prompt},
            token=token,
            timeout_seconds=min(timeout_seconds, max_total_seconds),
        ):
            elapsed = time.perf_counter() - started
            event_kind = _event_type(event)
            event_counts[event_kind] = event_counts.get(event_kind, 0) + 1
            if first_event_seconds is None:
                first_event_seconds = elapsed
            if event_kind == "token":
                if first_token_seconds is None:
                    first_token_seconds = elapsed
                content = event.get("content")
                if isinstance(content, str):
                    assistant_chars_observed += len(content)
            elif event_kind == "session_busy":
                blocked_reasons.append(
                    {
                        "key": "session_busy",
                        "finding": "Conversation lock was busy during the probe.",
                    }
                )
            elif event_kind == "error":
                blocked_reasons.append(
                    {"key": "sse_error", "finding": "Chat stream emitted an error event."}
                )
            elif event_kind == "done":
                completed = True
                break
            if elapsed > max_total_seconds:
                blocked_reasons.append(
                    {
                        "key": "max_total_seconds",
                        "finding": "Chat probe exceeded the configured total duration.",
                    }
                )
                break
    except (HTTPError, TimeoutError, URLError, OSError, RuntimeError, ValueError) as exc:
        _, reason = _status_from_exception(exc)
        blocked_reasons.append(reason)

    total_seconds = time.perf_counter() - started
    if not conversation_created and not blocked_reasons:
        blocked_reasons.append(
            {"key": "conversation_not_created", "finding": "Probe conversation was not created."}
        )
    if not completed and not blocked_reasons:
        blocked_reasons.append(
            {"key": "stream_not_completed", "finding": "Chat stream did not emit a done event."}
        )
    if completed and first_event_seconds is None:
        blocked_reasons.append(
            {"key": "no_sse_events", "finding": "Chat stream completed without observable SSE events."}
        )
    if completed and first_token_seconds is None:
        degraded_reasons.append(
            {
                "key": "no_token_event",
                "finding": "Chat stream completed but no token event was observed.",
            }
        )
    if first_event_seconds is not None and first_event_seconds > max_first_event_seconds:
        degraded_reasons.append(
            {
                "key": "first_event_latency",
                "finding": "First SSE event latency exceeded the configured threshold.",
            }
        )
    if first_token_seconds is not None and first_token_seconds > max_first_token_seconds:
        degraded_reasons.append(
            {
                "key": "first_token_latency",
                "finding": "First token latency exceeded the configured threshold.",
            }
        )
    if total_seconds > max_total_seconds:
        degraded_reasons.append(
            {
                "key": "total_latency",
                "finding": "Total chat probe latency exceeded the configured threshold.",
            }
        )

    status = "blocked" if blocked_reasons else ("degraded" if degraded_reasons else "passed")
    report.update(
        {
            "status": status,
            "observations": {
                "registration_requested": register_probe_user,
                "registration_attempted": registration_attempted,
                "registration_performed": registration_performed,
                "existing_probe_user_reused": existing_probe_user_reused,
                "conversation_created": conversation_created,
                "login_performed": login_performed,
                "conversation_id": CONVERSATION_ID_PLACEHOLDER if conversation_created else "",
                "conversation_id_echoed": False,
                "stream_completed": completed,
                "event_count": sum(event_counts.values()),
                "event_type_counts": dict(sorted(event_counts.items())),
                "first_event_seconds": round(first_event_seconds, 3)
                if first_event_seconds is not None
                else None,
                "first_token_seconds": round(first_token_seconds, 3)
                if first_token_seconds is not None
                else None,
                "total_seconds": round(total_seconds, 3),
                "assistant_chars_observed": assistant_chars_observed,
                "prompt_echoed": False,
                "assistant_text_echoed": False,
                "response_body_echoed": False,
            },
            "blocked_reasons": blocked_reasons,
            "degraded_reasons": degraded_reasons,
            "declaration_statuses": {"ZHIXING_LIVE_CHAT_PROBE_STATUS": status},
        }
    )
    return report


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_live_chat_probe_markdown(report: Mapping[str, Any]) -> str:
    observations = report.get("observations") if isinstance(report.get("observations"), Mapping) else {}
    lines = [
        "# Live Chat Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: public URL, access token, probe credentials, prompt, conversation id and assistant text are not echoed.",
        "",
        "## Observations",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Executed | `{_markdown_cell((report.get('policy') or {}).get('execute_requested'))}` |",
        f"| Register probe user requested | `{_markdown_cell((report.get('policy') or {}).get('register_probe_user_requested'))}` |",
        f"| Registration attempted | `{_markdown_cell(observations.get('registration_attempted'))}` |",
        f"| Registration performed | `{_markdown_cell(observations.get('registration_performed'))}` |",
        f"| Existing probe user reused | `{_markdown_cell(observations.get('existing_probe_user_reused'))}` |",
        f"| Login performed | `{_markdown_cell(observations.get('login_performed'))}` |",
        f"| Conversation created | `{_markdown_cell(observations.get('conversation_created'))}` |",
        f"| Stream completed | `{_markdown_cell(observations.get('stream_completed'))}` |",
        f"| Event count | `{_markdown_cell(observations.get('event_count'))}` |",
        f"| First event seconds | `{_markdown_cell(observations.get('first_event_seconds'))}` |",
        f"| First token seconds | `{_markdown_cell(observations.get('first_token_seconds'))}` |",
        f"| Total seconds | `{_markdown_cell(observations.get('total_seconds'))}` |",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    if report.get("degraded_reasons"):
        lines.extend(["", "## Degraded Reasons", ""])
        for item in report.get("degraded_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_probe") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="HTTP(S) base URL. Redacted from output.")
    parser.add_argument("--access-token", default=None, help="Bearer token. Redacted from output; prefer --access-token-env.")
    parser.add_argument("--access-token-env", default=DEFAULT_ACCESS_TOKEN_ENV, help="Environment variable containing the bearer token.")
    parser.add_argument("--username", default=None, help="Probe username. Redacted from output; prefer --username-env.")
    parser.add_argument("--username-env", default=DEFAULT_USERNAME_ENV, help="Environment variable containing the probe username.")
    parser.add_argument("--password", default=None, help="Probe password. Redacted from output; prefer --password-env.")
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV, help="Environment variable containing the probe password.")
    parser.add_argument("--email", default=None, help="Probe email for optional registration. Redacted from output; prefer --email-env.")
    parser.add_argument("--email-env", default=DEFAULT_EMAIL_ENV, help="Environment variable containing the probe email.")
    parser.add_argument("--register-probe-user", action="store_true", help="Register the probe user before chat when needed. Writes a runtime test user record.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Probe prompt. Not echoed in output.")
    parser.add_argument("--conversation-title", default=DEFAULT_CONVERSATION_TITLE)
    parser.add_argument("--execute", action="store_true", help="Actually create a conversation and run one chat SSE turn.")
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-first-event-seconds", type=float, default=20.0)
    parser.add_argument("--max-first-token-seconds", type=float, default=45.0)
    parser.add_argument("--max-total-seconds", type=float, default=90.0)
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_live_chat_probe_report(
        base_url=args.base_url,
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
        timeout_seconds=args.timeout_seconds,
        max_first_event_seconds=args.max_first_event_seconds,
        max_first_token_seconds=args.max_first_token_seconds,
        max_total_seconds=args.max_total_seconds,
    )
    if args.markdown:
        print(build_live_chat_probe_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
