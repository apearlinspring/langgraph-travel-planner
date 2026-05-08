"""
MCP 工具筛选器
按需获取特定类型的 MCP 工具
"""
from typing import List
from langchain_core.tools import BaseTool
from app.mcp_core.client import MCPClientManager, get_mcp_client
from app.utils.logger import app_logger


def _server_is_healthy(server: str) -> bool:
    snapshot = MCPClientManager.get_status_snapshot()
    return snapshot.get("servers", {}).get(server, {}).get("status") == "healthy"


async def get_all_mcp_tools() -> List[BaseTool]:
    """获取所有 MCP 工具"""
    manager = await get_mcp_client()
    tools = await manager.get_tools(
        servers=manager.get_default_tool_server_names(include_optional=False)
    )
    app_logger.info(f"📦 获取了 {len(tools)} 个 MCP 工具")
    return tools


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

    app_logger.info(f"🏨 酒店工具: {[t.name for t in hotel_tools]}")
    return hotel_tools


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

    app_logger.info(f"🏨 酒店后续工具: {[t.name for t in hotel_tools]}")
    return hotel_tools


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

    app_logger.info(f"🌤️ 天气工具: {[t.name for t in weather_tools]}")
    return weather_tools


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

    app_logger.info(f"🔍 搜索工具: {[t.name for t in search_tools]}")
    return search_tools


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

    app_logger.info(f"📅 日期工具: {[t.name for t in date_tools]}")
    return date_tools
