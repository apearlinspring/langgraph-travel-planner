"""Check redacted readiness of the M1 probe authentication path.

This script does not read `.env` files. It can either report whether probe
authentication inputs are present, or, with ``--execute-login``, verify the
token/login path against the target API without creating conversations or
calling the chat/LLM pipeline.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
import os
import sys
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROBE_AUTH_READINESS_VERSION = "probe_auth_readiness.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
DEFAULT_ACCESS_TOKEN_ENV = "ZHIXING_PROBE_ACCESS_TOKEN"
DEFAULT_USERNAME_ENV = "ZHIXING_PROBE_USERNAME"
DEFAULT_PASSWORD_ENV = "ZHIXING_PROBE_PASSWORD"


class ProbeAuthClient(Protocol):
    def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None = None,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        ...

    def get_json(
        self,
        path: str,
        *,
        token: str,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        ...


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be absolute HTTP(S)")
    return value.rstrip("/")


class StdlibProbeAuthClient:
    """Small stdlib HTTP client for probe auth checks."""

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
        request = self._request(path, method="POST", payload=payload, token=token)
        with urlopen(request, timeout=timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, Mapping):
            raise RuntimeError("JSON response is not an object")
        return parsed

    def get_json(
        self,
        path: str,
        *,
        token: str,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        request = self._request(path, method="GET", payload=None, token=token)
        with urlopen(request, timeout=timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, Mapping):
            raise RuntimeError("JSON response is not an object")
        return parsed

    def _request(
        self,
        path: str,
        *,
        method: str,
        payload: Mapping[str, Any] | None,
        token: str | None,
    ) -> Request:
        if not path.startswith("/") or "://" in path:
            raise ValueError("path must be an absolute relative path")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "zhixing-probe-auth-readiness/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None if payload is None else json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        return Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)


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


def _auth_strategy(*, token_present: bool, username_present: bool, password_present: bool) -> str:
    if token_present:
        return "bearer_token"
    if username_present and password_present:
        return "probe_login"
    if username_present or password_present:
        return "partial_probe_login"
    return "missing"


def _base_report(
    *,
    base_url: str,
    execute_login: bool,
    access_token_source: str,
    access_token_present: bool,
    username_source: str,
    username_present: bool,
    password_source: str,
    password_present: bool,
) -> dict[str, Any]:
    strategy = _auth_strategy(
        token_present=access_token_present,
        username_present=username_present,
        password_present=password_present,
    )
    status = "degraded" if strategy in {"bearer_token", "probe_login"} and not execute_login else "blocked"
    if execute_login:
        status = "blocked"
    return {
        "version": PROBE_AUTH_READINESS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "execute_login_requested": execute_login,
            "http_methods": ["POST", "GET"] if execute_login else [],
            "calls_chat": False,
            "calls_llm": False,
            "calls_external_provider_apis": False,
            "creates_conversation": False,
            "writes_runtime_messages": False,
            "creates_real_payment": False,
            "creates_real_booking": False,
            "locks_inventory": False,
            "records_credentials": False,
            "records_response_body": False,
            "public_base_url_echoed": False,
            "access_token_echoed": False,
            "username_echoed": False,
            "password_echoed": False,
        },
        "target": {
            "base_url": PUBLIC_URL_PLACEHOLDER if base_url else "",
            "base_url_present": bool(base_url),
            "base_url_echoed": False,
            "auth_strategy": strategy,
            "login_endpoint": "/api/v1/users/login",
            "me_endpoint": "/api/v1/users/me",
            "access_token_source": access_token_source,
            "access_token_present": access_token_present,
            "access_token_echoed": False,
            "username_source": username_source,
            "username_present": username_present,
            "username_echoed": False,
            "password_source": password_source,
            "password_present": password_present,
            "password_echoed": False,
        },
        "observations": {
            "login_performed": False,
            "me_checked": False,
            "token_validated": False,
            "user_id_present": False,
            "username_present_in_response": False,
            "response_body_echoed": False,
        },
        "not_proven_by_this_probe": [
            "A declared token or username/password pair is not proof that the target accepts it unless --execute-login is used.",
            "A passed auth check proves only that the probe account can authenticate and call /api/v1/users/me.",
            "It does not create a conversation, call the chat stream, call LLMs, call external travel providers, or prove chat throughput.",
            "It does not prove real payment, booking, inventory lock, ticketing or fulfillment.",
            "It does not store or echo the public URL, access token, username, password, user id or response body.",
        ],
    }


def _reason_from_exception(exc: BaseException) -> dict[str, str]:
    if isinstance(exc, HTTPError):
        if exc.code in {401, 403}:
            return {"key": "auth_failed", "finding": "Probe authentication was rejected."}
        if exc.code == 429:
            return {"key": "rate_limited", "finding": "Probe authentication was rate limited."}
        if exc.code == 404:
            return {"key": "endpoint_not_found", "finding": "Probe auth endpoint was not found."}
        return {"key": "http_error", "finding": f"Probe auth returned HTTP {exc.code}."}
    if isinstance(exc, TimeoutError):
        return {"key": "timeout", "finding": "Probe auth check timed out."}
    if isinstance(exc, URLError):
        return {"key": "network_error", "finding": "Probe auth check could not reach the target."}
    return {"key": exc.__class__.__name__, "finding": "Probe auth check failed."}


def build_probe_auth_readiness_report(
    *,
    base_url: str,
    access_token: str | None = None,
    access_token_env: str = DEFAULT_ACCESS_TOKEN_ENV,
    username: str | None = None,
    username_env: str = DEFAULT_USERNAME_ENV,
    password: str | None = None,
    password_env: str = DEFAULT_PASSWORD_ENV,
    execute_login: bool = False,
    timeout_seconds: float = 20.0,
    environ: Mapping[str, str] | None = None,
    client: ProbeAuthClient | None = None,
) -> dict[str, Any]:
    """Build redacted readiness evidence for the probe authentication path."""

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
    report = _base_report(
        base_url=base_url,
        execute_login=execute_login,
        access_token_source=token_source,
        access_token_present=bool(token),
        username_source=username_source,
        username_present=bool(probe_username),
        password_source=password_source,
        password_present=bool(probe_password),
    )
    strategy = str(report["target"]["auth_strategy"])
    if strategy in {"missing", "partial_probe_login"}:
        report["status"] = "blocked"
        report["blocked_reasons"] = [
            {
                "key": "missing_probe_auth",
                "finding": "Provide either a probe access token or both probe username and password.",
            }
        ]
        return report
    if not execute_login:
        report["degraded_reasons"] = [
            {
                "key": "auth_not_executed",
                "finding": "Probe auth inputs are present but not validated against the target.",
            }
        ]
        return report
    try:
        normalized_base_url = _normalize_base_url(base_url)
    except ValueError:
        report["status"] = "blocked"
        report["blocked_reasons"] = [
            {"key": "invalid_target", "finding": "Base URL must be absolute HTTP(S)."}
        ]
        return report
    if timeout_seconds <= 0:
        report["status"] = "blocked"
        report["blocked_reasons"] = [
            {"key": "invalid_timeout", "finding": "Timeout seconds must be positive."}
        ]
        return report

    http_client = client or StdlibProbeAuthClient(normalized_base_url)
    try:
        if not token:
            login_payload = http_client.post_json(
                "/api/v1/users/login",
                {"username": probe_username, "password": probe_password},
                token=None,
                timeout_seconds=timeout_seconds,
            )
            report["observations"]["login_performed"] = True
            token = str(login_payload.get("access_token") or "").strip()
            if not token:
                report["status"] = "blocked"
                report["blocked_reasons"] = [
                    {"key": "login_token_missing", "finding": "Login response did not contain an access token."}
                ]
                return report
            report["target"]["access_token_source"] = "login"
            report["target"]["access_token_present"] = True
        me_payload = http_client.get_json(
            "/api/v1/users/me",
            token=token,
            timeout_seconds=timeout_seconds,
        )
        report["observations"].update(
            {
                "me_checked": True,
                "token_validated": True,
                "user_id_present": bool(me_payload.get("id")),
                "username_present_in_response": bool(me_payload.get("username")),
            }
        )
        report["status"] = "passed"
        report["declaration_statuses"] = {"ZHIXING_PROBE_AUTH_STATUS": "passed"}
        return report
    except (HTTPError, TimeoutError, URLError, OSError, RuntimeError, ValueError) as exc:
        report["status"] = "blocked"
        report["blocked_reasons"] = [_reason_from_exception(exc)]
        report["declaration_statuses"] = {"ZHIXING_PROBE_AUTH_STATUS": "blocked"}
        return report


def _markdown_cell(value: Any) -> str:
    text = "-" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def build_probe_auth_readiness_markdown(report: Mapping[str, Any]) -> str:
    target = report.get("target") if isinstance(report.get("target"), Mapping) else {}
    observations = report.get("observations") if isinstance(report.get("observations"), Mapping) else {}
    lines = [
        "# Probe Auth Readiness Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: public URL, access token, username, password, user id and response body are not echoed.",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Auth strategy | `{_markdown_cell(target.get('auth_strategy'))}` |",
        f"| Execute login requested | `{_markdown_cell((report.get('policy') or {}).get('execute_login_requested'))}` |",
        f"| Login performed | `{_markdown_cell(observations.get('login_performed'))}` |",
        f"| /users/me checked | `{_markdown_cell(observations.get('me_checked'))}` |",
        f"| Token validated | `{_markdown_cell(observations.get('token_validated'))}` |",
        f"| User id present | `{_markdown_cell(observations.get('user_id_present'))}` |",
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
    parser.add_argument("--access-token-env", default=DEFAULT_ACCESS_TOKEN_ENV)
    parser.add_argument("--username", default=None, help="Probe username. Redacted from output; prefer --username-env.")
    parser.add_argument("--username-env", default=DEFAULT_USERNAME_ENV)
    parser.add_argument("--password", default=None, help="Probe password. Redacted from output; prefer --password-env.")
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    parser.add_argument("--execute-login", action="store_true", help="Actually verify token/login and /api/v1/users/me.")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--markdown", action="store_true")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_probe_auth_readiness_report(
        base_url=args.base_url,
        access_token=args.access_token,
        access_token_env=args.access_token_env,
        username=args.username,
        username_env=args.username_env,
        password=args.password,
        password_env=args.password_env,
        execute_login=args.execute_login,
        timeout_seconds=args.timeout_seconds,
    )
    if args.markdown:
        print(build_probe_auth_readiness_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
