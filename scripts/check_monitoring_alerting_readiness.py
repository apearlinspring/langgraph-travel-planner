"""Check monitoring, alerting, and cost readiness without reading .env files."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


MONITORING_ALERTING_READINESS_VERSION = "monitoring_alerting_readiness.v1"
PLACEHOLDER_PREFIXES = ("todo", "your-", "example", "change-me", "placeholder", "<", "${")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
HEALTH_ENDPOINTS = (
    ("health/live", "/health/live"),
    ("health/ready", "/health/ready"),
)


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"", "unknown", "tbd", "null", "none", "n/a"}:
        return True
    return any(lowered.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES)


def _check_present(
    *,
    env_var: str,
    value: str,
    label: str,
) -> dict[str, Any]:
    payload = {
        "key": env_var.lower(),
        "env_var": env_var,
        "label": label,
        "value_echoed": False,
    }
    if not value:
        return {**payload, "status": "blocked", "finding": "Missing required monitoring input."}
    if _looks_placeholder(value):
        return {
            **payload,
            "status": "blocked",
            "finding": "Monitoring input still looks like a placeholder.",
        }
    return {**payload, "status": "passed", "finding": "Declared."}


def _check_daily_budget(value: str) -> dict[str, Any]:
    payload = {
        "key": "zhixing_daily_cost_budget",
        "env_var": "ZHIXING_DAILY_COST_BUDGET",
        "label": "Daily cost budget",
        "value_echoed": False,
    }
    if not value or _looks_placeholder(value):
        return {**payload, "status": "blocked", "finding": "Daily cost budget is missing or placeholder-like."}
    if not any(char.isdigit() for char in value):
        return {
            **payload,
            "status": "blocked",
            "finding": "Daily cost budget must include a numeric budget.",
        }
    return {**payload, "status": "passed", "finding": "Daily cost budget is declared."}


def _public_base_url_check(value: str) -> dict[str, Any]:
    payload = {
        "key": "zhixing_public_base_url",
        "env_var": "ZHIXING_PUBLIC_BASE_URL",
        "label": "Public base URL",
        "value_echoed": False,
    }
    if not value or _looks_placeholder(value):
        return {**payload, "status": "blocked", "finding": "Public base URL is missing or placeholder-like."}

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return {
            **payload,
            "status": "blocked",
            "finding": "Public base URL must be a full http(s) URL.",
        }
    if host in LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local"):
        return {
            **payload,
            "status": "blocked",
            "finding": "Public base URL must not point to localhost.",
        }
    return {**payload, "status": "passed", "finding": "Public base URL is declared."}


def _probe_url(url: str, *, timeout_seconds: float) -> int:
    request = Request(url, headers={"User-Agent": "zhixing-monitoring-readiness/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - explicit readiness probe.
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except (OSError, TimeoutError, URLError) as exc:
        raise RuntimeError(exc.__class__.__name__) from exc


def _build_health_url(base_url: str, endpoint_path: str) -> str:
    return base_url.rstrip("/") + endpoint_path


def _health_probe(
    *,
    base_url: str,
    check: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_checked",
        "checked": check,
        "network_probe_requested": check,
        "base_url_env_var": "ZHIXING_PUBLIC_BASE_URL",
        "value_echoed": False,
        "endpoints": [],
        "finding": "Health URL probe not requested.",
    }
    if not check:
        return report

    base_check = _public_base_url_check(base_url)
    report["base_url_check"] = base_check
    if base_check["status"] == "blocked":
        report.update(
            {
                "status": "blocked",
                "finding": base_check["finding"],
            }
        )
        return report

    endpoint_reports: list[dict[str, Any]] = []
    for label, endpoint_path in HEALTH_ENDPOINTS:
        item: dict[str, Any] = {
            "endpoint": label,
            "value_echoed": False,
        }
        try:
            status_code = _probe_url(
                _build_health_url(base_url, endpoint_path),
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            item.update(
                {
                    "status": "blocked",
                    "finding": f"Health endpoint probe failed: {exc}",
                }
            )
        else:
            item["http_status"] = status_code
            if 200 <= status_code < 400:
                item.update({"status": "passed", "finding": "Endpoint responded successfully."})
            else:
                item.update(
                    {
                        "status": "blocked",
                        "finding": f"Endpoint returned HTTP {status_code}.",
                    }
                )
        endpoint_reports.append(item)

    blocked = [item for item in endpoint_reports if item["status"] == "blocked"]
    report.update(
        {
            "status": "blocked" if blocked else "passed",
            "endpoints": endpoint_reports,
            "finding": "Health endpoint probe failed." if blocked else "Health endpoints responded successfully.",
        }
    )
    return report


def build_monitoring_alerting_readiness_report(
    *,
    environ: Mapping[str, str] | None = None,
    check_health_url: bool = False,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Build a redacted monitoring/alerting readiness report."""

    env = environ if environ is not None else os.environ
    checks = [
        _check_present(
            env_var="ZHIXING_MONITORING_PROVIDER",
            value=_value(env, "ZHIXING_MONITORING_PROVIDER"),
            label="Monitoring provider",
        ),
        _check_present(
            env_var="ZHIXING_ALERT_CHANNEL",
            value=_value(env, "ZHIXING_ALERT_CHANNEL"),
            label="Alert channel",
        ),
        _check_daily_budget(_value(env, "ZHIXING_DAILY_COST_BUDGET")),
    ]
    health_probe = _health_probe(
        base_url=_value(env, "ZHIXING_PUBLIC_BASE_URL"),
        check=check_health_url,
        timeout_seconds=timeout_seconds,
    )

    blocked = [item for item in checks if item["status"] == "blocked"]
    if health_probe["status"] == "blocked":
        blocked.append(
            {
                "key": "health_probe",
                "env_var": "ZHIXING_PUBLIC_BASE_URL",
                "label": "Public health endpoint probe",
                "status": "blocked",
                "finding": health_probe["finding"],
                "value_echoed": False,
            }
        )

    return {
        "version": MONITORING_ALERTING_READINESS_VERSION,
        "status": "blocked" if blocked else "passed",
        "policy": {
            "reads_dotenv": False,
            "network_probe_requested": check_health_url,
            "does_not_echo_values": True,
        },
        "checks": checks,
        "health_probe": health_probe,
        "blocked_reasons": blocked,
        "not_proven_by_this_check": [
            "Monitoring metrics are actually scraped and retained.",
            "Alerts have actually been delivered to the configured channel.",
            "P95 latency, error rate, tool failure rate, and cost dashboards are complete.",
            "Provider-side budget caps or quota enforcement are active.",
            "The target server has deployed the current release.",
        ],
    }


def _render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "# Monitoring / Alerting Readiness",
        f"- Overall: {report['status']}",
        "- Policy: reads_dotenv=false, does_not_echo_values=true",
        "",
        "## Checks",
    ]
    for item in report.get("checks") or []:
        lines.append(f"- {item.get('env_var')}: {item.get('status')} ({item.get('finding')})")
    health_probe = report.get("health_probe") or {}
    lines.extend(
        [
            "",
            "## Health Probe",
            f"- status: {health_probe.get('status')}",
            f"- checked: {health_probe.get('checked')}",
        ]
    )
    for item in health_probe.get("endpoints") or []:
        code = item.get("http_status", "n/a")
        lines.append(f"- {item.get('endpoint')}: {item.get('status')} (HTTP {code})")
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked"])
        for item in report["blocked_reasons"]:
            lines.append(f"- {item.get('env_var')}: {item.get('finding')}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--check-health-url", action="store_true", help="Probe /health/live and /health/ready on ZHIXING_PUBLIC_BASE_URL.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout for each optional health URL probe.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_monitoring_alerting_readiness_report(
        check_health_url=args.check_health_url,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render_human(report))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
