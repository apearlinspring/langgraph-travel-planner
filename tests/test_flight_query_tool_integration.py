from datetime import date, timedelta

import pytest

from app.tools.flight_query import query_flight_options

pytestmark = [pytest.mark.integration, pytest.mark.mcp, pytest.mark.slow]


@pytest.mark.asyncio
async def test_query_flight_options_returns_real_variflight_candidates():
    departure_date = (date.today() + timedelta(days=30)).isoformat()

    result = await query_flight_options.ainvoke(
        {
            "origin_city": "北京",
            "destination_city": "上海",
            "departure_date": departure_date,
            "max_results": 3,
        }
    )

    assert "航班查询条件：北京(BJS) -> 上海(SHA)" in result
    assert "推荐摘要：" in result
    assert "结构化低价候选：" in result
    assert "正式预订前需要再次核实" in result
