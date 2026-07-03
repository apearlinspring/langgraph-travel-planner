import json

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
    assert report["summary"]["failure_count"] == 1
    assert report["summary"]["failure_rate"] == 0.25
    assert report["declaration_statuses"]["ZHIXING_TOOL_FAILURE_MONITOR_STATUS"] == "passed"


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
