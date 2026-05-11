"""
Flight query tools that wrap VariFlight MCP APIs with planner-friendly inputs.
"""
from __future__ import annotations

import ast
import re
from datetime import datetime
from typing import Any, Optional

from langchain.tools import tool

from app.mcp_core.client import get_mcp_client
from app.tools.execution_guard import execute_guarded_call
from app.tools.guardrails import validate_transport_query_args
from app.tools.result_validation import validate_transport_result
from app.utils.logger import app_logger


CITY_IATA_CODES = {
    "北京": "BJS",
    "北京市": "BJS",
    "上海": "SHA",
    "上海市": "SHA",
    "广州": "CAN",
    "广州市": "CAN",
    "深圳": "SZX",
    "深圳市": "SZX",
    "杭州": "HGH",
    "杭州市": "HGH",
    "南京": "NKG",
    "南京市": "NKG",
    "成都": "CTU",
    "成都市": "CTU",
    "重庆": "CKG",
    "重庆市": "CKG",
    "西安": "XIY",
    "西安市": "XIY",
    "武汉": "WUH",
    "武汉市": "WUH",
    "长沙": "CSX",
    "长沙市": "CSX",
    "厦门": "XMN",
    "厦门市": "XMN",
    "青岛": "TAO",
    "青岛市": "TAO",
    "天津": "TSN",
    "天津市": "TSN",
    "三亚": "SYX",
    "昆明": "KMG",
    "大理": "DLU",
    "丽江": "LJG",
    "哈尔滨": "HRB",
    "拉萨": "LXA",
}
TOOL_AUDIT_EVENTS_ARTIFACT_KEY = "tool_audit_events"
FLIGHT_QUERY_TIMEOUT_SECONDS = 45.0


def resolve_city_iata_code(city: str) -> str:
    """Resolve a Chinese city name or IATA code into a city IATA code."""
    normalized = city.strip()
    if re.fullmatch(r"[A-Za-z]{3}", normalized):
        return normalized.upper()
    return CITY_IATA_CODES.get(normalized) or CITY_IATA_CODES.get(normalized.rstrip("市")) or normalized


def _extract_text_blocks(result: Any) -> str:
    if isinstance(result, list):
        text_blocks = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                text_blocks.append(item.get("text", ""))
            else:
                text_blocks.append(str(item))
        return "\n".join(text_blocks)
    return str(result)


def _parse_prefixed_python_payload(text: str, prefix: str) -> dict[str, Any]:
    payload_text = text.strip()
    if payload_text.startswith(prefix):
        payload_text = payload_text[len(prefix):].strip()

    try:
        parsed = ast.literal_eval(payload_text)
    except (SyntaxError, ValueError):
        return {"code": None, "message": payload_text, "data": None}

    return parsed if isinstance(parsed, dict) else {"code": None, "message": str(parsed), "data": parsed}


def _format_timestamp(timestamp: Any) -> str:
    if not isinstance(timestamp, (int, float)):
        return "时间待确认"
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")


def _lowest_cabin(flight: dict[str, Any]) -> Optional[dict[str, Any]]:
    cabins = flight.get("cabins") or []
    priced_cabins = [
        cabin
        for cabin in cabins
        if isinstance(cabin, dict) and isinstance(cabin.get("price"), (int, float))
    ]
    if not priced_cabins:
        return None
    return min(priced_cabins, key=lambda cabin: cabin["price"])


def _format_price_flights(flights: list[dict[str, Any]], max_results: int) -> str:
    candidates = []
    for flight in flights:
        cabin = _lowest_cabin(flight)
        if not cabin:
            continue
        candidates.append((cabin["price"], flight, cabin))

    candidates.sort(key=lambda item: (item[0], item[1].get("flightdeptimeplandate") or 0))
    if not candidates:
        return "暂无可展示的舱位价格明细。"

    lines = ["结构化低价候选："]
    for index, (price, flight, cabin) in enumerate(candidates[:max_results], start=1):
        dep_time = _format_timestamp(flight.get("flightdeptimeplandate"))
        arr_time = _format_timestamp(flight.get("flightarrtimeplandate"))
        dep_airport = flight.get("depaptcname") or flight.get("flightdepcode") or "出发机场待确认"
        arr_airport = flight.get("arraptcname") or flight.get("flightarrcode") or "到达机场待确认"
        stop_text = "直飞" if not flight.get("stopflag") else "经停/中转"
        lines.append(
            (
                f"{index}. {flight.get('flightno', '未知航班')} "
                f"{dep_airport} {dep_time} -> {arr_airport} {arr_time}，"
                f"{stop_text}，{cabin.get('classname', '舱位')} 约 {price} 元，"
                f"余票 {cabin.get('seatnum', '未知')}"
            )
        )
    return "\n".join(lines)


def _compact_itinerary_summary(text: str) -> str:
    """Keep VariFlight's narrative summary, but drop long recommended-flight lists."""

    cleaned = text.strip()
    if not cleaned:
        return ""

    stop_markers = (
        "其他推荐航班",
        "推荐航班",
        "航班列表",
        "更多航班",
    )
    for marker in stop_markers:
        marker_index = cleaned.find(marker)
        if marker_index != -1:
            cleaned = cleaned[:marker_index].strip(" \n：:")
            break

    fragments = re.split(r"(?<=[。；;])\s*|\n+", cleaned)
    useful_fragments = [
        fragment.strip()
        for fragment in fragments
        if fragment.strip()
        and any(keyword in fragment for keyword in ("查询到", "最低价", "最短耗时", "最早", "最晚"))
    ]
    if useful_fragments:
        return "\n".join(useful_fragments[:3])
    return cleaned[:300]


async def _get_aviation_tool(tool_name: str) -> Any | None:
    manager = await get_mcp_client(servers=["VariFlight-Aviation"])
    tools = await manager.get_tools(servers=["VariFlight-Aviation"])
    for tool_instance in tools:
        if tool_instance.name == tool_name:
            return tool_instance
    return None


async def _query_flight_options_raw(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    max_results: int = 5,
) -> str:
    itinerary_tool = await _get_aviation_tool("searchFlightItineraries")
    price_tool = await _get_aviation_tool("getFlightPriceByCities")
    if itinerary_tool is None and price_tool is None:
        return "航班查询服务当前不可用，请稍后再试，或先考虑高铁/自驾备选。"

    dep_code = resolve_city_iata_code(origin_city)
    arr_code = resolve_city_iata_code(destination_city)
    normalized_max = min(max(max_results, 3), 8)

    app_logger.info(
        f"调用 query_flight_options: {origin_city}({dep_code}) -> "
        f"{destination_city}({arr_code}), date={departure_date}"
    )

    sections = [
        f"航班查询条件：{origin_city}({dep_code}) -> {destination_city}({arr_code})，{departure_date}",
    ]

    if itinerary_tool is not None:
        itinerary_result = await itinerary_tool.ainvoke(
            {
                "depCityCode": dep_code,
                "arrCityCode": arr_code,
                "depDate": departure_date,
            }
        )
        itinerary_payload = _parse_prefixed_python_payload(
            _extract_text_blocks(itinerary_result),
            "Flight itineraries:",
        )
        itinerary_text = itinerary_payload.get("data")
        if isinstance(itinerary_text, str) and itinerary_text.strip():
            compact_summary = _compact_itinerary_summary(itinerary_text)
            if compact_summary:
                sections.extend(["", "推荐摘要：", compact_summary])

    if price_tool is not None:
        price_result = await price_tool.ainvoke(
            {
                "dep_city": dep_code,
                "arr_city": arr_code,
                "dep_date": departure_date,
            }
        )
        price_payload = _parse_prefixed_python_payload(
            _extract_text_blocks(price_result),
            "Flight prices:",
        )
        price_data = price_payload.get("data")
        if isinstance(price_data, list):
            sections.extend(["", _format_price_flights(price_data, normalized_max)])

    sections.append("")
    sections.append("提示：航班价格和余票会随库存实时变化，正式预订前需要再次核实。")
    return "\n".join(sections)


@tool(response_format="content_and_artifact")
async def query_flight_options(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    max_results: int = 5,
) -> tuple[str, dict[str, Any]]:
    """
    查询真实航班方案，自动转换城市 IATA 码，并返回推荐摘要和低价候选。
    """

    async def _call(guarded_args: dict[str, Any]) -> str:
        return await _query_flight_options_raw(
            origin_city=str(guarded_args["origin_city"]),
            destination_city=str(guarded_args["destination_city"]),
            departure_date=str(guarded_args["departure_date"]),
            max_results=int(guarded_args.get("max_results") or max_results),
        )

    guarded = await execute_guarded_call(
        "query_flight_options",
        {
            "origin_city": origin_city,
            "destination_city": destination_city,
            "departure_date": departure_date,
            "transport_type": "flight",
            "max_results": max_results,
        },
        _call,
        input_validator=validate_transport_query_args,
        result_validator=validate_transport_result,
        evidence_type="live_transport_query",
        timeout_seconds=FLIGHT_QUERY_TIMEOUT_SECONDS,
    )
    artifact = {
        TOOL_AUDIT_EVENTS_ARTIFACT_KEY: [guarded.event],
        "tool_guard_status": guarded.status,
        "tool_guard_error_type": guarded.error_type,
    }
    if guarded.output is not None:
        return str(guarded.output), artifact

    fallback = (
        f"航班查询这次未得到可靠结果（{guarded.error_type or 'tool_guard_failed'}）。"
        "我不会编造航班、票价或余票；请标注为待二次核实，稍后可重新查询。"
    )
    return fallback, artifact
