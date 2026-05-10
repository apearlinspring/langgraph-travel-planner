from app.tools.audit import (
    build_tool_audit_event,
    pending_checks_from_audit_events,
    start_tool_audit,
    summarize_tool_input,
)
from app.tools.guardrails import validate_hotel_query_args, validate_transport_query_args
from app.tools.state_transition import (
    _build_budget_quality_notes,
    _build_report_tool_audit_summary,
)


def test_tool_guardrails_reject_placeholder_transport_and_hotel_args():
    transport = validate_transport_query_args(
        {
            "origin_city": "出发地",
            "destination_city": "目的地",
            "departure_date": "日期",
            "transport_type": "boat",
        }
    )
    hotel = validate_hotel_query_args(
        {
            "destination": "目的地",
            "check_in_date": "入住日期",
            "stay_nights": 0,
            "adult_count": 0,
            "children_count": -1,
            "budget_level": "vip",
            "place_type": "未知",
            "size": 99,
            "max_price_per_night": -1,
        }
    )

    assert transport.ok is False
    assert transport.error_type == "invalid_transport_query_args"
    assert hotel.ok is False
    assert hotel.error_type == "invalid_hotel_query_args"


def test_tool_input_summary_accepts_non_dict_and_masks_secret_key_parts():
    plain = summarize_tool_input("直接查询南京酒店")
    masked = summarize_tool_input(
        {
            "destination": "南京",
            "aigohotel_api_key": "should-not-leak",
            "nested": {"access_token": "also-secret", "safe": "ok"},
        }
    )

    assert plain == {"input": "直接查询南京酒店"}
    assert "aigohotel_api_key" not in masked
    assert "access_token" not in masked["nested"]
    assert masked["nested"]["safe"] == "ok"


def test_failed_tool_audit_events_feed_budget_and_report_pending_checks():
    context = start_tool_audit("query_hotel_options")
    event = build_tool_audit_event(
        context,
        status="timeout",
        input_summary={"destination": "南京"},
        output_summary={"message": "上游超时"},
        error_type="upstream_timeout",
        evidence_type="live_hotel_search",
    )

    pending_checks = pending_checks_from_audit_events([event])
    quality = _build_budget_quality_notes(
        {
            "tool_audit_events": [event],
            "selected_transport_option": {},
            "selected_accommodation_option": {},
        },
        {},
        [],
    )
    summary = _build_report_tool_audit_summary(
        {
            "estimated_items": [],
            "verification_items": [],
        },
        [],
        {},
        {},
        [event],
    )

    assert any("真实查询超时" in item for item in pending_checks)
    assert any("真实查询超时" in item for item in quality["verification_items"])
    assert summary["events"][0]["status"] == "timeout"
    assert any("住宿" in item and "超时" in item for item in summary["pending_checks"])
