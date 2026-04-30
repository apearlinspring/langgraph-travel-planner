import json
import pytest

from app.mcp_core.client import MCPClientManager

pytestmark = [pytest.mark.integration, pytest.mark.mcp, pytest.mark.slow]


@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前重置单例"""
    MCPClientManager.reset_instance()
    yield
    MCPClientManager.reset_instance()


@pytest.mark.asyncio
async def test_print_mcp_tools():
    """测试打印所有 MCP 工具"""

    print("\n" + "=" * 60)
    print("Initializing MCP client manager...")

    manager = await MCPClientManager.get_instance(
        servers=["weather", "search", "amap", "12306-mcp","VariFlight-Aviation","aigohotel-mcp"]
    )

    try:
        # 获取所有工具
        tools = await manager.get_tools()

        print(f"Connected successfully. Discovered {len(tools)} tools.")
        print("=" * 60)

        # 打印工具详情
        for i, tool in enumerate(tools, 1):
            print(f"Tool [{i}]")
            print(f"Name: {tool.name}")
            print(f"Description: {tool.description}")
            print("Args schema:")
            try:
                print(json.dumps(tool.args, indent=2, ensure_ascii=False))
            except Exception:
                print(f"   {tool.args}")
            print("-" * 60)

        assert len(tools) > 0, "Expected at least one MCP tool"

    finally:
        print("\nClosing MCP client manager...")
        await manager.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_print_mcp_tools())
