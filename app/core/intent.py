"""
Lightweight travel intent detection.

This module keeps routing decisions deterministic and testable before the
planner model decides how to answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agency.planning_mode import has_explicit_agency_signal, has_explicit_free_signal


TravelPlanningMode = Literal["free_planning", "agency_plan"]

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
    "product_candidate_query",
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
    planning_mode: TravelPlanningMode | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    protect_from_freeform_report: bool = False


@dataclass(frozen=True)
class PlanningModeDecision:
    mode: TravelPlanningMode | None = None
    confidence: float = 0.0
    source: Literal["latest_user", "state", "none"] = "none"
    reason: str = ""
    confirmed: bool = False
    needs_confirmation: bool = False


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
    "行程定稿",
    "定稿",
    "不用再问",
    "别再问",
)

_AGENCY_PLAN_KEYWORDS = (
    "省心方案",
    "省心套餐",
    "旅行社方案",
    "旅行社顾问方案",
    "旅行社帮我",
    "你们旅行社",
    "按你们的产品",
    "旅行社产品",
    "产品路线",
    "成熟路线",
    "定制游",
    "跟团",
    "成团",
    "小包团",
    "私家团",
    "一站式",
    "不用我操心",
    "不想自己操心",
    "不想做攻略",
    "懒得做攻略",
    "托管",
    "包办",
    "管家式",
    "行程管家",
    "顾问方案",
    "亲子团",
    "银发团",
)

_AGENCY_QUOTE_SERVICE_KEYWORDS = (
    "报价",
    "报价单",
    "报价规则",
    "合同",
    "合同规则",
    "服务标准",
    "服务流程",
    "费用包含",
    "费用不含",
    "儿童价",
    "成人价",
    "单房差",
    "SOP",
    "sop",
)

_PRODUCT_SOFT_MATCH_DESTINATIONS = (
    "新疆",
    "西藏",
    "云南",
    "西安",
    "厦门",
    "桂林",
    "苏州",
    "长沙",
    "拉萨",
    "乌鲁木齐",
    "大理",
    "丽江",
)

_PRODUCT_SOFT_MATCH_KEYWORDS = (
    "想去",
    "计划去",
    "去",
    "路线",
    "行程",
    "省心",
    "预算",
    "亲子",
    "情侣",
    "老人",
    "小团",
    "包车",
    "成熟",
    "推荐",
)

_PRODUCT_SOFT_MATCH_BLOCKERS = (
    "天气",
    "气温",
    "攻略",
    "景点",
    "好玩吗",
    "值得去",
    "适合吗",
)

_FREE_PLANNING_KEYWORDS = (
    "自由行",
    "自由规划",
    "个性化旅游规划",
    "个性化规划",
    "自助游",
    "自己出去玩",
    "自己玩",
    "不跟团",
    "不要跟团",
    "只要攻略",
    "只要建议",
    "自己订",
    "自己安排",
    "不要旅行社",
    "不需要旅行社",
    "别推产品",
    "不要推销",
    "diy",
)

_PRICING_KEYWORDS = (
    "报价",
    "报价单",
    "费用包含",
    "费用不含",
    "包含什么",
    "不包含",
    "怎么收费",
    "费用怎么算",
    "预算依据",
    "报价规则",
    "价格依据",
    "儿童价",
    "成人价",
    "单房差",
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
_DESTINATION_KEYWORDS = (
    "景点",
    "玩法",
    "攻略",
    "目的地",
    "适合吗",
    "好玩吗",
    "值得去",
    "推荐去哪",
    "天气",
    "气温",
    "雨季",
    "下雨",
    "暴雨",
    "台风",
)
_PROGRESS_KEYWORDS = ("现在到哪", "进度", "还缺什么", "收集完了吗", "当前状态")
_REQUIREMENT_RECORD_KEYWORDS = ("整理需求", "记录需求", "开始规划", "开始推荐", "需求完整")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword in text)


_ROUTE_TIME_WORDS = (
    "今天",
    "明天",
    "后天",
    "大后天",
    "周一",
    "周二",
    "周三",
    "周四",
    "周五",
    "周六",
    "周日",
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
    "下周",
    "这周",
    "本周",
)


def _has_compact_route_pair_hint(text: str) -> bool:
    for match in re.finditer(
        r"([\u4e00-\u9fff]{2,12})(?:出发)?(?:去|到|飞往)([\u4e00-\u9fff]{2,16})",
        text,
    ):
        origin, destination = match.group(1), match.group(2)
        segment = f"{origin}{destination}"
        if any(word in segment for word in _ROUTE_TIME_WORDS):
            continue
        if any(word in segment for word in ("预算", "每人", "每位", "人数", "天数", "行程")):
            continue
        return True
    return False


def _has_route_requirement_hint(text: str) -> bool:
    return bool(
        re.search(r"从.{1,12}(出发)?(去|到|飞|开车去|坐车去).{1,16}", text)
        or re.search(r".{1,12}(去|到).{1,16}(玩|旅行|旅游|出差|团建)", text)
        or _has_compact_route_pair_hint(text)
    )


def _has_date_or_duration_hint(text: str) -> bool:
    date_hint = bool(
        re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", text)
        or re.search(r"\d{1,2}\s*月\s*\d{0,2}\s*(日|号)?", text)
        or re.search(r"(今天|明天|后天|大后天|本周|这周|下周|周末|端午|五一|国庆|春节|暑假|寒假)", text)
    )
    duration_hint = bool(re.search(r"\d+\s*天(?:\s*\d+\s*晚)?", text))
    return date_hint or duration_hint


def _has_people_hint(text: str) -> bool:
    return bool(
        re.search(r"\d+\s*(人|位|个成人|成人|大人|大|小)", text)
        or re.search(r"(\d+\s*大\s*\d+\s*小|一家[三四五六]口|父母|老人|孩子)", text)
    )


def _has_budget_requirement_hint(text: str) -> bool:
    return bool(
        re.search(r"(预算|人均|每人|每位|总预算).{0,12}\d+", text)
        or re.search(r"\d+\s*(元|块|千|万)", text)
    )


def _needs_first_turn_mode_confirmation(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if has_explicit_agency_signal(normalized) or has_explicit_free_signal(normalized):
        return False
    if _keyword_score(normalized, _AGENCY_PLAN_KEYWORDS + _FREE_PLANNING_KEYWORDS):
        return False
    return (
        _has_route_requirement_hint(normalized)
        and _has_date_or_duration_hint(normalized)
        and _has_people_hint(normalized)
        and _has_budget_requirement_hint(normalized)
    )


def _state_planning_mode(state: dict[str, Any] | None) -> TravelPlanningMode | None:
    if not state:
        return None

    confirmed = _state_planning_mode_confirmed(state)
    raw_mode = state.get("active_workflow")
    if raw_mode == "agency_plan":
        return raw_mode
    if raw_mode == "free_planning" and confirmed:
        return raw_mode

    raw_mode = state.get("planning_mode")
    if raw_mode in ("free_planning", "agency_plan"):
        return raw_mode

    requirement = state.get("user_requirement")
    if isinstance(requirement, dict):
        raw_mode = requirement.get("planning_mode")
        if raw_mode in ("free_planning", "agency_plan"):
            return raw_mode

    return None


def _state_planning_mode_reason(state: dict[str, Any] | None) -> str:
    if not state:
        return ""
    reason = state.get("planning_mode_reason")
    if reason:
        return str(reason)
    requirement = state.get("user_requirement")
    if isinstance(requirement, dict) and requirement.get("planning_mode_reason"):
        return str(requirement["planning_mode_reason"])
    return "沿用已记录的规划模式"


def _state_planning_mode_confirmed(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    if bool(state.get("planning_mode_confirmed")):
        return True
    requirement = state.get("user_requirement")
    if isinstance(requirement, dict):
        return bool(requirement.get("planning_mode_confirmed"))
    return False


def _detect_planning_mode_from_text(text: str) -> PlanningModeDecision:
    normalized = (text or "").strip()
    if not normalized:
        return PlanningModeDecision()

    lower_text = normalized.lower()
    explicit_agency = has_explicit_agency_signal(normalized)
    explicit_free = has_explicit_free_signal(normalized)
    agency_plan_score = _keyword_score(normalized, _AGENCY_PLAN_KEYWORDS)
    agency_quote_service_score = _keyword_score(normalized, _AGENCY_QUOTE_SERVICE_KEYWORDS)
    agency_score = agency_plan_score + agency_quote_service_score
    free_score = _keyword_score(normalized, _FREE_PLANNING_KEYWORDS)
    if "diy" in lower_text:
        free_score += 1
    if explicit_agency and agency_score == 0:
        agency_score = 1
    if explicit_free and free_score == 0:
        free_score = 1

    agency_rejected = bool(
        re.search(
            r"(不需要|无需|拒绝|(?<!要)不要|不想)[^，。；;,.!?！？]{0,8}"
            r"(旅行社|顾问方案|产品|推销|销售|省心方案)",
            normalized,
        )
        or re.search(r"别.{0,6}(推销|销售|硬推|推产品|推荐产品)", normalized)
    )
    free_rejected = bool(
        re.search(
            r"(不需要|无需|拒绝|(?<!要)不要|不想)[^，。；;,.!?！？]{0,8}"
            r"(自由行|自由规划|自助游|自己玩|自己订|diy)",
            lower_text,
        )
    )
    self_service_rejected = bool(
        re.search(r"(不想|不愿意|懒得|没空).{0,10}(自己|我自己).{0,8}(做攻略|订|安排|操心|查)", normalized)
    )
    no_group_but_custom = bool(
        re.search(r"(不|不要|别).{0,4}(跟团|大团|成团).{0,20}(定制|小包团|私家团|旅行社|顾问|省心)", normalized)
    )
    uncertain_mode = any(keyword in normalized for keyword in ("不确定", "要不要", "纠结", "还没想好", "不好说"))

    if agency_rejected:
        agency_score = max(0, agency_score - 3)
        free_score += 3
    if free_rejected or self_service_rejected or (no_group_but_custom and not agency_rejected):
        free_score = max(0, free_score - 2)
        agency_score += 3

    if agency_score == 0 and free_score == 0:
        if _needs_first_turn_mode_confirmation(normalized):
            return PlanningModeDecision(
                confidence=0.68,
                source="latest_user",
                reason="用户已给出较完整旅行需求，但尚未选择省心方案或个性化旅游规划",
                confirmed=False,
                needs_confirmation=True,
            )
        return PlanningModeDecision()

    if explicit_free and agency_plan_score == 0 and agency_quote_service_score > 0:
        return PlanningModeDecision(
            "free_planning",
            confidence=0.82,
            source="latest_user",
            reason="用户明确自由规划，同时询问预算或费用边界，保持自由规划并仅补充费用依据",
            confirmed=True,
        )

    if agency_score and free_score and abs(agency_score - free_score) <= 1:
        if uncertain_mode:
            return PlanningModeDecision(
                confidence=0.55,
                source="latest_user",
                reason="用户同时出现自由规划和省心托付信号，需要先确认规划模式",
                confirmed=False,
                needs_confirmation=True,
            )
        if any(keyword in normalized for keyword in ("旅行社", "顾问", "定制", "托管", "包办")) and not agency_rejected:
            return PlanningModeDecision(
                "agency_plan",
                confidence=0.72,
                source="latest_user",
                reason="用户同时表达自由度和顾问托付诉求，倾向旅行社顾问方案",
                confirmed=False,
            )
        return PlanningModeDecision(
            confidence=0.55,
            source="latest_user",
            reason="用户同时出现自由规划和省心托付信号，需要先确认规划模式",
            confirmed=False,
            needs_confirmation=True,
        )

    if agency_score > free_score:
        return PlanningModeDecision(
            "agency_plan",
            confidence=min(0.95, 0.72 + 0.04 * (agency_score - free_score)),
            source="latest_user",
            reason="用户表达省心、成熟路线或旅行社顾问方案倾向",
            confirmed=True,
        )

    return PlanningModeDecision(
        "free_planning",
        confidence=min(0.95, 0.7 + 0.04 * (free_score - agency_score)),
        source="latest_user",
        reason="用户表达自由行、自助规划或拒绝旅行社产品倾向",
        confirmed=True,
    )


def _has_product_candidate_signal(text: str, state: dict[str, Any] | None = None) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if has_explicit_free_signal(normalized) or _state_planning_mode(state) == "free_planning":
        return False
    target_destinations = [
        destination
        for destination in _PRODUCT_SOFT_MATCH_DESTINATIONS
        if (
            re.search(rf"(想去|计划去|去|到|目的地).{{0,8}}{re.escape(destination)}", normalized)
            or re.search(
                rf"{re.escape(destination)}.{{0,10}}(路线|行程|省心|产品|候选|成熟|小团|包车|预算|亲子|情侣)",
                normalized,
            )
        )
        and not re.search(rf"从{re.escape(destination)}.{{0,6}}(出发|走)", normalized)
    ]
    if not target_destinations:
        return False
    has_soft_signal = any(keyword in normalized for keyword in _PRODUCT_SOFT_MATCH_KEYWORDS)
    if not has_soft_signal:
        return False
    has_blocker = any(keyword in normalized for keyword in _PRODUCT_SOFT_MATCH_BLOCKERS)
    has_productish_signal = any(
        keyword in normalized
        for keyword in ("省心", "路线", "行程", "产品", "候选", "成熟", "小团", "包车", "预算")
    )
    return has_productish_signal or not has_blocker


def resolve_planning_mode(
    text: str,
    *,
    state: dict[str, Any] | None = None,
    intent: TravelIntent | None = None,
) -> PlanningModeDecision:
    """Resolve the effective planning mode for this turn."""

    if intent and intent.planning_mode:
        return PlanningModeDecision(
            mode=intent.planning_mode,
            confidence=max(intent.confidence, 0.72),
            source="latest_user",
            reason=intent.reason or "用户本轮明确表达规划模式",
            confirmed=True,
        )

    text_decision = _detect_planning_mode_from_text(text)
    if text_decision.mode or text_decision.needs_confirmation:
        return text_decision

    state_mode = _state_planning_mode(state)
    if state_mode:
        return PlanningModeDecision(
            mode=state_mode,
            confidence=0.78,
            source="state",
            reason=_state_planning_mode_reason(state),
            confirmed=_state_planning_mode_confirmed(state),
        )

    return PlanningModeDecision()


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
    planning_decision = _detect_planning_mode_from_text(normalized)

    if _contains_any(lower_text, _EXPORT_REPORT_KEYWORDS):
        return TravelIntent(
            "export_report",
            confidence=0.92,
            target_step="order_generation",
            planning_mode=planning_decision.mode,
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
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户表达生成最终报告/定稿",
            protect_from_freeform_report=True,
        )

    if _contains_any(lower_text, _MAP_ROUTE_KEYWORDS):
        return TravelIntent(
            "map_route_query",
            confidence=0.88,
            target_step="itinerary_generation",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户关注地图、路线或分日可视化",
        )

    if _contains_any(normalized, _PRICING_KEYWORDS):
        return TravelIntent(
            "pricing_query",
            confidence=0.84,
            preferred_tool="search_agency_pricing_rules",
            target_step="budget_summarization",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户关注报价规则、费用包含或预算依据",
        )

    if _contains_any(normalized, _RISK_QUERY_KEYWORDS):
        return TravelIntent(
            "risk_query",
            confidence=0.82,
            preferred_tool="search_agency_risk_playbook",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户关注避坑、风险、预约或 Plan B",
        )

    hotel_hit = _contains_any(normalized, _HOTEL_KEYWORDS)
    if (
        hotel_hit
        and current_step == "accommodation_planning"
        and any(keyword in normalized for keyword in ("真实", "锁价", "待核验", "查不到", "具体酒店", "酒店候选"))
    ):
        return TravelIntent(
            "hotel_query",
            confidence=0.9,
            preferred_tool="query_hotel_options",
            target_step="accommodation_planning",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="住宿阶段用户要求真实酒店、锁价核验或兜底酒店方案",
        )

    if planning_decision.mode == "agency_plan":
        return TravelIntent(
            "agency_plan_query",
            confidence=max(0.86, planning_decision.confidence),
            preferred_tool="search_agency_product_templates",
            target_step=current_step,
            planning_mode="agency_plan",
            slots=slots,
            reason=planning_decision.reason or "用户表达旅行社省心方案或产品化路线意图",
        )

    if _has_product_candidate_signal(normalized, state):
        return TravelIntent(
            "product_candidate_query",
            confidence=0.76,
            preferred_tool="search_agency_product_templates",
            target_step=current_step,
            planning_mode=None,
            slots=slots,
            reason="用户未拒绝产品化方向，目的地或风格与成熟路线样板可能匹配",
        )

    if planning_decision.mode == "free_planning":
        return TravelIntent(
            "free_planning_query",
            confidence=max(0.8, planning_decision.confidence),
            target_step=current_step,
            planning_mode="free_planning",
            slots=slots,
            reason=planning_decision.reason or "用户表达自由行/自助规划意图",
        )

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
            planning_mode=planning_decision.mode,
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
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户表达交通查询/对比意图",
        )

    if _contains_any(normalized, _BUDGET_KEYWORDS):
        return TravelIntent(
            "budget_query",
            confidence=0.82,
            target_step="budget_summarization",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户关注预算或费用",
        )

    if _contains_any(normalized, _FOOD_KEYWORDS):
        return TravelIntent(
            "food_query",
            confidence=0.82,
            target_step="food_planning",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户关注餐饮/美食",
        )

    if _contains_any(normalized, _ITINERARY_KEYWORDS):
        return TravelIntent(
            "itinerary_query",
            confidence=0.78,
            target_step="itinerary_generation",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户关注每日行程安排",
        )

    if _contains_any(normalized, _PROGRESS_KEYWORDS):
        return TravelIntent(
            "progress_check",
            confidence=0.8,
            preferred_tool="check_current_progress",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户询问当前规划进度",
        )

    if _contains_any(normalized, _REQUIREMENT_RECORD_KEYWORDS) and not selection_turn:
        return TravelIntent(
            "requirement_record",
            confidence=0.78,
            preferred_tool="record_requirement_tool",
            target_step="requirement_collection",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户要求整理或记录需求",
        )

    if _contains_any(normalized, _DESTINATION_KEYWORDS):
        return TravelIntent(
            "destination_query",
            confidence=0.72,
            preferred_tool="query_destination_info",
            target_step="destination_recommendation",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户询问目的地/景点/玩法",
        )

    if re.search(r"(从|出发).{0,18}(去|到).{1,18}", normalized):
        return TravelIntent(
            "requirement_record",
            confidence=0.62,
            target_step="requirement_collection",
            planning_mode=planning_decision.mode,
            slots=slots,
            reason="用户提供出发地到目的地的路线需求",
        )

    return TravelIntent("unknown", reason="未命中明确旅行意图")
