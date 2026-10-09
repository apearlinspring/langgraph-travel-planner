import json
from pathlib import Path

from scripts import collect_live_concurrency_probe as probe


def _runner(status_code=200, elapsed_ms=25.0, error_class=None):
    def run(url: str, timeout_seconds: float):
        assert url.startswith("https://private.example")
        assert timeout_seconds > 0
        return status_code, elapsed_ms, error_class

    return run


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_live_concurrency_probe_passes_without_echoing_base_url_or_body():
    report = probe.build_live_concurrency_probe_report(
        base_url="https://private.example",
        requests_per_endpoint=3,
        concurrency=2,
        request_runner=_runner(),
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["target"]["base_url"] == "<public-url>"
    assert report["policy"]["http_methods"] == ["GET"]
    assert report["policy"]["calls_llm"] is False
    assert report["policy"]["creates_real_payment"] is False
    assert report["endpoints"][0]["request_count"] == 3
    assert "https://private.example" not in payload
    assert "response_body" not in payload.lower() or "response_body_echoed" in payload


def test_endpoint_error_rate_blocks_probe():
    report = probe.build_live_concurrency_probe_report(
        base_url="https://private.example",
        endpoints=[{"key": "health_live", "path": "/health/live", "expected_status": 200}],
        requests_per_endpoint=2,
        concurrency=2,
        max_error_rate=0,
        request_runner=_runner(status_code=503, elapsed_ms=30.0, error_class="HTTPError"),
    )

    assert report["status"] == "blocked"
    assert report["endpoints"][0]["status"] == "blocked"
    assert report["endpoints"][0]["error_rate"] == 1.0
    assert any(item["key"] == "health_live.error_rate" for item in report["blocked_reasons"])


def test_slow_p95_degrades_probe_without_errors():
    report = probe.build_live_concurrency_probe_report(
        base_url="https://private.example",
        endpoints=[{"key": "health_ready", "path": "/health/ready", "expected_status": 200}],
        requests_per_endpoint=4,
        concurrency=2,
        max_p95_ms=100,
        request_runner=_runner(status_code=200, elapsed_ms=250.0),
    )

    assert report["status"] == "degraded"
    assert report["endpoints"][0]["status"] == "degraded"
    assert report["endpoints"][0]["latency_ms"]["p95"] == 250.0
    assert any(item["key"] == "health_ready.p95_latency" for item in report["degraded_reasons"])


def test_invalid_base_url_blocks_before_network():
    report = probe.build_live_concurrency_probe_report(
        base_url="/relative",
        requests_per_endpoint=1,
        concurrency=1,
        request_runner=_runner(),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "invalid_target"


def test_invalid_endpoint_path_blocks_before_network():
    report = probe.build_live_concurrency_probe_report(
        base_url="https://private.example",
        endpoints=[{"key": "bad", "path": "https://other.example/path", "expected_status": 200}],
        requests_per_endpoint=1,
        concurrency=1,
        request_runner=_runner(),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "invalid_target"


def test_live_concurrency_probe_cli_writes_utf8_output(tmp_path: Path):
    output_path = tmp_path / "live-concurrency.json"

    code = probe.main(["--base-url", "/relative", "--output", str(output_path)])

    assert code == 2
    text = output_path.read_text(encoding="utf-8")
    assert '"status": "blocked"' in text
    assert "invalid_target" in text
