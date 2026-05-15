"""Planning-mode inference shared by agency rules and report generation."""
from __future__ import annotations

import re
from typing import Any

from app.agency.models import PlanningMode


AGENCY_MODE_KEYWORDS = (
    "旅行社",
    "旅行顾问",
    "顾问方案",
    "旅行社方案",
    "旅行社顾问方案",
    "省心方案",
    "省心套餐",
    "成熟路线",
    "定制游",
    "小包团",
    "私家团",
    "跟团",
    "成团",
    "一站式",
    "托管",
    "包办",
    "管家式",
    "不要我操心",
    "不用我操心",
    "不想自己操心",
    "不想做攻略",
    "懒得做攻略",
    "旅行社产品",
    "你们的产品",
    "产品路线",
)

AGENCY_QUOTE_SERVICE_KEYWORDS = (
    "报价",
    "报价单",
    "报价规则",
    "合同",
    "合同规则",
    "服务标准",
    "服务流程",
    "费用包含",
    "费用不含",
    "单房差",
    "儿童价",
    "成人价",
    "SOP",
    "sop",
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

AGENCY_TRANSPORT_CONTEXT_KEYWORDS = ("交通", "高铁", "航班", "飞机", "火车", "车次", "自驾")
AGENCY_LODGING_CONTEXT_KEYWORDS = ("酒店", "住宿", "民宿", "宾馆", "客栈")
AGENCY_RISK_CONTEXT_KEYWORDS = ("天气", "下雨", "雨季", "台风", "Plan B", "plan b", "风险")
AGENCY_CARE_CONTEXT_KEYWORDS = ("老人", "父母", "长辈", "银发", "走不动")

FREE_MODE_KEYWORDS = (
    "自由行",
    "自由规划",
    "自助游",
    "DIY",
    "diy",
    "自己玩",
    "自己出去玩",
    "不跟团",
    "不要跟团",
    "不成团",
    "自己订",
    "自己安排",
    "只要攻略",
    "只要建议",
    "不要旅行社",
    "不需要旅行社",
    "别推产品",
    "不要推销",
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _agency_rejected(text: str) -> bool:
    return bool(
        re.search(
            r"(不需要|无需|拒绝|(?<!要)不要|不想)[^，。；;,.!?！？]{0,10}"
            r"(旅行社|顾问方案|产品|推销|销售|省心方案|省心套餐)",
            text,
        )
        or re.search(r"别.{0,6}(推销|销售|硬推|推产品|推荐产品)", text)
    )


def _free_rejected(text: str) -> bool:
    return bool(
        re.search(
            r"(不需要|无需|拒绝|(?<!要)不要|不想)[^，。；;,.!?！？]{0,10}"
            r"(自由行|自由规划|自助游|自己玩|自己订|diy|DIY)",
            text,
        )
    )


def has_explicit_agency_plan_signal(text: str) -> bool:
    """Return true only for explicit agency-plan or productized service signals."""

    normalized = (text or "").strip()
    if not normalized or _agency_rejected(normalized):
        return False
    if _contains_any(normalized, AGENCY_MODE_KEYWORDS):
        return True
    if re.search(r"省心.{0,4}(安排|规划)", normalized):
        has_transport = _contains_any(normalized, AGENCY_TRANSPORT_CONTEXT_KEYWORDS)
        has_lodging = _contains_any(normalized, AGENCY_LODGING_CONTEXT_KEYWORDS)
        has_risk = _contains_any(normalized, AGENCY_RISK_CONTEXT_KEYWORDS)
        has_care = _contains_any(normalized, AGENCY_CARE_CONTEXT_KEYWORDS)
        if has_transport and has_lodging and (has_risk or has_care):
            return True
        if has_risk and has_care and (has_transport or has_lodging):
            return True
        return bool(
            re.search(r"省心.{0,4}(安排|规划).{0,24}(全程|一站式|托管|包办)", normalized)
        )
    return bool(
        re.search(r"省心.{0,4}(方案|套餐|托管|包办)", normalized)
        or re.search(r"(按|用).{0,6}(旅行社|顾问).{0,6}(方案|标准|流程)", normalized)
    )


def has_explicit_agency_signal(text: str) -> bool:
    """Return true for agency-plan, quote, contract, or service-standard signals."""

    normalized = (text or "").strip()
    if not normalized or _agency_rejected(normalized):
        return False
    return has_explicit_agency_plan_signal(normalized) or _contains_any(
        normalized,
        AGENCY_QUOTE_SERVICE_KEYWORDS,
    )


def has_explicit_free_signal(text: str) -> bool:
    """Return true when the user explicitly asks for free planning or rejects agency service."""

    normalized = (text or "").strip()
    if not normalized:
        return False
    return _agency_rejected(normalized) or (
        _contains_any(normalized, FREE_MODE_KEYWORDS) and not _free_rejected(normalized)
    )


def _has_agency_fallback_signal(text: str) -> bool:
    return (
        any(keyword in text for keyword in ("兜底方案", "兜底安排"))
        and any(keyword in text for keyword in AGENCY_FALLBACK_CONTEXT_KEYWORDS)
        and has_explicit_agency_plan_signal(text)
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
    free_signal = has_explicit_free_signal(text)
    agency_plan_signal = has_explicit_agency_plan_signal(text)
    agency_quote_service_signal = _contains_any(text, AGENCY_QUOTE_SERVICE_KEYWORDS)
    if free_signal and not agency_plan_signal:
        return "free_planning"
    if _has_agency_fallback_signal(text):
        return "agency_plan"
    if agency_plan_signal or agency_quote_service_signal:
        return "agency_plan"
    return "free_planning"
