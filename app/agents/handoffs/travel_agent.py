"""Main stage-configured travel planning agent."""
import asyncio

from langchain.agents import create_agent

from app.config import settings
from app.core.checkpointer import get_checkpointer
from app.core.middleware import create_step_config_middleware
from app.core.state import TravelState
from app.tools.mcp_tools import get_all_mcp_tools, get_hotel_followup_tools
from app.tools.contracts import classify_tool_governance
from app.tools.memory_tools import (
    add_travel_record_tool,
    update_accommodation_preference_tool,
    update_dietary_restriction_tool,
    update_food_preference_tool,
    update_travel_style_tool,
)
from app.tools.rag_tools import get_internal_rag_tools
from app.tools.hotel_query import query_hotel_options
from app.tools.router_query import query_destination_info
from app.tools.state_transition import (
    ALL_ROLLBACK_TOOLS,
    confirm_planning_mode_tool,
    generate_itinerary_tool,
    generate_order_tool,
    record_evidence_bundle_tool,
    record_requirement_tool,
    scenic_price_lookup_tool,
    select_accommodation_tool,
    select_destination_tool,
    select_food_tool,
    select_transport_tool,
    set_planning_mode_tool,
    summarize_budget_tool,
)
from app.tools.transport_query import query_transport_options
from app.tools.visual_journey import generate_visual_journey_tool
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


def describe_tool_governance(tool) -> dict:
    """Return the governance coverage record for one registered tool."""

    record = classify_tool_governance(
        getattr(tool, "name", ""),
        metadata=getattr(tool, "metadata", None) or {},
    )
    return record.to_dict()


def describe_travel_agent_tool_governance(tools: list) -> list[dict]:
    """List every Travel Agent tool with its execution-governance coverage."""

    return [describe_tool_governance(tool) for tool in tools]


def get_llm():
    """Return the configured chat model."""
    return build_chat_model(profile="planner", streaming=True)


def _with_recursion_limit(agent):
    """Attach a safer default recursion limit when the runnable supports config binding."""
    if hasattr(agent, "with_config"):
        return agent.with_config({"recursion_limit": settings.langgraph_recursion_limit})
    return agent


async def create_travel_agent(
    *,
    force_refresh: bool = False,
    include_raw_mcp_tools: bool = False,
):
    """Build the main travel planning agent."""
    global _travel_agent, _travel_agent_mcp_signature

    requested_signature = None if include_raw_mcp_tools else "raw-mcp-disabled"
    if (
        requested_signature is not None
        and _travel_agent is not None
        and not force_refresh
        and _travel_agent_mcp_signature == requested_signature
    ):
        return _travel_agent

    async with _travel_agent_lock:
        if (
            requested_signature is not None
            and _travel_agent is not None
            and not force_refresh
            and _travel_agent_mcp_signature == requested_signature
        ):
            return _travel_agent

        if include_raw_mcp_tools:
            all_mcp_tools = await get_all_mcp_tools()
            hotel_followup_tools = await get_hotel_followup_tools()
        else:
            all_mcp_tools = []
            hotel_followup_tools = []
        internal_rag_tools = get_internal_rag_tools()
        current_signature = (
            _build_tool_signature(
                all_mcp_tools,
                hotel_followup_tools,
                internal_rag_tools,
            )
            if include_raw_mcp_tools
            else "raw-mcp-disabled"
        )

        if (
            _travel_agent is not None
            and not force_refresh
            and _travel_agent_mcp_signature == current_signature
        ):
            return _travel_agent

        app_logger.info(
            f"Creating travel agent with {len(all_mcp_tools)} raw MCP tools "
            f"(signature={current_signature})"
        )

        llm = get_llm()
        step_config_middleware = await create_step_config_middleware()
        checkpointer = await get_checkpointer()

        all_tools = [
            record_requirement_tool,
            set_planning_mode_tool,
            confirm_planning_mode_tool,
            record_evidence_bundle_tool,
            scenic_price_lookup_tool,
            select_destination_tool,
            select_transport_tool,
            select_accommodation_tool,
            select_food_tool,
            generate_itinerary_tool,
            generate_visual_journey_tool,
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
            *internal_rag_tools,
            *hotel_followup_tools,
            *all_mcp_tools,
        ]
        tool_governance = describe_travel_agent_tool_governance(all_tools)
        missing_governance = [
            item["tool_name"]
            for item in tool_governance
            if item["coverage"] == "missing"
        ]
        if missing_governance:
            app_logger.warning(
                "Travel agent has tools missing governance classification: "
                f"{missing_governance}"
            )
        else:
            app_logger.info(
                "Travel agent tool governance coverage ready: "
                f"tool_count={len(tool_governance)}"
            )

        agent = create_agent(
            model=llm,
            tools=all_tools,
            state_schema=TravelState,
            middleware=[step_config_middleware],
            checkpointer=checkpointer,
        )
        _travel_agent = _with_recursion_limit(agent)
        _travel_agent_mcp_signature = current_signature

        app_logger.info("Travel agent is ready")
        return _travel_agent
