from types import SimpleNamespace

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from app.core.state import TravelState, create_initial_state
from app.tools import transport_query
from app.tools.execution_guard import _LOOP_GUARD_MEMORY
from app.tools.rag_tools import _guarded_rag_retrieval
from app.tools.state_transition import (
    select_accommodation_tool,
    select_food_tool,
    select_transport_tool,
)


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-loop-guard",
        store=None,
    )


def test_parallel_tool_loop_guard_updates_are_merged():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["turn_id"] = "turn-parallel-loop"

    def first_tool(_state):
        return {
            "tool_loop_guard": {
                "turn_id": "turn-parallel-loop",
                "calls": [
                    {
                        "key": "query_destination_info:single",
                        "tool": "query_destination_info",
                        "status": "success",
                    }
                ],
            },
            "tool_audit_events": [
                {
                    "name": "query_destination_info",
                    "started_at": 1.0,
                    "status": "success",
                    "error_type": None,
                }
            ],
        }

    def second_tool(_state):
        return {
            "tool_loop_guard": {
                "turn_id": "turn-parallel-loop",
                "calls": [
                    {
                        "key": "search_destination_guide:{\"query\": \"西安\"}",
                        "tool": "search_destination_guide",
                        "status": "success",
                    }
                ],
            },
            "tool_audit_events": [
                {
                    "name": "search_destination_guide",
                    "started_at": 2.0,
                    "status": "success",
                    "error_type": None,
                }
            ],
        }

    graph = StateGraph(TravelState)
    graph.add_node("first_tool", first_tool)
    graph.add_node("second_tool", second_tool)
    graph.add_edge(START, "first_tool")
    graph.add_edge(START, "second_tool")
    graph.add_edge("first_tool", END)
    graph.add_edge("second_tool", END)

    result = graph.compile().invoke(state)

    assert result["tool_loop_guard"]["turn_id"] == "turn-parallel-loop"
    assert {
        call["key"]
        for call in result["tool_loop_guard"]["calls"]
    } == {
        "query_destination_info:single",
        'search_destination_guide:{"query": "西安"}',
    }
    assert [
        event["name"] for event in result["tool_audit_events"]
    ] == ["query_destination_info", "search_destination_guide"]


class FakeCoordinator:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload, config=None):
        self.calls.append(payload)
        return {"messages": [SimpleNamespace(content="交通查询结果")]}


@pytest.mark.asyncio
async def test_transport_query_duplicate_same_turn_is_skipped(monkeypatch):
    _LOOP_GUARD_MEMORY.clear()
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["turn_id"] = "turn-transport-loop"
    coordinator = FakeCoordinator()

    async def fake_create_transport_coordinator():
        return coordinator

    monkeypatch.setattr(
        transport_query,
        "create_transport_coordinator",
        fake_create_transport_coordinator,
    )

    args = {
        "origin_city": "西安",
        "destination_city": "长沙",
        "departure_date": "2026-05-23",
        "transport_type": "train",
        "runtime": _build_runtime(state),
    }
    first = await transport_query.query_transport_options.ainvoke(args)
    second = await transport_query.query_transport_options.ainvoke(args)

    assert len(coordinator.calls) == 1
    assert first.update["tool_audit_events"][0]["status"] == "success"
    duplicate_event = second.update["tool_audit_events"][0]
    assert duplicate_event["status"] == "skipped"
    assert duplicate_event["error_type"] == "duplicate_tool_call_same_turn"
    assert "本轮已经执行过交通真实查询" in second.update["messages"][0].content


@pytest.mark.asyncio
async def test_rag_duplicate_same_turn_uses_recoverable_message():
    _LOOP_GUARD_MEMORY.clear()
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["turn_id"] = "turn-rag-loop"
    calls = []

    async def fake_retrieve():
        calls.append("called")
        return "长沙低压力行程证据"

    runtime = _build_runtime(state)
    first = await _guarded_rag_retrieval(
        tool_name="search_agency_risk_playbook",
        query="长沙 银发 低压力 风险",
        label="旅行社内部知识库",
        visibility="internal",
        expected_category="risk",
        retrieve_call=fake_retrieve,
        runtime=runtime,
    )
    second = await _guarded_rag_retrieval(
        tool_name="search_agency_risk_playbook",
        query="长沙 银发 低压力 风险",
        label="旅行社内部知识库",
        visibility="internal",
        expected_category="risk",
        retrieve_call=fake_retrieve,
        runtime=runtime,
    )

    assert first == "长沙低压力行程证据"
    assert calls == ["called"]
    assert "本轮已经执行过等价 RAG 检索" in second


def test_state_transition_duplicate_accommodation_does_not_rewind_step():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "food_planning",
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "hotel_id": 1001,
                "name": "长沙低压力酒店",
                "type": "star_hotel",
                "location": "五一广场",
                "price_per_night": 680.0,
                "rating": 4.7,
                "amenities": ["近地铁"],
            },
            "accommodation_options": [
                {
                    "hotel_id": 1001,
                    "name": "长沙低压力酒店",
                    "type": "star_hotel",
                    "location": "五一广场",
                    "price_per_night": 680.0,
                    "rating": 4.7,
                    "amenities": ["近地铁"],
                }
            ],
        }
    )

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["星级酒店"],
            "hotel_id": 1001,
            "runtime": _build_runtime(state),
        }
    )

    assert "不会重复写入同一住宿选择" in command.update["messages"][0].content
    assert "current_step" not in command.update
    assert "selected_accommodation_types" not in command.update


def test_select_accommodation_infers_type_from_existing_candidate():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "accommodation_planning",
            "accommodation_options": [
                {
                    "hotel_id": 1001,
                    "name": "长沙低压力酒店",
                    "type": "star_hotel",
                    "location": "五一广场",
                    "price_per_night": 680.0,
                    "rating": 4.7,
                    "amenities": ["近地铁"],
                }
            ],
        }
    )

    command = select_accommodation_tool.invoke(
        {
            "hotel_id": 1001,
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "food_planning"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    assert command.update["selected_accommodation_option"]["hotel_id"] == 1001


def test_select_accommodation_defaults_to_first_candidate_without_args():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "accommodation_planning",
            "accommodation_options": [
                {
                    "hotel_id": 1002,
                    "name": "北京舒适酒店",
                    "type": "舒适型酒店",
                    "location": "东城区",
                    "price_per_night": 520.0,
                    "rating": 4.6,
                    "amenities": ["安静"],
                }
            ],
        }
    )

    command = select_accommodation_tool.invoke({"runtime": _build_runtime(state)})

    assert command.update["current_step"] == "food_planning"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    assert command.update["selected_accommodation_option"]["hotel_id"] == 1002


def test_select_accommodation_accepts_model_string_arguments():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update({"current_step": "accommodation_planning"})

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": "舒适型酒店",
            "hotel_id": "hotel-1003",
            "hotel_name": "汉中舒适酒店",
            "price_per_night": "约 320 元/晚",
            "rating": "4.6",
            "amenities": "近商圈、安静",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "food_planning"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    option = command.update["selected_accommodation_option"]
    assert option["hotel_id"] == "hotel-1003"
    assert option["price_per_night"] == 320.0
    assert option["rating"] == 4.6
    assert option["amenities"] == ["近商圈、安静"]


def test_select_accommodation_requires_hotel_audit_for_unlocked_price_request():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "accommodation_planning",
            "messages": [
                HumanMessage(
                    content="住宿按省心、干净、动线方便的方案记录；如果没有真实锁价，请标注待核验。"
                )
            ],
        }
    )

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["舒适型酒店"],
            "runtime": _build_runtime(state),
        }
    )

    assert "query_hotel_options" in command.update["messages"][0].content
    assert "current_step" not in command.update
    assert "selected_accommodation_types" not in command.update


def test_select_accommodation_allows_selection_after_hotel_audit_result():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "accommodation_planning",
            "messages": [
                HumanMessage(
                    content="住宿按省心、干净、动线方便的方案记录；如果没有真实锁价，请标注待核验。"
                ),
                ToolMessage(
                    content="日期待确认，已跳过真实酒店库存查询，需二次核验。",
                    name="query_hotel_options",
                    tool_call_id="call-hotel-query",
                ),
            ],
        }
    )

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["舒适型酒店"],
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "food_planning"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]


def test_select_transport_requires_transport_audit_for_fallback_request():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "transport_planning",
            "messages": [
                HumanMessage(
                    content="优先高铁；如果查不到合适车次，请明确待核验并给可执行交通兜底。"
                )
            ],
        }
    )

    command = select_transport_tool.invoke(
        {
            "transport_type": "高铁",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "transport_planning"
    assert "query_transport_options" in command.update["messages"][0].content
    assert "selected_transport" not in command.update


def test_select_transport_allows_selection_after_transport_audit_result():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "transport_planning",
            "messages": [
                HumanMessage(
                    content="优先高铁；如果查不到合适车次，请明确待核验并给可执行交通兜底。"
                ),
                ToolMessage(
                    content="日期待确认，已跳过真实交通班次查询，需二次核验。",
                    name="query_transport_options",
                    tool_call_id="call-transport-query",
                ),
            ],
        }
    )

    command = select_transport_tool.invoke(
        {
            "transport_type": "高铁",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "accommodation_planning"
    assert command.update["selected_transport"] == "train"


def test_select_food_tool_keeps_flow_at_accommodation_when_accommodation_missing():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "food_planning",
            "messages": [
                HumanMessage(
                    content="住宿按江景房兜底方案记录；如果没有真实锁价，请标注待核验。"
                )
            ],
        }
    )

    command = select_food_tool.invoke(
        {
            "food_types": ["本地小吃"],
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "accommodation_planning"
    assert "query_hotel_options" in command.update["messages"][0].content
    assert "selected_food_types" not in command.update


def test_state_transition_duplicate_food_does_not_rewrite_state():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "itinerary_generation",
            "selected_food_types": ["local", "chain"],
        }
    )

    command = select_food_tool.invoke(
        {
            "food_types": ["本地小吃", "连锁快餐"],
            "runtime": _build_runtime(state),
        }
    )

    assert "不会重复写入同一餐饮选择" in command.update["messages"][0].content
    assert "current_step" not in command.update
    assert "selected_food_types" not in command.update
