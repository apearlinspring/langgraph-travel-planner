import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.core.context_budget import ContextBudget, decide_context_budget, estimate_tokens
from app.core.context_pack import abuild_context_pack, build_context_pack
from app.core.conversation_summary import (
    ConversationSummary,
    ConversationSummaryConfig,
    asummarize_conversation,
    extract_key_history_turns,
    summarize_conversation,
    summarize_state_for_context,
)
from app.core.memory_models import (
    build_memory_audit_entries,
    classify_memory_candidate,
    filter_stable_memory_values,
)


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
    assert summary.method == "deterministic"


def test_summary_backend_defaults_to_deterministic_without_model_key(monkeypatch):
    monkeypatch.delenv("CONVERSATION_SUMMARY_BACKEND", raising=False)
    monkeypatch.delenv("ZHIXING_CONTEXT_SUMMARY_MODE", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    config = ConversationSummaryConfig.from_environment()

    assert config.mode == "deterministic"
    assert config.requested_backend == "deterministic"
    assert config.fallback_reason is None


@pytest.mark.asyncio
async def test_llm_summary_backend_without_key_explicitly_degrades(monkeypatch):
    monkeypatch.setenv("CONVERSATION_SUMMARY_BACKEND", "llm")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    config = ConversationSummaryConfig.from_environment()
    summary = await asummarize_conversation(
        [HumanMessage(content="确认预算12000元。")],
        current_step="transport_planning",
        trigger_reason="测试缺少模型密钥",
        config=config,
    )

    assert config.requested_backend == "llm"
    assert config.mode == "deterministic"
    assert "DASHSCOPE_API_KEY" in (config.fallback_reason or "")
    assert summary.method == "deterministic"
    assert "DASHSCOPE_API_KEY" in (summary.fallback_reason or "")


def test_llm_summary_backend_without_key_can_fail_configuration(monkeypatch):
    monkeypatch.setenv("CONVERSATION_SUMMARY_BACKEND", "llm")
    monkeypatch.setenv("CONVERSATION_SUMMARY_FALLBACK", "false")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        ConversationSummaryConfig.from_environment()


def test_key_history_turns_retain_original_evidence():
    messages = [
        HumanMessage(content="闲聊一句。"),
        HumanMessage(content="我们一家三口从上海出发，预算12000元，孩子海鲜过敏。"),
        AIMessage(content="收到，我按亲子节奏处理。"),
        ToolMessage(
            content="高铁候选：G1，价格626元，来源12306-mcp，正式购票前待核实。",
            name="query_transport_options",
            tool_call_id="tool-1",
        ),
    ]

    turns = extract_key_history_turns(
        messages,
        query="最终报告里记得说明预算和海鲜过敏",
        limit=3,
        token_budget=180,
    )

    assert len(turns) >= 2
    assert any("预算12000元" in turn.content for turn in turns)
    assert any("12306-mcp" in turn.content for turn in turns)


@pytest.mark.asyncio
async def test_llm_summary_contract_is_configurable_with_injected_summarizer():
    class FakeSummarizer:
        async def summarize(self, messages, **kwargs):
            return ConversationSummary(
                text="【会话摘要】\n- LLM 摘要：已确认亲子高铁方案。",
                source_message_count=len(messages),
                retained_message_count=1,
                trigger_reason=kwargs["trigger_reason"],
                highlights=["用户：确认亲子高铁方案"],
                method="llm",
                model_name="fake-summary-model",
            )

    summary = await asummarize_conversation(
        [HumanMessage(content="确认亲子高铁方案，预算12000元。")],
        current_step="transport_planning",
        trigger_reason="测试 LLM 摘要",
        config=ConversationSummaryConfig(mode="llm"),
        llm_summarizer=FakeSummarizer(),
    )

    assert summary.method == "llm"
    assert summary.model_name == "fake-summary-model"
    assert "亲子高铁方案" in summary.text


@pytest.mark.asyncio
async def test_async_context_pack_defaults_to_deterministic_summary():
    messages = [
        HumanMessage(content=f"第{i}轮：预算{i * 1000}元，确认继续。")
        for i in range(8)
    ]

    pack = await abuild_context_pack(
        state={"current_step": "transport_planning"},
        messages=messages,
        budget=ContextBudget(max_messages_without_summary=3),
        summary_config=ConversationSummaryConfig(mode="deterministic"),
    )

    assert pack.metadata["summary_triggered"] is True
    assert pack.metadata["summary_method"] == "deterministic"
    assert "【会话摘要】" in pack.system_appendix


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
    assert "【关键历史轮次】" in pack.system_appendix
    assert pack.metadata["key_history_turn_count"] >= 1
    assert pack.key_history_turns
    assert "【证据包摘要】" in pack.system_appendix
    assert "已按上下文预算截断" in pack.messages[-1].content


def test_context_pack_has_layer_boundaries_and_token_ceiling():
    messages = [
        HumanMessage(content=f"第{i}轮：确认预算{i * 1000}元，孩子海鲜过敏。")
        for i in range(30)
    ]

    pack = build_context_pack(
        state={"current_step": "order_generation"},
        messages=messages,
        budget=ContextBudget(
            max_messages_without_summary=4,
            final_stage_recent_human_turns=1,
            conversation_summary_tokens=180,
            key_history_tokens=120,
            short_term_state_tokens=120,
            long_term_memory_tokens=80,
            evidence_bundle_tokens=80,
            max_message_chars=120,
        ),
    )

    assert pack.metadata["estimated_context_pack_tokens"] < 12000
    boundaries = pack.metadata["context_layer_boundaries"]
    assert "short_term_state" in boundaries
    assert "long_term_memory" in boundaries
    assert "evidence_bundle" in boundaries


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
    assert stable.source == "user_statement"
    assert stable.extraction_method == "rule_extraction"
    assert stable.reason
    assert stable.confidence >= 0.75
    assert explicit_temporary.accepted is False


def test_memory_policy_filters_mixed_candidates():
    accepted, rejected = filter_stable_memory_values(
        ["我喜欢博物馆", "本次想少走路"],
    )

    assert accepted == ["我喜欢博物馆"]
    assert [item.value for item in rejected] == ["本次想少走路"]


def test_memory_audit_entries_include_source_reason_and_confidence():
    entries = build_memory_audit_entries(
        "profile.travel_styles",
        ["我一直喜欢博物馆", "这次想少走路"],
        source="memory_tool:update_travel_style_tool",
        accepted_only=False,
    )

    assert len(entries) == 2
    accepted = [entry for entry in entries if entry.accepted]
    rejected = [entry for entry in entries if not entry.accepted]
    assert accepted[0].source == "memory_tool:update_travel_style_tool"
    assert accepted[0].extraction_method == "rule_extraction"
    assert accepted[0].reason
    assert accepted[0].confidence >= 0.75
    assert rejected[0].scope == "temporary"


def test_memory_audit_entries_distinguish_extraction_methods():
    llm_entries = build_memory_audit_entries(
        "profile.food_preferences",
        ["我喜欢吃辣"],
        source="memory_tool:update_food_preference_tool",
        extraction_method="llm_extraction",
    )
    human_entries = build_memory_audit_entries(
        "profile.dietary_restrictions",
        ["请记住我海鲜过敏"],
        source="memory_tool:update_dietary_restriction_tool",
        extraction_method="human_confirmed",
    )

    assert llm_entries[0].extraction_method == "llm_extraction"
    assert human_entries[0].extraction_method == "human_confirmed"
