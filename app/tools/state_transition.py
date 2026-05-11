"""
State transition tools for the travel-planning workflow.
"""
from datetime import datetime
from math import ceil
from typing import Any, Optional
from uuid import uuid4

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agency import product_rules as agency_product_rules
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
from app.reports import (
    build_report_bundle,
    build_report_evidence_bundle,
    build_report_tool_audit_summary,
    build_travel_report_data,
    format_report_duration,
    format_report_people,
    format_report_route_label,
)
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
    "经济酒店": "economy_hotel",
    "快捷酒店": "economy_hotel",
    "经济型酒店": "economy_hotel",
    "民宿": "hostel",
    "特色民宿": "hostel",
    "客栈": "hostel",
    "青年旅舍": "youth_hostel",
    "青旅": "youth_hostel",
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


def _normalize_choices(
    values: list[str],
    valid_labels: dict[str, str],
    aliases: dict[str, str],
) -> list[str]:
    normalized = []
    for value in values:
        choice = _normalize_choice(value, valid_labels, aliases)
        if choice not in normalized:
            normalized.append(choice)
    return normalized


def _find_accommodation_option(
    state: TravelState,
    *,
    hotel_id: Optional[int] = None,
    hotel_name: Optional[str] = None,
) -> Optional[dict]:
    for option in state.get("accommodation_options") or []:
        if hotel_id is not None and option.get("hotel_id") == hotel_id:
            return dict(option)
        if hotel_name and option.get("name") == hotel_name:
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


def _planning_mode_state_update(
    state: TravelState,
    *,
    planning_mode: str,
    planning_mode_reason: str,
    planning_mode_confirmed: bool,
) -> dict:
    update = {
        "planning_mode": planning_mode,
        "planning_mode_reason": planning_mode_reason,
        "planning_mode_confirmed": planning_mode_confirmed,
    }
    requirement = state.get("user_requirement")
    if isinstance(requirement, dict) and requirement:
        update["user_requirement"] = {
            **requirement,
            "planning_mode": planning_mode,
            "planning_mode_reason": planning_mode_reason,
            "planning_mode_confirmed": planning_mode_confirmed,
        }
    return update


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


def _budget_level_from_range(budget_min: float, budget_max: float) -> str:
    avg_budget = (budget_min + budget_max) / 2
    if avg_budget < 3000:
        return "economy"
    if avg_budget < 8000:
        return "comfort"
    return "luxury"


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
) -> tuple[float, str]:
    destination_pois = _get_destination_pois(destination_context)
    if not destination_pois:
        fallback = 200 * travel_days * total_people
        return fallback, "景点缺少结构化 POI 费用，按 200 元/人/天兜底估算。"

    text = _itinerary_text(itinerary)
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


def _dedupe_report_points(points: list[str], max_items: int = 6) -> list[str]:
    picked = []
    for point in points:
        normalized = str(point or "").strip()
        if not normalized or normalized in picked:
            continue
        picked.append(normalized)
        if len(picked) >= max_items:
            break
    return picked


def _is_pending_route_point(point: str) -> bool:
    pending_tokens = (
        "\u5f85",
        "\u5f85\u786e\u8ba4",
        "\u5f85\u6838\u9a8c",
        "\u5f85\u7ed3\u5408",
    )
    return any(token in point for token in pending_tokens)


def _collect_report_route_candidates(state: TravelState) -> list[str]:
    candidates = []
    destination = state.get("selected_destination")
    if destination:
        candidates.append(str(destination))

    accommodation = state.get("selected_accommodation_option") or {}
    for key in ["location", "name"]:
        if accommodation.get(key):
            candidates.append(str(accommodation[key]))

    for option in state.get("destination_options") or []:
        candidates.extend(str(name) for name in option.get("attractions", []) if name)
        for poi in option.get("attraction_pois", []) or []:
            if poi.get("area"):
                candidates.append(str(poi["area"]))
            if poi.get("name"):
                candidates.append(str(poi["name"]))

    for food_poi in state.get("selected_food_pois") or []:
        if food_poi.get("area"):
            candidates.append(str(food_poi["area"]))
        if food_poi.get("name"):
            candidates.append(str(food_poi["name"]))

    return _dedupe_report_points(candidates, max_items=40)


def _route_points_have_specific_visual_node(
    points: list[str],
    *,
    destination: str,
    departure_city: str,
    accommodation_points: Optional[list[str]] = None,
) -> bool:
    generic_points = {
        str(destination or "").strip(),
        str(departure_city or "").strip(),
        "返程交通",
        "返程缓冲",
    }
    for accommodation_point in accommodation_points or []:
        normalized = str(accommodation_point or "").strip()
        if normalized:
            generic_points.add(normalized)
    generic_points.discard("")
    return any(
        point not in generic_points and not _is_pending_route_point(point)
        for point in points
    )


def _fallback_report_route_points_for_day(
    day_number: int,
    expected_days: int,
    state: TravelState,
    requirement: dict,
) -> list[str]:
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    departure_city = requirement.get("departure_city") or ""
    selected_accommodation = state.get("selected_accommodation_option") or {}
    accommodation = selected_accommodation.get("location") or selected_accommodation.get("name")
    if not accommodation or _is_pending_route_point(str(accommodation)):
        accommodation = _recommended_accommodation_area(str(destination))

    destination_pois = _destination_pois_for_report(state, requirement)
    day_pois = _pick_report_pois_for_day(destination_pois, day_number, expected_days)
    day_poi_names = _poi_names(day_pois)

    if day_number == 1:
        points = [departure_city, destination, accommodation, *day_poi_names[:1]]
    elif day_number == expected_days:
        points = [accommodation, *day_poi_names[:1], "返程交通"]
    else:
        points = [accommodation, *day_poi_names]
    return _dedupe_report_points([str(point) for point in points if point])


def _format_report_route_points(
    day: dict,
    state: TravelState,
    requirement: dict,
) -> list[str]:
    day_number = day.get("day_number") or 0
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    departure_city = requirement.get("departure_city") or ""
    expected_days = _get_expected_travel_days(requirement, 0)
    selected_accommodation = state.get("selected_accommodation_option") or {}
    accommodation_candidates = [
        day.get("accommodation"),
        selected_accommodation.get("location"),
        selected_accommodation.get("name"),
    ]
    explicit_points = day.get("route_points")
    if isinstance(explicit_points, list) and explicit_points:
        explicit = _dedupe_report_points([str(point) for point in explicit_points])
        explicit_visual_points = [
            point for point in explicit if not _is_pending_route_point(point)
        ]
        if len(explicit_visual_points) >= 2 and _route_points_have_specific_visual_node(
            explicit_visual_points,
            destination=str(destination),
            departure_city=str(departure_city),
            accommodation_points=[str(point) for point in accommodation_candidates if point],
        ):
            return explicit
    else:
        explicit = []

    accommodation = day.get("accommodation") or selected_accommodation.get("name")
    text = "\n".join(
        str(item)
        for item in [
            day.get("theme"),
            *(day.get("activities") or []),
            *(day.get("time_blocks") or []),
            *(day.get("meals") or []),
            day.get("route_note"),
            day.get("transport_note"),
        ]
        if item
    )

    points = [point for point in explicit if not _is_pending_route_point(point)]
    if day_number == 1 and departure_city:
        points.append(str(departure_city))
    if day_number == 1 and destination:
        points.append(str(destination))

    matches = []
    for candidate in _collect_report_route_candidates(state):
        if candidate and candidate in text:
            matches.append((text.index(candidate), candidate))
    points.extend(candidate for _, candidate in sorted(matches, key=lambda item: item[0]))

    if accommodation and not _is_pending_route_point(str(accommodation)):
        points.append(str(accommodation))
    if day_number == expected_days:
        points.append("\u8fd4\u7a0b\u4ea4\u901a")
    if len(_dedupe_report_points(points)) < 2 or not _route_points_have_specific_visual_node(
        _dedupe_report_points(points),
        destination=str(destination),
        departure_city=str(departure_city),
        accommodation_points=[str(point) for point in accommodation_candidates if point],
    ):
        points.extend(
            _fallback_report_route_points_for_day(
                int(day_number or 0),
                expected_days,
                state,
                requirement,
            )
        )
    if len(_dedupe_report_points(points)) < 2 and destination:
        points.append(str(destination))
    if len(_dedupe_report_points(points)) < 2 and day_number == expected_days:
        points.append("\u8fd4\u7a0b\u7f13\u51b2")

    return _dedupe_report_points(points)


def _get_expected_travel_days(requirement: dict, fallback: int = 0) -> int:
    travel_days = requirement.get("travel_days")
    if isinstance(travel_days, int) and travel_days > 0:
        return travel_days
    if isinstance(travel_days, str):
        try:
            parsed_days = int(travel_days)
        except ValueError:
            parsed_days = 0
        if parsed_days > 0:
            return parsed_days
    return max(fallback, 0)


def _build_placeholder_itinerary_day(
    day_number: int,
    expected_days: int,
    state: TravelState,
    requirement: dict,
) -> dict:
    destination = state.get("selected_destination") or requirement.get("destination") or "目的地"
    selected_accommodation = state.get("selected_accommodation_option") or {}
    if not selected_accommodation.get("name"):
        selected_accommodation = _build_fallback_accommodation_option(state, requirement)
    accommodation = selected_accommodation.get("name") or f"{destination}交通便利区域住宿"
    destination_context = _get_destination_context(state, destination)
    destination_pois = _destination_pois_for_report(state, requirement)
    day_pois = _pick_report_pois_for_day(destination_pois, day_number, expected_days)
    day_poi_names = _poi_names(day_pois)
    primary_poi = day_poi_names[0] if day_poi_names else f"{destination}核心街区"
    lunch_food = _pick_food_poi(
        _get_food_pois(state),
        day_number * 2 - 2,
        target_area=day_pois[0].get("area") if day_pois else None,
        meal_keyword="午餐",
    )
    dinner_food = _pick_food_poi(
        _get_food_pois(state),
        day_number * 2 - 1,
        target_area=day_pois[-1].get("area") if day_pois else None,
        meal_keyword="晚餐",
        exclude_names={str(lunch_food["name"])} if lunch_food and lunch_food.get("name") else None,
    )
    plan_b = _format_weather_plan_b(destination_context.get("weather_info"))

    if day_number == 1:
        theme = f"抵达与{primary_poi}轻松适应"
        time_blocks = [
            "上午/出发：按已确认交通方案执行，预留到站/到机场缓冲。",
            f"下午/抵达：前往 {accommodation}，办理入住或寄存行李。",
            f"晚上/适应：安排 {primary_poi} 轻量游览和就近晚餐。",
        ]
        activities = [
            f"抵达 {destination}",
            f"入住/寄存：{accommodation}",
            _format_poi_activity(day_pois, f"{destination}住宿周边轻松活动"),
        ]
        route_note = "动线原则：抵达日只安排住宿区域和一个低强度夜间/傍晚体验，避免刚到就跨区奔波。"
        route_points = _dedupe_report_points(
            [
                requirement.get("departure_city") or "",
                destination,
                accommodation,
                *day_poi_names,
            ]
        )
    elif day_number == expected_days:
        theme = f"{primary_poi}补漏与返程缓冲"
        time_blocks = [
            f"上午/补漏：安排 {primary_poi} 或同区域低强度体验，避免跨区奔波。",
            "下午/收尾：退房、寄存或取行李，预留前往车站/机场的缓冲时间。",
            "晚上/返程：按实时交通情况出发，再次核对票务、证件和行李。",
        ]
        activities = [
            _format_poi_activity(day_pois, f"{destination}低强度补漏体验"),
            "退房/寄存/取行李",
            "返程交通缓冲",
        ]
        route_note = "动线原则：返程日优先保证稳定，只保留一个顺路体验和充分交通缓冲。"
        route_points = _dedupe_report_points([accommodation, *day_poi_names, "返程交通"])
    else:
        theme = " + ".join(day_poi_names) if day_poi_names else f"{destination}顺路体验"
        time_blocks = [
            f"上午/核心体验：{_format_poi_activity(day_pois[:1], f'{destination}核心景点或街区')}",
            f"下午/顺路延展：{_format_poi_activity(day_pois[1:], '同区域景点、商圈或室内场馆')}，减少折返。",
            "晚上/餐饮放松：结合已确认餐饮偏好就近用餐，保留休息时间。",
        ]
        activities = [
            *_poi_names(day_pois),
            "就近餐饮与休息",
        ]
        route_note = "动线原则：当天围绕同一区域或相邻街区展开，优先减少折返、保留休息。"
        route_points = _dedupe_report_points([accommodation, *day_poi_names])

    reservation_note = _format_reservation_note(day_pois)
    if reservation_note:
        time_blocks.append(f"预约/费用提醒：{reservation_note}")
    indoor_backup = _format_indoor_backup(day_pois)
    if indoor_backup:
        time_blocks.append(indoor_backup)

    return {
        "day_number": day_number,
        "theme": theme,
        "activities": activities,
        "route_points": route_points,
        "time_blocks": time_blocks,
        "meals": [
            "早餐：以酒店/周边省心用餐为主",
            f"午餐：{_format_food_poi_summary(lunch_food, '结合当日动线就近安排')}",
            f"晚餐：{_format_food_poi_summary(dinner_food, '优先匹配已确认餐饮偏好')}",
        ],
        "accommodation": accommodation,
        "transport_note": "当天交通以同区域步行、地铁或短途打车为主；跨区安排需二次核实。",
        "plan_b": plan_b,
        "route_note": route_note,
        "risk_notes": [
            "具体开放时间、预约和票价需在出发前二次核实。",
            "如遇天气、排队或体力变化，优先执行 Plan B 并保留休息时间。",
        ],
    }


def _build_day_route_summary(day: dict, state: TravelState, requirement: dict) -> dict:
    day_number = day.get("day_number", 0)
    route_points = _format_report_route_points(day, state, requirement)
    theme = day.get("theme") or "当天安排"
    if route_points:
        summary = " → ".join(route_points)
        if len(route_points) == 1 and theme not in summary:
            summary = f"{summary}｜{theme}"
    else:
        summary = theme
    return {
        "day_number": day_number,
        "route_points": route_points,
        "summary": summary,
        "map_label": f"Day {day_number}：{summary}",
        "route_note": day.get("route_note") or day.get("transport_note") or "",
    }


def _enrich_itinerary_day_for_report(
    day: dict,
    state: TravelState,
    requirement: dict,
) -> dict:
    enriched = dict(day)
    route_summary = _build_day_route_summary(enriched, state, requirement)
    enriched["route_points"] = route_summary["route_points"]
    enriched["route_summary"] = route_summary["summary"]
    enriched["map_route"] = route_summary["map_label"]
    return enriched


def _ensure_itinerary_day_count(
    itinerary: list[dict],
    state: TravelState,
    requirement: dict,
) -> list[dict]:
    source_days = [dict(day) for day in itinerary or [] if isinstance(day, dict)]
    expected_days = _get_expected_travel_days(requirement, len(source_days))
    if expected_days <= 0:
        return [
            _enrich_itinerary_day_for_report(day, state, requirement)
            for day in source_days
        ]

    by_day: dict[int, dict] = {}
    next_fallback_day = 1
    for index, day in enumerate(source_days, start=1):
        raw_day_number = day.get("day_number")
        if isinstance(raw_day_number, int) and raw_day_number > 0:
            day_number = raw_day_number
        else:
            while next_fallback_day in by_day:
                next_fallback_day += 1
            day_number = next_fallback_day or index
        if day_number > expected_days or day_number in by_day:
            continue
        day["day_number"] = day_number
        by_day[day_number] = day

    normalized = []
    for day_number in range(1, expected_days + 1):
        day = by_day.get(day_number) or _build_placeholder_itinerary_day(
            day_number,
            expected_days,
            state,
            requirement,
        )
        day["day_number"] = day_number
        normalized.append(_enrich_itinerary_day_for_report(day, state, requirement))
    return normalized


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
    route_summaries = [
        _build_day_route_summary(day, state, requirement)
        for day in itinerary
    ]
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


@tool
def record_requirement_tool(
    departure_city: str,
    departure_date: str,
    travel_days: int,
    budget_min: float,
    budget_max: float,
    travel_styles: list[str],
    special_needs: str = "",
    adult_count: Optional[int] = 1,
    children_count: Optional[int] = 0,
    destination: Optional[str] = None,
    planning_mode: Optional[str] = None,
    planning_mode_reason: str = "",
    planning_mode_confirmed: bool = True,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist the confirmed requirement summary and move to destination selection."""

    app_logger.info(
        f"记录用户需求: {departure_date}, {travel_days}天, 预算 {budget_min}-{budget_max}"
    )

    try:
        datetime.strptime(departure_date, "%Y-%m-%d")
    except ValueError:
        return _command_with_message(
            "日期格式错误，请使用 YYYY-MM-DD，例如 2026-05-01。",
            runtime,
        )

    budget_level = _budget_level_from_range(budget_min, budget_max)
    total_people = (adult_count or 0) + (children_count or 0)
    mode_seed = {
        "special_needs": special_needs or "",
        "travel_styles": travel_styles,
    }
    mode_seed_text = " ".join(
        [str(mode_seed["special_needs"]), " ".join(str(item) for item in travel_styles)]
    )
    inferred_text_mode = None
    if any(
        keyword in mode_seed_text
        for keyword in ("省心", "旅行社", "成熟路线", "定制游", "跟团", "小包团", "私家团", "团建", "亲子", "银发", "兜底", "自由行", "自由规划", "自助游", "自己玩", "不跟团", "自己订")
    ):
        inferred_text_mode = _infer_planning_mode(mode_seed)
    tool_planning_mode = _normalize_planning_mode(planning_mode)
    if tool_planning_mode == "free_planning" and inferred_text_mode == "agency_plan":
        tool_planning_mode = None
        planning_mode_reason = (
            planning_mode_reason
            or "已按用户提出的住宿兜底方案诉求修正为旅行社顾问方案"
        )
    state_mode = _state_planning_mode(runtime.state if runtime else None)
    normalized_planning_mode = (
        tool_planning_mode
        or inferred_text_mode
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

    return _command_with_message(
        "\n".join(summary_lines),
        runtime,
        user_requirement=requirement,
        planning_mode=normalized_planning_mode,
        planning_mode_reason=normalized_reason,
        planning_mode_confirmed=planning_mode_confirmed,
        current_step="destination_recommendation",
    )


@tool
def select_destination_tool(
    destination: str,
    description: Optional[str] = None,
    weather_info: Optional[str] = None,
    attractions: Optional[list[str]] = None,
    estimated_cost: Optional[float] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist the chosen destination and optional destination context, then move to transport planning."""

    app_logger.info(f"用户选择目的地: {destination}")
    state_update = {
        "selected_destination": destination,
        "current_step": "transport_planning",
    }
    if any([description, weather_info, attractions, estimated_cost]):
        destination_info = {
            "name": destination,
            "description": description or "",
            "weather_info": weather_info,
            "attractions": attractions or [],
            "estimated_cost": estimated_cost,
        }
        state_update["destination_options"] = [destination_info]

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

    return _command_with_message(response, runtime, **state_update)


@tool
def select_accommodation_tool(
    accommodation_types: list[str],
    hotel_id: Optional[int] = None,
    hotel_name: Optional[str] = None,
    location: Optional[str] = None,
    price_per_night: Optional[float] = None,
    rating: Optional[float] = None,
    amenities: Optional[list[str]] = None,
    booking_url: Optional[str] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist accommodation preferences or a concrete hotel choice and move to food planning."""

    app_logger.info(f"用户选择住宿偏好: {accommodation_types}")
    accommodation_types = _normalize_choices(
        accommodation_types,
        ACCOMMODATION_LABELS,
        ACCOMMODATION_ALIASES,
    )
    invalid_types = sorted(set(accommodation_types) - set(ACCOMMODATION_LABELS))
    if invalid_types:
        valid_types = ", ".join(sorted(ACCOMMODATION_LABELS))
        return _command_with_message(
            f"住宿类型无效：{', '.join(invalid_types)}。可选值为：{valid_types}",
            runtime,
        )

    selected_labels = [ACCOMMODATION_LABELS[item] for item in accommodation_types]
    state = _runtime_state(runtime)
    selected_option = _find_accommodation_option(
        state,
        hotel_id=hotel_id,
        hotel_name=hotel_name,
    )

    if hotel_id is not None or hotel_name:
        if selected_option is None:
            selected_option = {
                "name": hotel_name or f"酒店ID {hotel_id}",
                "type": accommodation_types[0],
                "location": location or "位置待确认",
                "price_per_night": price_per_night or 0.0,
                "rating": rating,
                "amenities": amenities or [],
            }
            if hotel_id is not None:
                selected_option["hotel_id"] = hotel_id

        if location is not None:
            selected_option["location"] = location
        if price_per_night is not None:
            selected_option["price_per_night"] = price_per_night
        if rating is not None:
            selected_option["rating"] = rating
        if amenities is not None:
            selected_option["amenities"] = amenities
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

    return _command_with_message(
        response,
        runtime,
        **state_update,
    )


@tool
def select_food_tool(
    food_types: list[str],
    food_pois: Optional[list[dict]] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """Persist food preferences and move to itinerary generation."""

    app_logger.info(f"用户选择餐饮偏好: {food_types}")
    food_types = _normalize_choices(food_types, FOOD_LABELS, FOOD_ALIASES)
    invalid_types = sorted(set(food_types) - set(FOOD_LABELS))
    if invalid_types:
        valid_types = ", ".join(sorted(FOOD_LABELS))
        return _command_with_message(
            f"餐饮类型无效：{', '.join(invalid_types)}。可选值为：{valid_types}",
            runtime,
        )

    selected_labels = [FOOD_LABELS[item] for item in food_types]
    state_update = {
        "selected_food_types": food_types,
        "current_step": "itinerary_generation",
    }
    if food_pois:
        state_update["selected_food_pois"] = [
            poi for poi in (_normalize_food_poi(item) for item in food_pois) if poi.get("name")
        ]

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
    required_fields = [
        "user_requirement",
        "selected_destination",
        "selected_transport",
        "selected_accommodation_types",
        "selected_food_types",
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
    selected_food_types = state.get("selected_food_types") or []
    selected_food_pois = _get_food_pois(state)
    food_summary = "、".join(FOOD_LABELS.get(item, item) for item in selected_food_types)
    travel_styles = "、".join(requirement.get("travel_styles") or [])
    travel_days = requirement["travel_days"]
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
    if not has_budget_hint:
        missing_items.append("预算")

    if missing_items:
        return _command_with_message(
            f"生成最终报告前还需要先确认：{'、'.join(missing_items)}。",
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
