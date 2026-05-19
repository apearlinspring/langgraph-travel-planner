import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.core.intent import detect_travel_intent, resolve_planning_mode
from app.core.middleware import StepConfigMiddleware
from app.utils.llm_factory import ModelCompatibility, get_model_compatibility


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


def _ready_report_state(**overrides):
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {
            "departure_city": "北京",
            "destination": "上海",
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_max": 8000,
        },
        "selected_destination": "上海",
        "selected_transport": "train",
        "selected_accommodation_types": ["star_hotel"],
        "itinerary": [
            {"day_number": 1, "theme": "抵达"},
            {"day_number": 2, "theme": "城市游览"},
            {"day_number": 3, "theme": "返程"},
        ],
        "budget": {"total": 7000},
    }
    state.update(overrides)
    return state


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


def test_detect_travel_planning_report_phrase_as_final_report():
    intent = detect_travel_intent(
        "方案可以，请生成最终旅游规划报告，包含每日行程、预算明细和地图路线节点。",
        current_step="itinerary_generation",
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
    assert intent.planning_mode == "agency_plan"
    assert intent.preferred_tool == "search_agency_product_templates"


def test_detect_destination_soft_product_candidate_without_rejection():
    intent = detect_travel_intent(
        "我想去新疆，先看看有没有成熟一点的路线样板。",
        current_step="requirement_collection",
        state={},
    )

    assert intent.name == "product_candidate_query"
    assert intent.planning_mode is None
    assert intent.preferred_tool == "search_agency_product_templates"


def test_detect_free_planning_keeps_neutral_mode():
    intent = detect_travel_intent(
        "我不跟团，只想自己出去玩，帮我做自由行规划。",
        current_step="requirement_collection",
    )

    assert intent.name == "free_planning_query"
    assert intent.planning_mode == "free_planning"
    assert intent.preferred_tool is None


def test_detect_agency_plan_can_override_no_group_tour_wording():
    intent = detect_travel_intent(
        "我不跟大团，但想让你们旅行社做定制游，不用我自己操心。",
        current_step="destination_recommendation",
    )

    assert intent.name == "agency_plan_query"
    assert intent.planning_mode == "agency_plan"
    assert intent.preferred_tool == "search_agency_product_templates"


def test_transport_fallback_plan_stays_neutral_mode():
    decision = resolve_planning_mode(
        "从西宁去敦煌，优先高铁，如果查不到合适车次也请给待核验兜底交通方案。",
        state={},
    )

    assert decision.mode is None


def test_detect_rejected_agency_plan_stays_free_planning():
    intent = detect_travel_intent(
        "不要旅行社产品，也别推销套餐，我只要自由行攻略。",
        current_step="destination_recommendation",
    )

    assert intent.name == "free_planning_query"
    assert intent.planning_mode == "free_planning"
    assert intent.preferred_tool is None


def test_product_candidate_respects_existing_free_planning_state():
    intent = detect_travel_intent(
        "我想去新疆，看看路线。",
        current_step="requirement_collection",
        state={"planning_mode": "free_planning", "planning_mode_confirmed": True},
    )

    assert intent.name != "product_candidate_query"


def test_accommodation_selection_with_price_verification_queries_hotels():
    intent = detect_travel_intent(
        "住宿按省心、干净、动线方便的方案记录；如果没有真实锁价，请标注待核验。",
        current_step="accommodation_planning",
    )

    assert intent.name == "hotel_query"
    assert intent.preferred_tool == "query_hotel_options"


def test_resolve_planning_mode_marks_ambiguous_mode_for_confirmation():
    decision = resolve_planning_mode(
        "我想省心一点，但也想自己订酒店机票，不确定要不要旅行社方案。",
        state={},
    )

    assert decision.mode is None
    assert decision.needs_confirmation is True
    assert decision.confirmed is False


def test_complete_first_turn_without_mode_asks_for_two_planning_choices():
    decision = resolve_planning_mode(
        "我想从西安出发去西藏，出发时间大概是下周一，行程预计7天，同行人数是2人，预算希望控制在每人5000",
        state={"current_step": "requirement_collection"},
    )

    assert decision.mode is None
    assert decision.needs_confirmation is True
    assert decision.confirmed is False
    assert "省心方案" in decision.reason
    assert "个性化旅游规划" in decision.reason


def test_personalized_travel_planning_phrase_maps_to_free_planning():
    intent = detect_travel_intent(
        "我想要个性化旅游规划，不要现成旅行社产品。",
        current_step="requirement_collection",
    )
    decision = resolve_planning_mode(
        "我想要个性化旅游规划，不要现成旅行社产品。",
        state={},
        intent=intent,
    )

    assert intent.name == "free_planning_query"
    assert intent.planning_mode == "free_planning"
    assert decision.mode == "free_planning"
    assert decision.confirmed is True


def test_resolve_planning_mode_uses_persisted_state_when_latest_text_is_neutral():
    decision = resolve_planning_mode(
        "那继续安排下一步。",
        state={
            "planning_mode": "agency_plan",
            "planning_mode_reason": "用户已确认希望按旅行社顾问方案交付",
            "planning_mode_confirmed": True,
        },
    )

    assert decision.mode == "agency_plan"
    assert decision.source == "state"
    assert decision.confirmed is True


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
    assert "当前规划模式：自由规划" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_uses_persisted_free_planning_mode_across_steps():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "destination",
                "tools": [
                    "select_destination_tool",
                    "query_destination_info",
                    "search_agency_product_templates",
                    "search_agency_risk_playbook",
                ],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "planning_mode": "free_planning",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "destination": "上海",
            "planning_mode": "free_planning",
            "planning_mode_confirmed": True,
        },
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="帮我推荐几个适合城市漫步的景点。")]),
        handler,
    )

    assert "query_destination_info" in captured["tools"]
    assert "search_agency_product_templates" not in captured["tools"]
    assert "search_agency_risk_playbook" not in captured["tools"]
    assert "当前规划模式：自由规划" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_keeps_pricing_tool_in_free_planning_mode():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "itinerary_generation": {
                "prompt": "itinerary",
                "tools": ["generate_itinerary_tool", "search_agency_product_templates"],
                "requires": ["user_requirement"],
            },
            "budget_summarization": {
                "prompt": "budget",
                "tools": ["search_agency_pricing_rules"],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "itinerary_generation",
        "planning_mode": "free_planning",
        "user_requirement": {"planning_mode": "free_planning"},
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="自由行也帮我看下预算依据和费用包含什么。")]),
        handler,
    )

    assert "search_agency_pricing_rules" in captured["tools"]
    assert "search_agency_product_templates" not in captured["tools"]
    assert "当前规划模式：自由规划" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_latest_agency_mode_overrides_persisted_free_mode():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "transport",
                "tools": ["query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            },
            "requirement_collection": {
                "prompt": "collect",
                "tools": [
                    "set_planning_mode_tool",
                    "confirm_planning_mode_tool",
                    "search_agency_product_templates",
                ],
                "requires": [],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "planning_mode": "free_planning",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "planning_mode": "free_planning",
            "planning_mode_confirmed": True,
        },
        "selected_destination": "成都",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="还是按你们旅行社省心方案来，我不想自己做攻略。")],
        ),
        handler,
    )

    assert "search_agency_product_templates" in captured["tools"]
    assert "当前规划模式：旅行社顾问方案" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_asks_to_confirm_ambiguous_planning_mode():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "collect",
                "tools": [
                    "record_requirement_tool",
                    "set_planning_mode_tool",
                    "confirm_planning_mode_tool",
                    "search_agency_product_templates",
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
            [HumanMessage(content="我想省心一点，但也想自己订酒店机票，不确定要不要旅行社方案。")],
        ),
        handler,
    )

    assert "confirm_planning_mode_tool" in captured["tools"]
    assert "record_requirement_tool" not in captured["tools"]
    assert "search_agency_product_templates" not in captured["tools"]
    assert "规划模式表达不够明确" in captured["system_prompt"]
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_asks_mode_for_complete_first_turn_without_mode():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "collect",
                "tools": [
                    "record_requirement_tool",
                    "set_planning_mode_tool",
                    "confirm_planning_mode_tool",
                    "search_agency_product_templates",
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
                        "我想从西安出发去西藏，出发时间大概是下周一，"
                        "行程预计7天，同行人数是2人，预算希望控制在每人5000。"
                    )
                )
            ],
        ),
        handler,
    )

    assert "confirm_planning_mode_tool" in captured["tools"]
    assert "record_requirement_tool" not in captured["tools"]
    assert "search_agency_product_templates" not in captured["tools"]
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_does_not_record_requirement_before_mode_confirmation(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=True),
    )
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "collect",
                "tools": [
                    "record_requirement_tool",
                    "set_planning_mode_tool",
                    "confirm_planning_mode_tool",
                    "search_agency_product_templates",
                ],
                "requires": [],
            },
        }
    )
    state = {"current_step": "requirement_collection"}

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "从上海到成都，2026-06-01 出发，玩4天，2个成人，"
                        "预算每人6000，喜欢美食文化。我想省心一点，"
                        "但也想自己订酒店机票，不确定要不要旅行社方案，开始规划。"
                    )
                )
            ],
        ),
        handler,
    )

    assert "confirm_planning_mode_tool" in captured["tools"]
    assert "record_requirement_tool" not in captured["tools"]
    assert captured["tool_choice"] is None
    assert "规划模式表达不够明确" in captured["system_prompt"]


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
async def test_middleware_keeps_hotel_fallback_audit_query_from_original_request():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "hotel",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": [
                    "user_requirement",
                    "selected_destination",
                    "selected_transport",
                ],
            },
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_city": "西安",
            "destination": "长沙",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
        },
        "selected_destination": "长沙",
        "selected_transport": "train",
        "messages": [
            HumanMessage(
                content="我想去长沙，住湘江边江景房，4天3晚，如果查不到具体酒店也请给兜底方案。"
            )
        ],
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="住宿按省心、干净、动线方便的方案记录，真实价格标注待核验。")],
        ),
        handler,
    )

    assert captured["tools"] == ["query_hotel_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_hotel_options"
    else:
        assert "query_hotel_options" in captured["system_prompt"]
    assert "保留一次酒店查询工具调用作为治理证据" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_keeps_transport_fallback_audit_query_from_original_request():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "transport",
                "tools": ["select_transport_tool", "query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_city": "武汉",
            "destination": "张家界",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
        },
        "selected_destination": "张家界",
        "messages": [
            HumanMessage(
                content="我想从武汉去张家界玩4天3晚，优先高铁，如果查不到合适车次也请给交通兜底。"
            )
        ],
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="交通按省心和时间合理优先，请直接记录推荐方式；真实班次和价格待核验。")],
        ),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_transport_options"
    else:
        assert "query_transport_options" in captured["system_prompt"]
    assert "保留一次交通查询工具调用作为治理证据" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_keeps_transport_audit_query_for_pending_verification_turn():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "transport",
                "tools": ["select_transport_tool", "query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_city": "武汉",
            "destination": "张家界",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
        },
        "selected_destination": "张家界",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content="交通按省心和时间合理优先，请直接记录推荐方式；真实班次和价格待核验。"
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_transport_options"
    else:
        assert "query_transport_options" in captured["system_prompt"]
    assert "让工具守卫返回 skipped 审计结果" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_keeps_hotel_audit_query_for_unlocked_price_turn():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "hotel",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": [
                    "user_requirement",
                    "selected_destination",
                    "selected_transport",
                ],
            },
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_city": "西安",
            "destination": "长沙",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
        },
        "selected_destination": "长沙",
        "selected_transport": "train",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content="住宿按省心、干净、动线方便的方案记录；如果没有真实锁价，请标注待核验。"
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["query_hotel_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_hotel_options"
    else:
        assert "query_hotel_options" in captured["system_prompt"]
    assert "不要执行真实库存、班次、票价或锁价查询" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_query_result_does_not_auto_select_on_destination_confirmation():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "transport",
                "tools": ["select_transport_tool", "query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_city": "广州",
            "destination": "桂林",
            "departure_date": "2026-07-10",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 3,
            "children_count": 0,
        },
        "selected_destination": "桂林",
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content="目的地确认桂林，请把天气风险、Plan B和适合老人低强度玩法一起记录到目的地上下文。"
                ),
                ToolMessage(
                    content="已查询交通候选，真实班次待核验。",
                    name="query_transport_options",
                    tool_call_id="call-transport-query",
                ),
            ],
        ),
        handler,
    )

    assert captured["tools"] == []
    assert captured.get("tool_choice") is None
    assert "不要在同一轮继续调用 `select_transport_tool`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_query_result_selects_after_recent_record_authorization():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "transport",
                "tools": ["select_transport_tool", "query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_city": "出发地待确认",
            "destination": "长沙",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 4,
            "adult_count": 1,
            "children_count": 0,
        },
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
            [
                HumanMessage(
                    content="交通按省心和时间合理优先，请直接记录你推荐的方式；实时班次和价格标注待核验。"
                ),
                HumanMessage(content="餐饮按本地特色和轻松节奏安排，请直接记录推荐方向。"),
                ToolMessage(
                    content="日期待确认，已跳过真实交通查询，需二次核验。",
                    name="query_transport_options",
                    tool_call_id="call-transport-query",
                ),
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["select_transport_tool"]
    if get_model_compatibility(profile="planner").supports_forced_tool_choice:
        assert captured["tool_choice"] == "select_transport_tool"
    else:
        assert "select_transport_tool" in captured["system_prompt"]
    assert "用户已经明确授权按推荐结果直接记录交通方案" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_initial_budgeted_style_trip_uses_lightweight_confirmation():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "requirement",
                "tools": ["record_requirement_tool", "query_destination_info"],
                "requires": [],
            },
        }
    )
    state = {"current_step": "requirement_collection", "user_requirement": {}}

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content="我想周末从西安出发去附近轻松玩两天，2个人，预算1500，想看自然风景和吃点当地小吃。"
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == []
    assert "首轮轻量响应" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_initial_requirement_record_stops_same_turn_slow_fanout():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "destination",
                "tools": [
                    "query_destination_info",
                    "search_agency_pricing_rules",
                    "search_food_recommendations",
                ],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {
            "departure_city": "成都",
            "destination": "重庆",
            "departure_date": "2026-06-20",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 4,
            "budget_min": 1500,
            "budget_max": 2500,
        },
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
                    content="我们4个大人想在2026-06-20从成都去重庆3天2晚，人均预算1500-2500元，想要省心方案。请按旅行社顾问方案先记录需求。"
                ),
                ToolMessage(
                    content="已记录需求",
                    name="record_requirement_tool",
                    tool_call_id="call-record",
                ),
            ],
        ),
        handler,
    )

    assert captured["tools"] == []
    assert "本轮已经完成需求记录" in captured["system_prompt"]


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
async def test_middleware_opens_generate_order_tool_when_report_basics_are_ready():
    captured = {}
    compatibility = get_model_compatibility()
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
    state = _ready_report_state()

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="\u8bf7\u76f4\u63a5\u751f\u6210\u6700\u7ec8\u65c5\u6e38\u62a5\u544a\u3002")],
        ),
        handler,
    )

    assert captured["tools"] == ["generate_order_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "generate_order_tool"
    else:
        assert captured["tool_choice"] is None
        assert "generate_order_tool" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_final_report_request_forces_missing_budget_after_tool_result():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "budget_summarization": {
                "prompt": "预算阶段",
                "tools": ["summarize_budget_tool"],
                "requires": ["user_requirement", "itinerary"],
            },
            "order_generation": {
                "prompt": "订单阶段",
                "tools": ["generate_order_tool"],
                "requires": ["user_requirement", "itinerary", "budget"],
            },
        }
    )
    state = _ready_report_state(
        current_step="budget_summarization",
        budget=None,
        messages=[HumanMessage(content="请直接生成最终旅行规划报告和report_data。")],
    )

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(content="请直接生成最终旅行规划报告和report_data。"),
                ToolMessage(
                    content="已生成行程",
                    name="generate_itinerary_tool",
                    tool_call_id="call-itinerary",
                ),
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["summarize_budget_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "summarize_budget_tool"
    else:
        assert "summarize_budget_tool" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_final_report_request_forces_missing_itinerary_before_budget():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "itinerary_generation": {
                "prompt": "行程阶段",
                "tools": ["generate_itinerary_tool"],
                "requires": [
                    "user_requirement",
                    "selected_destination",
                    "selected_transport",
                    "selected_accommodation_types",
                    "selected_food_types",
                ],
            },
            "budget_summarization": {
                "prompt": "预算阶段",
                "tools": ["summarize_budget_tool"],
                "requires": ["user_requirement", "itinerary"],
            },
        }
    )
    state = _ready_report_state(
        current_step="itinerary_generation",
        itinerary=None,
        budget=None,
        selected_food_types=["local"],
    )

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请直接生成最终旅行规划报告和report_data。")],
        ),
        handler,
    )

    assert captured["tools"] == ["generate_itinerary_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "generate_itinerary_tool"
    else:
        assert "generate_itinerary_tool" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_final_report_intent_overrides_destination_selection_confirmation():
    captured = {}
    compatibility = get_model_compatibility()
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
    state = _ready_report_state(destination_options=[{"name": "\u4e0a\u6d77"}])

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "\u4e0a\u6d77\u6ca1\u95ee\u9898\uff0c"
                        "\u8bf7\u76f4\u63a5\u751f\u6210\u6700\u7ec8\u65c5\u6e38\u62a5\u544a\u3002"
                    )
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["generate_order_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "generate_order_tool"
    else:
        assert captured["tool_choice"] is None
        assert "generate_order_tool" in captured["system_prompt"]
        assert "select_destination_tool" not in captured["system_prompt"]


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
    state = _ready_report_state(
        current_step="budget_summarization",
        user_requirement={
            "destination": "长沙",
            "departure_city": "西安",
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_max": 8000,
        },
        selected_destination="长沙",
    )

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

    assert captured["tools"] == ["generate_order_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "generate_order_tool"
    else:
        assert captured["tool_choice"] is None
        assert "generate_order_tool" in captured["system_prompt"]
