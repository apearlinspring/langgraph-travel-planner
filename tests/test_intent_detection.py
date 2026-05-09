import pytest
from langchain_core.messages import HumanMessage

from app.core.intent import detect_travel_intent
from app.core.middleware import StepConfigMiddleware
from app.utils.llm_factory import get_model_compatibility


class DummyRequest:
    def __init__(self, state, messages=None):
        self.state = state
        self.messages = messages or []

    def override(self, **kwargs):
        class RequestSnapshot:
            pass

        snapshot = RequestSnapshot()
        for key, value in {**self.__dict__, **kwargs}.items():
            setattr(snapshot, key, value)
        return snapshot


def test_detect_hotel_query_prefers_hotel_tool():
    intent = detect_travel_intent(
        "请帮我查长沙湘江中路附近真实江景房酒店候选。",
        current_step="destination_recommendation",
    )

    assert intent.name == "hotel_query"
    assert intent.preferred_tool == "query_hotel_options"
    assert intent.target_step == "accommodation_planning"


def test_detect_final_report_protects_against_freeform_report():
    intent = detect_travel_intent(
        "不要再问了，直接生成最终旅游报告。",
        current_step="destination_recommendation",
    )

    assert intent.name == "final_report"
    assert intent.preferred_tool == "generate_order_tool"
    assert intent.protect_from_freeform_report is True


def test_detect_selection_turn_does_not_force_transport_query():
    intent = detect_travel_intent(
        "就选第一个航班，帮我记录为交通方案。",
        current_step="transport_planning",
    )

    assert intent.name != "transport_query"
    assert intent.preferred_tool != "query_transport_options"


def test_detect_agency_plan_prefers_internal_product_tool():
    intent = detect_travel_intent(
        "我想要省心方案，最好按你们旅行社的成熟路线来。",
        current_step="destination_recommendation",
    )

    assert intent.name == "agency_plan_query"
    assert intent.preferred_tool == "search_agency_product_templates"


def test_detect_free_planning_keeps_neutral_mode():
    intent = detect_travel_intent(
        "我不跟团，只想自己出去玩，帮我做自由行规划。",
        current_step="requirement_collection",
    )

    assert intent.name == "free_planning_query"
    assert intent.preferred_tool is None


def test_detect_pricing_query_prefers_internal_pricing_rules():
    intent = detect_travel_intent(
        "这个报价费用包含什么，预算依据是什么？",
        current_step="budget_summarization",
    )

    assert intent.name == "pricing_query"
    assert intent.preferred_tool == "search_agency_pricing_rules"


def test_detect_risk_query_prefers_internal_risk_playbook():
    intent = detect_travel_intent(
        "这条路线有什么避坑和下雨 Plan B？",
        current_step="itinerary_generation",
    )

    assert intent.name == "risk_query"
    assert intent.preferred_tool == "search_agency_risk_playbook"


@pytest.mark.asyncio
async def test_middleware_opens_cross_step_hotel_tool_for_hotel_intent():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地阶段",
                "tools": ["select_destination_tool"],
                "requires": ["user_requirement"],
            },
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": ["query_hotel_options"],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            },
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {"destination": "长沙", "departure_date": "2026-06-19"},
        "selected_destination": "长沙",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请帮我查长沙湘江中路附近真实江景房酒店候选。")],
        ),
        handler,
    )

    assert "query_hotel_options" in captured["tools"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_hotel_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_hotel_options" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_removes_agency_tools_for_free_planning_intent():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "collect requirements",
                "tools": [
                    "record_requirement_tool",
                    "query_destination_info",
                    "search_agency_product_templates",
                    "search_agency_risk_playbook",
                ],
                "requires": [],
            },
        }
    )
    state = {"current_step": "requirement_collection"}

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "\u6211\u4e0d\u8ddf\u56e2\uff0c\u53ea\u60f3\u505a"
                        "\u81ea\u7531\u884c\u89c4\u5212\uff0c\u4e0d\u9700\u8981"
                        "\u65c5\u884c\u793e\u7701\u5fc3\u65b9\u6848\u3002"
                    )
                )
            ],
        ),
        handler,
    )

    assert "record_requirement_tool" in captured["tools"]
    assert "query_destination_info" in captured["tools"]
    assert "search_agency_product_templates" not in captured["tools"]
    assert "search_agency_risk_playbook" not in captured["tools"]


@pytest.mark.asyncio
async def test_middleware_opens_transport_and_hotel_tools_for_cross_step_verification():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "collect requirements",
                "tools": ["record_requirement_tool", "query_destination_info"],
                "requires": [],
            },
            "transport_planning": {
                "prompt": "transport",
                "tools": ["query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            },
            "accommodation_planning": {
                "prompt": "hotel",
                "tools": ["query_hotel_options"],
                "requires": [
                    "user_requirement",
                    "selected_destination",
                    "selected_transport",
                ],
            },
        }
    )
    state = {
        "current_step": "requirement_collection",
        "user_requirement": {
            "departure_city": "北京",
            "destination": "上海",
            "departure_date": "2026-06-19",
        },
        "selected_destination": "上海",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "\u53ef\u4ee5\u5f00\u59cb\u5b89\u6392\uff0c"
                        "\u5e76\u628a\u9700\u8981\u67e5\u8bc1\u7684"
                        "\u4ea4\u901a\u548c\u4f4f\u5bbf\u90fd\u67e5\u4e00\u4e0b\u3002"
                    )
                )
            ],
        ),
        handler,
    )

    assert "query_transport_options" in captured["tools"]
    assert "query_hotel_options" in captured["tools"]
    assert "query_transport_options" in captured["system_prompt"]
    assert "query_hotel_options" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_blocks_freeform_final_report_when_state_is_not_ready():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地阶段",
                "tools": ["select_destination_tool"],
                "requires": ["user_requirement"],
            },
            "order_generation": {
                "prompt": "订单阶段",
                "tools": ["generate_order_tool"],
                "requires": ["user_requirement", "itinerary", "budget"],
            },
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {"destination": "长沙"},
        "selected_destination": "长沙",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="不要再问了，直接生成最终旅游报告。")],
        ),
        handler,
    )

    assert "generate_order_tool" not in captured["tools"]
    assert captured["tool_choice"] is None
    assert "不要手写伪最终报告" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_opens_generate_order_tool_when_report_state_is_ready():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "budget_summarization": {
                "prompt": "预算阶段",
                "tools": ["summarize_budget_tool"],
                "requires": ["itinerary"],
            },
            "order_generation": {
                "prompt": "订单阶段",
                "tools": ["generate_order_tool"],
                "requires": ["user_requirement", "itinerary", "budget"],
            },
        }
    )
    state = {
        "current_step": "budget_summarization",
        "user_requirement": {"destination": "长沙"},
        "selected_destination": "长沙",
        "itinerary": [{"day_number": 1, "theme": "抵达"}],
        "budget": {"total": 7000},
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="预算没问题，直接生成最终旅游报告。")],
        ),
        handler,
    )

    assert "generate_order_tool" in captured["tools"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "generate_order_tool"
    else:
        assert captured["tool_choice"] is None
        assert "generate_order_tool" in captured["system_prompt"]
