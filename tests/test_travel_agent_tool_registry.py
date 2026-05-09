import pytest

from app.agents.handoffs import travel_agent as travel_agent_module


@pytest.fixture(autouse=True)
def reset_travel_agent_cache():
    travel_agent_module._travel_agent = None
    travel_agent_module._travel_agent_mcp_signature = None
    yield
    travel_agent_module._travel_agent = None
    travel_agent_module._travel_agent_mcp_signature = None


@pytest.mark.asyncio
async def test_create_travel_agent_registers_accommodation_tools(monkeypatch):
    recorded = {}

    async def fake_get_all_mcp_tools():
        return []

    async def fake_create_step_config_middleware():
        return object()

    async def fake_get_checkpointer():
        return object()

    def fake_create_agent(*, model, tools, state_schema, middleware, checkpointer):
        recorded["tool_names"] = [tool.name for tool in tools]
        return object()

    monkeypatch.setattr(travel_agent_module, "get_all_mcp_tools", fake_get_all_mcp_tools)
    monkeypatch.setattr(
        travel_agent_module,
        "create_step_config_middleware",
        fake_create_step_config_middleware,
    )
    monkeypatch.setattr(travel_agent_module, "get_checkpointer", fake_get_checkpointer)
    monkeypatch.setattr(travel_agent_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(travel_agent_module, "get_llm", lambda: object())

    await travel_agent_module.create_travel_agent()

    assert "update_accommodation_preference_tool" in recorded["tool_names"]
    assert "query_hotel_options" in recorded["tool_names"]
    assert "search_agency_product_templates" in recorded["tool_names"]
    assert "search_agency_pricing_rules" in recorded["tool_names"]


@pytest.mark.asyncio
async def test_create_travel_agent_binds_recursion_limit(monkeypatch):
    recorded = {}

    class FakeAgent:
        def with_config(self, config):
            recorded["config"] = config
            return self

    async def fake_get_all_mcp_tools():
        return []

    async def fake_get_hotel_followup_tools():
        return []

    async def fake_create_step_config_middleware():
        return object()

    async def fake_get_checkpointer():
        return object()

    def fake_create_agent(*, model, tools, state_schema, middleware, checkpointer):
        return FakeAgent()

    monkeypatch.setattr(travel_agent_module, "get_all_mcp_tools", fake_get_all_mcp_tools)
    monkeypatch.setattr(
        travel_agent_module,
        "get_hotel_followup_tools",
        fake_get_hotel_followup_tools,
    )
    monkeypatch.setattr(
        travel_agent_module,
        "create_step_config_middleware",
        fake_create_step_config_middleware,
    )
    monkeypatch.setattr(travel_agent_module, "get_checkpointer", fake_get_checkpointer)
    monkeypatch.setattr(travel_agent_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(travel_agent_module, "get_llm", lambda: object())

    await travel_agent_module.create_travel_agent()

    assert recorded["config"]["recursion_limit"] > 25
