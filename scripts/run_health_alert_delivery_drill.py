"""Run a redacted health/readiness alert delivery drill.

The drill emits synthetic M1 alert events after probing health endpoints. It
does not read .env files and does not print delivery target paths or URLs.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALERT_DELIVERY_DRILL_VERSION = "health_alert_delivery_drill.v1"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
ENDPOINTS = (
    ("health", "/health/live", "ZHIXING_HEALTH_ALERT_DELIVERY_STATUS"),
    ("readiness", "/health/ready", "ZHIXING_READINESS_ALERT_DELIVERY_STATUS"),
)


@dataclass(frozen=True)
class ProbeResult:
    label: str
    path: str
    status: str
    http_status: int | None
    finding: str


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _looks_local_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return host in LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local")


def _validate_base_url(base_url: str, *, allow_local_base_url: bool) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "base_url_echoed": False,
        "finding": "Base URL is usable for alert drill.",
    }
    if not base_url:
        return {**payload, "status": "blocked", "finding": "Missing base URL."}
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {**payload, "status": "blocked", "finding": "Base URL must be a full http(s) URL."}
    if _looks_local_url(base_url) and not allow_local_base_url:
        return {
            **payload,
            "status": "blocked",
            "finding": "Local base URL requires --allow-local-base-url.",
        }
    return payload


def _validate_sink_file(sink_file: str) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "sink_path_echoed": False,
        "finding": "Alert sink file is usable for drill output.",
    }
    if not sink_file:
        return {**payload, "status": "blocked", "finding": "Missing alert sink file path."}
    path = Path(sink_file)
    if not path.is_absolute():
        return {**payload, "status": "blocked", "finding": "Alert sink file must be an absolute path."}
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return payload
    return {**payload, "status": "blocked", "finding": "Alert sink file must stay outside the Git workspace."}


def _probe_endpoint(
    *,
    base_url: str,
    path: str,
    label: str,
    timeout_seconds: float,
    insecure_tls: bool,
) -> ProbeResult:
    url = base_url.rstrip("/") + path
    request = Request(url, headers={"User-Agent": "zhixing-health-alert-drill/1.0"})
    context = None
    if insecure_tls and urlparse(url).scheme == "https":
        import ssl

        context = ssl._create_unverified_context()  # noqa: S323 - explicit drill option.
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:  # noqa: S310
            status_code = int(response.status)
    except HTTPError as exc:
        status_code = int(exc.code)
    except (OSError, TimeoutError, URLError, socket.timeout) as exc:
        return ProbeResult(
            label=label,
            path=path,
            status="blocked",
            http_status=None,
            finding=f"Probe failed: {exc.__class__.__name__}.",
        )
    if 200 <= status_code < 400:
        return ProbeResult(
            label=label,
            path=path,
            status="passed",
            http_status=status_code,
            finding="Endpoint responded successfully.",
        )
    return ProbeResult(
        label=label,
        path=path,
        status="degraded",
        http_status=status_code,
        finding=f"Endpoint returned HTTP {status_code}; alert event was still generated.",
    )


def _event_for_probe(probe: ProbeResult, *, env_var: str) -> dict[str, Any]:
    return {
        "event_id": "m1-alert-drill-" + uuid4().hex,
        "version": ALERT_DELIVERY_DRILL_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "severity": "test",
        "alert_type": f"{probe.label}_alert_delivery_drill",
        "endpoint": probe.label,
        "endpoint_path": probe.path,
        "probe_status": probe.status,
        "http_status": probe.http_status,
        "finding": probe.finding,
        "declaration_env_var": env_var,
        "demo_boundary": "M1 alert delivery drill only; no real payment, booking, inventory lock, ticketing, or fulfillment.",
    }


def _write_file_sink(*, sink_file: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    path = Path(sink_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        return {
            "status": "blocked",
            "sink_path_echoed": False,
            "delivered_events": 0,
            "finding": f"Alert sink write failed: {exc.__class__.__name__}.",
        }
    return {
        "status": "passed",
        "sink_path_echoed": False,
        "delivered_events": len(events),
        "finding": "Synthetic alert events were written to the configured sink.",
    }


def build_health_alert_delivery_drill_report(
    *,
    environ: Mapping[str, str] | None = None,
    base_url: str | None = None,
    sink_file: str | None = None,
    allow_local_base_url: bool = False,
    insecure_tls: bool = False,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Run probes, deliver synthetic alerts, and return redacted evidence."""

    env = environ if environ is not None else os.environ
    resolved_base_url = (base_url or _value(env, "ZHIXING_PUBLIC_BASE_URL")).strip()
    resolved_sink_file = (sink_file or _value(env, "ZHIXING_ALERT_DRILL_SINK_FILE")).strip()
    base_url_check = _validate_base_url(
        resolved_base_url,
        allow_local_base_url=allow_local_base_url,
    )
    sink_file_check = _validate_sink_file(resolved_sink_file)
    blockers = [
        item
        for item in (base_url_check, sink_file_check)
        if item["status"] == "blocked"
    ]
    if blockers:
        return {
            "version": ALERT_DELIVERY_DRILL_VERSION,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "sends_webhook": False,
                "writes_alert_sink": False,
                "base_url_echoed": False,
                "sink_path_echoed": False,
                "allow_local_base_url": allow_local_base_url,
                "insecure_tls": insecure_tls,
            },
            "checks": {
                "base_url": base_url_check,
                "sink_file": sink_file_check,
            },
            "endpoint_probes": [],
            "delivery": {
                "status": "not_checked",
                "delivered_events": 0,
                "sink_path_echoed": False,
            },
            "declaration_statuses": {},
            "blocked_reasons": blockers,
        }

    probes: list[ProbeResult] = []
    events: list[dict[str, Any]] = []
    declaration_statuses: dict[str, str] = {}
    for label, path, env_var in ENDPOINTS:
        probe = _probe_endpoint(
            base_url=resolved_base_url,
            path=path,
            label=label,
            timeout_seconds=timeout_seconds,
            insecure_tls=insecure_tls,
        )
        probes.append(probe)
        events.append(_event_for_probe(probe, env_var=env_var))
        declaration_statuses[env_var] = "passed"

    delivery = _write_file_sink(sink_file=resolved_sink_file, events=events)
    probe_payloads = [
        {
            "endpoint": probe.label,
            "path": probe.path,
            "status": probe.status,
            "http_status": probe.http_status,
            "finding": probe.finding,
        }
        for probe in probes
    ]
    blocked_probes = [item for item in probe_payloads if item["status"] == "blocked"]
    if delivery["status"] == "blocked":
        status = "blocked"
    elif blocked_probes:
        status = "blocked"
    elif any(item["status"] == "degraded" for item in probe_payloads):
        status = "degraded"
    else:
        status = "passed"
    return {
        "version": ALERT_DELIVERY_DRILL_VERSION,
        "status": status,
        "policy": {
            "reads_dotenv": False,
            "sends_webhook": False,
            "writes_alert_sink": True,
            "base_url_echoed": False,
            "sink_path_echoed": False,
            "allow_local_base_url": allow_local_base_url,
            "insecure_tls": insecure_tls,
        },
        "checks": {
            "base_url": base_url_check,
            "sink_file": sink_file_check,
        },
        "endpoint_probes": probe_payloads,
        "delivery": delivery,
        "declaration_statuses": declaration_statuses if delivery["status"] == "passed" else {},
        "blocked_reasons": blocked_probes if blocked_probes else [],
        "not_proven_by_this_drill": [
            "File-sink delivery is an M1 drill, not a human paging or external IM notification.",
            "This drill does not prove long-term metric retention, escalation policy, or cost alerts.",
            "Use a real webhook, email, SMS, or cloud monitoring channel before M2 production traffic.",
        ],
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None, help="Base URL to probe. Falls back to ZHIXING_PUBLIC_BASE_URL.")
    parser.add_argument("--sink-file", default=None, help="Absolute alert drill sink file path. Falls back to ZHIXING_ALERT_DRILL_SINK_FILE.")
    parser.add_argument("--allow-local-base-url", action="store_true", help="Allow probing localhost from the target server.")
    parser.add_argument("--insecure-tls", action="store_true", help="Skip TLS certificate verification for the drill probe.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout per health probe.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON for automation.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_health_alert_delivery_drill_report(
        base_url=args.base_url,
        sink_file=args.sink_file,
        allow_local_base_url=args.allow_local_base_url,
        insecure_tls=args.insecure_tls,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
