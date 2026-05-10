"""Post-call validation for planner-facing tool results."""
from __future__ import annotations

import asyncio
from typing import Any

from app.tools.audit import summarize_tool_output
from app.tools.contracts import ToolResultValidation


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
            status="failed",
            output_summary=output_summary,
            error_type="empty_transport_result",
            message="交通工具未返回可用内容",
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

