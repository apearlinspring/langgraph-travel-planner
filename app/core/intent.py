"""
Lightweight travel intent detection.

This module keeps routing decisions deterministic and testable before the
planner model decides how to answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


TravelIntentName = Literal[
    "unknown",
    "requirement_record",
    "destination_query",
    "transport_query",
    "hotel_query",
    "food_query",
    "itinerary_query",
    "map_route_query",
    "agency_plan_query",
    "free_planning_query",
    "pricing_query",
    "risk_query",
    "budget_query",
    "final_report",
    "export_report",
    "progress_check",
]


@dataclass(frozen=True)
class TravelIntent:
    name: TravelIntentName
    confidence: float = 0.0
    preferred_tool: str | None = None
    target_step: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    protect_from_freeform_report: bool = False


_DIRECT_QUERY_KEYWORDS = (
    "查",
    "查询",
    "看看",
    "推荐",
    "真实",
    "具体",
    "候选",
    "方案",
    "有没有",
    "帮我找",
    "直接",
)

_SELECTION_KEYWORDS = (
    "选第",
    "就这",
    "选这个",
    "确认",
    "锁定",
    "记录",
    "定这个",
    "就它",
)

_HOTEL_KEYWORDS = (
    "酒店",
    "住宿",
    "民宿",
    "宾馆",
    "客栈",
    "江景房",
    "景观房",
    "房型",
    "入住",
    "落脚",
    "离地铁",
    "交通方便",
    "安静",
    "亲子房",
    "住哪",
    "住哪里",
    "住的地方",
    "适合住",
)

_TRANSPORT_KEYWORDS = (
    "交通",
    "飞机",
    "航班",
    "机票",
    "机场",
    "高铁",
    "火车",
    "车次",
    "票价",
    "12306",
    "自驾",
    "公交",
    "地铁",
    "怎么去",
    "往返",
)

_FINAL_REPORT_KEYWORDS = (
    "最终报告",
    "旅游报告",
    "旅行报告",
    "旅游规划报告",
    "旅行规划报告",
    "规划报告",
    "完整报告",
    "生成报告",
    "最终方案",
    "完整方案",
    "个性化旅游规划",
    "行程定稿",
    "定稿",
    "不用再问",
    "别再问",
)

_AGENCY_PLAN_KEYWORDS = (
    "省心方案",
    "旅行社方案",
    "旅行社帮我",
    "你们旅行社",
    "按你们的产品",
    "成熟路线",
    "定制游",
    "跟团",
    "成团",
    "一站式",
    "不用我操心",
    "少操心",
    "顾问方案",
    "亲子团",
    "团建",
)

_FREE_PLANNING_KEYWORDS = (
    "自由行",
    "自由规划",
    "自己出去玩",
    "自己玩",
    "不跟团",
    "只要攻略",
    "自己订",
)

_PRICING_KEYWORDS = (
    "报价",
    "费用包含",
    "包含什么",
    "不包含",
    "怎么收费",
    "费用怎么算",
    "预算依据",
    "报价规则",
    "价格依据",
)

_RISK_QUERY_KEYWORDS = (
    "避坑",
    "踩坑",
    "风险",
    "注意事项",
    "注意什么",
    "plan b",
    "Plan B",
    "下雨怎么办",
    "太热怎么办",
    "预约",
    "限流",
)

_EXPORT_REPORT_KEYWORDS = (
    "导出",
    "pdf",
    "PDF",
    "图片",
    "截图",
    "保存",
    "下载",
)

_MAP_ROUTE_KEYWORDS = (
    "地图",
    "路线图",
    "路线地图",
    "景点地图",
    "路线预览",
    "路线可视化",
    "分日路线",
    "沿途景点",
    "day1",
    "day 1",
    "第1天路线",
    "第一天路线",
)

_FOOD_KEYWORDS = ("美食", "餐厅", "吃", "小吃", "夜市", "忌口", "口味")
_BUDGET_KEYWORDS = ("预算", "费用", "花费", "多少钱", "贵", "便宜", "人均")
_ITINERARY_KEYWORDS = ("行程", "怎么玩", "怎么安排", "每天", "第一天", "Day")
_DESTINATION_KEYWORDS = ("景点", "玩法", "攻略", "目的地", "适合吗", "好玩吗", "值得去", "推荐去哪")
_PROGRESS_KEYWORDS = ("现在到哪", "进度", "还缺什么", "收集完了吗", "当前状态")
_REQUIREMENT_RECORD_KEYWORDS = ("整理需求", "记录需求", "开始规划", "开始推荐", "需求完整")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _has_explicit_query_intent(text: str) -> bool:
    return _contains_any(text, _DIRECT_QUERY_KEYWORDS)


def _extract_transport_type(text: str) -> str | None:
    if any(keyword in text for keyword in ("飞机", "航班", "机票", "机场")):
        return "flight"
    if any(keyword in text for keyword in ("高铁", "火车", "车次", "12306")):
        return "train"
    if "自驾" in text:
        return "driving"
    return None


def _looks_like_selection_turn(text: str) -> bool:
    return _contains_any(text, _SELECTION_KEYWORDS)


def detect_travel_intent(
    text: str,
    *,
    current_step: str | None = None,
    state: dict[str, Any] | None = None,
) -> TravelIntent:
    """Detect the user's most likely current travel-planning intent."""

    normalized = (text or "").strip()
    if not normalized:
        return TravelIntent("unknown")

    lower_text = normalized.lower()
    slots: dict[str, Any] = {}
    selection_turn = _looks_like_selection_turn(normalized)

    if _contains_any(lower_text, _EXPORT_REPORT_KEYWORDS):
        return TravelIntent(
            "export_report",
            confidence=0.92,
            target_step="order_generation",
            slots=slots,
            reason="用户表达导出或保存报告",
            protect_from_freeform_report=True,
        )

    if _contains_any(normalized, _FINAL_REPORT_KEYWORDS):
        return TravelIntent(
            "final_report",
            confidence=0.94,
            preferred_tool="generate_order_tool",
            target_step="order_generation",
            slots=slots,
            reason="用户表达生成最终报告/定稿",
            protect_from_freeform_report=True,
        )

    if _contains_any(lower_text, _MAP_ROUTE_KEYWORDS):
        return TravelIntent(
            "map_route_query",
            confidence=0.88,
            target_step="itinerary_generation",
            slots=slots,
            reason="用户关注地图、路线或分日可视化",
        )

    if _contains_any(normalized, _FREE_PLANNING_KEYWORDS):
        return TravelIntent(
            "free_planning_query",
            confidence=0.8,
            target_step=current_step,
            slots=slots,
            reason="用户表达自由行/自助规划意图",
        )

    if _contains_any(normalized, _AGENCY_PLAN_KEYWORDS):
        return TravelIntent(
            "agency_plan_query",
            confidence=0.86,
            preferred_tool="search_agency_product_templates",
            target_step=current_step,
            slots=slots,
            reason="用户表达旅行社省心方案或产品化路线意图",
        )

    if _contains_any(normalized, _PRICING_KEYWORDS):
        return TravelIntent(
            "pricing_query",
            confidence=0.84,
            preferred_tool="search_agency_pricing_rules",
            target_step="budget_summarization",
            slots=slots,
            reason="用户关注报价规则、费用包含或预算依据",
        )

    if _contains_any(normalized, _RISK_QUERY_KEYWORDS):
        return TravelIntent(
            "risk_query",
            confidence=0.82,
            preferred_tool="search_agency_risk_playbook",
            slots=slots,
            reason="用户关注避坑、风险、预约或 Plan B",
        )

    hotel_hit = _contains_any(normalized, _HOTEL_KEYWORDS)
    if (
        hotel_hit
        and not selection_turn
        and (_has_explicit_query_intent(normalized) or current_step != "requirement_collection")
    ):
        return TravelIntent(
            "hotel_query",
            confidence=0.9,
            preferred_tool="query_hotel_options",
            target_step="accommodation_planning",
            slots=slots,
            reason="用户表达住宿/酒店查询意图",
        )

    transport_hit = _contains_any(normalized, _TRANSPORT_KEYWORDS)
    if transport_hit and not selection_turn and (
        _has_explicit_query_intent(normalized)
        or current_step in {"transport_planning", "destination_recommendation"}
    ):
        transport_type = _extract_transport_type(normalized)
        if transport_type:
            slots["transport_type"] = transport_type
        return TravelIntent(
            "transport_query",
            confidence=0.88,
            preferred_tool="query_transport_options",
            target_step="transport_planning",
            slots=slots,
            reason="用户表达交通查询/对比意图",
        )

    if _contains_any(normalized, _BUDGET_KEYWORDS):
        return TravelIntent(
            "budget_query",
            confidence=0.82,
            target_step="budget_summarization",
            slots=slots,
            reason="用户关注预算或费用",
        )

    if _contains_any(normalized, _FOOD_KEYWORDS):
        return TravelIntent(
            "food_query",
            confidence=0.82,
            target_step="food_planning",
            slots=slots,
            reason="用户关注餐饮/美食",
        )

    if _contains_any(normalized, _ITINERARY_KEYWORDS):
        return TravelIntent(
            "itinerary_query",
            confidence=0.78,
            target_step="itinerary_generation",
            slots=slots,
            reason="用户关注每日行程安排",
        )

    if _contains_any(normalized, _PROGRESS_KEYWORDS):
        return TravelIntent(
            "progress_check",
            confidence=0.8,
            preferred_tool="check_current_progress",
            slots=slots,
            reason="用户询问当前规划进度",
        )

    if _contains_any(normalized, _REQUIREMENT_RECORD_KEYWORDS) and not selection_turn:
        return TravelIntent(
            "requirement_record",
            confidence=0.78,
            preferred_tool="record_requirement_tool",
            target_step="requirement_collection",
            slots=slots,
            reason="用户要求整理或记录需求",
        )

    if _contains_any(normalized, _DESTINATION_KEYWORDS):
        return TravelIntent(
            "destination_query",
            confidence=0.72,
            preferred_tool="query_destination_info",
            target_step="destination_recommendation",
            slots=slots,
            reason="用户询问目的地/景点/玩法",
        )

    if re.search(r"(从|出发).{0,18}(去|到).{1,18}", normalized):
        return TravelIntent(
            "requirement_record",
            confidence=0.62,
            target_step="requirement_collection",
            slots=slots,
            reason="用户提供出发地到目的地的路线需求",
        )

    return TravelIntent("unknown", reason="未命中明确旅行意图")
