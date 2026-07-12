from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.handoffs.step_config import get_step_config
from app.core.middleware import StepConfigMiddleware
from app.core.workflow import AGENCY_STEPS, PLANNING_STEPS
from app.utils.llm_factory import ModelCompatibility, get_model_compatibility
from app.utils.message_utils import (
    STATE_TRANSITION_OUTCOME_SCHEMA,
    tool_names_from_message,
)


class DummyRequest:
    def __init__(self, state, messages=None):
        self.state = state
        self.messages = messages or []

    def override(self, **kwargs):
        merged = {**self.__dict__, **kwargs}
        return SimpleNamespace(**merged)


def _force_supported_tool_choice(monkeypatch):
    compatibility = ModelCompatibility(supports_forced_tool_choice=True)
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: compatibility,
    )
    return compatibility


def _tool_names(tools):
    return {getattr(tool, "name", getattr(tool, "__name__", str(tool))) for tool in tools}


def _transition_artifact(tool, status="applied", **extra):
    return {
        "schema": STATE_TRANSITION_OUTCOME_SCHEMA,
        "tool": tool,
        "status": status,
        **extra,
    }


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
        captured["model_settings"] = request.model_settings
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state), handler)

    assert "目的地：北京" in captured["system_prompt"]
    assert "出发地：上海" in captured["system_prompt"]
    assert "日期：2026-05-29" in captured["system_prompt"]
    assert "人数：2+1" in captured["system_prompt"]
    assert captured["tools"] == ["tool-a"]
    assert captured["model_settings"]["parallel_tool_calls"] is False


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
            artifact=_transition_artifact(
                "select_transport_tool",
                next_step="accommodation_planning",
            ),
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
            artifact=_transition_artifact(
                "select_accommodation_tool",
                next_step="food_planning",
            ),
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
    monkeypatch,
):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
    if current_step == "budget_summarization":
        state["itinerary"] = [{"day_number": 1, "activities": ["已生成行程"]}]

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
    monkeypatch,
):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
        captured["tools"] = getattr(request, "tools", [])
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
async def test_transport_selection_stops_same_turn_transport_query_fanout():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": [
                    "query_transport_options",
                    "select_transport_tool",
                    "go_back_to_destination",
                ],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "user_requirement": {"departure_date": "2026-07-18"},
        "selected_destination": "汉中",
    }
    messages = [
        HumanMessage(content="请直接记录推荐交通方式为高铁，本轮不查询实时班次。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_transport_tool",
                    "args": {"transport_type": "train"},
                    "id": "transport-selected",
                }
            ],
        ),
        ToolMessage(
            content="交通方向已记录。",
            tool_call_id="transport-selected",
            artifact=_transition_artifact(
                "select_transport_tool",
                next_step="accommodation_planning",
            ),
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "query_transport_options" not in captured["tools"]
    assert "select_transport_tool" not in captured["tools"]
    assert captured["tools"] == ["go_back_to_destination"]


@pytest.mark.asyncio
async def test_accommodation_selection_stops_same_turn_hotel_query_fanout():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "accommodation_planning": {
                "prompt": "住宿阶段",
                "tools": [
                    "query_hotel_options",
                    "select_accommodation_tool",
                    "go_back_to_requirement",
                ],
                "requires": ["user_requirement", "selected_destination", "selected_transport"],
            }
        }
    )
    state = {
        "current_step": "accommodation_planning",
        "user_requirement": {"departure_date": "2026-07-18"},
        "selected_destination": "汉中",
        "selected_transport": "train",
    }
    messages = [
        HumanMessage(content="请直接记录城区干净安静的住宿，真实房态待核验。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_accommodation_tool",
                    "args": {"accommodation_types": ["star_hotel"]},
                    "id": "accommodation-selected",
                }
            ],
        ),
        ToolMessage(
            content="住宿方向已记录。",
            tool_call_id="accommodation-selected",
            artifact=_transition_artifact(
                "select_accommodation_tool",
                next_step="food_planning",
            ),
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert "query_hotel_options" not in captured["tools"]
    assert "select_accommodation_tool" not in captured["tools"]
    assert captured["tools"] == ["go_back_to_requirement"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "query_tool", "selection_tool", "message", "reason"),
    [
        (
            "transport_planning",
            "query_transport_options",
            "select_transport_tool",
            "交通记录暂缓，请先查询真实交通并保留审计结果。",
            "audit_required",
        ),
        (
            "accommodation_planning",
            "query_hotel_options",
            "select_accommodation_tool",
            "住宿记录暂缓，请先查询酒店并保留审计结果。",
            "audit_required",
        ),
    ],
)
async def test_selection_audit_required_preserves_and_forces_recovery_query(
    step,
    query_tool,
    selection_tool,
    message,
    reason,
):
    captured = {}
    compatibility = get_model_compatibility()
    state = {
        "current_step": step,
        "user_requirement": {"departure_date": "2026-07-18"},
        "selected_destination": "汉中",
        "selected_transport": "train" if step == "accommodation_planning" else None,
    }
    middleware = StepConfigMiddleware(
        {
            step: {
                "prompt": "当前阶段",
                "tools": [query_tool, selection_tool, "go_back_to_requirement"],
                "requires": [],
            }
        }
    )
    call_id = f"{selection_tool}-audit"
    messages = [
        HumanMessage(content="请直接记录推荐方向；如果缺少证据先补审计查询。"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": selection_tool, "args": {}, "id": call_id}
            ],
        ),
        ToolMessage(
            content=message,
            tool_call_id=call_id,
            artifact=_transition_artifact(
                selection_tool,
                status="not_applied",
                reason=reason,
                next_step=step,
            ),
        ),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tools"] == [query_tool]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == query_tool
    else:
        assert captured["tool_choice"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "query_tool", "selection_tool", "human_text", "query_result"),
    [
        (
            "transport_planning",
            "query_transport_options",
            "select_transport_tool",
            "交通请直接记录推荐方式；若需先审计就查询。",
            "交通查询审计已完成。",
        ),
        (
            "accommodation_planning",
            "query_hotel_options",
            "select_accommodation_tool",
            "住宿请直接记录推荐偏好；若需先审计就查询酒店。",
            "酒店查询审计已完成。",
        ),
    ],
)
async def test_audit_query_allows_retrying_not_applied_selection(
    step,
    query_tool,
    selection_tool,
    human_text,
    query_result,
):
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            step: {
                "prompt": "当前阶段",
                "tools": [query_tool, selection_tool],
                "requires": [],
            }
        }
    )
    selection_call_id = f"{selection_tool}-first"
    query_call_id = f"{query_tool}-recovery"
    messages = [
        HumanMessage(content=human_text),
        AIMessage(
            content="",
            tool_calls=[
                {"name": selection_tool, "args": {}, "id": selection_call_id}
            ],
        ),
        ToolMessage(
            content="状态暂未写入，请先完成查询审计。",
            tool_call_id=selection_call_id,
            artifact=_transition_artifact(
                selection_tool,
                status="not_applied",
                reason="audit_required",
                next_step=step,
            ),
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"name": query_tool, "args": {}, "id": query_call_id}
            ],
        ),
        ToolMessage(
            content=query_result,
            name=query_tool,
            tool_call_id=query_call_id,
        ),
    ]
    state = {
        "current_step": step,
        "user_requirement": {"departure_date": "2026-07-18"},
        "selected_destination": "汉中",
        "selected_transport": "train" if step == "accommodation_planning" else None,
    }

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tools"] == [selection_tool]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == selection_tool
    else:
        assert captured["tool_choice"] is None


@pytest.mark.asyncio
async def test_invalid_selection_result_is_not_treated_as_completed():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": [
                    "query_transport_options",
                    "select_transport_tool",
                    "go_back_to_destination",
                ],
                "requires": [],
            }
        }
    )
    messages = [
        HumanMessage(content="请直接记录交通选择。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_transport_tool",
                    "args": {"transport_type": "invalid"},
                    "id": "invalid-transport",
                }
            ],
        ),
        ToolMessage(
            content="交通方式无效，未写入。",
            tool_call_id="invalid-transport",
            artifact=_transition_artifact(
                "select_transport_tool",
                status="not_applied",
                reason="invalid_input",
                next_step="transport_planning",
            ),
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {
                "current_step": "transport_planning",
                "user_requirement": {"departure_date": "2026-07-18"},
                "selected_destination": "汉中",
            },
            messages,
        ),
        handler,
    )

    assert set(captured["tools"]) == {
        "query_transport_options",
        "select_transport_tool",
        "go_back_to_destination",
    }
    assert "本轮交通选择尚未写入" in captured["system_prompt"]
    assert "本轮已经完成这些一次性工具调用" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_selection_tool_call_without_result_is_not_treated_as_applied():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": [],
            }
        }
    )
    messages = [
        HumanMessage(content="继续处理当前阶段。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_transport_tool",
                    "args": {"transport_type": "train"},
                    "id": "unfinished-selection",
                }
            ],
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {
                "current_step": "transport_planning",
                "user_requirement": {"departure_date": "2026-07-18"},
                "selected_destination": "汉中",
            },
            messages,
        ),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    assert "本轮已经完成这些一次性工具调用" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_error_tool_message_cannot_claim_applied_transition():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": [],
            }
        }
    )
    messages = [
        HumanMessage(content="继续处理当前阶段。"),
        ToolMessage(
            content="工具执行失败",
            tool_call_id="failed-selection",
            status="error",
            artifact=_transition_artifact(
                "select_transport_tool",
                next_step="accommodation_planning",
            ),
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {
                "current_step": "transport_planning",
                "user_requirement": {"departure_date": "2026-07-18"},
                "selected_destination": "汉中",
            },
            messages,
        ),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    assert "本轮已经完成这些一次性工具调用" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_successful_selection_from_previous_user_turn_does_not_block_new_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": [],
            }
        }
    )
    messages = [
        HumanMessage(content="上一轮请记录高铁。"),
        ToolMessage(
            content="交通方式已确认：高铁",
            tool_call_id="old-selection",
            artifact=_transition_artifact(
                "select_transport_tool",
                next_step="accommodation_planning",
            ),
        ),
        AIMessage(content="交通已记录。"),
        HumanMessage(content="现在请直接查2026年7月18日的真实高铁方案。"),
    ]

    async def handler(request):
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["tools"] = getattr(request, "tools", [])
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {
                "current_step": "transport_planning",
                "user_requirement": {"departure_date": "2026-07-18"},
                "selected_destination": "汉中",
            },
            messages,
        ),
        handler,
    )

    assert captured["tools"] == ["query_transport_options"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_transport_options"
    else:
        assert captured["tool_choice"] is None


def test_tool_names_support_role_tool_dict_and_transition_artifact():
    assert tool_names_from_message(
        {"role": "tool", "name": "query_transport_options", "content": "ok"}
    ) == {"query_transport_options"}
    assert tool_names_from_message(
        {
            "role": "tool",
            "content": "交通已记录",
            "artifact": _transition_artifact("select_transport_tool"),
        }
    ) == {"select_transport_tool"}
    assert not tool_names_from_message(
        {
            "role": "assistant",
            "content": "不能伪造工具完成证据",
            "artifact": _transition_artifact("select_transport_tool"),
        }
    )


@pytest.mark.asyncio
async def test_agency_workflow_uses_agency_step_and_blocks_free_stage_tools():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "自由交通阶段",
                "tools": ["query_transport_options", "select_transport_tool"],
                "requires": ["user_requirement", "selected_destination"],
            },
            "agency_product_match": {
                "prompt": "省心方案匹配阶段",
                "tools": [
                    "record_requirement_tool",
                    "search_agency_product_templates",
                    "query_transport_options",
                    "select_transport_tool",
                ],
                "requires": ["user_requirement"],
            },
        }
    )
    state = {
        "current_step": "transport_planning",
        "agency_step": "agency_product_match",
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "departure_city": "西安",
            "destination": "拉萨",
            "departure_date": "2026-05-25",
            "departure_date_confirmed": True,
            "travel_days": 7,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 5000,
        },
        "selected_destination": "拉萨",
    }

    async def handler(request):
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        captured["tools"] = getattr(request, "tools", [])
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="继续给我现成方案")]),
        handler,
    )

    assert "省心方案匹配阶段" in captured["system_prompt"]
    assert "自由交通阶段" not in captured["system_prompt"]
    assert set(captured["tools"]) == {
        "record_requirement_tool",
        "search_agency_product_templates",
    }
    assert "query_transport_options" not in captured["tools"]
    assert "select_transport_tool" not in captured["tools"]
    assert state["agency_step"] == "agency_product_match"
    assert state["context_last_step"] == "agency_product_match"


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
        captured["tools"] = getattr(request, "tools", [])
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
async def test_destination_selection_stops_before_transport_tools_in_same_turn():
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
        "user_requirement": {"departure_city": "武汉", "departure_date": "2026-11-12"},
        "selected_destination": "张家界",
    }
    messages = [
        HumanMessage(content="目的地确认张家界，请记录目的地方案并继续下一阶段。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "select_destination_tool",
                    "args": {"destination": "张家界"},
                    "id": "tool-call-destination-select",
                }
            ],
        ),
        ToolMessage(
            content="目的地已确认：张家界",
            name="select_destination_tool",
            tool_call_id="tool-call-destination-select",
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
    assert "本轮已经完成目的地确认" in captured["system_prompt"]
    assert "不要在同一用户轮次继续查询或记录交通" in captured["system_prompt"]


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
async def test_requirement_collection_confirms_mode_before_recording_complete_core_info():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "requirement_collection": {
                "prompt": "需求收集阶段",
                "tools": [
                    "record_requirement_tool",
                    "set_planning_mode_tool",
                    "confirm_planning_mode_tool",
                ],
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
        captured["tools"] = getattr(request, "tools", [])
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content=message)]),
        handler,
    )

    assert captured["tools"] == []
    assert "您想要现成省心方案，还是个性化旅游规划" in captured["system_prompt"]
    assert "不要整理已知信息" in captured["system_prompt"]
    assert "先用一句自然" in captured["system_prompt"]


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
async def test_requirement_collection_records_confirmed_hotel_fallback_trip():
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
                "我想去长沙，住湘江边江景房，4天3晚，"
                "如果查不到具体酒店也请给我可执行的兜底方案。"
            )
        ),
        AIMessage(content="我先按长沙4天3晚江景住宿需求理解。"),
        HumanMessage(content="以上需求确认无误，请先记录需求，然后继续推进规划。"),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tools"] == ["record_requirement_tool"]
    assert "record_requirement_tool" in captured["system_prompt"]
    assert "出发地待确认" in captured["system_prompt"]


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
    assert "本轮只回答用户实际询问的目的地或天气范围" in captured["system_prompt"]
    assert "不得断言班次准点、余票、航班可订、酒店有房或实时价格" in captured["system_prompt"]
    assert "待二次核验" in captured["system_prompt"]
    if compatibility.supports_forced_tool_choice:
        assert captured["tool_choice"] == "query_destination_info"
    else:
        assert captured["tool_choice"] is None
        assert "query_destination_info" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_agency_weather_risk_followup_keeps_and_forces_destination_query():
    captured = {}
    compatibility = get_model_compatibility()
    middleware = StepConfigMiddleware(
        {
            "agency_product_match": {
                "prompt": "省心方案匹配阶段",
                "tools": [
                    "query_destination_info",
                    "search_agency_risk_playbook",
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
            [
                HumanMessage(
                    content=(
                        "请先查询桂林7月天气、雨季情况和老人友好玩法，"
                        "重点保留室内Plan B与天气风险。"
                    )
                )
            ],
        ),
        handler,
    )

    assert captured["tools"] == ["query_destination_info"]
    assert "本轮只回答用户实际询问的目的地或天气范围" in captured["system_prompt"]
    assert "不得断言班次准点、余票、航班可订、酒店有房或实时价格" in captured["system_prompt"]
    assert "待二次核验" in captured["system_prompt"]
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
async def test_confirmed_date_and_agency_workflow_are_not_reasked_in_later_steps():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "transport_planning": {
                "prompt": "交通阶段",
                "tools": ["query_transport_options", "search_agency_product_templates"],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "transport_planning",
        "active_workflow": "agency_plan",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "confirmed_facts": {
            "departure_city": "西安",
            "destination": "杭州",
            "departure_date": "2026-05-27",
            "travel_days": 5,
            "check_in_date": "2026-05-27",
            "check_out_date": "2026-05-31",
            "active_workflow": "agency_plan",
        },
        "matched_product": {"name": "西安出发杭州 5 天省心样板"},
        "user_requirement": {
            "departure_city": "西安",
            "destination": "杭州",
            "departure_date": "2026-05-27",
            "departure_date_confirmed": True,
            "travel_days": 5,
            "adult_count": 2,
            "children_count": 0,
            "budget_level": "comfort",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
        "selected_destination": "杭州",
    }

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="交通和住宿按这个省心方案继续，不用问我偏好。")]),
        handler,
    )

    assert "query_transport_options" not in captured["tools"]
    assert captured["tools"] == ["search_agency_product_templates"]
    assert "出发日期：2026-05-27" in captured["system_prompt"]
    assert "入住日期：2026-05-27" in captured["system_prompt"]
    assert "退房日期：2026-05-31" in captured["system_prompt"]
    assert "不得再次询问同一出发日期、入住日期或退房日期" in captured["system_prompt"]
    assert "active_workflow=agency_plan" in captured["system_prompt"]
    assert "不要漂回自由行逐项追问交通方式、酒店偏好" in captured["system_prompt"]
    assert "不要询问用户选择飞机/高铁或酒店偏好" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_order_generation_final_report_request_forces_report_tool(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
async def test_agency_report_final_request_serializes_state_writing_tools_within_one_turn(
    monkeypatch,
):
    captures = []
    compatibility = _force_supported_tool_choice(monkeypatch)
    middleware = StepConfigMiddleware(
        {
            "agency_report": {
                "prompt": "省心方案报告阶段",
                "tools": [
                    "generate_itinerary_tool",
                    "summarize_budget_tool",
                    "generate_order_tool",
                    "search_agency_report_standards",
                ],
                "requires": ["user_requirement"],
            }
        }
    )
    state = {
        "current_step": "requirement_collection",
        "active_workflow": "agency_plan",
        "agency_step": "agency_report",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "selected_destination": "桂林",
        "itinerary": [{"day_number": 1, "activities": ["象鼻山"]}],
        "user_requirement": {
            "departure_city": "西安",
            "destination": "桂林",
            "departure_date": "2026-08-10",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_text": "人均预算5000-7000元",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
    }
    messages = [HumanMessage(content="方案满意，请直接生成最终旅行规划报告和 report_data。")]

    async def invoke_middleware():
        captured = {}

        async def handler(request):
            captured["tool_choice"] = getattr(request, "tool_choice", None)
            captured["tools"] = getattr(request, "tools", [])
            captured["system_prompt"] = getattr(request, "system_prompt", "")
            return "ok"

        await middleware.awrap_model_call(DummyRequest(state, list(messages)), handler)
        captures.append(captured)

    await invoke_middleware()

    state["itinerary"] = [
        {"day_number": 1, "activities": ["象鼻山"]},
        {"day_number": 2, "activities": ["漓江"]},
        {"day_number": 3, "activities": ["龙脊梯田"]},
    ]
    messages.extend(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_itinerary_tool",
                        "args": {},
                        "id": "agency-itinerary",
                    }
                ],
            ),
            ToolMessage(
                content="结构化行程已生成",
                name="generate_itinerary_tool",
                tool_call_id="agency-itinerary",
            ),
        ]
    )
    await invoke_middleware()

    state["budget"] = {"total": 7600, "per_person": 3800}
    messages.extend(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "summarize_budget_tool",
                        "args": {},
                        "id": "agency-budget",
                    }
                ],
            ),
            ToolMessage(
                content="结构化预算已生成",
                name="summarize_budget_tool",
                tool_call_id="agency-budget",
            ),
        ]
    )
    await invoke_middleware()

    expected_tools = [
        "generate_itinerary_tool",
        "summarize_budget_tool",
        "generate_order_tool",
    ]
    assert [captured["tools"] for captured in captures] == [
        [tool_name] for tool_name in expected_tools
    ]
    for captured, tool_name in zip(captures, expected_tools, strict=True):
        if compatibility.supports_forced_tool_choice:
            assert captured["tool_choice"] == tool_name
        else:
            assert captured["tool_choice"] is None
        assert "行程生成 → 预算汇总 → 正式报告" in captured["system_prompt"]
        assert f"本轮只能调用 `{tool_name}`" in captured["system_prompt"]


def _agency_report_dispatch_state(*, itinerary=None, budget=None):
    return {
        "current_step": "requirement_collection",
        "active_workflow": "agency_plan",
        "agency_step": "agency_report",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "selected_destination": "南京",
        "itinerary": itinerary,
        "budget": budget,
        "user_requirement": {
            "departure_city": "北京",
            "destination": "南京",
            "departure_date": "2026-10-10",
            "departure_date_confirmed": True,
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_text": "总预算8000元",
            "planning_mode": "agency_plan",
            "planning_mode_confirmed": True,
        },
    }


def _agency_report_dispatch_middleware():
    return StepConfigMiddleware(
        {
            "agency_report": {
                "prompt": "省心方案报告阶段",
                "tools": [
                    "generate_itinerary_tool",
                    "summarize_budget_tool",
                    "generate_order_tool",
                ],
                "requires": ["user_requirement"],
            }
        }
    )


def _only_tool_call_name_and_id(response):
    assert len(response.result) == 1
    assert isinstance(response.result[0], AIMessage)
    assert response.result[0].content == ""
    assert response.result[0].response_metadata == {
        "synthetic_tool_dispatch": True,
        "dispatch_source": "state_machine",
    }
    assert len(response.result[0].tool_calls) == 1
    call = response.result[0].tool_calls[0]
    assert call["args"] == {}
    assert call["type"] == "tool_call"
    return call["name"], call["id"]


@pytest.mark.asyncio
async def test_unsupported_model_deterministically_dispatches_each_report_phase(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=False),
    )
    complete_itinerary = [
        {"day_number": 1, "activities": ["中山陵"]},
        {"day_number": 2, "activities": ["南京博物院"]},
        {"day_number": 3, "activities": ["玄武湖"]},
    ]
    states = [
        _agency_report_dispatch_state(),
        _agency_report_dispatch_state(itinerary=complete_itinerary),
        _agency_report_dispatch_state(
            itinerary=complete_itinerary,
            budget={"total": 7600},
        ),
    ]
    expected_tools = [
        "generate_itinerary_tool",
        "summarize_budget_tool",
        "generate_order_tool",
    ]
    handler_calls = 0
    call_ids = []

    async def handler(_request):
        nonlocal handler_calls
        handler_calls += 1
        return "unexpected"

    for state, expected_tool in zip(states, expected_tools, strict=True):
        response = await _agency_report_dispatch_middleware().awrap_model_call(
            DummyRequest(
                state,
                [HumanMessage(content="请生成最终旅行规划报告和 report_data。")],
            ),
            handler,
        )
        tool_name, call_id = _only_tool_call_name_and_id(response)
        assert tool_name == expected_tool
        assert state["observability_context"]["available_tool_count"] == 1
        call_ids.append(call_id)

    assert handler_calls == 0
    assert len(set(call_ids)) == len(expected_tools)


@pytest.mark.asyncio
async def test_unsupported_model_advances_report_pipeline_after_tool_results(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=False),
    )
    middleware = _agency_report_dispatch_middleware()
    state = _agency_report_dispatch_state()
    messages = [HumanMessage(content="请生成最终旅行规划报告和 report_data。")]
    handler_calls = 0

    async def handler(_request):
        nonlocal handler_calls
        handler_calls += 1
        return "handled"

    observed_tools = []
    observed_ids = []
    response = await middleware.awrap_model_call(DummyRequest(state, messages), handler)
    tool_name, call_id = _only_tool_call_name_and_id(response)
    observed_tools.append(tool_name)
    observed_ids.append(call_id)
    assert handler_calls == 0

    state["itinerary"] = [
        {"day_number": 1, "activities": ["中山陵"]},
        {"day_number": 2, "activities": ["南京博物院"]},
        {"day_number": 3, "activities": ["玄武湖"]},
    ]
    messages.extend(
        [
            response.result[0],
            ToolMessage(
                content="结构化行程已生成",
                name=tool_name,
                tool_call_id=call_id,
            ),
        ]
    )
    response = await middleware.awrap_model_call(DummyRequest(state, messages), handler)
    tool_name, call_id = _only_tool_call_name_and_id(response)
    observed_tools.append(tool_name)
    observed_ids.append(call_id)
    assert handler_calls == 0

    state["budget"] = {"total": 7600}
    messages.extend(
        [
            response.result[0],
            ToolMessage(
                content="结构化预算已生成",
                name=tool_name,
                tool_call_id=call_id,
            ),
        ]
    )
    response = await middleware.awrap_model_call(DummyRequest(state, messages), handler)
    tool_name, call_id = _only_tool_call_name_and_id(response)
    observed_tools.append(tool_name)
    observed_ids.append(call_id)
    assert handler_calls == 0

    assert observed_tools == [
        "generate_itinerary_tool",
        "summarize_budget_tool",
        "generate_order_tool",
    ]
    assert len(set(observed_ids)) == 3

    messages.extend(
        [
            response.result[0],
            ToolMessage(
                content="正式报告已生成",
                name=tool_name,
                tool_call_id=call_id,
            ),
        ]
    )
    result = await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert result == "handled"
    assert handler_calls == 1


@pytest.mark.asyncio
async def test_nonfinal_itinerary_request_stops_before_budget_in_same_turn():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "budget_summarization": {
                "prompt": "预算阶段",
                "tools": ["summarize_budget_tool", "generate_order_tool"],
                "requires": ["user_requirement", "itinerary"],
            }
        }
    )
    state = {
        "current_step": "budget_summarization",
        "user_requirement": {
            "departure_city": "上海",
            "destination": "南京",
            "departure_date": "2026-10-16",
        },
        "itinerary": [{"day_number": 1, "activities": ["南京博物院"]}],
    }
    messages = [
        HumanMessage(content="请生成并记录结构化行程。"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "generate_itinerary_tool",
                    "args": {},
                    "id": "tool-call-itinerary",
                }
            ],
        ),
        ToolMessage(
            content="结构化行程已生成",
            name="generate_itinerary_tool",
            tool_call_id="tool-call-itinerary",
        ),
    ]

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(DummyRequest(state, messages), handler)

    assert captured["tools"] == []
    assert captured["tool_choice"] is None
    assert "不要在同一用户轮次继续生成下一阶段" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_food_only_request_defers_itinerary_tools_to_next_turn():
    captured = {}
    middleware = StepConfigMiddleware(
        {
            "itinerary_generation": {
                "prompt": "行程阶段",
                "tools": [
                    "select_food_tool",
                    "generate_itinerary_tool",
                    "summarize_budget_tool",
                    "generate_order_tool",
                ],
                "requires": ["user_requirement", "selected_destination"],
            }
        }
    )
    state = {
        "current_step": "itinerary_generation",
        "user_requirement": {"departure_city": "上海", "departure_date": "2026-10-16"},
        "selected_destination": "南京",
    }

    async def handler(request):
        captured["tools"] = getattr(request, "tools", [])
        captured["system_prompt"] = getattr(request, "system_prompt", "")
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请仅记录餐饮方向并继续推进，下一轮再生成结构化行程。")],
        ),
        handler,
    )

    assert captured["tools"] == ["select_food_tool"]
    assert "下一轮" in captured["system_prompt"]
    assert "本轮不得调用 `generate_itinerary_tool`" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_supported_model_keeps_handler_and_forced_report_tool_choice(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=True),
    )
    state = _agency_report_dispatch_state(
        itinerary=[
            {"day_number": 1},
            {"day_number": 2},
            {"day_number": 3},
        ],
        budget={"total": 7600},
    )
    captured = {"calls": 0}

    async def handler(request):
        captured["calls"] += 1
        captured["tool_choice"] = request.tool_choice
        return "handled"

    result = await _agency_report_dispatch_middleware().awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="请生成最终旅行规划报告和 report_data。")],
        ),
        handler,
    )

    assert result == "handled"
    assert captured == {"calls": 1, "tool_choice": "generate_order_tool"}


@pytest.mark.asyncio
async def test_unsupported_model_keeps_non_report_tool_on_handler_path(monkeypatch):
    monkeypatch.setattr(
        "app.core.middleware.get_model_compatibility",
        lambda **_: ModelCompatibility(supports_forced_tool_choice=False),
    )
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
        "selected_destination": "南京",
        "user_requirement": {
            "departure_city": "北京",
            "destination": "南京",
            "departure_date": "2026-10-10",
            "departure_date_confirmed": True,
        },
    }
    captured = {"calls": 0}

    async def handler(request):
        captured["calls"] += 1
        captured["tool_choice"] = getattr(request, "tool_choice", None)
        captured["system_prompt"] = request.system_prompt
        return "handled"

    result = await middleware.awrap_model_call(
        DummyRequest(state, [HumanMessage(content="请直接查真实高铁方案。")]),
        handler,
    )

    assert result == "handled"
    assert captured["calls"] == 1
    assert captured["tool_choice"] is None
    assert "query_transport_options" in captured["system_prompt"]


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
async def test_budget_stage_combined_budget_and_report_request_forces_budget_first(monkeypatch):
    captured = {}
    compatibility = _force_supported_tool_choice(monkeypatch)
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
            artifact=_transition_artifact(
                "select_transport_tool",
                next_step="accommodation_planning",
            ),
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


@pytest.mark.asyncio
async def test_all_workflow_steps_define_prompt_and_tools():
    config = await get_step_config()

    assert set(config) == set(PLANNING_STEPS) | set(AGENCY_STEPS)
    for step in (*PLANNING_STEPS, *AGENCY_STEPS):
        assert config[step]["prompt"].strip(), f"{step} must define a prompt"
        assert config[step]["tools"], f"{step} must expose at least one tool"


@pytest.mark.asyncio
async def test_agency_prompts_do_not_follow_free_planning_confirmation_chain():
    config = await get_step_config()

    for step in AGENCY_STEPS:
        prompt = config[step]["prompt"]
        assert "省心方案" in prompt
        assert "不走自由规划的交通/住宿/餐饮逐项确认链路" in prompt
        assert "不要询问用户选择飞机/高铁或酒店偏好" in prompt


@pytest.mark.asyncio
async def test_agency_default_tools_keep_live_inventory_and_free_selection_closed():
    config = await get_step_config()
    blocked_tools = {
        "query_transport_options",
        "query_hotel_options",
        "select_transport_tool",
        "select_accommodation_tool",
    }
    required_boundary_terms = [
        "待核验",
        "不锁价",
        "不要调用实时交通查询",
        "不要输出 Markdown 表格作为主结构",
    ]

    for step in AGENCY_STEPS:
        prompt = config[step]["prompt"]
        assert blocked_tools.isdisjoint(_tool_names(config[step]["tools"]))

    assert "query_destination_info" in _tool_names(
        config["agency_product_match"]["tools"]
    )

    common_prompt = config["agency_plan_draft"]["prompt"]
    for term in required_boundary_terms:
        assert term in common_prompt


@pytest.mark.asyncio
async def test_final_report_prompts_do_not_commit_to_payment_booking_or_locked_price():
    config = await get_step_config()

    free_report_prompt = config["order_generation"]["prompt"]
    agency_report_prompt = config["agency_report"]["prompt"]

    assert "不要编造支付链接" in free_report_prompt
    assert "不要编造真实库存、票价、房态或支付链接" in free_report_prompt
    assert "估算性质和不锁价边界" in free_report_prompt
    assert "不锁价" in config["agency_product_match"]["prompt"]
    assert "必须先调用 summarize_budget_tool" in agency_report_prompt
    assert "再调用 generate_order_tool" in agency_report_prompt
    assert "不要跳过预算阶段直接手写最终报告" in agency_report_prompt


@pytest.mark.asyncio
async def test_agency_pricing_prompts_require_itinerary_before_budget_summary():
    config = await get_step_config()

    for step in ("agency_plan_draft", "agency_feedback"):
        prompt = config[step]["prompt"]
        assert "结构化 itinerary 尚未写入时" in prompt
        assert "不得调用 summarize_budget_tool" in prompt
        assert "不得声称已经生成结构化 budget" in prompt
        assert "只有结构化 itinerary 已写入后" in prompt
