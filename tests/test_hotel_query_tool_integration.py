from datetime import date, timedelta

import pytest

from app.tools.hotel_query import query_hotel_options

pytestmark = [pytest.mark.integration, pytest.mark.mcp, pytest.mark.slow]


@pytest.mark.asyncio
async def test_query_hotel_options_returns_real_candidates_for_chinese_destination():
    check_in_date = (date.today() + timedelta(days=30)).isoformat()

    command = await query_hotel_options.ainvoke(
        {
            "destination": "北京",
            "check_in_date": check_in_date,
            "stay_nights": 2,
            "adult_count": 2,
            "children_count": 1,
            "budget_level": "comfort",
            "preferences": "亲子友好、交通方便、尽量安静、最好含早餐",
            "size": 3,
        }
    )

    result = command.update["messages"][0].content
    assert "已为 北京 找到" in result
    assert "酒店ID：" in result
    assert "暂时没有查到" not in result
    assert command.update["accommodation_options"]
    assert command.update["accommodation_options"][0]["name"]
