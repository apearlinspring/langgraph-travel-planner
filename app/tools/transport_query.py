"""
交通查询工具
调用交通规划协调器（Subagents 主 Agent）
"""
import time

from langchain.tools import tool
from app.agents.subagents.transport_coordinator import create_transport_coordinator
from app.utils.logger import app_logger


@tool
async def query_transport_options(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    transport_type: str = None
) -> str:
    """
    查询交通选项（调用交通规划协调器）

    参数说明：
    - origin_city: 出发城市
    - destination_city: 目的地城市
    - departure_date: 出发日期，格式 YYYY-MM-DD
    - transport_type: 交通方式（可选），可选值：flight（航班）、train（高铁）、driving（自驾）

    返回：
    - 格式化的交通选项信息
    """

    started_at = time.perf_counter()
    app_logger.info(
        "Transport query started: "
        f"origin={origin_city}, destination={destination_city}, "
        f"departure_date={departure_date}, transport_type={transport_type or 'auto'}"
    )

    # 异步创建协调器（主 Agent）
    coordinator = await create_transport_coordinator()

    # 构建用户查询
    if transport_type:
        type_labels = {
            "flight": "航班",
            "train": "高铁",
            "driving": "自驾"
        }
        user_query = (
            f"我想从 {origin_city} 去 {destination_city}，"
            f"出发日期是 {departure_date}，"
            f"我当前更偏向 {type_labels.get(transport_type, transport_type)}，"
            f"请优先给我这种方式的真实方案；"
            f"如果同一天还有明显更省时、更省心或更省钱的替代方式，也请顺带对比 1-2 个，"
            f"不要因为我提到了 {type_labels.get(transport_type, transport_type)} 就默认排除其他交通方式。"
        )
    else:
        user_query = (
            f"我想从 {origin_city} 去 {destination_city}，"
            f"出发日期是 {departure_date}，"
            f"请推荐合适的交通方式并提供详细信息。"
        )

    # 调用协调器
    result = await coordinator.ainvoke({
        "messages": [
            {"role": "user", "content": user_query}
        ]
    })
    elapsed = time.perf_counter() - started_at
    app_logger.info(
        "Transport query completed: "
        f"origin={origin_city}, destination={destination_city}, "
        f"elapsed_seconds={elapsed:.2f}"
    )
    return result["messages"][-1].content
