"""
交通查询工具
调用交通规划协调器（Subagents 主 Agent）
"""
from __future__ import annotations

from typing import Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.config import settings
from app.agents.subagents.transport_coordinator import create_transport_coordinator
from app.core.state import TravelState
from app.tools.audit import (
    append_tool_audit_event,
    build_tool_audit_event,
    start_tool_audit,
    summarize_tool_input,
)
from app.tools.guardrails import validate_transport_query_args
from app.tools.result_validation import classify_exception, validate_transport_result
from app.utils.logger import app_logger


def _tool_message(content: str, runtime: Optional[ToolRuntime]) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=getattr(runtime, "tool_call_id", ""),
    )


def _normalize_args_from_state(
    *,
    origin_city: str,
    destination_city: str,
    departure_date: str,
    transport_type: Optional[str],
    runtime: Optional[ToolRuntime],
) -> dict:
    state = runtime.state if runtime and runtime.state else {}
    requirement = state.get("user_requirement") or {}
    normalized_origin = origin_city
    if str(origin_city or "").strip() in {"", "出发地", "城市", "未确认", "origin"}:
        normalized_origin = requirement.get("departure_city") or origin_city

    normalized_destination = destination_city
    if str(destination_city or "").strip() in {"", "目的地", "城市", "未确认", "destination"}:
        normalized_destination = (
            state.get("selected_destination")
            or requirement.get("destination")
            or destination_city
        )

    normalized_date = departure_date
    if str(departure_date or "").strip() in {"", "日期", "出发日期", "未确认", "departure_date"}:
        normalized_date = requirement.get("departure_date") or departure_date

    normalized_type = transport_type or None
    return {
        "origin_city": normalized_origin,
        "destination_city": normalized_destination,
        "departure_date": normalized_date,
        "transport_type": normalized_type,
    }


@tool
async def query_transport_options(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    transport_type: str = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """
    查询交通选项（调用交通规划协调器）

    参数说明：
    - origin_city: 出发城市
    - destination_city: 目的地城市
    - departure_date: 出发日期，格式 YYYY-MM-DD
    - transport_type: 交通方式（可选），可选值：flight（航班）、train（高铁）、driving（自驾）

    返回：
    - 格式化的交通选项信息
    """

    audit_context = start_tool_audit("query_transport_options")
    normalized_args = _normalize_args_from_state(
        origin_city=origin_city,
        destination_city=destination_city,
        departure_date=departure_date,
        transport_type=transport_type,
        runtime=runtime,
    )
    input_summary = summarize_tool_input(normalized_args)
    validation = validate_transport_query_args(normalized_args)
    if not validation.ok:
        message = f"交通真实查询参数不完整：{validation.message}。请先补齐后再查，我不会编造车次、航班或价格。"
        event = build_tool_audit_event(
            audit_context,
            status="skipped",
            input_summary=input_summary,
            output_summary={"message": validation.message},
            error_type=validation.error_type,
            evidence_type="live_transport_query",
        )
        state = runtime.state if runtime and runtime.state else {}
        return Command(
            update=append_tool_audit_event(
                state,
                {"messages": [_tool_message(message, runtime)]},
                event,
            )
        )

    origin_city = str(normalized_args["origin_city"])
    destination_city = str(normalized_args["destination_city"])
    departure_date = str(normalized_args["departure_date"])
    transport_type = normalized_args["transport_type"]
    app_logger.info(
        "Transport query started: "
        f"origin={origin_city}, destination={destination_city}, "
        f"departure_date={departure_date}, transport_type={transport_type or 'auto'}"
    )

    # 构建用户查询
    if transport_type:
        type_labels = {
            "flight": "航班",
            "train": "高铁",
            "driving": "自驾"
        }
        user_query = (
            f"我想从 {origin_city} 去 {destination_city}，"
            f"出发日期是 {departure_date}，"
            f"我当前更偏向 {type_labels.get(transport_type, transport_type)}，"
            f"请优先给我这种方式的真实方案；"
            f"如果同一天还有明显更省时、更省心或更省钱的替代方式，也请顺带对比 1-2 个，"
            f"不要因为我提到了 {type_labels.get(transport_type, transport_type)} 就默认排除其他交通方式。"
        )
    else:
        user_query = (
            f"我想从 {origin_city} 去 {destination_city}，"
            f"出发日期是 {departure_date}，"
            f"请推荐合适的交通方式并提供详细信息。"
        )

    try:
        coordinator = await create_transport_coordinator()
        result = await coordinator.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": user_query}
                ]
            },
            config={"recursion_limit": settings.langgraph_recursion_limit},
        )
        content = result["messages"][-1].content
    except Exception as exc:
        status, error_type = classify_exception(exc)
        message = str(exc).strip() or exc.__class__.__name__
        app_logger.warning(
            "Transport query failed without crashing workflow: "
            f"origin={origin_city}, destination={destination_city}, error={message}"
        )
        audit_event = build_tool_audit_event(
            audit_context,
            status=status,
            input_summary=input_summary,
            output_summary={"message": message},
            error_type=error_type,
            evidence_type="live_transport_query",
        )
        state = runtime.state if runtime and runtime.state else {}
        return Command(
            update=append_tool_audit_event(
                state,
                {
                    "messages": [
                        _tool_message(
                            f"交通查询这次调用失败：{message}。我不会编造车次、航班或价格；可以稍后重试真实交通查询。",
                            runtime,
                        )
                    ]
                },
                audit_event,
            )
        )

    result_validation = validate_transport_result(content)
    audit_event = build_tool_audit_event(
        audit_context,
        status=result_validation.status,
        input_summary=input_summary,
        output_summary=result_validation.output_summary,
        error_type=result_validation.error_type,
        evidence_type="live_transport_query",
    )
    app_logger.info(
        "Transport query completed: "
        f"origin={origin_city}, destination={destination_city}, "
        f"elapsed_seconds={audit_event['elapsed_seconds']:.2f}"
    )
    state = runtime.state if runtime and runtime.state else {}
    return Command(
        update=append_tool_audit_event(
            state,
            {"messages": [_tool_message(content, runtime)]},
            audit_event,
        )
    )
