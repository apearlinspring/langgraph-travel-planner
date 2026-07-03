"""Collect redacted low-risk live concurrency evidence for M1 endpoints."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


LIVE_CONCURRENCY_PROBE_VERSION = "live_concurrency_probe.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
DEFAULT_ENDPOINTS = (
    {"key": "health_live", "path": "/health/live", "expected_status": 200},
    {"key": "health_ready", "path": "/health/ready", "expected_status": 200},
    {
        "key": "mock_checkout_status",
        "path": "/api/v1/mock-checkout/ORDER-LOADTEST01/status",
        "expected_status": 200,
    },
)


@dataclass(frozen=True)
class RequestResult:
    endpoint_key: str
    status_code: int | None
    elapsed_ms: float
    error_class: str | None = None


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be absolute HTTP(S)")
    return value.rstrip("/") + "/"


def _normalize_endpoint_path(path: str) -> str:
    value = str(path or "").strip()
    if not value.startswith("/") or "://" in value:
        raise ValueError("endpoint paths must be relative absolute paths")
    return value


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(float(values[0]), 3)
    ordered = sorted(float(item) for item in values)
    index = max(0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _http_get_status(url: str, *, timeout_seconds: float) -> tuple[int | None, float, str | None]:
    started = time.perf_counter()
    request = Request(url, method="GET", headers={"User-Agent": "zhixing-m1-concurrency-probe/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(4096)
            status_code = int(response.status)
            error_class = None
    except HTTPError as exc:
        status_code = int(exc.code)
        error_class = "HTTPError"
    except (TimeoutError, URLError, OSError) as exc:
        status_code = None
        error_class = exc.__class__.__name__
    elapsed_ms = (time.perf_counter() - started) * 1000
    return status_code, elapsed_ms, error_class


def _run_one_request(
    *,
    base_url: str,
    endpoint: Mapping[str, Any],
    timeout_seconds: float,
    request_runner: Callable[[str, float], tuple[int | None, float, str | None]],
) -> RequestResult:
    path = _normalize_endpoint_path(str(endpoint["path"]))
    status_code, elapsed_ms, error_class = request_runner(
        urljoin(base_url, path.lstrip("/")),
        timeout_seconds,
    )
    return RequestResult(
        endpoint_key=str(endpoint["key"]),
        status_code=status_code,
        elapsed_ms=float(elapsed_ms),
        error_class=error_class,
    )


def _default_request_runner(url: str, timeout_seconds: float) -> tuple[int | None, float, str | None]:
    return _http_get_status(url, timeout_seconds=timeout_seconds)


def _summarize_endpoint(
    *,
    endpoint: Mapping[str, Any],
    results: Sequence[RequestResult],
    max_p95_ms: float,
    max_error_rate: float,
) -> dict[str, Any]:
    expected_status = int(endpoint.get("expected_status") or 200)
    elapsed_values = [item.elapsed_ms for item in results if item.status_code == expected_status]
    status_codes: dict[str, int] = {}
    error_classes: dict[str, int] = {}
    success_count = 0
    for item in results:
        status_key = str(item.status_code) if item.status_code is not None else "network_error"
        status_codes[status_key] = status_codes.get(status_key, 0) + 1
        if item.error_class:
            error_classes[item.error_class] = error_classes.get(item.error_class, 0) + 1
        if item.status_code == expected_status and not item.error_class:
            success_count += 1
    request_count = len(results)
    failure_count = request_count - success_count
    error_rate = failure_count / request_count if request_count else 1.0
    p95_ms = _percentile(elapsed_values, 95)
    p50_ms = _percentile(elapsed_values, 50)
    max_ms = round(max(elapsed_values), 3) if elapsed_values else None
    blocked_reasons: list[dict[str, str]] = []
    degraded_reasons: list[dict[str, str]] = []
    if request_count <= 0:
        blocked_reasons.append({"key": "no_requests", "finding": "No requests were executed."})
    if success_count <= 0:
        blocked_reasons.append({"key": "no_successes", "finding": "No successful response was observed."})
    if error_rate > max_error_rate:
        blocked_reasons.append({"key": "error_rate", "finding": "Endpoint error rate is above the allowed threshold."})
    if p95_ms is not None and p95_ms > max_p95_ms:
        degraded_reasons.append({"key": "p95_latency", "finding": "Endpoint P95 latency is above the target."})
    status = "blocked" if blocked_reasons else ("degraded" if degraded_reasons else "passed")
    return {
        "status": status,
        "endpoint_key": str(endpoint["key"]),
        "path": str(endpoint["path"]),
        "expected_status": expected_status,
        "request_count": request_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "error_rate": round(error_rate, 4),
        "latency_ms": {
            "p50": p50_ms,
            "p95": p95_ms,
            "max": max_ms,
        },
        "status_codes": dict(sorted(status_codes.items())),
        "error_classes": dict(sorted(error_classes.items())),
        "blocked_reasons": blocked_reasons,
        "degraded_reasons": degraded_reasons,
        "response_body_echoed": False,
        "url_echoed": False,
    }


def build_live_concurrency_probe_report(
    *,
    base_url: str,
    endpoints: Sequence[Mapping[str, Any]] | None = None,
    requests_per_endpoint: int = 20,
    concurrency: int = 10,
    timeout_seconds: float = 5,
    max_p95_ms: float = 2000,
    max_error_rate: float = 0,
    request_runner: Callable[[str, float], tuple[int | None, float, str | None]] = _default_request_runner,
) -> dict[str, Any]:
    """Build redacted concurrency evidence for safe live endpoints."""

    report: dict[str, Any] = {
        "version": LIVE_CONCURRENCY_PROBE_VERSION,
        "status": "blocked",
        "collected_at": datetime.now(UTC).isoformat(),
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
        "target": {
            "base_url": PUBLIC_URL_PLACEHOLDER if base_url else "",
            "base_url_echoed": False,
        },
        "thresholds": {
            "requests_per_endpoint": requests_per_endpoint,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
            "max_p95_ms": max_p95_ms,
            "max_error_rate": max_error_rate,
        },
        "endpoints": [],
        "not_proven_by_this_probe": [
            "This probe covers low-risk GET endpoints only; it does not prove full chat throughput.",
            "This probe does not call LLMs, map providers, hotel providers, flight providers, payment, booking or fulfillment APIs.",
            "A passed short-window probe does not prove autoscaling, long-duration soak stability, or production SLO compliance.",
        ],
    }
    if requests_per_endpoint <= 0 or concurrency <= 0:
        report["blocked_reasons"] = [{"key": "invalid_threshold", "finding": "Request count and concurrency must be positive."}]
        return report
    try:
        normalized_base_url = _normalize_base_url(base_url)
        endpoint_defs = list(endpoints or DEFAULT_ENDPOINTS)
        for endpoint in endpoint_defs:
            _normalize_endpoint_path(str(endpoint["path"]))
    except (KeyError, ValueError) as exc:
        report["blocked_reasons"] = [{"key": "invalid_target", "finding": exc.__class__.__name__}]
        return report

    work_items = [
        endpoint
        for endpoint in endpoint_defs
        for _ in range(requests_per_endpoint)
    ]
    results_by_endpoint: dict[str, list[RequestResult]] = {str(endpoint["key"]): [] for endpoint in endpoint_defs}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _run_one_request,
                base_url=normalized_base_url,
                endpoint=endpoint,
                timeout_seconds=timeout_seconds,
                request_runner=request_runner,
            )
            for endpoint in work_items
        ]
        for future in as_completed(futures):
            result = future.result()
            results_by_endpoint.setdefault(result.endpoint_key, []).append(result)

    endpoint_reports = [
        _summarize_endpoint(
            endpoint=endpoint,
            results=results_by_endpoint.get(str(endpoint["key"]), []),
            max_p95_ms=max_p95_ms,
            max_error_rate=max_error_rate,
        )
        for endpoint in endpoint_defs
    ]
    blocked = []
    degraded = []
    for endpoint_report in endpoint_reports:
        if endpoint_report["status"] == "blocked":
            blocked.append(
                {
                    "key": endpoint_report["endpoint_key"],
                    "finding": "Endpoint failed concurrency probe.",
                }
            )
            for item in endpoint_report.get("blocked_reasons") or []:
                blocked.append(
                    {
                        "key": f"{endpoint_report['endpoint_key']}.{item.get('key')}",
                        "finding": item.get("finding"),
                    }
                )
        elif endpoint_report["status"] == "degraded":
            degraded.append(
                {
                    "key": endpoint_report["endpoint_key"],
                    "finding": "Endpoint latency exceeded target.",
                }
            )
            for item in endpoint_report.get("degraded_reasons") or []:
                degraded.append(
                    {
                        "key": f"{endpoint_report['endpoint_key']}.{item.get('key')}",
                        "finding": item.get("finding"),
                    }
                )
    report.update(
        {
            "status": "blocked" if blocked else ("degraded" if degraded else "passed"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "endpoints": endpoint_reports,
            "blocked_reasons": blocked,
            "degraded_reasons": degraded,
            "declaration_statuses": {
                "ZHIXING_LIVE_CONCURRENCY_STATUS": "blocked" if blocked else ("degraded" if degraded else "passed")
            },
        }
    )
    return report


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("|", "\\|")
    return text or "-"


def build_live_concurrency_probe_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Live Concurrency Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: base URL and response bodies are not echoed.",
        "",
        "## Endpoints",
        "",
        "| Endpoint | Status | Requests | Error rate | P50 ms | P95 ms | Max ms |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in report.get("endpoints") or []:
        if not isinstance(item, Mapping):
            continue
        latency = item.get("latency_ms") or {}
        lines.append(
            "| "
            f"`{_markdown_cell(item.get('endpoint_key'))}` | "
            f"`{_markdown_cell(item.get('status'))}` | "
            f"{_markdown_cell(item.get('request_count'))} | "
            f"{_markdown_cell(item.get('error_rate'))} | "
            f"{_markdown_cell(latency.get('p50'))} | "
            f"{_markdown_cell(latency.get('p95'))} | "
            f"{_markdown_cell(latency.get('max'))} |"
        )
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


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="HTTP(S) base URL. Redacted from output.")
    parser.add_argument("--requests-per-endpoint", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=5)
    parser.add_argument("--max-p95-ms", type=float, default=2000)
    parser.add_argument("--max-error-rate", type=float, default=0)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--output", type=Path, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_live_concurrency_probe_report(
        base_url=args.base_url,
        requests_per_endpoint=args.requests_per_endpoint,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout_seconds,
        max_p95_ms=args.max_p95_ms,
        max_error_rate=args.max_error_rate,
    )
    output_text = (
        build_live_concurrency_probe_markdown(report)
        if args.markdown
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
    else:
        print(output_text, end="")
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
