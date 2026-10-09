"""Route-segment preference helpers for edited visual journeys."""

from __future__ import annotations

from typing import Any


ROUTE_SEGMENT_MODE_LABELS = {
    "walking": "步行",
    "transit": "公交/地铁",
    "taxi": "打车",
    "rail": "铁路",
    "flight": "航班",
}

ROUTE_SEGMENT_VERIFICATION_LABELS = {
    "verified": "已核验",
    "estimated": "估算",
    "needs_live_route": "待高德路线核验",
}


def format_route_distance(distance_meters: float) -> str:
    if distance_meters >= 1000:
        return f"{distance_meters / 1000:.1f} 公里"
    return f"{distance_meters:.0f} 米"


def format_route_duration(duration_seconds: float) -> str:
    total_minutes = max(int(round(duration_seconds / 60)), 1)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def normalize_route_segment_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if any(token in raw for token in ("walk", "walking", "步行")):
        return "walking"
    if any(token in raw for token in ("bus", "公交", "metro", "subway", "地铁", "transit")):
        return "transit"
    if any(token in raw for token in ("taxi", "ride", "打车", "网约车")):
        return "taxi"
    if any(token in raw for token in ("drive", "driving", "car", "驾车", "自驾")):
        return "taxi"
    if any(token in raw for token in ("train", "rail", "火车", "高铁")):
        return "rail"
    if any(token in raw for token in ("flight", "air", "航班", "飞机")):
        return "flight"
    return raw or "taxi"


def route_segment_mode_label(mode: Any) -> str:
    return ROUTE_SEGMENT_MODE_LABELS.get(normalize_route_segment_mode(mode), "交通")


def route_segment_duration_matches_mode(mode: Any, duration_text: Any) -> bool:
    text = str(duration_text or "").strip().lower()
    if not text:
        return False
    normalized = normalize_route_segment_mode(mode)
    explicit_modes: set[str] = set()
    if any(token in text for token in ("walk", "walking", "步行")):
        explicit_modes.add("walking")
    if any(token in text for token in ("bus", "公交", "metro", "subway", "地铁", "transit")):
        explicit_modes.add("transit")
    if any(token in text for token in ("taxi", "ride", "打车", "网约车", "drive", "driving", "驾车", "自驾")):
        explicit_modes.add("taxi")
    if any(token in text for token in ("train", "rail", "火车", "高铁")):
        explicit_modes.add("rail")
    if any(token in text for token in ("flight", "air", "航班", "飞机")):
        explicit_modes.add("flight")
    return not explicit_modes or normalized in explicit_modes


def extract_route_segment_preferences(
    journey_data: dict[str, Any] | None,
    *,
    max_items: int = 24,
) -> list[dict[str, Any]]:
    """Extract user-touched route-segment choices from a journey_plan.v1 draft."""

    if not isinstance(journey_data, dict) or journey_data.get("version") != "journey_plan.v1":
        return []
    preferences: list[dict[str, Any]] = []
    days = journey_data.get("days") if isinstance(journey_data.get("days"), list) else []
    for day_index, day in enumerate(days, start=1):
        if not isinstance(day, dict):
            continue
        day_number = int(day.get("day_number") or day_index)
        poi_lookup = {
            str(poi.get("id")): poi
            for poi in day.get("pois") or []
            if isinstance(poi, dict) and poi.get("id")
        }
        for segment_index, segment in enumerate(day.get("segments") or [], start=1):
            if not isinstance(segment, dict):
                continue
            selected_mode = normalize_route_segment_mode(
                segment.get("selected_mode")
                or segment.get("mode")
                or segment.get("transport_mode")
                or ""
            )
            recommended_mode = normalize_route_segment_mode(
                segment.get("recommended_mode") or selected_mode
            )
            locked = bool(segment.get("locked_by_user") or segment.get("mode_locked"))
            source_text = " ".join(
                str(segment.get(key) or "")
                for key in ("source", "confidence", "verification_note")
            )
            user_touched = (
                locked
                or "user_segment_mode_preference" in source_text
                or selected_mode != recommended_mode
            )
            if not user_touched:
                continue
            left = poi_lookup.get(str(segment.get("from_poi_id") or "")) or {}
            right = poi_lookup.get(str(segment.get("to_poi_id") or "")) or {}
            duration_text = str(segment.get("duration_text") or "").strip()
            distance_text = str(segment.get("distance_text") or "").strip()
            verification_status = str(
                segment.get("verification_status") or segment.get("confidence") or "needs_live_route"
            )
            preferences.append(
                {
                    "day_number": day_number,
                    "segment_index": segment_index,
                    "from_name": str(segment.get("from_name") or left.get("name") or "上一站"),
                    "to_name": str(segment.get("to_name") or right.get("name") or "下一站"),
                    "selected_mode": selected_mode,
                    "mode_label": route_segment_mode_label(selected_mode),
                    "recommended_mode": recommended_mode,
                    "locked_by_user": locked,
                    "distance_text": distance_text,
                    "duration_text": duration_text,
                    "verification_status": verification_status,
                    "verification_label": _verification_label(verification_status),
                }
            )
            if len(preferences) >= max_items:
                return preferences
    return preferences


def format_route_segment_preferences_summary(
    preferences: list[dict[str, Any]] | None,
    *,
    max_items: int = 8,
) -> str:
    items = [item for item in preferences or [] if isinstance(item, dict)]
    if not items:
        return ""
    lines = ["路段交通偏好："]
    for item in items[:max_items]:
        metric_parts = [
            str(item.get("distance_text") or "").strip(),
            str(item.get("duration_text") or "").strip(),
        ]
        metric = " · ".join(part for part in metric_parts if part)
        status = str(item.get("verification_label") or "待高德路线核验")
        locked = "；已锁定" if item.get("locked_by_user") else ""
        metric_text = f"；{metric}" if metric else ""
        lines.append(
            "- Day {day} {from_name} → {to_name}：{mode}{locked}；{status}{metric}".format(
                day=item.get("day_number") or "?",
                from_name=item.get("from_name") or "上一站",
                to_name=item.get("to_name") or "下一站",
                mode=item.get("mode_label") or route_segment_mode_label(item.get("selected_mode")),
                locked=locked,
                status=status,
                metric=metric_text,
            )
        )
    if len(items) > max_items:
        lines.append(f"- 其余 {len(items) - max_items} 段路段偏好按已保存草案执行。")
    return "\n".join(lines)


def _verification_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "amap" in text or "verified" in text or "已核验" in text:
        return ROUTE_SEGMENT_VERIFICATION_LABELS["verified"]
    if "estimated" in text or "估算" in text:
        return ROUTE_SEGMENT_VERIFICATION_LABELS["estimated"]
    return ROUTE_SEGMENT_VERIFICATION_LABELS["needs_live_route"]
