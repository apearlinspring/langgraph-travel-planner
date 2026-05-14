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
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {"current_step": "requirement_collection"},
            [HumanMessage(content="我想去长沙，住湘江边江景房，4天3晚。")],
        ),
        handler,
    )

    assert captured["tools"] == ["record_requirement_tool"]


@pytest.mark.asyncio
async def test_requirement_collection_keeps_date_tools_for_relative_date():
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
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            {"current_step": "requirement_collection"},
            [HumanMessage(content="我想下周末去长沙，住湘江边江景房。")],
        ),
        handler,
    )

    assert "getTodayDate" in captured["tools"]


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
