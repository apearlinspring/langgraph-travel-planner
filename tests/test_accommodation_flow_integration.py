import sys
import uuid
import asyncio
from datetime import date, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.handoffs.travel_agent import create_travel_agent

pytestmark = [
    pytest.mark.integration,
    pytest.mark.llm,
    pytest.mark.mcp,
    pytest.mark.slow,
]


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.mark.asyncio
async def test_accommodation_step_uses_confirmed_context_without_reasking_destination():
    agent = await create_travel_agent()
    check_in = (date.today() + timedelta(days=30)).isoformat()
    thread_id = str(uuid.uuid4())

    result = await agent.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "信息已经齐了，不需要继续追问。"
                        f"请直接查询北京适合亲子、交通方便、尽量安静的中高档酒店，{check_in} 入住，"
                        "住2晚，2大1小，最好含早餐，给我3个真实推荐。"
                    )
                )
            ],
            "current_step": "accommodation_planning",
            "user_requirement": {
                "departure_city": "上海",
                "destination": "北京",
                "departure_date": check_in,
                "travel_days": 2,
                "adult_count": 2,
                "children_count": 1,
                "budget_min": 2500.0,
                "budget_max": 5000.0,
                "budget_level": "comfort",
                "travel_styles": ["relaxation", "culture"],
                "special_needs": "亲子友好，交通方便，尽量安静",
            },
            "selected_destination": "北京",
            "selected_transport": "train",
        },
        config={"configurable": {"thread_id": thread_id}},
    )

    ai_messages = [message for message in result["messages"] if isinstance(message, AIMessage)]
    assert ai_messages, "Expected at least one AI response"

    final_text = ai_messages[-1].content
    assert "预算等级" not in final_text
    assert "确认一下目的地" not in final_text
    assert "打算去哪个城市" not in final_text
    assert "市中心" in final_text or "景点周边" in final_text or "交通枢纽" in final_text
