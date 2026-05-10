"""
Context budget helpers for prompt construction.

The numbers here are intentionally approximate. They give the middleware a
stable, explainable policy for when to summarize or trim, without depending on a
provider-specific tokenizer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ContextLayerName = Literal[
    "system_prompt",
    "short_term_state",
    "recent_messages",
    "conversation_summary",
    "long_term_memory",
    "evidence_bundle",
]


@dataclass(frozen=True)
class ContextBudget:
    """Token budget allocation for the planner prompt."""

    max_prompt_tokens: int = 12000
    system_prompt_tokens: int = 5200
    short_term_state_tokens: int = 1800
    recent_message_tokens: int = 2800
    conversation_summary_tokens: int = 900
    long_term_memory_tokens: int = 700
    evidence_bundle_tokens: int = 600
    max_messages_without_summary: int = 18
    max_recent_human_turns: int = 6
    final_stage_recent_human_turns: int = 2
    max_message_chars: int = 1600
    max_tool_message_chars: int = 900


@dataclass(frozen=True)
class ContextBudgetDecision:
    """Explain why context was summarized or left untouched."""

    should_summarize: bool
    estimated_tokens: int
    message_count: int
    reason: str


DEFAULT_CONTEXT_BUDGET = ContextBudget()


def estimate_tokens(text: Any) -> int:
    """Return a conservative token estimate for mixed Chinese and English text."""
    if text is None:
        return 0
    value = str(text)
    if not value:
        return 0

    cjk_chars = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    other_chars = len(value) - cjk_chars
    # Chinese text often tokenizes close to one character per token, while
    # English usually packs several characters into one token.
    return cjk_chars + max(1, other_chars // 4)


def estimate_messages_tokens(messages: list[Any]) -> int:
    return sum(estimate_tokens(_message_content(message)) for message in messages or [])


def decide_context_budget(
    messages: list[Any],
    *,
    budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
    current_step: str | None = None,
    previous_step: str | None = None,
) -> ContextBudgetDecision:
    """Decide whether the current model call needs summarization."""
    message_count = len(messages or [])
    estimated_tokens = estimate_messages_tokens(messages or [])

    if current_step and previous_step and current_step != previous_step:
        return ContextBudgetDecision(
            should_summarize=True,
            estimated_tokens=estimated_tokens,
            message_count=message_count,
            reason=f"规划阶段从 {previous_step} 进入 {current_step}，压缩上一阶段对话",
        )

    if message_count > budget.max_messages_without_summary:
        return ContextBudgetDecision(
            should_summarize=True,
            estimated_tokens=estimated_tokens,
            message_count=message_count,
            reason=(
                f"消息数 {message_count} 超过阈值 "
                f"{budget.max_messages_without_summary}"
            ),
        )

    if estimated_tokens > budget.recent_message_tokens:
        return ContextBudgetDecision(
            should_summarize=True,
            estimated_tokens=estimated_tokens,
            message_count=message_count,
            reason=(
                f"最近消息估算 {estimated_tokens} token 超过预算 "
                f"{budget.recent_message_tokens}"
            ),
        )

    return ContextBudgetDecision(
        should_summarize=False,
        estimated_tokens=estimated_tokens,
        message_count=message_count,
        reason="当前上下文在预算内",
    )


def trim_text_to_token_budget(text: str, token_budget: int) -> str:
    """Trim text to a rough token budget while preserving a clear suffix marker."""
    if estimate_tokens(text) <= token_budget:
        return text
    if token_budget <= 0:
        return ""

    # Mixed-language approximation: two chars per budget token leaves room for
    # Chinese-heavy inputs while not cutting English too aggressively.
    max_chars = max(80, token_budget * 2)
    trimmed = text[:max_chars].rstrip()
    return f"{trimmed}\n...（已按上下文预算截断）"


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content or "")
