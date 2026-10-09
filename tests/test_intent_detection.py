import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.core.intent import detect_travel_intent, resolve_planning_mode
from app.core.middleware import StepConfigMiddleware, _progress_tool_for_explicit_request
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


def _force_supported_tool_choice(monkeypatch):
    compatibility = ModelCompatibility(supports_forced_tool_choice=True)
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: compatibility,
    )
    return compatibility


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


def test_progress_report_or_export_with_map_nodes_keeps_report_sequence_priority():
    report_text = (
        "请生成最终旅游规划报告和 report_data，包含每日地图路线节点。"
    )
    free_missing_itinerary = _ready_report_state(itinerary=None, budget=None)
    agency_overrides = {
        "active_workflow": "agency_plan",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "agency_step": "agency_report",
        "user_requirement": {
            "departure_city": "北京",
            "destination": "上海",
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_max": 8000,
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
    }
    agency_missing_budget = _ready_report_state(
        **agency_overrides,
        budget=None,
    )
    agency_ready = _ready_report_state(**agency_overrides)

    assert (
        _progress_tool_for_explicit_request(report_text, free_missing_itinerary)
        == "generate_itinerary_tool"
    )
    assert (
        _progress_tool_for_explicit_request(report_text, agency_missing_budget)
        == "summarize_budget_tool"
    )
    assert (
        _progress_tool_for_explicit_request(report_text, agency_ready)
        == "generate_order_tool"
    )
    assert (
        _progress_tool_for_explicit_request(
            "请导出 PDF，保留地图路线节点。",
            _ready_report_state(),
        )
        == "generate_order_tool"
    )


def test_progress_structured_itinerary_with_map_nodes_beats_visual_draft():
    state = _ready_report_state(itinerary=None, budget=None)
    text = "请生成并记录3天2晚结构化行程，包含每日地图路线节点。"

    assert (
        _progress_tool_for_explicit_request(text, state)
        == "generate_itinerary_tool"
    )
    assert (
        _progress_tool_for_explicit_request(
            text,
            _ready_report_state(
                itinerary=None,
                budget=None,
                selected_transport=None,
                selected_accommodation_types=[],
            ),
        )
        is None
    )


def test_progress_pure_visual_route_request_keeps_visual_journey_tool():
    assert (
        _progress_tool_for_explicit_request(
            "先给我路线图和可视化旅程草案。",
            {"selected_destination": "南京"},
        )
        == "generate_visual_journey_tool"
    )


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


def test_pending_fast_split_neutral_confirmation_defaults_to_free():
    initial_text = (
        "我想周末从西安出发去附近轻松玩两天，2个人，预算1500，"
        "想看自然风景和吃点当地小吃。"
    )
    state = {
        "current_step": "requirement_collection",
        "fast_mode_split_needs_confirmation": True,
        "pending_initial_request_text": initial_text,
    }

    decision = resolve_planning_mode(
        "以上需求确认无误，请先记录需求，然后继续推进规划。",
        state=state,
    )

    assert decision.mode == "free_planning"
    assert decision.confirmed is True
    assert decision.source == "latest_user"


def test_pending_fast_split_explicit_agency_choice_still_wins():
    state = {
        "current_step": "requirement_collection",
        "fast_mode_split_needs_confirmation": True,
        "pending_initial_request_text": "西安出发周末玩两天，2个人，预算1500。",
    }

    decision = resolve_planning_mode(
        "以上需求没问题，我选择旅行社省心方案。",
        state=state,
    )

    assert decision.mode == "agency_plan"
    assert decision.confirmed is True


def test_compact_route_first_turn_without_mode_asks_for_two_planning_choices():
    decision = resolve_planning_mode(
        "西安到西藏，下周一，7天，2人，每人5000",
        state={"current_step": "requirement_collection"},
    )

    assert decision.mode is None
    assert decision.needs_confirmation is True
    assert decision.confirmed is False


def test_destination_with_chinese_people_count_without_mode_asks_for_two_planning_choices():
    decision = resolve_planning_mode(
        "我们两个人，想去云南玩，大概预算每人5000,5天左右",
        state={"current_step": "requirement_collection"},
    )

    assert decision.mode is None
    assert decision.needs_confirmation is True
    assert decision.confirmed is False
    assert "省心方案" in decision.reason
    assert "个性化旅游规划" in decision.reason


def test_ready_made_plan_phrase_maps_to_agency_plan():
    decision = resolve_planning_mode(
        "现成的方案吧",
        state={"current_step": "requirement_collection"},
    )

    assert decision.mode == "agency_plan"
    assert decision.confirmed is True


def test_unconfirmed_persisted_mode_stays_pending_on_next_turn():
    decision = resolve_planning_mode(
        "预算还是按前面说的范围就好。",
        state={
            "current_step": "requirement_collection",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": False,
            "pending_initial_planning_mode": "agency_plan",
        },
    )

    assert decision.mode == "agency_plan"
    assert decision.source == "state"
    assert decision.confirmed is False
    assert decision.needs_confirmation is True


def test_mixed_free_and_agency_tendency_requires_confirmation():
    decision = resolve_planning_mode(
        "我想自己订酒店机票，也希望旅行社顾问帮我定制路线。",
        state={"current_step": "requirement_collection"},
    )

    assert decision.mode == "agency_plan"
    assert decision.confirmed is False
    assert decision.needs_confirmation is True


@pytest.mark.asyncio
async def test_unconfirmed_agency_preference_does_not_enter_agency_workflow():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "collect",
                "tools": ["set_planning_mode_tool", "confirm_planning_mode_tool"],
                "requires": [],
            },
            "agency_requirement": {
                "prompt": "agency",
                "tools": ["search_agency_product_templates"],
                "requires": [],
            },
        }
    )
    state = {
        "current_step": "requirement_collection",
        "agency_step": "agency_requirement",
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "planning_mode_confirmed": False,
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="预算还是按前面说的范围就好。")]),
        handler,
    )

    assert captured["tools"] == []
    assert "规划模式表达不够明确" in captured["system_prompt"]
    assert "旅行社方案工作流已锁定" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_forces_mode_confirmation_when_user_selects_agency_plan(monkeypatch):
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
        DummyRequest(state, [HumanMessage(content="现成的方案吧")]),
        handler,
    )

    assert captured["tools"] == ["confirm_planning_mode_tool"]
    assert captured["tool_choice"] == "confirm_planning_mode_tool"
    assert "mode 参数传 agency_plan" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_agency_plan_transport_stage_does_not_force_free_planning_preferences(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=True),
    )
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "transport",
                "tools": [
                    "query_transport_options",
                    "select_transport_tool",
                    "query_hotel_options",
                    "select_accommodation_tool",
                    "scenic_price_lookup_tool",
                    "search_agency_product_templates",
                ],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "departure_city": "西安",
            "destination": "南京",
            "departure_date": "2026-05-25",
            "travel_days": 4,
            "adult_count": 2,
            "planning_mode": "agency_plan",
        },
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="人均5000左右")]),
        handler,
    )

    assert "query_transport_options" not in captured["tools"]
    assert "select_transport_tool" not in captured["tools"]
    assert "query_hotel_options" not in captured["tools"]
    assert "select_accommodation_tool" not in captured["tools"]
    assert captured["tool_choice"] not in {"query_transport_options", "select_transport_tool"}
    assert "不要询问用户选择飞机/高铁或酒店偏好" in captured["system_prompt"]
    assert "不得把高铁、火车、车次或航班写成已确认、有票、可订、准点或已出票" in captured[
        "system_prompt"
    ]
    assert "班次、时刻和票价待二次核验" in captured["system_prompt"]
    assert "不得写酒店有房、房型可订或已锁房" in captured["system_prompt"]
    assert "不得写库存、名额、余位或席位有、充足、可订、已预留或已锁定" in captured[
        "system_prompt"
    ]
    assert "‘确认后说明’不能代替核验限定" in captured["system_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "state", "user_message", "expects_pricing_guard"),
    [
        (
            "transport_planning",
            {
                "current_step": "transport_planning",
                "planning_mode": "free_planning",
                "active_workflow": "free_planning",
                "planning_mode_confirmed": True,
            },
            "交通按前面说的继续。",
            False,
        ),
        (
            "agency_product_match",
            {
                "current_step": "agency_product_match",
                "agency_step": "agency_product_match",
                "planning_mode": "agency_plan",
                "active_workflow": "agency_plan",
                "planning_mode_confirmed": True,
                "user_requirement": {
                    "planning_mode": "agency_plan",
                    "planning_mode_confirmed": True,
                },
            },
            "请解释报价、费用包含和库存边界。",
            True,
        ),
        (
            "requirement_collection",
            {
                "current_step": "requirement_collection",
                "planning_mode": "agency_plan",
                "active_workflow": "agency_plan",
                "planning_mode_confirmed": False,
            },
            "继续安排下一步。",
            False,
        ),
    ],
)
async def test_global_transport_claim_guard_is_last_for_every_mode_and_step(
    step,
    state,
    user_message,
    expects_pricing_guard,
):
    captured = {}
    middleware = StepConfigMiddleware(
        {
            step: {
                "prompt": f"{step} prompt",
                "tools": [],
                "requires": [],
            },
        }
    )

    async def handler(request):
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=user_message)]),
        handler,
    )

    prompt = captured["system_prompt"]
    guard_heading = "【动态交通事实逐句输出硬校验（最高优先级）】"
    assert guard_heading in prompt
    assert "车次/航班/班次/高铁/火车/机票" in prompt
    assert "已确认/有票/余票/已出票/可订/准点" in prompt
    assert "同一句必须明确包含“待二次核验”“未确认”或“以官方为准”" in prompt
    assert "如果无法在同一句加入核验限定，必须删除整个动态断言" in prompt
    assert prompt.rstrip().endswith(
        "也不能用“确认后说明”代替同句限定。"
    )
    if expects_pricing_guard:
        assert "必须同句写明待二次核验、当前未确认" in prompt
        assert prompt.rfind(guard_heading) > prompt.rfind(
            "必须同句写明待二次核验、当前未确认"
        )


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


@pytest.mark.asyncio
async def test_agency_pricing_turn_blocks_budget_and_report_without_itinerary():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "agency_plan_draft": {
                "prompt": "省心方案草案",
                "tools": [
                    "record_requirement_tool",
                    "record_evidence_bundle_tool",
                    "search_agency_pricing_rules",
                    "search_agency_report_standards",
                    "query_destination_info",
                    "scenic_price_lookup_tool",
                    "generate_itinerary_tool",
                    "summarize_budget_tool",
                    "generate_order_tool",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "requirement_collection",
        "agency_step": "agency_plan_draft",
        "active_workflow": "agency_plan",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "selected_destination": "成都",
        "user_requirement": {
            "departure_city": "西安",
            "destination": "成都",
            "departure_date": "2026-10-23",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_text": "总预算 8000 元",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请说明报价费用包含什么、预算依据，并汇总预算。")],
        ),
        handler,
    )

    assert captured["tools"] == [
        "record_requirement_tool",
        "record_evidence_bundle_tool",
        "search_agency_pricing_rules",
    ]
    assert "search_agency_report_standards" not in captured["tools"]
    assert "query_destination_info" not in captured["tools"]
    assert "scenic_price_lookup_tool" not in captured["tools"]
    assert "generate_itinerary_tool" not in captured["tools"]
    assert "summarize_budget_tool" not in captured["tools"]
    assert "generate_order_tool" not in captured["tools"]
    assert captured["tool_choice"] not in {
        "summarize_budget_tool",
        "generate_order_tool",
    }
    assert "本轮只说明内部报价规则" in captured["system_prompt"]
    assert "不得调用目的地动态搜索" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_agency_pricing_intent_survives_tool_message_and_keeps_tools_narrowed():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "agency_plan_draft": {
                "prompt": "省心方案匹配",
                "tools": [
                    "record_evidence_bundle_tool",
                    "search_agency_pricing_rules",
                    "search_agency_product_templates",
                    "query_destination_info",
                    "scenic_price_lookup_tool",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "requirement_collection",
        "agency_step": "agency_product_match",
        "active_workflow": "agency_plan",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "selected_destination": "成都",
        "user_requirement": {
            "departure_city": "西安",
            "destination": "成都",
            "departure_date": "2026-10-23",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_text": "总预算 8000 元",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
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
                HumanMessage(content="请说明报价费用包含什么、预算依据和待核验项。"),
                ToolMessage(
                    content="已返回内部报价规则。",
                    name="search_agency_pricing_rules",
                    tool_call_id="call-pricing-rules",
                ),
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["record_evidence_bundle_tool"]
    assert captured["tool_choice"] is None
    assert "本轮用户关注报价、费用包含或预算依据" in captured["system_prompt"]
    assert "不得调用目的地动态搜索" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_agency_budget_turn_keeps_and_forces_budget_tool_with_itinerary(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
    middleware = StepConfigMiddleware(
        {
            "agency_plan_draft": {
                "prompt": "省心方案草案",
                "tools": [
                    "search_agency_pricing_rules",
                    "generate_itinerary_tool",
                    "summarize_budget_tool",
                    "generate_order_tool",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "requirement_collection",
        "agency_step": "agency_plan_draft",
        "active_workflow": "agency_plan",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "selected_destination": "成都",
        "itinerary": [
            {"day_number": day, "activities": [f"第 {day} 天行程"]}
            for day in range(1, 5)
        ],
        "user_requirement": {
            "departure_city": "西安",
            "destination": "成都",
            "departure_date": "2026-10-23",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_text": "总预算 8000 元",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="请汇总并记录结构化预算。")]),
        handler,
    )

    assert captured["tools"] == ["summarize_budget_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "summarize_budget_tool"
    else:
        assert captured["tool_choice"] is None


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
    assert "必须同句写明待二次核验、当前未确认" in captured["system_prompt"]


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

    assert captured["tools"] == []
    assert "规划模式表达不够明确" in captured["system_prompt"]
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]
    assert "不要整理已知信息" in captured["system_prompt"]
    assert "先用一句自然" in captured["system_prompt"]


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
                HumanMessage(content="西安到西藏，下周一，7天，2人，每人5000")
            ],
        ),
        handler,
    )

    assert captured["tools"] == []
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]
    assert "不要整理已知信息" in captured["system_prompt"]
    assert "先用一句自然" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_middleware_asks_mode_for_destination_budget_duration_with_chinese_count():
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
            [HumanMessage(content="我们两个人，想去云南玩，大概预算每人5000,5天左右")],
        ),
        handler,
    )

    assert captured["tools"] == []
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]
    assert "先用一句自然" in captured["system_prompt"]
    assert "必须使用用户原文里的目的地" in captured["system_prompt"]


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

    assert captured["tools"] == []
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
async def test_initial_budgeted_style_trip_confirms_planning_mode_first():
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
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]
    assert "不要整理已知信息" in captured["system_prompt"]
    assert "首轮轻量响应" not in captured["system_prompt"]


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
async def test_middleware_opens_generate_order_tool_when_report_basics_are_ready(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
async def test_final_report_request_forces_missing_budget_after_tool_result(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
async def test_final_report_request_forces_missing_itinerary_before_budget(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
async def test_explicit_agency_itinerary_request_does_not_require_free_planning_selections(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=True),
    )
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "agency_plan_draft": {
                "prompt": "省心方案草案",
                "tools": ["generate_itinerary_tool", "summarize_budget_tool"],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "agency_step": "agency_plan_draft",
        "active_workflow": "agency_plan",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "destination": "成都",
            "travel_days": 4,
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
        "selected_destination": "成都",
        "selected_transport": None,
        "selected_accommodation_types": [],
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="请生成并记录4天3晚结构化行程。")]),
        handler,
    )

    assert captured["tools"] == ["generate_itinerary_tool"]
    assert captured["tool_choice"] == "generate_itinerary_tool"


@pytest.mark.asyncio
async def test_explicit_free_itinerary_request_still_requires_transport_and_accommodation(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=True),
    )
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "food_planning": {
                "prompt": "餐饮阶段",
                "tools": ["select_food_tool", "search_food_recommendations"],
                "requires": ["user_requirement"],
            },
            "itinerary_generation": {
                "prompt": "行程阶段",
                "tools": ["generate_itinerary_tool"],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "food_planning",
        "active_workflow": "free_planning",
        "planning_mode": "free_planning",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "destination": "成都",
            "travel_days": 4,
            "planning_mode": "free_planning",
            "planning_mode_confirmed": True,
        },
        "selected_destination": "成都",
        "selected_transport": None,
        "selected_accommodation_types": [],
    }

    async def handler(request):
        captured["tools"] = request.tools
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="请生成并记录4天3晚结构化行程。")]),
        handler,
    )

    assert "generate_itinerary_tool" not in captured["tools"]
    assert captured["tool_choice"] is None


@pytest.mark.asyncio
async def test_final_report_intent_overrides_destination_selection_confirmation(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
async def test_middleware_opens_generate_order_tool_when_report_state_is_ready(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
