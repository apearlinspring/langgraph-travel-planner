"""Route normalization helpers for structured travel reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.journey.route_preferences import (
    normalize_route_segment_mode,
    route_segment_duration_matches_mode,
    route_segment_mode_label,
)


@dataclass(frozen=True)
class RouteBuilderServices:
    """State-specific callbacks used to fill report itinerary and map routes."""

    recommended_accommodation_area: Callable[[str], str]
    destination_pois_for_report: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]
    pick_report_pois_for_day: Callable[[list[dict[str, Any]], int, int], list[dict[str, Any]]]
    poi_names: Callable[[list[dict[str, Any]]], list[str]]
    format_poi_activity: Callable[[list[dict[str, Any]], str], str]
    format_reservation_note: Callable[[list[dict[str, Any]]], str | None]
    format_indoor_backup: Callable[[list[dict[str, Any]]], str | None]
    get_destination_context: Callable[[dict[str, Any], str], dict[str, Any]]
    get_food_pois: Callable[[dict[str, Any]], list[dict[str, Any]]]
    pick_food_poi: Callable[..., dict[str, Any] | None]
    format_food_poi_summary: Callable[[dict[str, Any] | None, str], str]
    format_weather_plan_b: Callable[[Any], str]
    build_fallback_accommodation_option: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RouteAlignmentResult:
    """Normalized itinerary and map routes plus explicit alignment findings."""

    itinerary: list[dict[str, Any]]
    route_summaries: list[dict[str, Any]]
    findings: list[str] = field(default_factory=list)


ROUTE_POINT_TYPE_LABELS = {
    "transport": "交通节点",
    "accommodation": "住宿/落脚",
    "attraction": "景点/体验",
    "business_district": "商业街区",
    "food": "美食",
    "city": "城市节点",
    "other": "路线点",
}

ROUTE_SEGMENT_VERIFICATION_LABELS = {
    "verified": "已核验",
    "estimated": "估算",
    "needs_live_route": "待核验",
}


def dedupe_route_points(points: list[str], max_items: int = 6) -> list[str]:
    picked = []
    for point in points:
        normalized = str(point or "").strip()
        if not normalized or normalized in picked:
            continue
        picked.append(normalized)
        if len(picked) >= max_items:
            break
    return picked


def normalize_route_segment_verification_status(segment: dict[str, Any]) -> str:
    explicit = str(segment.get("verification_status") or "").strip().lower()
    if explicit in ROUTE_SEGMENT_VERIFICATION_LABELS:
        return explicit
    source = " ".join(
        str(item or "")
        for item in (
            segment.get("confidence"),
            segment.get("source"),
            segment.get("verification_note"),
            segment.get("distance_text"),
            segment.get("duration_text"),
        )
    ).lower()
    if "amap_driving" in source or "verified" in source or "已核验" in source:
        return "verified"
    if "estimated" in source or "估算" in source:
        return "estimated"
    return "needs_live_route"


def _segment_duration_for_mode(
    *,
    mode: str,
    selected_mode: str,
    duration_text: str,
    fallback: str,
) -> str:
    if duration_text and "待" not in duration_text and "unknown" not in duration_text.lower():
        if (
            normalize_route_segment_mode(mode) == normalize_route_segment_mode(selected_mode)
            and route_segment_duration_matches_mode(mode, duration_text)
        ):
            return duration_text
    return fallback


def default_route_segment_alternatives(
    *,
    selected_mode: str,
    duration_text: str = "",
) -> list[dict[str, str]]:
    return [
        {
            "mode": "taxi",
            "label": "打车",
            "duration_text": _segment_duration_for_mode(
                mode="taxi",
                selected_mode=selected_mode,
                duration_text=duration_text,
                fallback="约10-20分钟",
            ),
            "cost_text": "费用待核验",
            "reason": "省体力，适合赶时间或带行李。",
            "verification_status": "needs_live_route",
        },
        {
            "mode": "transit",
            "label": "公交/地铁",
            "duration_text": _segment_duration_for_mode(
                mode="transit",
                selected_mode=selected_mode,
                duration_text=duration_text,
                fallback="约25-40分钟",
            ),
            "cost_text": "约2-8元",
            "reason": "更省预算，班次和换乘待核验。",
            "verification_status": "needs_live_route",
        },
        {
            "mode": "walking",
            "label": "步行",
            "duration_text": _segment_duration_for_mode(
                mode="walking",
                selected_mode=selected_mode,
                duration_text=duration_text,
                fallback="约30-45分钟",
            ),
            "cost_text": "0元",
            "reason": "适合短距离慢游，体力消耗更高。",
            "verification_status": "needs_live_route",
        },
    ]


def normalize_report_route_segment_alternative(
    option: dict[str, Any],
    *,
    selected_mode: str,
    duration_text: str,
) -> dict[str, Any]:
    mode = normalize_route_segment_mode(
        option.get("mode") or option.get("transport_mode") or option.get("label")
    )
    return {
        "mode": mode,
        "label": str(option.get("label") or route_segment_mode_label(mode)),
        "duration_text": str(
            option.get("duration_text")
            or option.get("duration")
            or _segment_duration_for_mode(
                mode=mode,
                selected_mode=selected_mode,
                duration_text=duration_text,
                fallback="时间待核验",
            )
        ),
        "cost_text": str(option.get("cost_text") or option.get("cost") or "费用待核验"),
        "reason": str(option.get("reason") or option.get("note") or "适配性待核验。"),
        "verification_status": normalize_route_segment_verification_status(option),
    }


def normalize_report_route_segment(
    segment: dict[str, Any] | None,
    *,
    day_number: int,
    index: int,
    from_name: str,
    to_name: str,
) -> dict[str, Any]:
    base = dict(segment or {})
    selected_mode = normalize_route_segment_mode(
        base.get("selected_mode")
        or base.get("mode")
        or base.get("transport_mode")
        or base.get("duration_text")
        or base.get("source")
    )
    recommended_mode = normalize_route_segment_mode(
        base.get("recommended_mode") or base.get("mode") or selected_mode
    )
    duration_text = str(base.get("duration_text") or "待高德路线核验")
    raw_alternatives = base.get("alternatives") if isinstance(base.get("alternatives"), list) else []
    alternatives = [
        normalize_report_route_segment_alternative(
            option if isinstance(option, dict) else {"label": option},
            selected_mode=selected_mode,
            duration_text=duration_text,
        )
        for option in raw_alternatives
    ]
    if not alternatives:
        alternatives = default_route_segment_alternatives(
            selected_mode=selected_mode,
            duration_text=duration_text,
        )

    seen_modes: set[str] = set()
    deduped_alternatives: list[dict[str, Any]] = []
    for option in alternatives:
        mode = normalize_route_segment_mode(option.get("mode"))
        if not mode or mode in seen_modes:
            continue
        seen_modes.add(mode)
        deduped_alternatives.append({**option, "mode": mode})

    if selected_mode not in seen_modes:
        selected_duration_text = _segment_duration_for_mode(
            mode=selected_mode,
            selected_mode=selected_mode,
            duration_text=duration_text,
            fallback="时间待核验",
        )
        deduped_alternatives.insert(
            0,
            {
                "mode": selected_mode,
                "label": route_segment_mode_label(selected_mode),
                "duration_text": selected_duration_text,
                "cost_text": str(base.get("cost_text") or "费用待核验"),
                "reason": str(base.get("reason") or "当前推荐方式，真实路线待核验。"),
                "verification_status": normalize_route_segment_verification_status(base),
            },
        )

    verification_status = normalize_route_segment_verification_status(base)
    return {
        "id": str(base.get("id") or f"d{day_number}-s{index + 1}"),
        "day_number": day_number,
        "from_poi_id": str(base.get("from_poi_id") or ""),
        "to_poi_id": str(base.get("to_poi_id") or ""),
        "from_name": str(base.get("from_name") or from_name),
        "to_name": str(base.get("to_name") or to_name),
        "mode": selected_mode,
        "recommended_mode": recommended_mode,
        "selected_mode": selected_mode,
        "mode_label": route_segment_mode_label(selected_mode),
        "locked_by_user": bool(base.get("locked_by_user") or base.get("mode_locked")),
        "verification_status": verification_status,
        "verification_label": ROUTE_SEGMENT_VERIFICATION_LABELS.get(
            verification_status,
            "待核验",
        ),
        "distance_text": str(base.get("distance_text") or "待高德路线核验"),
        "duration_text": duration_text,
        "cost_text": str(base.get("cost_text") or "费用待核验"),
        "confidence": str(base.get("confidence") or verification_status),
        "source": str(base.get("source") or "report_route_segment_contract"),
        "verification_note": str(
            base.get("verification_note")
            or "交通方式为草案偏好，真实路线、票价和耗时待核验。"
        ),
        "alternatives": deduped_alternatives[:3],
    }


def normalize_report_route_segments(
    route_points: list[str],
    *,
    day_number: int,
    raw_segments: Any = None,
) -> list[dict[str, Any]]:
    if len(route_points) < 2:
        return []
    source_segments = raw_segments if isinstance(raw_segments, list) else []
    segments = []
    for index in range(len(route_points) - 1):
        segment = source_segments[index] if index < len(source_segments) else {}
        if not isinstance(segment, dict):
            segment = {}
        segments.append(
            normalize_report_route_segment(
                segment,
                day_number=day_number,
                index=index,
                from_name=route_points[index],
                to_name=route_points[index + 1],
            )
        )
    return segments


def _route_point_name(point: Any) -> str:
    if isinstance(point, dict):
        for key in ("name", "label", "title", "address"):
            value = point.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
    return str(point or "").strip()


def _route_text_items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _classify_route_point(
    name: str,
    *,
    day: dict[str, Any],
    index: int,
    point_count: int,
) -> str:
    text = "\n".join(
        str(item)
        for item in [
            day.get("title"),
            day.get("theme"),
            *_route_text_items(day.get("activities")),
            *_route_text_items(day.get("time_blocks")),
            *_route_text_items(day.get("meals")),
            day.get("accommodation"),
        ]
        if item
    )
    source = f"{name} {text}"
    if any(token in name for token in ("机场", "车站", "高铁", "火车", "航站", "码头", "返程", "交通")):
        return "transport"
    if any(token in name for token in ("酒店", "民宿", "客栈", "住宿", "入住")):
        return "accommodation"
    if any(token in source for token in ("餐", "小吃", "美食", "菜馆", "咖啡", "茶", "夜宵", "饮品")) and any(
        token in name for token in ("小吃", "餐", "菜", "咖啡", "茶", "夜市", "美食", "文和友")
    ):
        return "food"
    if any(token in name for token in ("商圈", "步行街", "商业", "太古里", "广场", "老街", "街区", "夜市")):
        return "business_district"
    if any(
        token in name
        for token in (
            "博物",
            "景区",
            "公园",
            "书院",
            "寺",
            "山",
            "湖",
            "岛",
            "园",
            "阁",
            "故宫",
            "城墙",
            "中山陵",
            "外滩",
            "锦里",
            "宽窄巷子",
        )
    ):
        return "attraction"
    if index == 0 or index == point_count - 1:
        return "transport" if any(token in source for token in ("抵达", "返程", "出发")) else "city"
    return "attraction"


def _route_point_description(point_type: str, *, index: int, point_count: int) -> str:
    if point_type == "transport":
        return "出发、抵达或返程衔接点，建议预留交通缓冲。"
    if point_type == "accommodation":
        return "当天落脚区域，适合作为动线起止点。"
    if point_type == "food":
        return "餐饮或小吃节点，可按排队情况灵活替换。"
    if point_type == "business_district":
        return "商业街区节点，适合穿插购物、休息和餐饮。"
    if point_type == "city":
        return "城市级路线节点，用于串联抵达和核心区域。"
    if index == 0:
        return "当天首个体验节点，建议先确认开放时间。"
    if index == point_count - 1:
        return "当天收尾节点，保留返程或回酒店缓冲。"
    return "当天核心体验节点，适合结合停留时长继续细化。"


def build_route_map(
    itinerary: list[dict[str, Any]],
    route_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an optional frontend-friendly cartoon route map payload."""

    days = []
    for index, route in enumerate(route_summaries):
        day = itinerary[index] if index < len(itinerary) else {}
        day_number = route.get("day_number") or day.get("day_number") or index + 1
        raw_points = route.get("route_points") or route.get("points") or []
        names = dedupe_route_points([_route_point_name(point) for point in raw_points])
        typed_points = []
        for point_index, name in enumerate(names):
            point_type = _classify_route_point(
                name,
                day=day,
                index=point_index,
                point_count=len(names),
            )
            typed_points.append(
                {
                    "name": name,
                    "type": point_type,
                    "type_label": ROUTE_POINT_TYPE_LABELS.get(point_type, "路线点"),
                    "description": _route_point_description(
                        point_type,
                        index=point_index,
                        point_count=len(names),
                    ),
                }
            )
        segments = normalize_report_route_segments(
            names,
            day_number=day_number,
            raw_segments=route.get("segments") or _as_dict(day.get("route")).get("segments"),
        )

        days.append(
            {
                "day_number": day_number,
                "title": day.get("title") or day.get("theme") or f"Day {day_number}",
                "summary": route.get("summary") or " → ".join(names),
                "route_note": route.get("route_note") or day.get("route_note") or "",
                "route_points": names,
                "points": typed_points,
                "segments": segments,
            }
        )

    return {
        "version": "route_map.v1",
        "style": "cartoon_daily_route",
        "days": days,
    }


def is_pending_route_point(point: str) -> bool:
    pending_tokens = (
        "\u5f85",
        "\u5f85\u786e\u8ba4",
        "\u5f85\u6838\u9a8c",
        "\u5f85\u7ed3\u5408",
    )
    return any(token in point for token in pending_tokens)


def get_expected_travel_days(requirement: dict[str, Any], fallback: int = 0) -> int:
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


def collect_report_route_candidates(state: dict[str, Any]) -> list[str]:
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

    return dedupe_route_points(candidates, max_items=40)


def route_points_have_specific_visual_node(
    points: list[str],
    *,
    destination: str,
    departure_city: str,
    accommodation_points: list[str] | None = None,
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
        point not in generic_points and not is_pending_route_point(point)
        for point in points
    )


def fallback_report_route_points_for_day(
    day_number: int,
    expected_days: int,
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> list[str]:
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    departure_city = requirement.get("departure_city") or ""
    selected_accommodation = state.get("selected_accommodation_option") or {}
    accommodation = selected_accommodation.get("location") or selected_accommodation.get("name")
    if not accommodation or is_pending_route_point(str(accommodation)):
        accommodation = services.recommended_accommodation_area(str(destination))

    destination_pois = services.destination_pois_for_report(state, requirement)
    day_pois = services.pick_report_pois_for_day(destination_pois, day_number, expected_days)
    day_poi_names = services.poi_names(day_pois)

    if day_number == 1:
        points = [departure_city, destination, accommodation, *day_poi_names[:1]]
    elif day_number == expected_days:
        points = [accommodation, *day_poi_names[:1], "返程交通"]
    else:
        points = [accommodation, *day_poi_names]
    return dedupe_route_points([str(point) for point in points if point])


def format_report_route_points(
    day: dict[str, Any],
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> list[str]:
    day_number = day.get("day_number") or 0
    destination = state.get("selected_destination") or requirement.get("destination") or ""
    departure_city = requirement.get("departure_city") or ""
    expected_days = get_expected_travel_days(requirement, 0)
    selected_accommodation = state.get("selected_accommodation_option") or {}
    accommodation_candidates = [
        day.get("accommodation"),
        selected_accommodation.get("location"),
        selected_accommodation.get("name"),
    ]
    explicit_points = day.get("route_points")
    if isinstance(explicit_points, list) and explicit_points:
        explicit = dedupe_route_points([str(point) for point in explicit_points])
        explicit_visual_points = [
            point for point in explicit if not is_pending_route_point(point)
        ]
        if len(explicit_visual_points) >= 2 and route_points_have_specific_visual_node(
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

    points = [point for point in explicit if not is_pending_route_point(point)]
    if day_number == 1 and departure_city:
        points.append(str(departure_city))
    if day_number == 1 and destination:
        points.append(str(destination))

    matches = []
    for candidate in collect_report_route_candidates(state):
        if candidate and candidate in text:
            matches.append((text.index(candidate), candidate))
    points.extend(candidate for _, candidate in sorted(matches, key=lambda item: item[0]))

    if accommodation and not is_pending_route_point(str(accommodation)):
        points.append(str(accommodation))
    if day_number == expected_days:
        points.append("\u8fd4\u7a0b\u4ea4\u901a")
    if len(dedupe_route_points(points)) < 2 or not route_points_have_specific_visual_node(
        dedupe_route_points(points),
        destination=str(destination),
        departure_city=str(departure_city),
        accommodation_points=[str(point) for point in accommodation_candidates if point],
    ):
        points.extend(
            fallback_report_route_points_for_day(
                int(day_number or 0),
                expected_days,
                state,
                requirement,
                services,
            )
        )
    if len(dedupe_route_points(points)) < 2 and destination:
        points.append(str(destination))
    if len(dedupe_route_points(points)) < 2 and day_number == expected_days:
        points.append("\u8fd4\u7a0b\u7f13\u51b2")

    return dedupe_route_points(points)


def build_placeholder_itinerary_day(
    day_number: int,
    expected_days: int,
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> dict[str, Any]:
    destination = state.get("selected_destination") or requirement.get("destination") or "目的地"
    selected_accommodation = state.get("selected_accommodation_option") or {}
    if not selected_accommodation.get("name"):
        selected_accommodation = services.build_fallback_accommodation_option(state, requirement)
    accommodation = selected_accommodation.get("name") or f"{destination}交通便利区域住宿"
    destination_context = services.get_destination_context(state, destination)
    destination_pois = services.destination_pois_for_report(state, requirement)
    day_pois = services.pick_report_pois_for_day(destination_pois, day_number, expected_days)
    day_poi_names = services.poi_names(day_pois)
    primary_poi = day_poi_names[0] if day_poi_names else f"{destination}核心街区"
    lunch_food = services.pick_food_poi(
        services.get_food_pois(state),
        day_number * 2 - 2,
        target_area=day_pois[0].get("area") if day_pois else None,
        meal_keyword="午餐",
    )
    dinner_food = services.pick_food_poi(
        services.get_food_pois(state),
        day_number * 2 - 1,
        target_area=day_pois[-1].get("area") if day_pois else None,
        meal_keyword="晚餐",
        exclude_names={str(lunch_food["name"])} if lunch_food and lunch_food.get("name") else None,
    )
    plan_b = services.format_weather_plan_b(destination_context.get("weather_info"))

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
            services.format_poi_activity(day_pois, f"{destination}住宿周边轻松活动"),
        ]
        route_note = "动线原则：抵达日只安排住宿区域和一个低强度夜间/傍晚体验，避免刚到就跨区奔波。"
        route_points = dedupe_route_points(
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
            services.format_poi_activity(day_pois, f"{destination}低强度补漏体验"),
            "退房/寄存/取行李",
            "返程交通缓冲",
        ]
        route_note = "动线原则：返程日优先保证稳定，只保留一个顺路体验和充分交通缓冲。"
        route_points = dedupe_route_points([accommodation, *day_poi_names, "返程交通"])
    else:
        theme = " + ".join(day_poi_names) if day_poi_names else f"{destination}顺路体验"
        time_blocks = [
            f"上午/核心体验：{services.format_poi_activity(day_pois[:1], f'{destination}核心景点或街区')}",
            f"下午/顺路延展：{services.format_poi_activity(day_pois[1:], '同区域景点、商圈或室内场馆')}，减少折返。",
            "晚上/餐饮放松：结合已确认餐饮偏好就近用餐，保留休息时间。",
        ]
        activities = [
            *services.poi_names(day_pois),
            "就近餐饮与休息",
        ]
        route_note = "动线原则：当天围绕同一区域或相邻街区展开，优先减少折返、保留休息。"
        route_points = dedupe_route_points([accommodation, *day_poi_names])

    reservation_note = services.format_reservation_note(day_pois)
    if reservation_note:
        time_blocks.append(f"预约/费用提醒：{reservation_note}")
    indoor_backup = services.format_indoor_backup(day_pois)
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
            f"午餐：{services.format_food_poi_summary(lunch_food, '结合当日动线就近安排')}",
            f"晚餐：{services.format_food_poi_summary(dinner_food, '优先匹配已确认餐饮偏好')}",
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


def build_day_route_summary(
    day: dict[str, Any],
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> dict[str, Any]:
    day_number = day.get("day_number", 0)
    route_points = format_report_route_points(day, state, requirement, services)
    theme = day.get("theme") or "当天安排"
    if route_points:
        summary = " → ".join(route_points)
        if len(route_points) == 1 and theme not in summary:
            summary = f"{summary}｜{theme}"
    else:
        summary = theme
    raw_segments = day.get("segments")
    day_route = day.get("route") if isinstance(day.get("route"), dict) else {}
    if not isinstance(raw_segments, list):
        raw_segments = day_route.get("segments")
    return {
        "day_number": day_number,
        "route_points": route_points,
        "summary": summary,
        "map_label": f"Day {day_number}：{summary}",
        "route_note": day.get("route_note") or day.get("transport_note") or "",
        "segments": normalize_report_route_segments(
            route_points,
            day_number=int(day_number or 0),
            raw_segments=raw_segments,
        ),
    }


def enrich_itinerary_day_for_report(
    day: dict[str, Any],
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> dict[str, Any]:
    enriched = dict(day)
    route_summary = build_day_route_summary(enriched, state, requirement, services)
    enriched["route_points"] = route_summary["route_points"]
    enriched["route_summary"] = route_summary["summary"]
    enriched["map_route"] = route_summary["map_label"]
    return enriched


def ensure_itinerary_day_count(
    itinerary: list[dict[str, Any]],
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> list[dict[str, Any]]:
    source_days = [dict(day) for day in itinerary or [] if isinstance(day, dict)]
    expected_days = get_expected_travel_days(requirement, len(source_days))
    if expected_days <= 0:
        return [
            enrich_itinerary_day_for_report(day, state, requirement, services)
            for day in source_days
        ]

    by_day: dict[int, dict[str, Any]] = {}
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
        day = by_day.get(day_number) or build_placeholder_itinerary_day(
            day_number,
            expected_days,
            state,
            requirement,
            services,
        )
        day["day_number"] = day_number
        normalized.append(enrich_itinerary_day_for_report(day, state, requirement, services))
    return normalized


def build_route_summaries(
    itinerary: list[dict[str, Any]],
    state: dict[str, Any],
    requirement: dict[str, Any],
    services: RouteBuilderServices,
) -> list[dict[str, Any]]:
    return [
        build_day_route_summary(day, state, requirement, services)
        for day in itinerary
    ]


def _coerce_route_summary_points(
    raw_points: Any,
    day: dict[str, Any],
    day_number: int,
) -> list[str]:
    source_points = raw_points if isinstance(raw_points, list) else []
    points = dedupe_route_points([_route_point_name(point) for point in source_points])
    if not points:
        title = day.get("title") or day.get("theme") or f"Day {day_number}"
        activities = [str(item) for item in (day.get("activities") or [])[:1] if str(item).strip()]
        points = dedupe_route_points([str(title), *activities, "待核验路线"])
    if len(points) < 2:
        title = str(day.get("title") or day.get("theme") or f"Day {day_number} 衔接点")
        points = dedupe_route_points([*points, title, "待核验路线"])
    if len(points) < 2:
        points.append(f"Day {day_number} 待核验路线")
    return points


def _route_summary_from_day(day: dict[str, Any], fallback_day_number: int) -> dict[str, Any]:
    day_number = day.get("day_number") or fallback_day_number
    existing_route = day.get("route")
    if isinstance(existing_route, dict) and existing_route.get("summary"):
        route = dict(existing_route)
        route.setdefault("day_number", day_number)
        route_points = _coerce_route_summary_points(
            route.get("route_points") or route.get("points"),
            day,
            int(day_number or fallback_day_number or 0),
        )
        route["route_points"] = route_points
        route.setdefault("map_label", f"Day {day_number}：{route['summary']}")
        route.setdefault("route_note", day.get("route_note") or day.get("transport_note") or "")
        route["segments"] = normalize_report_route_segments(
            route_points,
            day_number=int(day_number or 0),
            raw_segments=route.get("segments") or day.get("segments"),
        )
        return route

    points = _coerce_route_summary_points(
        day.get("route_points"),
        day,
        int(day_number or fallback_day_number or 0),
    )

    summary = " → ".join(points)
    return {
        "day_number": day_number,
        "route_points": points,
        "summary": summary,
        "map_label": f"Day {day_number}：{summary}",
        "route_note": day.get("route_note") or day.get("transport_note") or "",
        "segments": normalize_report_route_segments(
            points,
            day_number=int(day_number or 0),
            raw_segments=day.get("segments"),
        ),
    }


def _placeholder_day_from_route(route: dict[str, Any], fallback_day_number: int) -> dict[str, Any]:
    day_number = route.get("day_number") or fallback_day_number
    summary = route.get("summary") or "待核验路线"
    return {
        "day_number": day_number,
        "theme": f"路线补齐 Day {day_number}",
        "title": f"路线补齐 Day {day_number}",
        "route": route,
        "route_points": list(route.get("route_points") or []),
        "time_blocks": [f"该日地图路线已存在，行程明细待补充：{summary}。"],
        "activities": [summary],
        "meals": [],
        "plan_b": "出发前补齐该日具体行程和 Plan B。",
        "risk_notes": ["该日由地图路线补齐生成，需人工复核行程内容。"],
    }


def normalize_report_route_alignment(
    itinerary: list[dict[str, Any]],
    route_summaries: list[dict[str, Any]],
) -> RouteAlignmentResult:
    """Ensure report itinerary and map routes have matching lengths without truncation."""

    normalized_days = [dict(day) for day in itinerary or [] if isinstance(day, dict)]
    normalized_routes = [dict(route) for route in route_summaries or [] if isinstance(route, dict)]
    findings: list[str] = []

    if len(normalized_days) > len(normalized_routes):
        for index in range(len(normalized_routes), len(normalized_days)):
            day = normalized_days[index]
            normalized_routes.append(_route_summary_from_day(day, index + 1))
            findings.append(f"Day {day.get('day_number') or index + 1} 缺少地图路线，已按行程内容补齐。")
    elif len(normalized_routes) > len(normalized_days):
        for index in range(len(normalized_days), len(normalized_routes)):
            route = normalized_routes[index]
            normalized_days.append(_placeholder_day_from_route(route, index + 1))
            findings.append(f"地图路线 Day {route.get('day_number') or index + 1} 缺少每日行程，已生成待核验行程占位。")

    for index, day in enumerate(normalized_days):
        if index >= len(normalized_routes):
            break
        route = dict(normalized_routes[index])
        day_number = day.get("day_number") or route.get("day_number") or index + 1
        route.setdefault("day_number", day_number)
        route.setdefault(
            "summary",
            " → ".join(_coerce_route_summary_points(route.get("route_points"), day, int(day_number or 0)))
            or f"Day {day_number} 路线待核验",
        )
        route = _route_summary_from_day({**day, "route": route}, index + 1)
        normalized_routes[index] = route
        day["route"] = route

    return RouteAlignmentResult(
        itinerary=normalized_days,
        route_summaries=normalized_routes,
        findings=findings,
    )


def normalize_report_route_contract_surfaces(report_data: dict[str, Any]) -> dict[str, Any]:
    """Return report_data with itinerary, map routes, and route_map sharing one route contract."""

    normalized = dict(report_data)
    itinerary = [
        dict(day)
        for day in normalized.get("itinerary") or []
        if isinstance(day, dict)
    ]
    map_routes = [
        dict(route)
        for route in normalized.get("map_routes") or []
        if isinstance(route, dict)
    ]
    if not itinerary and not map_routes:
        return normalized

    route_alignment = normalize_report_route_alignment(itinerary, map_routes)
    itinerary = route_alignment.itinerary
    map_routes = route_alignment.route_summaries

    for index, day in enumerate(itinerary):
        if index >= len(map_routes):
            break
        day["route"] = map_routes[index]

    normalized["itinerary"] = itinerary
    normalized["map_routes"] = map_routes
    normalized["route_map"] = build_route_map(itinerary, map_routes)
    return normalized
