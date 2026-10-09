"""Tool for map-first visual journey drafts."""
from __future__ import annotations

from typing import Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.core.state import TravelState
from app.journey.enrichment import enrich_visual_journey_result
from app.journey.visual_planner import build_visual_journey_plan, validate_journey_plan


def _tool_message(content: str, runtime: Optional[ToolRuntime]) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=getattr(runtime, "tool_call_id", ""),
    )


def _runtime_state(runtime: Optional[ToolRuntime]) -> TravelState:
    if runtime and runtime.state:
        return runtime.state
    return TravelState(messages=[])


@tool
async def generate_visual_journey_tool(
    destination: str = "",
    date_text: str = "",
    days: int | None = None,
    style_query: str = "",
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Generate a map-first visual journey draft before transport/hotel/report gates.

    Use this when the user asks for a classic route, visual route, itinerary map,
    or "先排路线/几天经典线" style answer. This tool does not create a final
    report, order, booking, locked price, transport ticket, or hotel reservation.
    """

    state = _runtime_state(runtime)
    result = build_visual_journey_plan(
        destination=destination,
        date_text=date_text,
        days=days,
        style_query=style_query,
        state=state,
    )
    result = await enrich_visual_journey_result(result)
    journey_plan = result["journey_plan"]
    ok, findings = validate_journey_plan(journey_plan)
    if not ok:
        message = "可视化旅程草案生成失败：" + "；".join(findings)
        return Command(update={"messages": [_tool_message(message, runtime)]})

    overview = journey_plan.get("overview") or {}
    destination_name = overview.get("destination") or destination or "目的地"
    poi_names = [
        str(poi.get("name"))
        for poi in journey_plan.get("pois", [])[:6]
        if isinstance(poi, dict) and poi.get("name")
    ]
    message = (
        f"已生成{destination_name}的可视化旅程草案："
        f"{overview.get('route_label') or overview.get('title') or '经典路线'}。"
        "地图里可以先看总览和每天路线；交通、酒店、预算和最终报告会在后续继续核验。"
    )
    if poi_names:
        message += f" 核心地点包括：{'、'.join(poi_names)}。"

    destination_option = {
        "name": destination_name,
        "description": overview.get("summary") or "",
        "weather_info": "天气、开放和预约规则待实时核验。",
        "attractions": poi_names,
        "attraction_pois": [
            {
                "name": poi.get("name"),
                "area": poi.get("city"),
                "best_time": poi.get("suggested_time"),
                "duration_hours": round((poi.get("duration_minutes") or 120) / 60, 1),
                "reservation_required": True,
                "estimated_cost": None,
                "tags": poi.get("tags") or [],
            }
            for poi in journey_plan.get("pois", [])[:10]
            if isinstance(poi, dict) and poi.get("name")
        ],
    }
    existing_options = state.get("destination_options") or []
    merged_options = [destination_option]
    for option in existing_options:
        if isinstance(option, dict) and option.get("name") != destination_name:
            merged_options.append(option)

    return Command(
        update={
            "messages": [_tool_message(message, runtime)],
            "journey_plan": journey_plan,
            "planning_trace": result["planning_trace"],
            "selected_destination": state.get("selected_destination") or destination_name,
            "destination_options": merged_options,
            "current_step": state.get("current_step") or "destination_recommendation",
        }
    )
