import json
from pathlib import Path
import threading

from scripts import collect_rate_limit_live_probe as probe


PUBLIC_URL = "https://m1.zhixing.example"


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_rate_limit_live_probe_passes_after_success_then_429():
    statuses = [200, 200, 429]

    def runner(url, *, timeout_seconds):
        status = statuses.pop(0)
        headers = {
            "x-ratelimit-limit": "2",
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "60",
            "x-ratelimit-backend": "redis",
        }
        if status == 429:
            headers["retry-after"] = "60"
        return status, headers, "HTTPError" if status == 429 else None, 12.3

    report = probe.build_rate_limit_live_probe_report(
        base_url=PUBLIC_URL,
        request_count=3,
        request_runner=runner,
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["status_counts"] == {"200": 2, "429": 1}
    assert report["rate_limit_headers_seen"]["x-ratelimit-limit"] is True
    assert report["rate_limit_headers_seen"]["retry-after"] is True
    assert report["rate_limit_header_observations"]["limit_values_seen"] == [2]
    assert report["rate_limit_header_observations"]["remaining_min"] == 0
    assert report["rate_limit_header_observations"]["backend_values_seen"] == ["redis"]
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["reads_response_body"] is False
    assert report["policy"]["calls_llm"] is False
    assert report["policy"]["creates_real_payment"] is False
    assert PUBLIC_URL not in payload
    assert probe.DEFAULT_PATH not in payload
    assert "<public-url>" in payload


def test_rate_limit_live_probe_blocks_when_429_missing():
    def runner(url, *, timeout_seconds):
        return (
            200,
            {
                "x-ratelimit-limit": "120",
                "x-ratelimit-remaining": "119",
                "x-ratelimit-reset": "60",
            },
            None,
            5.0,
        )

    report = probe.build_rate_limit_live_probe_report(
        base_url=PUBLIC_URL,
        request_count=2,
        request_runner=runner,
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "missing_429" for item in report["blocked_reasons"])


def test_rate_limit_live_probe_can_burst_with_concurrency():
    lock = threading.Lock()
    calls = 0

    def runner(url, *, timeout_seconds):
        nonlocal calls
        with lock:
            calls += 1
            current = calls
        status = 200 if current <= 2 else 429
        headers = {
            "x-ratelimit-limit": "2",
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "60",
            "x-ratelimit-backend": "redis",
        }
        if status == 429:
            headers["retry-after"] = "60"
        return status, headers, "HTTPError" if status == 429 else None, 12.3

    report = probe.build_rate_limit_live_probe_report(
        base_url=PUBLIC_URL,
        request_count=8,
        concurrency=4,
        request_runner=runner,
    )

    assert report["status"] == "passed"
    assert report["concurrency"] == 4
    assert report["thresholds"]["concurrency"] == 4
    assert report["status_counts"] == {"200": 2, "429": 6}


def test_rate_limit_live_probe_invalid_target_is_blocked():
    report = probe.build_rate_limit_live_probe_report(
        base_url="not-a-url",
        request_count=1,
        request_runner=lambda **kwargs: (200, {}, None, 1.0),
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["key"] == "invalid_target"


def test_rate_limit_live_probe_markdown_is_redacted():
    report = probe.build_rate_limit_live_probe_report(
        base_url=PUBLIC_URL,
        request_count=1,
        request_runner=lambda *args, **kwargs: (
            429,
            {"x-ratelimit-limit": "1", "retry-after": "60"},
            "HTTPError",
            1.0,
        ),
    )
    markdown = probe.build_rate_limit_live_probe_markdown(report)

    assert "Rate Limit Live Probe Evidence" in markdown
    assert "Status" in markdown
    assert PUBLIC_URL not in markdown
    assert probe.DEFAULT_PATH not in markdown
    assert "Values are redacted" in markdown


def test_rate_limit_live_probe_cli_writes_utf8_output(tmp_path: Path):
    output_path = tmp_path / "rate-limit.json"

    code = probe.main(["--base-url", "not-a-url", "--output", str(output_path)])

    assert code == 2
    text = output_path.read_text(encoding="utf-8")
    assert '"status": "blocked"' in text
    assert "invalid_target" in text


def test_rate_limit_live_probe_cli_renders_existing_json_without_base_url(tmp_path: Path):
    report_path = tmp_path / "rate-limit.json"
    output_path = tmp_path / "rate-limit.md"
    report_path.write_text(
        json.dumps(
            {
                "version": probe.RATE_LIMIT_LIVE_PROBE_VERSION,
                "status": "passed",
                "request_count": 3,
                "status_counts": {"200": 2, "429": 1},
                "rate_limit_headers_seen": {"retry-after": True},
                "rate_limit_header_observations": {"limit_values_seen": [2]},
                "not_proven_by_this_probe": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    code = probe.main(["--report-json", str(report_path), "--markdown", "--output", str(output_path)])

    assert code == 0
    markdown = output_path.read_text(encoding="utf-8")
    assert "Rate Limit Live Probe Evidence" in markdown
    assert "passed" in markdown
