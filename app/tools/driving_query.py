"""
Deterministic driving-route query wrapper for AMap MCP tools.
"""
import json
from typing import Any, Optional

from langchain.tools import tool

from app.mcp_core.client import get_mcp_client
from app.utils.logger import app_logger


def _extract_text_payload(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text", ""))
    if isinstance(result, dict) and result.get("type") == "text":
        return str(result.get("text", ""))
    return str(result)


def _parse_json_text(result: Any) -> dict[str, Any]:
    text = _extract_text_payload(result)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _format_distance(distance_meters: float) -> str:
    if distance_meters >= 1000:
        return f"{distance_meters / 1000:.1f} 公里"
    return f"{distance_meters:.0f} 米"


def _format_duration(duration_seconds: float) -> str:
    total_minutes = int(round(duration_seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def _estimate_driving_cost(distance_km: float) -> tuple[float, float, float]:
    fuel_cost = distance_km * 0.07 * 8
    toll_cost = distance_km * 0.45
    return fuel_cost, toll_cost, fuel_cost + toll_cost


async def _get_amap_tool(name: str):
    manager = await get_mcp_client(servers=["amap"])
    tools = await manager.get_tools(servers=["amap"])
    for tool_item in tools:
        if tool_item.name == name:
            return tool_item
    raise RuntimeError(f"AMap tool not available: {name}")


async def _resolve_location(address: str, city: Optional[str] = None) -> tuple[str, str]:
    geo_tool = await _get_amap_tool("maps_geo")
    payload = {"address": address}
    if city:
        payload["city"] = city
    result = await geo_tool.ainvoke(payload)
    data = _parse_json_text(result)
    candidates = data.get("results") or []
    if not candidates:
        raise RuntimeError(f"无法解析地址坐标：{address}")
    location = candidates[0].get("location")
    if not location:
        raise RuntimeError(f"地址缺少坐标：{address}")
    label = candidates[0].get("formatted_address") or address
    return str(location), str(label)


def _route_summary(
    *,
    origin_label: str,
    destination_label: str,
    route_data: dict[str, Any],
) -> str:
    paths = route_data.get("paths") or []
    if not paths:
        return "未查询到可用自驾路线，请换更具体的出发地/目的地后重试。"

    path = paths[0]
    distance_meters = float(path.get("distance") or 0)
    duration_seconds = float(path.get("duration") or 0)
    distance_km = distance_meters / 1000
    fuel_cost, toll_cost, total_cost = _estimate_driving_cost(distance_km)
    steps = path.get("steps") or []
    main_roads = []
    for step in steps:
        road = step.get("road")
        if road and road not in main_roads:
            main_roads.append(str(road))
        if len(main_roads) >= 5:
            break

    lines = [
        f"自驾查询条件：{origin_label} -> {destination_label}",
        "",
        "自驾路线摘要：",
        f"- 总距离：{_format_distance(distance_meters)}",
        f"- 预计时长：{_format_duration(duration_seconds)}",
        f"- 油费估算：约 {fuel_cost:.0f} 元（按 7L/100km、8 元/L）",
        f"- 过路费估算：约 {toll_cost:.0f} 元（按长途高速经验值估算）",
        f"- 自驾总成本估算：约 {total_cost:.0f} 元/车",
    ]
    if main_roads:
        lines.append(f"- 主要道路：{'、'.join(main_roads)}")
    lines.extend(
        [
            "",
            "提醒：自驾时长来自高德实时路线字段，费用为估算值；长距离自驾需要额外考虑疲劳驾驶、休息和停车成本。",
        ]
    )
    return "\n".join(lines)


@tool
async def query_driving_route(origin: str, destination: str) -> str:
    """Query and format a driving route using AMap geocoding and driving direction tools."""

    app_logger.info(f"调用 query_driving_route: {origin} -> {destination}")
    try:
        origin_location, origin_label = await _resolve_location(origin, origin)
        destination_location, destination_label = await _resolve_location(destination, destination)
        driving_tool = await _get_amap_tool("maps_direction_driving")
        route_result = await driving_tool.ainvoke(
            {
                "origin": origin_location,
                "destination": destination_location,
            }
        )
        route_data = _parse_json_text(route_result)
    except Exception as exc:
        app_logger.warning(f"Driving route query failed: {exc}")
        return f"自驾路线查询失败：{exc}"

    return _route_summary(
        origin_label=origin_label,
        destination_label=destination_label,
        route_data=route_data,
    )
