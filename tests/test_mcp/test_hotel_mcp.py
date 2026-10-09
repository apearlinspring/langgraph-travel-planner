from datetime import date, timedelta

import pytest

from app.mcp_core.client import MCPClientManager

pytestmark = [pytest.mark.integration, pytest.mark.mcp, pytest.mark.slow]


@pytest.fixture(autouse=True)
def reset_singleton():
    MCPClientManager.reset_instance()
    yield
    MCPClientManager.reset_instance()


@pytest.mark.asyncio
async def test_hotel_mcp_search_hotels():
    manager = await MCPClientManager.get_instance(servers=["aigohotel-mcp"])

    try:
        tools = await manager.get_tools(servers=["aigohotel-mcp"])
        tool_names = {tool.name: tool for tool in tools}
        assert "searchHotels" in tool_names

        check_in_date = (date.today() + timedelta(days=30)).isoformat()
        result = await tool_names["searchHotels"].ainvoke(
            {
                "originQuery": "帮我找北京适合亲子出行、交通方便的中高档酒店",
                "place": "北京",
                "placeType": "城市",
                "checkInParam": {
                    "checkInDate": check_in_date,
                    "stayNights": 2,
                    "adultCount": 2,
                },
                "filterOptions": {
                    "starRatings": [3.5, 5.0],
                },
                "size": 3,
            }
        )

        assert result is not None
        assert "error" not in str(result).lower()
        assert any(keyword in str(result) for keyword in ["hotel", "酒店", "price", "价格"])
    finally:
        await manager.close()
