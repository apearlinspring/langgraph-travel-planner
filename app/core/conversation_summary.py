"""
Deterministic conversation summarization for long travel-planning sessions.

This module deliberately avoids an extra LLM call. It extracts durable planning
facts and recent decisions from older messages so the planner can keep long
dialogues bounded while still seeing why the current state looks the way it
does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.context_budget import DEFAULT_CONTEXT_BUDGET, trim_text_to_token_budget


ROLE_LABELS = {
    "human": "用户",
    "user": "用户",
    "ai": "顾问",
    "assistant": "顾问",
    "tool": "工具结果",
}

IMPORTANT_KEYWORDS = (
    "确认",
    "选择",
    "选第",
    "预算",
    "日期",
    "出发",
    "目的地",
    "酒店",
    "住宿",
    "高铁",
    "航班",
    "自驾",
    "忌口",
    "过敏",
    "老人",
    "孩子",
    "亲子",
    "省心",
    "自由行",
    "待核实",
    "待二次核实",
    "兜底估算",
)


@dataclass(frozen=True)
class ConversationSummary:
    """A compact, explainable summary of messages outside the recent window."""

    text: str
    source_message_count: int
    retained_message_count: int
    trigger_reason: str
    highlights: list[str] = field(default_factory=list)


def summarize_conversation(
    messages: list[Any],
    *,
    current_step: str,
    trigger_reason: str,
    previous_summary: str | None = None,
    token_budget: int = DEFAULT_CONTEXT_BUDGET.conversation_summary_tokens,
) -> ConversationSummary:
    """Build a compact summary from older messages."""
    highlights = _extract_highlights(messages)
    lines = ["【会话摘要】"]
    if previous_summary:
        lines.append(trim_text_to_token_budget(previous_summary, token_budget // 3))
    lines.append(f"- 当前规划阶段：{current_step}")
    lines.append(f"- 摘要触发原因：{trigger_reason}")
    if highlights:
        lines.append("- 关键上下文：")
        lines.extend(f"  - {item}" for item in highlights)
    else:
        lines.append("- 关键上下文：旧消息未包含明确可复用决策，优先依赖结构化状态。")

    summary_text = trim_text_to_token_budget("\n".join(lines), token_budget)
    return ConversationSummary(
        text=summary_text,
        source_message_count=len(messages or []),
        retained_message_count=len(highlights),
        trigger_reason=trigger_reason,
        highlights=highlights,
    )


def summarize_state_for_context(state: dict[str, Any]) -> str:
    """Summarize structured short-term planning state for prompt appendices."""
    requirement = state.get("user_requirement") or {}
    lines: list[str] = ["【短期规划状态】"]
    current_step = state.get("current_step")
    if current_step:
        lines.append(f"- 当前阶段：{current_step}")
    planning_mode = state.get("planning_mode") or requirement.get("planning_mode")
    if planning_mode:
        confirmed = state.get("planning_mode_confirmed")
        if confirmed is None:
            confirmed = requirement.get("planning_mode_confirmed")
        lines.append(
            f"- 规划模式：{planning_mode}"
            f"（{'已确认' if confirmed else '待确认'}）"
        )
    if requirement:
        route = " → ".join(
            item
            for item in [
                str(requirement.get("departure_city") or "").strip(),
                str(requirement.get("destination") or state.get("selected_destination") or "").strip(),
            ]
            if item
        )
        if route:
            lines.append(f"- 路线意向：{route}")
        if requirement.get("departure_date"):
            lines.append(f"- 出发日期：{requirement['departure_date']}")
        if requirement.get("travel_days"):
            lines.append(f"- 天数：{requirement['travel_days']} 天")
        people = _format_people(requirement)
        if people:
            lines.append(f"- 人数：{people}")
        budget = _format_budget(requirement)
        if budget:
            lines.append(f"- 预算：{budget}")
        if requirement.get("special_needs"):
            lines.append(f"- 特殊需求：{requirement['special_needs']}")
    if state.get("selected_transport_summary"):
        lines.append(f"- 已选交通：{state['selected_transport_summary']}")
    if state.get("selected_accommodation_summary"):
        lines.append(f"- 已选住宿：{state['selected_accommodation_summary']}")
    if state.get("budget_summary"):
        lines.append(f"- 预算摘要：{state['budget_summary']}")
    return "\n".join(lines)


def _extract_highlights(messages: list[Any]) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()
    for message in messages or []:
        text = _normalize_text(_message_content(message))
        if not text or not _looks_important(text):
            continue
        role = _message_role(message)
        line = f"{ROLE_LABELS.get(role, role or '消息')}：{text}"
        line = _truncate_line(line)
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        highlights.append(line)
    return highlights[-10:]


def _looks_important(text: str) -> bool:
    if any(keyword in text for keyword in IMPORTANT_KEYWORDS):
        return True
    if re.search(r"\d+\s*(天|晚|人|元|万)", text):
        return True
    if re.search(r"20\d{2}[-年/.]\d{1,2}", text):
        return True
    return False


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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate_line(text: str, max_chars: int = 180) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "...（已截断）"


def _format_people(requirement: dict[str, Any]) -> str:
    adults = requirement.get("adult_count")
    children = requirement.get("children_count")
    parts = []
    if adults is not None:
        parts.append(f"{adults} 成人")
    if children:
        parts.append(f"{children} 儿童")
    return " + ".join(parts)


def _format_budget(requirement: dict[str, Any]) -> str:
    budget_min = requirement.get("budget_min")
    budget_max = requirement.get("budget_max")
    if budget_min and budget_max:
        return f"{budget_min}-{budget_max} 元/人"
    if budget_max:
        return f"不超过 {budget_max} 元/人"
    if budget_min:
        return f"不少于 {budget_min} 元/人"
    return ""

