"""Planning-mode inference shared by agency rules and report generation."""
from __future__ import annotations

from typing import Any

from app.agency.models import PlanningMode


AGENCY_MODE_KEYWORDS = (
    "省心",
    "旅行社",
    "成熟路线",
    "定制游",
    "跟团",
    "成团",
    "团建",
    "研学",
    "亲子",
    "银发",
    "老人",
    "长辈",
    "不要我操心",
    "少操心",
    "你帮我安排",
)

AGENCY_FALLBACK_CONTEXT_KEYWORDS = (
    "酒店",
    "住宿",
    "民宿",
    "宾馆",
    "客栈",
    "房型",
    "江景房",
    "景观房",
    "住",
)

FREE_MODE_KEYWORDS = (
    "自由行",
    "自由规划",
    "自己玩",
    "自己出去玩",
    "不跟团",
    "自己订",
    "只要攻略",
)


def _has_agency_fallback_signal(text: str) -> bool:
    return (
        any(keyword in text for keyword in ("兜底方案", "兜底安排"))
        and any(keyword in text for keyword in AGENCY_FALLBACK_CONTEXT_KEYWORDS)
    )


def _recent_human_text(state: dict[str, Any] | None) -> str:
    if not state:
        return ""

    texts: list[str] = []
    for message in (state.get("messages") or [])[-8:]:
        content = None
        if isinstance(message, dict):
            role = message.get("role") or message.get("type")
            if role in {"user", "human"}:
                content = message.get("content")
        elif getattr(message, "type", None) == "human" or getattr(message, "role", None) == "user":
            content = getattr(message, "content", None)

        if content:
            texts.append(content if isinstance(content, str) else str(content))
    return "\n".join(texts)


def requirement_text(requirement: dict[str, Any], state: dict[str, Any] | None = None) -> str:
    return " ".join(
        item
        for item in [
            str(requirement.get("special_needs") or ""),
            str(requirement.get("destination") or ""),
            " ".join(str(style) for style in requirement.get("travel_styles") or []),
            _recent_human_text(state),
        ]
        if item
    )


def infer_planning_mode(
    requirement: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> PlanningMode:
    """Infer free-planning vs agency-plan mode without creating sales promises."""

    explicit_mode = state.get("planning_mode") if state else None
    if explicit_mode in {"free_planning", "agency_plan"}:
        return explicit_mode

    text = requirement_text(requirement, state)
    if any(keyword in text for keyword in FREE_MODE_KEYWORDS):
        return "free_planning"
    if _has_agency_fallback_signal(text):
        return "agency_plan"
    if any(keyword in text for keyword in AGENCY_MODE_KEYWORDS):
        return "agency_plan"
    return "free_planning"
