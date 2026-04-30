"""测试天气 MCP Server"""
import pytest
import asyncio
from app.mcp_core.servers.weather_server import get_weather_forecast

pytestmark = [pytest.mark.integration, pytest.mark.mcp]

@pytest.mark.asyncio
async def test_weather_mcp_server():
    print("=== 测试西安天气 (adcode: 610100) ===")
    result = await get_weather_forecast("610100")
    print(result)

    print("\n=== 测试北京天气 (adcode: 110000) ===")
    result = await get_weather_forecast("110000")
    print(result)


if __name__ == "__main__":
    asyncio.run(test_weather_mcp_server())
