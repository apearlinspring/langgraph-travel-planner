"""
Hotel query tools that wrap the raw hotel MCP APIs with planner-friendly inputs.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.core.state import TravelState
from app.mcp_core.client import get_mcp_client
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


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    unique_items: list[str] = []
    for item in items:
        if item and item not in unique_items:
            unique_items.append(item)
    return unique_items


def _strip_place_suffix(place: str) -> str:
    return re.sub(r"(特别行政区|自治区|自治州|省|市|区|县)$", "", place.strip())


def _expand_place_candidates(place: str) -> list[str]:
    raw_place = place.strip()
    stripped_place = _strip_place_suffix(raw_place)
    alias = COMMON_CITY_ALIASES.get(raw_place) or COMMON_CITY_ALIASES.get(stripped_place)
    return _dedupe_preserve_order([raw_place, stripped_place, alias or ""])


def _infer_preferred_tags(preferences: str, children_count: int) -> list[str]:
    inferred_tags: list[str] = []
    preference_text = preferences or ""
    if children_count > 0:
        inferred_tags.extend(["亲子酒店", "提供家庭房", "儿童玩乐设施"])

    for keywords, tags in PREFERENCE_TAG_RULES:
        if any(keyword in preference_text for keyword in keywords):
            inferred_tags.extend(tags)

    return _dedupe_preserve_order(inferred_tags)


def _extract_text_blocks(result: Any) -> str:
    if isinstance(result, list):
        text_blocks = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                text_blocks.append(item.get("text", ""))
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


async def _get_hotel_tool(tool_name: str) -> Any | None:
    manager = await get_mcp_client(servers=["aigohotel-mcp"])
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

    normalized_destination = destination
    if _is_placeholder(destination, {"目的地", "城市", "未确认", "destination"}):
        normalized_destination = state.get("selected_destination") or requirement.get("destination") or destination

    normalized_check_in = check_in_date
    if _is_placeholder(check_in_date, {"日期", "入住日期", "未确认", "check_in_date"}):
        normalized_check_in = requirement.get("departure_date") or check_in_date

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
    normalized_preferences = preferences
    if special_needs and str(special_needs) not in normalized_preferences:
        normalized_preferences = "；".join(
            item for item in [normalized_preferences, str(special_needs)] if item
        )

    normalized_place_type = place_type
    if _is_placeholder(place_type, {"地点类型", "place_type", "未确认"}):
        normalized_place_type = "城市"

    return {
        "destination": normalized_destination,
        "check_in_date": normalized_check_in,
        "stay_nights": normalized_nights,
        "adult_count": normalized_adults,
        "children_count": normalized_children,
        "budget_level": normalized_budget,
        "preferences": normalized_preferences,
        "place_type": normalized_place_type,
    }


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

    search_tool = await _get_hotel_tool("searchHotels")
    if search_tool is None:
        return Command(
            update={
                "messages": [_tool_message("酒店搜索服务当前不可用，请稍后再试。", runtime)]
            }
        )

    budget_key = budget_level if budget_level in STAR_RATING_BY_BUDGET else "comfort"
    preferred_tags = _infer_preferred_tags(preferences, children_count)
    place_candidates = _expand_place_candidates(destination)
    normalized_size = min(max(size, 3), 10)

    search_payload_base = {
        "originQuery": (
            f"请帮我找{destination}适合{adult_count}位成人"
            f"{'和' + str(children_count) + '位儿童' if children_count else ''}"
            f"入住{stay_nights}晚的酒店。用户偏好：{preferences or '交通方便、住得舒适'}。"
        ),
        "placeType": place_type,
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

    for candidate in place_candidates:
        tried_places.append(candidate)
        payload = dict(search_payload_base)
        payload["place"] = candidate

        app_logger.info(
            f"调用 query_hotel_options: destination={destination}, place={candidate}, "
            f"budget={budget_key}, size={normalized_size}"
        )
        result = await search_tool.ainvoke(payload)
        parsed_payload = _parse_search_payload(result)
        hotels = parsed_payload.get("hotelInformationList") or []
        last_message = str(parsed_payload.get("message") or "").strip()

        if hotels:
            limited_hotels = hotels[:normalized_size]
            formatted_hotels = _format_hotels(
                destination,
                candidate,
                limited_hotels,
                preferences,
            )
            return Command(
                update={
                    "messages": [_tool_message(formatted_hotels, runtime)],
                    "accommodation_options": [
                        _normalize_hotel_option(hotel) for hotel in limited_hotels
                    ],
                }
            )

    tried_text = " / ".join(tried_places)
    if last_message:
        message = (
            f"这次暂时没有查到符合条件的酒店。已尝试检索地：{tried_text}。\n"
            f"上游返回：{last_message}\n"
            "建议下一步放宽预算、缩短偏好条件，或者告诉我更具体的区域再查一次。"
        )
        return Command(update={"messages": [_tool_message(message, runtime)]})

    message = (
        f"这次暂时没有查到符合条件的酒店。已尝试检索地：{tried_text}。\n"
        "建议下一步放宽预算、缩短偏好条件，或者告诉我更具体的区域再查一次。"
    )
    return Command(update={"messages": [_tool_message(message, runtime)]})
