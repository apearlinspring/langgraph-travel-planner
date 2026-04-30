"""
State transition tools for the travel-planning workflow.
"""
from datetime import datetime
from math import ceil
from typing import Optional
from uuid import uuid4

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.core.state import TravelState, UserRequirement
from app.core.workflow import (
    FINAL_PLANNING_STEP,
    INITIAL_PLANNING_STEP,
    PLANNING_STEPS as WORKFLOW_STEPS,
    RollbackTargetStep,
    STEP_LABELS as WORKFLOW_STEP_LABELS,
    STEP_STATE_FIELDS as WORKFLOW_STEP_STATE_FIELDS,
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


def _build_budget_quality_notes(
    state: TravelState,
    destination_context: dict,
    itinerary: list[dict],
) -> dict[str, list[str] | str]:
    selected_transport_option = state.get("selected_transport_option") or {}
    selected_accommodation = state.get("selected_accommodation_option") or {}
    food_pois = _get_food_pois(state)
    destination_pois = _get_destination_pois(destination_context)
    itinerary_text = _itinerary_text(itinerary)

    confirmed_items = []
    estimated_items = []
    verification_items = []

    transport_price = selected_transport_option.get("price")
    if isinstance(transport_price, (int, float)) and transport_price > 0:
        confirmed_items.append(
            f"交通：已记录具体交通方案参考价 {transport_price:.0f} 元/人。"
        )
    else:
        estimated_items.append("交通：缺少具体票价，按交通方式基准价估算。")
    verification_items.append("交通：正式购票前复核实时票价、余票、退改签规则和行李限制。")

    hotel_price = selected_accommodation.get("price_per_night")
    hotel_name = selected_accommodation.get("name", "已选酒店")
    if isinstance(hotel_price, (int, float)) and hotel_price > 0:
        confirmed_items.append(
            f"住宿：{hotel_name} 已记录每间夜参考价 {hotel_price:.0f} 元。"
        )
    else:
        estimated_items.append("住宿：缺少已选酒店价格，按兜底每间夜价格估算。")
    verification_items.append("住宿：入住前复核房型、税费、取消政策、押金和儿童/加床规则。")

    matched_food_names = []
    for food_poi in food_pois:
        name = str(food_poi.get("name") or "").strip()
        average_cost = food_poi.get("average_cost")
        if name and name in itinerary_text and isinstance(average_cost, (int, float)) and average_cost > 0:
            matched_food_names.append(f"{name} {average_cost:g} 元/人")
    if matched_food_names:
        estimated_items.append(
            f"餐饮：按行程餐饮 POI 人均价估算（{'、'.join(matched_food_names)}）。"
        )
    else:
        estimated_items.append("餐饮：缺少具体餐饮人均价，按餐饮偏好或兜底餐价估算。")
    verification_items.append("餐饮：热门餐厅需复核营业时间、预约、排队风险和节假日价格。")

    paid_attractions = []
    for poi in destination_pois:
        name = str(poi.get("name") or "").strip()
        cost = poi.get("estimated_cost")
        if name and name in itinerary_text and isinstance(cost, (int, float)) and cost > 0:
            paid_attractions.append(f"{name} {cost:g} 元/人")
    if paid_attractions:
        estimated_items.append(
            f"景点：按结构化 POI 参考门票估算（{'、'.join(paid_attractions)}）。"
        )
    elif destination_pois:
        estimated_items.append("景点：当前行程未识别到付费 POI，暂按 0 元估算。")
    else:
        estimated_items.append("景点：缺少结构化 POI 费用，按兜底日均景点费用估算。")
    verification_items.append("景点：出发前复核开放日、预约名额、临展收费和儿童/老人优惠。")

    estimated_items.append("其他：市内交通、寄存、临时休息和小额杂费按 100 元/人/天估算。")
    verification_items.append("天气/体力：如切换 Plan B，预算可能随室内场馆、打车或休息安排变化。")

    if len(confirmed_items) >= 2 and len(matched_food_names) >= 1 and destination_pois:
        confidence_level = "中高"
    elif confirmed_items:
        confidence_level = "中"
    else:
        confidence_level = "偏低"

    return {
        "confidence_level": confidence_level,
        "confirmed_items": confirmed_items,
        "estimated_items": estimated_items,
        "verification_items": verification_items,
    }


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


def _default_food_pois(food_types: list[str]) -> list[dict]:
    defaults_by_type = {
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
    return _default_food_pois(state.get("selected_food_types") or [])


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


def _format_money(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f} 元"
    return "待确认"


def _format_food_preferences(food_types: list[str]) -> str:
    labels = [FOOD_LABELS.get(food_type, food_type) for food_type in food_types]
    return "、".join(labels) if labels else "待确认"


def _format_itinerary_highlights(itinerary: list[dict], max_days: int = 5) -> list[str]:
    highlights = []
    for day in itinerary[:max_days]:
        day_number = day.get("day_number", len(highlights) + 1)
        theme = day.get("theme") or "当日安排"
        activities = [str(item) for item in day.get("activities", [])[:2]]
        activity_text = "；".join(activities) if activities else "具体活动待确认"
        highlights.append(f"- Day {day_number}｜{theme}：{activity_text}")
    if len(itinerary) > max_days:
        highlights.append(f"- 其余 {len(itinerary) - max_days} 天按已生成行程继续执行。")
    return highlights or ["- 行程明细待确认。"]


def _format_itinerary_details(itinerary: list[dict], max_days: int = 8) -> list[str]:
    if not itinerary:
        return ["- 行程明细待确认。"]

    lines = []
    for day in itinerary[:max_days]:
        day_number = day.get("day_number", len(lines) + 1)
        theme = day.get("theme") or "当日安排"
        lines.append(f"- Day {day_number}｜{theme}")
        time_blocks = day.get("time_blocks") or []
        if time_blocks:
            lines.extend(f"  {block}" for block in time_blocks)
        else:
            activities = day.get("activities") or []
            for activity in activities[:3]:
                lines.append(f"  - {activity}")
        route_note = day.get("route_note") or day.get("transport_note")
        if route_note:
            lines.append(f"  动线/交通：{route_note}")
        meals = day.get("meals") or []
        if meals:
            lines.append(f"  餐饮：{'；'.join(str(item) for item in meals[:3])}")
        accommodation = day.get("accommodation")
        if accommodation:
            lines.append(f"  住宿：{accommodation}")
        plan_b = day.get("plan_b")
        if plan_b:
            lines.append(f"  Plan B：{plan_b}")
    if len(itinerary) > max_days:
        lines.append(f"- 其余 {len(itinerary) - max_days} 天按已生成行程继续执行。")
    return lines


def _format_budget_breakdown(budget: dict) -> list[str]:
    return [
        f"- 交通：{_format_money(budget.get('transport'))}",
        f"- 住宿：{_format_money(budget.get('accommodation'))}",
        f"- 餐饮：{_format_money(budget.get('food'))}",
        f"- 景点/体验：{_format_money(budget.get('attractions'))}",
        f"- 其他机动：{_format_money(budget.get('misc'))}",
        f"- 总计：{_format_money(budget.get('total'))}，人均：{_format_money(budget.get('per_person'))}",
    ]


def _format_budget_assumptions(budget: dict) -> list[str]:
    assumptions = budget.get("assumptions") or []
    if not assumptions:
        return ["- 费用依据待补充，建议以正式预订页面为准。"]
    return [f"- {assumption}" for assumption in assumptions]


def _format_budget_confidence(budget: dict) -> list[str]:
    confidence_level = budget.get("confidence_level") or "待评估"
    confirmed_items = budget.get("confirmed_items") or []
    estimated_items = budget.get("estimated_items") or []
    lines = [f"- 预算置信度：{confidence_level}"]
    if confirmed_items:
        lines.append("- 已确认/可追溯价格：" + "；".join(str(item) for item in confirmed_items))
    if estimated_items:
        lines.append("- 估算项：" + "；".join(str(item) for item in estimated_items))
    return lines


def _format_budget_verification_items(budget: dict) -> list[str]:
    verification_items = budget.get("verification_items") or []
    if not verification_items:
        return ["- 待核验项：正式预订或出发前复核票价、酒店、景点开放和天气。"]
    return [f"- {item}" for item in verification_items]


def _format_budget_fit(requirement: dict, budget: dict) -> str:
    per_person = budget.get("per_person")
    budget_min = requirement.get("budget_min")
    budget_max = requirement.get("budget_max")
    if not isinstance(per_person, (int, float)) or not isinstance(budget_max, (int, float)):
        return "预算匹配：缺少用户预算上限，建议人工复核。"
    if per_person <= budget_max:
        if isinstance(budget_min, (int, float)) and per_person < budget_min:
            return "预算匹配：低于用户预算区间，可考虑升级住宿或增加体验项目。"
        return "预算匹配：在人均预算上限内。"
    return "预算匹配：超过用户预算上限，建议先调整住宿、交通或高票价体验。"


def _format_adjustment_options(state: TravelState, budget: dict) -> list[str]:
    requirement = state.get("user_requirement") or {}
    budget_fit = _format_budget_fit(requirement, budget)
    options = [
        "- 想更省钱：优先调整住宿区域/档次，或减少高票价体验项目。",
        "- 想更省心：保留当前交通和酒店，增加打车/预约/休息时间预算。",
        "- 想更丰富：当前预算若低于区间，可增加一顿特色餐厅或一个付费体验。",
    ]
    if "超过" in budget_fit:
        options.insert(0, "- 当前估算超过预算上限，建议先从住宿和景点/体验费用开始压缩。")
    elif "低于" in budget_fit:
        options.insert(0, "- 当前估算低于预算区间，可考虑升级住宿、增加特色体验或保留为机动金。")
    return options


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
        ]
    )
    if special_needs:
        summary_lines.append(f"- 特殊需求：{special_needs}")

    return _command_with_message(
        "\n".join(summary_lines),
        runtime,
        user_requirement=requirement,
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

        itinerary.append(
            {
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
        )

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

    budget_breakdown = {
        "transport": transport_cost,
        "accommodation": accommodation_cost,
        "food": food_cost,
        "attractions": attractions_cost,
        "misc": misc_cost,
        "total": total_cost,
        "per_person": total_cost / max(total_people, 1),
        "assumptions": assumptions,
        **budget_quality,
    }
    budget_fit = _format_budget_fit(requirement, budget_breakdown)

    budget_summary = "\n".join(
        [
            "预算汇总完成：",
            f"- 总计：{total_cost:.2f} 元",
            f"- 人均：{budget_breakdown['per_person']:.2f} 元",
            f"- 交通：{transport_cost:.2f} 元",
            f"- 住宿：{accommodation_cost:.2f} 元",
            f"- 餐饮：{food_cost:.2f} 元",
            f"- 景点：{attractions_cost:.2f} 元",
            f"- 其他：{misc_cost:.2f} 元",
            "",
            budget_fit,
            "",
            "关键假设：",
            *[f"- {assumption}" for assumption in assumptions],
            "",
            "预算置信度：",
            *_format_budget_confidence(budget_breakdown),
            "",
            "出发前待核验：",
            *_format_budget_verification_items(budget_breakdown),
        ]
    )

    return _command_with_message(
        budget_summary,
        runtime,
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
    if not state.get("budget") or not state.get("itinerary"):
        return _command_with_message(
            "订单生成前需要先完成行程和预算确认。",
            runtime,
        )

    order_id = f"ORDER-{uuid4().hex[:8].upper()}"
    requirement = state.get("user_requirement") or {}
    selected_transport_option = state.get("selected_transport_option") or {}
    selected_accommodation = state.get("selected_accommodation_option") or {}
    budget = state.get("budget") or {}
    itinerary = state.get("itinerary") or []
    selected_food_types = state.get("selected_food_types") or []
    special_needs = requirement.get("special_needs") or "无特别备注"
    report = "\n".join(
        [
            "最终旅行方案报告",
            "",
            "1. 基本信息",
            f"- 目的地：{state.get('selected_destination', '未确认')}",
            f"- 日期：{requirement.get('departure_date', '未确认')} 起，{requirement.get('travel_days', '未确认')} 天",
            f"- 人数：{requirement.get('adult_count', 0)} 成人 + {requirement.get('children_count', 0)} 儿童",
            f"- 旅行风格：{'、'.join(requirement.get('travel_styles') or []) or '待确认'}",
            f"- 特殊需求：{special_needs}",
            "",
            "2. 已确认资源",
            f"- 交通：{TRANSPORT_LABELS.get(state.get('selected_transport'), state.get('selected_transport', '未确认'))}；{_format_transport_option(selected_transport_option)}",
            f"- 住宿：{_format_accommodation_option(selected_accommodation)}",
            f"- 餐饮偏好：{_format_food_preferences(selected_food_types)}",
            "",
            "3. 行程亮点",
            *_format_itinerary_highlights(itinerary),
            "",
            "4. 每日详细行程",
            *_format_itinerary_details(itinerary),
            "",
            "5. 预算明细",
            *_format_budget_breakdown(budget),
            f"- {_format_budget_fit(requirement, budget)}",
            "",
            "6. 费用依据",
            *_format_budget_assumptions(budget),
            "",
            "7. 预算置信度与待核验项",
            *_format_budget_confidence(budget),
            *_format_budget_verification_items(budget),
            "",
            "8. 风险与出行前核验",
            "- 提醒：实时票价、酒店价格、余票和景点开放情况会变动，正式支付或出发前需要再次核实。",
            "- 建议：出发前 24-48 小时再次确认交通、酒店入住政策、天气和景点预约要求。",
            "- 天气/体力：优先保留 Plan B 和每日机动时间，不建议把每天塞满。",
            "",
            "9. 可调整项",
            *_format_adjustment_options(state, budget),
        ]
    )
    message = "\n".join(
        [
            report,
            "",
            "订单生成成功：",
            f"- 订单号：{order_id}",
            "- 支付链接：当前项目未接入真实支付服务，暂不生成支付链接。",
            "感谢使用智能旅行规划系统。",
        ]
    )
    return _command_with_message(
        message,
        runtime,
        order_id=order_id,
        report=report,
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
