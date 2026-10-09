import json
from pathlib import Path

from scripts import collect_live_chat_concurrency_probe as probe
from scripts import check_live_chat_concurrency_probe_approval as approval


def _approval_report(max_probe_conversations=3, max_concurrency=2):
    return {
        "version": approval.LIVE_CHAT_CONCURRENCY_PROBE_APPROVAL_VERSION,
        "status": "passed",
        "decision": "approved_for_live_chat_concurrency_probe",
        "approved_limits": {
            "max_probe_conversations": max_probe_conversations,
            "max_concurrency": max_concurrency,
        },
    }


def _single_probe_report(status="passed", total_seconds=3.0, first_token_seconds=1.5):
    return {
        "status": status,
        "observations": {
            "stream_completed": status != "blocked",
            "event_count": 2,
            "first_event_seconds": 0.5,
            "first_token_seconds": first_token_seconds,
            "total_seconds": total_seconds,
            "assistant_chars_observed": 12,
        },
        "blocked_reasons": [] if status != "blocked" else [{"key": "timeout", "finding": "timed out"}],
        "degraded_reasons": [] if status != "degraded" else [{"key": "total_latency", "finding": "slow"}],
    }


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_plan_only_chat_concurrency_probe_does_not_execute():
    report = probe.build_live_chat_concurrency_probe_report(
        base_url="https://private.example",
        execute=False,
    )
    payload = _payload_text(report)

    assert report["status"] == "not_checked"
    assert report["policy"]["calls_llm"] is False
    assert report["plan"]["not_a_load_test"] is True
    assert "https://private.example" not in payload
    assert "<public-url>" in payload


def test_chat_concurrency_probe_passes_without_echoing_private_values():
    report = probe.build_live_chat_concurrency_probe_report(
        base_url="https://private.example",
        approval_report=_approval_report(),
        username="probe-user",
        password="probe-password",
        execute=True,
        request_count=3,
        concurrency=2,
        probe_runner=lambda index: _single_probe_report(
            total_seconds=2.0 + index,
            first_token_seconds=1.0 + index,
        ),
    )
    payload = _payload_text(report)

    assert report["status"] == "passed"
    assert report["target"]["base_url"] == "<public-url>"
    assert report["policy"]["calls_llm"] is True
    assert report["policy"]["load_test"] is False
    assert report["observations"]["request_count"] == 3
    assert report["observations"]["concurrency"] == 2
    assert report["observations"]["passed_count"] == 3
    assert report["observations"]["total_seconds"]["p95"] == 5.0
    assert "https://private.example" not in payload
    assert "probe-user" not in payload
    assert "probe-password" not in payload


def test_chat_concurrency_probe_blocks_when_approval_missing():
    report = probe.build_live_chat_concurrency_probe_report(
        base_url="https://private.example",
        username="probe-user",
        password="probe-password",
        execute=True,
        request_count=3,
        concurrency=2,
        probe_runner=lambda index: _single_probe_report(),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "approval_report_missing" for item in report["blocked_reasons"])


def test_chat_concurrency_probe_blocks_when_limits_exceeded():
    report = probe.build_live_chat_concurrency_probe_report(
        base_url="https://private.example",
        approval_report=_approval_report(max_probe_conversations=2, max_concurrency=1),
        username="probe-user",
        password="probe-password",
        execute=True,
        request_count=3,
        concurrency=2,
        probe_runner=lambda index: _single_probe_report(),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "request_count_exceeds_approval" for item in report["blocked_reasons"])
    assert any(item["key"] == "concurrency_exceeds_approval" for item in report["blocked_reasons"])


def test_chat_concurrency_probe_degrades_when_one_sample_blocks_under_threshold():
    def runner(index):
        if index == 3:
            return _single_probe_report(status="blocked")
        return _single_probe_report()

    report = probe.build_live_chat_concurrency_probe_report(
        base_url="https://private.example",
        approval_report=_approval_report(),
        username="probe-user",
        password="probe-password",
        execute=True,
        request_count=3,
        concurrency=2,
        max_blocked_rate=0.34,
        probe_runner=runner,
    )

    assert report["status"] == "degraded"
    assert report["observations"]["blocked_count"] == 1
    assert any(item["key"] == "sample_blocked_under_threshold" for item in report["degraded_reasons"])


def test_chat_concurrency_probe_blocks_when_blocked_rate_exceeds_threshold():
    report = probe.build_live_chat_concurrency_probe_report(
        base_url="https://private.example",
        approval_report=_approval_report(),
        username="probe-user",
        password="probe-password",
        execute=True,
        request_count=3,
        concurrency=2,
        max_blocked_rate=0,
        probe_runner=lambda index: _single_probe_report(status="blocked") if index == 1 else _single_probe_report(),
    )

    assert report["status"] == "blocked"
    assert any(item["key"] == "blocked_rate" for item in report["blocked_reasons"])


def test_chat_concurrency_probe_cli_writes_utf8_output(tmp_path: Path):
    output_path = tmp_path / "live-chat-concurrency.json"

    code = probe.main(["--base-url", "/relative", "--execute", "--output", str(output_path)])

    assert code == 2
    text = output_path.read_text(encoding="utf-8")
    assert '"status": "blocked"' in text
    assert "invalid_target" in text
