import os
import json
from types import SimpleNamespace

import pytest

os.environ.setdefault("DASHSCOPE_API_KEY", "test-dashscope-key")
os.environ.setdefault("LANGSMITH_API_KEY", "test-langsmith-key")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")

from app.api.v1 import chat
from app.api.v1.chat import (
    extract_fast_split_facts,
    _report_content_from_tool_output,
    _report_extra_info_from_tool_output,
    _strip_assistant_thinking_content,
)
from app.core.approval import ApprovalGovernanceManager
from app.core.observability import TurnObservation, get_turn_observability_snapshot
from app.core.session_lock import reset_session_locks_for_tests
from app.tools.audit import build_tool_audit_event, start_tool_audit


def test_report_extra_info_from_command_output():
    report_data = {
        "version": "travel_report.v1",
        "overview": {"route_label": "北京 -> 上海"},
        "agency_context": {"mode": "free_planning"},
        "route_map": {"days": [{"day_number": 1, "points": [{"name": "外滩"}]}]},
        "traveler": {"email": "test@example.com"},
    }
    output = SimpleNamespace(
        update={
            "order_id": "ORDER-1234",
            "report_data": report_data,
        }
    )

    extra_info = _report_extra_info_from_tool_output(output)

    assert extra_info["message_type"] == "travel_report"
    assert extra_info["order_id"] == "ORDER-1234"
    assert extra_info["report_data"]["version"] == "travel_report.v1"
    assert extra_info["report_data"]["agency_context"]["mode"] == "free_planning"
    assert extra_info["report_data"]["route_map"]["days"][0]["day_number"] == 1
    assert extra_info["report_data"]["traveler"]["email"] == "[REDACTED]"


def test_report_extra_info_ignores_non_report_tool_output():
    assert _report_extra_info_from_tool_output(SimpleNamespace(update={})) == {}
    assert _report_extra_info_from_tool_output({"content": "plain text"}) == {}


def test_report_content_from_command_output_prefers_report_field():
    output = SimpleNamespace(update={"report": "# 完整报告 test@example.com", "messages": []})

    assert _report_content_from_tool_output(output) == "# 完整报告 [REDACTED]"


def test_sse_redacts_sensitive_payload_values():
    frame = chat.sse(
        {
            "type": "token",
            "content": "联系 test@example.com，手机号 13800138000",
            "nested": {"api_key": "sk-testvalue123456789"},
        }
    )
    payload = json.loads(frame.removeprefix("data: ").strip())
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "test@example.com" not in serialized
    assert "13800138000" not in serialized
    assert "sk-testvalue123456789" not in serialized
    assert payload["nested"]["api_key"] == "[REDACTED]"


def test_report_content_from_command_output_falls_back_to_tool_message():
    output = SimpleNamespace(
        update={
            "messages": [
                SimpleNamespace(content=""),
                SimpleNamespace(content="工具消息报告"),
            ],
        }
    )

    assert _report_content_from_tool_output(output) == "工具消息报告"


def test_fast_split_directional_route_uses_destination_not_first_place():
    facts = extract_fast_split_facts("我想从西安去南京，两个人，预算1万左右，下周一出发，你帮我规划一下")

    assert facts["departure_city"] == "西安"
    assert facts["destination"] == "南京"
    assert facts["departure_date"]
    assert facts["adult_count"] == 2
    assert "口径待确认" in facts["budget_text"]


def test_fast_split_state_seed_carries_facts_into_agency_mode():
    facts = extract_fast_split_facts("我想从西安去南京玩5天，两个人，预算1万左右，下周一出发，你帮我规划一下")

    seed = chat._fast_split_state_seed(facts, planning_mode="agency_plan")

    assert seed["planning_mode"] == "agency_plan"
    assert seed["active_workflow"] == "agency_plan"
    assert seed["user_requirement"]["departure_city"] == "西安"
    assert seed["user_requirement"]["destination"] == "南京"
    assert seed["confirmed_facts"]["destination"] == "南京"
    assert seed["progress_snapshot"]["confirmed_facts"]
    assert seed["agency_step"] == "agency_product_match"
    assert seed["progress_snapshot"]["agency_step"] == "agency_product_match"


def test_empty_tool_update_does_not_overwrite_fast_split_progress():
    facts = extract_fast_split_facts("西安到杭州玩5天，两个人，预算每人5000，下周一出发")
    seed = chat._fast_split_state_seed(facts, planning_mode="agency_plan")
    observation = TurnObservation(
        conversation_id="conversation-progress",
        user_id="user-1",
        user_message="省心方案",
    )
    observation.update_context(
        current_step=seed["current_step"],
        planning_mode=seed["planning_mode"],
        planning_mode_source="fast_split_seed",
    )
    observation.set_progress_snapshot(seed["progress_snapshot"])

    chat._update_observation_from_state_update(
        observation,
        {"messages": [SimpleNamespace(content="工具返回文本，但没有状态更新")]},
    )

    assert observation.planning_mode == "agency_plan"
    assert observation.progress_snapshot["planning_mode"] == "agency_plan"
    assert observation.progress_snapshot["agency_step"] == "agency_product_match"
    assert observation.progress_snapshot["confirmed_facts"]


def test_progress_snapshot_merge_preserves_confirmed_agency_state():
    previous = {
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "agency_step": "agency_plan_draft",
        "confirmed_facts": [
            {"key": "departure_city", "label": "出发地", "value": "西安"},
            {"key": "destination", "label": "目的地", "value": "杭州"},
        ],
        "long_term_preferences": ["历史文化", "少折腾"],
    }
    weak_tool_snapshot = {
        "planning_mode": "pending_confirmation",
        "active_workflow": "",
        "agency_step": "",
        "confirmed_facts": [],
        "long_term_preferences": [],
        "pending_items": ["出发日期"],
    }

    merged = chat._merge_progress_snapshot(previous, weak_tool_snapshot)

    assert merged["planning_mode"] == "agency_plan"
    assert merged["active_workflow"] == "agency_plan"
    assert merged["agency_step"] == "agency_plan_draft"
    confirmed = {
        item["key"]: item["value"]
        for item in merged["confirmed_facts"]
        if isinstance(item, dict)
    }
    assert confirmed == {"departure_city": "西安", "destination": "杭州"}
    assert merged["long_term_preferences"] == ["历史文化", "少折腾"]
    assert merged["pending_items"] == ["出发日期"]


@pytest.mark.asyncio
async def test_chat_stream_fast_mode_split_skips_full_agent(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append(
            {
                "role": role,
                "content": content,
                "extra_info": extra_info or {},
            }
        )
        return SimpleNamespace()

    async def fake_role_counts(db, conversation_id):
        return {"user": 1, "assistant": 0}

    async def fake_create_travel_agent():
        raise AssertionError("fast mode split should not create the full travel agent")

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-fast-split",
        "我想去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["token", "turn_observability", "done"]
    assert "杭州" in events[0]["content"]
    assert "您想要现成省心方案，还是个性化旅游规划" in events[0]["content"]
    assert saved_messages[0]["role"] == "user"
    assert saved_messages[1]["role"] == "assistant"
    assert saved_messages[1]["extra_info"]["fast_mode_split"]["needs_confirmation"] is True
    assert saved_messages[1]["extra_info"]["fast_mode_split"]["facts"]["destination"] == "杭州"
    assert saved_messages[1]["extra_info"]["observability"]["metrics"]["progress_snapshot"][
        "confirmed_facts"
    ]
    assert events[1]["observability"]["planning_mode"] == "pending_confirmation"
    assert events[1]["observability"]["progress_snapshot"]["confirmed_facts"]


@pytest.mark.asyncio
async def test_chat_stream_fast_agency_confirmation_sets_mode_without_agent(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []
    initial_facts = extract_fast_split_facts(
        "我想从西安去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下"
    )

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append(
            {
                "role": role,
                "content": content,
                "extra_info": extra_info or {},
            }
        )
        return SimpleNamespace()

    async def fake_role_counts(db, conversation_id):
        return {"user": 2, "assistant": 1}

    async def fake_load_fast_facts(db, *, conversation_id):
        return dict(initial_facts)

    async def fake_create_travel_agent():
        raise AssertionError("agency confirmation fast path should not create the full agent")

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)
    monkeypatch.setattr(chat, "_load_latest_fast_split_facts_for_turn", fake_load_fast_facts)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-agency-confirm",
        "省心方案",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["token", "turn_observability", "done"]
    assert "已切到省心方案" in events[0]["content"]
    assert "计划哪天出发" in events[0]["content"]
    assert events[1]["observability"]["planning_mode"] == "agency_plan"
    assert events[1]["observability"]["step"] == "agency_requirement"
    assert events[1]["observability"]["progress_snapshot"]["planning_mode"] == "agency_plan"
    assert saved_messages[-1]["extra_info"]["fast_mode_split"]["needs_confirmation"] is False
    assert saved_messages[-1]["extra_info"]["fast_mode_split"]["facts"]["planning_mode"] == "agency_plan"
    assert saved_messages[-1]["extra_info"]["fast_mode_split"]["facts"]["destination"] == "杭州"


@pytest.mark.asyncio
async def test_chat_stream_fast_agency_date_update_sets_progress_without_agent(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []
    initial_facts = extract_fast_split_facts(
        "我想从西安去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下"
    )
    initial_facts.update({"planning_mode": "agency_plan", "active_workflow": "agency_plan"})

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append(
            {
                "role": role,
                "content": content,
                "extra_info": extra_info or {},
            }
        )
        return SimpleNamespace()

    async def fake_role_counts(db, conversation_id):
        return {"user": 3, "assistant": 2}

    async def fake_load_fast_facts(db, *, conversation_id):
        return dict(initial_facts)

    async def fake_create_travel_agent():
        raise AssertionError("agency date fast path should not create the full agent")

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)
    monkeypatch.setattr(chat, "_load_latest_fast_split_facts_for_turn", fake_load_fast_facts)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-agency-date",
        "计划下周一",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["token", "turn_observability", "done"]
    assert "出发时间按" in events[0]["content"]
    assert events[1]["observability"]["planning_mode"] == "agency_plan"
    progress = events[1]["observability"]["progress_snapshot"]
    assert progress["agency_step"] == "agency_requirement"
    confirmed = {
        item["key"]: item["value"]
        for item in progress["confirmed_facts"]
        if isinstance(item, dict)
    }
    assert confirmed["departure_date"]
    assert saved_messages[-1]["extra_info"]["fast_mode_split"]["facts"]["departure_date"]


def test_strip_assistant_thinking_content_removes_complete_and_unclosed_blocks():
    text = (
        "公开建议。"
        "<think>内部推理 query_transport_options 不应展示</think>"
        "继续说明。<think>未闭合内部推理"
    )

    stripped = _strip_assistant_thinking_content(text)

    assert stripped == "公开建议。继续说明。"
    assert "<think" not in stripped
    assert "query_transport_options" not in stripped


@pytest.mark.asyncio
async def test_tool_audit_persistence_failure_records_degradation():
    class FailingDb:
        def __init__(self) -> None:
            self.rolled_back = False

        def add(self, _model):
            raise RuntimeError("database down")

        async def rollback(self):
            self.rolled_back = True

    event = build_tool_audit_event(
        start_tool_audit("query_transport_options"),
        status="success",
        input_summary={"origin_city": "北京"},
        output_summary={"option_count": 1},
        evidence_type="live_transport_query",
    )
    db = FailingDb()

    result = await chat._persist_tool_audit_events_safely(
        db,
        events=[event],
        user_id="user-1",
        conversation_id="conversation-1",
    )
    snapshot = ApprovalGovernanceManager.get_status_snapshot()

    assert result["status"] == "degraded"
    assert result["persistent"] is False
    assert result["error_type"] == "RuntimeError"
    assert "PostgreSQL" in result["message"]
    assert db.rolled_back is True
    assert snapshot["status"] == "not_ready"
    assert snapshot["hitl_closed_loop"] is False
    ApprovalGovernanceManager.configure_uninitialized(app_env="development")


@pytest.mark.asyncio
async def test_chat_stream_stops_after_structured_report_event(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []
    report_data = {
        "version": "travel_report.v1",
        "overview": {"route_label": "上海 -> 杭州"},
    }

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append(
            {
                "role": role,
                "content": content,
                "extra_info": extra_info or {},
            }
        )
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            yield {
                "event": "on_tool_start",
                "name": "generate_order_tool",
                "run_id": "run-1",
                "data": {"input": {}},
            }
            yield {
                "event": "on_tool_end",
                "name": "generate_order_tool",
                "run_id": "run-1",
                "data": {
                    "output": SimpleNamespace(
                        update={
                            "order_id": "ORDER-1234",
                            "report": "# 完整报告",
                            "report_data": report_data,
                        }
                    )
                },
            }
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": SimpleNamespace(content="不应继续生成")},
            }

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-1",
        "生成最终报告",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == [
        "tool_call",
        "report_data",
        "tool_audit",
        "turn_observability",
        "done",
    ]
    assert events[1]["report_data"] == report_data
    assert events[2]["status"] == "success"
    assert "input_summary" not in events[2]
    assert "output_summary" not in events[2]
    assert events[3]["observability"]["tool_call_count"] == 1
    assert saved_messages[-1]["role"] == "assistant"
    assert saved_messages[-1]["content"] == "# 完整报告"
    assert saved_messages[-1]["extra_info"]["report_data"] == report_data
    assert saved_messages[-1]["extra_info"]["observability"]["turn_id"] == events[-1]["turn_id"]
    assert get_turn_observability_snapshot(events[-1]["turn_id"]) is not None


@pytest.mark.asyncio
async def test_chat_stream_suppresses_duplicate_tool_call_events(monkeypatch):
    await reset_session_locks_for_tests()

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            for index in (1, 2):
                yield {
                    "event": "on_tool_start",
                    "name": "search_travel_info",
                    "run_id": f"run-{index}",
                    "data": {"input": {"query": "杭州最新开放"}},
                }
                yield {
                    "event": "on_tool_end",
                    "name": "search_travel_info",
                    "run_id": f"run-{index}",
                    "data": {"output": "ok"},
                }

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-dup-tool",
        "查一下杭州最新开放",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    tool_call_events = [event for event in events if event["type"] == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0]["tool"] == "search_travel_info"
    assert tool_call_events[0]["turn_id"]
    assert [event["type"] for event in events].count("tool_audit") == 2
    observability = next(event["observability"] for event in events if event["type"] == "turn_observability")
    assert observability["tool_call_count"] == 2


@pytest.mark.asyncio
async def test_chat_stream_filters_thinking_blocks_across_token_chunks(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append({"role": role, "content": content, "extra_info": extra_info or {}})
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            for chunk in [
                "公开开头<thi",
                "nk>内部推理 query_transport_options",
                "</thi",
                "nk>继续给用户看的内容。",
            ]:
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": SimpleNamespace(content=chunk)},
                }

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-thinking-filter",
        "查一下航班",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    token_contents = [event["content"] for event in events if event["type"] == "token"]
    serialized = json.dumps(events, ensure_ascii=False)
    saved_assistant = [item for item in saved_messages if item["role"] == "assistant"][-1]

    assert token_contents == ["公开开头", "继续给用户看的内容。"]
    assert saved_assistant["content"] == "公开开头继续给用户看的内容。"
    assert "<think" not in serialized
    assert "query_transport_options" not in serialized
    assert "内部推理" not in saved_assistant["content"]


@pytest.mark.asyncio
async def test_chat_stream_finishes_transient_disconnect_after_partial_content(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append({"role": role, "content": content, "extra_info": extra_info or {}})
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": SimpleNamespace(content="已生成部分回答")},
            }
            raise RuntimeError(
                "peer closed connection without sending complete message body "
                "(incomplete chunked read)"
            )

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-2",
        "继续规划",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["token", "turn_observability", "done"]
    assert events[0]["content"] == "已生成部分回答"
    assert events[1]["observability"]["fallback_count"] == 1
    assert saved_messages[-1]["content"] == "已生成部分回答"
    assert saved_messages[-1]["extra_info"]["observability"]["metrics"]["degradation_status"] == "degraded"


@pytest.mark.asyncio
async def test_chat_stream_uses_fallback_token_for_empty_transient_disconnect(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append({"role": role, "content": content, "extra_info": extra_info or {}})
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            if False:
                yield {}
            raise RuntimeError("incomplete chunked read")

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-3",
        "继续规划",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["token", "turn_observability", "done"]
    assert "模型流式连接中断" in events[0]["content"]
    assert events[1]["observability"]["fallback_count"] == 1
    assert saved_messages[-1]["content"] == events[0]["content"]


@pytest.mark.asyncio
async def test_chat_stream_sanitizes_user_visible_error(monkeypatch):
    await reset_session_locks_for_tests()

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            if False:
                yield {}
            raise RuntimeError("upstream leaked secret-token")

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-error",
        "继续规划",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert [event["type"] for event in events] == ["turn_observability", "error"]
    assert events[0]["observability"]["degradation_status"] == "failed"
    assert "secret-token" not in json.dumps(events, ensure_ascii=False)
