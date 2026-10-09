import json

import pytest

from scripts import check_tool_failure_monitor_status as monitor


def _payload_text(report):
    return json.dumps(report, ensure_ascii=False)


def test_tool_failure_monitor_passes_with_low_failure_rate():
    rows = [
        {"name": "query_transport_options", "status": "success", "elapsed_seconds": 0.2},
        {"name": "query_hotel_options", "status": "success", "elapsed_seconds": 0.4},
        {"name": "maps_geo", "status": "success", "elapsed_seconds": 0.1},
        {
            "name": "get_weather_forecast",
            "status": "degraded",
            "error_type": "empty_weather_result",
            "elapsed_seconds": 0.5,
        },
    ]

    report = monitor.build_tool_failure_monitor_status_report(
        rows=rows,
        warn_failure_rate=0.5,
        max_failure_rate=0.8,
    )

    assert report["status"] == "passed"
    assert report["summary"]["sample_count"] == 4
    assert report["summary"]["failure_count"] == 0
    assert report["summary"]["failure_rate"] == 0.0
    assert report["summary"]["fallback_count"] == 1
    assert report["summary"]["degraded_count"] == 1
    assert report["summary"]["success_count"] == 3
    assert report["declaration_statuses"]["ZHIXING_TOOL_FAILURE_MONITOR_STATUS"] == "passed"


def test_tool_failure_monitor_separates_hard_failures_fallbacks_and_degradation():
    rows = [
        {"name": "success", "status": "success"},
        {"name": "needs_verification", "status": "degraded"},
        {
            "name": "empty_result",
            "status": "degraded",
            "error_type": "empty_transport_result",
        },
        {
            "name": "insufficient_parameters",
            "status": "skipped",
            "error_type": "invalid_destination",
        },
        {"name": "governance_skip", "status": "skipped"},
        {"name": "approval", "status": "approval_required"},
        {"name": "semantic_not_found", "status": "not_found"},
        {
            "name": "semantic_exception",
            "status": "degraded",
            "semantic_status": "service_exception",
        },
        {"name": "failed", "status": "failed"},
        {"name": "failure", "status": "failure"},
        {"name": "timeout", "status": "timeout"},
        {"name": "error", "status": "error"},
    ]

    report = monitor.build_tool_failure_monitor_status_report(
        rows=rows,
        warn_failure_rate=0.9,
        max_failure_rate=1.0,
    )
    summary = report["summary"]

    assert report["status"] == "passed"
    assert summary["failure_count"] == 5
    assert summary["hard_failure_count"] == 5
    assert summary["fallback_count"] == 2
    assert summary["degraded_count"] == 11
    assert summary["success_count"] == 1
    assert summary["metric_semantics"]["failure"] == "hard_failure"
    semantic_counts = {
        item["key"]: item["count"]
        for item in summary["semantic_status_counts"]
    }
    assert semantic_counts["insufficient_parameters"] == 1
    assert semantic_counts["needs_verification"] == 1
    assert semantic_counts["skipped"] == 2


def test_tool_failure_monitor_treats_failed_empty_results_as_fallbacks_only():
    rows = [
        {"name": "rag", "status": "failed", "error_type": "empty_rag_result"},
        {"name": "mcp", "status": "failed", "error_type": "empty_mcp_result"},
        {
            "name": "transport",
            "status": "failed",
            "error_type": "empty_transport_result",
        },
        {"name": "explicit", "status": "failed", "semantic_status": "not_found"},
    ]

    report = monitor.build_tool_failure_monitor_status_report(rows=rows)

    assert report["summary"]["hard_failure_count"] == 0
    assert report["summary"]["fallback_count"] == 4
    assert report["summary"]["semantic_status_counts"] == [
        {"key": "not_found", "count": 4}
    ]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "field_name",
    ["lookback_hours", "warn_failure_rate", "max_failure_rate", "timeout_seconds"],
)
def test_tool_failure_monitor_rejects_non_finite_float_thresholds(field_name, value):
    with pytest.raises(ValueError, match=field_name):
        monitor.build_tool_failure_monitor_status_report(
            rows=[],
            **{field_name: value},
        )


@pytest.mark.parametrize(
    ("warn_failure_rate", "max_failure_rate"),
    [(-0.1, 0.5), (0.6, 0.5), (0.2, 1.1)],
)
def test_tool_failure_monitor_rejects_invalid_failure_rate_order(
    warn_failure_rate,
    max_failure_rate,
):
    with pytest.raises(ValueError, match="0 <= warn_failure_rate <= max_failure_rate <= 1"):
        monitor.build_tool_failure_monitor_status_report(
            rows=[],
            warn_failure_rate=warn_failure_rate,
            max_failure_rate=max_failure_rate,
        )


def test_tool_failure_monitor_cli_rejects_nan_threshold():
    with pytest.raises(SystemExit) as exc_info:
        monitor.parse_args(["--warn-failure-rate", "nan"])

    assert exc_info.value.code == 2


def test_tool_failure_monitor_degrades_for_warning_failure_rate():
    rows = [
        {"name": "query_transport_options", "status": "success", "elapsed_seconds": 0.2},
        {
            "name": "query_hotel_options",
            "status": "timeout",
            "error_type": "upstream_timeout",
            "elapsed_seconds": 3.0,
        },
    ]

    report = monitor.build_tool_failure_monitor_status_report(
        rows=rows,
        warn_failure_rate=0.2,
        max_failure_rate=0.8,
    )

    assert report["status"] == "degraded"
    assert report["degraded_reasons"][0]["metric"] == "failure_rate"
    assert report["declaration_statuses"]["ZHIXING_TOOL_FAILURE_MONITOR_STATUS"] == "passed"


def test_tool_failure_monitor_blocks_for_excessive_failure_rate():
    rows = [
        {"name": "query_transport_options", "status": "timeout", "elapsed_seconds": 3.0},
        {"name": "query_hotel_options", "status": "failed", "elapsed_seconds": 1.2},
    ]

    report = monitor.build_tool_failure_monitor_status_report(
        rows=rows,
        warn_failure_rate=0.2,
        max_failure_rate=0.5,
    )

    assert report["status"] == "blocked"
    assert report["blocked_reasons"][0]["metric"] == "failure_rate"
    assert report["declaration_statuses"]["ZHIXING_TOOL_FAILURE_MONITOR_STATUS"] == "passed"


def test_tool_failure_monitor_can_allow_empty_m1_sample():
    report = monitor.build_tool_failure_monitor_status_report(
        rows=[],
        allow_empty_sample=True,
    )

    assert report["status"] == "passed"
    assert report["summary"]["sample_count"] == 0
    assert report["degraded_reasons"][0]["metric"] == "sample_count"
    assert report["declaration_statuses"]["ZHIXING_TOOL_FAILURE_MONITOR_STATUS"] == "passed"


def test_tool_failure_monitor_blocks_missing_database_env_without_echoing_values():
    report = monitor.build_tool_failure_monitor_status_report(
        environ={"POSTGRES_PASSWORD": "secret-should-not-leak"}
    )
    payload = _payload_text(report)

    assert report["status"] == "blocked"
    assert report["declaration_statuses"]["ZHIXING_TOOL_FAILURE_MONITOR_STATUS"] == "blocked"
    assert "secret-should-not-leak" not in payload
    assert report["policy"]["reads_dotenv"] is False


def test_tool_failure_monitor_redacts_sensitive_error_types():
    rows = [
        {
            "name": "maps_geo",
            "status": "failed",
            "error_type": "upstream 403 api_key=amap-secret-123 token=abc123456789",
            "elapsed_seconds": 0.3,
        }
    ]

    report = monitor.build_tool_failure_monitor_status_report(
        rows=rows,
        max_failure_rate=1.0,
    )
    payload = _payload_text(report)

    assert "amap-secret-123" not in payload
    assert "abc123456789" not in payload
    assert "[REDACTED]" in payload
