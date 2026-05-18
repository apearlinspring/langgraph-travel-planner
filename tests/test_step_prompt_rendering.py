from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.middleware import StepConfigMiddleware
from app.utils.llm_factory import get_model_compatibility


class DummyRequest:
    def __init__(self, state, messages=None):
        self.state = state
        self.messages = messages or []

    def override(self, **kwargs):
        merged = {**self.__dict__, **kwargs}
        return SimpleNamespace(**merged)


@pytest.mark.asyncio
async def test_step_middleware_renders_python_style_placeholders():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": (
                    "目的地：{selected_destination}\n"
                    "出发地：{origin_city}\n"
                    "日期：{user_requirement.departure_date}\n"
                    "人数：{user_requirement.adult_count}+{user_requirement.children_count}"
                ),
                "tools": ["tool-a"],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )

    state = {
        "current_step": "accommodation_planning",
        "selected_destination": "北京",
        "selected_transport": "train",
        "user_requirement": {
            "departure_city": "上海",
            "departure_date": "2026-05-29",
            "adult_count": 2,
            "children_count": 1,
        },
    }

    async def handler(request):
        captured["system_prompt"] = request.system_prompt
        captured["tools"] = request.tools
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state), handler)

    assert "目的地：北京" in captured["system_prompt"]
    assert "出发地：上海" in captured["system_prompt"]
    assert "日期：2026-05-29" in captured["system_prompt"]
    assert "人数：2+1" in captured["system_prompt"]
    assert captured["tools"] == ["tool-a"]


@pytest.mark.asyncio
async def test_step_middleware_heals_missing_accommodation_type_from_selected_option():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "itinerary_generation": {
                "prompt": "住宿：{selected_accommodation_summary}",
                "tools": ["generate_itinerary_tool"],
                "requires": [
                    "user_requirement",
                    "selected_destination",
                    "selected_transport",
                    "selected_accommodation_types",
                    "selected_food_types",
                ],
            }
        }
    )
    state = {
        "current_step": "itinerary_generation",
        "user_requirement": {"destination": "北京", "travel_days": 5},
        "selected_destination": "北京",
        "selected_transport": "train",
        "selected_accommodation_option": {
            "name": "北京核心区舒适酒店",
            "type": "comfort_hotel",
            "location": "核心区",
        },
        "selected_food_types": ["local"],
    }

    async def handler(request):
        captured["system_prompt"] = request.system_prompt
        captured["tools"] = request.tools
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state), handler)

    assert state["selected_accommodation_types"] == ["star_hotel"]
    assert "北京核心区舒适酒店" in captured["system_prompt"]
    assert captured["tools"] == ["generate_itinerary_tool"]


@pytest.mark.asyncio
async def test_step_middleware_injects_order_stage_summaries():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "order_generation": {
                "prompt": (
                    "交通：{selected_transport_summary}\n"
                    "住宿：{selected_accommodation_summary}\n"
                    "行程：{itinerary_summary}\n"
                    "预算：{budget_summary}"
                ),
                "tools": ["tool-a"],
                "requires": ["user_requirement", "itinerary", "budget"],
            }
        }
    )

    state = {
        "current_step": "order_generation",
        "user_requirement": {},
        "selected_transport_option": {
            "details": "G1 北京南 -> 上海虹桥",
            "departure_time": "09:00",
            "arrival_time": "13:29",
            "duration": "4小时29分",
            "price": 626.0,
            "source": "12306-mcp",
        },
        "selected_accommodation_option": {
            "name": "上海城市酒店",
            "location": "人民广场",
            "price_per_night": 650.0,
        },
        "itinerary": [
            {
                "day_number": 1,
                "theme": "外滩夜景",
                "activities": ["外滩", "南京路"],
            }
        ],
        "budget": {
            "transport": 1252.0,
            "accommodation": 1300.0,
            "food": 1320.0,
            "total": 5672.0,
            "per_person": 2836.0,
            "assumptions": ["交通按已选具体方案价格估算"],
        },
    }

    async def handler(request):
        captured["system_prompt"] = request.system_prompt
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state), handler)

    assert "G1 北京南 -> 上海虹桥" in captured["system_prompt"]
    assert "上海城市酒店" in captured["system_prompt"]
    assert "Day 1 外滩夜景" in captured["system_prompt"]
    assert "总计：5672.00 元" in captured["system_prompt"]
    assert "关键假设：交通按已选具体方案价格估算" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_step_middleware_packs_long_context_into_summary():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": ["record_requirement_tool"],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}
    messages = [
        HumanMessage(content=f"第{i}轮：预算{i * 1000}元，确认继续。")
        for i in range(20)
    ]

    async def handler(request):
        captured["system_prompt"] = request.system_prompt
        captured["messages"] = request.messages
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "【会话摘要】" in captured["system_prompt"]
    assert "【短期规划状态】" in captured["system_prompt"]
    assert len(captured["messages"]) == 6
    assert state["conversation_summary"]
    assert state["key_history_turns"]
    assert "key_history" in state["context_layer_boundaries"]
    assert state["context_pack_metadata"]["summary_triggered"] is True


@pytest.mark.asyncio
async def test_step_middleware_forces_direct_hotel_query_only_on_user_turn():
    captured = []
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": ["query_hotel_options"],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {},
        "selected_destination": "上海",
        "selected_transport": "train",
    }

    async def handler(request):
        captured.append(
            {
                "tool_choice": getattr(request, "tool_choice", None),
                "system_prompt": getattr(request, "system_prompt", ""),
            }
        )
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="信息已经齐了，请直接查真实酒店。")],
        ),
        handler,
    )
    state["messages"] = [HumanMessage(content="信息已经齐了，请直接查真实酒店。")]
    await middleware.awrap_model_call(DummyRequest(state), handler)
    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [ToolMessage(content="工具结果", tool_call_id="1", name="query_hotel_options")],
        ),
        handler,
    )

    if compatibility.supports_forced_tool_choice:
        assert [item["tool_choice"] for item in captured] == [
            "query_hotel_options",
            "query_hotel_options",
            None,
        ]
    else:
        assert [item["tool_choice"] for item in captured] == [None, None, None]
        assert "query_hotel_options" in captured[0]["system_prompt"]
        assert "query_hotel_options" in captured[1]["system_prompt"]
        assert "query_hotel_options" not in captured[2]["system_prompt"]


@pytest.mark.asyncio
async def test_step_middleware_blocks_duplicate_hotel_query_after_tool_call():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": ["query_hotel_options"],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {},
        "selected_destination": "长沙",
        "selected_transport": "train",
    }
    messages = [
        HumanMessage(content="信息已经齐了，请直接查真实酒店，要江景房。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_hotel_options",
                    "args": {},
                    "id": "tool-call-1",
                }
            ],
        ),
        ToolMessage(
            content="工具结果",
            name="query_hotel_options",
            tool_call_id="tool-call-1",
        ),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tool_choice"] is None
    assert "本轮已经执行过 `query_hotel_options`" in captured["system_prompt"]
    assert "query_hotel_options" not in captured["tools"]


@pytest.mark.asyncio
async def test_accommodation_stage_does_not_query_hotel_immediately_after_transport_selection():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "query_hotel_options",
                    "select_accommodation_tool",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {},
        "selected_destination": "眉县",
        "selected_transport": "train",
    }
    messages = [
        HumanMessage(content="交通按省心和时间合理优先，请直接记录你推荐的方式。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_transport_tool",
                    "args": {"transport_type": "train"},
                    "id": "tool-call-transport-select",
                }
            ],
        ),
        ToolMessage(
            content="交通方式已确认：高铁",
            name="select_transport_tool",
            tool_call_id="tool-call-transport-select",
        ),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tool_choice"] is None
    assert captured["tools"] == []
    assert "本轮刚刚完成交通方案记录" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_step_middleware_removes_repeated_state_transition_tool():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "food_planning": {
                "prompt": "餐饮阶段",
                "tools": ["select_accommodation_tool", "select_food_tool"],
                "requires": [],
            }
        }
    )
    state = {"current_step": "food_planning"}
    messages = [
        HumanMessage(content="餐饮按本地特色和轻松节奏安排，请直接记录推荐方向。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_accommodation_tool",
                    "args": {},
                    "id": "tool-call-1",
                }
            ],
        ),
        ToolMessage(
            content="住宿已记录",
            name="select_accommodation_tool",
            tool_call_id="tool-call-1",
        ),
    ]

    async def handler(request):
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "select_accommodation_tool" not in captured["tools"]
    assert "select_food_tool" in captured["tools"]
    assert "`select_accommodation_tool`" in captured["system_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_step", "message", "tools", "expected_tool"),
    [
        (
            "accommodation_planning",
            "住宿按省心、干净、动线方便的方案记录；真实酒店价格待核验。",
            ["query_hotel_options", "select_accommodation_tool"],
            "query_hotel_options",
        ),
        (
            "food_planning",
            "餐饮按本地特色和轻松节奏安排，请直接记录推荐方向。",
            ["select_food_tool"],
            "select_food_tool",
        ),
        (
            "itinerary_generation",
            "请生成并记录最终行程，天数必须和需求一致。",
            ["generate_itinerary_tool"],
            "generate_itinerary_tool",
        ),
        (
            "budget_summarization",
            "请汇总预算，包含交通、住宿、餐饮、景点体验和其他机动费用。",
            ["summarize_budget_tool"],
            "summarize_budget_tool",
        ),
    ],
)
async def test_stage_record_confirmation_forces_state_tool(
    current_step,
    message,
    tools,
    expected_tool,
):
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            current_step: {
                "prompt": "阶段提示",
                "tools": tools,
                "requires": [],
            }
        }
    )
    state = {
        "current_step": current_step,
        "user_requirement": {
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
        },
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, [HumanMessage(content=message)]), handler)

    assert captured["tools"] == [expected_tool]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == expected_tool
    else:
        assert captured["tool_choice"] is None
        assert expected_tool in captured["system_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_step", "message", "extra_state", "expected_tool"),
    [
        (
            "requirement_collection",
            "请生成并记录3天2晚结构化行程，动线要合理。",
            {},
            "generate_itinerary_tool",
        ),
        (
            "requirement_collection",
            "请汇总预算，包含交通、住宿、餐饮、景点体验和机动费用。",
            {"itinerary": [{"day_number": 1, "activities": ["夫子庙"]}]},
            "summarize_budget_tool",
        ),
        (
            "food_planning",
            "请直接生成最终旅行规划报告和 report_data。",
            {
                "user_requirement": {
                    "destination": "南京",
                    "departure_city": "北京",
                    "departure_date": "2026-06-01",
                    "departure_date_confirmed": True,
                    "travel_days": 3,
                    "adult_count": 2,
                    "children_count": 0,
                    "budget_min": 1500,
                },
                "itinerary": [
                    {"day_number": 1, "activities": ["夫子庙"]},
                    {"day_number": 2, "activities": ["南京博物院"]},
                    {"day_number": 3, "activities": ["玄武湖"]},
                ],
                "budget": {"total": 5000},
            },
            "generate_order_tool",
        ),
    ],
)
async def test_explicit_progress_request_forces_state_tool_after_step_regression(
    current_step,
    message,
    extra_state,
    expected_tool,
):
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求阶段",
                "tools": ["record_requirement_tool"],
                "requires": [],
            },
            "food_planning": {
                "prompt": "餐饮阶段",
                "tools": ["select_food_tool"],
                "requires": [],
            },
            "itinerary_generation": {
                "prompt": "行程阶段",
                "tools": ["generate_itinerary_tool"],
                "requires": [],
            },
            "budget_summarization": {
                "prompt": "预算阶段",
                "tools": ["summarize_budget_tool"],
                "requires": [],
            },
            "order_generation": {
                "prompt": "报告阶段",
                "tools": ["generate_order_tool"],
                "requires": [],
            },
        }
    )
    state = {
        "current_step": current_step,
        "user_requirement": {
            "destination": "南京",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 1500,
        },
        "selected_destination": "南京",
        "selected_transport": "train",
        "selected_accommodation_types": ["star_hotel"],
    }
    state.update(extra_state)

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    assert captured["tools"] == [expected_tool]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == expected_tool
    else:
        assert captured["tool_choice"] is None
        assert expected_tool in captured["system_prompt"]


@pytest.mark.asyncio
async def test_step_middleware_forces_direct_transport_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_date": "2026-05-16",
            "departure_date_confirmed": True,
        },
        "selected_destination": "上海",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="我想坐高铁，请直接查真实方案。")],
        ),
        handler,
    )

    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_transport_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_transport_options" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_stage_missing_date_does_not_open_live_query():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
        },
        "selected_destination": "上海",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="我想坐飞机，请直接查真实航班。")],
        ),
        handler,
    )

    assert captured["tool_choice"] is None
    assert "query_transport_options" not in captured["tools"]
    assert "暂缓真实交通查询" in captured["system_prompt"]
    assert "不要自己生成类似“5月22日”" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_fallback_missing_date_keeps_auditable_guarded_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {
            "departure_city": "武汉",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "special_needs": "优先高铁，如果查不到合适车次也请明确待核验并给出可执行交通兜底。",
        },
        "selected_destination": "张家界",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "交通按省心和时间合理优先，请直接记录你推荐的方式；"
                        "实时班次和价格标注待核验。"
                    )
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_transport_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_transport_options" in captured["system_prompt"]
    assert "保留一次交通查询工具调用作为治理证据" in captured["system_prompt"]
    assert "让工具守卫返回 skipped 审计结果" in captured["system_prompt"]
    assert "不要编造 YYYY-MM-DD 日期" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_step_middleware_does_not_force_transport_query_on_selection_turn():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {},
        "selected_destination": "上海",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="就选第一个最省心的航班，帮我记录为交通方案。")],
        ),
        handler,
    )

    assert captured["tool_choice"] is None
    assert "query_transport_options" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_stage_without_selection_forces_single_transport_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {"departure_date": "2026-05-16"},
        "selected_destination": "眉县",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="交通想坐高铁，帮我看真实方案。")]),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_transport_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_transport_options" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_query_result_waits_for_user_confirmation_before_selection():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {"departure_date": "2026-05-16"},
        "selected_destination": "眉县",
    }
    messages = [
        HumanMessage(content="交通想坐高铁，帮我看真实方案。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_transport_options",
                    "args": {"transport_type": "train"},
                    "id": "tool-call-transport-query",
                }
            ],
        ),
        ToolMessage(
            content="G123 西安北到眉县东，二等座待核验。",
            name="query_transport_options",
            tool_call_id="tool-call-transport-query",
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "query_transport_options" not in captured["tools"]
    assert "select_transport_tool" not in captured["tools"]
    assert "本轮已经完成真实交通查询" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_query_result_can_record_when_user_confirmed_same_turn():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {"departure_date": "2026-05-16"},
        "selected_destination": "眉县",
    }
    messages = [
        HumanMessage(content="交通按省心和时间合理优先，请直接记录你推荐的方式。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_transport_options",
                    "args": {"transport_type": "train"},
                    "id": "tool-call-transport-query",
                }
            ],
        ),
        ToolMessage(
            content="G123 西安北到眉县东，二等座待核验。",
            name="query_transport_options",
            tool_call_id="tool-call-transport-query",
        ),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tools"] == ["select_transport_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "select_transport_tool"
    else:
        assert captured["tool_choice"] is None
        assert "select_transport_tool" in captured["system_prompt"]
    assert "不要再次调用 `query_transport_options`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_stage_records_fallback_before_accommodation_request():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": [
                    "query_transport_options",
                    "select_transport_tool",
                    "query_hotel_options",
                ],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {"departure_city": "出发地待确认"},
        "selected_destination": "北京",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="住宿按省心、干净、动线方便的方案记录；如果没有真实锁价，请标注待核验。")],
        ),
        handler,
    )

    assert captured["tools"] == ["select_transport_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "select_transport_tool"
    else:
        assert captured["tool_choice"] is None
        assert "select_transport_tool" in captured["system_prompt"]
    assert "当前还没有记录交通方案" in captured["system_prompt"]
    assert "不要跨阶段查询或记录住宿" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_transport_stage_does_not_treat_destination_confirmation_as_transport_selection():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {"departure_city": "出发地待确认"},
        "selected_destination": "北京",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="目的地就按你推荐的最合适方案确认。")],
        ),
        handler,
    )

    assert captured["tool_choice"] is None
    assert "select_transport_tool" in captured["tools"]
    assert "交通方案尚未记录" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_filters_date_tools_without_relative_date():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集",
                "tools": ["record_requirement_tool", "getTodayDate"],
                "requires": [],
            }
        }
    )

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {"current_step": "requirement_collection"},
            [HumanMessage(content="我想去长沙，住湘江边江景房，4天3晚。")],
        ),
        handler,
    )

    assert captured["tools"] == ["record_requirement_tool"]
    assert "【当前日期】" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_uses_injected_date_for_relative_date():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集",
                "tools": ["record_requirement_tool", "getTodayDate"],
                "requires": [],
            }
        }
    )

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {"current_step": "requirement_collection"},
            [HumanMessage(content="我想下周末去长沙，住湘江边江景房。")],
        ),
        handler,
    )

    assert captured["tools"] == ["record_requirement_tool"]
    assert "直接基于这个日期换算" in captured["system_prompt"]
    assert "不要调用日期工具" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_prioritizes_record_when_user_already_provided_core_info():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": ["record_requirement_tool"],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}
    message = (
        "我们一家三口想从上海去北京玩3天，2个大人1个8岁孩子，"
        "总预算1.5万，2026年5月10日出发，偏向亲子游+环球影城，"
        "请先帮我把需求记录完整并开始推荐。"
    )

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "record_requirement_tool"
    else:
        assert captured["tool_choice"] is None
        assert "record_requirement_tool" in captured["system_prompt"]
        assert "不要为了补充非关键偏好而继续追问" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_records_confirmed_minimum_plannable_need():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": ["record_requirement_tool", "query_destination_info"],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}
    messages = [
        HumanMessage(content="我第一次去南京，3天2晚，自由行，想要文化加美食，不想太赶。"),
        AIMessage(content="我先按南京低压力文化美食路线理解。"),
        HumanMessage(content="以上需求确认无误，请先记录需求，然后继续推进规划。"),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "record_requirement_tool"
    else:
        assert captured["tool_choice"] is None
        assert "record_requirement_tool" in captured["system_prompt"]
        assert "出发地待确认" in captured["system_prompt"]
        assert "待核验" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_narrows_forced_record_tool_to_single_tool():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "query_destination_info",
                    "search_travel_info",
                ],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}
    messages = [
        HumanMessage(
            content=(
                "我想周末从西安出发去附近轻松玩两天，2个人，预算1500，"
                "想看自然风景和吃点当地小吃。"
            )
        ),
        AIMessage(content="我先按西安周边轻松自然风景两天理解。"),
        HumanMessage(content="以上需求确认无误，请先记录需求，然后继续推进规划。"),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, messages),
        handler,
    )

    assert captured["tools"] == ["record_requirement_tool"]
    assert "record_requirement_tool" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_treats_trip_preferences_as_temporary_memory():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "update_travel_style_tool",
                    "update_food_preference_tool",
                    "add_travel_record_tool",
                ],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content="这次周末想轻松一点，少走路，吃点当地小吃，不要记成长期偏好。"
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["record_requirement_tool"]
    assert "不要调用长期记忆工具" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_keeps_explicit_stable_memory_tools():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "update_travel_style_tool",
                    "update_food_preference_tool",
                    "add_travel_record_tool",
                ],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请记住我以后每次旅行都喜欢慢节奏和当地小吃。")],
        ),
        handler,
    )

    assert "update_travel_style_tool" in captured["tools"]
    assert "update_food_preference_tool" in captured["tools"]


@pytest.mark.asyncio
async def test_requirement_collection_defers_first_turn_hotel_fallback_tools():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "set_planning_mode_tool",
                    "query_destination_info",
                    "search_agency_risk_playbook",
                ],
                "requires": [],
            },
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": ["query_hotel_options"],
                "requires": [],
            },
        }
    )
    state = {"current_step": "requirement_collection"}
    message = "我想去长沙，住湘江边江景房，4天3晚，如果查不到具体酒店也请给我可执行的兜底方案。"

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    assert captured["tool_choice"] is None
    assert captured["tools"] == []
    assert state["pending_initial_request_text"] == message
    assert "首轮轻量响应" in captured["system_prompt"]
    assert "需求确认后核验真实交通、酒店" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_defers_first_turn_transport_and_weather_tools():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "set_planning_mode_tool",
                    "query_destination_info",
                    "search_agency_risk_playbook",
                ],
                "requires": [],
            },
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options"],
                "requires": [],
            },
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": ["query_hotel_options"],
                "requires": [],
            },
        }
    )
    state = {"current_step": "requirement_collection"}
    message = "我计划7月带父母去桂林4天3晚，担心下雨和老人走不动，请给省心安排并把天气、交通、酒店和Plan B风险写清楚。"

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    assert captured["tools"] == []
    assert state["pending_initial_request_text"] == message
    assert state["pending_initial_planning_mode"] == "agency_plan"
    assert "不调用任何工具" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_destination_weather_followup_forces_destination_info_before_selection():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地推荐阶段",
                "tools": [
                    "select_destination_tool",
                    "query_destination_info",
                    "search_agency_risk_playbook",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "destination": "桂林",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请先查询桂林7月天气和雨季情况，给老人友好的室内备选。")],
        ),
        handler,
    )

    assert captured["tools"] == ["query_destination_info"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_destination_info"
    else:
        assert captured["tool_choice"] is None
        assert "query_destination_info" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_defers_first_turn_full_agency_plan_tools():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "query_destination_info",
                    "search_agency_product_templates",
                ],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}
    message = "我们两个人想从西安出发，2026年5月23日去长沙4天3晚，总预算7000，希望省心一点，帮我按旅行社方案安排。"

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    assert "search_agency_product_templates" in captured["tools"]
    assert "pending_initial_request_text" not in state
    assert state.get("pending_initial_planning_mode") is None
    assert "成熟路线样板" in captured["system_prompt"]
    assert "不要暴露内部知识库、RAG 或工具名" in captured["system_prompt"]
    if compatibility.supports_forced_tool_choice:
        assert captured.get("tool_choice") == "search_agency_product_templates"
    else:
        assert captured.get("tool_choice") is None


@pytest.mark.asyncio
async def test_requirement_collection_soft_product_candidate_for_destination_match():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "query_destination_info",
                    "search_agency_product_templates",
                ],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="我想去新疆，先看看有没有成熟一点的路线。")]),
        handler,
    )

    assert "search_agency_product_templates" in captured["tools"]
    assert "目的地级命中也可以给一个候选方向" in captured["system_prompt"]
    assert "同时保留自由规划选项" in captured["system_prompt"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "search_agency_product_templates"
    else:
        assert captured["tool_choice"] is None


@pytest.mark.asyncio
async def test_agency_plan_query_uses_product_templates_before_plan_card():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地阶段",
                "tools": [
                    "query_destination_info",
                    "search_agency_product_templates",
                    "search_agency_service_sop",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_level": "comfort",
        },
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="我想要省心方案，请先按旅行社产品路线给几个方向。")],
        ),
        handler,
    )

    assert "search_agency_product_templates" in captured["tools"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "search_agency_product_templates"
    else:
        assert captured["tool_choice"] is None
        assert "search_agency_product_templates" in captured["system_prompt"]
    assert "给 2-3 个方向" in captured["system_prompt"]
    assert "出发城市或出发日期" in captured["system_prompt"]
    assert "不要直接生成最终报告或 report_data" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_user_rejecting_agency_product_switches_to_free_planning_tools():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地阶段",
                "tools": [
                    "query_destination_info",
                    "search_agency_product_templates",
                    "search_agency_service_sop",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_level": "comfort",
            "planning_mode": "agency_plan",
        },
    }

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="不需要旅行社产品，我想自由行，酒店和交通我自己订。")],
        ),
        handler,
    )

    assert "query_destination_info" in captured["tools"]
    assert "search_agency_product_templates" not in captured["tools"]
    assert "search_agency_service_sop" not in captured["tools"]
    assert "当前规划模式：自由规划" in captured["system_prompt"]
    assert "不要主动推旅行社产品" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_order_generation_final_report_request_forces_report_tool():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "order_generation": {
                "prompt": "订单阶段",
                "tools": ["generate_order_tool", "go_back_to_budget"],
                "requires": [],
            }
        }
    )
    state = {
        "current_step": "order_generation",
        "user_requirement": {
            "destination": "重庆",
            "departure_city": "西安",
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 4,
            "children_count": 0,
            "budget_min": 1500,
        },
        "selected_destination": "重庆",
        "selected_transport": "train",
        "selected_accommodation_types": ["star_hotel"],
        "budget": {"total": 8000},
        "itinerary": [
            {"day_number": 1, "activities": ["解放碑"]},
            {"day_number": 2, "activities": ["洪崖洞"]},
            {"day_number": 3, "activities": ["磁器口"]},
        ],
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请直接生成最终旅行规划报告和report_data。")],
        ),
        handler,
    )

    assert captured["tools"] == ["generate_order_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "generate_order_tool"
    else:
        assert captured["tool_choice"] is None
        assert "只能调用 `generate_order_tool`" in captured["system_prompt"]
        assert "generate_order_tool" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_order_generation_final_report_blocks_pending_date_until_confirmed():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "order_generation": {
                "prompt": "订单阶段",
                "tools": ["generate_order_tool", "go_back_to_budget"],
                "requires": [],
            }
        }
    )
    state = {
        "current_step": "order_generation",
        "user_requirement": {
            "destination": "南京",
            "departure_city": "北京",
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 1500,
        },
        "selected_destination": "南京",
        "selected_transport": "train",
        "selected_accommodation_types": ["star_hotel"],
        "budget": {"total": 5000},
        "itinerary": [
            {"day_number": 1, "activities": ["夫子庙"]},
            {"day_number": 2, "activities": ["南京博物院"]},
            {"day_number": 3, "activities": ["玄武湖"]},
        ],
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请直接生成最终旅行规划报告和report_data。")],
        ),
        handler,
    )

    assert "generate_order_tool" not in captured["tools"]
    assert captured["tool_choice"] != "generate_order_tool"
    assert "出发城市、出发日期" in captured["system_prompt"]
    assert "不要调用 `generate_order_tool`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_budget_stage_combined_budget_and_report_request_forces_budget_first():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "budget_summarization": {
                "prompt": "预算阶段",
                "tools": ["summarize_budget_tool", "generate_order_tool"],
                "requires": [],
            }
        }
    )
    state = {
        "current_step": "budget_summarization",
        "user_requirement": {
            "destination": "桂林",
            "departure_date": "2026-07-10",
            "departure_date_confirmed": True,
            "travel_days": 4,
            "adult_count": 1,
            "children_count": 0,
            "budget_min": 2500,
        },
        "selected_destination": "桂林",
        "selected_transport": "train",
        "selected_accommodation_types": ["star_hotel"],
        "itinerary": [{"day_number": 1, "activities": ["两江四湖"]}],
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "请汇总预算并直接生成最终旅行规划报告和report_data，"
                        "保留天气风险、Plan B、预算置信度和待核验项。"
                    )
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["summarize_budget_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "summarize_budget_tool"
    else:
        assert captured["tool_choice"] is None
        assert "summarize_budget_tool" in captured["system_prompt"]
    assert "generate_order_tool" not in captured["tools"]


@pytest.mark.asyncio
async def test_order_generation_does_not_generate_report_before_key_confirmations():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "order_generation": {
                "prompt": "订单阶段",
                "tools": ["generate_order_tool", "go_back_to_budget"],
                "requires": [],
            }
        }
    )
    state = {
        "current_step": "order_generation",
        "user_requirement": {
            "destination": "重庆",
            "departure_date": "2026-06-01",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 4,
            "children_count": 0,
            "budget_min": 1500,
        },
        "selected_destination": "重庆",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请直接生成最终旅行规划报告和report_data。")],
        ),
        handler,
    )

    assert captured["tool_choice"] is None
    assert "generate_order_tool" not in captured["tools"]
    assert "不要调用 `generate_order_tool`" in captured["system_prompt"]
    assert "不要手写最终报告卡片" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_requirement_collection_can_answer_destination_info_before_full_intake():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": ["record_requirement_tool", "query_destination_info"],
                "requires": [],
            }
        }
    )
    state = {"current_step": "requirement_collection"}
    message = "推荐眉县适合周末放松的景点和玩法，顺便说下天气。"

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_destination_info"
    else:
        assert captured["tool_choice"] is None
        assert "query_destination_info" in captured["system_prompt"]
        assert "完整旅游报告" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_destination_candidates_wait_for_user_confirmation_after_tool_result():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地推荐阶段",
                "tools": [
                    "select_destination_tool",
                    "query_destination_info",
                    "search_travel_info",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {
            "departure_city": "西安",
            "travel_days": 2,
            "total_people": 2,
        },
        "destination_options": [{"name": "太白山", "reason": "轻户外"}],
    }
    messages = [
        HumanMessage(content="推荐西安周边周末两天轻松自然风景。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_destination_info",
                    "args": {"destination": "太白山"},
                    "id": "tool-call-1",
                }
            ],
        ),
        ToolMessage(
            content="太白山适合轻户外，天气待核验。",
            name="query_destination_info",
            tool_call_id="tool-call-1",
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "query_destination_info" not in captured["tools"]
    assert "select_destination_tool" not in captured["tools"]
    assert "search_travel_info" not in captured["tools"]
    assert "等待用户确认目的地" in captured["system_prompt"]
    assert "不要调用 `select_destination_tool`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_destination_search_tool_is_one_shot_within_turn():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地推荐阶段",
                "tools": [
                    "select_destination_tool",
                    "query_destination_info",
                    "search_travel_info",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {"departure_city": "西安", "travel_days": 2},
    }
    messages = [
        HumanMessage(content="推荐西安周边周末两天轻松自然风景。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_travel_info",
                    "args": {"query": "西安周边周末自然风景"},
                    "id": "tool-call-search",
                }
            ],
        ),
        ToolMessage(
            content="太白山、关山草原、华山是候选。",
            name="search_travel_info",
            tool_call_id="tool-call-search",
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "search_travel_info" not in captured["tools"]
    assert "本轮已经完成这些一次性工具调用" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_destination_recommendation_prioritizes_selection_when_user_confirms():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地推荐阶段",
                "tools": ["select_destination_tool", "query_destination_info"],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {"destination": "北京"},
        "destination_options": [{"name": "北京"}],
    }
    message = "确认就去北京，按故宫+环球影城的方向走，请直接开始查交通方案。"

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "select_destination_tool"
    else:
        assert captured["tool_choice"] is None
        assert "select_destination_tool" in captured["system_prompt"]
        assert "不要继续停留在目的地比较阶段" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_destination_confirmation_can_infer_destination_from_prior_route_text():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "destination_recommendation": {
                "prompt": "目的地推荐阶段",
                "tools": ["select_destination_tool", "query_destination_info"],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "destination_recommendation",
        "user_requirement": {"departure_city": "上海"},
        "messages": [
            HumanMessage(content="亲子游，2大1小，从上海去杭州3天2晚，希望少走路。"),
        ],
    }
    message = "目的地就按你推荐的最合适方案确认；如果我已经给了目的地，就确认该目的地。"

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "select_destination_tool"
    else:
        assert captured["tool_choice"] is None
        assert "目的地为 `杭州`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_accommodation_candidates_force_selection_without_requery_or_memory_write():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_city": "西安",
            "travel_days": 2,
            "total_people": 2,
        },
        "selected_destination": "太白山",
        "selected_transport": "train",
        "accommodation_options": [
            {
                "hotel_id": "h1",
                "name": "太白山脚轻松酒店",
                "location": "游客中心附近",
            }
        ],
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="住宿按省心、干净、动线方便的方案记录。")],
        ),
        handler,
    )

    assert captured["tools"] == ["select_accommodation_tool"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "select_accommodation_tool"
    else:
        assert captured["tool_choice"] is None
        assert "select_accommodation_tool" in captured["system_prompt"]
    assert "query_hotel_options" not in captured["tools"]
    assert "update_accommodation_preference_tool" not in captured["tools"]
    assert "当前已经有酒店候选或住宿查询结果" in captured["system_prompt"]
    assert "不要再次调用 `query_hotel_options`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_temporary_accommodation_preferences_do_not_write_long_term_memory():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {},
        "selected_destination": "太白山",
        "selected_transport": "train",
    }

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="这次住宿按省心、干净、动线方便来，不要记成长期偏好。")],
        ),
        handler,
    )

    assert "update_accommodation_preference_tool" not in captured["tools"]
    assert "本轮住宿偏好属于当前行程条件" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_accommodation_stage_without_candidates_forces_hotel_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_date": "2026-05-16",
            "departure_date_confirmed": True,
            "travel_days": 2,
        },
        "selected_destination": "眉县",
        "selected_transport": "train",
    }
    messages = [
        HumanMessage(content="交通就按高铁，住宿干净省心、动线方便就行。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_transport_tool",
                    "args": {"transport_type": "train"},
                    "id": "tool-call-transport",
                }
            ],
        ),
        ToolMessage(
            content="已记录高铁方案。",
            name="select_transport_tool",
            tool_call_id="tool-call-transport",
        ),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tools"] == ["query_hotel_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_hotel_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_hotel_options" in captured["system_prompt"]
    assert "update_accommodation_preference_tool" not in captured["tools"]


@pytest.mark.asyncio
async def test_accommodation_record_request_with_price_verification_queries_first():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 2,
        },
        "selected_destination": "眉县",
        "selected_transport": "train",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="住宿按省心、干净、动线方便的方案记录；真实价格标注待核验。")],
        ),
        handler,
    )

    assert captured["tools"] == ["query_hotel_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_hotel_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_hotel_options" in captured["system_prompt"]
    assert "select_accommodation_tool" not in captured["tools"]
    assert "update_accommodation_preference_tool" not in captured["tools"]


@pytest.mark.asyncio
async def test_accommodation_stage_missing_date_does_not_open_live_hotel_query():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 2,
        },
        "selected_destination": "眉县",
        "selected_transport": "train",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="住宿想要干净省心，请直接查真实酒店。")],
        ),
        handler,
    )

    assert captured["tool_choice"] is None
    assert "query_hotel_options" not in captured["tools"]
    assert "暂缓真实酒店查询" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_hotel_fallback_missing_date_keeps_auditable_guarded_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "select_accommodation_tool",
                    "query_hotel_options",
                    "update_accommodation_preference_tool",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {
            "departure_date": "日期待确认",
            "departure_date_confirmed": False,
            "travel_days": 4,
            "special_needs": "住湘江边江景房，如果查不到具体酒店也给可执行兜底方案。",
        },
        "selected_destination": "长沙",
        "selected_transport": "train",
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [
                HumanMessage(
                    content=(
                        "住宿按省心、干净、动线方便的方案记录；"
                        "如果没有真实锁价，请标注待核验。"
                    )
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["query_hotel_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_hotel_options"
    else:
        assert captured["tool_choice"] is None
        assert "query_hotel_options" in captured["system_prompt"]
    assert "保留一次酒店查询工具调用作为治理证据" in captured["system_prompt"]
    assert "让工具守卫返回 skipped 审计结果" in captured["system_prompt"]
    assert "update_accommodation_preference_tool" not in captured["tools"]
