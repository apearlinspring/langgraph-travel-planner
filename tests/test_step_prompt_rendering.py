from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.core.middleware import StepConfigMiddleware


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
async def test_step_middleware_forces_direct_hotel_query_only_on_user_turn():
    captured = []
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
        captured.append(getattr(request, "tool_choice", None))
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="信息已经齐了，请直接查真实酒店。")],
        ),
        handler,
    )
    state["messages"] = [HumanMessage(content="信息已经齐了，请直接查真实酒店。")]
    await middleware.awrap_model_call(
        DummyRequest(state),
        handler,
    )
    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [ToolMessage(content="工具结果", tool_call_id="1", name="query_hotel_options")],
        ),
        handler,
    )

    assert captured == ["query_hotel_options", "query_hotel_options", None]


@pytest.mark.asyncio
async def test_step_middleware_forces_direct_transport_query():
    captured = {}
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
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="我想坐高铁，请直接查真实方案。")],
        ),
        handler,
    )

    assert captured["tool_choice"] == "query_transport_options"


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
        return "ok"

    await middleware.awrap_model_call(
        DummyRequest(
            state,
            [HumanMessage(content="就选第一个最省心的航班，帮我记录为交通方案。")],
        ),
        handler,
    )

    assert captured["tool_choice"] is None
