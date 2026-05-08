"""
Main handoff-style travel planning agent.
"""
import asyncio
from typing import Optional

from langchain.agents import create_agent

from app.config import settings
from app.core.checkpointer import get_checkpointer
from app.core.middleware import create_step_config_middleware
from app.core.state import TravelState
from app.tools.mcp_tools import get_all_mcp_tools, get_hotel_followup_tools
from app.tools.memory_tools import (
    add_travel_record_tool,
    update_accommodation_preference_tool,
    update_dietary_restriction_tool,
    update_food_preference_tool,
    update_travel_style_tool,
)
from app.tools.hotel_query import query_hotel_options
from app.tools.router_query import query_destination_info
from app.tools.state_transition import (
    ALL_ROLLBACK_TOOLS,
    generate_itinerary_tool,
    generate_order_tool,
    record_requirement_tool,
    select_accommodation_tool,
    select_destination_tool,
    select_food_tool,
    select_transport_tool,
    summarize_budget_tool,
)
from app.tools.transport_query import query_transport_options
from app.utils.llm_factory import build_chat_model
from app.utils.logger import app_logger

_travel_agent = None
_travel_agent_mcp_signature: tuple[str, ...] | None = None
_travel_agent_lock = asyncio.Lock()


def _build_tool_signature(*tool_groups) -> tuple[str, ...]:
    return tuple(
        sorted(
            tool.name
            for group in tool_groups
            for tool in group
            if getattr(tool, "name", None)
        )
    )


def get_llm():
    """Return the configured chat model."""
    return build_chat_model(profile="planner", streaming=True)


async def create_travel_agent():
    """Build the main travel planning agent and rebuild it when MCP availability changes."""
    global _travel_agent, _travel_agent_mcp_signature

    all_mcp_tools = await get_all_mcp_tools()
    hotel_followup_tools = await get_hotel_followup_tools()
    current_signature = _build_tool_signature(all_mcp_tools, hotel_followup_tools)

    if _travel_agent is not None and _travel_agent_mcp_signature == current_signature:
        return _travel_agent

    async with _travel_agent_lock:
        all_mcp_tools = await get_all_mcp_tools()
        hotel_followup_tools = await get_hotel_followup_tools()
        current_signature = _build_tool_signature(all_mcp_tools, hotel_followup_tools)

        if _travel_agent is not None and _travel_agent_mcp_signature == current_signature:
            return _travel_agent

        app_logger.info(
            f"Creating travel agent with {len(all_mcp_tools)} MCP tools "
            f"(signature={current_signature})"
        )

        llm = get_llm()
        step_config_middleware = await create_step_config_middleware()
        checkpointer = await get_checkpointer()

        all_tools = [
            record_requirement_tool,
            select_destination_tool,
            select_transport_tool,
            select_accommodation_tool,
            select_food_tool,
            generate_itinerary_tool,
            summarize_budget_tool,
            generate_order_tool,
            *ALL_ROLLBACK_TOOLS,
            query_destination_info,
            query_hotel_options,
            query_transport_options,
            update_travel_style_tool,
            update_dietary_restriction_tool,
            update_food_preference_tool,
            update_accommodation_preference_tool,
            add_travel_record_tool,
            *hotel_followup_tools,
            *all_mcp_tools,
        ]

        _travel_agent = create_agent(
            model=llm,
            tools=all_tools,
            state_schema=TravelState,
            middleware=[step_config_middleware],
            checkpointer=checkpointer,
        )
        _travel_agent_mcp_signature = current_signature

        app_logger.info("Travel agent is ready")
        return _travel_agent
