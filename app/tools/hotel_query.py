"""
Hotel query tools that wrap the raw hotel MCP APIs with planner-friendly inputs.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from difflib import SequenceMatcher
from typing import Any, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.core.state import TravelState
from app.mcp_core.client import get_mcp_client
from app.tools.execution_guard import (
    audited_command,
    begin_tool_execution,
    build_guard_event,
    fail_tool_execution,
    finalize_tool_execution,
)
from app.tools.guardrails import validate_hotel_query_args
from app.tools.result_validation import validate_hotel_search_result
from app.utils.logger import app_logger


COMMON_CITY_ALIASES = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "苏州": "Suzhou",
    "成都": "Chengdu",
    "重庆": "Chongqing",
    "西安": "Xi'an",
    "武汉": "Wuhan",
    "长沙": "Changsha",
    "厦门": "Xiamen",
    "青岛": "Qingdao",
    "天津": "Tianjin",
    "三亚": "Sanya",
    "昆明": "Kunming",
    "大理": "Dali",
    "丽江": "Lijiang",
    "哈尔滨": "Harbin",
    "拉萨": "Lhasa",
}

PLACE_CANDIDATE_OVERRIDES = {
    "四姑娘山镇": ["四姑娘山", "日隆镇", "四姑娘山景区"],
    "日隆镇": ["四姑娘山", "四姑娘山镇", "四姑娘山景区"],
    "新都桥": ["新都桥镇", "康定新都桥", "康定"],
    "丹巴": ["丹巴县", "甘孜丹巴", "甲居藏寨"],
}

CHINESE_CITY_PREFIXES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "苏州",
    "成都",
    "重庆",
    "西安",
    "武汉",
    "长沙",
    "厦门",
    "青岛",
    "天津",
    "三亚",
    "昆明",
    "大理",
    "丽江",
    "哈尔滨",
    "拉萨",
)

STAR_RATING_BY_BUDGET = {
    "economy": [0.0, 3.5],
    "comfort": [3.5, 4.5],
    "luxury": [4.5, 5.0],
}

PRICE_CAP_BY_BUDGET = {
    "economy": 450.0,
    "comfort": 900.0,
    "luxury": 1800.0,
}

PREFERENCE_TAG_RULES = (
    (("亲子", "带娃", "儿童", "家庭"), ["亲子酒店", "提供家庭房", "儿童玩乐设施", "可提供婴儿床或围栏"]),
    (("泳池", "游泳"), ["室内恒温泳池", "户外泳池"]),
    (("健身",), ["健身房"]),
    (("停车", "自驾"), ["免费停车场"]),
    (("早餐", "含早"), ["供应中式早餐"]),
    (("联通房",), ["提供联通房"]),
)

ACCOMMODATION_PREFERENCE_KEYWORDS = (
    "江景",
    "河景",
    "湖景",
    "水景",
    "景观",
    "海景",
    "山景",
    "亲子",
    "带娃",
    "家庭房",
    "连通房",
    "浴缸",
    "儿童",
    "安静",
    "隔音",
    "交通方便",
    "近地铁",
    "含早餐",
    "含早",
    "早餐",
    "泳池",
    "健身",
    "停车",
    "高档",
    "中高档",
    "便宜",
    "性价比",
)

MAX_FILTERED_PLACE_CANDIDATES = 3
MAX_RELAXED_PLACE_CANDIDATES = 1
HOTEL_SESSION_START_TIMEOUT_SECONDS = 18.0
HOTEL_SEARCH_CALL_TIMEOUT_SECONDS = 12.0
HOTEL_TOTAL_QUERY_TIMEOUT_SECONDS = 35.0
SPECIFIC_PLACE_DISTANCE_LIMIT_METERS = 8000

VALID_PLACE_TYPES = {
    "城市",
    "机场",
    "景点",
    "火车站",
    "地铁站",
    "酒店",
    "区/县",
    "详细地址",
}
PENDING_DATE_VALUES = {
    "",
    "日期",
    "日期待确认",
    "入住日期",
    "入住日期待确认",
    "出发日期",
    "出发日期待确认",
    "待确认",
    "未确认",
    "待核验",
    "待核实",
}

PREFERENCE_SPLIT_MARKERS = (
    "想住",
    "想要",
    "希望",
    "最好",
    "偏好",
    "要求",
    "要住",
    "住在",
    "入住",
)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    unique_items: list[str] = []
    for item in items:
        if item and item not in unique_items:
            unique_items.append(item)
    return unique_items


def _normalize_match_text(value: str) -> str:
    return re.sub(r"[()（）·•、,/\\\-\s，。；;:：]", "", value or "").strip().lower()


def _strip_place_suffix(place: str) -> str:
    return re.sub(
        r"(特别行政区|自治区|自治州|新区|风景区|景区|街道|省|市|区|县|镇)$",
        "",
        place.strip(),
    )


def _extract_city_prefix(place: str) -> str:
    compact_place = re.sub(r"[()（）·•/\\-\\s]", "", place or "")
    for city in CHINESE_CITY_PREFIXES:
        if compact_place.startswith(city) and compact_place != city:
            return city
    return ""


def _find_city_prefix(place: str) -> str:
    compact_place = re.sub(r"^[\s，,。；;、]+", "", place or "")
    for city in sorted(CHINESE_CITY_PREFIXES, key=len, reverse=True):
        if compact_place.startswith(city):
            return city
    return ""


def _expand_place_candidates(place: str) -> list[str]:
    raw_place = place.strip()
    stripped_place = _strip_place_suffix(raw_place)
    city_prefix = _extract_city_prefix(raw_place) or _extract_city_prefix(stripped_place)
    alias = COMMON_CITY_ALIASES.get(raw_place) or COMMON_CITY_ALIASES.get(stripped_place)
    overrides = (
        PLACE_CANDIDATE_OVERRIDES.get(raw_place)
        or PLACE_CANDIDATE_OVERRIDES.get(stripped_place)
        or []
    )
    city_alias = COMMON_CITY_ALIASES.get(city_prefix, "")
    return _dedupe_preserve_order(
        [raw_place, stripped_place, *overrides, city_prefix, alias or city_alias or ""]
    )


def _contains_accommodation_preference(text: str) -> bool:
    return _looks_like_accommodation_preference(text, "")


def _find_preference_start(text: str) -> int:
    indices = [
        index
        for marker in PREFERENCE_SPLIT_MARKERS
        if (index := text.find(marker)) > 0
    ]
    indices.extend(
        index
        for keyword in ACCOMMODATION_PREFERENCE_KEYWORDS
        if (index := text.find(keyword)) > 0
    )
    return min(indices) if indices else -1


def _clean_destination_phrase(text: str) -> str:
    cleaned = re.sub(r"^[\s，,。；;、]+|[\s，,。；;、]+$", "", text or "")
    cleaned = re.sub(r"(附近|周边|周围|一带|旁边|附近的酒店|酒店|住宿)$", "", cleaned)
    city_prefix = _find_city_prefix(cleaned)
    if city_prefix:
        suffix = cleaned[len(city_prefix):].strip()
        if suffix in {"亲子游", "亲子", "家庭游", "旅游", "旅行", "出游", "游"}:
            return city_prefix
    return cleaned


def _looks_like_specific_location(text: str) -> bool:
    return bool(
        _find_city_prefix(text)
        and re.search(r"(路|街|大道|巷|弄|号|广场|商圈|中心|公园|景区|风景区|机场|车站|地铁站|寺|庙|湖|山|桥|滩)", text)
    )


def _split_destination_and_preferences(
    destination: str,
    preferences: str,
    selected_destination: str = "",
) -> tuple[str, str]:
    text = str(destination or "").strip()
    if not text or not _contains_accommodation_preference(text):
        return destination, preferences

    extracted_destination = ""
    extracted_preferences = ""
    preference_start = _find_preference_start(text)
    if preference_start <= 0 and _looks_like_specific_location(text):
        return _clean_destination_phrase(text), preferences

    if preference_start > 0:
        extracted_destination = _clean_destination_phrase(text[:preference_start])
        extracted_preferences = text[preference_start:].strip(" ，,。；;、")
    else:
        city_prefix = _find_city_prefix(text)
        if city_prefix and text != city_prefix:
            extracted_destination = city_prefix
            extracted_preferences = text[len(city_prefix):].strip(" ，,。；;、")
        elif selected_destination:
            extracted_destination = selected_destination
            extracted_preferences = text

    if selected_destination and (
        not extracted_destination
        or _contains_accommodation_preference(extracted_destination)
        or extracted_destination in {"亲子游", "家庭游", "旅游", "旅行", "出游"}
    ):
        extracted_destination = selected_destination

    if not extracted_destination:
        return destination, preferences

    normalized_preferences = preferences
    if extracted_preferences and extracted_preferences not in normalized_preferences:
        normalized_preferences = "；".join(
            item for item in [normalized_preferences, extracted_preferences] if item
        )
    return extracted_destination, normalized_preferences


def _infer_place_type(place: str, requested_place_type: str) -> str:
    place_text = str(place or "").strip()
    requested = requested_place_type if requested_place_type in VALID_PLACE_TYPES else "城市"
    if not place_text:
        return requested

    stripped_place = _strip_place_suffix(place_text)
    if (
        place_text in COMMON_CITY_ALIASES
        or stripped_place in COMMON_CITY_ALIASES
        or place_text in set(COMMON_CITY_ALIASES.values())
    ):
        return "城市"
    if place_text.endswith("机场"):
        return "机场"
    if "地铁" in place_text:
        return "地铁站"
    if place_text.endswith(("火车站", "高铁站")):
        return "火车站"
    if place_text.endswith(("区", "县")):
        return "区/县"
    if place_text.endswith(("景区", "风景区")):
        return "景点"
    if _extract_city_prefix(place_text) and re.search(r"(路|街|大道|道|巷|弄|号|广场|商圈|中心|附近|周边|一带|\d)", place_text):
        return "详细地址"
    return requested


def _build_place_candidates(destination: str, requested_place_type: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for candidate in _expand_place_candidates(destination):
        if candidate in COMMON_CITY_ALIASES.values():
            candidate_place_type = "城市"
        elif candidate == destination:
            candidate_place_type = _infer_place_type(candidate, requested_place_type)
        elif candidate in COMMON_CITY_ALIASES:
            candidate_place_type = "城市"
        else:
            candidate_place_type = _infer_place_type(candidate, "城市")
        candidates.append({"place": candidate, "place_type": candidate_place_type})

    unique_candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate["place"], candidate["place_type"])
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def _build_relevance_tokens(place: str) -> list[str]:
    tokens: list[str] = []
    for candidate in _expand_place_candidates(place):
        cleaned = _normalize_match_text(candidate or "")
        if len(cleaned) >= 2:
            tokens.append(cleaned)
        stripped = re.sub(r"(风景区|景区|街道|省|市|区|县|镇)$", "", cleaned)
        if len(stripped) >= 2:
            tokens.append(stripped)
    return _dedupe_preserve_order(tokens)


def _fuzzy_token_in_text(token: str, normalized_haystack: str) -> bool:
    if len(token) < 4 or len(normalized_haystack) < 4:
        return False

    window_size = min(max(len(token) + 2, 4), len(normalized_haystack))
    threshold = 0.88 if re.search(r"[\u4e00-\u9fff]", token) else 0.9
    for start in range(0, len(normalized_haystack) - window_size + 1):
        window = normalized_haystack[start:start + window_size]
        if SequenceMatcher(None, token, window).ratio() >= threshold:
            return True
    return False


def _hotel_matches_destination(hotel: dict[str, Any], place: str) -> bool:
    tokens = _build_relevance_tokens(place)
    if not tokens:
        return True

    haystack = " ".join(
        str(hotel.get(field) or "") for field in ("name", "address", "description")
    )
    normalized_haystack = _normalize_match_text(haystack)
    if not normalized_haystack:
        return False

    return any(
        token in normalized_haystack or _fuzzy_token_in_text(token, normalized_haystack)
        for token in tokens
    )


def _relax_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    relaxed_payload = dict(payload)
    filter_options = dict(relaxed_payload.get("filterOptions") or {})
    distance_limit = filter_options.get("distanceInMeter")
    relaxed_payload.pop("filterOptions", None)
    if distance_limit:
        relaxed_payload["filterOptions"] = {"distanceInMeter": distance_limit}
    hotel_tags = dict(relaxed_payload.get("hotelTags") or {})
    if "preferredTags" in hotel_tags:
        hotel_tags.pop("preferredTags", None)
    if hotel_tags:
        relaxed_payload["hotelTags"] = hotel_tags
    else:
        relaxed_payload.pop("hotelTags", None)
    return relaxed_payload


def _infer_preferred_tags(preferences: str, children_count: int) -> list[str]:
    inferred_tags: list[str] = []
    preference_text = preferences or ""
    compact_preference_text = re.sub(r"[的得地\s,，。；;、/\\-]", "", preference_text)
    if children_count > 0:
        inferred_tags.extend(["亲子酒店", "提供家庭房", "儿童玩乐设施"])

    for keywords, tags in PREFERENCE_TAG_RULES:
        if any(keyword in preference_text for keyword in keywords):
            inferred_tags.extend(tags)

    has_water_view_preference = (
        any(keyword in compact_preference_text for keyword in ("江景", "河景", "湖景", "水景", "景观房", "观景"))
        or ("江" in compact_preference_text and "景" in compact_preference_text)
        or ("河" in compact_preference_text and "景" in compact_preference_text)
        or ("湖" in compact_preference_text and "景" in compact_preference_text)
    )
    if has_water_view_preference:
        inferred_tags.extend(["江景房", "河景房", "湖景房", "景观房"])

    return _dedupe_preserve_order(inferred_tags)


def _extract_text_blocks(result: Any) -> str:
    if hasattr(result, "content"):
        return _extract_text_blocks(getattr(result, "content"))
    if isinstance(result, list):
        text_blocks = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                text_blocks.append(item.get("text", ""))
            elif hasattr(item, "text"):
                text_blocks.append(str(getattr(item, "text") or ""))
            else:
                text_blocks.append(str(item))
        return "\n".join(text_blocks)
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def _parse_search_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result

    payload_text = _extract_text_blocks(result).strip()
    if not payload_text:
        return {"message": "", "hotelInformationList": []}

    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", payload_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    return {
        "message": payload_text,
        "hotelInformationList": [],
    }


def _format_distance(distance_in_meters: Any) -> str:
    if not isinstance(distance_in_meters, (int, float)):
        return "距离信息未知"
    if distance_in_meters < 1000:
        return f"{int(distance_in_meters)} 米"
    return f"{distance_in_meters / 1000:.1f} 公里"


def _format_price(hotel: dict[str, Any]) -> str:
    price_info = hotel.get("price") or {}
    if isinstance(price_info, dict):
        lowest_price = price_info.get("lowestPrice")
        currency = price_info.get("currency", "CNY")
        if isinstance(lowest_price, (int, float)):
            return f"{lowest_price:.0f} {currency}/晚"
        message = price_info.get("message")
        if message:
            return str(message)
    return "价格待确认"


def _extract_price_per_night(hotel: dict[str, Any]) -> float:
    price_info = hotel.get("price") or {}
    if isinstance(price_info, dict):
        lowest_price = price_info.get("lowestPrice")
        if isinstance(lowest_price, (int, float)):
            return float(lowest_price)
    return 0.0


def _infer_accommodation_type(hotel: dict[str, Any]) -> str:
    star_rating = hotel.get("starRating")
    if isinstance(star_rating, (int, float)) and star_rating < 3.5:
        return "economy_hotel"
    return "star_hotel"


def _normalize_hotel_option(hotel: dict[str, Any]) -> dict[str, Any]:
    amenities = hotel.get("tags") or hotel.get("hotelAmenities") or []
    if not isinstance(amenities, list):
        amenities = []

    option = {
        "name": hotel.get("name") or "未命名酒店",
        "type": _infer_accommodation_type(hotel),
        "location": hotel.get("address") or "地址待补充",
        "price_per_night": _extract_price_per_night(hotel),
        "rating": hotel.get("starRating"),
        "amenities": [str(item) for item in amenities[:10]],
        "source": "aigohotel-mcp",
    }

    hotel_id = hotel.get("hotelId")
    if isinstance(hotel_id, int):
        option["hotel_id"] = hotel_id
    booking_url = hotel.get("bookingUrl")
    if booking_url:
        option["booking_url"] = str(booking_url)

    return option


def _pick_fit_reason(hotel: dict[str, Any], preferences: str) -> str:
    hotel_tags = hotel.get("tags") or []
    if not isinstance(hotel_tags, list):
        hotel_tags = []

    preference_text = preferences or ""
    matched_tags = []
    for tag in hotel_tags:
        if any(keyword in tag for keyword in ("亲子", "家庭", "早餐", "泳池", "健身", "联通房", "停车")):
            matched_tags.append(str(tag))
        elif preference_text and any(keyword in str(tag) for keyword in preference_text.split()):
            matched_tags.append(str(tag))

    matched_tags = _dedupe_preserve_order(matched_tags)
    if matched_tags:
        return f"更贴合你的需求：{', '.join(matched_tags[:3])}"

    description = re.sub(r"<[^>]+>", "", hotel.get("description") or "")
    description = re.sub(r"\s+", " ", description).strip()
    if description:
        return description[:70] + ("..." if len(description) > 70 else "")

    return "位置和基础配置更均衡，适合先加入候选。"


def _format_hotels(
    destination: str,
    actual_place: str,
    hotels: list[dict[str, Any]],
    preferences: str,
) -> str:
    lines = [
        f"已为 {destination} 找到 {len(hotels)} 家真实酒店候选。",
        f"实际检索地：{actual_place}",
        "",
    ]

    for index, hotel in enumerate(hotels, start=1):
        lines.append(f"{index}. {hotel.get('name', '未命名酒店')}")
        lines.append(f"   - 酒店ID：{hotel.get('hotelId', '未知')}")
        lines.append(
            f"   - 星级：{hotel.get('starRating', '未知')}，参考价：{_format_price(hotel)}"
        )
        lines.append(
            f"   - 位置：{hotel.get('address', '地址待补充')}，距检索中心约 {_format_distance(hotel.get('distanceInMeters'))}"
        )
        lines.append(f"   - 适配理由：{_pick_fit_reason(hotel, preferences)}")

    lines.extend(
        [
            "",
            "如果你想继续确认某一家，我可以再查这家酒店更细的房型、退改和实时价格。",
        ]
    )
    return "\n".join(lines)


class _HotelSearchSessionTool:
    """Invoke hotel MCP calls through one stdio session for a full query."""

    def __init__(self, tool_name: str) -> None:
        self.name = tool_name
        self._session_context: Any | None = None
        self._session: Any | None = None

    async def __aenter__(self) -> "_HotelSearchSessionTool":
        manager = await get_mcp_client()
        self._session_context = manager.session("aigohotel-mcp")
        self._session = await asyncio.wait_for(
            self._session_context.__aenter__(),
            timeout=HOTEL_SESSION_START_TIMEOUT_SECONDS,
        )
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc, tb)
        self._session_context = None
        self._session = None

    async def ainvoke(self, payload: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("Hotel MCP session is not initialized")
        return await self._session.call_tool(self.name, payload)


async def _get_hotel_tool(tool_name: str) -> Any | None:
    if tool_name == "searchHotels":
        manager = await get_mcp_client()
        if "aigohotel-mcp" not in manager.SERVER_CONFIGS:
            return None
        return _HotelSearchSessionTool(tool_name)

    manager = await get_mcp_client()
    tools = await manager.get_tools(servers=["aigohotel-mcp"])
    for tool_instance in tools:
        if tool_instance.name == tool_name:
            return tool_instance
    return None


def _tool_message(content: str, runtime: Optional[ToolRuntime]) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=getattr(runtime, "tool_call_id", ""),
    )


def _is_placeholder(value: object, placeholders: set[str]) -> bool:
    text = str(value or "").strip()
    return not text or text in placeholders


def _looks_like_accommodation_preference(value: object, selected_destination: str = "") -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if selected_destination and selected_destination in text:
        return False
    if any(keyword in text for keyword in ACCOMMODATION_PREFERENCE_KEYWORDS):
        return True
    return bool(re.search(r"(房型|房间|酒店|住宿|附近|周边|商圈|市中心|景点|地铁|机场|高铁站)$", text))


def _requirement_departure_date_confirmation(
    requirement: dict,
    normalized_date: str,
) -> tuple[bool | None, str]:
    if not requirement:
        return None, ""

    date_text = str(normalized_date or "").strip()
    if date_text in PENDING_DATE_VALUES:
        return False, "pending"
    if requirement.get("departure_date_confirmed") is False:
        return False, str(requirement.get("departure_date_source") or "unconfirmed")
    if requirement.get("departure_date_confirmed") is True:
        return True, str(requirement.get("departure_date_source") or "user_confirmed")
    return True, str(requirement.get("departure_date_source") or "legacy_confirmed")


def _normalize_query_args_from_state(
    *,
    destination: str,
    check_in_date: str,
    stay_nights: int,
    adult_count: int,
    children_count: int,
    budget_level: str,
    preferences: str,
    place_type: str,
    runtime: Optional[ToolRuntime],
) -> dict[str, Any]:
    state = runtime.state if runtime and runtime.state else {}
    requirement = state.get("user_requirement") or {}

    state_destination = state.get("selected_destination") or requirement.get("destination")
    normalized_destination = destination
    normalized_preferences = preferences
    split_destination, split_preferences = _split_destination_and_preferences(
        str(destination or ""),
        normalized_preferences,
        str(state_destination or ""),
    )
    normalized_destination = split_destination
    normalized_preferences = split_preferences
    destination_is_placeholder = _is_placeholder(destination, {"目的地", "城市", "未确认", "destination"})
    destination_is_preference = (
        bool(state_destination)
        and _looks_like_accommodation_preference(destination, str(state_destination))
    )
    if destination_is_placeholder or destination_is_preference:
        normalized_destination = state_destination or destination

    normalized_check_in = check_in_date
    if _is_placeholder(check_in_date, {"日期", "入住日期", "未确认", "check_in_date"}):
        normalized_check_in = requirement.get("departure_date") or check_in_date
    date_confirmed, date_source = _requirement_departure_date_confirmation(
        requirement,
        str(normalized_check_in or ""),
    )

    travel_days = requirement.get("travel_days")
    normalized_nights = stay_nights
    if isinstance(travel_days, int) and travel_days > 1:
        expected_nights = travel_days - 1
        if not isinstance(stay_nights, int) or stay_nights <= 0 or stay_nights >= travel_days:
            normalized_nights = expected_nights
    elif not isinstance(stay_nights, int) or stay_nights <= 0:
        normalized_nights = 1

    normalized_adults = adult_count
    if not isinstance(adult_count, int) or adult_count <= 0:
        normalized_adults = int(requirement.get("adult_count") or 2)

    normalized_children = children_count
    if not isinstance(children_count, int) or children_count < 0:
        normalized_children = int(requirement.get("children_count") or 0)

    normalized_budget = budget_level
    if budget_level not in STAR_RATING_BY_BUDGET:
        normalized_budget = requirement.get("budget_level") or "comfort"

    special_needs = requirement.get("special_needs")
    if destination_is_preference and str(destination).strip() not in normalized_preferences:
        normalized_preferences = "；".join(
            item for item in [normalized_preferences, str(destination).strip()] if item
        )
    if special_needs and str(special_needs) not in normalized_preferences:
        normalized_preferences = "；".join(
            item for item in [normalized_preferences, str(special_needs)] if item
        )

    normalized_place_type = place_type
    if _is_placeholder(place_type, {"地点类型", "place_type", "未确认"}):
        normalized_place_type = "城市"

    normalized_args = {
        "destination": normalized_destination,
        "check_in_date": normalized_check_in,
        "stay_nights": normalized_nights,
        "adult_count": normalized_adults,
        "children_count": normalized_children,
        "budget_level": normalized_budget,
        "preferences": normalized_preferences,
        "place_type": normalized_place_type,
    }
    if date_confirmed is not None:
        normalized_args["check_in_date_confirmed"] = date_confirmed
        normalized_args["check_in_date_source"] = date_source
    return normalized_args


def _build_search_payload_for_candidate(
    search_payload_base: dict[str, Any],
    candidate: dict[str, str],
) -> dict[str, Any]:
    payload = dict(search_payload_base)
    payload["place"] = candidate["place"]
    payload["placeType"] = candidate["place_type"]
    if candidate["place_type"] == "详细地址":
        filter_options = dict(payload.get("filterOptions") or {})
        filter_options.setdefault("distanceInMeter", SPECIFIC_PLACE_DISTANCE_LIMIT_METERS)
        payload["filterOptions"] = filter_options
    return payload


async def _search_relevant_hotels(
    *,
    search_tool: Any,
    payload: dict[str, Any],
    destination: str,
    relaxed: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    place = str(payload.get("place") or "")
    place_type = str(payload.get("placeType") or "")
    started_at = time.perf_counter()
    log_prefix = "Hotel query relaxed candidate" if relaxed else "Hotel query candidate"
    app_logger.info(
        f"{log_prefix} started: "
        f"destination={destination}, place={place}, place_type={place_type}, "
        f"size={payload.get('size')}"
    )
    try:
        result = await asyncio.wait_for(
            search_tool.ainvoke(payload),
            timeout=HOTEL_SEARCH_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - started_at
        app_logger.warning(
            f"{log_prefix} timed out: "
            f"destination={destination}, place={place}, "
            f"elapsed_seconds={elapsed:.2f}"
        )
        return [], "酒店搜索上游响应超时，已停止等待这次请求"
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        message = str(exc).strip() or exc.__class__.__name__
        app_logger.warning(
            f"{log_prefix} failed: "
            f"destination={destination}, place={place}, "
            f"elapsed_seconds={elapsed:.2f}, error={message}"
        )
        return [], f"酒店搜索上游异常：{message}"

    elapsed = time.perf_counter() - started_at
    parsed_payload = _parse_search_payload(result)
    hotels = parsed_payload.get("hotelInformationList") or []
    relevant_hotels = [
        hotel for hotel in hotels if _hotel_matches_destination(hotel, destination)
    ]
    app_logger.info(
        f"{log_prefix} completed: "
        f"destination={destination}, place={place}, "
        f"elapsed_seconds={elapsed:.2f}, hotel_count={len(hotels)}, "
        f"relevant_hotel_count={len(relevant_hotels)}"
    )
    return relevant_hotels, str(parsed_payload.get("message") or "").strip()


@tool
async def query_hotel_options(
    destination: str,
    check_in_date: str,
    stay_nights: int,
    adult_count: int = 2,
    children_count: int = 0,
    budget_level: str = "comfort",
    preferences: str = "",
    place_type: str = "城市",
    size: int = 5,
    max_price_per_night: Optional[float] = None,
    runtime: ToolRuntime[None, TravelState] = None,
) -> Command:
    """
    用更稳定的高层参数搜索真实酒店候选，自动处理预算、偏好和地点别名兜底。
    """

    normalized_args = _normalize_query_args_from_state(
        destination=destination,
        check_in_date=check_in_date,
        stay_nights=stay_nights,
        adult_count=adult_count,
        children_count=children_count,
        budget_level=budget_level,
        preferences=preferences,
        place_type=place_type,
        runtime=runtime,
    )
    destination = normalized_args["destination"]
    check_in_date = normalized_args["check_in_date"]
    stay_nights = normalized_args["stay_nights"]
    adult_count = normalized_args["adult_count"]
    children_count = normalized_args["children_count"]
    budget_level = normalized_args["budget_level"]
    preferences = normalized_args["preferences"]
    place_type = normalized_args["place_type"]
    normalized_input = {
        **normalized_args,
        "size": size,
        "max_price_per_night": max_price_per_night,
    }
    guard = begin_tool_execution(
        "query_hotel_options",
        normalized_input,
        runtime=runtime,
        input_validator=validate_hotel_query_args,
        evidence_type="live_hotel_search",
    )
    started_at = guard.context.perf_counter_started_at
    if not guard.ok and guard.blocked_event is not None:
        if guard.blocked_event.get("error_type") == "duplicate_tool_call_same_turn":
            message = guard.blocked_message
        else:
            message = f"酒店真实查询参数不完整：{guard.blocked_message}。请先补齐后再查，我不会编造酒店候选。"
        return audited_command(
            {"messages": [_tool_message(message, runtime)]},
            runtime,
            guard.blocked_event,
            approval_update=guard.approval_update,
        )
    normalized_input = guard.args

    try:
        search_tool = await asyncio.wait_for(
            _get_hotel_tool("searchHotels"),
            timeout=HOTEL_SESSION_START_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        app_logger.warning(
            "Hotel query unavailable while preparing MCP tool: "
            f"destination={destination}, elapsed_seconds={elapsed:.2f}, "
            f"error={exc.__class__.__name__}"
        )
        event = fail_tool_execution(
            guard,
            exc,
            output_summary={"message": "hotel MCP tool preparation failed"},
        )
        return audited_command(
            {
                "messages": [
                    _tool_message(
                        "酒店搜索服务这次没有及时准备好，我不会编造酒店候选；可以稍后重试真实酒店查询。",
                        runtime,
                    )
                ]
            },
            runtime,
            event,
        )
    if search_tool is None:
        elapsed = time.perf_counter() - started_at
        app_logger.warning(
            "Hotel query unavailable: "
            f"destination={destination}, elapsed_seconds={elapsed:.2f}"
        )
        event = build_guard_event(
            guard,
            status="failed",
            output_summary={"message": "hotel MCP server is unavailable"},
            error_type="hotel_mcp_unavailable",
        )
        return audited_command(
            {
                "messages": [_tool_message("酒店搜索服务当前不可用，我不会编造酒店候选；请稍后再试。", runtime)]
            },
            runtime,
            event,
        )

    budget_key = budget_level if budget_level in STAR_RATING_BY_BUDGET else "comfort"
    preferred_tags = _infer_preferred_tags(preferences, children_count)
    place_candidates = _build_place_candidates(destination, place_type)[:MAX_FILTERED_PLACE_CANDIDATES]
    normalized_size = min(max(size, 3), 10)

    search_payload_base = {
        "originQuery": (
            f"请帮我找{destination}适合{adult_count}位成人"
            f"{'和' + str(children_count) + '位儿童' if children_count else ''}"
            f"入住{stay_nights}晚的酒店。用户偏好：{preferences or '交通方便、住得舒适'}。"
        ),
        "checkInParam": {
            "checkInDate": check_in_date,
            "stayNights": stay_nights,
            "adultCount": adult_count,
        },
        "filterOptions": {
            "starRatings": STAR_RATING_BY_BUDGET[budget_key],
        },
        "size": normalized_size,
    }

    hotel_tags: dict[str, Any] = {}
    if max_price_per_night is not None:
        hotel_tags["maxPricePerNight"] = max_price_per_night
    elif budget_key in PRICE_CAP_BY_BUDGET:
        hotel_tags["maxPricePerNight"] = PRICE_CAP_BY_BUDGET[budget_key]
    if preferred_tags:
        hotel_tags["preferredTags"] = preferred_tags
    if hotel_tags:
        search_payload_base["hotelTags"] = hotel_tags

    tried_places: list[str] = []
    last_message = ""

    matched_hotels: list[dict[str, Any]] = []
    matched_place = ""

    async def run_searches(active_search_tool: Any) -> tuple[list[dict[str, Any]], str, str]:
        nonlocal last_message
        for candidate in place_candidates:
            tried_places.append(f"{candidate['place']}({candidate['place_type']})")
            payload = _build_search_payload_for_candidate(search_payload_base, candidate)

            relevant_hotels, message = await _search_relevant_hotels(
                search_tool=active_search_tool,
                payload=payload,
                destination=destination,
            )
            if message:
                last_message = message
            if relevant_hotels:
                return relevant_hotels, candidate["place"], last_message

        for candidate in place_candidates[:MAX_RELAXED_PLACE_CANDIDATES]:
            payload = _build_search_payload_for_candidate(search_payload_base, candidate)
            relaxed_payload = _relax_search_payload(payload)
            relevant_hotels, message = await _search_relevant_hotels(
                search_tool=active_search_tool,
                payload=relaxed_payload,
                destination=destination,
                relaxed=True,
            )
            if message:
                last_message = message
            if relevant_hotels:
                return relevant_hotels, candidate["place"], last_message
        return [], "", last_message

    async def run_with_active_tool() -> tuple[list[dict[str, Any]], str, str]:
        if hasattr(search_tool, "__aenter__"):
            async with search_tool as active_search_tool:
                return await run_searches(active_search_tool)
        return await run_searches(search_tool)

    try:
        matched_hotels, matched_place, last_message = await asyncio.wait_for(
            run_with_active_tool(),
            timeout=HOTEL_TOTAL_QUERY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        total_elapsed = time.perf_counter() - started_at
        app_logger.warning(
            "Hotel query stopped by total runtime budget: "
            f"destination={destination}, elapsed_seconds={total_elapsed:.2f}, "
            f"tried_places={' / '.join(tried_places)}"
        )
        event = fail_tool_execution(
            guard,
            exc,
            output_summary={
                "message": "hotel query exceeded per-turn runtime budget",
                "tried_places": tried_places,
            },
            retry_count=max(len(tried_places) - 1, 0),
        )
        return audited_command(
            {
                "messages": [
                    _tool_message(
                        "酒店查询超过本轮运行预算，已停止继续等待上游结果。"
                        "我不会编造酒店候选；可以下一轮放宽区域、预算或偏好后重新查询。",
                        runtime,
                    )
                ]
            },
            runtime,
            event,
        )
    except Exception as exc:
        total_elapsed = time.perf_counter() - started_at
        message = str(exc).strip() or exc.__class__.__name__
        app_logger.warning(
            "Hotel query failed without crashing workflow: "
            f"destination={destination}, elapsed_seconds={total_elapsed:.2f}, "
            f"error={message}"
        )
        event = fail_tool_execution(
            guard,
            exc,
            output_summary={"message": message},
            retry_count=max(len(tried_places) - 1, 0),
        )
        return audited_command(
            {
                "messages": [
                    _tool_message(
                        f"酒店搜索服务这次调用失败：{message}。我不会编造酒店候选；可以稍后重试真实酒店查询。",
                        runtime,
                    )
                ]
            },
            runtime,
            event,
        )

    if matched_hotels:
        limited_hotels = matched_hotels[:normalized_size]
        formatted_hotels = _format_hotels(
            destination,
            matched_place,
            limited_hotels,
            preferences,
        )
        total_elapsed = time.perf_counter() - started_at
        app_logger.info(
            "Hotel query completed: "
            f"destination={destination}, place={matched_place}, "
            f"elapsed_seconds={total_elapsed:.2f}, hotel_count={len(limited_hotels)}"
        )
        result_validation = validate_hotel_search_result(limited_hotels, last_message)
        event = finalize_tool_execution(
            guard,
            result_validation,
            output_summary={
                **result_validation.output_summary,
                "actual_place": matched_place,
            },
            retry_count=max(len(tried_places) - 1, 0),
        )
        return audited_command(
            {
                "messages": [_tool_message(formatted_hotels, runtime)],
                "accommodation_options": [
                    _normalize_hotel_option(hotel) for hotel in limited_hotels
                ],
            },
            runtime,
            event,
        )

    tried_text = " / ".join(tried_places)
    if last_message:
        total_elapsed = time.perf_counter() - started_at
        app_logger.warning(
            "Hotel query returned no results: "
            f"destination={destination}, elapsed_seconds={total_elapsed:.2f}, "
            f"tried_places={tried_text}"
        )
        message = (
            f"这次暂时没有查到符合条件的酒店。已尝试检索地：{tried_text}。\n"
            f"上游返回：{last_message}\n"
            "建议下一步放宽预算、缩短偏好条件，或者告诉我更具体的区域再查一次。"
        )
        result_validation = validate_hotel_search_result([], last_message)
        event = finalize_tool_execution(
            guard,
            result_validation,
            output_summary={
                **result_validation.output_summary,
                "tried_places": tried_places,
            },
            retry_count=max(len(tried_places) - 1, 0),
        )
        return audited_command({"messages": [_tool_message(message, runtime)]}, runtime, event)

    total_elapsed = time.perf_counter() - started_at
    app_logger.warning(
        "Hotel query exhausted all candidates: "
        f"destination={destination}, elapsed_seconds={total_elapsed:.2f}, "
        f"tried_places={tried_text}"
    )
    message = (
        f"这次暂时没有查到符合条件的酒店。已尝试检索地：{tried_text}。\n"
        "建议下一步放宽预算、缩短偏好条件，或者告诉我更具体的区域再查一次。"
    )
    result_validation = validate_hotel_search_result([], last_message)
    event = finalize_tool_execution(
        guard,
        result_validation,
        output_summary={
            **result_validation.output_summary,
            "tried_places": tried_places,
        },
        retry_count=max(len(tried_places) - 1, 0),
    )
    return audited_command({"messages": [_tool_message(message, runtime)]}, runtime, event)
