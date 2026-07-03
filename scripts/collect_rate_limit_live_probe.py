"""Collect redacted live API rate-limit evidence."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


RATE_LIMIT_LIVE_PROBE_VERSION = "rate_limit_live_probe.v1"
PUBLIC_URL_PLACEHOLDER = "<public-url>"
DEFAULT_PATH = "/api/v1/mock-checkout/ORDER-RATELIMIT01/status"


def _normalize_base_url(base_url: str) -> str:
    value = str(base_url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be absolute HTTP(S)")
    return value.rstrip("/") + "/"


def _normalize_path(path: str) -> str:
    value = str(path or "").strip()
    if not value.startswith("/") or "://" in value:
        raise ValueError("probe path must be a relative absolute path")
    return value


def _request_status(url: str, *, timeout_seconds: float) -> tuple[int | None, dict[str, str], str | None, float]:
    request = Request(url, method="GET", headers={"User-Agent": "zhixing-rate-limit-probe/1.0"})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(512)
            headers = {key.lower(): value for key, value in response.headers.items()}
            return int(response.status), headers, None, (time.perf_counter() - started) * 1000
    except HTTPError as exc:
        exc.read(512)
        headers = {key.lower(): value for key, value in exc.headers.items()}
        return int(exc.code), headers, "HTTPError", (time.perf_counter() - started) * 1000
    except (TimeoutError, URLError, OSError) as exc:
        return None, {}, exc.__class__.__name__, (time.perf_counter() - started) * 1000


def _int_header(headers: Mapping[str, str], key: str) -> int | None:
    try:
        return int(str(headers.get(key) or "").strip())
    except ValueError:
        return None


def build_rate_limit_live_probe_report(
    *,
    base_url: str,
    path: str = DEFAULT_PATH,
    request_count: int = 8,
    concurrency: int = 1,
    timeout_seconds: float = 5,
    expect_429: bool = True,
    request_runner: Any = _request_status,
) -> dict[str, Any]:
    """Build redacted live rate-limit evidence."""

    report: dict[str, Any] = {
        "version": RATE_LIMIT_LIVE_PROBE_VERSION,
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
            "path_key": "mock_checkout_status",
            "base_url_echoed": False,
            "path_echoed": False,
        },
        "thresholds": {
            "request_count": request_count,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
            "expect_429": expect_429,
        },
        "not_proven_by_this_probe": [
            "This probe proves only that a sampled low-risk API path enforces rate-limit responses.",
            "It does not prove full traffic shaping, WAF protection, autoscaling, or upstream provider quota protection.",
            "GET mock checkout status is used because it has no real payment, booking, inventory, or fulfillment side effects.",
        ],
    }
    if request_count <= 0:
        report["blocked_reasons"] = [{"key": "invalid_request_count", "finding": "Request count must be positive."}]
        return report
    if concurrency <= 0:
        report["blocked_reasons"] = [{"key": "invalid_concurrency", "finding": "Concurrency must be positive."}]
        return report
    try:
        normalized_base_url = _normalize_base_url(base_url)
        normalized_path = _normalize_path(path)
    except ValueError as exc:
        report["blocked_reasons"] = [{"key": "invalid_target", "finding": exc.__class__.__name__}]
        return report

    status_counts: dict[str, int] = {}
    error_classes: dict[str, int] = {}
    rate_limit_headers_seen = {
        "x-ratelimit-limit": False,
        "x-ratelimit-remaining": False,
        "x-ratelimit-reset": False,
        "retry-after": False,
        "x-ratelimit-backend": False,
    }
    limit_values_seen: set[int] = set()
    remaining_values_seen: list[int] = []
    backend_values_seen: set[str] = set()
    latencies_ms: list[float] = []
    probe_url = urljoin(normalized_base_url, normalized_path.lstrip("/"))
    max_workers = min(concurrency, request_count)
    if max_workers == 1:
        results = [
            request_runner(
                probe_url,
                timeout_seconds=timeout_seconds,
            )
            for _ in range(request_count)
        ]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(request_runner, probe_url, timeout_seconds=timeout_seconds)
                for _ in range(request_count)
            ]
            results = [future.result() for future in as_completed(futures)]
    for status_code, headers, error_class, elapsed_ms in results:
        status_key = str(status_code) if status_code is not None else "network_error"
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        if error_class:
            error_classes[error_class] = error_classes.get(error_class, 0) + 1
        for header in rate_limit_headers_seen:
            if header in headers:
                rate_limit_headers_seen[header] = True
        limit_value = _int_header(headers, "x-ratelimit-limit")
        remaining_value = _int_header(headers, "x-ratelimit-remaining")
        backend_value = str(headers.get("x-ratelimit-backend") or "").strip().lower()
        if limit_value is not None:
            limit_values_seen.add(limit_value)
        if remaining_value is not None:
            remaining_values_seen.append(remaining_value)
        if backend_value:
            backend_values_seen.add(backend_value[:40])
        latencies_ms.append(float(elapsed_ms))

    saw_429 = status_counts.get("429", 0) > 0
    saw_success = any(status_counts.get(str(code), 0) > 0 for code in range(200, 300))
    blocked_reasons = []
    if expect_429 and not saw_429:
        blocked_reasons.append({"key": "missing_429", "finding": "No 429 response was observed."})
    if not saw_success:
        blocked_reasons.append({"key": "missing_success", "finding": "No successful response was observed before limiting."})
    if saw_429 and not rate_limit_headers_seen["retry-after"]:
        blocked_reasons.append({"key": "missing_retry_after", "finding": "429 response did not include Retry-After."})
    if not rate_limit_headers_seen["x-ratelimit-limit"]:
        blocked_reasons.append({"key": "missing_limit_header", "finding": "Rate-limit headers were not observed."})

    report.update(
        {
            "status": "blocked" if blocked_reasons else "passed",
            "request_count": request_count,
            "concurrency": concurrency,
            "status_counts": dict(sorted(status_counts.items())),
            "error_classes": dict(sorted(error_classes.items())),
            "rate_limit_headers_seen": rate_limit_headers_seen,
            "rate_limit_header_observations": {
                "limit_values_seen": sorted(limit_values_seen),
                "remaining_min": min(remaining_values_seen) if remaining_values_seen else None,
                "remaining_max": max(remaining_values_seen) if remaining_values_seen else None,
                "backend_values_seen": sorted(backend_values_seen),
                "value_echoed": False,
            },
            "latency_ms": {
                "max": round(max(latencies_ms), 3) if latencies_ms else None,
            },
            "blocked_reasons": blocked_reasons,
            "degraded_reasons": [],
            "declaration_statuses": {
                "ZHIXING_RATE_LIMIT_LIVE_STATUS": "blocked" if blocked_reasons else "passed"
            },
        }
    )
    return report


def _markdown_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|") or "-"


def build_rate_limit_live_probe_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Rate Limit Live Probe Evidence",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Version: `{report.get('version')}`",
        "- Values are redacted: base URL, path and response bodies are not echoed.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Request count | `{_markdown_cell(report.get('request_count'))}` |",
        f"| Concurrency | `{_markdown_cell(report.get('concurrency'))}` |",
        f"| Status counts | `{_markdown_cell(json.dumps(report.get('status_counts') or {}, ensure_ascii=False))}` |",
        f"| Headers seen | `{_markdown_cell(json.dumps(report.get('rate_limit_headers_seen') or {}, ensure_ascii=False))}` |",
        f"| Header observations | `{_markdown_cell(json.dumps(report.get('rate_limit_header_observations') or {}, ensure_ascii=False))}` |",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons", ""])
        for item in report.get("blocked_reasons") or []:
            lines.append(f"- `{item.get('key')}`: {item.get('finding')}")
    lines.extend(["", "## Not Proven", ""])
    for item in report.get("not_proven_by_this_probe") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="", help="HTTP(S) base URL. Redacted from output.")
    parser.add_argument("--path", default=DEFAULT_PATH, help="Relative path to probe. Redacted from output.")
    parser.add_argument("--request-count", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=5)
    parser.add_argument("--allow-missing-429", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--report-json", type=Path, default=None, help="Render an existing UTF-8 report without probing.")
    parser.add_argument("--output", type=Path, default=None, help="Optional UTF-8 output path. Path is not echoed.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.report_json is not None:
        try:
            report = json.loads(args.report_json.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            report = {
                "version": RATE_LIMIT_LIVE_PROBE_VERSION,
                "status": "blocked",
                "blocked_reasons": [
                    {"key": "report_json", "finding": "Existing report JSON could not be read."}
                ],
            }
    else:
        report = build_rate_limit_live_probe_report(
            base_url=args.base_url,
            path=args.path,
            request_count=args.request_count,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            expect_429=not args.allow_missing_429,
        )
    output_text = (
        build_rate_limit_live_probe_markdown(report)
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
