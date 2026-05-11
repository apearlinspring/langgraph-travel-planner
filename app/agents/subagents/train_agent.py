"""
高铁查询 Subagent
调用 12306 MCP 的多个工具
"""
import asyncio
from langchain.agents import create_agent
from app.mcp_core.client import get_mcp_client
from app.tools.mcp_tools import guard_mcp_tools
from app.tools.train_query import query_train_options
from app.utils.llm_factory import build_chat_model
from app.utils.logger import app_logger


async def _get_railway_followup_tools():
    """获取高铁补充查询 MCP 工具，核心余票查询由 query_train_options 包装。"""
    manager = await get_mcp_client(servers=["12306-mcp"])
    all_tools = await manager.get_tools(servers=["12306-mcp"])

    followup_tool_names = {
        "get-current-date",
        "get-station-code-of-citys",
        "get-station-code-by-names",
        "get-stations-code-in-city",
        "get-train-route-stations",
    }
    railway_tools = [
        tool for tool in all_tools
        if tool.name in followup_tool_names
    ]

    guarded_tools = guard_mcp_tools(railway_tools)
    app_logger.info(f"高铁补充工具: {[t.name for t in guarded_tools]}")
    return guarded_tools


async def create_train_subagent():
    """创建高铁查询 Subagent"""

    llm = build_chat_model(profile="transport", temperature=0.1)

    railway_tools = [query_train_options]
    railway_tools += await _get_railway_followup_tools()

    agent = create_agent(
        model=llm,
        tools=railway_tools,
        system_prompt="""你是高铁查询专家，负责处理火车票查询、行程规划及车次详情查询。

**可用工具**：
1.  **核心查询**：
    - `query_train_options`: 查询真实 12306 火车/高铁方案。它会自动做城市/车站编码、优先查直达，并在直达无结果时查询中转。用户询问某天从 A 到 B 坐火车/高铁时，优先调用这个工具。

2.  **日期与基础信息**：
    - `get-current-date`: 获取今日日期（yyyy-MM-dd）。用户提到"明天/下周"时必须先调用此工具。
    - `get-station-code-of-citys`: 用【城市名】（如"北京"）查询对应的车站代码，仅在需要解释站点选择或用户追问时使用。
    - `get-station-code-by-names`: 用【具体车站名】（如"北京南"）查询对应的车站代码，仅在需要校准具体车站时使用。
    - `get-stations-code-in-city`: 查询某城市内【所有】火车站列表。

3.  **车次详情**：
    - `get-train-route-stations`: 查询某具体车次（如 G101）的【经停站、时刻表】信息。

**查询流程**：
1.  **日期处理**：首先解析日期，若为相对日期必须调用 `get-current-date` 计算目标日期。
2.  **余票查询策略**：
    - 优先调用 `query_train_options`，不要自行拼接中文地名给底层接口。
    - 如果用户明确只要直达，将 `allow_transfer` 设为 false。
    - 如果用户偏好高铁/动车，默认使用 `train_filter_flags="GD"`；如果用户说普通火车也可以，可放宽为 `GDZTK`。
4.  **经停查询**：仅当用户询问"这趟车经过哪里"或"时刻表"时，使用 `get-train-route-stations`。

**输出格式**：
请以结构化清晰的方式回答，包含：车次、起降时间、时长、各席别余票与价格。如果是中转方案，请清楚标明中转站和换乘时间。
"""
    )

    app_logger.info("高铁 Subagent 创建完成")
    return agent


if __name__ == "__main__":
    async def main():
        print("\n" + "=" * 50)
        print("正在初始化高铁查询 Subagent...")
        print("=" * 50)

        train_agent = await create_train_subagent()

        test_query = "帮我查一下2026-1-17从北京到上海的火车票"

        print(f"\n用户提问: {test_query}")
        print("-" * 30)

        response = await train_agent.ainvoke({
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
