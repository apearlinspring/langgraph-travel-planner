import asyncio

import pytest
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from app.api.v1.chat import _extract_embedded_tool_audit_events
from app.core.approval import approval_store
from app.core.permissions import (
    decide_tool_execution_permission,
    get_tool_execution_policy,
)
from app.tools.audit import (
    build_tool_audit_event,
    pending_checks_from_audit_events,
    start_tool_audit,
    summarize_tool_input,
)
from app.tools.execution_guard import begin_tool_execution, execute_guarded_call
from app.tools.guardrails import validate_hotel_query_args, validate_transport_query_args
from app.models.approval import ToolAuditEvent
from app.tools import mcp_tools
from app.tools.mcp_tools import guard_mcp_tool
from app.tools.state_transition import (
    _build_budget_quality_notes,
    _build_report_tool_audit_summary,
)


def test_tool_audit_event_model_keeps_persistent_summary_contract():
    columns = ToolAuditEvent.__table__.columns

    assert ToolAuditEvent.__tablename__ == "tool_audit_event"
    assert columns["name"].index is True
    assert columns["input_summary"].nullable is False
    assert columns["output_summary"].nullable is False
    assert columns["evidence_type"].index is True


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


def test_tool_execution_policy_classifies_high_value_tools():
    hotel_policy = get_tool_execution_policy("query_hotel_options")
    rag_policy = get_tool_execution_policy("search_agency_pricing_rules")
    mcp_policy = get_tool_execution_policy("maps_geo")

    assert hotel_policy.risk_level == "high"
    assert hotel_policy.category == "live_hotel_search"
    assert rag_policy.category == "internal_rag"
    assert mcp_policy.category == "mcp_external_query"
    assert decide_tool_execution_permission("query_hotel_options").allowed is True


def test_execution_guard_blocks_sensitive_action_before_real_call():
    approval_store.clear()
    attempt = begin_tool_execution(
        "real_payment",
        {"amount": 100, "phone": "should-be-redacted"},
        runtime=None,
    )

    assert attempt.ok is False
    assert attempt.blocked_event["status"] == "skipped"
    assert attempt.blocked_event["error_type"] == "approval_required"
    assert attempt.approval_update["approval_pending"] is True
    assert attempt.approval_update["approval_action"] == "real_payment"
    record = approval_store.get(attempt.approval_update["approval_record_id"])
    assert record.metadata["phone"] == "[REDACTED]"
    approval_store.clear()


@pytest.mark.asyncio
async def test_execute_guarded_call_times_out_and_writes_audit_event():
    async def slow_call(_args):
        import asyncio

        await asyncio.sleep(0.05)
        return "late"

    result = await execute_guarded_call(
        "query_transport_options",
        {
            "origin_city": "西安",
            "destination_city": "眉县",
            "departure_date": "2026-05-16",
            "transport_type": "train",
        },
        slow_call,
        input_validator=validate_transport_query_args,
        timeout_seconds=0.001,
        evidence_type="live_transport_query",
    )

    assert result.output is None
    assert result.event["status"] == "timeout"
    assert result.event["error_type"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_guard_mcp_tool_emits_success_event_in_artifact_for_content_and_artifact_tool():
    async def raw_tool(city: str):
        return f"{city}天气晴朗", {"source": "raw-weather"}

    raw = StructuredTool.from_function(
        coroutine=raw_tool,
        name="get_weather_forecast",
        description="天气查询",
        response_format="content_and_artifact",
    )
    guarded = guard_mcp_tool(raw)

    direct_result = await guarded.ainvoke({"city": "南京"})
    tool_message = await guarded.ainvoke(
        {
            "type": "tool_call",
            "id": "call-success",
            "name": "get_weather_forecast",
            "args": {"city": "南京"},
        }
    )
    events = _extract_embedded_tool_audit_events(tool_message)

    assert direct_result == "南京天气晴朗"
    assert guarded.response_format == "content_and_artifact"
    assert guarded.metadata["original_response_format"] == "content_and_artifact"
    assert tool_message.content == "南京天气晴朗"
    assert tool_message.artifact["tool_guard_status"] == "success"
    assert events[0]["name"] == "get_weather_forecast"
    assert events[0]["status"] == "success"
    assert events[0]["evidence_type"] == "mcp_live_query"


@pytest.mark.asyncio
async def test_guard_mcp_tool_blocks_placeholder_args_with_visible_fallback_and_skipped_event():
    calls = []

    async def raw_tool(city: str):
        calls.append(city)
        raise AssertionError("raw MCP tool should not run with placeholder args")

    raw = StructuredTool.from_function(
        coroutine=raw_tool,
        name="get_weather_forecast",
        description="天气查询",
    )
    guarded = guard_mcp_tool(raw)

    direct_result = await guarded.ainvoke({"city": "城市"})
    tool_message = await guarded.ainvoke(
        {
            "type": "tool_call",
            "id": "call-skipped",
            "name": "get_weather_forecast",
            "args": {"city": "城市"},
        }
    )
    events = _extract_embedded_tool_audit_events(tool_message)

    assert guarded.metadata["execution_guard"] == "tool_execution_guard"
    assert guarded.metadata["original_response_format"] == "content"
    assert "未得到可靠结果" in direct_result
    assert "tool_guard_failed" not in direct_result
    assert calls == []
    assert tool_message.artifact["tool_guard_status"] == "skipped"
    assert events[0]["status"] == "skipped"
    assert events[0]["error_type"] == "invalid_mcp_tool_args"


@pytest.mark.asyncio
async def test_guard_mcp_tool_emits_timeout_event(monkeypatch):
    async def raw_tool(city: str):
        await asyncio.sleep(0.05)
        return f"{city}天气晴朗"

    raw = StructuredTool.from_function(
        coroutine=raw_tool,
        name="get_weather_forecast",
        description="天气查询",
    )
    guarded = guard_mcp_tool(raw)
    monkeypatch.setattr(mcp_tools, "MCP_TOOL_TIMEOUT_SECONDS", 0.001)

    tool_message = await guarded.ainvoke(
        {
            "type": "tool_call",
            "id": "call-timeout",
            "name": "get_weather_forecast",
            "args": {"city": "南京"},
        }
    )
    events = _extract_embedded_tool_audit_events(tool_message)

    assert "未得到可靠结果" in tool_message.content
    assert tool_message.artifact["tool_guard_status"] == "timeout"
    assert events[0]["status"] == "timeout"
    assert events[0]["error_type"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_guard_mcp_tool_emits_degraded_event_for_unreliable_content():
    async def raw_tool(city: str):
        return f"{city}天气结果待核验"

    raw = StructuredTool.from_function(
        coroutine=raw_tool,
        name="get_weather_forecast",
        description="天气查询",
    )
    guarded = guard_mcp_tool(raw)

    tool_message = await guarded.ainvoke(
        {
            "type": "tool_call",
            "id": "call-degraded",
            "name": "get_weather_forecast",
            "args": {"city": "南京"},
        }
    )
    events = _extract_embedded_tool_audit_events(tool_message)

    assert tool_message.content == "南京天气结果待核验"
    assert tool_message.artifact["tool_guard_status"] == "degraded"
    assert events[0]["status"] == "degraded"
    assert events[0]["error_type"] == "mcp_result_requires_verification"


def test_chat_stream_prefers_embedded_tool_audit_event_from_command():
    context = start_tool_audit("query_hotel_options")
    event = build_tool_audit_event(
        context,
        status="degraded",
        input_summary={"destination": "南京"},
        output_summary={"message": "empty"},
        error_type="empty_hotel_result",
        evidence_type="live_hotel_search",
    )
    command = Command(update={"tool_audit_events": [event]})

    assert _extract_embedded_tool_audit_events(command) == [event]
