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
    trim_text_to_token_budget,
)
from app.core.conversation_summary import summarize_conversation, summarize_state_for_context


@dataclass(frozen=True)
class ContextPack:
    """Context bundle injected into a model call."""

    system_appendix: str
    messages: list[Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    summary_text: str = ""


def build_context_pack(
    *,
    state: dict[str, Any],
    messages: list[Any],
    memory_prompt: str = "",
    budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> ContextPack:
    """Return a layered context pack and the bounded message window."""
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

    previous_summary = _coerce_text(state.get("conversation_summary"))
    summary_text = ""
    if decision.should_summarize and old_messages:
        summary = summarize_conversation(
            old_messages,
            current_step=current_step,
            trigger_reason=decision.reason,
            previous_summary=previous_summary,
            token_budget=budget.conversation_summary_tokens,
        )
        summary_text = summary.text
    elif previous_summary:
        summary_text = trim_text_to_token_budget(
            previous_summary,
            budget.conversation_summary_tokens,
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
    if evidence_text:
        sections.append(evidence_text)

    metadata = {
        "message_count": len(messages or []),
        "retained_message_count": len(recent_messages),
        "estimated_message_tokens": decision.estimated_tokens,
        "summary_triggered": decision.should_summarize and bool(old_messages),
        "summary_reason": decision.reason,
        "current_step": current_step,
        "layers": {
            "short_term_state": bool(state_summary),
            "recent_messages": len(recent_messages),
            "conversation_summary": bool(summary_text),
            "long_term_memory": bool(memory_text),
            "evidence_bundle": bool(evidence_text),
        },
    }
    return ContextPack(
        system_appendix="\n\n".join(section for section in sections if section),
        messages=recent_messages if decision.should_summarize else _trim_messages(messages, budget),
        metadata=metadata,
        summary_text=summary_text,
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
