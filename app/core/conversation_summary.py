"""
Deterministic conversation summarization for long travel-planning sessions.

This module deliberately avoids an extra LLM call. It extracts durable planning
facts and recent decisions from older messages so the planner can keep long
dialogues bounded while still seeing why the current state looks the way it
does.
"""
from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.context_budget import (
    DEFAULT_CONTEXT_BUDGET,
    estimate_tokens,
    trim_text_to_token_budget,
)

logger = logging.getLogger(__name__)


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
    method: Literal["deterministic", "llm"] = "deterministic"
    model_name: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class KeyConversationTurn:
    """Original turn retained as evidence beside the compressed summary."""

    index: int
    role: str
    content: str
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "role": self.role,
            "content": self.content,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ConversationSummaryConfig:
    """Runtime controls for conversation summarization."""

    mode: Literal["deterministic", "llm"] = "deterministic"
    llm_profile: str = "rag"
    llm_max_tokens: int = 700
    fallback_to_deterministic: bool = True
    requested_backend: str = "deterministic"
    fallback_reason: str | None = None

    @classmethod
    def from_environment(cls) -> "ConversationSummaryConfig":
        """Build config from environment variables without requiring tests to use LLM."""

        requested_backend = (
            os.getenv("CONVERSATION_SUMMARY_BACKEND")
            or os.getenv("ZHIXING_CONTEXT_SUMMARY_MODE")
            or "deterministic"
        ).strip().lower()
        mode = requested_backend if requested_backend in {"deterministic", "llm"} else "deterministic"
        profile = os.getenv("ZHIXING_CONTEXT_SUMMARY_PROFILE", "rag").strip() or "rag"
        max_tokens = _safe_int(
            os.getenv("ZHIXING_CONTEXT_SUMMARY_MAX_TOKENS"),
            default=700,
        )
        fallback = (
            os.getenv("CONVERSATION_SUMMARY_FALLBACK")
            or os.getenv("ZHIXING_CONTEXT_SUMMARY_FALLBACK")
            or "true"
        ).strip().lower()
        fallback_to_deterministic = fallback not in {"0", "false", "no"}
        fallback_reason = None
        if mode == "llm" and not _has_model_credentials():
            fallback_reason = (
                "CONVERSATION_SUMMARY_BACKEND=llm 但未检测到模型密钥 "
                "DASHSCOPE_API_KEY"
            )
            if fallback_to_deterministic:
                mode = "deterministic"
            else:
                raise RuntimeError(f"{fallback_reason}，且已关闭确定性摘要回退")
        return cls(
            mode=mode,  # type: ignore[arg-type]
            llm_profile=profile,
            llm_max_tokens=max(128, max_tokens),
            fallback_to_deterministic=fallback_to_deterministic,
            requested_backend=requested_backend,
            fallback_reason=fallback_reason,
        )


class LLMConversationSummarizer:
    """Optional LLM-backed summarizer.

    The model is imported lazily so deterministic tests do not initialize a
    provider client. All model creation still goes through llm_factory.
    """

    def __init__(self, config: ConversationSummaryConfig | None = None) -> None:
        self.config = config or ConversationSummaryConfig()

    async def summarize(
        self,
        messages: list[Any],
        *,
        current_step: str,
        trigger_reason: str,
        previous_summary: str | None = None,
        token_budget: int = DEFAULT_CONTEXT_BUDGET.conversation_summary_tokens,
    ) -> ConversationSummary:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.utils.llm_factory import build_chat_model, resolve_model_name

        model_name = resolve_model_name(profile=self.config.llm_profile)  # type: ignore[arg-type]
        model = build_chat_model(
            profile=self.config.llm_profile,  # type: ignore[arg-type]
            temperature=0.1,
            max_tokens=self.config.llm_max_tokens,
        )
        prompt = _build_llm_summary_prompt(
            messages,
            current_step=current_step,
            trigger_reason=trigger_reason,
            previous_summary=previous_summary,
            token_budget=token_budget,
        )
        response = await model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "你是旅行规划系统的会话压缩器。只保留可复用事实、"
                        "用户确认、偏好依据和待核验项；不要编造新事实。"
                    )
                ),
                HumanMessage(content=prompt),
            ]
        )
        summary_text = _message_content(response).strip()
        summary_text = trim_text_to_token_budget(summary_text, token_budget)
        highlights = _extract_highlights(messages)
        return ConversationSummary(
            text=summary_text,
            source_message_count=len(messages or []),
            retained_message_count=len(highlights),
            trigger_reason=trigger_reason,
            highlights=highlights,
            method="llm",
            model_name=model_name,
        )


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
        method="deterministic",
    )


async def asummarize_conversation(
    messages: list[Any],
    *,
    current_step: str,
    trigger_reason: str,
    previous_summary: str | None = None,
    token_budget: int = DEFAULT_CONTEXT_BUDGET.conversation_summary_tokens,
    config: ConversationSummaryConfig | None = None,
    llm_summarizer: LLMConversationSummarizer | None = None,
) -> ConversationSummary:
    """Summarize messages with optional LLM support and deterministic fallback."""

    summary_config = config or ConversationSummaryConfig()
    deterministic = summarize_conversation(
        messages,
        current_step=current_step,
        trigger_reason=trigger_reason,
        previous_summary=previous_summary,
        token_budget=token_budget,
    )
    if summary_config.mode != "llm":
        if summary_config.fallback_reason:
            return ConversationSummary(
                text=deterministic.text,
                source_message_count=deterministic.source_message_count,
                retained_message_count=deterministic.retained_message_count,
                trigger_reason=deterministic.trigger_reason,
                highlights=deterministic.highlights,
                method="deterministic",
                fallback_reason=summary_config.fallback_reason,
            )
        return deterministic

    summarizer = llm_summarizer or LLMConversationSummarizer(summary_config)
    try:
        return await summarizer.summarize(
            messages,
            current_step=current_step,
            trigger_reason=trigger_reason,
            previous_summary=previous_summary,
            token_budget=token_budget,
        )
    except Exception as exc:
        logger.warning("LLM 会话摘要失败，回退确定性摘要: %s", exc)
        if not summary_config.fallback_to_deterministic:
            raise
        return ConversationSummary(
            text=deterministic.text,
            source_message_count=deterministic.source_message_count,
            retained_message_count=deterministic.retained_message_count,
            trigger_reason=deterministic.trigger_reason,
            highlights=deterministic.highlights,
            method="deterministic",
            fallback_reason=f"LLM 摘要失败：{exc}",
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


def extract_key_history_turns(
    messages: list[Any],
    *,
    query: str = "",
    limit: int = DEFAULT_CONTEXT_BUDGET.max_key_history_turns,
    token_budget: int = DEFAULT_CONTEXT_BUDGET.key_history_tokens,
) -> list[KeyConversationTurn]:
    """Select a small set of original historical turns worth retaining."""

    if not messages or limit <= 0 or token_budget <= 0:
        return []

    query_terms = _important_query_terms(query)
    scored: list[KeyConversationTurn] = []
    for index, message in enumerate(messages):
        content = _normalize_text(_message_content(message))
        if not content:
            continue
        score, reasons = _score_key_turn(content, _message_role(message), query_terms)
        if score <= 0:
            continue
        scored.append(
            KeyConversationTurn(
                index=index,
                role=ROLE_LABELS.get(_message_role(message), _message_role(message) or "消息"),
                content=_truncate_line(content, max_chars=220),
                score=score,
                reason="；".join(reasons),
            )
        )

    selected = sorted(scored, key=lambda item: (item.score, item.index), reverse=True)[:limit]
    selected = sorted(selected, key=lambda item: item.index)
    bounded: list[KeyConversationTurn] = []
    used_tokens = 0
    for turn in selected:
        estimated = estimate_tokens(f"{turn.role} {turn.reason} {turn.content}")
        if bounded and used_tokens + estimated > token_budget:
            break
        bounded.append(turn)
        used_tokens += estimated
    return bounded


def format_key_history_turns(turns: list[KeyConversationTurn]) -> str:
    if not turns:
        return ""
    lines = ["【关键历史轮次】"]
    for turn in turns:
        lines.append(f"- {turn.role}（#{turn.index + 1}，{turn.reason}）：{turn.content}")
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


def _score_key_turn(
    text: str,
    role: str,
    query_terms: set[str],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    keyword_hits = [keyword for keyword in IMPORTANT_KEYWORDS if keyword in text]
    if keyword_hits:
        score += min(4, len(keyword_hits))
        reasons.append("含关键规划词")
    if re.search(r"\d+\s*(天|晚|人|元|万)", text):
        score += 1.5
        reasons.append("含人数/天数/预算")
    if re.search(r"20\d{2}[-年/.]\d{1,2}", text):
        score += 1.0
        reasons.append("含日期")
    overlap = {term for term in query_terms if term and term in text}
    if overlap:
        score += min(3, len(overlap))
        reasons.append("匹配当前问题")
    if role in {"human", "user"}:
        score += 0.5
        reasons.append("用户原话")
    if role == "tool":
        score += 0.5
        reasons.append("工具证据")
    return score, reasons


def _important_query_terms(query: str) -> set[str]:
    text = _normalize_text(query)
    if not text:
        return set()
    terms = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", text))
    return {term for term in terms if term not in {"请帮我", "这个", "一下"}}


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


def _build_llm_summary_prompt(
    messages: list[Any],
    *,
    current_step: str,
    trigger_reason: str,
    previous_summary: str | None,
    token_budget: int,
) -> str:
    excerpts = []
    for message in messages or []:
        role = ROLE_LABELS.get(_message_role(message), _message_role(message) or "消息")
        content = _truncate_line(_normalize_text(_message_content(message)), max_chars=260)
        if content:
            excerpts.append(f"{role}：{content}")
    previous = previous_summary or "无"
    body = "\n".join(excerpts[-24:])
    return (
        "请把以下旧对话压缩成中文要点摘要，输出必须包含：\n"
        "1. 已确认的旅行需求、选择和变更。\n"
        "2. 稳定长期偏好与本次临时条件的边界。\n"
        "3. 仍需核验或不能承诺的事项。\n"
        f"摘要目标预算约 {token_budget} token。\n\n"
        f"当前阶段：{current_step}\n"
        f"触发原因：{trigger_reason}\n"
        f"已有摘要：{previous}\n\n"
        f"旧对话摘录：\n{body}"
    )


def _safe_int(value: str | None, *, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _has_model_credentials() -> bool:
    return bool((os.getenv("DASHSCOPE_API_KEY") or "").strip())
