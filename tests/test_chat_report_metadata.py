import os
import json
from datetime import date
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


def test_report_extra_info_from_top_level_dict_output():
    report_data = {
        "version": "travel_report.v1",
        "overview": {"route_label": "成都 -> 重庆"},
        "agency_context": {"mode": "agency_plan"},
    }
    output = {
        "order_id": "ORDER-5678",
        "report_data": report_data,
        "messages": [],
    }

    extra_info = _report_extra_info_from_tool_output(output)

    assert extra_info["message_type"] == "travel_report"
    assert extra_info["order_id"] == "ORDER-5678"
    assert extra_info["report_data"]["agency_context"]["mode"] == "agency_plan"


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


def test_transport_claim_filter_qualifies_claim_split_across_chunks():
    claim_filter = chat._AssistantTransportClaimFilter()

    assert claim_filter.feed("推荐高") == ""
    assert claim_filter.feed("铁有票。") == (
        "推荐高铁有票（动态班次与票务状态待二次核验，以官方实时结果为准）。"
    )
    assert claim_filter.finish() == ""


@pytest.mark.parametrize(
    "text",
    [
        "高铁余票待核验。",
        "航班已确认，但仍需二次核验。",
        "火车可订情况未确认。",
        "机票已出票，以官方实时结果为准。",
        "车次准点情况请复核。",
        "班次已确认，请出发前核验。",
    ],
)
def test_transport_claim_filter_preserves_qualified_claims(text):
    assert chat._qualify_unsupported_transport_claims(text) == text


def test_transport_claim_filter_handles_multiple_sentences_and_markdown_lines():
    text = "### 交通\n- 高铁有票；航班可订待确认。\n普通建议保持不变"

    assert chat._qualify_unsupported_transport_claims(text) == (
        "### 交通\n"
        "- 高铁有票（动态班次与票务状态待二次核验，以官方实时结果为准）；"
        "航班可订待确认。\n"
        "普通建议保持不变"
    )


def test_transport_claim_filter_qualifies_unpunctuated_text_on_finish():
    claim_filter = chat._AssistantTransportClaimFilter()

    assert claim_filter.feed("当前车次已确认") == ""
    assert claim_filter.finish() == (
        "当前车次已确认（动态班次与票务状态待二次核验，以官方实时结果为准）"
    )


def test_transport_claim_filter_preserves_safe_stream_text_and_layout():
    chunks = ["### 出行建议\n", "- 优先公共交通；", "换乘预留时间\n", "祝旅途愉快"]
    claim_filter = chat._AssistantTransportClaimFilter()

    streamed = "".join(claim_filter.feed(chunk) for chunk in chunks)
    streamed += claim_filter.finish()

    assert streamed == "".join(chunks)


def test_transport_claim_tool_boundary_flush_keeps_thinking_state():
    thinking_filter = chat._AssistantThinkingFilter()
    claim_filter = chat._AssistantTransportClaimFilter()

    claim_filter.feed(thinking_filter.feed("公开内容<think>内部"))
    before_tool = claim_filter.finish()
    after_tool = claim_filter.feed(
        thinking_filter.feed("推理内容</think>继续给用户。")
    )
    after_tool += claim_filter.feed(thinking_filter.finish()) + claim_filter.finish()

    assert before_tool + after_tool == "公开内容继续给用户。"


def test_fast_split_directional_route_uses_destination_not_first_place():
    facts = extract_fast_split_facts("我想从西安去南京，两个人，预算1万左右，下周一出发，你帮我规划一下")

    assert facts["departure_city"] == "西安"
    assert facts["destination"] == "南京"
    assert facts["departure_date"]
    assert facts["adult_count"] == 2
    assert "口径待确认" in facts["budget_text"]


def test_fast_split_route_accepts_date_between_origin_and_destination():
    facts = extract_fast_split_facts(
        "我们两个人想从西安出发，2026年10月23日去长沙4天3晚，"
        "总预算7000，希望省心一点。"
    )

    assert facts["departure_city"] == "西安"
    assert facts["destination"] == "长沙"
    assert facts["departure_date"] == "2026-10-23"


def test_fast_split_budget_range_is_preserved_in_agent_seed():
    facts = extract_fast_split_facts(
        "我想从广州去桂林玩4天，3位成人，预算3000-4500元，2026-07-20出发"
    )

    assert facts["budget_text"] == "预算3000-4500元（口径待确认）"

    seed = chat._fast_split_state_seed(facts, planning_mode="agency_plan")
    assert seed["user_requirement"]["budget_text"] == facts["budget_text"]
    assert seed["user_requirement"]["special_needs"] == f"预算：{facts['budget_text']}"
    assert seed["confirmed_facts"]["budget_text"] == facts["budget_text"]
    progress_facts = {
        item["key"]: item["value"]
        for item in seed["progress_snapshot"]["confirmed_facts"]
    }
    assert progress_facts["budget_text"] == facts["budget_text"]


def test_fast_split_people_accepts_measure_word_wei():
    facts = extract_fast_split_facts(
        "需求确认：2026-07-10出发，共3位成人，其中2位老人。"
    )

    assert facts["adult_count"] == 3


def test_fast_split_preserves_adult_and_child_counts_from_total_breakdown():
    facts = extract_fast_split_facts(
        "需求确认：2026-09-12出发，共3位（2位成人、1名儿童），人均预算3000-4500元。"
    )

    assert facts["adult_count"] == 2
    assert facts["children_count"] == 1

    seed = chat._fast_split_state_seed(facts, planning_mode="agency_plan")
    assert seed["user_requirement"]["adult_count"] == 2
    assert seed["user_requirement"]["children_count"] == 1
    assert seed["confirmed_facts"]["children_count"] == 1
    progress = {
        item["key"]: item["value"]
        for item in seed["progress_snapshot"]["confirmed_facts"]
    }
    assert progress["adult_count"] == "2人"
    assert progress["children_count"] == "1人"


def test_fast_split_preserves_compact_adult_child_counts():
    facts = extract_fast_split_facts("亲子游，2大1小，从上海去杭州3天2晚。")

    assert facts["adult_count"] == 2
    assert facts["children_count"] == 1


def test_fast_split_neutral_confirmation_seeds_free_mode_with_original_facts():
    facts = extract_fast_split_facts(
        "我想周末从西安出发去附近轻松玩两天，2个人，预算1500，"
        "想看自然风景和吃点当地小吃。"
    )
    decision = chat._resolve_fast_planning_mode(
        "以上需求确认无误，请先记录需求，然后继续推进规划。",
        latest_fast_split_facts=facts,
        fast_mode_context={"fast_mode_split_needs_confirmation": True},
    )

    assert decision.mode == "free_planning"
    assert decision.confirmed is True

    seed = chat._fast_split_state_seed(
        facts,
        planning_mode=decision.mode,
        planning_mode_reason=decision.reason,
    )
    assert seed["planning_mode"] == "free_planning"
    assert seed["user_requirement"]["adult_count"] == 2
    assert seed["user_requirement"]["budget_text"] == "预算1500（口径待确认）"
    assert "非销售边界" in seed["pending_initial_planning_mode_reason"]


def test_fast_mode_resolution_does_not_auto_confirm_persisted_mode_value():
    decision = chat._resolve_fast_planning_mode(
        "预算还是按前面说的范围就好。",
        latest_fast_split_facts={"planning_mode": "agency_plan"},
        fast_mode_context={
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": False,
        },
    )

    assert decision.mode == "agency_plan"
    assert decision.source == "state"
    assert decision.confirmed is False
    assert decision.needs_confirmation is True
    assert chat._fast_context_has_selected_planning_mode(
        {"planning_mode": "agency_plan", "active_workflow": "agency_plan"}
    ) is False


def test_fast_agency_requirement_does_not_reconfirm_complete_or_existing_mode():
    existing = {
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "departure_city": "广州",
        "destination": "桂林",
        "departure_date": "2026-07-10",
        "travel_days": 4,
        "adult_count": 3,
        "budget_text": "人均预算2500元",
    }

    should_reply, merged, mode_just_confirmed = (
        chat._should_use_fast_agency_requirement_reply(
            latest_fast_split_facts=existing,
            user_message="继续按旅行社省心方案生成行程。",
            mode_decision=SimpleNamespace(
                confirmed=True,
                mode="agency_plan",
                source="latest_user",
            ),
        )
    )

    assert should_reply is False
    assert merged["adult_count"] == 3
    assert mode_just_confirmed is False


def test_initial_complete_agency_ack_requires_first_complete_confirmed_agent_turn():
    complete_facts = {
        "destination": "桂林",
        "departure_date": "2026-07-10",
        "travel_days": 4,
        "adult_count": 3,
        "budget_text": "人均预算2500元",
    }
    confirmed_agency = SimpleNamespace(confirmed=True, mode="agency_plan")

    assert chat._should_emit_initial_complete_agency_ack(
        fast_mode_context={},
        mode_decision=confirmed_agency,
        agency_facts=complete_facts,
        should_fast_agency=False,
    ) is True
    assert chat._should_emit_initial_complete_agency_ack(
        fast_mode_context={"agent_state_initialized": True},
        mode_decision=confirmed_agency,
        agency_facts=complete_facts,
        should_fast_agency=False,
    ) is False
    assert chat._should_emit_initial_complete_agency_ack(
        fast_mode_context={},
        mode_decision=confirmed_agency,
        agency_facts={key: value for key, value in complete_facts.items() if key != "budget_text"},
        should_fast_agency=False,
    ) is False
    assert chat._should_emit_initial_complete_agency_ack(
        fast_mode_context={},
        mode_decision=SimpleNamespace(confirmed=True, mode="free_planning"),
        agency_facts=complete_facts,
        should_fast_agency=False,
    ) is False
    assert chat._should_emit_initial_complete_agency_ack(
        fast_mode_context={},
        mode_decision=confirmed_agency,
        agency_facts=complete_facts,
        should_fast_agency=True,
    ) is False


def test_fast_facts_seed_only_before_agent_initialization_or_real_mode_switch():
    assert chat._should_seed_agent_from_fast_facts(
        {},
        mode_just_confirmed=False,
    ) is True
    assert chat._should_seed_agent_from_fast_facts(
        {"agent_state_initialized": True},
        mode_just_confirmed=False,
    ) is False
    assert chat._should_seed_agent_from_fast_facts(
        {"agent_state_initialized": True},
        mode_just_confirmed=True,
    ) is True


@pytest.mark.asyncio
async def test_fast_facts_sparse_sync_merges_initialized_durable_requirements_only():
    config = {"configurable": {"thread_id": "conversation-existing"}}
    existing_state = {
        "current_step": "itinerary_generation",
        "agency_step": "agency_plan_draft",
        "selected_destination": "长沙",
        "selected_transport": "train",
        "selected_accommodation_option": {"name": "已有酒店"},
        "user_requirement": {
            "destination": "长沙",
            "travel_styles": ["relaxation"],
            "special_needs": "节奏轻松",
        },
        "confirmed_facts": {
            "destination": "长沙",
            "active_workflow": "agency_plan",
        },
    }

    class FakeAgent:
        def __init__(self):
            self.update = None
            self.update_config = None

        async def aget_state(self, received_config):
            assert received_config is config
            return SimpleNamespace(values=existing_state)

        async def aupdate_state(self, received_config, update):
            self.update_config = received_config
            self.update = update

    agent = FakeAgent()
    synced = await chat._sync_fast_facts_to_initialized_agent_state(
        agent,
        config=config,
        fast_mode_context={"agent_state_initialized": True},
        turn_fast_facts={
            "raw_text": "不应写入 checkpoint",
            "source": "first_turn_fast_split",
            "departure_city": "西安",
            "destination": "长沙",
            "departure_date_text": "2026年10月23日",
            "departure_date": "2026-10-23",
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 0,
            "budget_text": "预算7000（口径待确认）",
            "unknown": "不应写入",
        },
    )

    assert synced is True
    assert agent.update_config is config
    assert set(agent.update) == {"user_requirement", "confirmed_facts"}
    assert agent.update["user_requirement"] == {
        "destination": "长沙",
        "travel_styles": ["relaxation"],
        "special_needs": "节奏轻松",
        "departure_city": "西安",
        "departure_date": "2026-10-23",
        "travel_days": 4,
        "adult_count": 2,
        "children_count": 0,
        "budget_text": "预算7000（口径待确认）",
    }
    assert agent.update["confirmed_facts"] == {
        "destination": "长沙",
        "active_workflow": "agency_plan",
        "departure_city": "西安",
        "departure_date": "2026-10-23",
        "travel_days": 4,
        "adult_count": 2,
        "children_count": 0,
        "budget_text": "预算7000（口径待确认）",
    }
    assert "current_step" not in agent.update
    assert "agency_step" not in agent.update
    assert "selected_destination" not in agent.update
    assert existing_state["current_step"] == "itinerary_generation"
    assert existing_state["selected_accommodation_option"] == {"name": "已有酒店"}


@pytest.mark.asyncio
async def test_fast_facts_sparse_sync_skips_uninitialized_or_empty_turn():
    class UnexpectedAgent:
        async def aget_state(self, config):
            raise AssertionError("uninitialized state must not be read")

        async def aupdate_state(self, config, update):
            raise AssertionError("uninitialized state must not be updated")

    assert await chat._sync_fast_facts_to_initialized_agent_state(
        UnexpectedAgent(),
        config={"configurable": {"thread_id": "not-initialized"}},
        fast_mode_context={"agent_state_initialized": False},
        turn_fast_facts={"departure_city": "西安"},
    ) is False
    assert await chat._sync_fast_facts_to_initialized_agent_state(
        UnexpectedAgent(),
        config={"configurable": {"thread_id": "initialized"}},
        fast_mode_context={"agent_state_initialized": True},
        turn_fast_facts={"departure_city": ""},
    ) is False


def test_mode_only_fast_context_is_not_treated_as_trip_requirements():
    mode_only_context = {
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "planning_mode_confirmed": True,
        "agency_step": "agency_plan_draft",
    }

    assert chat._has_meaningful_fast_trip_facts(mode_only_context) is True
    assert chat._has_fast_requirement_facts(mode_only_context) is False
    assert chat._has_fast_requirement_facts({**mode_only_context, "travel_days": 4}) is True


@pytest.mark.asyncio
async def test_persist_fast_mode_context_keeps_only_structured_allowed_facts():
    conversation = SimpleNamespace(extra_info={"existing": "preserved"})

    class FakeResult:
        def scalar_one_or_none(self):
            return conversation

    class FakeDb:
        def __init__(self):
            self.added = []
            self.commit_count = 0

        async def execute(self, statement):
            return FakeResult()

        def add(self, item):
            self.added.append(item)

        async def commit(self):
            self.commit_count += 1

    db = FakeDb()
    await chat._persist_fast_mode_context_on_conversation(
        db,
        conversation_id="conversation-fast-facts",
        facts={
            "raw_text": "包含完整用户原文，不应重复持久化",
            "source": "first_turn_fast_split",
            "destination": "杭州",
            "departure_date_text": "下周一",
            "departure_date": "2026-07-20",
            "travel_days": 4,
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": True,
            "unknown_field": "not allowed",
        },
        needs_confirmation=False,
    )

    persisted = conversation.extra_info["fast_mode_split"]["facts"]
    assert persisted == {
        "destination": "杭州",
        "departure_date_text": "下周一",
        "departure_date": "2026-07-20",
        "travel_days": 4,
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "planning_mode_confirmed": True,
    }
    assert "raw_text" not in persisted
    assert "source" not in persisted
    assert conversation.extra_info["existing"] == "preserved"
    assert db.added == [conversation]
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_persist_agent_state_initialized_commits_marker_before_next_turn():
    conversation = SimpleNamespace(
        extra_info={"fast_mode_split": {"needs_confirmation": True}}
    )

    class FakeResult:
        def scalar_one_or_none(self):
            return conversation

    class FakeDb:
        def __init__(self):
            self.added = []
            self.commit_count = 0

        async def execute(self, statement):
            return FakeResult()

        def add(self, item):
            self.added.append(item)

        async def commit(self):
            self.commit_count += 1

    db = FakeDb()
    await chat._persist_agent_state_initialized(
        db,
        conversation_id="conversation-1",
        progress_snapshot={
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "agency_step": "agency_product_match",
        },
        planning_mode_confirmed=True,
    )

    assert conversation.extra_info["agent_state_initialized"] is True
    assert conversation.extra_info["planning_mode_confirmed"] is True
    assert conversation.extra_info["fast_mode_split"]["needs_confirmation"] is False
    assert conversation.extra_info["agency_step"] == "agency_product_match"
    assert db.added == [conversation]
    assert db.commit_count == 1


@pytest.mark.asyncio
async def test_persist_agent_state_initialized_rolls_back_failed_marker_commit():
    conversation = SimpleNamespace(extra_info={})

    class FakeResult:
        def scalar_one_or_none(self):
            return conversation

    class FailingDb:
        def __init__(self):
            self.rollback_count = 0

        async def execute(self, statement):
            return FakeResult()

        def add(self, item):
            pass

        async def commit(self):
            raise RuntimeError("marker commit failed")

        async def rollback(self):
            self.rollback_count += 1

    db = FailingDb()
    await chat._persist_agent_state_initialized(
        db,
        conversation_id="conversation-1",
    )

    assert db.rollback_count == 1


def test_fast_split_month_day_date_does_not_fall_back_to_weekday():
    facts = extract_fast_split_facts(
        "我想从西安去杭州，两个人，6月10日出发，玩4天，人均预算5000",
        today=date(2026, 5, 21),
    )

    assert facts["departure_date_text"] == "6月10日"
    assert facts["departure_date"] == "2026-06-10"
    assert facts["departure_city"] == "西安"
    assert facts["destination"] == "杭州"


def test_fast_split_prefers_explicit_labeled_route_fields():
    facts = extract_fast_split_facts(
        "目的地确认重庆，出发地成都，2026-06-20出发，3天2晚，4个大人，继续下一阶段。"
    )

    assert facts["departure_city"] == "成都"
    assert facts["destination"] == "重庆"
    assert facts["departure_date"] == "2026-06-20"
    assert facts["travel_days"] == 3
    assert facts["adult_count"] == 4


def test_fast_split_extracts_unlabeled_chinese_destination():
    facts = extract_fast_split_facts("计划去成都旅游，三天，两个人，预算5000左右")

    assert facts["destination"] == "成都"
    assert facts["travel_days"] == 3
    assert facts["adult_count"] == 2
    assert "口径待确认" in facts["budget_text"]


def test_fast_split_final_report_request_does_not_mutate_trip_facts():
    facts = extract_fast_split_facts(
        "请直接生成最终旅行规划报告和report_data，保留预算置信度、风险、待核验项和旅行社业务证据。"
    )

    assert facts == {
        "raw_text": "请直接生成最终旅行规划报告和report_data，保留预算置信度、风险、待核验项和旅行社业务证据。",
        "source": "first_turn_fast_split",
    }


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


def test_progress_snapshot_merge_current_turn_facts_override_old_report_date():
    previous = {
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "agency_step": "agency_plan_draft",
        "confirmed_facts": [
            {"key": "departure_city", "label": "出发地", "value": "西安"},
            {"key": "destination", "label": "目的地", "value": "杭州"},
            {"key": "departure_date", "label": "出发时间", "value": "2026-05-24"},
            {"key": "people", "label": "人数", "value": "2人"},
        ],
    }
    current_turn_snapshot = {
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "agency_step": "agency_requirement",
        "confirmed_facts": [
            {"key": "departure_city", "label": "出发地", "value": "西安"},
            {"key": "destination", "label": "目的地", "value": "杭州"},
            {"key": "departure_date", "label": "出发时间", "value": "2026-06-10"},
            {"key": "days", "label": "行程天数", "value": "4天"},
            {"key": "budget", "label": "预算", "value": "人均预算5000"},
        ],
    }

    merged = chat._merge_progress_snapshot(previous, current_turn_snapshot)

    confirmed = {
        item["key"]: item["value"]
        for item in merged["confirmed_facts"]
        if isinstance(item, dict)
    }
    assert confirmed["departure_date"] == "2026-06-10"
    assert confirmed["days"] == "4天"
    assert confirmed["budget"] == "人均预算5000"
    assert confirmed["people"] == "2人"
    assert merged["planning_mode"] == "agency_plan"
    assert merged["active_workflow"] == "agency_plan"


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
async def test_fast_mode_split_allows_one_user_retry_without_assistant(monkeypatch):
    async def fake_role_counts(db, conversation_id):
        return {"user": 2, "assistant": 0}

    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)

    should_split = await chat._should_use_fast_mode_split(
        SimpleNamespace(),
        "conversation-fast-retry",
        "我想去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下",
    )

    assert should_split is True


@pytest.mark.asyncio
async def test_fast_mode_split_allows_persisted_welcome_assistant(monkeypatch):
    async def fake_role_counts(db, conversation_id):
        return {"user": 1, "assistant": 1}

    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)

    should_split = await chat._should_use_fast_mode_split(
        SimpleNamespace(),
        "conversation-welcome",
        "我想去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下",
    )

    assert should_split is True


@pytest.mark.asyncio
async def test_fast_mode_split_blocks_previous_fast_split_question(monkeypatch):
    async def fake_role_counts(db, conversation_id):
        return {"user": 1, "assistant": 1}

    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)

    should_split = await chat._should_use_fast_mode_split(
        SimpleNamespace(),
        "conversation-fast-already-asked",
        "我想去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下",
        latest_fast_split_facts={"destination": "杭州", "adult_count": 2},
    )

    assert should_split is False


@pytest.mark.asyncio
async def test_fast_mode_split_blocks_confirmed_planning_state(monkeypatch):
    async def fail_role_counts(db, conversation_id):
        raise AssertionError("confirmed mode should short-circuit before role counts")

    monkeypatch.setattr(chat, "_conversation_role_counts", fail_role_counts)

    should_split = await chat._should_use_fast_mode_split(
        SimpleNamespace(),
        "conversation-confirmed-mode",
        "我想去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下",
        state={
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": True,
        },
    )

    assert should_split is False


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
    assert saved_messages[-1]["extra_info"]["fast_mode_split"]["facts"]["planning_mode_confirmed"] is True
    assert saved_messages[-1]["extra_info"]["fast_mode_split"]["facts"]["destination"] == "杭州"


@pytest.mark.asyncio
async def test_chat_stream_complete_fast_agency_date_update_initializes_agent(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []
    captured_input = {}
    persisted_fast_context = {}
    initial_facts = extract_fast_split_facts(
        "我想从西安去杭州，两个人，四天左右，人均预算3500，请你帮我规划一下"
    )
    initial_facts.update(
        {
            "planning_mode": "agency_plan",
            "active_workflow": "agency_plan",
            "planning_mode_confirmed": True,
        }
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
        return {"user": 3, "assistant": 2}

    async def fake_load_fast_facts(db, *, conversation_id):
        return dict(initial_facts)

    class FakeAgent:
        def astream_events(self, input_data, **kwargs):
            captured_input.update(input_data)

            async def response_stream():
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": SimpleNamespace(content="方案正文")},
                }

            return response_stream()

    async def fake_create_travel_agent():
        assert events
        assert events[0]["type"] == "token"
        assert events[0]["content"] == chat._INITIAL_COMPLETE_AGENCY_ACK_MESSAGE
        return FakeAgent()

    async def fake_persist_fast_context(
        db,
        *,
        conversation_id,
        facts,
        needs_confirmation,
    ):
        persisted_fast_context.update(
            {
                "conversation_id": conversation_id,
                "facts": facts,
                "needs_confirmation": needs_confirmation,
            }
        )

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "_conversation_role_counts", fake_role_counts)
    monkeypatch.setattr(chat, "_load_latest_fast_split_facts_for_turn", fake_load_fast_facts)
    monkeypatch.setattr(
        chat,
        "_persist_fast_mode_context_on_conversation",
        fake_persist_fast_context,
    )
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-agency-date",
        "计划下周一",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    assert captured_input["active_workflow"] == "agency_plan"
    assert captured_input["agency_step"] == "agency_product_match"
    assert captured_input["user_requirement"]["departure_date"]
    assert persisted_fast_context["conversation_id"] == "conversation-agency-date"
    assert persisted_fast_context["facts"]["destination"] == "杭州"
    assert persisted_fast_context["facts"]["departure_date"]
    assert persisted_fast_context["facts"]["planning_mode"] == "agency_plan"
    assert persisted_fast_context["needs_confirmation"] is False
    token_events = [event for event in events if event["type"] == "token"]
    assert [event["content"] for event in token_events] == [
        chat._INITIAL_COMPLETE_AGENCY_ACK_MESSAGE,
        "方案正文",
    ]
    assert saved_messages[-1]["content"] == (
        f"{chat._INITIAL_COMPLETE_AGENCY_ACK_MESSAGE}方案正文"
    )
    assert any(event["type"] == "turn_observability" for event in events)
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_chat_stream_sparse_syncs_fast_facts_after_agent_initialization(monkeypatch):
    await reset_session_locks_for_tests()
    captured = {}
    durable_context = {
        "agent_state_initialized": True,
        "planning_mode": "agency_plan",
        "active_workflow": "agency_plan",
        "planning_mode_confirmed": True,
        "agency_step": "agency_plan_draft",
        "destination": "长沙",
        "departure_date": "2026-10-23",
        "travel_days": 4,
        "adult_count": 2,
        "budget_text": "预算7000（口径待确认）",
    }

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        return SimpleNamespace()

    async def fake_load_context(db, *, conversation_id):
        return dict(durable_context)

    async def fake_load_fast_facts(db, *, conversation_id):
        return dict(durable_context)

    async def fake_sync(agent, *, config, fast_mode_context, turn_fast_facts):
        captured["sync_config"] = config
        captured["sync_context"] = fast_mode_context
        captured["sync_facts"] = turn_fast_facts
        return True

    class FakeAgent:
        def astream_events(self, input_data, *, config, version):
            captured["input"] = input_data
            captured["stream_config"] = config

            async def response_stream():
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": SimpleNamespace(content="继续推进")},
                }

            return response_stream()

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "_load_fast_mode_context_for_turn", fake_load_context)
    monkeypatch.setattr(chat, "_load_latest_fast_split_facts_for_turn", fake_load_fast_facts)
    monkeypatch.setattr(chat, "_sync_fast_facts_to_initialized_agent_state", fake_sync)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    async for _ in chat.generate_sse_stream(
        "conversation-durable-fast-sync",
        "我们两个人想从西安出发，2026年10月23日去长沙4天3晚，"
        "总预算7000，希望省心一点，帮我按旅行社方案安排。",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        pass

    assert captured["sync_context"]["agent_state_initialized"] is True
    assert captured["sync_facts"]["departure_city"] == "西安"
    assert captured["sync_facts"]["destination"] == "长沙"
    assert captured["sync_config"] is captured["stream_config"]
    assert "user_requirement" not in captured["input"]
    assert "current_step" not in captured["input"]
    assert "agency_step" not in captured["input"]


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
    assert snapshot["approval_persistence_ready"] is False
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
                            "report": "# 完整报告\n高铁有票。",
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
    assert saved_messages[-1]["content"] == (
        "# 完整报告\n"
        "高铁有票（动态班次与票务状态待二次核验，以官方实时结果为准）。"
    )
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

    assert "".join(token_contents) == "公开开头继续给用户看的内容。"
    assert saved_assistant["content"] == "公开开头继续给用户看的内容。"
    assert "<think" not in serialized
    assert "query_transport_options" not in serialized
    assert "内部推理" not in saved_assistant["content"]


@pytest.mark.asyncio
async def test_chat_stream_transport_claim_tokens_match_saved_assistant(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append({"role": role, "content": content, "extra_info": extra_info or {}})
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            for chunk in ["推荐高", "铁有票。", "其余安排保持不变"]:
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
        "conversation-transport-claim-filter",
        "继续规划交通",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    streamed_text = "".join(
        event["content"] for event in events if event["type"] == "token"
    )
    saved_assistant = [item for item in saved_messages if item["role"] == "assistant"][-1]
    expected = (
        "推荐高铁有票（动态班次与票务状态待二次核验，以官方实时结果为准）。"
        "其余安排保持不变"
    )

    assert streamed_text == expected
    assert saved_assistant["content"] == expected


@pytest.mark.asyncio
async def test_chat_stream_tool_start_flush_preserves_open_thinking_block(monkeypatch):
    await reset_session_locks_for_tests()
    saved_messages = []

    async def fake_save_message(db, conversation_id, role, content, extra_info=None):
        saved_messages.append({"role": role, "content": content, "extra_info": extra_info or {}})
        return SimpleNamespace()

    class FakeAgent:
        async def astream_events(self, *args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": SimpleNamespace(content="公开内容<think>内部")},
            }
            yield {
                "event": "on_tool_start",
                "name": "search_travel_info",
                "run_id": "run-thinking-boundary",
                "data": {"input": {"query": "杭州"}},
            }
            yield {
                "event": "on_tool_end",
                "name": "search_travel_info",
                "run_id": "run-thinking-boundary",
                "data": {"output": "ok"},
            }
            yield {
                "event": "on_chat_model_stream",
                "data": {
                    "chunk": SimpleNamespace(
                        content="推理内容</think>高铁有票"
                    )
                },
            }

    async def fake_create_travel_agent():
        return FakeAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    events = []
    async for frame in chat.generate_sse_stream(
        "conversation-thinking-tool-boundary",
        "继续规划交通",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    ):
        events.append(json.loads(frame.removeprefix("data: ").strip()))

    token_text = "".join(
        event["content"] for event in events if event["type"] == "token"
    )
    expected = (
        "公开内容高铁有票"
        "（动态班次与票务状态待二次核验，以官方实时结果为准）"
    )

    assert token_text == expected
    assert saved_messages[-1]["content"] == expected
    assert "内部" not in json.dumps(events, ensure_ascii=False)
    assert "推理内容" not in saved_messages[-1]["content"]


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
