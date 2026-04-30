
"""
航班查询 Subagent
调用 Aviation MCP 的多个工具
"""
import asyncio
from langchain.agents import create_agent
from app.mcp_core.client import get_mcp_client
from app.tools.flight_query import query_flight_options
from app.utils.llm_factory import build_chat_model
from app.utils.logger import app_logger


async def _get_aviation_followup_tools():
    """获取航班补充查询工具，核心方案查询由 query_flight_options 包装。"""
    manager = await get_mcp_client(servers=["VariFlight-Aviation"])
    all_tools = await manager.get_tools(servers=["VariFlight-Aviation"])

    followup_tool_names = {
        "getTodayDate",
        "searchFlightsByNumber",
        "flightHappinessIndex",
        "getFutureWeatherByAirport",
        "getFlightTransferInfo",
    }
    aviation_tools = [
        tool for tool in all_tools
        if tool.name in followup_tool_names
    ]

    app_logger.info(f"航班补充工具: {[t.name for t in aviation_tools]}")
    return aviation_tools


async def create_flight_subagent():
    """创建航班查询 Subagent"""
    
    llm = build_chat_model(temperature=0.1)
    
    # 异步获取工具
    aviation_tools = [query_flight_options, *await _get_aviation_followup_tools()]
    
    agent = create_agent(
        model=llm,
        tools=aviation_tools,
        system_prompt="""你是航班查询专家，负责处理航班查询、机票价格比较及航班状态查询。可以使用以下工具：

**可用工具**：
1.  **核心航班方案查询**：
    - `query_flight_options`: 按出发城市、目的地城市和日期查询真实航班方案。优先使用这个工具。

2.  **日期与基础信息**：
    - `getTodayDate`: 获取今天日期（用于用户提供相对日期时）

3.  **航班补充查询**：
    - `searchFlightsByNumber`: 按航班号查询航班信息
    - `getFlightTransferInfo`: 查询中转航班信息
    - `flightHappinessIndex`: 查询已知航班的舒适度、机型、准点等体验信息
    - `getFutureWeatherByAirport`: 查询机场未来天气

**IATA三字码示例**：
- query_flight_options 可直接接收中文城市名，你不需要自己转换。
- 如果使用其他补充工具，城市码：北京=BJS, 上海=SHA, 广州=CAN, 西安=XIY, 成都=CTU。

**工作流程**：
1. 分析用户查询，提取出发地、目的地、日期
2. 如果用户说"明天"等相对日期，先调用getTodayDate获取今天日期
3. 查询城市间航班方案时，调用 query_flight_options
4. 用户给出具体航班号时，再调用 searchFlightsByNumber 或 flightHappinessIndex 做补充

**输出格式**：
✈️ 航班 {航班号}
- 出发：{机场} {时间}
- 到达：{机场} {时间}
- 价格：¥{价格}

**注意**：
- 一定要调用工具，不要编造数据
- 日期格式必须是YYYY-MM-DD
- 如果没找到航班，明确告知用户
- 价格和余票会波动，输出时要提醒正式预订前再次核实
"""
    )
    
    app_logger.info("✅ 航班 Subagent 创建完成")
    return agent


if __name__ == "__main__":
    async def main():
        print("\n" + "=" * 50)
        print("正在初始化航班查询 Subagent...")
        print("=" * 50)

        flight_agent = await create_flight_subagent()

        test_query = "帮我查一下明天从北京到上海的航班"

        print(f"\n用户提问: {test_query}")
        print("-" * 30)

        response = await flight_agent.ainvoke({
            "messages": [{"role": "user", "content": test_query}]
        })

        print("-" * 30)
        print("Agent 回复:")
        final_message = response["messages"][-1].content
        print(final_message)

        print("\n" + "=" * 50)
        print("测试结束")
        print("=" * 50)

    asyncio.run(main())
