"""
Router 查询工具
"""
import time
import re
from typing import Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agents.routers.destination_router import create_destination_router
from app.core.state import TravelState
from app.tools.execution_guard import (
    audited_command,
    begin_tool_execution,
    fail_tool_execution,
    finalize_tool_execution,
)
from app.tools.guardrails import validate_destination_query_args
from app.tools.result_validation import validate_rag_result
from app.utils.logger import app_logger


_COMMON_DESTINATION_ATTRACTIONS = {
    "上海": ["外滩", "上海博物馆", "豫园", "田子坊", "南京路步行街", "陆家嘴", "东方明珠", "武康路"],
    "北京": ["故宫", "天安门广场", "颐和园", "天坛", "什刹海", "南锣鼓巷", "国家博物馆"],
    "西安": ["秦始皇兵马俑", "西安城墙", "钟楼", "鼓楼", "回民街", "大雁塔", "陕西历史博物馆"],
    "杭州": ["西湖", "灵隐寺", "河坊街", "京杭大运河", "西溪湿地", "龙井村"],
    "成都": ["宽窄巷子", "武侯祠", "锦里", "成都大熊猫繁育研究基地", "杜甫草堂", "人民公园"],
    "广州": ["陈家祠", "沙面", "广州塔", "越秀公园", "北京路步行街", "永庆坊"],
}


def _tool_message(content: str, runtime: Optional[ToolRuntime]) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=getattr(runtime, "tool_call_id", ""),
    )


def _extract_description(destination: str, report: str) -> str:
    for line in report.splitlines():
        stripped = line.strip(" -*#\t")
        if not stripped:
            continue
        if stripped.startswith("信息来源") or stripped.startswith("天气信息"):
            continue
        if destination in stripped or len(stripped) >= 12:
            return stripped[:180]
    return f"{destination}目的地信息已查询，适合结合用户偏好继续规划。"


def _extract_weather_info(report: str) -> Optional[str]:
    weather_match = re.search(r"##\s*.+?天气信息\s*(.*?)(?:\n##|\Z)", report, re.S)
    if not weather_match:
        return None

    lines = []
    for line in weather_match.group(1).splitlines():
        stripped = line.strip(" -\t")
        if stripped:
            lines.append(stripped)
        if len(lines) >= 3:
            break
    return "；".join(lines)[:500] if lines else None


def _extract_attractions(destination: str, report: str) -> list[str]:
    candidates = _COMMON_DESTINATION_ATTRACTIONS.get(destination.strip(), [])
    found = [name for name in candidates if name in report]
    return (found or candidates)[:6]


def _build_destination_context(destination: str, report: str) -> dict:
    return {
        "name": destination,
        "description": _extract_description(destination, report),
        "weather_info": _extract_weather_info(report),
        "attractions": _extract_attractions(destination, report),
        "estimated_cost": None,
    }


def _merge_destination_options(options: list[dict], destination_info: dict) -> list[dict]:
    merged = [dict(option) for option in options or []]
    for index, option in enumerate(merged):
        if option.get("name") == destination_info["name"]:
            merged[index] = {
                **option,
                **{key: value for key, value in destination_info.items() if value not in (None, "", [])},
            }
            return merged
    return [destination_info, *merged]


def _command_with_destination_context(
    destination: str,
    report: str,
    runtime: Optional[ToolRuntime],
) -> Command:
    state = runtime.state if runtime and runtime.state else TravelState(messages=[])
    destination_info = _build_destination_context(destination, report)
    return Command(
        update={
            "messages": [_tool_message(report, runtime)],
            "destination_options": _merge_destination_options(
                state.get("destination_options") or [],
                destination_info,
            ),
        }
    )


@tool
async def query_destination_info(
    destination: str,
    query: str = "",
    runtime: ToolRuntime[None, TravelState] = None,
) -> str | Command:
    """
    查询目的地详细信息（并行查询多个源）

    此工具会调用 Router，并行执行：
    1. 探索 Agent：从 RAG 系统检索景点攻略
    2. 天气 Agent：查询实时天气信息

    参数：
    - destination: 目的地名称，如 "西安"
    - query: 具体查询（可选），如 "景点推荐"

    返回：
    - 综合的目的地信息（景点 + 天气）
    """

    guard = begin_tool_execution(
        "query_destination_info",
        {"destination": destination, "query": query},
        runtime=runtime,
        input_validator=validate_destination_query_args,
        evidence_type="destination_router_evidence",
    )
    if not guard.ok and guard.blocked_event is not None:
        message = f"目的地信息查询参数不完整：{guard.blocked_message}。请先补齐目的地后再查。"
        if runtime is None:
            return message
        return audited_command(
            {"messages": [_tool_message(message, runtime)]},
            runtime,
            guard.blocked_event,
            approval_update=guard.approval_update,
        )

    destination = str(guard.args["destination"])
    query = str(guard.args.get("query") or "")
    started_at = time.perf_counter()
    app_logger.info(
        "Destination router query started: "
        f"destination={destination}, query={query or '(default)'}"
    )

    # 创建 Router
    router = create_destination_router()

    # 如果没有提供具体查询，使用默认
    if not query:
        query = f"推荐{destination}旅游"

    try:
        result = await router.ainvoke({
            "original_query": query,
            "destination": destination
        })
    except Exception as exc:
        event = fail_tool_execution(
            guard,
            exc,
            output_summary={"message": "destination router failed"},
        )
        message = (
            f"{destination}目的地信息查询暂时失败：{exc.__class__.__name__}。"
            "请把实时天气、开放时间和预约信息标注为待二次核实。"
        )
        if runtime is None:
            return message
        return audited_command(
            {"messages": [_tool_message(message, runtime)]},
            runtime,
            event,
        )
    elapsed = time.perf_counter() - started_at
    app_logger.info(
        "Destination router query completed: "
        f"destination={destination}, elapsed_seconds={elapsed:.2f}"
    )

    # 返回综合报告，并把可跨阶段复用的目的地上下文写入状态。
    final_report = result["final_report"]
    validation = validate_rag_result(final_report)
    event = finalize_tool_execution(
        guard,
        validation,
        output_summary=validation.output_summary,
    )
    if runtime is None:
        return final_report
    command = _command_with_destination_context(destination, final_report, runtime)
    return audited_command(command.update, runtime, event)
