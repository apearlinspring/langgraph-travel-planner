"""
Build layered prompt context for the travel-planning agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.context_budget import (
    DEFAULT_CONTEXT_BUDGET,
    ContextBudget,
    ContextBudgetDecision,
    decide_context_budget,
    estimate_messages_tokens,
    estimate_tokens,
    trim_text_to_token_budget,
)
from app.core.conversation_summary import (
    ConversationSummary,
    ConversationSummaryConfig,
    asummarize_conversation,
    extract_key_history_turns,
    format_key_history_turns,
    summarize_conversation,
    summarize_state_for_context,
)


@dataclass(frozen=True)
class ContextPack:
    """Context bundle injected into a model call."""

    system_appendix: str
    messages: list[Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    summary_text: str = ""
    key_history_turns: list[dict[str, Any]] = field(default_factory=list)


def build_context_pack(
    *,
    state: dict[str, Any],
    messages: list[Any],
    memory_prompt: str = "",
    budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> ContextPack:
    """Return a layered context pack and the bounded message window."""
    prepared = _prepare_context_pack_inputs(
        state=state,
        messages=messages,
        budget=budget,
    )
    summary = _build_sync_summary(
        prepared=prepared,
        budget=budget,
    )
    return _compose_context_pack(
        state=state,
        messages=messages,
        memory_prompt=memory_prompt,
        budget=budget,
        prepared=prepared,
        summary=summary,
    )


async def abuild_context_pack(
    *,
    state: dict[str, Any],
    messages: list[Any],
    memory_prompt: str = "",
    budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
    summary_config: ConversationSummaryConfig | None = None,
) -> ContextPack:
    """Async context pack builder that can use an optional LLM summarizer."""

    prepared = _prepare_context_pack_inputs(
        state=state,
        messages=messages,
        budget=budget,
    )
    summary = await _build_async_summary(
        prepared=prepared,
        budget=budget,
        summary_config=summary_config or ConversationSummaryConfig.from_environment(),
    )
    return _compose_context_pack(
        state=state,
        messages=messages,
        memory_prompt=memory_prompt,
        budget=budget,
        prepared=prepared,
        summary=summary,
    )


def _prepare_context_pack_inputs(
    *,
    state: dict[str, Any],
    messages: list[Any],
    budget: ContextBudget,
) -> dict[str, Any]:
    current_step = str(state.get("current_step") or "")
    previous_step = state.get("context_last_step")
    decision = decide_context_budget(
        messages,
        budget=budget,
        current_step=current_step,
        previous_step=str(previous_step) if previous_step else None,
    )
    recent_turns = (
        budget.final_stage_recent_human_turns
        if current_step == "order_generation"
        else budget.max_recent_human_turns
    )
    recent_messages = _select_recent_messages(
        messages,
        human_turns=recent_turns,
        budget=budget,
    )
    old_messages = messages[: max(0, len(messages) - len(recent_messages))]
    return {
        "current_step": current_step,
        "decision": decision,
        "recent_messages": recent_messages,
        "old_messages": old_messages,
        "previous_summary": _coerce_text(state.get("conversation_summary")),
    }


def _build_sync_summary(
    *,
    prepared: dict[str, Any],
    budget: ContextBudget,
) -> ConversationSummary | None:
    decision: ContextBudgetDecision = prepared["decision"]
    old_messages = prepared["old_messages"]
    previous_summary = prepared["previous_summary"]
    if decision.should_summarize and old_messages:
        return summarize_conversation(
            old_messages,
            current_step=prepared["current_step"],
            trigger_reason=decision.reason,
            previous_summary=previous_summary,
            token_budget=budget.conversation_summary_tokens,
        )
    if previous_summary:
        return ConversationSummary(
            text=trim_text_to_token_budget(
                previous_summary,
                budget.conversation_summary_tokens,
            ),
            source_message_count=0,
            retained_message_count=0,
            trigger_reason="沿用已有摘要",
            method="deterministic",
        )
    return None


async def _build_async_summary(
    *,
    prepared: dict[str, Any],
    budget: ContextBudget,
    summary_config: ConversationSummaryConfig,
) -> ConversationSummary | None:
    decision: ContextBudgetDecision = prepared["decision"]
    old_messages = prepared["old_messages"]
    previous_summary = prepared["previous_summary"]
    if decision.should_summarize and old_messages:
        return await asummarize_conversation(
            old_messages,
            current_step=prepared["current_step"],
            trigger_reason=decision.reason,
            previous_summary=previous_summary,
            token_budget=budget.conversation_summary_tokens,
            config=summary_config,
        )
    if previous_summary:
        return ConversationSummary(
            text=trim_text_to_token_budget(
                previous_summary,
                budget.conversation_summary_tokens,
            ),
            source_message_count=0,
            retained_message_count=0,
            trigger_reason="沿用已有摘要",
            method="deterministic",
        )
    return None


def _compose_context_pack(
    *,
    state: dict[str, Any],
    messages: list[Any],
    memory_prompt: str,
    budget: ContextBudget,
    prepared: dict[str, Any],
    summary: ConversationSummary | None,
) -> ContextPack:
    current_step = prepared["current_step"]
    decision: ContextBudgetDecision = prepared["decision"]
    recent_messages = prepared["recent_messages"]
    old_messages = prepared["old_messages"]
    summary_text = summary.text if summary else ""
    key_history_turns = (
        extract_key_history_turns(
            old_messages,
            query=_latest_human_text(recent_messages),
            limit=budget.max_key_history_turns,
            token_budget=budget.key_history_tokens,
        )
        if old_messages and (decision.should_summarize or summary_text)
        else []
    )
    key_history_text = trim_text_to_token_budget(
        format_key_history_turns(key_history_turns),
        budget.key_history_tokens,
    )

    state_summary = trim_text_to_token_budget(
        summarize_state_for_context(state),
        budget.short_term_state_tokens,
    )
    memory_text = trim_text_to_token_budget(
        memory_prompt,
        budget.long_term_memory_tokens,
    )
    evidence_text = trim_text_to_token_budget(
        _format_evidence_bundle(state.get("evidence_bundle")),
        budget.evidence_bundle_tokens,
    )

    sections = [
        "【上下文工程】",
        "- 当前提示词只注入必要状态、长期偏好、会话摘要和证据包；旧消息已按预算压缩。",
        "- 长期记忆只代表稳定偏好或历史事实；临时要求以本轮消息和短期状态为准。",
        state_summary,
    ]
    if memory_text:
        sections.append(memory_text)
    if summary_text:
        sections.append(summary_text)
    if key_history_text:
        sections.append(key_history_text)
    if evidence_text:
        sections.append(evidence_text)
    system_appendix = "\n\n".join(section for section in sections if section)
    context_token_estimate = estimate_tokens(system_appendix) + estimate_messages_tokens(
        recent_messages if decision.should_summarize else _trim_messages(messages, budget)
    )

    metadata = {
        "message_count": len(messages or []),
        "retained_message_count": len(recent_messages),
        "estimated_message_tokens": decision.estimated_tokens,
        "estimated_context_pack_tokens": context_token_estimate,
        "summary_triggered": decision.should_summarize and bool(old_messages),
        "summary_reason": decision.reason,
        "summary_method": summary.method if summary else "none",
        "summary_model": summary.model_name if summary else None,
        "summary_fallback_reason": summary.fallback_reason if summary else None,
        "key_history_turn_count": len(key_history_turns),
        "current_step": current_step,
        "context_layer_boundaries": _context_layer_boundaries(),
        "layers": {
            "short_term_state": bool(state_summary),
            "recent_messages": len(recent_messages),
            "conversation_summary": bool(summary_text),
            "key_history": len(key_history_turns),
            "long_term_memory": bool(memory_text),
            "evidence_bundle": bool(evidence_text),
        },
    }
    return ContextPack(
        system_appendix=system_appendix,
        messages=recent_messages if decision.should_summarize else _trim_messages(messages, budget),
        metadata=metadata,
        summary_text=summary_text,
        key_history_turns=[turn.to_dict() for turn in key_history_turns],
    )


def _select_recent_messages(
    messages: list[Any],
    *,
    human_turns: int,
    budget: ContextBudget,
) -> list[Any]:
    if not messages:
        return []

    human_seen = 0
    start_index = 0
    for index in range(len(messages) - 1, -1, -1):
        if _is_human_message(messages[index]):
            human_seen += 1
            if human_seen >= human_turns:
                start_index = index
                break
    else:
        start_index = max(0, len(messages) - max(1, human_turns * 2))

    return _trim_messages(messages[start_index:], budget)


def _trim_messages(messages: list[Any], budget: ContextBudget) -> list[Any]:
    return [_trim_message(message, budget) for message in messages or []]


def _trim_message(message: Any, budget: ContextBudget) -> Any:
    content = _message_content(message)
    max_chars = (
        budget.max_tool_message_chars
        if _message_role(message) == "tool"
        else budget.max_message_chars
    )
    if len(content) <= max_chars:
        return message
    trimmed_content = content[:max_chars].rstrip() + "\n...（已按上下文预算截断）"

    if isinstance(message, dict):
        copied = dict(message)
        copied["content"] = trimmed_content
        return copied
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": trimmed_content})
    if hasattr(message, "copy"):
        return message.copy(update={"content": trimmed_content})
    return message


def _is_human_message(message: Any) -> bool:
    return _message_role(message) in {"human", "user"}


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "")
    msg_type = getattr(message, "type", None)
    if msg_type:
        return str(msg_type)
    return message.__class__.__name__.replace("Message", "").lower()


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content or "")


def _latest_human_text(messages: list[Any]) -> str:
    for message in reversed(messages or []):
        if _is_human_message(message):
            return _message_content(message)
    return ""


def _format_evidence_bundle(evidence_bundle: Any) -> str:
    if not isinstance(evidence_bundle, dict) or not evidence_bundle:
        return ""

    lines = ["【证据包摘要】"]
    for category, raw_items in list(evidence_bundle.items())[:6]:
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        compact_items: list[str] = []
        for item in items[:3]:
            if isinstance(item, dict):
                summary = (
                    item.get("summary")
                    or item.get("title")
                    or item.get("source")
                    or item.get("basis")
                    or str(item)
                )
            else:
                summary = str(item)
            compact_items.append(str(summary))
        if compact_items:
            lines.append(f"- {category}：{'；'.join(compact_items)}")
    return "\n".join(lines)


def _coerce_text(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text") or value.get("summary") or "")
    return str(value)


def _context_layer_boundaries() -> dict[str, str]:
    return {
        "short_term_state": "TravelState 当前规划字段，是本次行程的可信结构化状态。",
        "recent_messages": "最近原始对话，用于承接用户最新修改、确认或反悔。",
        "conversation_summary": "旧消息压缩摘要，只承载可复用事实和阶段变更。",
        "key_history": "从旧消息检索出的少量原文轮次，用于补充摘要之外的证据。",
        "long_term_memory": "跨会话稳定偏好和历史事实，不代表本次临时条件。",
        "evidence_bundle": "RAG 和工具证据摘要，用于报告依据、预算置信度和待核验项。",
    }
