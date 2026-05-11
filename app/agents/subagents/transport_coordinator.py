#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Transport coordinator that orchestrates flight, train, and driving subagents.
"""
import asyncio

from langchain.agents import create_agent
from langchain.tools import tool

from app.mcp_core.client import get_mcp_client
from app.tools.driving_query import query_driving_route
from app.tools.flight_query import query_flight_options
from app.tools.mcp_tools import guard_mcp_tools
from app.tools.train_query import query_train_options
from app.utils.date_normalization import normalize_travel_date
from app.utils.llm_factory import build_chat_model
from app.utils.logger import app_logger


async def _get_auxiliary_tools():
    manager = await get_mcp_client()
    all_tools = await manager.get_tools(
        servers=manager.get_default_tool_server_names(include_optional=False)
    )
    keywords = ("getfutureweather", "get-current-date", "maps_around_search")
    aux_tools = [
        tool_item
        for tool_item in all_tools
        if any(keyword in tool_item.name.lower() for keyword in keywords)
    ]
    guarded_tools = guard_mcp_tools(aux_tools)
    app_logger.info(f"Transport auxiliary tools: {[tool_item.name for tool_item in guarded_tools]}")
    return guarded_tools


async def _has_live_flight_capability() -> bool:
    manager = await get_mcp_client()
    tools = await manager.get_tools(servers=["VariFlight-Aviation"])
    keywords = ("flight", "aviation", "searchflights")
    return any(any(keyword in tool_item.name.lower() for keyword in keywords) for tool_item in tools)


async def create_transport_coordinator():
    """Create the transport planning coordinator."""
    llm = build_chat_model(profile="transport", temperature=0.2)

    @tool("query_flights", description="查询航班信息，需要提供出发城市、目的地城市、出发日期。")
    async def query_flights_tool(origin: str, destination: str, departure_date: str) -> str:
        app_logger.info(f"Transport coordinator calling flight subagent: {origin} -> {destination}")
        try:
            normalized_date = normalize_travel_date(departure_date)
        except ValueError as exc:
            return f"航班查询日期无效：{exc}"
        result = await query_flight_options.ainvoke(
            {
                "origin_city": origin,
                "destination_city": destination,
                "departure_date": normalized_date,
            }
        )
        return result

    @tool("query_trains", description="查询高铁/火车信息，需要提供出发城市、目的地城市、出发日期。")
    async def query_trains_tool(origin: str, destination: str, departure_date: str) -> str:
        app_logger.info(f"Transport coordinator calling train query wrapper: {origin} -> {destination}")
        try:
            normalized_date = normalize_travel_date(departure_date)
        except ValueError as exc:
            return f"火车查询日期无效：{exc}"
        result = await query_train_options.ainvoke(
            {
                "origin_city": origin,
                "destination_city": destination,
                "departure_date": normalized_date,
            }
        )
        return result

    @tool("plan_driving_route", description="规划自驾路线，需要提供出发地和目的地。")
    async def plan_driving_route_tool(origin: str, destination: str) -> str:
        app_logger.info(f"Transport coordinator calling driving query wrapper: {origin} -> {destination}")
        result = await query_driving_route.ainvoke(
            {
                "origin": origin,
                "destination": destination,
            }
        )
        return result

    auxiliary_tools = await _get_auxiliary_tools()
    flight_enabled = await _has_live_flight_capability()

    tools = [query_trains_tool, plan_driving_route_tool]
    if flight_enabled:
        tools.insert(0, query_flights_tool)
    tools += auxiliary_tools

    flight_capability_note = (
        "- query_flights：查询真实航班推荐、低价候选和价格提醒（当前环境已就绪，可用于长途方案对比）"
        if flight_enabled
        else "- query_flights：当前环境未就绪，不要调用，优先给出高铁或自驾方案"
    )

    coordinator = create_agent(
        model=llm,
        tools=tools,
        system_prompt=(
            "你是交通规划协调专家，需要根据用户的时间、预算、省心程度和自由度偏好推荐交通方式。\n\n"
            "可用工具：\n"
            f"{flight_capability_note}\n"
            "- query_trains：查询真实 12306 高铁/火车方案，优先直达，必要时给中转候选\n"
            "- plan_driving_route：查询真实高德自驾路线摘要，代码会解析距离、秒级时长和费用估算，避免误读原始 JSON\n"
            "- 其余辅助工具只在确有必要时使用，例如日期、周边信息、天气补充\n\n"
            "工作原则：\n"
            "1. 如果用户明确说“只要/必须/只坐某种方式”，再把它当成唯一候选并直接调用对应工具。\n"
            "2. 如果用户只是说“可以考虑/偏向/优先看看某种方式”，把它当成偏好而不是排他条件：优先查询这种方式，但如有必要也顺带补 1-2 个更合适的替代方式做对比。\n"
            "3. 如果用户没有指定，就根据距离、时间和预算做推荐。\n"
            "4. query_flights/query_trains 可以直接接收今天、明天、后天等相对日期；不要自己猜测或编造绝对日期。\n"
            "5. 同一轮内，同一出发地/目的地/日期/方式只调用一次对应工具；除非工具明确失败或用户要求刷新，不要重复查询。\n"
            "6. 工具返回结果后，直接基于已有结果做比较和总结；不要为了确认最低价、余票、耗时或写最终结论再次调用同一个工具。\n"
            "7. 当用户明确要坐飞机或城市间距离较远时，优先调用 query_flights 获取真实航班数据。\n"
            "8. 当用户明确要坐高铁/火车，或中短途城市间高铁体验更好时，调用 query_trains 获取真实 12306 数据。\n"
            "9. 如果用户提到带孩子、老人、行李多、门到门、省心或不想折腾，且属于短中途或同日可轻松自驾的路线，要同时查询自驾路线作为便利性对照。\n"
            "10. 对于北京-上海这类明显超长距离、跨多省、常识上自驾就会非常疲劳的路线，除非用户明确要求自驾，或明确强调大量行李/老人幼儿的门到门搬运诉求，否则不要把自驾作为默认对照。\n"
            "11. 当前无票、仅无座、只有高价商务座的火车方案不要作为首选；只能作为候补/刷新/改签日期的备选。\n"
            "12. 自驾路线里的 duration 是秒，已经由工具换算成小时分钟；不要再把原始秒数字段误读为小时。\n"
            "13. 不要编造实时交通信息；查不到时明确说明，并给替代方案。\n"
            "14. 最终推荐必须说明余票、票价、路况等实时信息会变化，正式购票或出发前需要再次核实。"
        ),
    )

    app_logger.info(
        "Transport coordinator created with capabilities: "
        f"flight_enabled={flight_enabled}, total_tools={len(tools)}"
    )
    return coordinator


if __name__ == "__main__":
    async def main():
        print("\n" + "=" * 50)
        print("Initializing transport coordinator...")
        print("=" * 50)

        coordinator = await create_transport_coordinator()
        test_query = "我想从北京去上海，明天出发，帮我推荐交通方式"

        print(f"\nUser: {test_query}")
        print("-" * 30)

        response = await coordinator.ainvoke(
            {"messages": [{"role": "user", "content": test_query}]}
        )

        print("-" * 30)
        print("Coordinator response:")
        print(response["messages"][-1].content)
        print("\n" + "=" * 50)
        print("Done")
        print("=" * 50)

    asyncio.run(main())
