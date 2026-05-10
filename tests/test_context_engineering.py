from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.context_budget import ContextBudget, decide_context_budget, estimate_tokens
from app.core.context_pack import build_context_pack
from app.core.conversation_summary import summarize_conversation, summarize_state_for_context
from app.core.memory_models import classify_memory_candidate, filter_stable_memory_values


def test_estimate_tokens_handles_chinese_more_conservatively():
    assert estimate_tokens("上海北京西安") >= 6
    assert estimate_tokens("high speed rail") < estimate_tokens("高铁真实票价")


def test_budget_decision_triggers_on_message_count():
    messages = [HumanMessage(content=f"第{i}轮：预算确认{i}元") for i in range(5)]
    decision = decide_context_budget(
        messages,
        budget=ContextBudget(max_messages_without_summary=3),
        current_step="transport_planning",
    )

    assert decision.should_summarize is True
    assert "消息数" in decision.reason


def test_conversation_summary_keeps_planning_facts():
    messages = [
        HumanMessage(content="我们一家三口从上海出发，预算12000元，想去北京。"),
        AIMessage(content="我会按亲子节奏安排。"),
        HumanMessage(content="确认选择高铁，孩子海鲜过敏。"),
    ]

    summary = summarize_conversation(
        messages,
        current_step="accommodation_planning",
        trigger_reason="测试压缩",
    )

    assert "【会话摘要】" in summary.text
    assert "预算12000元" in summary.text
    assert "孩子海鲜过敏" in summary.text
    assert summary.source_message_count == 3


def test_state_summary_prefers_structured_short_term_state():
    state = {
        "current_step": "order_generation",
        "planning_mode": "agency_plan",
        "planning_mode_confirmed": True,
        "user_requirement": {
            "departure_city": "上海",
            "destination": "北京",
            "departure_date": "2026-05-10",
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 1,
            "budget_max": 12000,
            "special_needs": "亲子省心",
        },
    }

    text = summarize_state_for_context(state)

    assert "【短期规划状态】" in text
    assert "上海 → 北京" in text
    assert "agency_plan" in text
    assert "2 成人 + 1 儿童" in text


def test_context_pack_summarizes_old_messages_and_keeps_recent_window():
    messages = [
        HumanMessage(content="我们从上海去北京，预算12000元。"),
        AIMessage(content="收到，我先按亲子方案理解。"),
        HumanMessage(content="孩子海鲜过敏，记得避开。"),
        AIMessage(content="已记录饮食禁忌。"),
        HumanMessage(content="确认选择高铁。"),
        ToolMessage(
            content="工具返回：" + "真实车次候选。" * 300,
            name="query_transport_options",
            tool_call_id="tool-1",
        ),
    ]
    state = {
        "current_step": "order_generation",
        "user_requirement": {
            "departure_city": "上海",
            "destination": "北京",
            "travel_days": 4,
            "adult_count": 2,
            "children_count": 1,
        },
        "evidence_bundle": {
            "pricing": [{"summary": "交通按真实工具价优先"}],
        },
    }

    pack = build_context_pack(
        state=state,
        messages=messages,
        memory_prompt="**用户历史偏好**：\n- 饮食禁忌：海鲜过敏",
        budget=ContextBudget(
            max_messages_without_summary=3,
            final_stage_recent_human_turns=1,
            max_tool_message_chars=80,
        ),
    )

    assert pack.metadata["summary_triggered"] is True
    assert len(pack.messages) == 2
    assert "孩子海鲜过敏" in pack.system_appendix
    assert "【证据包摘要】" in pack.system_appendix
    assert "已按上下文预算截断" in pack.messages[-1].content


def test_memory_policy_rejects_temporary_trip_conditions():
    temporary = classify_memory_candidate("这次想住江景房")
    temporary_like = classify_memory_candidate("这次喜欢安静一点")
    stable = classify_memory_candidate("我一直喜欢安静的酒店")
    explicit_temporary = classify_memory_candidate("清淡饮食", memory_scope="temporary")

    assert temporary.accepted is False
    assert temporary.scope == "temporary"
    assert temporary_like.accepted is False
    assert stable.accepted is True
    assert stable.scope == "stable"
    assert explicit_temporary.accepted is False


def test_memory_policy_filters_mixed_candidates():
    accepted, rejected = filter_stable_memory_values(
        ["我喜欢博物馆", "本次想少走路"],
    )

    assert accepted == ["我喜欢博物馆"]
    assert [item.value for item in rejected] == ["本次想少走路"]
