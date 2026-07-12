"""Post-call validation for planner-facing tool results."""
from __future__ import annotations

import asyncio
from typing import Any

from app.tools.audit import summarize_tool_output
from app.tools.contracts import ToolEvidenceType, ToolResultValidation
from app.utils.message_utils import (
    APPLIED_STATE_TRANSITION_STATUSES,
    state_transition_outcome_from_message,
)


ERROR_HINTS = (
    "不可用",
    "失败",
    "超时",
    "没有查到",
    "暂时没有",
    "待确认",
    "待核验",
    "error",
    "failed",
    "timeout",
)


def _state_transition_outcome_from_tool_output(
    tool_name: str,
    output: Any,
) -> dict[str, Any] | None:
    candidates = [output]
    update = (
        output.get("update")
        if isinstance(output, dict)
        else getattr(output, "update", None)
    )
    if isinstance(update, dict):
        messages = update.get("messages") or []
        if isinstance(messages, (list, tuple)):
            candidates.extend(reversed(messages))

    for candidate in candidates:
        outcome = state_transition_outcome_from_message(candidate)
        if outcome and outcome.get("tool") == tool_name:
            return outcome
    return None


def _validate_state_transition_outcome(
    tool_name: str,
    output: Any,
) -> ToolResultValidation | None:
    outcome = _state_transition_outcome_from_tool_output(tool_name, output)
    if not outcome:
        return None

    outcome_summary = {
        key: value
        for key in ("schema", "tool", "status", "reason", "next_step")
        if isinstance((value := outcome.get(key)), str) and value
    }
    output_summary = summarize_tool_output(output)
    output_summary["state_transition_outcome"] = outcome_summary
    if outcome["status"] == "not_applied":
        reason = str(outcome.get("reason") or "state_transition_not_applied")
        return ToolResultValidation(
            status="failed",
            output_summary=output_summary,
            error_type=reason,
            message="状态迁移工具已返回，但状态未应用。",
        )
    if outcome["status"] in APPLIED_STATE_TRANSITION_STATUSES:
        return ToolResultValidation(status="success", output_summary=output_summary)
    return None


def classify_exception(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout", "upstream_timeout"
    return "failed", exc.__class__.__name__


def validate_hotel_search_result(
    hotels: list[dict[str, Any]] | None,
    message: str = "",
) -> ToolResultValidation:
    hotel_count = len(hotels or [])
    output_summary = {
        "hotel_count": hotel_count,
        "message": message[:180] if message else "",
    }
    if hotel_count > 0:
        return ToolResultValidation(status="success", output_summary=output_summary)
    if "超时" in message or "timeout" in message.lower():
        return ToolResultValidation(
            status="timeout",
            output_summary=output_summary,
            error_type="upstream_timeout",
            message=message,
        )
    if message:
        return ToolResultValidation(
            status="degraded",
            output_summary=output_summary,
            error_type="empty_hotel_result",
            message=message,
        )
    return ToolResultValidation(
        status="degraded",
        output_summary=output_summary,
        error_type="empty_hotel_result",
        message="酒店工具未返回可用候选",
    )


def validate_transport_result(content: Any) -> ToolResultValidation:
    output_summary = summarize_tool_output(content)
    if not isinstance(content, str) or not content.strip():
        return ToolResultValidation(
            status="degraded",
            output_summary=output_summary,
            error_type="empty_transport_result",
            message="交通工具调用完成，但没有查到合适结果",
        )

    lowered = content.lower()
    if any(hint in lowered for hint in ERROR_HINTS):
        return ToolResultValidation(
            status="degraded",
            output_summary=output_summary,
            error_type="transport_result_requires_verification",
            message="交通工具返回内容包含失败或待核验信号",
        )
    return ToolResultValidation(status="success", output_summary=output_summary)


def validate_rag_result(content: Any) -> ToolResultValidation:
    output_summary = summarize_tool_output(content)
    text = content if isinstance(content, str) else str(content or "")
    lowered = text.lower()
    if not text.strip():
        return ToolResultValidation(
            status="failed",
            output_summary=output_summary,
            error_type="empty_rag_result",
            message="RAG 工具未返回证据内容",
        )
    if '"result_status": "empty"' in lowered or "检索暂时不可用" in text:
        return ToolResultValidation(
            status="degraded",
            output_summary=output_summary,
            error_type="rag_empty_or_unavailable",
            message="RAG 工具返回空证据或降级证据",
        )
    return ToolResultValidation(status="success", output_summary=output_summary)


def validate_mcp_result(content: Any) -> ToolResultValidation:
    output_summary = summarize_tool_output(content)
    text = content if isinstance(content, str) else str(content or "")
    lowered = text.lower()
    if not text.strip():
        return ToolResultValidation(
            status="failed",
            output_summary=output_summary,
            error_type="empty_mcp_result",
            message="MCP 工具未返回可用内容",
        )
    if "超时" in text or "timeout" in lowered:
        return ToolResultValidation(
            status="timeout",
            output_summary=output_summary,
            error_type="upstream_timeout",
            message="MCP 工具返回超时信号",
        )
    if any(hint in lowered for hint in ERROR_HINTS):
        return ToolResultValidation(
            status="degraded",
            output_summary=output_summary,
            error_type="mcp_result_requires_verification",
            message="MCP 工具返回失败或待核验信号",
        )
    return ToolResultValidation(status="success", output_summary=output_summary)


def evidence_type_for_tool_name(tool_name: str) -> ToolEvidenceType:
    if tool_name == "query_hotel_options":
        return "live_hotel_search"
    if tool_name in {
        "query_transport_options",
        "query_flight_options",
        "query_train_options",
        "query_driving_route",
        "query_flights",
        "query_trains",
        "plan_driving_route",
    }:
        return "live_transport_query"
    if tool_name == "query_destination_info":
        return "destination_router_evidence"
    if tool_name.startswith("search_agency_"):
        return "internal_rag_evidence"
    if tool_name in {
        "search_destination_guide",
        "search_food_recommendations",
        "search_accommodation_info",
        "search_travel_tips",
    }:
        return "public_rag_evidence"
    if tool_name:
        return "mcp_live_query"
    return "unknown"


def validate_tool_output_for_audit(tool_name: str, content: Any) -> ToolResultValidation:
    transition_validation = _validate_state_transition_outcome(tool_name, content)
    if transition_validation is not None:
        return transition_validation
    if tool_name == "query_hotel_options":
        return validate_mcp_result(content)
    if tool_name in {
        "query_transport_options",
        "query_flight_options",
        "query_train_options",
        "query_driving_route",
        "query_flights",
        "query_trains",
        "plan_driving_route",
    }:
        return validate_transport_result(content)
    if tool_name == "query_destination_info":
        return validate_rag_result(content)
    if tool_name.startswith("search_agency_") or tool_name in {
        "search_destination_guide",
        "search_food_recommendations",
        "search_accommodation_info",
        "search_travel_tips",
    }:
        return validate_rag_result(content)
    return validate_mcp_result(content)
