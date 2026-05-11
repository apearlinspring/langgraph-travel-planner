"""
MCP 工具筛选器
按需获取特定类型的 MCP 工具
"""
from typing import Any
from typing import List
from langchain_core.tools import BaseTool
from langchain_core.tools import StructuredTool
from app.mcp_core.client import MCPClientManager, get_mcp_client
from app.tools.execution_guard import execute_guarded_call
from app.tools.guardrails import validate_mcp_tool_args
from app.tools.result_validation import validate_mcp_result
from app.utils.logger import app_logger


MCP_TOOL_TIMEOUT_SECONDS = 20.0
TOOL_AUDIT_EVENTS_ARTIFACT_KEY = "tool_audit_events"


def _server_is_healthy(server: str) -> bool:
    snapshot = MCPClientManager.get_status_snapshot()
    return snapshot.get("servers", {}).get(server, {}).get("status") == "healthy"


def _tool_already_guarded(tool: BaseTool) -> bool:
    metadata = getattr(tool, "metadata", None) or {}
    return metadata.get("execution_guard") == "tool_execution_guard"


def guard_mcp_tool(tool: BaseTool) -> BaseTool:
    """Wrap an MCP tool with timeout, argument guardrails and audit artifact output."""

    if _tool_already_guarded(tool):
        return tool

    async def _guarded_tool(**kwargs: Any) -> Any:
        async def _call(guarded_args: dict[str, Any]) -> Any:
            return await tool.ainvoke(guarded_args)

        guarded = await execute_guarded_call(
            getattr(tool, "name", "mcp_tool"),
            kwargs,
            _call,
            input_validator=validate_mcp_tool_args,
            result_validator=validate_mcp_result,
            evidence_type="mcp_live_query",
            timeout_seconds=MCP_TOOL_TIMEOUT_SECONDS,
        )
        artifact = {
            TOOL_AUDIT_EVENTS_ARTIFACT_KEY: [guarded.event],
            "tool_guard_status": guarded.status,
            "tool_guard_error_type": guarded.error_type,
        }
        if guarded.output is not None:
            return guarded.output, artifact
        fallback = (
            f"{getattr(tool, 'name', 'MCP 工具')} 本次调用未得到可靠结果"
            f"（{guarded.error_type or 'tool_guard_failed'}）。请标注为待二次核实，"
            "不要据此编造实时价格、库存、路线或开放状态。"
        )
        return fallback, artifact

    metadata = dict(getattr(tool, "metadata", None) or {})
    metadata["execution_guard"] = "tool_execution_guard"
    metadata["original_response_format"] = getattr(tool, "response_format", "content")
    return StructuredTool.from_function(
        coroutine=_guarded_tool,
        name=tool.name,
        description=tool.description or f"{tool.name} MCP 工具",
        args_schema=getattr(tool, "args_schema", None),
        return_direct=getattr(tool, "return_direct", False),
        response_format="content_and_artifact",
        metadata=metadata,
    )


def guard_mcp_tools(tools: List[BaseTool]) -> List[BaseTool]:
    return [guard_mcp_tool(tool) for tool in tools]


async def get_all_mcp_tools() -> List[BaseTool]:
    """获取所有 MCP 工具"""
    manager = await get_mcp_client()
    tools = await manager.get_tools(
        servers=manager.get_default_tool_server_names(include_optional=False)
    )
    guarded_tools = guard_mcp_tools(tools)
    app_logger.info(f"📦 获取了 {len(guarded_tools)} 个 MCP 工具")
    return guarded_tools


async def get_hotel_tools() -> List[BaseTool]:
    """
    获取酒店相关工具

    Returns:
        酒店搜索、周边查询等工具
    """
    manager = await get_mcp_client()
    all_tools = await manager.get_tools(servers=["aigohotel-mcp"])

    hotel_tools = [
        tool for tool in all_tools
        if any(keyword in tool.name.lower() for keyword in [
            'find-hotels',           # 酒店搜索
            'find_hotels',           # 兼容下划线命名
            'hotel',                 # 兼容更通用的酒店工具命名
            'maps_around_search',    # 周边POI搜索（找附近餐厅等）
        ])
    ]

    guarded_tools = guard_mcp_tools(hotel_tools)
    app_logger.info(f"🏨 酒店工具: {[t.name for t in guarded_tools]}")
    return guarded_tools


async def get_hotel_followup_tools() -> List[BaseTool]:
    """
    获取酒店后续查询工具

    Returns:
        酒店详情、标签等二次查询工具
    """
    if not _server_is_healthy("aigohotel-mcp"):
        app_logger.info("🏨 酒店后续工具暂不预加载，等待酒店查询链路按需唤起")
        return []

    manager = await get_mcp_client()
    all_tools = await manager.get_tools(servers=["aigohotel-mcp"])

    hotel_tools = [
        tool for tool in all_tools
        if tool.name in {
            "getHotelDetail",
            "getHotelSearchTags",
        }
    ]

    guarded_tools = guard_mcp_tools(hotel_tools)
    app_logger.info(f"🏨 酒店后续工具: {[t.name for t in guarded_tools]}")
    return guarded_tools


async def get_weather_tools() -> List[BaseTool]:
    """
    获取天气相关工具

    Returns:
        天气查询工具
    """
    manager = await get_mcp_client()
    all_tools = await manager.get_tools(servers=["weather"])

    weather_tools = [
        tool for tool in all_tools
        if any(keyword in tool.name.lower() for keyword in [
            'get_weather_forecast',      # 自建天气服务
        ])
    ]

    guarded_tools = guard_mcp_tools(weather_tools)
    app_logger.info(f"🌤️ 天气工具: {[t.name for t in guarded_tools]}")
    return guarded_tools


async def get_search_tools() -> List[BaseTool]:
    """
    获取搜索相关工具

    Returns:
        旅游信息搜索工具
    """
    manager = await get_mcp_client()
    all_tools = await manager.get_tools(servers=["search"])

    search_tools = [
        tool for tool in all_tools
        if any(keyword in tool.name.lower() for keyword in [
            'search_travel_info',  # 自建搜索服务
        ])
    ]

    guarded_tools = guard_mcp_tools(search_tools)
    app_logger.info(f"🔍 搜索工具: {[t.name for t in guarded_tools]}")
    return guarded_tools


async def get_date_tools() -> List[BaseTool]:
    """
    获取日期相关工具

    Returns:
        获取当前日期的工具
    """
    manager = await get_mcp_client()
    all_tools = await manager.get_tools(
        servers=manager.get_default_tool_server_names(include_optional=False)
    )

    date_tools = [
        tool for tool in all_tools
        if any(keyword in tool.name.lower() for keyword in [
            'get-current-date',
            'gettodaydate',
        ])
    ]

    guarded_tools = guard_mcp_tools(date_tools)
    app_logger.info(f"📅 日期工具: {[t.name for t in guarded_tools]}")
    return guarded_tools
