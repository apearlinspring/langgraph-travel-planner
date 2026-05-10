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


class FakeRagTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return self.result


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


@pytest.mark.asyncio
async def test_get_explore_tools_can_skip_live_search_tools(monkeypatch):
    monkeypatch.setattr(
        destination_router,
        "get_rag_tools",
        lambda: [SimpleNamespace(name="search_destination_guide")],
    )

    async def unexpected_search_tools():
        raise AssertionError("live search should not be loaded for stable guide queries")

    monkeypatch.setattr(destination_router, "get_search_tools", unexpected_search_tools)

    tools = await destination_router._get_explore_tools_for_query(include_live_search=False)

    assert [tool.name for tool in tools] == ["search_destination_guide"]


def test_destination_router_only_uses_live_search_for_time_sensitive_queries():
    assert destination_router._should_include_live_search("长沙最近开放和门票规则")
    assert not destination_router._should_include_live_search("长沙经典景点和美食攻略")


@pytest.mark.asyncio
async def test_explore_agent_node_uses_single_direct_rag_for_stable_queries(monkeypatch):
    guide_tool = FakeRagTool("search_destination_guide", "杭州亲子攻略证据")

    monkeypatch.setattr(destination_router, "get_rag_tools", lambda: [guide_tool])

    async def unexpected_agent(*args, **kwargs):
        raise AssertionError("stable RAG query should not create nested explore agent")

    monkeypatch.setattr(destination_router, "_get_or_create_explore_agent", unexpected_agent)

    result = await destination_router.explore_agent_node(
        {"destination": "杭州", "query": "亲子轻松景点攻略"}
    )

    report = result["agent_results"][0]["result"]
    assert guide_tool.calls == [{"query": "杭州 亲子轻松景点攻略"}]
    assert "杭州亲子攻略证据" in report


@pytest.mark.asyncio
async def test_explore_agent_node_uses_single_live_search_for_time_sensitive_queries(monkeypatch):
    guide_tool = FakeRagTool("search_destination_guide", "杭州攻略证据")
    live_tool = FakeRagTool("search_travel_info", "杭州最新开放信息")

    monkeypatch.setattr(destination_router, "get_rag_tools", lambda: [guide_tool])

    async def fake_search_tools():
        return [live_tool]

    monkeypatch.setattr(destination_router, "get_search_tools", fake_search_tools)

    async def unexpected_agent(*args, **kwargs):
        raise AssertionError("live destination query should use deterministic search once")

    monkeypatch.setattr(destination_router, "_get_or_create_explore_agent", unexpected_agent)

    result = await destination_router.explore_agent_node(
        {"destination": "杭州", "query": "亲子景点最新开放和预约"}
    )

    report = result["agent_results"][0]["result"]
    assert guide_tool.calls == [{"query": "杭州 亲子景点最新开放和预约"}]
    assert live_tool.calls == [{"query": "杭州 亲子景点最新开放和预约", "max_results": 3}]
    assert "杭州攻略证据" in report
    assert "杭州最新开放信息" in report


def test_select_stable_rag_tool_prefers_food_and_accommodation_tools(monkeypatch):
    tools = [
        SimpleNamespace(name="search_destination_guide"),
        SimpleNamespace(name="search_food_recommendations"),
        SimpleNamespace(name="search_accommodation_info"),
    ]
    monkeypatch.setattr(destination_router, "get_rag_tools", lambda: tools)

    assert destination_router._select_stable_rag_tool("长沙美食小吃").name == "search_food_recommendations"
    assert destination_router._select_stable_rag_tool("长沙酒店住宿").name == "search_accommodation_info"
    assert destination_router._select_stable_rag_tool("长沙经典景点").name == "search_destination_guide"


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


def test_classifier_node_prefers_rule_based_explore(monkeypatch):
    monkeypatch.setattr(
        destination_router,
        "_build_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be used")),
    )

    result = destination_router.classifier_node(
        {"original_query": "推荐眉县适合周末放松的景点和玩法", "destination": "眉县"}
    )

    assert result["classifications"] == [
        {"agent": "explore", "query": "推荐眉县适合周末放松的景点和玩法"}
    ]


def test_classifier_node_prefers_rule_based_weather(monkeypatch):
    monkeypatch.setattr(
        destination_router,
        "_build_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be used")),
    )

    result = destination_router.classifier_node(
        {"original_query": "眉县周末天气和气温怎么样", "destination": "眉县"}
    )

    assert result["classifications"] == [
        {"agent": "weather", "query": "眉县周末天气和气温怎么样"}
    ]


def test_classifier_node_falls_back_to_boolean_model_output(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            return destination_router.ClassificationDecision(explore=True, weather=False)

    class FakeLLM:
        def with_structured_output(self, schema):
            assert schema is destination_router.ClassificationDecision
            return FakeStructuredLLM()

    monkeypatch.setattr(destination_router, "_build_llm", lambda *args, **kwargs: FakeLLM())

    result = destination_router.classifier_node(
        {"original_query": "帮我分类这个模糊问题", "destination": "眉县"}
    )

    assert result["classifications"] == [
        {"agent": "explore", "query": "帮我分类这个模糊问题"}
    ]
