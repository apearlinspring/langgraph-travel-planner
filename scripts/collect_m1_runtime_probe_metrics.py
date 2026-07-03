"""Collect redacted M1 health/readiness probe metrics.

This is a lightweight uptime probe for M1 operations. It measures health and
readiness endpoint latency/error rate only; it is not a full APM or chat-turn
latency monitor.
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
from time import perf_counter, sleep
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
M1_RUNTIME_PROBE_METRICS_VERSION = "m1_runtime_probe_metrics.v1"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
DEFAULT_ENDPOINTS = (
    ("live", "/health/live"),
    ("ready", "/health/ready"),
)


@dataclass(frozen=True)
class ProbeSample:
    endpoint: str
    status: str
    http_status: int | None
    latency_ms: float | None
    finding: str


def _value(environ: Mapping[str, str], key: str) -> str:
    return str(environ.get(key) or "").strip()


def _is_local_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return host in LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local")


def _validate_base_url(base_url: str, *, allow_local_base_url: bool) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "base_url_echoed": False,
        "finding": "Base URL is usable for M1 runtime probes.",
    }
    if not base_url:
        return {**payload, "status": "blocked", "finding": "Missing base URL."}
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {**payload, "status": "blocked", "finding": "Base URL must be a full http(s) URL."}
    if _is_local_url(base_url) and not allow_local_base_url:
        return {
            **payload,
            "status": "blocked",
            "finding": "Local base URL requires --allow-local-base-url.",
        }
    return payload


def _validate_output_path(path_text: str | None) -> dict[str, Any]:
    payload = {
        "status": "passed",
        "output_path_echoed": False,
        "finding": "Output path is usable.",
    }
    if not path_text:
        return {**payload, "status": "not_checked", "finding": "Output path not requested."}
    path = Path(path_text)
    if not path.is_absolute():
        return {**payload, "status": "blocked", "finding": "Output path must be absolute."}
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return payload
    return {**payload, "status": "blocked", "finding": "Output path must stay outside the Git workspace."}


def _probe_once(
    *,
    base_url: str,
    label: str,
    path: str,
    timeout_seconds: float,
    insecure_tls: bool,
) -> ProbeSample:
    url = base_url.rstrip("/") + path
    request = Request(url, headers={"User-Agent": "zhixing-m1-runtime-probe/1.0"})
    context = None
    if insecure_tls and urlparse(url).scheme == "https":
        import ssl

        context = ssl._create_unverified_context()  # noqa: S323 - explicit drill option.
    started_at = perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:  # noqa: S310
            status_code = int(response.status)
            response.read(2048)
    except HTTPError as exc:
        latency_ms = round((perf_counter() - started_at) * 1000, 2)
        return ProbeSample(
            endpoint=label,
            status="failed",
            http_status=int(exc.code),
            latency_ms=latency_ms,
            finding=f"Endpoint returned HTTP {int(exc.code)}.",
        )
    except (OSError, TimeoutError, URLError, socket.timeout) as exc:
        latency_ms = round((perf_counter() - started_at) * 1000, 2)
        return ProbeSample(
            endpoint=label,
            status="failed",
            http_status=None,
            latency_ms=latency_ms,
            finding=f"Probe failed: {exc.__class__.__name__}.",
        )
    latency_ms = round((perf_counter() - started_at) * 1000, 2)
    if 200 <= status_code < 400:
        return ProbeSample(
            endpoint=label,
            status="passed",
            http_status=status_code,
            latency_ms=latency_ms,
            finding="Endpoint responded successfully.",
        )
    return ProbeSample(
        endpoint=label,
        status="failed",
        http_status=status_code,
        latency_ms=latency_ms,
        finding=f"Endpoint returned HTTP {status_code}.",
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = max(1, int((percentile / 100.0) * len(ordered) + 0.999999))
    return round(ordered[min(rank, len(ordered)) - 1], 2)


def _endpoint_summary(samples: list[ProbeSample]) -> dict[str, Any]:
    count = len(samples)
    failed = [sample for sample in samples if sample.status != "passed"]
    latencies = [
        float(sample.latency_ms)
        for sample in samples
        if isinstance(sample.latency_ms, int | float)
    ]
    return {
        "sample_count": count,
        "success_count": count - len(failed),
        "failure_count": len(failed),
        "error_rate": round(len(failed) / count, 4) if count else 1.0,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
        },
        "http_status_counts": {
            str(status): sum(1 for sample in samples if sample.http_status == status)
            for status in sorted({sample.http_status for sample in samples if sample.http_status is not None})
        },
        "failures": [
            {
                "http_status": sample.http_status,
                "finding": sample.finding,
            }
            for sample in failed[:10]
        ],
    }


def _overall_status(
    summaries: Mapping[str, Mapping[str, Any]],
    *,
    max_error_rate: float,
    max_p95_ms: float,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    for endpoint, summary in summaries.items():
        error_rate = float(summary.get("error_rate") or 0)
        p95 = (summary.get("latency_ms") or {}).get("p95")
        if error_rate > max_error_rate:
            blockers.append(
                {
                    "endpoint": endpoint,
                    "metric": "error_rate",
                    "value": error_rate,
                    "threshold": max_error_rate,
                    "finding": "Endpoint error rate exceeded threshold.",
                }
            )
        if isinstance(p95, int | float) and p95 > max_p95_ms:
            degraded.append(
                {
                    "endpoint": endpoint,
                    "metric": "p95_latency_ms",
                    "value": p95,
                    "threshold": max_p95_ms,
                    "finding": "Endpoint P95 latency exceeded threshold.",
                }
            )
    if blockers:
        return "blocked", blockers, degraded
    if degraded:
        return "degraded", blockers, degraded
    return "passed", blockers, degraded


def build_m1_runtime_probe_metrics_report(
    *,
    environ: Mapping[str, str] | None = None,
    base_url: str | None = None,
    sample_count: int = 10,
    interval_seconds: float = 0.0,
    timeout_seconds: float = 5,
    max_error_rate: float = 0.0,
    max_p95_ms: float = 1000.0,
    allow_local_base_url: bool = False,
    insecure_tls: bool = False,
    probe_func: Any | None = None,
) -> dict[str, Any]:
    """Collect redacted endpoint probe metrics."""

    env = environ if environ is not None else os.environ
    resolved_base_url = (base_url or _value(env, "ZHIXING_PUBLIC_BASE_URL")).strip()
    base_url_check = _validate_base_url(
        resolved_base_url,
        allow_local_base_url=allow_local_base_url,
    )
    if sample_count <= 0:
        return {
            "version": M1_RUNTIME_PROBE_METRICS_VERSION,
            "status": "blocked",
            "policy": {"reads_dotenv": False, "base_url_echoed": False},
            "checks": {
                "base_url": base_url_check,
                "sample_count": {"status": "blocked", "finding": "Sample count must be positive."},
            },
            "blocked_reasons": [{"finding": "Sample count must be positive."}],
        }
    if base_url_check["status"] == "blocked":
        return {
            "version": M1_RUNTIME_PROBE_METRICS_VERSION,
            "status": "blocked",
            "policy": {"reads_dotenv": False, "base_url_echoed": False},
            "checks": {"base_url": base_url_check},
            "blocked_reasons": [base_url_check],
        }

    probe = probe_func or _probe_once
    samples_by_endpoint: dict[str, list[ProbeSample]] = {
        label: []
        for label, _path in DEFAULT_ENDPOINTS
    }
    for index in range(sample_count):
        for label, path in DEFAULT_ENDPOINTS:
            samples_by_endpoint[label].append(
                probe(
                    base_url=resolved_base_url,
                    label=label,
                    path=path,
                    timeout_seconds=timeout_seconds,
                    insecure_tls=insecure_tls,
                )
            )
        if interval_seconds > 0 and index < sample_count - 1:
            sleep(interval_seconds)

    endpoint_summaries = {
        endpoint: _endpoint_summary(samples)
        for endpoint, samples in samples_by_endpoint.items()
    }
    status, blockers, degraded = _overall_status(
        endpoint_summaries,
        max_error_rate=max_error_rate,
        max_p95_ms=max_p95_ms,
    )
    return {
        "version": M1_RUNTIME_PROBE_METRICS_VERSION,
        "status": status,
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "reads_dotenv": False,
            "base_url_echoed": False,
            "records_response_body": False,
            "insecure_tls": insecure_tls,
            "allow_local_base_url": allow_local_base_url,
        },
        "thresholds": {
            "max_error_rate": max_error_rate,
            "max_p95_ms": max_p95_ms,
        },
        "checks": {"base_url": base_url_check},
        "sample_count_per_endpoint": sample_count,
        "endpoint_summaries": endpoint_summaries,
        "declaration_statuses": {
            "ZHIXING_ERROR_RATE_MONITOR_STATUS": "passed" if not blockers else "blocked",
            "ZHIXING_P95_LATENCY_MONITOR_STATUS": "passed" if status == "passed" else "degraded",
        },
        "blocked_reasons": blockers,
        "degraded_reasons": degraded,
        "not_proven_by_this_report": [
            "This is health/readiness endpoint probing, not chat-turn P95 latency.",
            "This does not prove tool failure rate, cost alerts, log redaction sampling, or long-term retention.",
            "Use application metrics/APM or acceptance snapshots for user conversation latency and tool quality.",
        ],
    }


def _path_arg(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None, help="Base URL to probe. Falls back to ZHIXING_PUBLIC_BASE_URL.")
    parser.add_argument("--sample-count", type=int, default=10, help="Number of samples per endpoint.")
    parser.add_argument("--interval-seconds", type=float, default=0.0, help="Delay between sample rounds.")
    parser.add_argument("--timeout-seconds", type=float, default=5, help="Timeout per probe.")
    parser.add_argument("--max-error-rate", type=float, default=0.0, help="Maximum allowed error rate per endpoint.")
    parser.add_argument("--max-p95-ms", type=float, default=1000.0, help="Maximum allowed P95 latency per endpoint.")
    parser.add_argument("--allow-local-base-url", action="store_true", help="Allow localhost/127.0.0.1 base URLs.")
    parser.add_argument("--insecure-tls", action="store_true", help="Skip TLS verification for HTTPS probes.")
    parser.add_argument("--json", action="store_true", help="Print JSON. Default is JSON.")
    parser.add_argument("--output", type=_path_arg, default=None, help="Optional absolute output path outside the repo.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    output_check = _validate_output_path(str(args.output) if args.output else None)
    if output_check["status"] == "blocked":
        report = {
            "version": M1_RUNTIME_PROBE_METRICS_VERSION,
            "status": "blocked",
            "policy": {
                "reads_dotenv": False,
                "base_url_echoed": False,
                "output_path_echoed": False,
            },
            "checks": {"output": output_check},
            "blocked_reasons": [output_check],
        }
    else:
        report = build_m1_runtime_probe_metrics_report(
            base_url=args.base_url,
            sample_count=args.sample_count,
            interval_seconds=args.interval_seconds,
            timeout_seconds=args.timeout_seconds,
            max_error_rate=args.max_error_rate,
            max_p95_ms=args.max_p95_ms,
            allow_local_base_url=args.allow_local_base_url,
            insecure_tls=args.insecure_tls,
        )
        report["checks"]["output"] = output_check
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None and output_check["status"] != "blocked":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print("wrote output")
    else:
        print(text)
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
