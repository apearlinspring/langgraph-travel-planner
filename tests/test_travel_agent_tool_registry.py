import pytest
from langchain_core.tools import StructuredTool

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

    async def fake_get_hotel_followup_tools():
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

    assert "update_accommodation_preference_tool" in recorded["tool_names"]
    assert "query_hotel_options" in recorded["tool_names"]
    assert "set_planning_mode_tool" in recorded["tool_names"]
    assert "confirm_planning_mode_tool" in recorded["tool_names"]
    assert "record_evidence_bundle_tool" in recorded["tool_names"]
    assert "search_agency_product_templates" in recorded["tool_names"]
    assert "search_agency_pricing_rules" in recorded["tool_names"]


@pytest.mark.asyncio
async def test_create_travel_agent_tool_registry_has_governance_coverage(monkeypatch):
    recorded = {}

    async def fake_dynamic_tool(city: str) -> str:
        return city

    guarded_mcp_tool = StructuredTool.from_function(
        coroutine=fake_dynamic_tool,
        name="get_weather_forecast",
        description="天气查询",
        metadata={"execution_guard": "tool_execution_guard"},
    )

    async def fake_get_all_mcp_tools():
        return [guarded_mcp_tool]

    async def fake_get_hotel_followup_tools():
        return []

    async def fake_create_step_config_middleware():
        return object()

    async def fake_get_checkpointer():
        return object()

    def fake_create_agent(*, model, tools, state_schema, middleware, checkpointer):
        recorded["governance"] = travel_agent_module.describe_travel_agent_tool_governance(
            tools
        )
        return object()

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

    missing = [
        item["tool_name"]
        for item in recorded["governance"]
        if item["coverage"] == "missing"
    ]
    by_name = {item["tool_name"]: item for item in recorded["governance"]}

    assert missing == []
    assert by_name["query_hotel_options"]["coverage"] == "guarded"
    assert by_name["query_transport_options"]["coverage"] == "guarded"
    assert by_name["search_agency_risk_playbook"]["coverage"] == "guarded"
    assert by_name["generate_order_tool"]["coverage"] == "governed_boundary"
    assert by_name["select_destination_tool"]["coverage"] == "exception"
    assert by_name["get_weather_forecast"]["coverage"] == "metadata_guarded"


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
