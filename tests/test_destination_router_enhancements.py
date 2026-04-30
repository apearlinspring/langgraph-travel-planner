import json
from types import SimpleNamespace

import pytest

from app.agents.routers import destination_router
from app.tools import router_query


class FakeWeatherTool:
    name = "get_weather_forecast"

    async def ainvoke(self, payload):
        assert payload == {"city_adcode": "610100"}
        return json.dumps(
            {
                "city": "Xi'an",
                "casts": [
                    {
                        "date": "2026-05-01",
                        "dayweather": "Sunny",
                        "nightweather": "Cloudy",
                        "daytemp": "28",
                        "nighttemp": "17",
                        "daywind": "North",
                        "daypower": "3",
                    }
                ],
            },
            ensure_ascii=False,
        )


class FakeListWeatherTool:
    name = "get_weather_forecast"

    async def ainvoke(self, payload):
        assert payload == {"city_adcode": "610100"}
        return json.dumps(
            [
                {
                    "city": "Xi'an",
                    "casts": [
                        {
                            "date": "2026-05-02",
                            "dayweather": "Rain",
                            "nightweather": "Cloudy",
                            "daytemp": "20",
                            "nighttemp": "12",
                            "daywind": "East",
                            "daypower": "3",
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        )


@pytest.mark.asyncio
async def test_get_explore_tools_appends_live_search_tools(monkeypatch):
    monkeypatch.setattr(
        destination_router,
        "get_rag_tools",
        lambda: [SimpleNamespace(name="search_destination_guide")],
    )

    async def fake_search_tools():
        return [SimpleNamespace(name="search_travel_info")]

    monkeypatch.setattr(destination_router, "get_search_tools", fake_search_tools)

    tools = await destination_router._get_explore_tools()

    assert [tool.name for tool in tools] == [
        "search_destination_guide",
        "search_travel_info",
    ]


def test_resolve_city_adcode_supports_known_city_and_literal_code():
    assert destination_router.resolve_city_adcode("\u897f\u5b89") == "610100"
    assert destination_router.resolve_city_adcode(" 110000 ") == "110000"
    assert destination_router.resolve_city_adcode("unknown-city") is None


@pytest.mark.asyncio
async def test_weather_agent_node_uses_weather_mcp(monkeypatch):
    async def fake_weather_tools():
        return [FakeWeatherTool()]

    monkeypatch.setattr(destination_router, "get_weather_tools", fake_weather_tools)

    result = await destination_router.weather_agent_node(
        {"destination": "\u897f\u5b89", "query": "\u5929\u6c14\u600e\u4e48\u6837"}
    )

    report = result["agent_results"][0]["result"]
    assert result["agent_results"][0]["agent_name"] == "weather"
    assert "2026-05-01" in report
    assert "Sunny" in report
    assert "Cloudy" in report


@pytest.mark.asyncio
async def test_weather_agent_node_accepts_list_payload(monkeypatch):
    async def fake_weather_tools():
        return [FakeListWeatherTool()]

    monkeypatch.setattr(destination_router, "get_weather_tools", fake_weather_tools)

    result = await destination_router.weather_agent_node(
        {"destination": "\u897f\u5b89", "query": "\u5929\u6c14\u600e\u4e48\u6837"}
    )

    report = result["agent_results"][0]["result"]
    assert "2026-05-02" in report
    assert "Rain" in report
    assert "list" not in report


@pytest.mark.asyncio
async def test_weather_agent_node_falls_back_when_tool_is_unavailable(monkeypatch):
    async def no_weather_tools():
        return []

    monkeypatch.setattr(destination_router, "get_weather_tools", no_weather_tools)

    result = await destination_router.weather_agent_node(
        {"destination": "Xi'an", "query": "weather"}
    )

    report = result["agent_results"][0]["result"]
    assert "Xi'an" in report
    assert "MCP" in report


def test_destination_query_builds_state_context_from_report():
    report = (
        "## \u4e0a\u6d77\u76ee\u7684\u5730\u4fe1\u606f\n\n"
        "\u4e0a\u6d77\u9002\u5408\u6587\u5316\u548c\u7f8e\u98df\u884c\u7a0b\uff0c"
        "\u63a8\u8350\u5916\u6ee9\u3001\u4e0a\u6d77\u535a\u7269\u9986\u548c\u7530\u5b50\u574a\u3002\n\n"
        "## \u4e0a\u6d77\u5929\u6c14\u4fe1\u606f\n\n"
        "- 2026-05-20: \u767d\u5929 \u9635\u96e8 / \u591c\u95f4 \u591a\u4e91"
    )

    context = router_query._build_destination_context("\u4e0a\u6d77", report)

    assert context["name"] == "\u4e0a\u6d77"
    assert "\u9635\u96e8" in context["weather_info"]
    assert "\u5916\u6ee9" in context["attractions"]
    assert "\u4e0a\u6d77\u535a\u7269\u9986" in context["attractions"]
