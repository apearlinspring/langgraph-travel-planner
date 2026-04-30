from datetime import date, timedelta

import pytest

from app.tools.train_query import query_train_options

pytestmark = [pytest.mark.integration, pytest.mark.mcp, pytest.mark.slow]


@pytest.mark.asyncio
async def test_query_train_options_returns_real_12306_candidates():
    departure_date = (date.today() + timedelta(days=7)).isoformat()

    result = await query_train_options.ainvoke(
        {
            "origin_city": "\u5317\u4eac",
            "destination_city": "\u4e0a\u6d77",
            "departure_date": departure_date,
            "max_results": 3,
        }
    )

    assert "\u706b\u8f66\u67e5\u8be2\u6761\u4ef6" in result
    assert "\u5317\u4eac" in result
    assert "\u4e0a\u6d77" in result
    assert (
        "\u76f4\u8fbe\u8f66\u6b21\u5019\u9009" in result
        or "\u9884\u552e\u8303\u56f4" in result
        or "\u5c1a\u672a\u653e\u51fa" in result
    )
    assert "\u6b63\u5f0f\u8d2d\u7968\u524d\u9700\u8981\u518d\u6b21\u6838\u5b9e" in result or "\u5efa\u8bae\u6539\u67e5" in result
