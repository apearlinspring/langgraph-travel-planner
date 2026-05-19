"""
State transition tools for the travel-planning workflow.
"""
from datetime import date, datetime, timedelta
from math import ceil
import re
import time
from typing import Any, Optional
from uuid import uuid4

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agency import product_rules as agency_product_rules
from app.agency.planning_mode import (
    has_explicit_agency_plan_signal,
    has_explicit_agency_signal,
    has_explicit_free_signal,
)
from app.agency.pricing_rules import (
    budget_confidence_payload,
    build_adjustment_options,
    build_budget_line_item,
    build_budget_quality_notes as build_agency_budget_quality_notes,
    build_budget_summary_lines,
    build_quote_policy,
    format_budget_assumptions,
    format_budget_breakdown,
    format_budget_confidence,
    format_budget_fit,
    format_budget_verification_items,
    safe_per_person,
)
from app.agency.product_rules import (
    build_agency_context,
    build_light_product,
    format_agency_context_lines,
)
from app.agency.risk_rules import build_report_risk_lines
from app.core.approval import approval_state_update, mark_sensitive_action
from app.core.state import TravelState, UserRequirement
from app.core.workflow import (
    FINAL_PLANNING_STEP,
    INITIAL_PLANNING_STEP,
    PLANNING_STEPS as WORKFLOW_STEPS,
    RollbackTargetStep,
    STEP_LABELS as WORKFLOW_STEP_LABELS,
    STEP_STATE_FIELDS as WORKFLOW_STEP_STATE_FIELDS,
)
from app.journey.visual_planner import JOURNEY_PLAN_VERSION, validate_journey_plan
from app.reports import (
    build_report_bundle,
    build_report_evidence_bundle,
    build_report_tool_audit_summary,
    build_travel_report_data,
    format_report_duration,
    format_report_people,
    format_report_route_label,
)
from app.reports.route_builder import (
    RouteBuilderServices,
    build_day_route_summary,
    build_placeholder_itinerary_day,
    build_route_summaries,
    collect_report_route_candidates,
    dedupe_route_points,
    ensure_itinerary_day_count,
    enrich_itinerary_day_for_report,
    fallback_report_route_points_for_day,
    format_report_route_points,
    get_expected_travel_days,
    is_pending_route_point,
    route_points_have_specific_visual_node,
)
from app.tools.scenic_ticket_provider import (
    SCENIC_TICKET_COLLECTION_DATE,
    find_scenic_ticket_candidates,
)
from app.utils.date_normalization import normalize_travel_date
from app.utils.logger import app_logger


TRANSPORT_LABELS = {
    "flight": "航班",
    "train": "高铁",
    "driving": "自驾",
}

TRANSPORT_ALIASES = {
    "飞机": "flight",
    "航班": "flight",
    "机票": "flight",
    "高铁": "train",
    "动车": "train",
    "火车": "train",
    "铁路": "train",
    "自驾": "driving",
    "开车": "driving",
    "驾车": "driving",
}

ACCOMMODATION_LABELS = {
    "star_hotel": "星级酒店",
    "economy_hotel": "经济酒店",
    "hostel": "特色民宿",
    "youth_hostel": "青年旅舍",
}

ACCOMMODATION_ALIASES = {
    "酒店": "star_hotel",
    "星级": "star_hotel",
    "星级酒店": "star_hotel",
    "中高档酒店": "star_hotel",
    "高档酒店": "star_hotel",
    "舒适酒店": "star_hotel",
    "舒适型": "star_hotel",
    "舒适型酒店": "star_hotel",
    "舒适住宿": "star_hotel",
    "中档酒店": "star_hotel",
    "中端酒店": "star_hotel",
    "经济酒店": "economy_hotel",
    "快捷酒店": "economy_hotel",
    "经济型酒店": "economy_hotel",
    "民宿": "hostel",
    "特色民宿": "hostel",
    "客栈": "hostel",
    "青年旅舍": "youth_hostel",
    "青旅": "youth_hostel",
}
ACCOMMODATION_STATE_TYPE_ALIASES = {
    "comfort_hotel": "star_hotel",
    "comfortable_hotel": "star_hotel",
    "business_hotel": "star_hotel",
    "midscale_hotel": "star_hotel",
    "upscale_hotel": "star_hotel",
    "budget_hotel": "economy_hotel",
    "hotel": "star_hotel",
    **ACCOMMODATION_ALIASES,
}

FOOD_LABELS = {
    "specialty": "特色美食",
    "chain": "连锁快餐",
    "local": "本地小吃",
}

FOOD_ALIASES = {
    "特色美食": "specialty",
    "特色餐厅": "specialty",
    "特色餐厅/名店": "specialty",
    "名店": "specialty",
    "餐厅打卡": "specialty",
    "打卡特色餐厅": "specialty",
    "本地小吃": "local",
    "本地小吃/夜市": "local",
    "本地特色": "local",
    "当地特色": "local",
    "夜市": "local",
    "小吃": "local",
    "小吃扫街": "local",
    "扫街小吃": "local",
    "连锁": "chain",
    "连锁快餐": "chain",
    "连锁/商场": "chain",
    "商场": "chain",
    "省心": "chain",
}

PLANNING_MODE_LABELS = {
    "free_planning": "自由规划",
    "agency_plan": "旅行社顾问方案",
}

PLANNING_MODE_ALIASES = {
    "free_planning": "free_planning",
    "free": "free_planning",
    "自由规划": "free_planning",
    "自由行": "free_planning",
    "自助游": "free_planning",
    "自己订": "free_planning",
    "agency_plan": "agency_plan",
    "agency": "agency_plan",
    "旅行社": "agency_plan",
    "旅行社方案": "agency_plan",
    "旅行社顾问方案": "agency_plan",
    "省心方案": "agency_plan",
    "定制游": "agency_plan",
    "小包团": "agency_plan",
    "私家团": "agency_plan",
}

PENDING_REQUIREMENT_VALUES = {
    "",
    "待定",
    "待确认",
    "未确认",
    "不确定",
    "未知",
    "待核验",
    "待核实",
    "日期",
    "日期待确认",
    "出发日期",
    "出发日期待确认",
    "出发地",
    "出发地待确认",
    "unknown",
    "none",
    "null",
    "tbd",
}
PENDING_DEPARTURE_DATE = "日期待确认"
DEFAULT_BUDGET_MIN_PER_PERSON = 1500.0
DEFAULT_BUDGET_MAX_PER_PERSON = 3500.0
SCENIC_PRICE_COLLECTION_DATE = SCENIC_TICKET_COLLECTION_DATE

TRANSPORT_BASE_COST_PER_PERSON = {
    "flight": 800,
    "train": 350,
    "driving": 250,
}

FOOD_DAILY_COST_PER_PERSON = {
    "specialty": 220,
    "chain": 90,
    "local": 130,
}

KNOWN_POI_PROFILES = {
    "外滩": {
        "area": "黄浦江沿岸",
        "best_time": "傍晚/晚上",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["夜景", "城市漫步", "免费"],
    },
    "上海博物馆": {
        "area": "人民广场",
        "best_time": "上午",
        "duration_hours": 2.5,
        "reservation_required": True,
        "indoor": True,
        "estimated_cost": 0.0,
        "tags": ["文化", "室内", "预约"],
    },
    "田子坊": {
        "area": "打浦桥/泰康路",
        "best_time": "下午",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["街区", "文创", "小吃"],
    },
    "豫园": {
        "area": "老城厢/城隍庙",
        "best_time": "上午/下午",
        "duration_hours": 2.0,
        "reservation_required": True,
        "indoor": False,
        "estimated_cost": 40.0,
        "tags": ["园林", "传统文化", "门票"],
    },
    "武康路": {
        "area": "衡复风貌区",
        "best_time": "下午",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["城市漫步", "建筑", "免费"],
    },
    "南京路步行街": {
        "area": "南京路/人民广场",
        "best_time": "傍晚/晚上",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["城市漫步", "商业街区", "美食"],
    },
    "陆家嘴": {
        "area": "浦东/陆家嘴",
        "best_time": "下午/晚上",
        "duration_hours": 2.0,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["天际线", "城市景观", "免费"],
    },
    "东方明珠": {
        "area": "浦东/陆家嘴",
        "best_time": "下午/晚上",
        "duration_hours": 2.0,
        "reservation_required": True,
        "indoor": True,
        "estimated_cost": 199.0,
        "tags": ["地标", "观景", "门票"],
    },
    "城隍庙": {
        "area": "老城厢/豫园",
        "best_time": "上午/下午",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["传统街区", "小吃", "免费"],
    },
    "橘子洲头": {
        "area": "湘江沿岸/橘子洲",
        "best_time": "傍晚/晚上",
        "duration_hours": 2.0,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["江景", "城市漫步", "免费"],
    },
    "岳麓山": {
        "area": "岳麓山/大学城",
        "best_time": "上午",
        "duration_hours": 3.0,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["自然", "人文", "免费"],
    },
    "岳麓书院": {
        "area": "岳麓山/大学城",
        "best_time": "上午/下午",
        "duration_hours": 1.5,
        "reservation_required": True,
        "indoor": False,
        "estimated_cost": 40.0,
        "tags": ["历史", "文化", "预约"],
    },
    "湖南博物院": {
        "area": "开福区/烈士公园",
        "best_time": "上午/下午",
        "duration_hours": 3.0,
        "reservation_required": True,
        "indoor": True,
        "estimated_cost": 0.0,
        "tags": ["室内", "文化", "预约"],
    },
    "五一广场": {
        "area": "五一广场/黄兴路",
        "best_time": "下午/晚上",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["商圈", "美食", "步行"],
    },
    "太平老街": {
        "area": "五一广场/太平街",
        "best_time": "下午/晚上",
        "duration_hours": 1.5,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["老街", "小吃", "步行"],
    },
    "杜甫江阁": {
        "area": "湘江沿岸/杜甫江阁",
        "best_time": "晚上",
        "duration_hours": 1.0,
        "reservation_required": False,
        "indoor": False,
        "estimated_cost": 0.0,
        "tags": ["夜景", "江景", "城市漫步"],
    },
}

DEFAULT_DESTINATION_ATTRACTIONS = {
    "上海": ["外滩", "南京路步行街", "上海博物馆", "豫园", "城隍庙", "武康路", "陆家嘴"],
    "北京": ["故宫", "天安门广场", "国家博物馆", "什刹海", "南锣鼓巷"],
    "西安": ["秦始皇兵马俑", "西安城墙", "钟楼", "鼓楼", "回民街", "陕西历史博物馆"],
    "南京": ["中山陵", "南京博物院", "总统府", "夫子庙", "老门东", "玄武湖"],
    "杭州": ["西湖", "灵隐寺", "河坊街", "京杭大运河", "西溪湿地"],
    "成都": ["宽窄巷子", "武侯祠", "锦里", "成都大熊猫繁育研究基地", "人民公园"],
    "\u957f\u6c99": [
        "\u6a58\u5b50\u6d32\u5934",
        "\u5cb3\u9e93\u5c71",
        "\u5cb3\u9e93\u4e66\u9662",
        "\u6e56\u5357\u535a\u7269\u9662",
        "\u4e94\u4e00\u5e7f\u573a",
        "\u592a\u5e73\u8001\u8857",
        "\u675c\u752b\u6c5f\u9601",
    ],
}

DEFAULT_ACCOMMODATION_AREAS = {
    "上海": "人民广场/南京东路",
    "北京": "前门/王府井",
    "西安": "钟楼/鼓楼",
    "南京": "新街口/夫子庙",
    "杭州": "湖滨/武林广场",
    "成都": "春熙路/天府广场",
    "\u957f\u6c99": "\u4e94\u4e00\u5e7f\u573a/\u9ec4\u5174\u8def\u6b65\u884c\u8857",
}

KNOWN_FOOD_POI_PROFILES = {
    "南京路小吃": {
        "type": "local",
        "area": "南京路/人民广场",
        "meal_time": "晚餐/夜宵",
        "average_cost": 80.0,
        "reservation_required": False,
        "queue_risk": "中",
        "suitable_for": ["城市漫步", "小吃扫街"],
        "tags": ["本地小吃", "步行可达"],
    },
    "城隍庙小吃": {
        "type": "local",
        "area": "老城厢/豫园",
        "meal_time": "午餐/下午茶",
        "average_cost": 90.0,
        "reservation_required": False,
        "queue_risk": "高",
        "suitable_for": ["传统街区", "小吃体验"],
        "tags": ["本地小吃", "热门区域"],
    },
    "本帮菜餐厅": {
        "type": "specialty",
        "area": "人民广场/南京路周边",
        "meal_time": "晚餐",
        "average_cost": 180.0,
        "reservation_required": True,
        "queue_risk": "中",
        "suitable_for": ["特色餐厅", "文化美食"],
        "tags": ["本帮菜", "建议预约"],
    },
    "商场连锁简餐": {
        "type": "chain",
        "area": "大型商场/地铁站周边",
        "meal_time": "午餐/晚餐",
        "average_cost": 70.0,
        "reservation_required": False,
        "queue_risk": "低",
        "suitable_for": ["赶路", "带娃", "省心"],
        "tags": ["稳定", "省心"],
    },
    "茶颜悦色": {
        "type": "local",
        "area": "五一广场/黄兴路",
        "meal_time": "下午茶/夜宵",
        "average_cost": 25.0,
        "reservation_required": False,
        "queue_risk": "中",
        "suitable_for": ["本地打卡", "轻松休闲"],
        "tags": ["长沙特色", "饮品", "排队错峰"],
    },
    "黑色经典臭豆腐": {
        "type": "local",
        "area": "五一广场/太平街",
        "meal_time": "午餐/下午茶/夜宵",
        "average_cost": 35.0,
        "reservation_required": False,
        "queue_risk": "中",
        "suitable_for": ["小吃扫街", "本地风味"],
        "tags": ["长沙小吃", "步行可达"],
    },
    "笨萝卜浏阳菜馆": {
        "type": "specialty",
        "area": "五一广场/芙蓉区",
        "meal_time": "午餐/晚餐",
        "average_cost": 90.0,
        "reservation_required": False,
        "queue_risk": "高",
        "suitable_for": ["湘菜", "特色餐厅"],
        "tags": ["湘菜", "热门餐厅", "建议错峰"],
    },
    "超级文和友": {
        "type": "specialty",
        "area": "海信广场/湘江中路",
        "meal_time": "晚餐/夜宵",
        "average_cost": 120.0,
        "reservation_required": False,
        "queue_risk": "高",
        "suitable_for": ["城市打卡", "小吃集合"],
        "tags": ["长沙地标", "夜间氛围", "排队风险"],
    },
}

DEFAULT_DESTINATION_FOOD_POIS = {
    "长沙": {
        "local": ["茶颜悦色", "黑色经典臭豆腐"],
        "specialty": ["笨萝卜浏阳菜馆", "超级文和友"],
        "chain": ["五一广场商场简餐"],
    },
    "上海": {
        "local": ["南京路小吃", "城隍庙小吃"],
        "specialty": ["本帮菜餐厅"],
        "chain": ["商场连锁简餐"],
    },
}


def _normalize_choice(value: str, valid_labels: dict[str, str], aliases: dict[str, str]) -> str:
    normalized = str(value).strip()
    if normalized in valid_labels:
        return normalized
    lowered = normalized.lower()
    if lowered in valid_labels:
        return lowered
    if normalized in aliases:
        return aliases[normalized]
    if lowered in aliases:
        return aliases[lowered]
    return normalized


def _matching_choice_aliases(
    value: str,
    valid_labels: dict[str, str],
    aliases: dict[str, str],
) -> list[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return []
    matches: list[str] = []
    for key, choice in {**aliases, **valid_labels}.items():
        if key and key in normalized and choice in valid_labels and choice not in matches:
            matches.append(choice)
    return matches


def _normalize_choices(
    values: list[str],
    valid_labels: dict[str, str],
    aliases: dict[str, str],
) -> list[str]:
    normalized = []
    for value in values:
        choice = _normalize_choice(value, valid_labels, aliases)
        if choice in valid_labels and choice not in normalized:
            normalized.append(choice)
            continue
        matched_choices = _matching_choice_aliases(value, valid_labels, aliases)
        for matched_choice in matched_choices:
            if matched_choice not in normalized:
                normalized.append(matched_choice)
        if not matched_choices and choice not in valid_labels and choice not in normalized:
            normalized.append(choice)
    return normalized


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _as_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def _find_accommodation_option(
    state: TravelState,
    *,
    hotel_id: Optional[int | str] = None,
    hotel_name: Optional[str] = None,
) -> Optional[dict]:
    for option in state.get("accommodation_options") or []:
        if hotel_id is not None and str(option.get("hotel_id")) == str(hotel_id):
            return dict(option)
        if hotel_name and option.get("name") == hotel_name:
            return dict(option)
    return None


def _first_accommodation_option(state: TravelState) -> Optional[dict]:
    for option in state.get("accommodation_options") or []:
        if option:
            return dict(option)
    return None


def _tool_message(content: str, runtime: Optional[ToolRuntime]) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=getattr(runtime, "tool_call_id", ""),
    )


def _command_with_message(
    content: str,
    runtime: Optional[ToolRuntime],
    **state_update,
) -> Command:
    return Command(
        update={
            "messages": [_tool_message(content, runtime)],
            **state_update,
        }
    )


def _runtime_state(runtime: Optional[ToolRuntime]) -> TravelState:
    if runtime and runtime.state:
        return runtime.state
    return TravelState(messages=[])


def _step_at_or_after(current_step: str | None, target_step: str | None) -> bool:
    if not current_step or not target_step:
        return current_step == target_step
    try:
        return WORKFLOW_STEPS.index(current_step) >= WORKFLOW_STEPS.index(target_step)
    except ValueError:
        return current_step == target_step


def _duplicate_state_update(
    state: TravelState,
    state_update: dict[str, Any],
) -> bool:
    fields_to_compare = {
        key: value
        for key, value in state_update.items()
        if key not in {"messages", "current_step", "confirmation_history"}
    }
    if not fields_to_compare:
        return False
    if any(state.get(key) != value for key, value in fields_to_compare.items()):
        return False
    desired_step = state_update.get("current_step")
    if desired_step is None:
        return True
    return _step_at_or_after(state.get("current_step"), desired_step)


def _duplicate_state_command(
    tool_name: str,
    state_update: dict[str, Any],
    runtime: Optional[ToolRuntime],
) -> Command | None:
    state = _runtime_state(runtime)
    if not _duplicate_state_update(state, state_update):
        return None
    messages = {
        "record_requirement_tool": "本轮需求已经记录，规划阶段已推进；不会重复写入同一份需求。",
        "select_destination_tool": "目的地已经确认，规划阶段已推进；不会重复写入同一目的地或回退阶段。",
        "select_transport_tool": "交通方案已经确认，规划阶段已推进；不会重复写入同一交通选择。",
        "select_accommodation_tool": "住宿选择已经确认，规划阶段已推进；不会重复写入同一住宿选择。",
        "select_food_tool": "餐饮偏好已经确认，规划阶段已推进；不会重复写入同一餐饮选择。",
    }
    return _command_with_message(
        messages.get(tool_name, "本轮已经写入等价状态，已跳过重复状态迁移。"),
        runtime,
    )


def _planning_mode_state_update(
    state: TravelState,
    *,
    planning_mode: str,
    planning_mode_reason: str,
    planning_mode_confirmed: bool,
) -> dict:
    update = {
        "planning_mode": planning_mode,
        "active_workflow": planning_mode,
        "planning_mode_reason": planning_mode_reason,
        "planning_mode_confirmed": planning_mode_confirmed,
    }
    requirement = state.get("user_requirement")
    if isinstance(requirement, dict) and requirement:
        update["user_requirement"] = {
            **requirement,
            "planning_mode": planning_mode,
            "active_workflow": planning_mode,
            "planning_mode_reason": planning_mode_reason,
            "planning_mode_confirmed": planning_mode_confirmed,
        }
    return update


def _state_confirmed_facts(state: TravelState | dict[str, Any] | None) -> dict[str, Any]:
    facts = (state or {}).get("confirmed_facts") if isinstance(state, dict) else {}
    return dict(facts) if isinstance(facts, dict) else {}


def _iso_date_or_none(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _confirmation_history_with_entries(
    state: TravelState | dict[str, Any] | None,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = list((state or {}).get("confirmation_history") or []) if isinstance(state, dict) else []
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*existing, *entries]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        value = str(item.get("value") or "")
        if not key or (key, value) in seen:
            continue
        seen.add((key, value))
        merged.append(item)
    return merged[-40:]


def _confirmed_fact_entries(
    facts: dict[str, Any],
    *,
    source: str,
) -> list[dict[str, Any]]:
    labels = {
        "departure_city": "出发城市",
        "destination": "目的地",
        "departure_date": "出发日期",
        "travel_days": "行程天数",
        "return_date": "行程结束日期",
        "check_in_date": "入住日期",
        "check_out_date": "退房日期",
        "adult_count": "成人数",
        "children_count": "儿童数",
        "budget_min": "预算下限",
        "budget_max": "预算上限",
        "active_workflow": "规划工作流",
    }
    now = time.time()
    return [
        {
            "key": key,
            "value": value,
            "label": labels.get(key, key),
            "confirmed_at": now,
            "source": source,
        }
        for key, value in facts.items()
        if value not in (None, "", [], {})
    ]


def _build_confirmed_facts(
    *,
    state: TravelState | dict[str, Any] | None,
    requirement: dict[str, Any],
    planning_mode: str,
) -> dict[str, Any]:
    facts = _state_confirmed_facts(state)
    for key in (
        "departure_city",
        "destination",
        "travel_days",
        "adult_count",
        "children_count",
        "budget_min",
        "budget_max",
    ):
        value = requirement.get(key)
        if value not in (None, "", [], {}):
            facts[key] = value

    departure_date = requirement.get("departure_date")
    if requirement.get("departure_date_confirmed") and not _is_pending_requirement_value(departure_date):
        parsed = _iso_date_or_none(departure_date)
        if parsed:
            travel_days = int(requirement.get("travel_days") or 1)
            end_date = parsed + timedelta(days=max(travel_days - 1, 0))
            facts["departure_date"] = parsed.isoformat()
            facts["return_date"] = end_date.isoformat()
            facts["check_in_date"] = parsed.isoformat()
            facts["check_out_date"] = end_date.isoformat()
    facts["active_workflow"] = planning_mode
    return facts


def _matched_product_summary(requirement: dict[str, Any], state: TravelState | dict[str, Any] | None) -> dict[str, Any]:
    product = build_light_product(requirement, state)
    return {
        "code": product.get("code"),
        "name": product.get("name"),
        "product_type": product.get("product_type"),
        "duration_label": product.get("duration_label"),
        "positioning": product.get("positioning"),
        "service_nodes": list(product.get("service_nodes") or []),
        "non_commitments": list(product.get("non_commitments") or []),
    }


def _set_planning_mode_command(
    *,
    mode: str,
    reason: str,
    confirmed: bool,
    runtime: Optional[ToolRuntime],
) -> Command:
    normalized_mode = _normalize_planning_mode(mode)
    if not normalized_mode:
        return _command_with_message(
            "规划模式只能是 free_planning（自由规划）或 agency_plan（旅行社顾问方案）。",
            runtime,
        )

    state = _runtime_state(runtime)
    label = PLANNING_MODE_LABELS[normalized_mode]
    mode_reason = reason or f"用户选择{label}"
    state_update = _planning_mode_state_update(
        state,
        planning_mode=normalized_mode,
        planning_mode_reason=mode_reason,
        planning_mode_confirmed=confirmed,
    )
    status_text = "已确认" if confirmed else "已记录为倾向"
    return _command_with_message(
        f"规划模式{status_text}：{label}。后续会按这个模式组织方案表达。",
        runtime,
        **state_update,
    )


@tool
def set_planning_mode_tool(
    mode: str,
    reason: str = "",
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Record the user's current planning-mode preference without treating it as final confirmation."""

    return _set_planning_mode_command(
        mode=mode,
        reason=reason,
        confirmed=False,
        runtime=runtime,
    )


@tool
def confirm_planning_mode_tool(
    mode: str,
    reason: str = "",
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist the confirmed planning mode: free planning or agency consultant plan."""

    return _set_planning_mode_command(
        mode=mode,
        reason=reason,
        confirmed=True,
        runtime=runtime,
    )


@tool
def record_evidence_bundle_tool(
    evidence_bundle: dict[str, Any],
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist structured evidence used by planning, pricing, risk, or report generation."""

    if not isinstance(evidence_bundle, dict) or not evidence_bundle:
        return _command_with_message("证据包为空，未写入状态。", runtime)
    return _command_with_message(
        "证据包已记录，后续方案会优先引用这些依据。",
        runtime,
        evidence_bundle=evidence_bundle,
    )


def _scenic_price_candidates(
    destination: Any,
    scenic_names: Any = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    return find_scenic_ticket_candidates(destination, scenic_names)


@tool
def scenic_price_lookup_tool(
    destination: Any = "",
    scenic_names: Any = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Return first-version scenic ticket evidence from curated public reference data."""

    state = _runtime_state(runtime)
    if not destination:
        destination = (
            state.get("selected_destination")
            or (state.get("user_requirement") or {}).get("destination")
            or ""
        )
    destination_name, items, catalog = _scenic_price_candidates(destination, scenic_names)
    collected_at = str(catalog.get("collected_at") or SCENIC_PRICE_COLLECTION_DATE)
    if not items:
        payload = {
            "destination": destination_name,
            "collected_at": collected_at,
            "provider": catalog.get("provider") or "curated_rag_ticket_catalog",
            "provider_status": catalog.get("provider_status") or "reference_only",
            "supplier_candidates": catalog.get("supplier_candidates") or [],
            "catalog_source": catalog.get("source"),
            "items": [],
            "disclaimer": "第一版景点价格库尚未覆盖该目的地；门票、预约、开放时间和优惠政策需出发前二次核验，不锁价。",
        }
        return _command_with_message(
            f"{destination_name} 的景点价格库暂未覆盖；门票和预约请以官方渠道二次核验。",
            runtime,
            scenic_price_evidence=payload,
        )

    payload = {
        "destination": destination_name,
        "collected_at": collected_at,
        "provider": catalog.get("provider") or "curated_rag_ticket_catalog",
        "provider_status": catalog.get("provider_status") or "reference_only",
        "supplier_candidates": catalog.get("supplier_candidates") or [],
        "catalog_source": catalog.get("source"),
        "items": items,
        "disclaimer": "以上为公开资料整理的样例参考价，不代表实时库存、优惠政策、预约成功或锁价；不锁价，正式出发前必须以官方购票页/景区公告二次核验。",
    }
    lines = [
        f"{destination_name} 景点门票参考（采集日期：{collected_at}）",
        "当前来自可审计票价知识目录；价格不是实时价，不锁价；预约、开放时间、优惠政策需出发前二次核验。",
    ]
    for item in items:
        lines.append(
            f"- {item['name']}：{item['price_label']}；预约/开放：{item['reservation_note']} {item['open_note']}；来源：{item['source']} {item['source_url']}"
        )
    return _command_with_message(
        "\n".join(lines),
        runtime,
        scenic_price_evidence=payload,
    )


def _budget_level_from_range(budget_min: float, budget_max: float) -> str:
    avg_budget = (budget_min + budget_max) / 2
    if avg_budget < 3000:
        return "economy"
    if avg_budget < 8000:
        return "comfort"
    return "luxury"


def _is_pending_requirement_value(value: Any) -> bool:
    return str(value or "").strip().lower() in PENDING_REQUIREMENT_VALUES


def _runtime_recent_human_text(runtime: Optional[ToolRuntime]) -> str:
    state = runtime.state if runtime and runtime.state else {}
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


def _runtime_message_tool_names(message: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(message, ToolMessage):
        name = getattr(message, "name", None)
        if name:
            names.add(str(name))

    if isinstance(message, dict):
        if message.get("type") == "tool" and message.get("name"):
            names.add(str(message["name"]))
        tool_calls = message.get("tool_calls") or []
    else:
        tool_calls = getattr(message, "tool_calls", None) or []

    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            name = tool_call.get("name") or tool_call.get("function", {}).get("name")
        else:
            name = getattr(tool_call, "name", None)
        if name:
            names.add(str(name))
    return names


def _runtime_has_tool_result(runtime: Optional[ToolRuntime], tool_name: str) -> bool:
    state = runtime.state if runtime and runtime.state else {}
    return any(
        tool_name in _runtime_message_tool_names(message)
        for message in (state.get("messages") or [])
    )


def _needs_hotel_audit_before_accommodation_selection(runtime: Optional[ToolRuntime]) -> bool:
    state = _runtime_state(runtime)
    if _runtime_has_tool_result(runtime, "query_hotel_options"):
        return False
    if state.get("accommodation_options"):
        return False

    text = _runtime_recent_human_text(runtime)
    if not text:
        return False

    hotel_keywords = ("酒店", "住宿", "住", "江景", "海景", "房", "民宿", "锁价")
    fallback_keywords = (
        "查不到",
        "查不到具体",
        "没有真实",
        "没有锁定",
        "没有真实锁价",
        "没有真实价格",
        "未锁价",
        "没锁价",
        "兜底",
        "待核验",
        "待二次核验",
        "二次核验",
    )
    return any(keyword in text for keyword in hotel_keywords) and any(
        keyword in text for keyword in fallback_keywords
    )


def _needs_transport_audit_before_transport_selection(runtime: Optional[ToolRuntime]) -> bool:
    state = _runtime_state(runtime)
    if _runtime_has_tool_result(runtime, "query_transport_options"):
        return False
    if state.get("transport_options"):
        return False

    text = _runtime_recent_human_text(runtime)
    if not text:
        return False

    transport_keywords = ("交通", "高铁", "火车", "车次", "航班", "飞机", "班次", "票价", "自驾")
    fallback_keywords = (
        "查不到",
        "没有查到",
        "查不到合适",
        "查不到具体",
        "如果没有",
        "兜底",
        "待核验",
        "待二次核验",
        "二次核验",
    )
    return any(keyword in text for keyword in transport_keywords) and any(
        keyword in text for keyword in fallback_keywords
    )


def _parse_requirement_date_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or _is_pending_requirement_value(text):
        return None

    normalized = text.replace("/", "-")
    match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", normalized)
    if match:
        normalized = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    try:
        return normalize_travel_date(normalized, today=date.today())
    except ValueError:
        pass

    match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日?", normalized)
    if not match:
        return None

    month = int(match.group(1))
    day = int(match.group(2))
    today = date.today()
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate < today:
        try:
            candidate = date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate.isoformat()


def _human_text_has_date_hint(text: str) -> bool:
    patterns = (
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{4}/\d{1,2}/\d{1,2}",
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{1,2}月\d{1,2}日?",
        r"(周|星期|礼拜)[一二三四五六日天]",
        r"(今天|明天|后天|大后天|这周|本周|下周|下下周|周末|下个月|春节|五一|端午|中秋|国庆|暑假|寒假|元旦|清明|劳动节)",
    )
    return any(re.search(pattern, text or "") for pattern in patterns)


def _date_supported_by_human_text(date_text: str, raw_value: Any, human_text: str) -> bool:
    if not human_text:
        return True
    if not date_text:
        return False

    raw_text = str(raw_value or "").strip()
    compact_human = re.sub(r"[\s/]", "-", human_text)
    if raw_text and raw_text in human_text:
        return True
    if date_text in compact_human or date_text in human_text:
        return True

    parsed = _parse_requirement_date_text(raw_text)
    if parsed == date_text and _human_text_has_date_hint(human_text):
        return True

    try:
        parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return False
    month_day_patterns = (
        f"{parsed_date.month}月{parsed_date.day}日",
        f"{parsed_date.month:02d}月{parsed_date.day:02d}日",
        f"{parsed_date.month}月{parsed_date.day}",
        f"{parsed_date.month:02d}月{parsed_date.day:02d}",
    )
    if any(pattern in human_text for pattern in month_day_patterns):
        return True

    return _human_text_has_date_hint(human_text)


def _normalize_requirement_date(
    value: Any,
    runtime: Optional[ToolRuntime] = None,
) -> tuple[str, bool, bool]:
    parsed_date = _parse_requirement_date_text(value)
    if not parsed_date:
        return PENDING_DEPARTURE_DATE, True, False

    human_text = _runtime_recent_human_text(runtime)
    if not _date_supported_by_human_text(parsed_date, value, human_text):
        return PENDING_DEPARTURE_DATE, True, False
    return parsed_date, False, True


def _coerce_positive_int(value: Any, default: int) -> tuple[int, bool]:
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            value = match.group(0)
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default, True
    if normalized <= 0:
        return default, True
    return normalized, False


def _coerce_non_negative_int(value: Any, default: int = 0) -> tuple[int, bool]:
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            value = match.group(0)
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default, True
    if normalized < 0:
        return default, True
    return normalized, False


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, str):
        text = value.strip()
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        parsed = float(match.group(0))
        return parsed * 10000 if "万" in text else parsed
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_requirement_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_requirement_styles(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[、,，/；;\s]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    elif value is None:
        raw_items = []
    else:
        raw_items = [value]
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "确认", "是"}:
        return True
    if text in {"false", "0", "no", "n", "否"}:
        return False
    return default


def _append_requirement_assumptions(
    special_needs: str,
    assumption_notes: list[str],
) -> str:
    if not assumption_notes:
        return special_needs
    normalized = (special_needs or "").strip()
    assumption_text = "待核验假设：" + "；".join(assumption_notes)
    if not normalized:
        return assumption_text
    if assumption_text in normalized:
        return normalized
    return f"{normalized}；{assumption_text}"


def _format_transport_option(option: Optional[dict]) -> str:
    if not option:
        return "具体班次/路线待确认"

    parts = []
    details = option.get("details")
    if details:
        parts.append(str(details))

    time_parts = []
    if option.get("departure_time"):
        time_parts.append(f"出发 {option['departure_time']}")
    if option.get("arrival_time"):
        time_parts.append(f"到达 {option['arrival_time']}")
    if option.get("duration"):
        time_parts.append(f"耗时 {option['duration']}")
    if time_parts:
        parts.append("，".join(time_parts))

    price = option.get("price")
    if isinstance(price, (int, float)) and price > 0:
        parts.append(f"参考价 {price:.0f} 元/人")

    return "；".join(parts) or "具体班次/路线待确认"


def _format_accommodation_option(option: Optional[dict]) -> str:
    if not option:
        return "住宿待结合偏好确认"

    parts = [option.get("name", "未命名酒店")]
    if option.get("location"):
        parts.append(str(option["location"]))
    price = option.get("price_per_night")
    if isinstance(price, (int, float)) and price > 0:
        parts.append(f"约 {price:.0f} 元/晚")
    if option.get("rating"):
        parts.append(f"评分/星级 {option['rating']}")
    return "，".join(parts)


def _estimate_transport_cost(state: TravelState, total_people: int) -> float:
    selected_transport = state.get("selected_transport")
    selected_option = state.get("selected_transport_option") or {}
    price = selected_option.get("price")
    if isinstance(price, (int, float)) and price > 0:
        return price * total_people
    return TRANSPORT_BASE_COST_PER_PERSON.get(selected_transport, 500) * total_people


def _estimate_food_cost_by_type(
    selected_food_types: list[str],
    travel_days: int,
    total_people: int,
) -> float:
    if not selected_food_types:
        daily_per_person = 150
    else:
        daily_per_person = max(
            FOOD_DAILY_COST_PER_PERSON.get(food_type, 150)
            for food_type in selected_food_types
        )
    return daily_per_person * travel_days * total_people


def _itinerary_text(itinerary: list[dict]) -> str:
    lines = []
    for day in itinerary:
        for key in ["activities", "time_blocks", "meals", "risk_notes"]:
            value = day.get(key) or []
            if isinstance(value, list):
                lines.extend(str(item) for item in value)
            elif value:
                lines.append(str(value))
        for key in ["theme", "route_note", "transport_note", "plan_b"]:
            if day.get(key):
                lines.append(str(day[key]))
    return "\n".join(lines)


def _estimate_accommodation_cost(
    selected_accommodation: dict,
    travel_days: int,
    total_people: int,
) -> tuple[float, str]:
    nights = max(travel_days - 1, 1)
    room_count = max(ceil(total_people / 2), 1)
    price_per_night = selected_accommodation.get("price_per_night")
    if isinstance(price_per_night, (int, float)) and price_per_night > 0:
        return (
            price_per_night * nights * room_count,
            f"住宿按已选酒店每间夜 {price_per_night:.0f} 元、{nights} 晚、约 {room_count} 间房估算。",
        )
    fallback_price = 300
    return (
        fallback_price * nights * room_count,
        f"住宿缺少具体酒店价格，按每间夜 {fallback_price} 元、{nights} 晚、约 {room_count} 间房兜底估算。",
    )


def _estimate_food_cost_from_itinerary(
    state: TravelState,
    itinerary: list[dict],
    travel_days: int,
    total_people: int,
) -> tuple[float, str]:
    food_pois = _get_food_pois(state)
    if not food_pois:
        return (
            _estimate_food_cost_by_type(
                state.get("selected_food_types") or [],
                travel_days,
                total_people,
            ),
            "餐饮缺少具体餐饮 POI，按已确认餐饮偏好类型兜底估算。",
        )

    breakfast_per_person = 30
    total = breakfast_per_person * travel_days * total_people
    matched_meals = []
    fallback_meal_count = 0
    fallback_meal_price = 70
    food_by_name = {
        str(food_poi.get("name")): food_poi
        for food_poi in food_pois
        if food_poi.get("name")
    }

    for day in itinerary:
        for meal in day.get("meals") or []:
            meal_text = str(meal)
            if meal_text.startswith("早餐"):
                continue
            matched_poi = next(
                (
                    food_poi
                    for name, food_poi in food_by_name.items()
                    if name and name in meal_text
                ),
                None,
            )
            average_cost = matched_poi.get("average_cost") if matched_poi else None
            if isinstance(average_cost, (int, float)) and average_cost > 0:
                total += average_cost * total_people
                matched_meals.append(str(matched_poi.get("name")))
            else:
                total += fallback_meal_price * total_people
                fallback_meal_count += 1

    unique_matched = []
    for name in matched_meals:
        if name not in unique_matched:
            unique_matched.append(name)
    assumption = (
        f"餐饮按行程中的具体餐饮 POI 人均价估算，早餐按 {breakfast_per_person} 元/人/天；"
        f"已匹配：{'、'.join(unique_matched) or '无'}。"
    )
    if fallback_meal_count:
        assumption += f" 另有 {fallback_meal_count} 餐缺少具体人均价，按 {fallback_meal_price} 元/人/餐兜底。"
    return total, assumption


def _estimate_attractions_cost(
    destination_context: dict,
    itinerary: list[dict],
    travel_days: int,
    total_people: int,
    scenic_price_evidence: dict[str, Any] | None = None,
) -> tuple[float, str]:
    text = _itinerary_text(itinerary)
    scenic_items = (
        scenic_price_evidence.get("items")
        if isinstance(scenic_price_evidence, dict)
        else []
    )
    if isinstance(scenic_items, list) and scenic_items:
        total = 0.0
        paid_items = []
        seen_names = set()
        for item in scenic_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen_names or name not in text:
                continue
            seen_names.add(name)
            price = item.get("adult_price")
            if isinstance(price, (int, float)) and price > 0:
                total += price * total_people
                paid_items.append(f"{name} {price:g} 元/人")
        if paid_items:
            collected_at = scenic_price_evidence.get("collected_at") or SCENIC_PRICE_COLLECTION_DATE
            return (
                total,
                "景点/体验按景点价格参考库估算："
                f"{'、'.join(paid_items)}；采集日期 {collected_at}，不锁价，出发前需二次核验。",
            )

    destination_pois = _get_destination_pois(destination_context)
    if not destination_pois:
        fallback = 200 * travel_days * total_people
        return fallback, "景点缺少结构化 POI 费用，按 200 元/人/天兜底估算。"

    paid_items = []
    total = 0.0
    seen_names = set()
    for poi in destination_pois:
        name = str(poi.get("name") or "").strip()
        if not name or name in seen_names or name not in text:
            continue
        seen_names.add(name)
        cost = poi.get("estimated_cost")
        if isinstance(cost, (int, float)) and cost > 0:
            total += cost * total_people
            paid_items.append(f"{name} {cost:g} 元/人")

    if paid_items:
        return total, f"景点/体验按行程中可识别门票估算：{'、'.join(paid_items)}。"
    return 0.0, "景点 POI 未识别到需付费项目，景点/体验费用暂按 0 元估算；出发前仍需核验预约和临时展览收费。"


def _safe_per_person(amount: float, total_people: int) -> float:
    return safe_per_person(amount, total_people)


def _budget_line_item(
    key: str,
    label: str,
    amount: float,
    total_people: int,
    basis: str,
    confidence: str,
) -> dict:
    return build_budget_line_item(
        key,
        label,
        amount,
        total_people,
        basis,
        confidence,
    )


def _build_budget_line_items(
    state: TravelState,
    itinerary: list[dict],
    travel_days: int,
    total_people: int,
    transport_cost: float,
    accommodation_cost: float,
    food_cost: float,
    attractions_cost: float,
    misc_cost: float,
) -> list[dict]:
    selected_transport = state.get("selected_transport")
    selected_transport_option = state.get("selected_transport_option") or {}
    selected_accommodation = state.get("selected_accommodation_option") or {}
    nights = max(travel_days - 1, 1)
    room_count = max(ceil(total_people / 2), 1)

    transport_price = selected_transport_option.get("price")
    if isinstance(transport_price, (int, float)) and transport_price > 0:
        transport_basis = f"已选交通方案 {transport_price:.0f} 元/人 × {total_people} 人"
        transport_confidence = "已确认价格"
    else:
        base_price = TRANSPORT_BASE_COST_PER_PERSON.get(selected_transport, 500)
        transport_basis = f"{TRANSPORT_LABELS.get(selected_transport, selected_transport or '交通')} 基准 {base_price:.0f} 元/人 × {total_people} 人"
        transport_confidence = "兜底估算"

    hotel_price = selected_accommodation.get("price_per_night")
    if isinstance(hotel_price, (int, float)) and hotel_price > 0:
        accommodation_basis = f"每间夜 {hotel_price:.0f} 元 × {nights} 晚 × {room_count} 间"
        accommodation_confidence = "已确认价格"
    else:
        accommodation_basis = f"兜底每间夜 300 元 × {nights} 晚 × {room_count} 间"
        accommodation_confidence = "兜底估算"

    food_pois = _get_food_pois(state)
    matched_food_names = []
    itinerary_text = _itinerary_text(itinerary)
    for food_poi in food_pois:
        name = str(food_poi.get("name") or "").strip()
        average_cost = food_poi.get("average_cost")
        if name and name in itinerary_text and isinstance(average_cost, (int, float)) and average_cost > 0:
            matched_food_names.append(f"{name} {average_cost:g} 元/人")
    if matched_food_names:
        food_basis = (
            f"早餐 30 元/人/天；午晚餐按 {'、'.join(matched_food_names)} 与缺口餐次兜底估算"
        )
        food_confidence = "行程 POI 估算"
    else:
        food_basis = "早餐 30 元/人/天；午晚餐按餐饮偏好或 70 元/人/餐兜底估算"
        food_confidence = "偏好兜底估算"

    attractions_basis = "按行程可识别付费 POI 门票估算；未识别付费项则暂按 0 元"
    attractions_confidence = "POI 估算" if attractions_cost > 0 else "待核验"
    misc_basis = f"市内交通、寄存、临时休息和小额杂费 100 元/人/天 × {travel_days} 天 × {total_people} 人"

    return [
        _budget_line_item("transport", "交通", transport_cost, total_people, transport_basis, transport_confidence),
        _budget_line_item("accommodation", "住宿", accommodation_cost, total_people, accommodation_basis, accommodation_confidence),
        _budget_line_item("food", "餐饮", food_cost, total_people, food_basis, food_confidence),
        _budget_line_item("attractions", "景点/体验", attractions_cost, total_people, attractions_basis, attractions_confidence),
        _budget_line_item("misc", "其他机动", misc_cost, total_people, misc_basis, "固定规则估算"),
    ]


def _build_budget_quality_notes(
    state: TravelState,
    destination_context: dict,
    itinerary: list[dict],
) -> dict[str, list[str] | str]:
    return build_agency_budget_quality_notes(
        selected_transport_option=state.get("selected_transport_option") or {},
        selected_accommodation=state.get("selected_accommodation_option") or {},
        food_pois=_get_food_pois(state),
        destination_pois=_get_destination_pois(destination_context),
        itinerary_text=_itinerary_text(itinerary),
        tool_audit_events=state.get("tool_audit_events"),
    )


def _budget_confidence_payload(budget: dict) -> dict:
    return budget_confidence_payload(budget)


def _ensure_budget_quality_contract(
    state: TravelState,
    requirement: dict,
    budget: dict,
    itinerary: list[dict],
) -> dict:
    normalized = dict(budget or {})
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    destination_context = _get_destination_context(state, destination)
    travel_days = (
        normalized.get("travel_days")
        or _get_expected_travel_days(requirement, len(itinerary))
        or 1
    )
    total_people = (
        normalized.get("total_people")
        or (requirement.get("adult_count") or 0) + (requirement.get("children_count") or 0)
        or 1
    )
    selected_accommodation = state.get("selected_accommodation_option") or {}

    transport_cost = normalized.get("transport")
    if not isinstance(transport_cost, (int, float)):
        transport_cost = _estimate_transport_cost(state, total_people)
        normalized["transport"] = transport_cost

    accommodation_cost = normalized.get("accommodation")
    accommodation_assumption = ""
    if not isinstance(accommodation_cost, (int, float)):
        accommodation_cost, accommodation_assumption = _estimate_accommodation_cost(
            selected_accommodation,
            travel_days,
            total_people,
        )
        normalized["accommodation"] = accommodation_cost

    food_cost = normalized.get("food")
    food_assumption = ""
    if not isinstance(food_cost, (int, float)):
        food_cost, food_assumption = _estimate_food_cost_from_itinerary(
            state,
            itinerary,
            travel_days,
            total_people,
        )
        normalized["food"] = food_cost

    attractions_cost = normalized.get("attractions")
    attractions_assumption = ""
    if not isinstance(attractions_cost, (int, float)):
        attractions_cost, attractions_assumption = _estimate_attractions_cost(
            destination_context,
            itinerary,
            travel_days,
            total_people,
            state.get("scenic_price_evidence"),
        )
        normalized["attractions"] = attractions_cost

    misc_cost = normalized.get("misc")
    if not isinstance(misc_cost, (int, float)):
        misc_cost = 100 * travel_days * total_people
        normalized["misc"] = misc_cost

    normalized.setdefault("currency", "CNY")
    normalized.setdefault("travel_days", travel_days)
    normalized.setdefault("nights", max(travel_days - 1, 1))
    normalized.setdefault("total_people", total_people)
    if not isinstance(normalized.get("total"), (int, float)):
        normalized["total"] = (
            transport_cost
            + accommodation_cost
            + food_cost
            + attractions_cost
            + misc_cost
        )
    if not isinstance(normalized.get("per_person"), (int, float)):
        normalized["per_person"] = _safe_per_person(normalized["total"], total_people)
    if not normalized.get("assumptions"):
        assumptions = [
            "交通按已选具体方案价格估算；缺少具体价格时按交通类型基准估算。",
            accommodation_assumption
            or "住宿按已确认预算明细估算；缺少具体酒店价格时使用兜底每间夜规则。",
            food_assumption
            or "餐饮按已确认预算明细估算；缺少具体餐饮 POI 时按偏好类型兜底。",
            attractions_assumption
            or "景点/体验按已确认预算明细估算；缺少结构化 POI 时保留待核验项。",
            "其他机动费用按 100 元/人/天估算，用于市内交通、临时休息、寄存和小额杂费。",
        ]
        normalized["assumptions"] = [item for item in assumptions if item]

    quality_notes = _build_budget_quality_notes(
        state,
        destination_context,
        itinerary,
    )

    if not normalized.get("confidence_level"):
        normalized["confidence_level"] = quality_notes["confidence_level"]
    for key in ["confirmed_items", "estimated_items", "verification_items"]:
        if not normalized.get(key):
            normalized[key] = list(quality_notes[key])

    _add_departure_date_verification_item(normalized, requirement)

    if not normalized.get("line_items"):
        normalized["line_items"] = _build_budget_line_items(
            state,
            itinerary,
            travel_days,
            total_people,
            transport_cost,
            accommodation_cost,
            food_cost,
            attractions_cost,
            misc_cost,
        )

    normalized["budget_confidence"] = _budget_confidence_payload(normalized)
    if not normalized.get("quote_policy"):
        product = build_light_product(requirement, state)
        normalized["quote_policy"] = build_quote_policy(
            requirement,
            normalized,
            product=product,
            state=state,
        )
    return normalized


def _get_destination_context(state: TravelState, destination: str) -> dict:
    options = state.get("destination_options") or []
    if not options:
        return {}

    normalized_destination = str(destination).strip()
    for option in options:
        if option.get("name") == normalized_destination:
            return option
    return options[0]


def _normalize_poi(item: object) -> dict:
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip()
        if not name:
            return {}
        profile = dict(KNOWN_POI_PROFILES.get(name, {}))
        profile.update({key: value for key, value in item.items() if value not in (None, "", [])})
        profile["name"] = name
        return profile

    name = str(item).strip()
    if not name:
        return {}
    profile = dict(KNOWN_POI_PROFILES.get(name, {}))
    profile["name"] = name
    profile.setdefault("area", "区域待确认")
    profile.setdefault("best_time", "时间灵活")
    profile.setdefault("duration_hours", 1.5)
    profile.setdefault("reservation_required", False)
    profile.setdefault("indoor", False)
    profile.setdefault("estimated_cost", 0.0)
    profile.setdefault("tags", [])
    return profile


def _get_destination_pois(destination_context: dict) -> list[dict]:
    raw_pois = destination_context.get("attraction_pois") or destination_context.get("pois")
    if not raw_pois:
        raw_pois = destination_context.get("attractions") or []
    pois = [_normalize_poi(item) for item in raw_pois]
    return [poi for poi in pois if poi.get("name")]


def _default_destination_pois(destination: str) -> list[dict]:
    names = DEFAULT_DESTINATION_ATTRACTIONS.get(str(destination or "").strip(), [])
    pois = [_normalize_poi(name) for name in names]
    return [poi for poi in pois if poi.get("name")]


def _destination_pois_for_report(state: TravelState, requirement: dict) -> list[dict]:
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    destination_context = _get_destination_context(state, destination)
    return _get_destination_pois(destination_context) or _default_destination_pois(destination)


def _recommended_accommodation_area(destination: str) -> str:
    normalized = str(destination or "").strip()
    return DEFAULT_ACCOMMODATION_AREAS.get(normalized) or f"{normalized or '目的地'}交通便利核心区"


def _build_fallback_accommodation_option(
    state: TravelState,
    requirement: dict,
) -> dict:
    selected = state.get("selected_accommodation_option") or {}
    if selected.get("name"):
        return dict(selected)

    for option in state.get("accommodation_options") or []:
        if option.get("name"):
            return dict(option)

    destination = state.get("selected_destination") or requirement.get("destination") or ""
    area = _recommended_accommodation_area(destination)
    return {
        "name": f"{area}附近舒适型酒店",
        "location": area,
        "type": "comfort_hotel",
        "amenities": ["交通便利", "便于晚间返回", "价格需二次核实"],
        "status": "待二次核实",
    }


def _pick_report_pois_for_day(
    pois: list[dict],
    day_number: int,
    expected_days: int,
) -> list[dict]:
    if not pois:
        return []
    if day_number == 1:
        evening_first = [
            poi
            for poi in pois
            if any(token in str(poi.get("best_time") or "") for token in ["傍晚", "晚上"])
        ]
        return (evening_first or pois)[:1]
    if day_number == expected_days:
        start = min(max(len(pois) - 2, 0), max((day_number - 1) * 2, 0))
        return _pick_pois_by_area(pois, start, 1) or pois[-1:]
    start = max((day_number - 2) * 2 + 1, 0)
    return _pick_pois_by_area(pois, start, 2)


def _area_tokens(area: object) -> list[str]:
    if not area:
        return []
    text = str(area)
    for separator in ["、", "/", "／", ",", "，", "及", "和"]:
        text = text.replace(separator, "|")
    tokens = []
    for raw_token in text.split("|"):
        token = raw_token.strip()
        if not token:
            continue
        tokens.append(token)
        simplified = token.removesuffix("周边").removesuffix("区域").strip()
        if simplified and simplified != token:
            tokens.append(simplified)
    return tokens


def _areas_overlap(left: object, right: object) -> bool:
    left_tokens = _area_tokens(left)
    right_tokens = _area_tokens(right)
    return any(
        left_token in right_token or right_token in left_token
        for left_token in left_tokens
        for right_token in right_tokens
    )


def _format_area_list(pois: list[dict]) -> str:
    areas = []
    for poi in pois:
        area = poi.get("area")
        if area and str(area) not in areas:
            areas.append(str(area))
    return "、".join(areas)


def _pick_pois_by_area(pois: list[dict], start: int, count: int) -> list[dict]:
    if start >= len(pois) or count <= 0:
        return []

    seed = pois[start]
    selected = [seed]
    remaining = pois[start + 1:]

    for candidate in remaining:
        if len(selected) >= count:
            break
        if _areas_overlap(seed.get("area"), candidate.get("area")):
            selected.append(candidate)

    for candidate in remaining:
        if len(selected) >= count:
            break
        if candidate not in selected:
            selected.append(candidate)

    return selected


def _poi_names(pois: list[dict]) -> list[str]:
    return [str(poi["name"]) for poi in pois if poi.get("name")]


def _format_poi_summary(poi: dict) -> str:
    name = poi.get("name", "未命名体验")
    area = poi.get("area")
    best_time = poi.get("best_time")
    duration = poi.get("duration_hours")
    tags = "、".join(poi.get("tags") or [])
    parts = [str(name)]
    meta = []
    if area:
        meta.append(str(area))
    if best_time:
        meta.append(str(best_time))
    if isinstance(duration, (int, float)):
        meta.append(f"约 {duration:g} 小时")
    if tags:
        meta.append(tags)
    if meta:
        parts.append(f"（{'；'.join(meta)}）")
    return "".join(parts)


def _format_poi_activity(pois: list[dict], fallback: str) -> str:
    if not pois:
        return fallback
    return "同区域安排：" + "、".join(_format_poi_summary(poi) for poi in pois)


def _format_reservation_note(pois: list[dict]) -> str:
    notes = []
    for poi in pois:
        name = poi.get("name")
        if not name:
            continue
        if poi.get("reservation_required"):
            notes.append(f"{name} 建议提前预约/购票")
        cost = poi.get("estimated_cost")
        if isinstance(cost, (int, float)) and cost > 0:
            notes.append(f"{name} 参考门票/体验费约 {cost:g} 元/人")
    return "；".join(notes)


def _format_indoor_backup(pois: list[dict]) -> Optional[str]:
    indoor_names = [str(poi["name"]) for poi in pois if poi.get("indoor") and poi.get("name")]
    if indoor_names:
        return "室内备选：" + "、".join(indoor_names)
    return None


def _normalize_food_poi(item: object, fallback_type: str = "local") -> dict:
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip()
        if not name:
            return {}
        profile = dict(KNOWN_FOOD_POI_PROFILES.get(name, {}))
        profile.update({key: value for key, value in item.items() if value not in (None, "", [])})
        profile["name"] = name
        profile.setdefault("type", fallback_type)
        return profile

    name = str(item).strip()
    if not name:
        return {}
    profile = dict(KNOWN_FOOD_POI_PROFILES.get(name, {}))
    profile["name"] = name
    profile.setdefault("type", fallback_type)
    profile.setdefault("area", "区域待确认")
    profile.setdefault("meal_time", "餐次灵活")
    profile.setdefault("average_cost", FOOD_DAILY_COST_PER_PERSON.get(fallback_type, 130))
    profile.setdefault("reservation_required", False)
    profile.setdefault("queue_risk", "中")
    profile.setdefault("suitable_for", [])
    profile.setdefault("tags", [])
    return profile


def _default_food_pois(food_types: list[str], destination: str = "") -> list[dict]:
    normalized_destination = str(destination or "").strip()
    defaults_by_type = DEFAULT_DESTINATION_FOOD_POIS.get(normalized_destination) or {
        "local": ["南京路小吃", "城隍庙小吃"],
        "specialty": ["本帮菜餐厅"],
        "chain": ["商场连锁简餐"],
    }
    food_pois = []
    for food_type in food_types or ["local"]:
        normalized_type = food_type if food_type in FOOD_LABELS else "local"
        for name in defaults_by_type.get(normalized_type, []):
            food_pois.append(_normalize_food_poi(name, normalized_type))
    return food_pois or [_normalize_food_poi("商场连锁简餐", "chain")]


def _get_food_pois(state: TravelState) -> list[dict]:
    raw_pois = state.get("selected_food_pois") or []
    if not raw_pois:
        for option in state.get("food_options") or []:
            raw_pois.extend(option.get("food_pois") or [])
            raw_pois.extend(option.get("recommendations") or [])
    if raw_pois:
        pois = [_normalize_food_poi(item) for item in raw_pois]
        return [poi for poi in pois if poi.get("name")]
    requirement = state.get("user_requirement") or {}
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    return _default_food_pois(state.get("selected_food_types") or [], str(destination))


def _pick_food_poi(
    food_pois: list[dict],
    index: int,
    *,
    target_area: Optional[str] = None,
    meal_keyword: Optional[str] = None,
    exclude_names: Optional[set[str]] = None,
) -> Optional[dict]:
    if not food_pois:
        return None
    exclude_names = exclude_names or set()
    offset = index % len(food_pois)
    ordered_pois = food_pois[offset:] + food_pois[:offset]
    fallback = next(
        (poi for poi in ordered_pois if poi.get("name") not in exclude_names),
        ordered_pois[0],
    )
    best_poi = fallback
    best_score = -1
    for food_poi in ordered_pois:
        if food_poi.get("name") in exclude_names:
            continue
        score = 0
        if target_area and _areas_overlap(target_area, food_poi.get("area")):
            score += 4
        meal_time = str(food_poi.get("meal_time") or "")
        if meal_keyword and (meal_keyword in meal_time or "灵活" in meal_time):
            score += 2
        queue_risk = food_poi.get("queue_risk")
        if queue_risk == "低":
            score += 1
        if score > best_score:
            best_score = score
            best_poi = food_poi
    return best_poi


def _format_food_poi_summary(food_poi: Optional[dict], fallback: str) -> str:
    if not food_poi:
        return fallback
    name = food_poi.get("name", "餐饮待确认")
    area = food_poi.get("area")
    meal_time = food_poi.get("meal_time")
    average_cost = food_poi.get("average_cost")
    tags = "、".join(food_poi.get("tags") or [])
    meta = []
    if area:
        meta.append(str(area))
    if meal_time:
        meta.append(str(meal_time))
    if isinstance(average_cost, (int, float)):
        meta.append(f"人均约 {average_cost:g} 元")
    if tags:
        meta.append(tags)
    return f"{name}（{'；'.join(meta)}）" if meta else str(name)


def _format_food_booking_note(food_pois: list[dict]) -> Optional[str]:
    notes = []
    for food_poi in food_pois:
        name = food_poi.get("name")
        if not name:
            continue
        if food_poi.get("reservation_required"):
            notes.append(f"{name} 建议提前预约")
        queue_risk = food_poi.get("queue_risk")
        if queue_risk and queue_risk != "低":
            notes.append(f"{name} 排队风险{queue_risk}，建议错峰")
    return "；".join(notes) if notes else None


def _format_attraction_activity(attractions: list[str], fallback: str) -> str:
    if not attractions:
        return fallback
    return "同区域安排：" + "、".join(attractions)


def _format_weather_plan_b(weather_info: object) -> str:
    if weather_info:
        return (
            f"天气提醒：{weather_info}。如遇下雨、太热或体力不足，"
            "优先切换到室内展馆、商场或酒店周边轻松活动。"
        )
    return "如遇下雨、太热或体力不足，优先切换到室内展馆、商场或酒店周边轻松活动。"


def _format_food_preferences(food_types: list[str]) -> str:
    labels = [FOOD_LABELS.get(food_type, food_type) for food_type in food_types]
    return "、".join(labels) if labels else "待确认"


def _format_budget_breakdown(budget: dict) -> list[str]:
    return format_budget_breakdown(budget)


def _format_budget_assumptions(budget: dict) -> list[str]:
    return format_budget_assumptions(budget)


def _format_budget_confidence(budget: dict) -> list[str]:
    return format_budget_confidence(budget)


def _format_budget_verification_items(budget: dict) -> list[str]:
    return format_budget_verification_items(budget)


def _format_budget_fit(requirement: dict, budget: dict) -> str:
    return format_budget_fit(requirement, budget)


def _format_adjustment_options(state: TravelState, budget: dict) -> list[str]:
    requirement = state.get("user_requirement") or {}
    return build_adjustment_options(requirement, budget)


def _format_report_people(requirement: dict) -> str:
    return format_report_people(requirement)


def _format_report_duration(requirement: dict) -> str:
    return format_report_duration(requirement)


def _format_report_route_label(state: TravelState, requirement: dict) -> str:
    return format_report_route_label(state, requirement)


def _route_builder_services() -> RouteBuilderServices:
    return RouteBuilderServices(
        recommended_accommodation_area=_recommended_accommodation_area,
        destination_pois_for_report=_destination_pois_for_report,
        pick_report_pois_for_day=_pick_report_pois_for_day,
        poi_names=_poi_names,
        format_poi_activity=_format_poi_activity,
        format_reservation_note=_format_reservation_note,
        format_indoor_backup=_format_indoor_backup,
        get_destination_context=_get_destination_context,
        get_food_pois=_get_food_pois,
        pick_food_poi=_pick_food_poi,
        format_food_poi_summary=_format_food_poi_summary,
        format_weather_plan_b=_format_weather_plan_b,
        build_fallback_accommodation_option=_build_fallback_accommodation_option,
    )


def _dedupe_report_points(points: list[str], max_items: int = 6) -> list[str]:
    return dedupe_route_points(points, max_items)


def _is_pending_route_point(point: str) -> bool:
    return is_pending_route_point(point)


def _collect_report_route_candidates(state: TravelState) -> list[str]:
    return collect_report_route_candidates(state)


def _route_points_have_specific_visual_node(
    points: list[str],
    *,
    destination: str,
    departure_city: str,
    accommodation_points: Optional[list[str]] = None,
) -> bool:
    return route_points_have_specific_visual_node(
        points,
        destination=destination,
        departure_city=departure_city,
        accommodation_points=accommodation_points,
    )


def _fallback_report_route_points_for_day(
    day_number: int,
    expected_days: int,
    state: TravelState,
    requirement: dict,
) -> list[str]:
    return fallback_report_route_points_for_day(
        day_number,
        expected_days,
        state,
        requirement,
        _route_builder_services(),
    )


def _format_report_route_points(
    day: dict,
    state: TravelState,
    requirement: dict,
) -> list[str]:
    return format_report_route_points(
        day,
        state,
        requirement,
        _route_builder_services(),
    )


def _get_expected_travel_days(requirement: dict, fallback: int = 0) -> int:
    return get_expected_travel_days(requirement, fallback)


def _build_placeholder_itinerary_day(
    day_number: int,
    expected_days: int,
    state: TravelState,
    requirement: dict,
) -> dict:
    return build_placeholder_itinerary_day(
        day_number,
        expected_days,
        state,
        requirement,
        _route_builder_services(),
    )


def _build_day_route_summary(day: dict, state: TravelState, requirement: dict) -> dict:
    return build_day_route_summary(day, state, requirement, _route_builder_services())


def _enrich_itinerary_day_for_report(
    day: dict,
    state: TravelState,
    requirement: dict,
) -> dict:
    return enrich_itinerary_day_for_report(
        day,
        state,
        requirement,
        _route_builder_services(),
    )


def _ensure_itinerary_day_count(
    itinerary: list[dict],
    state: TravelState,
    requirement: dict,
) -> list[dict]:
    return ensure_itinerary_day_count(
        itinerary,
        state,
        requirement,
        _route_builder_services(),
    )


def _valid_journey_plan_from_state(state: TravelState) -> dict:
    journey_plan = state.get("journey_plan")
    if not isinstance(journey_plan, dict):
        return {}
    if journey_plan.get("version") != JOURNEY_PLAN_VERSION:
        return {}
    ok, _findings = validate_journey_plan(journey_plan)
    return journey_plan if ok else {}


def _journey_plan_destination(journey_plan: dict) -> str:
    overview = journey_plan.get("overview") or {}
    return str(overview.get("destination") or "").strip()


def _journey_day_pois(day: dict) -> list[dict]:
    pois = [dict(poi) for poi in day.get("pois") or [] if isinstance(poi, dict)]
    return sorted(
        pois,
        key=lambda poi: (
            int(poi.get("order") or poi.get("sequence") or 999),
            str(poi.get("id") or poi.get("name") or ""),
        ),
    )


def _journey_poi_names(pois: list[dict]) -> list[str]:
    return dedupe_route_points(
        [str(poi.get("name") or "").strip() for poi in pois],
        max_items=8,
    )


def _format_journey_poi_activity(poi: dict) -> str:
    name = str(poi.get("name") or "待核验地点").strip()
    description = str(poi.get("description") or "").strip()
    if description:
        return f"{name}：{description}"
    return name


def _format_journey_poi_time_block(poi: dict) -> str:
    time_text = str(poi.get("suggested_time") or "时间待定").strip()
    name = str(poi.get("name") or "待核验地点").strip()
    description = str(poi.get("description") or "").strip()
    cost = str(poi.get("estimated_cost") or "").strip()
    reservation = str(poi.get("reservation_note") or "").strip()
    suffixes = []
    if cost and cost != "待核验":
        suffixes.append(f"费用参考：{cost}")
    if reservation:
        suffixes.append(reservation)
    suffix = f"（{'；'.join(suffixes)}）" if suffixes else ""
    body = f"{name}｜{description}" if description else name
    return f"{time_text}：{body}{suffix}"


def _build_itinerary_from_journey_plan(
    journey_plan: dict,
    state: TravelState,
    requirement: dict,
    *,
    selected_transport_option: dict,
    selected_accommodation: dict,
    selected_food_types: list[str],
) -> list[dict]:
    """Convert the saved map-first journey draft into the formal itinerary state."""

    overview = journey_plan.get("overview") or {}
    destination = (
        state.get("selected_destination")
        or requirement.get("destination")
        or overview.get("destination")
        or "目的地"
    )
    transport_summary = _format_transport_option(selected_transport_option)
    accommodation_summary = _format_accommodation_option(selected_accommodation)
    food_summary = "、".join(FOOD_LABELS.get(item, item) for item in selected_food_types)
    pending_checks = [
        str(item)
        for item in journey_plan.get("pending_checks") or []
        if str(item).strip()
    ]
    strategy_summary = str(
        (journey_plan.get("route_strategy") or {}).get("summary")
        or overview.get("summary")
        or "按已保存可视化路线草案执行"
    )
    itinerary: list[dict] = []
    days = [
        dict(day)
        for day in journey_plan.get("days") or []
        if isinstance(day, dict) and day.get("pois")
    ]
    days.sort(key=lambda day: int(day.get("day_number") or len(itinerary) + 1))

    for index, day in enumerate(days, start=1):
        day_number = int(day.get("day_number") or index)
        pois = _journey_day_pois(day)
        poi_names = _journey_poi_names(pois)
        city = str(day.get("city") or destination).strip()
        title = str(day.get("title") or f"{city}经典动线").strip()
        weather = day.get("weather") if isinstance(day.get("weather"), dict) else {}
        accommodation = (
            selected_accommodation.get("name")
            or selected_accommodation.get("location")
            or f"{city}交通便利区域住宿"
        )
        time_blocks = [_format_journey_poi_time_block(poi) for poi in pois]
        if food_summary:
            time_blocks.append(f"餐饮安排：结合 {food_summary}，优先贴合当天路线顺序就近安排。")
        if weather.get("summary"):
            time_blocks.append(f"天气/Plan B：{weather['summary']}")

        route_note_parts = [
            str(day.get("route_note") or "").strip(),
            "本日顺序来自已保存的可视化旅程草案，保留用户在地图工作台里的编辑结果。",
        ]
        if strategy_summary:
            route_note_parts.append(f"整体路线逻辑：{strategy_summary}")

        day_plan = {
            "day_number": day_number,
            "date": day.get("date") or "",
            "theme": title,
            "activities": [_format_journey_poi_activity(poi) for poi in pois],
            "route_points": poi_names,
            "time_blocks": time_blocks,
            "meals": [
                "早餐：以酒店/周边省心用餐为主",
                "午餐：贴合上午景点顺路安排，避免额外跨区。",
                "晚餐：结合已确认餐饮偏好，优先选择当天落脚区域。",
            ],
            "accommodation": accommodation,
            "transport_note": (
                transport_summary
                if day_number == 1
                else "当天交通按地图草案点位顺序串联；具体距离、时长和路况以高德实时路线二次核验。"
            ),
            "plan_b": weather.get("summary")
            or "如遇天气、排队或体力变化，优先减少远途点并保留休息时间。",
            "route_note": " ".join(part for part in route_note_parts if part),
            "risk_notes": [
                "该日由可视化旅程草案转为正式行程，交通距离、门票、预约和开放时间仍需出发前二次核验。",
                *pending_checks[:2],
            ],
        }
        itinerary.append(_enrich_itinerary_day_for_report(day_plan, state, requirement))

    return itinerary


def _format_report_risk_lines(
    itinerary: list[dict],
    budget: dict,
    state: Optional[TravelState] = None,
    requirement: Optional[dict] = None,
) -> list[str]:
    weather_info = None
    if state is not None:
        current_requirement = requirement or {}
        destination = state.get("selected_destination") or current_requirement.get("destination") or ""
        weather_info = _get_destination_context(state, destination).get("weather_info")
    return build_report_risk_lines(
        itinerary,
        budget,
        weather_info=weather_info,
    )


_internal_doc_highlights = agency_product_rules.internal_doc_highlights
_internal_doc_evidence = agency_product_rules.internal_doc_evidence
_fallback_internal_evidence = agency_product_rules.fallback_internal_evidence


def _normalize_planning_mode(value: Optional[str]) -> str | None:
    if value is None:
        return None
    return PLANNING_MODE_ALIASES.get(str(value).strip())


def _state_planning_mode(state: TravelState | None) -> str | None:
    if not state:
        return None

    state_mode = _normalize_planning_mode(state.get("active_workflow"))
    if state_mode == "agency_plan":
        return state_mode
    if state_mode == "free_planning" and bool(state.get("planning_mode_confirmed")):
        return state_mode

    state_mode = _normalize_planning_mode(state.get("planning_mode"))
    if state_mode:
        return state_mode

    requirement = state.get("user_requirement") or {}
    if isinstance(requirement, dict):
        return _normalize_planning_mode(requirement.get("planning_mode"))
    return None


def _infer_planning_mode(requirement: dict, state: TravelState | None = None) -> str:
    explicit_mode = _normalize_planning_mode(requirement.get("planning_mode")) or _state_planning_mode(state)
    if explicit_mode:
        return explicit_mode
    return agency_product_rules.infer_report_planning_mode(requirement, state)


def _agency_signal_mode(requirement: dict, state: TravelState | None = None) -> str | None:
    inferred = agency_product_rules.infer_report_planning_mode(requirement, state)
    return inferred if inferred == "agency_plan" else None


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "title", "summary", "description", "content", "text"):
            if value.get(key):
                return str(value[key]).strip()
        return "；".join(
            f"{key}:{item}"
            for key, item in value.items()
            if item is not None and str(item).strip()
        )
    if isinstance(value, (list, tuple, set)):
        return "；".join(_coerce_text(item) for item in value if _coerce_text(item))
    return str(value).strip()


def _coerce_attractions(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    attractions: list[str] = []
    for item in items:
        text = _coerce_text(item)
        if text:
            attractions.append(text)
    return attractions


def _coerce_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return float(match.group(0))


def _pick_highlight(lines: list[str], keywords: tuple[str, ...], fallback_index: int = 0) -> str | None:
    return agency_product_rules._pick_highlight(lines, keywords, fallback_index)


def _build_agency_context(requirement: dict, state: TravelState | None = None) -> dict:
    return build_agency_context(requirement, state)


def _format_agency_context_lines(agency_context: dict) -> list[str]:
    return format_agency_context_lines(agency_context)


def _clean_report_line(line: str) -> str:
    return str(line).strip().lstrip("-").strip()


def _build_report_evidence_bundle(
    agency_context: dict,
    budget: dict,
    route_summaries: list[dict],
    selected_transport_option: dict,
    selected_accommodation: dict,
    tool_audit_events: list[dict] | None = None,
) -> dict:
    return build_report_evidence_bundle(
        agency_context,
        budget,
        route_summaries,
        selected_transport_option,
        selected_accommodation,
        tool_audit_events,
    )


def _build_report_tool_audit_summary(
    budget: dict,
    route_summaries: list[dict],
    selected_transport_option: dict,
    selected_accommodation: dict,
    tool_audit_events: list[dict] | None = None,
) -> dict:
    return build_report_tool_audit_summary(
        budget,
        route_summaries,
        selected_transport_option,
        selected_accommodation,
        tool_audit_events,
    )


def _approval_report_payload(approval_update: dict) -> dict:
    governance = approval_update.get("approval_governance") or {}
    return {
        "approval_id": approval_update.get("approval_record_id"),
        "action": approval_update.get("approval_action"),
        "status": approval_update.get("approval_status"),
        "pending": approval_update.get("approval_pending", False),
        "requires_approval": approval_update.get("approval_required", False),
        "is_blocking": governance.get("is_blocking", False),
        "record_only": governance.get("record_only", True),
        "expires_at": approval_update.get("approval_expires_at"),
        "reason": approval_update.get("approval_reason") or "",
        "boundary": governance.get("boundary") or "",
        "unsupported_without_integration": list(
            governance.get("unsupported_without_integration") or []
        ),
    }


def _build_report_data(
    state: TravelState,
    requirement: dict,
    budget: dict,
    itinerary: list[dict],
    selected_transport_option: dict,
    selected_accommodation: dict,
    selected_food_types: list[str],
) -> dict:
    route_summaries = build_route_summaries(
        itinerary,
        state,
        requirement,
        _route_builder_services(),
    )
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    weather_info = _get_destination_context(state, destination).get("weather_info")
    return build_travel_report_data(
        state=state,
        requirement=requirement,
        budget=budget,
        itinerary=itinerary,
        route_summaries=route_summaries,
        selected_transport_option=selected_transport_option,
        selected_accommodation=selected_accommodation,
        selected_food_types=selected_food_types,
        transport_label=TRANSPORT_LABELS.get(
            state.get("selected_transport"),
            state.get("selected_transport", "未确认"),
        ),
        transport_summary=_format_transport_option(selected_transport_option),
        accommodation_summary=_format_accommodation_option(selected_accommodation),
        food_preferences_summary=_format_food_preferences(selected_food_types),
        weather_info=weather_info,
    )


def _build_final_report(
    state: TravelState,
    requirement: dict,
    budget: dict,
    itinerary: list[dict],
    selected_transport_option: dict,
    selected_accommodation: dict,
    selected_food_types: list[str],
) -> str:
    itinerary = _ensure_itinerary_day_count(itinerary, state, requirement)
    report_data = _build_report_data(
        state,
        requirement,
        budget,
        itinerary,
        selected_transport_option,
        selected_accommodation,
        selected_food_types,
    )
    bundle = build_report_bundle(report_data)
    if not bundle.validation.ok:
        return bundle.validation.to_user_message()
    return bundle.markdown


def _requirement_has_confirmed_departure_date(requirement: dict[str, Any]) -> bool:
    departure_date = requirement.get("departure_date")
    if _is_pending_requirement_value(departure_date):
        return False
    if _parse_requirement_date_text(departure_date) is None:
        return False
    if requirement.get("departure_date_confirmed") is False:
        return False
    return True


def _add_departure_date_verification_item(
    budget: dict[str, Any],
    requirement: dict[str, Any],
) -> None:
    if _requirement_has_confirmed_departure_date(requirement):
        return
    item = "出发日期：当前为日期待确认，真实交通、酒店、门票和天气窗口需在用户确认日期后复核。"
    verification_items = budget.setdefault("verification_items", [])
    if item not in verification_items:
        verification_items.append(item)


def _has_confirmed_transport_state(state: TravelState) -> bool:
    return bool(state.get("selected_transport") or state.get("selected_transport_option"))


def _has_confirmed_accommodation_state(state: TravelState) -> bool:
    return bool(
        state.get("selected_accommodation_option")
        or state.get("selected_accommodation_types")
    )


def _normalize_accommodation_type_for_state(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in ACCOMMODATION_LABELS:
        return raw
    lowered = raw.lower().replace("-", "_").replace(" ", "_")
    if lowered in ACCOMMODATION_LABELS:
        return lowered
    if lowered in ACCOMMODATION_STATE_TYPE_ALIASES:
        return ACCOMMODATION_STATE_TYPE_ALIASES[lowered]
    if raw in ACCOMMODATION_STATE_TYPE_ALIASES:
        return ACCOMMODATION_STATE_TYPE_ALIASES[raw]
    for keyword, normalized in ACCOMMODATION_STATE_TYPE_ALIASES.items():
        if keyword and keyword in raw:
            return normalized
    return None


def _infer_selected_accommodation_types_for_state(state: TravelState) -> list[str]:
    existing = _as_string_list(state.get("selected_accommodation_types"))
    normalized_existing = []
    for item in existing:
        normalized = _normalize_accommodation_type_for_state(item)
        if normalized and normalized not in normalized_existing:
            normalized_existing.append(normalized)
    if normalized_existing:
        return normalized_existing

    accommodation_sources = []
    selected = state.get("selected_accommodation_option")
    if isinstance(selected, dict):
        accommodation_sources.append(selected)
    accommodation_sources.extend(
        option for option in state.get("accommodation_options") or [] if isinstance(option, dict)
    )
    for option in accommodation_sources:
        for key in ("type", "category", "hotel_type", "type_label", "name", "location"):
            normalized = _normalize_accommodation_type_for_state(option.get(key))
            if normalized:
                return [normalized]
    if accommodation_sources:
        return ["star_hotel"]
    return []


@tool
def record_requirement_tool(
    departure_city: Any = None,
    departure_date: Any = None,
    travel_days: Any = None,
    budget_min: Any = None,
    budget_max: Any = None,
    travel_styles: Any = None,
    special_needs: Any = "",
    adult_count: Any = 1,
    children_count: Any = 0,
    destination: Any = None,
    planning_mode: Any = None,
    planning_mode_reason: Any = "",
    planning_mode_confirmed: Any = True,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist the confirmed requirement summary and move to destination selection."""

    runtime_state = _runtime_state(runtime)
    existing_confirmed_facts = _state_confirmed_facts(runtime_state)
    assumption_notes: list[str] = []
    departure_city = _normalize_requirement_text(departure_city)
    if _is_pending_requirement_value(departure_city) and existing_confirmed_facts.get("departure_city"):
        departure_city = str(existing_confirmed_facts["departure_city"])
    if _is_pending_requirement_value(departure_city):
        departure_city = "出发地待确认"
        assumption_notes.append("出发地未明确，暂按出发地待确认处理")

    destination = _normalize_requirement_text(destination)
    if _is_pending_requirement_value(destination) and existing_confirmed_facts.get("destination"):
        destination = str(existing_confirmed_facts["destination"])
    if _is_pending_requirement_value(destination):
        destination = None

    planning_mode = _normalize_requirement_text(planning_mode)
    if _is_pending_requirement_value(planning_mode):
        planning_mode = None
    planning_mode_reason = _normalize_requirement_text(planning_mode_reason)
    planning_mode_confirmed = _coerce_bool(planning_mode_confirmed, default=True)

    departure_date_input = departure_date
    if (
        _is_pending_requirement_value(_normalize_requirement_text(departure_date_input))
        and existing_confirmed_facts.get("departure_date")
    ):
        departure_date_input = existing_confirmed_facts["departure_date"]
    departure_date, date_assumed, departure_date_confirmed = _normalize_requirement_date(
        departure_date_input,
        runtime,
    )
    if date_assumed:
        assumption_notes.append(
            "出发日期未明确，日期待确认；真实交通、酒店和票务查询需等用户明确或确认日期后再执行"
        )

    if _is_pending_requirement_value(travel_days) and existing_confirmed_facts.get("travel_days"):
        travel_days = existing_confirmed_facts["travel_days"]
    travel_days, days_assumed = _coerce_positive_int(travel_days, default=1)
    if days_assumed:
        assumption_notes.append("行程天数未明确，暂按 1 天估算")

    adult_count, adult_assumed = _coerce_positive_int(adult_count, default=1)
    if adult_assumed:
        assumption_notes.append("成人数量未明确，暂按 1 位成人估算")
    children_count, children_assumed = _coerce_non_negative_int(children_count, default=0)
    if children_assumed:
        assumption_notes.append("儿童数量未明确，暂按无儿童估算")

    normalized_budget_min = _coerce_float(budget_min)
    normalized_budget_max = _coerce_float(budget_max)
    if not normalized_budget_min or normalized_budget_min <= 0:
        normalized_budget_min = DEFAULT_BUDGET_MIN_PER_PERSON
        assumption_notes.append(
            f"预算下限未明确，暂按每人 {normalized_budget_min:.0f} 元估算"
        )
    if not normalized_budget_max or normalized_budget_max <= 0:
        normalized_budget_max = DEFAULT_BUDGET_MAX_PER_PERSON
        assumption_notes.append(
            f"预算上限未明确，暂按每人 {normalized_budget_max:.0f} 元估算"
        )
    if normalized_budget_min > normalized_budget_max:
        normalized_budget_min, normalized_budget_max = (
            normalized_budget_max,
            normalized_budget_min,
        )
    budget_min = normalized_budget_min
    budget_max = normalized_budget_max

    travel_styles = _normalize_requirement_styles(travel_styles)
    if not travel_styles:
        travel_styles = ["轻松舒适"]
        assumption_notes.append("旅行风格未结构化，暂按轻松舒适估算")
    special_needs = _append_requirement_assumptions(special_needs, assumption_notes)

    app_logger.info(
        f"记录用户需求: {departure_date}, {travel_days}天, 预算 {budget_min}-{budget_max}"
    )

    budget_level = _budget_level_from_range(budget_min, budget_max)
    total_people = (adult_count or 0) + (children_count or 0)
    mode_seed = {
        "special_needs": special_needs or "",
        "travel_styles": travel_styles,
        "destination": destination or "",
    }
    pending_initial_request_text = ""
    pending_initial_planning_mode = None
    pending_initial_planning_mode_reason = ""
    if runtime and runtime.state:
        pending_initial_request_text = _normalize_requirement_text(
            runtime.state.get("pending_initial_request_text")
        )
        pending_initial_planning_mode = _normalize_planning_mode(
            runtime.state.get("pending_initial_planning_mode")
        )
        pending_initial_planning_mode_reason = _normalize_requirement_text(
            runtime.state.get("pending_initial_planning_mode_reason")
        )
    mode_inference_seed = {
        **mode_seed,
        "special_needs": " ".join(
            item
            for item in [
                str(mode_seed.get("special_needs") or ""),
                pending_initial_request_text,
                planning_mode_reason,
                pending_initial_planning_mode_reason,
            ]
            if item
        ),
    }
    user_mode_inference_seed = {
        **mode_seed,
        "special_needs": " ".join(
            item
            for item in [
                str(mode_seed.get("special_needs") or ""),
                pending_initial_request_text,
            ]
            if item
        ),
    }
    mode_context_text = agency_product_rules.requirement_text(
        user_mode_inference_seed,
        runtime.state if runtime else None,
    )
    inferred_text_mode = None
    explicit_agency_signal = has_explicit_agency_signal(mode_context_text)
    explicit_agency_plan_signal = has_explicit_agency_plan_signal(mode_context_text)
    explicit_free_signal = has_explicit_free_signal(mode_context_text)
    if explicit_agency_signal or explicit_free_signal:
        inferred_text_mode = _infer_planning_mode(
            mode_inference_seed,
            runtime.state if runtime else None,
        )
    inferred_state_agency_mode = _agency_signal_mode(
        user_mode_inference_seed,
        runtime.state if runtime else None,
    )
    tool_planning_mode = _normalize_planning_mode(planning_mode)
    if not tool_planning_mode and pending_initial_planning_mode and explicit_agency_signal:
        tool_planning_mode = pending_initial_planning_mode
        planning_mode_reason = planning_mode_reason or pending_initial_planning_mode_reason
    state_mode = _state_planning_mode(runtime.state if runtime else None)
    if tool_planning_mode == "agency_plan" and not explicit_agency_signal and state_mode != "agency_plan":
        tool_planning_mode = None
        planning_mode_reason = (
            "未发现用户明确旅行社/省心方案/报价服务信号，保持自由规划"
        )
    if tool_planning_mode == "agency_plan" and explicit_free_signal and not explicit_agency_plan_signal:
        tool_planning_mode = "free_planning"
        planning_mode_reason = (
            planning_mode_reason
            or "已按用户明确自由行/自助规划诉求修正为自由规划"
        )
    if tool_planning_mode == "free_planning" and (
        inferred_text_mode == "agency_plan"
        or (inferred_state_agency_mode == "agency_plan" and not explicit_free_signal)
    ):
        tool_planning_mode = None
        planning_mode_reason = (
            planning_mode_reason
            or "已按用户提出的省心方案诉求修正为旅行社顾问方案"
        )
    normalized_planning_mode = (
        tool_planning_mode
        or inferred_text_mode
        or inferred_state_agency_mode
        or state_mode
        or "free_planning"
    )
    normalized_reason = (
        planning_mode_reason
        or (runtime.state.get("planning_mode_reason") if runtime and runtime.state else "")
        or f"根据已确认需求识别为{PLANNING_MODE_LABELS[normalized_planning_mode]}"
    )
    requirement = UserRequirement(
        departure_city=departure_city,
        destination=destination,
        departure_date=departure_date,
        departure_date_confirmed=departure_date_confirmed,
        travel_days=travel_days,
        adult_count=adult_count or 0,
        children_count=children_count or 0,
        budget_min=budget_min,
        budget_max=budget_max,
        budget_level=budget_level,
        travel_styles=travel_styles,
        special_needs=special_needs or None,
        planning_mode=normalized_planning_mode,
        planning_mode_reason=normalized_reason,
        planning_mode_confirmed=planning_mode_confirmed,
    )
    confirmed_facts = _build_confirmed_facts(
        state=runtime_state,
        requirement=requirement,
        planning_mode=normalized_planning_mode,
    )
    confirmation_source = _runtime_recent_human_text(runtime) or "record_requirement_tool"
    confirmation_history = _confirmation_history_with_entries(
        runtime_state,
        _confirmed_fact_entries(confirmed_facts, source=confirmation_source),
    )
    matched_product = (
        _matched_product_summary(requirement, runtime_state)
        if normalized_planning_mode == "agency_plan"
        else None
    )

    summary_lines = [
        "需求已记录：",
        f"- 出发地：{departure_city}",
    ]
    if destination:
        summary_lines.append(f"- 意向目的地：{destination}")
    summary_lines.extend(
        [
            f"- 出发日期：{departure_date}",
            f"- 行程天数：{travel_days} 天",
            f"- 出行人数：{total_people} 人",
            f"- 预算区间：{budget_min}-{budget_max} 元/人（{budget_level}）",
            f"- 旅行风格：{', '.join(travel_styles)}",
            f"- 规划模式：{PLANNING_MODE_LABELS[normalized_planning_mode]}",
        ]
    )
    if special_needs:
        summary_lines.append(f"- 特殊需求：{special_needs}")

    state_update = {
        "user_requirement": requirement,
        "planning_mode": normalized_planning_mode,
        "active_workflow": normalized_planning_mode,
        "planning_mode_reason": normalized_reason,
        "planning_mode_confirmed": planning_mode_confirmed,
        "departure_date_confirmed": departure_date_confirmed,
        "confirmed_facts": confirmed_facts,
        "confirmation_history": confirmation_history,
        "current_step": "destination_recommendation",
        "pending_initial_request_text": "",
        "pending_initial_planning_mode": None,
        "pending_initial_planning_mode_reason": "",
    }
    if matched_product:
        state_update["matched_product"] = matched_product
    duplicate_command = _duplicate_state_command(
        "record_requirement_tool",
        state_update,
        runtime,
    )
    if duplicate_command is not None:
        return duplicate_command

    return _command_with_message(
        "\n".join(summary_lines),
        runtime,
        **state_update,
    )


@tool
def select_destination_tool(
    destination: str,
    description: Optional[Any] = None,
    weather_info: Optional[Any] = None,
    attractions: Optional[Any] = None,
    estimated_cost: Optional[Any] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist the chosen destination and optional destination context, then move to transport planning."""

    app_logger.info(f"用户选择目的地: {destination}")
    state_update = {
        "selected_destination": destination,
        "current_step": "transport_planning",
    }
    normalized_description = _coerce_text(description)
    normalized_weather_info = _coerce_text(weather_info)
    normalized_attractions = _coerce_attractions(attractions)
    normalized_estimated_cost = _coerce_optional_float(estimated_cost)
    if any(
        [
            normalized_description,
            normalized_weather_info,
            normalized_attractions,
            normalized_estimated_cost is not None,
        ]
    ):
        destination_info = {
            "name": destination,
            "description": normalized_description,
            "weather_info": normalized_weather_info,
            "attractions": normalized_attractions,
            "estimated_cost": normalized_estimated_cost,
        }
        state_update["destination_options"] = [destination_info]

    duplicate_command = _duplicate_state_command(
        "select_destination_tool",
        state_update,
        runtime,
    )
    if duplicate_command is not None:
        return duplicate_command

    return _command_with_message(
        f"目的地已确认：{destination}",
        runtime,
        **state_update,
    )


@tool
def select_transport_tool(
    transport_type: str,
    details: Optional[str] = None,
    departure_time: Optional[str] = None,
    arrival_time: Optional[str] = None,
    duration: Optional[str] = None,
    price: Optional[float] = None,
    source: Optional[str] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist the selected transport mode or concrete transport option and move to accommodation planning."""

    if _needs_transport_audit_before_transport_selection(runtime):
        return _command_with_message(
            "交通记录暂缓：用户要求查不到车次或真实班次时也要保留兜底/待核验证据。"
            "请先调用 query_transport_options；如果日期仍未确认，就用“日期待确认”让工具返回 skipped 审计结果，"
            "再记录高铁优先或可执行交通兜底方案。",
            runtime,
            current_step="transport_planning",
        )

    app_logger.info(f"用户选择交通方式: {transport_type}")
    transport_type = _normalize_choice(transport_type, TRANSPORT_LABELS, TRANSPORT_ALIASES)
    if transport_type not in TRANSPORT_LABELS:
        return _command_with_message(
            "交通方式无效，请选择 flight、train 或 driving。",
            runtime,
        )

    state_update = {
        "selected_transport": transport_type,
        "current_step": "accommodation_planning",
    }
    response = f"交通方式已确认：{TRANSPORT_LABELS[transport_type]}"

    if any([details, departure_time, arrival_time, duration, price, source]):
        selected_option = {
            "transport_type": transport_type,
            "details": details or TRANSPORT_LABELS[transport_type],
        }
        if departure_time:
            selected_option["departure_time"] = departure_time
        if arrival_time:
            selected_option["arrival_time"] = arrival_time
        if duration:
            selected_option["duration"] = duration
        if isinstance(price, (int, float)) and price > 0:
            selected_option["price"] = price
        if source:
            selected_option["source"] = source
        state_update["selected_transport_option"] = selected_option
        response += f"\n已记录具体方案：{_format_transport_option(selected_option)}"

    duplicate_command = _duplicate_state_command(
        "select_transport_tool",
        state_update,
        runtime,
    )
    if duplicate_command is not None:
        return duplicate_command

    return _command_with_message(response, runtime, **state_update)


@tool
def select_accommodation_tool(
    accommodation_types: Optional[list[str] | str] = None,
    hotel_id: Optional[int | str] = None,
    hotel_name: Optional[str] = None,
    location: Optional[str] = None,
    price_per_night: Optional[float | str] = None,
    rating: Optional[float | str] = None,
    amenities: Optional[list[str] | str] = None,
    booking_url: Optional[str] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist accommodation preferences or a concrete hotel choice and move to food planning."""

    state = _runtime_state(runtime)
    if _needs_hotel_audit_before_accommodation_selection(runtime):
        return _command_with_message(
            "住宿记录暂缓：用户要求没有真实锁价或查不到具体酒店时也要保留兜底/待核验证据。"
            "请先调用 query_hotel_options；如果日期仍未确认，就用“日期待确认”让工具返回 skipped 审计结果，"
            "再记录湘江边/核心商圈等可执行住宿兜底方案。",
            runtime,
        )

    selected_option = _find_accommodation_option(
        state,
        hotel_id=hotel_id,
        hotel_name=hotel_name,
    )
    if selected_option is None and hotel_id is None and not hotel_name:
        selected_option = _first_accommodation_option(state)

    normalized_price = _as_optional_float(price_per_night)
    normalized_rating = _as_optional_float(rating)
    normalized_amenities = _as_string_list(amenities)
    raw_accommodation_types = _as_string_list(accommodation_types)
    if not raw_accommodation_types:
        inferred_type = (selected_option or {}).get("type")
        raw_accommodation_types = [inferred_type or "star_hotel"]

    app_logger.info(f"用户选择住宿偏好: {raw_accommodation_types}")
    accommodation_types = _normalize_choices(
        raw_accommodation_types,
        ACCOMMODATION_LABELS,
        ACCOMMODATION_ALIASES,
    )
    invalid_types = sorted(set(accommodation_types) - set(ACCOMMODATION_LABELS))
    if invalid_types and selected_option:
        accommodation_types = ["star_hotel"]
        invalid_types = []
    if invalid_types:
        valid_types = ", ".join(sorted(ACCOMMODATION_LABELS))
        return _command_with_message(
            f"住宿类型无效：{', '.join(invalid_types)}。可选值为：{valid_types}",
            runtime,
        )

    selected_labels = [ACCOMMODATION_LABELS[item] for item in accommodation_types]

    if hotel_id is not None or hotel_name:
        if selected_option is None:
            selected_option = {
                "name": hotel_name or f"酒店ID {hotel_id}",
                "type": accommodation_types[0],
                "location": location or "位置待确认",
                "price_per_night": normalized_price or 0.0,
                "rating": normalized_rating,
                "amenities": normalized_amenities,
            }
            if hotel_id is not None:
                selected_option["hotel_id"] = hotel_id

        if location is not None:
            selected_option["location"] = location
        if normalized_price is not None:
            selected_option["price_per_night"] = normalized_price
        if normalized_rating is not None:
            selected_option["rating"] = normalized_rating
        if normalized_amenities:
            selected_option["amenities"] = normalized_amenities
        if booking_url is not None:
            selected_option["booking_url"] = booking_url

    response = f"住宿偏好已确认：{', '.join(selected_labels)}"
    state_update = {
        "selected_accommodation_types": accommodation_types,
        "current_step": "food_planning",
    }
    if selected_option:
        response += f"\n已确认酒店：{selected_option['name']}"
        if selected_option.get("hotel_id"):
            response += f"（酒店ID：{selected_option['hotel_id']}）"
        state_update["selected_accommodation_option"] = selected_option

    duplicate_command = _duplicate_state_command(
        "select_accommodation_tool",
        state_update,
        runtime,
    )
    if duplicate_command is not None:
        return duplicate_command

    return _command_with_message(
        response,
        runtime,
        **state_update,
    )


@tool
def select_food_tool(
    food_types: list[str] | str,
    food_pois: Optional[list[dict]] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist food preferences and move to itinerary generation."""

    state = _runtime_state(runtime)
    if state.get("current_step") == "food_planning" and not _has_confirmed_accommodation_state(
        state
    ):
        return _command_with_message(
            "餐饮记录暂缓：住宿方案还没有通过 query_hotel_options 和 "
            "select_accommodation_tool 完成审计与记录。请先回到住宿阶段；"
            "如果日期仍未确认，就用“日期待确认”调用 query_hotel_options 返回 skipped 审计结果，"
            "再调用 select_accommodation_tool 记录兜底住宿方案。",
            runtime,
            current_step="accommodation_planning",
        )

    app_logger.info(f"用户选择餐饮偏好: {food_types}")
    food_types = _normalize_choices(_as_string_list(food_types), FOOD_LABELS, FOOD_ALIASES)
    invalid_types = sorted(set(food_types) - set(FOOD_LABELS))
    if invalid_types:
        valid_types = ", ".join(sorted(FOOD_LABELS))
        return _command_with_message(
            f"餐饮类型无效：{', '.join(invalid_types)}。可选值为：{valid_types}",
            runtime,
        )

    selected_labels = [FOOD_LABELS[item] for item in food_types]
    selected_accommodation_types = _infer_selected_accommodation_types_for_state(state)
    state_update = {
        "selected_food_types": food_types,
        "current_step": "itinerary_generation",
    }
    if selected_accommodation_types and not state.get("selected_accommodation_types"):
        state_update["selected_accommodation_types"] = selected_accommodation_types
    if food_pois:
        state_update["selected_food_pois"] = [
            poi for poi in (_normalize_food_poi(item) for item in food_pois) if poi.get("name")
        ]

    duplicate_command = _duplicate_state_command(
        "select_food_tool",
        state_update,
        runtime,
    )
    if duplicate_command is not None:
        return duplicate_command

    return _command_with_message(
        f"餐饮偏好已确认：{', '.join(selected_labels)}",
        runtime,
        **state_update,
    )


@tool
def generate_itinerary_tool(
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Generate a lightweight itinerary skeleton and move to budget summarization."""

    app_logger.info("开始生成行程")
    state = _runtime_state(runtime)
    selected_accommodation_types = _infer_selected_accommodation_types_for_state(state)
    if selected_accommodation_types and not state.get("selected_accommodation_types"):
        state["selected_accommodation_types"] = selected_accommodation_types
    journey_plan = _valid_journey_plan_from_state(state)
    journey_destination = _journey_plan_destination(journey_plan)
    if journey_destination and not state.get("selected_destination"):
        state["selected_destination"] = journey_destination
    required_fields = [
        "user_requirement",
        "selected_destination",
        "selected_transport",
        "selected_accommodation_types",
    ]
    missing = [field for field in required_fields if not state.get(field)]
    if missing:
        return _command_with_message(
            f"信息还不完整，缺少：{', '.join(missing)}",
            runtime,
        )

    requirement = state["user_requirement"]
    destination = state["selected_destination"]
    destination_context = _get_destination_context(state, destination)
    weather_plan_b = _format_weather_plan_b(destination_context.get("weather_info"))
    destination_pois = _get_destination_pois(destination_context)
    selected_transport_option = state.get("selected_transport_option") or {}
    selected_accommodation = state.get("selected_accommodation_option") or {}
    transport_summary = _format_transport_option(selected_transport_option)
    accommodation_summary = _format_accommodation_option(selected_accommodation)
    selected_food_types = state.get("selected_food_types") or ["local", "specialty"]
    selected_food_pois = _get_food_pois(state)
    food_summary = "、".join(FOOD_LABELS.get(item, item) for item in selected_food_types)
    travel_styles = "、".join(requirement.get("travel_styles") or [])
    travel_days = requirement["travel_days"]
    if journey_plan:
        itinerary = _build_itinerary_from_journey_plan(
            journey_plan,
            state,
            requirement,
            selected_transport_option=selected_transport_option,
            selected_accommodation=selected_accommodation,
            selected_food_types=selected_food_types,
        )
        itinerary = _ensure_itinerary_day_count(itinerary, state, requirement)
        overview = journey_plan.get("overview") or {}
        return _command_with_message(
            (
                f"已按可视化旅程草案记录 {travel_days} 天正式行程。"
                f"路线逻辑：{overview.get('route_label') or overview.get('summary') or '按地图草案顺序执行'}。"
            ),
            runtime,
            itinerary=itinerary,
            journey_plan=journey_plan,
            selected_destination=destination,
            selected_food_types=selected_food_types,
            selected_accommodation_types=selected_accommodation_types,
            current_step="budget_summarization",
        )
    itinerary = []
    for day in range(1, travel_days + 1):
        if day == 1:
            theme = "抵达与轻松适应"
            arrival_pois = _pick_pois_by_area(destination_pois, 0, 1)
            day_area = _format_area_list(arrival_pois)
            attraction_text = "、".join(_poi_names(arrival_pois)) if arrival_pois else "酒店周边"
            reservation_note = _format_reservation_note(arrival_pois)
            activities = [
                f"抵达 {destination}，按已选交通方案安排到达节奏",
                f"入住或前往住宿区域：{accommodation_summary}",
                _format_poi_activity(
                    arrival_pois,
                    "晚上安排酒店周边轻松散步或低强度美食体验",
                ),
            ]
            time_blocks = [
                f"上午/出发：按已确认交通执行，{transport_summary}",
                f"下午/抵达：前往住宿区域并办理入住，{accommodation_summary}",
                f"晚上/轻松适应：安排 {attraction_text} 或酒店周边低强度美食体验",
            ]
            if reservation_note:
                time_blocks.append(f"预约/费用提醒：{reservation_note}")
            route_note = "抵达日以车站/机场到酒店、酒店周边短动线为主，避免第一天过度奔波。"
        elif day == travel_days:
            theme = "收尾与返程弹性"
            final_offset = max(len(destination_pois) - 1, 0)
            final_pois = _pick_pois_by_area(destination_pois, final_offset, 1)
            day_area = _format_area_list(final_pois)
            attraction_text = "、".join(_poi_names(final_pois)) if final_pois else "低强度补漏体验"
            reservation_note = _format_reservation_note(final_pois)
            activities = [
                _format_poi_activity(
                    final_pois,
                    "上午安排一个低强度核心体验或自由补漏",
                ),
                "预留打包、退房和前往车站/机场的机动时间",
                "返程前再次核对票务、行李和儿童/老人休息需求",
            ]
            time_blocks = [
                f"上午/补漏：安排 {attraction_text}，不再塞入高强度跨区活动",
                "下午/收尾：退房、寄存或取行李，预留前往车站/机场的缓冲时间",
                "晚上/返程：再次核对票务、行李和证件，按实时交通情况出发",
            ]
            if reservation_note:
                time_blocks.append(f"预约/费用提醒：{reservation_note}")
            route_note = "最后一天以低强度同区域活动和返程缓冲为主，优先保证不误车/误机。"
        else:
            theme = f"{destination} 深度体验"
            attraction_offset = 1 + max(day - 2, 0) * 2
            day_pois = _pick_pois_by_area(destination_pois, attraction_offset, 2)
            day_area = _format_area_list(day_pois)
            morning_pois = day_pois[:1]
            afternoon_pois = day_pois[1:2]
            morning_text = _format_poi_summary(morning_pois[0]) if morning_pois else f"符合 {travel_styles or '当前旅行偏好'} 的核心体验"
            afternoon_text = _format_poi_summary(afternoon_pois[0]) if afternoon_pois else "同区域景点/街区"
            reservation_note = _format_reservation_note(day_pois)
            indoor_backup = _format_indoor_backup(day_pois)
            activities = [
                _format_poi_activity(
                    morning_pois,
                    f"上午安排符合 {travel_styles or '当前旅行偏好'} 的核心体验",
                ),
                "下午选择同区域景点/街区，减少跨城和反复折返",
                f"晚上结合餐饮偏好：{food_summary or '本地特色与省心用餐'}",
            ]
            time_blocks = [
                f"上午/核心体验：{morning_text}",
                f"下午/顺路延展：{afternoon_text}，尽量保持同区域动线",
                f"晚上/餐饮放松：结合 {food_summary or '本地特色与省心用餐'}，避免再安排高强度景点",
            ]
            if reservation_note:
                time_blocks.append(f"预约/费用提醒：{reservation_note}")
            if indoor_backup:
                time_blocks.append(indoor_backup)
            route_note = "当天活动尽量串联在同一区域或同一条地铁/打车动线上，减少折返。"

        target_area = day_area
        lunch_food = _pick_food_poi(
            selected_food_pois,
            (day - 1) * 2,
            target_area=target_area,
            meal_keyword="午餐",
        )
        dinner_food = _pick_food_poi(
            selected_food_pois,
            (day - 1) * 2 + 1,
            target_area=target_area,
            meal_keyword="晚餐",
            exclude_names={str(lunch_food["name"])} if lunch_food and lunch_food.get("name") else None,
        )
        food_areas = _format_area_list(
            [poi for poi in [lunch_food, dinner_food] if poi]
        )
        if target_area and food_areas:
            if _areas_overlap(target_area, food_areas):
                route_note = f"{route_note} 当日主区域：{target_area}；餐饮优先匹配 {food_areas}，避免为了吃饭额外跨区。"
            else:
                route_note = f"{route_note} 当日主区域：{target_area}；当前餐饮候选集中在 {food_areas}，如时间紧建议就近替换。"
        food_booking_note = _format_food_booking_note(
            [poi for poi in [lunch_food, dinner_food] if poi]
        )
        if food_booking_note:
            time_blocks.append(f"餐饮提醒：{food_booking_note}")

        day_plan = {
            "day_number": day,
            "theme": theme,
            "activities": activities,
            "time_blocks": time_blocks,
            "meals": [
                "早餐：以酒店/周边省心用餐为主",
                f"午餐：{_format_food_poi_summary(lunch_food, '结合当日动线就近安排')}",
                f"晚餐：{_format_food_poi_summary(dinner_food, '优先匹配已确认餐饮偏好')}",
            ],
            "accommodation": selected_accommodation.get("name", "待结合酒店方案确认"),
            "transport_note": transport_summary if day == 1 else "当天以同区域动线为主，减少无效通勤",
            "plan_b": weather_plan_b,
            "route_note": route_note,
            "risk_notes": [
                "热门景点、餐厅和酒店价格可能随日期变化，出发前需要再次核验。",
                "如遇天气、排队或体力变化，优先执行 Plan B 并保留休息时间。",
            ],
        }
        itinerary.append(_enrich_itinerary_day_for_report(day_plan, state, requirement))

    return _command_with_message(
        f"已生成 {travel_days} 天的行程草案。",
        runtime,
        itinerary=itinerary,
        selected_food_types=selected_food_types,
        selected_accommodation_types=selected_accommodation_types,
        current_step="budget_summarization",
    )


@tool
def summarize_budget_tool(
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Estimate a simple budget breakdown and move to order generation."""

    app_logger.info("开始汇总预算")
    state = _runtime_state(runtime)
    requirement = state.get("user_requirement")
    itinerary = state.get("itinerary")
    if not requirement or not itinerary:
        return _command_with_message(
            "预算汇总前需要先生成完整行程。",
            runtime,
        )

    total_people = requirement["adult_count"] + requirement["children_count"]
    travel_days = requirement["travel_days"]
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    destination_context = _get_destination_context(state, destination)
    selected_accommodation = state.get("selected_accommodation_option") or {}
    itinerary = _ensure_itinerary_day_count(itinerary, state, requirement)

    transport_cost = _estimate_transport_cost(state, total_people)
    accommodation_cost, accommodation_assumption = _estimate_accommodation_cost(
        selected_accommodation,
        travel_days,
        total_people,
    )
    food_cost, food_assumption = _estimate_food_cost_from_itinerary(
        state,
        itinerary,
        travel_days,
        total_people,
    )
    attractions_cost, attractions_assumption = _estimate_attractions_cost(
        destination_context,
        itinerary,
        travel_days,
        total_people,
        state.get("scenic_price_evidence"),
    )
    misc_cost = 100 * travel_days * total_people
    total_cost = (
        transport_cost
        + accommodation_cost
        + food_cost
        + attractions_cost
        + misc_cost
    )

    assumptions = [
        "交通按已选具体方案价格估算；缺少具体价格时按交通类型基准估算。",
        accommodation_assumption,
        food_assumption,
        attractions_assumption,
        "其他机动费用按 100 元/人/天估算，用于市内交通、临时休息、寄存和小额杂费。",
    ]
    budget_quality = _build_budget_quality_notes(
        state,
        destination_context,
        itinerary,
    )
    budget_line_items = _build_budget_line_items(
        state,
        itinerary,
        travel_days,
        total_people,
        transport_cost,
        accommodation_cost,
        food_cost,
        attractions_cost,
        misc_cost,
    )

    budget_breakdown = {
        "currency": "CNY",
        "travel_days": travel_days,
        "nights": max(travel_days - 1, 1),
        "total_people": total_people,
        "transport": transport_cost,
        "accommodation": accommodation_cost,
        "food": food_cost,
        "attractions": attractions_cost,
        "misc": misc_cost,
        "total": total_cost,
        "per_person": total_cost / max(total_people, 1),
        "line_items": budget_line_items,
        "assumptions": assumptions,
        **budget_quality,
    }
    budget_breakdown["budget_confidence"] = _budget_confidence_payload(budget_breakdown)
    light_product = build_light_product(requirement, state)
    budget_breakdown["quote_policy"] = build_quote_policy(
        requirement,
        budget_breakdown,
        product=light_product,
        state=state,
    )
    budget_summary = "\n".join(
        build_budget_summary_lines(
            requirement,
            budget_breakdown,
            product=light_product,
        )
    )

    return _command_with_message(
        budget_summary,
        runtime,
        itinerary=itinerary,
        budget=budget_breakdown,
        current_step="order_generation",
    )


@tool
def generate_order_tool(
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Create an order id for the finalized travel plan."""

    app_logger.info("开始生成订单")
    state = _runtime_state(runtime)
    requirement = state.get("user_requirement") or {}
    if not isinstance(requirement, dict):
        requirement = {}
    selected_destination = state.get("selected_destination") or requirement.get("destination")
    expected_days = _get_expected_travel_days(
        requirement,
        len(state.get("itinerary") or []),
    )
    total_people = (
        (requirement.get("adult_count") or 0)
        + (requirement.get("children_count") or 0)
        or (state.get("budget") or {}).get("total_people")
        or 0
    )
    has_budget_hint = (
        bool(state.get("budget"))
        or requirement.get("budget_min") is not None
        or requirement.get("budget_max") is not None
        or bool(requirement.get("budget_level"))
    )
    missing_items = []
    if not selected_destination:
        missing_items.append("目的地")
    if expected_days <= 0:
        missing_items.append("行程天数")
    if total_people <= 0:
        missing_items.append("出行人数")
    if not _has_confirmed_transport_state(state):
        missing_items.append("交通方案")
    if not _has_confirmed_accommodation_state(state):
        missing_items.append("住宿方案")
    if not state.get("itinerary"):
        missing_items.append("完整行程")
    if not state.get("budget") or not has_budget_hint:
        missing_items.append("预算汇总")

    if missing_items:
        return _command_with_message(
            f"生成最终报告前还需要先确认：{'、'.join(missing_items)}。不会在目的地或产品框架阶段提前生成 report_data。",
            runtime,
        )

    order_id = f"ORDER-{uuid4().hex[:8].upper()}"
    approval_record = mark_sensitive_action(
        action="generate_order_id",
        reason="生成项目内模拟订单号，用于最终旅行方案归档；当前不触发真实支付或真实预订。",
        user_id=str(state.get("user_id") or "anonymous"),
        conversation_id=state.get("session_id"),
        metadata={
            "order_id": order_id,
            "destination": selected_destination,
            "report_version": "travel_report.v1",
        },
    )
    approval_update = approval_state_update(approval_record)
    selected_transport_option = state.get("selected_transport_option") or {}
    selected_accommodation = _build_fallback_accommodation_option(state, requirement)
    report_state = dict(state)
    report_state.update(approval_update)
    if not report_state.get("selected_destination") and selected_destination:
        report_state["selected_destination"] = selected_destination
    if not report_state.get("selected_accommodation_option"):
        report_state["selected_accommodation_option"] = selected_accommodation
    itinerary = _ensure_itinerary_day_count(
        report_state.get("itinerary") or [],
        report_state,
        requirement,
    )
    budget = _ensure_budget_quality_contract(
        report_state,
        requirement,
        report_state.get("budget") or {},
        itinerary,
    )
    selected_food_types = state.get("selected_food_types") or []
    report_data = _build_report_data(
        report_state,
        requirement,
        budget,
        itinerary,
        selected_transport_option,
        selected_accommodation,
        selected_food_types,
    )
    approval_payload = _approval_report_payload(approval_update)
    report_data.setdefault("tool_audit_summary", {})["approval"] = approval_payload
    report_data.setdefault("evidence_bundle", {})[
        "approval_governance"
    ] = approval_payload
    report_bundle = build_report_bundle(report_data)
    if not report_bundle.validation.ok:
        return _command_with_message(
            report_bundle.validation.to_user_message(),
            runtime,
        )
    report = report_bundle.markdown
    message = "\n".join(
        [
            report,
            "",
            "订单生成成功：",
            f"- 订单号：{order_id}",
            "- 支付链接：当前项目未接入真实支付服务，暂不生成支付链接。",
            "- 审批治理：生成订单号当前为记录型敏感动作，不阻塞报告交付；未来接入真实支付或真实预订时必须先完成人工审批。",
            f"- 治理边界：{approval_payload['boundary']}",
            "感谢使用智能旅行规划系统。",
        ]
    )
    return _command_with_message(
        message,
        runtime,
        order_id=order_id,
        selected_destination=selected_destination,
        selected_accommodation_option=selected_accommodation,
        itinerary=itinerary,
        budget=budget,
        report=report,
        report_data=report_data,
        current_step="order_generation",
        **approval_update,
    )


# Compatibility aliases for legacy imports.
ALL_STEPS = list(WORKFLOW_STEPS)
STEP_LABELS = dict(WORKFLOW_STEP_LABELS)
STEP_STATE_FIELDS = dict(WORKFLOW_STEP_STATE_FIELDS)


@tool
def go_back_to_step(
    target_step: RollbackTargetStep,
    reason: str,
    clear_subsequent_data: bool = True,
    runtime: ToolRuntime = None,
) -> Command:
    """Return to a previous planning step and optionally clear downstream data."""

    app_logger.info(
        f"收到回退请求: target_step={target_step}, "
        f"reason={reason}, clear_subsequent_data={clear_subsequent_data}"
    )

    if target_step not in WORKFLOW_STEPS:
        return _command_with_message(f"无效的目标步骤：{target_step}", runtime)

    if target_step == FINAL_PLANNING_STEP:
        return _command_with_message(
            "订单生成是最终步骤，无法直接回退到这里，请回退到更早的步骤。",
            runtime,
        )

    current_step = _runtime_state(runtime).get("current_step", "unknown")
    app_logger.info(f"执行回退: {current_step} -> {target_step}")

    state_update = {"current_step": target_step}
    cleared_fields: list[str] = []
    if clear_subsequent_data:
        target_index = WORKFLOW_STEPS.index(target_step)
        for step in WORKFLOW_STEPS[target_index:]:
            for field in WORKFLOW_STEP_STATE_FIELDS.get(step, []):
                state_update[field] = None
                cleared_fields.append(field)

    step_label = WORKFLOW_STEP_LABELS.get(target_step, target_step)
    response_parts = [
        f"已回退到【{step_label}】阶段。",
        f"原因：{reason}",
    ]
    if clear_subsequent_data and cleared_fields:
        response_parts.append("已清除该步骤及其后续步骤的数据。")

    state_update["messages"] = [_tool_message("\n".join(response_parts), runtime)]
    app_logger.info(f"回退完成: {target_step}, 清除字段数={len(cleared_fields)}")
    return Command(update=state_update)


@tool
def go_back_to_requirement(
    reason: str = "用户需要修改旅行需求",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the requirement-collection step."""

    return go_back_to_step.invoke(
        {
            "target_step": "requirement_collection",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def go_back_to_destination(
    reason: str = "用户需要重新选择目的地",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the destination-recommendation step."""

    return go_back_to_step.invoke(
        {
            "target_step": "destination_recommendation",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def go_back_to_transport(
    reason: str = "用户需要调整交通方式",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the transport-planning step."""

    return go_back_to_step.invoke(
        {
            "target_step": "transport_planning",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def go_back_to_accommodation(
    reason: str = "用户需要调整住宿偏好",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the accommodation-planning step."""

    return go_back_to_step.invoke(
        {
            "target_step": "accommodation_planning",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def go_back_to_food(
    reason: str = "用户需要调整餐饮偏好",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the food-planning step."""

    return go_back_to_step.invoke(
        {
            "target_step": "food_planning",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def go_back_to_itinerary(
    reason: str = "用户需要调整行程安排",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the itinerary-generation step."""

    return go_back_to_step.invoke(
        {
            "target_step": "itinerary_generation",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def go_back_to_budget(
    reason: str = "用户需要重新核算预算",
    runtime: ToolRuntime = None,
) -> Command:
    """Shortcut rollback to the budget-summarization step."""

    return go_back_to_step.invoke(
        {
            "target_step": "budget_summarization",
            "reason": reason,
            "clear_subsequent_data": True,
            "runtime": runtime,
        }
    )


@tool
def check_current_progress(runtime: ToolRuntime = None) -> str:
    """Return a human-readable progress summary for the current workflow state."""

    state = _runtime_state(runtime)
    current_step = state.get("current_step", INITIAL_PLANNING_STEP)

    try:
        current_index = WORKFLOW_STEPS.index(current_step)
    except ValueError:
        app_logger.warning(f"未知的当前步骤: {current_step}")
        current_index = 0

    progress_lines = ["当前规划进度", ""]
    for index, step in enumerate(WORKFLOW_STEPS):
        label = WORKFLOW_STEP_LABELS.get(step, step)
        step_num = index + 1
        if index < current_index:
            status = "已完成"
        elif index == current_index:
            status = "当前步骤"
        else:
            status = "待完成"
        progress_lines.append(f"[{step_num}] {label} - {status}")

    progress_lines.extend(["", "已收集信息"])
    requirement = state.get("user_requirement")
    if requirement:
        progress_lines.extend(
            [
                f"- 出发日期：{requirement.get('departure_date', '未设置')}",
                f"- 行程天数：{requirement.get('travel_days', '未设置')} 天",
                (
                    f"- 出行人数：{requirement.get('adult_count', 0)} 成人 + "
                    f"{requirement.get('children_count', 0)} 儿童"
                ),
            ]
        )

    if state.get("selected_destination"):
        progress_lines.append(f"- 目的地：{state['selected_destination']}")

    if state.get("selected_transport"):
        selected_transport = state["selected_transport"]
        progress_lines.append(
            f"- 交通：{TRANSPORT_LABELS.get(selected_transport, selected_transport)}"
        )
    if state.get("selected_transport_option"):
        progress_lines.append(
            f"- 交通方案：{_format_transport_option(state['selected_transport_option'])}"
        )

    if state.get("selected_accommodation_types"):
        selected_labels = [
            ACCOMMODATION_LABELS.get(item, item)
            for item in state["selected_accommodation_types"]
        ]
        progress_lines.append(f"- 住宿：{', '.join(selected_labels)}")
    if state.get("selected_accommodation_option"):
        option = state["selected_accommodation_option"]
        progress_lines.append(f"- 已选酒店：{option.get('name', '未命名酒店')}")

    if state.get("selected_food_types"):
        selected_labels = [
            FOOD_LABELS.get(item, item) for item in state["selected_food_types"]
        ]
        progress_lines.append(f"- 餐饮：{', '.join(selected_labels)}")

    app_logger.info(
        f"进度查询完成: 当前步骤={current_step}, "
        f"进度={current_index + 1}/{len(WORKFLOW_STEPS)}"
    )
    return "\n".join(progress_lines)


ALL_ROLLBACK_TOOLS = [
    go_back_to_step,
    go_back_to_requirement,
    go_back_to_destination,
    go_back_to_transport,
    go_back_to_accommodation,
    go_back_to_food,
    go_back_to_itinerary,
    go_back_to_budget,
    check_current_progress,
]
