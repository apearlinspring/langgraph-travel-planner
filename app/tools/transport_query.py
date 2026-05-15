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
from app.tools.execution_guard import audited_command, execute_guarded_call
from app.tools.guardrails import validate_transport_query_args
from app.tools.result_validation import validate_transport_result
from app.utils.logger import app_logger


TRANSPORT_QUERY_TIMEOUT_SECONDS = 60.0
PENDING_DATE_VALUES = {
    "",
    "日期",
    "日期待确认",
    "出发日期",
    "出发日期待确认",
    "待确认",
    "未确认",
    "待核验",
    "待核实",
}


def _tool_message(content: str, runtime: Optional[ToolRuntime]) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=getattr(runtime, "tool_call_id", ""),
    )


def _requirement_departure_date_confirmation(
    requirement: dict,
    normalized_date: str,
) -> tuple[bool | None, str]:
    if not requirement:
        return None, ""

    date_text = str(normalized_date or "").strip()
    if date_text in PENDING_DATE_VALUES:
        return False, "pending"
    if requirement.get("departure_date_confirmed") is False:
        return False, str(requirement.get("departure_date_source") or "unconfirmed")
    if requirement.get("departure_date_confirmed") is True:
        return True, str(requirement.get("departure_date_source") or "user_confirmed")
    return True, str(requirement.get("departure_date_source") or "legacy_confirmed")


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

    date_confirmed, date_source = _requirement_departure_date_confirmation(
        requirement,
        str(normalized_date or ""),
    )
    normalized_type = transport_type or None
    normalized_args = {
        "origin_city": normalized_origin,
        "destination_city": normalized_destination,
        "departure_date": normalized_date,
        "transport_type": normalized_type,
    }
    if date_confirmed is not None:
        normalized_args["departure_date_confirmed"] = date_confirmed
        normalized_args["departure_date_source"] = date_source
    return normalized_args


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

    normalized_args = _normalize_args_from_state(
        origin_city=origin_city,
        destination_city=destination_city,
        departure_date=departure_date,
        transport_type=transport_type,
        runtime=runtime,
    )

    async def _call_transport(guarded_args: dict) -> str:
        guarded_origin = str(guarded_args["origin_city"])
        guarded_destination = str(guarded_args["destination_city"])
        guarded_date = str(guarded_args["departure_date"])
        guarded_type = guarded_args["transport_type"]
        app_logger.info(
            "Transport query started: "
            f"origin={guarded_origin}, destination={guarded_destination}, "
            f"departure_date={guarded_date}, transport_type={guarded_type or 'auto'}"
        )

        if guarded_type:
            type_labels = {
                "flight": "航班",
                "train": "高铁",
                "driving": "自驾",
            }
            type_label = type_labels.get(guarded_type, guarded_type)
            user_query = (
                f"我想从 {guarded_origin} 去 {guarded_destination}，"
                f"出发日期是 {guarded_date}，"
                f"本轮已确认先按 {type_label} 查询。"
                f"请只调用 {type_label} 对应的真实查询工具，给出这种方式的可核验方案；"
                "不要在同一轮额外查询其他交通方式。"
                "如果你认为存在明显更合适的替代交通，只用一句话提示可另行发起对比，"
                "不要编造未查询方式的班次、价格或库存。"
            )
        else:
            user_query = (
                f"我想从 {guarded_origin} 去 {guarded_destination}，"
                f"出发日期是 {guarded_date}，"
                f"请推荐合适的交通方式并提供详细信息。"
            )

        coordinator = await create_transport_coordinator()
        result = await coordinator.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": user_query}
                ]
            },
            config={"recursion_limit": settings.langgraph_recursion_limit},
        )
        return result["messages"][-1].content

    guarded = await execute_guarded_call(
        "query_transport_options",
        normalized_args,
        _call_transport,
        runtime=runtime,
        input_validator=validate_transport_query_args,
        result_validator=validate_transport_result,
        evidence_type="live_transport_query",
        timeout_seconds=TRANSPORT_QUERY_TIMEOUT_SECONDS,
    )
    if guarded.status == "skipped":
        if guarded.error_type == "duplicate_tool_call_same_turn":
            message = guarded.message
        else:
            message = f"交通真实查询参数不完整：{guarded.message}。请先补齐后再查，我不会编造车次、航班或价格。"
        return audited_command(
            {"messages": [_tool_message(message, runtime)]},
            runtime,
            guarded.event,
            approval_update=guarded.approval_update,
        )
    if guarded.output is None:
        message = guarded.message or guarded.error_type or "交通工具调用失败"
        app_logger.warning(
            "Transport query failed without crashing workflow: "
            f"origin={normalized_args.get('origin_city')}, "
            f"destination={normalized_args.get('destination_city')}, error={message}"
        )
        return audited_command(
            {
                "messages": [
                    _tool_message(
                        f"交通查询这次调用失败：{message}。我不会编造车次、航班或价格；可以稍后重试真实交通查询。",
                        runtime,
                    )
                ]
            },
            runtime,
            guarded.event,
        )

    app_logger.info(
        "Transport query completed: "
        f"origin={normalized_args.get('origin_city')}, destination={normalized_args.get('destination_city')}, "
        f"elapsed_seconds={guarded.event['elapsed_seconds']:.2f}"
    )
    return audited_command(
        {"messages": [_tool_message(str(guarded.output), runtime)]},
        runtime,
        guarded.event,
    )
