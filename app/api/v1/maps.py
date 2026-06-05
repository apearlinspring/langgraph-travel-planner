"""
Map preview APIs for frontend route visualization.
"""
from __future__ import annotations

import json
import asyncio
import math
import re
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.config import settings
from app.journey.route_preferences import (
    normalize_route_segment_mode,
    route_segment_mode_label,
)
from app.mcp_core.client import get_mcp_client
from app.models.user import User
from app.utils.logger import app_logger

router = APIRouter(prefix="/maps", tags=["地图预览"])


class MapPreviewStopRequest(BaseModel):
    id: str | None = None
    name: str
    city: str | None = None
    type: str | None = None
    time_range: str | None = None
    estimated_cost: str | None = None
    lng: float | None = None
    lat: float | None = None


class MapPreviewSegmentRequest(BaseModel):
    id: str | None = None
    day_number: int | None = None
    from_poi_id: str | None = None
    to_poi_id: str | None = None
    from_name: str | None = None
    to_name: str | None = None
    mode: str | None = None
    selected_mode: str | None = None
    recommended_mode: str | None = None
    transport_mode: str | None = None
    locked_by_user: bool = False
    mode_locked: bool = False
    distance_text: str | None = None
    duration_text: str | None = None
    confidence: str | None = None
    source: str | None = None
    verification_status: str | None = None
    verification_note: str | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class MapPreviewDayRequest(BaseModel):
    key: str | None = None
    label: str
    waypoints: list[str] = Field(default_factory=list)
    stops: list[MapPreviewStopRequest] = Field(default_factory=list)
    segments: list[MapPreviewSegmentRequest] = Field(default_factory=list)


class MapPreviewRequest(BaseModel):
    origin: str | None = None
    destination: str | None = None
    stay: str | None = None
    highlights: list[str] = Field(default_factory=list)
    recommendations: list[MapPreviewStopRequest] = Field(default_factory=list)
    days: list[MapPreviewDayRequest] = Field(default_factory=list)


class MapPoint(BaseModel):
    kind: str
    label: str
    name: str
    lng: float
    lat: float
    address: str


class MapRouteSegment(BaseModel):
    day_key: str
    day_label: str
    from_name: str
    to_name: str
    mode: str = "taxi"
    selected_mode: str = "taxi"
    recommended_mode: str = "taxi"
    mode_label: str = "打车"
    locked_by_user: bool = False
    distance_text: str
    duration_text: str
    distance_meters: float | None = None
    duration_seconds: float | None = None
    confidence: str = "needs_live_route"
    source: str = ""
    verification_status: str = "needs_live_route"
    verification_label: str = "待高德路线核验"
    verification_note: str = ""
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    path: list[dict[str, float]] = Field(default_factory=list)


class MapPreviewDay(BaseModel):
    key: str
    label: str
    points: list[MapPoint] = Field(default_factory=list)
    segments: list[MapRouteSegment] = Field(default_factory=list)


class MapPreviewResponse(BaseModel):
    provider: str = "leaflet-osm"
    geocoder: str = "amap-mcp"
    status: str = "success"
    message: str = ""
    elapsed_seconds: float | None = None
    center: dict[str, float] | None = None
    points: list[MapPoint] = Field(default_factory=list)
    days: list[MapPreviewDay] = Field(default_factory=list)
    segments: list[MapRouteSegment] = Field(default_factory=list)


PREVIEW_CACHE_TTL_SECONDS = 60 * 10
GEOCODE_CACHE_TTL_SECONDS = 60 * 60 * 12
GEOCODE_FAILURE_TTL_SECONDS = 60 * 15
MAP_TOOL_LOAD_TIMEOUT_SECONDS = 3.0
MAP_GEOCODE_TIMEOUT_SECONDS = 2.5
MAP_DIRECTION_TIMEOUT_SECONDS = 2.5
MAP_PREVIEW_OVERALL_TIMEOUT_SECONDS = 10.5

_preview_cache: dict[str, tuple[float, MapPreviewResponse]] = {}
_geocode_cache: dict[str, tuple[float, MapPoint | None]] = {}


def _map_preview_deadline_expired(deadline: float | None) -> bool:
    return bool(deadline and time.perf_counter() >= deadline)


def _extract_text_payload(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text", ""))
    if isinstance(result, dict) and result.get("type") == "text":
        return str(result.get("text", ""))
    return str(result)


def _parse_json_text(result: Any) -> dict[str, Any]:
    text = _extract_text_payload(result)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _normalize_query(text: str | None) -> str:
    if not text:
        return ""
    compact = " ".join(str(text).replace("\n", " ").split()).strip()
    compact = re.sub(
        r"^(需求很完整|信息基本齐了|现在先把|我先帮你梳理确认一下|我已经按你的要求查到)\s*[!！:：,-]*\s*",
        "",
        compact,
    )
    for token in ["待确认", "待继续", "交通待定", "住宿待补充"]:
        compact = compact.replace(token, "")
    compact = re.sub(r"^[!！:：\-—\s]+", "", compact)
    compact = compact.strip("，。；、：:,. ")
    return compact[:40]


def _build_day_key(label: str, index: int) -> str:
    ascii_key = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    if ascii_key:
        return ascii_key
    return f"day-{index + 1}"


async def _get_amap_tool(name: str):
    manager = await asyncio.wait_for(
        get_mcp_client(servers=["amap"]),
        timeout=MAP_TOOL_LOAD_TIMEOUT_SECONDS,
    )
    tools = await asyncio.wait_for(
        manager.get_tools(servers=["amap"]),
        timeout=MAP_TOOL_LOAD_TIMEOUT_SECONDS,
    )
    for tool_item in tools:
        if tool_item.name == name:
            return tool_item
    raise RuntimeError(f"AMap tool not available: {name}")


async def _get_optional_amap_tool(name: str):
    try:
        return await _get_amap_tool(name)
    except Exception as exc:
        app_logger.info(f"Optional AMap tool unavailable: {name}, reason={exc}")
        return None


def _make_geocode_cache_key(address: str, city: str | None = None) -> str:
    normalized_address = _normalize_query(address)
    normalized_city = _normalize_query(city)
    return f"{normalized_city}::{normalized_address}".strip(":")


def _clone_map_point(value: MapPoint | None) -> MapPoint | None:
    return value.model_copy(deep=True) if value else None


def _point_from_stop_coordinates(
    stop: MapPreviewStopRequest,
    *,
    label: str,
    kind: str = "day",
) -> MapPoint | None:
    if stop.lng is None or stop.lat is None:
        return None
    if not (-180 <= stop.lng <= 180 and -90 <= stop.lat <= 90):
        return None
    name = _normalize_query(stop.name)
    if not name:
        return None
    return MapPoint(
        kind=kind,
        label=label,
        name=name,
        lng=stop.lng,
        lat=stop.lat,
        address=_normalize_query(stop.city) or name,
    )


def _fallback_points_from_day_groups(
    day_groups: list[MapPreviewDay],
    *,
    max_items: int = 12,
) -> list[MapPoint]:
    """Use real day POI coordinates as map anchors when overview points are absent."""

    picked: list[MapPoint] = []
    seen: set[str] = set()
    for day in day_groups:
        for point in day.points:
            dedupe_key = f"{point.lat:.5f},{point.lng:.5f}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            picked.append(point.model_copy(update={"kind": "day", "label": day.label}))
            if len(picked) >= max_items:
                return picked
    return picked


def _get_cached_geocode(address: str, city: str | None = None) -> MapPoint | None | Ellipsis:
    cache_key = _make_geocode_cache_key(address, city)
    if not cache_key:
        return None
    cached = _geocode_cache.get(cache_key)
    if not cached:
        return ...
    expires_at, point = cached
    if expires_at <= time.time():
        _geocode_cache.pop(cache_key, None)
        return ...
    return _clone_map_point(point)


def _set_cached_geocode(
    address: str,
    city: str | None,
    point: MapPoint | None,
    *,
    success: bool,
) -> None:
    cache_key = _make_geocode_cache_key(address, city)
    if not cache_key:
        return
    ttl = GEOCODE_CACHE_TTL_SECONDS if success else GEOCODE_FAILURE_TTL_SECONDS
    _geocode_cache[cache_key] = (
        time.time() + ttl,
        _clone_map_point(point),
    )


async def _resolve_point(
    tool: Any,
    *,
    address: str,
    label: str,
    kind: str,
    city: str | None = None,
) -> MapPoint | None:
    if tool is None:
        return None

    normalized = _normalize_query(address)
    if not normalized:
        return None

    cached = _get_cached_geocode(normalized, city)
    if cached is not ...:
        return cached

    payload: dict[str, str] = {"address": normalized}
    if city:
        payload["city"] = city

    try:
        result = await asyncio.wait_for(
            tool.ainvoke(payload),
            timeout=MAP_GEOCODE_TIMEOUT_SECONDS,
        )
        data = _parse_json_text(result)
        candidates = data.get("results") or []
        if not candidates:
            return None
        first = candidates[0]
        location = str(first.get("location") or "")
        if "," not in location:
            return None
        lng_text, lat_text = location.split(",", 1)
        point = MapPoint(
            kind=kind,
            label=label,
            name=normalized,
            lng=float(lng_text),
            lat=float(lat_text),
            address=str(first.get("formatted_address") or normalized),
        )
        _set_cached_geocode(normalized, city, point, success=True)
        return point
    except Exception as exc:
        app_logger.warning(f"Map preview geocode failed for {normalized}: {exc}")
        _set_cached_geocode(normalized, city, None, success=False)
        return None


def _format_distance(distance_meters: float) -> str:
    if distance_meters >= 1000:
        return f"{distance_meters / 1000:.1f} 公里"
    return f"{distance_meters:.0f} 米"


def _format_duration(duration_seconds: float) -> str:
    total_minutes = max(int(round(duration_seconds / 60)), 1)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}小时{minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{minutes}分钟"


def _verification_label(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "verified":
        return "已核验"
    if normalized == "estimated":
        return "估算"
    return "待高德路线核验"


def _segment_selected_mode(preference: MapPreviewSegmentRequest | None) -> str:
    if not preference:
        return "taxi"
    return normalize_route_segment_mode(
        preference.selected_mode
        or preference.mode
        or preference.transport_mode
        or ""
    )


def _segment_recommended_mode(
    preference: MapPreviewSegmentRequest | None,
    selected_mode: str,
) -> str:
    if not preference:
        return selected_mode
    return normalize_route_segment_mode(preference.recommended_mode or selected_mode)


def _segment_locked_by_user(preference: MapPreviewSegmentRequest | None) -> bool:
    return bool(
        preference
        and (preference.locked_by_user or preference.mode_locked)
    )


def _segment_alternatives(
    preference: MapPreviewSegmentRequest | None,
) -> list[dict[str, Any]]:
    if not preference:
        return []
    alternatives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in preference.alternatives[:4]:
        if not isinstance(option, dict):
            continue
        mode = normalize_route_segment_mode(
            option.get("mode") or option.get("transport_mode") or ""
        )
        if not mode or mode in seen:
            continue
        seen.add(mode)
        alternatives.append(
            {
                "mode": mode,
                "label": str(option.get("label") or route_segment_mode_label(mode)),
                "duration_text": str(
                    option.get("duration_text") or option.get("duration") or "时间待核验"
                ),
                "cost_text": str(option.get("cost_text") or option.get("cost") or "费用待核验"),
                "reason": str(option.get("reason") or option.get("note") or "适配性待核验"),
            }
        )
    return alternatives


def _segment_contract_fields(
    preference: MapPreviewSegmentRequest | None,
    *,
    source: str,
    confidence: str,
    verification_status: str,
    verification_note: str,
) -> dict[str, Any]:
    selected_mode = _segment_selected_mode(preference)
    recommended_mode = _segment_recommended_mode(preference, selected_mode)
    return {
        "mode": selected_mode,
        "selected_mode": selected_mode,
        "recommended_mode": recommended_mode,
        "mode_label": route_segment_mode_label(selected_mode),
        "locked_by_user": _segment_locked_by_user(preference),
        "confidence": confidence,
        "source": source,
        "verification_status": verification_status,
        "verification_label": _verification_label(verification_status),
        "verification_note": verification_note,
        "alternatives": _segment_alternatives(preference),
    }


def _haversine_distance_meters(left: MapPoint, right: MapPoint) -> float:
    radius = 6371000
    lat1 = math.radians(left.lat)
    lat2 = math.radians(right.lat)
    d_lat = math.radians(right.lat - left.lat)
    d_lng = math.radians(right.lng - left.lng)
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _decode_amap_polyline(value: str | None) -> list[dict[str, float]]:
    if not value:
        return []
    points: list[dict[str, float]] = []
    for item in str(value).split(";"):
        if "," not in item:
            continue
        lng_text, lat_text = item.split(",", 1)
        try:
            lng = float(lng_text)
            lat = float(lat_text)
        except ValueError:
            continue
        if -180 <= lng <= 180 and -90 <= lat <= 90:
            points.append({"lng": lng, "lat": lat})
    return points


def _extract_amap_route_path(path: dict[str, Any]) -> list[dict[str, float]]:
    route_path: list[dict[str, float]] = []
    for step in path.get("steps") or []:
        step_path = _decode_amap_polyline(step.get("polyline"))
        if not step_path:
            continue
        if route_path and step_path:
            previous = route_path[-1]
            first = step_path[0]
            if (
                abs(previous["lng"] - first["lng"]) < 0.000001
                and abs(previous["lat"] - first["lat"]) < 0.000001
            ):
                step_path = step_path[1:]
        route_path.extend(step_path)
    if not route_path:
        route_path = _decode_amap_polyline(path.get("polyline"))
    return route_path


async def _resolve_segment(
    direction_tool: Any | None,
    *,
    day_key: str,
    day_label: str,
    left: MapPoint,
    right: MapPoint,
    preference: MapPreviewSegmentRequest | None = None,
) -> MapRouteSegment:
    selected_mode = _segment_selected_mode(preference)
    direct_path = [{"lng": left.lng, "lat": left.lat}, {"lng": right.lng, "lat": right.lat}]
    if selected_mode not in {"taxi"}:
        return MapRouteSegment(
            day_key=day_key,
            day_label=day_label,
            from_name=left.name,
            to_name=right.name,
            distance_text="待高德路线核验",
            duration_text="待高德路线核验",
            distance_meters=_haversine_distance_meters(left, right),
            duration_seconds=None,
            path=direct_path,
            **_segment_contract_fields(
                preference,
                source="route_mode_pending_amap_tool",
                confidence="needs_live_route",
                verification_status="needs_live_route",
                verification_note=(
                    f"已收到{route_segment_mode_label(selected_mode)}偏好，"
                    "真实路线、用时和换乘细节待高德对应路线工具核验。"
                ),
            ),
        )

    if direction_tool is not None:
        try:
            result = await asyncio.wait_for(
                direction_tool.ainvoke(
                    {
                        "origin": f"{left.lng},{left.lat}",
                        "destination": f"{right.lng},{right.lat}",
                    }
                ),
                timeout=MAP_DIRECTION_TIMEOUT_SECONDS,
            )
            data = _parse_json_text(result)
            paths = data.get("paths") or []
            if paths:
                path = paths[0]
                distance = float(path.get("distance") or 0)
                duration = float(path.get("duration") or 0)
                if distance > 0 and duration > 0:
                    return MapRouteSegment(
                        day_key=day_key,
                        day_label=day_label,
                        from_name=left.name,
                        to_name=right.name,
                        distance_text=_format_distance(distance),
                        duration_text=_format_duration(duration),
                        distance_meters=distance,
                        duration_seconds=duration,
                        path=_extract_amap_route_path(path),
                        **_segment_contract_fields(
                            preference,
                            source="amap_direction_driving",
                            confidence="amap_driving",
                            verification_status="verified",
                            verification_note="已用高德驾车路线核验距离和用时；票价、路况和叫车费用仍需行前确认。",
                        ),
                    )
        except Exception as exc:
            app_logger.warning(
                "Map preview direction failed: "
                f"{left.name}->{right.name}: {exc}"
            )

    distance = _haversine_distance_meters(left, right)
    duration = distance / 1000 / 25 * 3600
    return MapRouteSegment(
        day_key=day_key,
        day_label=day_label,
        from_name=left.name,
        to_name=right.name,
        distance_text=f"约 {_format_distance(distance)}",
        duration_text=f"约 {_format_duration(duration)}",
        distance_meters=distance,
        duration_seconds=duration,
        path=direct_path,
        **_segment_contract_fields(
            preference,
            source="estimated_straight_line",
            confidence="estimated_straight_line",
            verification_status="estimated",
            verification_note="高德驾车路线暂不可用，已按点位直线距离给出估算，真实路线待二次核验。",
        ),
    )


@router.get("/config")
async def get_map_config(user: User = Depends(get_current_user)):
    """Return frontend map runtime configuration without backend API secrets."""

    web_key = settings.amap_web_js_key.strip()
    return {
        "preferred_provider": "amap-js" if web_key else "leaflet-osm",
        "amap_web_js_key": web_key,
        "amap_web_js_key_configured": bool(web_key),
        "fallback_provider": "leaflet-osm",
    }


@router.post("/preview", response_model=MapPreviewResponse)
async def get_map_preview(
    data: MapPreviewRequest,
    user: User = Depends(get_current_user),
):
    """Resolve frontend route-preview places into coordinates and day segments."""

    started_at = time.perf_counter()
    deadline = started_at + MAP_PREVIEW_OVERALL_TIMEOUT_SECONDS
    cache_key = json.dumps(
        {
            "origin": data.origin,
            "destination": data.destination,
            "stay": data.stay,
            "highlights": data.highlights[:4],
            "recommendations": [
                {
                    "id": stop.id,
                    "name": stop.name,
                    "city": stop.city,
                    "type": stop.type,
                    "lng": stop.lng,
                    "lat": stop.lat,
                }
                for stop in data.recommendations[:8]
            ],
            "days": [
                {
                    "label": day.label,
                    "key": day.key,
                    "waypoints": day.waypoints[:8],
                    "stops": [
                        {
                            "id": stop.id,
                            "name": stop.name,
                            "city": stop.city,
                            "type": stop.type,
                            "time_range": stop.time_range,
                            "estimated_cost": stop.estimated_cost,
                            "lng": stop.lng,
                            "lat": stop.lat,
                        }
                        for stop in day.stops[:8]
                    ],
                    "segments": [
                        {
                            "id": segment.id,
                            "from_poi_id": segment.from_poi_id,
                            "to_poi_id": segment.to_poi_id,
                            "from_name": segment.from_name,
                            "to_name": segment.to_name,
                            "mode": segment.mode,
                            "selected_mode": segment.selected_mode,
                            "recommended_mode": segment.recommended_mode,
                            "transport_mode": segment.transport_mode,
                            "locked_by_user": segment.locked_by_user,
                            "mode_locked": segment.mode_locked,
                            "confidence": segment.confidence,
                            "source": segment.source,
                            "verification_status": segment.verification_status,
                            "alternatives": segment.alternatives[:4],
                        }
                        for segment in day.segments[:8]
                    ],
                }
                for day in data.days[:7]
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached_preview = _preview_cache.get(cache_key)
    if cached_preview and cached_preview[0] > time.time():
        cached = MapPreviewResponse.model_validate(cached_preview[1].model_dump())
        cached.elapsed_seconds = round(time.perf_counter() - started_at, 3)
        return cached

    geo_tool = None
    direction_tool = None
    geocoder_unavailable = False
    try:
        geo_tool = await _get_amap_tool("maps_geo")
    except Exception as exc:
        elapsed = round(time.perf_counter() - started_at, 3)
        geocoder_unavailable = True
        app_logger.warning(
            "Map preview unavailable before geocoding: "
            f"user_id={user.id}, elapsed_seconds={elapsed:.3f}, error={exc}"
        )
    if geo_tool is not None:
        direction_tool = await _get_optional_amap_tool("maps_direction_driving")
    destination_hint = _normalize_query(data.destination)

    ordered_queries = [
        ("origin", "出发", data.origin, data.origin),
        ("destination", "目的地", data.destination, data.destination),
        (
            "stay",
            "落脚点",
            f"{destination_hint} {data.stay}" if destination_hint and data.stay else data.stay,
            destination_hint or data.destination,
        ),
    ]

    points: list[MapPoint] = []
    for kind, label, query, city in ordered_queries:
        if _map_preview_deadline_expired(deadline):
            break
        point = await _resolve_point(
            geo_tool,
            address=query or "",
            label=label,
            kind=kind,
            city=_normalize_query(city),
        )
        if point:
            points.append(point)

    for highlight in data.highlights[:4]:
        if _map_preview_deadline_expired(deadline):
            break
        query = f"{destination_hint} {highlight}" if destination_hint else highlight
        point = await _resolve_point(
            geo_tool,
            address=query,
            label="看点",
            kind="highlight",
            city=destination_hint,
        )
        if point:
            points.append(point)

    for recommendation in data.recommendations[:8]:
        if _map_preview_deadline_expired(deadline):
            break
        normalized_name = _normalize_query(recommendation.name)
        if not normalized_name:
            continue
        city_hint = _normalize_query(recommendation.city) or destination_hint
        point = _point_from_stop_coordinates(
            recommendation,
            label="推荐点",
            kind="recommendation",
        )
        if point is None:
            query = (
                recommendation.name
                if city_hint and city_hint in recommendation.name
                else f"{city_hint} {recommendation.name}".strip()
            )
            point = await _resolve_point(
                geo_tool,
                address=query,
                label="推荐点",
                kind="recommendation",
                city=city_hint,
            )
        if point:
            points.append(
                point.model_copy(
                    update={
                        "kind": "recommendation",
                        "label": "推荐点",
                        "name": normalized_name,
                        "address": city_hint or point.address or normalized_name,
                    }
                )
            )

    day_groups: list[MapPreviewDay] = []
    all_segments: list[MapRouteSegment] = []
    for index, day in enumerate(data.days[:7]):
        seen_names: set[str] = set()
        day_points: list[MapPoint] = []
        day_label = _normalize_query(day.label) or f"Day {index + 1}"
        day_key = day.key or _build_day_key(day.label, index)
        if _map_preview_deadline_expired(deadline):
            day_groups.append(
                MapPreviewDay(
                    key=day_key,
                    label=day_label,
                    points=[],
                    segments=[],
                )
            )
            continue
        stop_items = [stop for stop in day.stops[:8] if _normalize_query(stop.name)]
        if stop_items:
            waypoint_items: list[MapPreviewStopRequest | str] = stop_items
        else:
            waypoint_items = day.waypoints[:8]
        for waypoint_item in waypoint_items[:8]:
            if _map_preview_deadline_expired(deadline):
                break
            if isinstance(waypoint_item, MapPreviewStopRequest):
                normalized_waypoint = _normalize_query(waypoint_item.name)
                point = _point_from_stop_coordinates(
                    waypoint_item,
                    label=day_label,
                    kind="day",
                )
                city_hint = _normalize_query(waypoint_item.city) or destination_hint
            else:
                normalized_waypoint = _normalize_query(waypoint_item)
                point = None
                city_hint = destination_hint
            if not normalized_waypoint:
                continue
            if point is None:
                geocode_address = (
                    f"{city_hint} {normalized_waypoint}".strip()
                    if city_hint and city_hint not in normalized_waypoint
                    else normalized_waypoint
                )
                point = await _resolve_point(
                    geo_tool,
                    address=geocode_address,
                    label=day_label,
                    kind="day",
                    city=city_hint,
                )
            if not point and destination_hint and destination_hint not in normalized_waypoint:
                point = await _resolve_point(
                    geo_tool,
                    address=f"{destination_hint} {normalized_waypoint}".strip(),
                    label=day_label,
                    kind="day",
                    city=destination_hint,
                )
            if not point:
                continue
            point = point.model_copy(
                update={
                    "name": normalized_waypoint,
                    "address": city_hint or point.address or normalized_waypoint,
                }
            )
            dedupe_key = f"{point.lat:.5f},{point.lng:.5f}"
            if dedupe_key in seen_names:
                continue
            seen_names.add(dedupe_key)
            day_points.append(point)
        segments: list[MapRouteSegment] = []
        for point_index in range(max(len(day_points) - 1, 0)):
            if _map_preview_deadline_expired(deadline):
                break
            segment = await _resolve_segment(
                direction_tool,
                day_key=day_key,
                day_label=day_label,
                left=day_points[point_index],
                right=day_points[point_index + 1],
                preference=day.segments[point_index]
                if point_index < len(day.segments)
                else None,
            )
            segments.append(segment)
            all_segments.append(segment)
        day_groups.append(
            MapPreviewDay(
                key=day_key,
                label=day_label,
                points=day_points,
                segments=segments,
            )
        )

    if not points and any(day.points for day in day_groups):
        points = _fallback_points_from_day_groups(day_groups)

    center_source = next(
        (item for item in points if item.kind == "destination"),
        points[0]
        if points
        else (
            day_groups[0].points[0]
            if day_groups and day_groups[0].points
            else None
        ),
    )
    center = (
        {"lng": center_source.lng, "lat": center_source.lat}
        if center_source
        else None
    )

    elapsed = round(time.perf_counter() - started_at, 3)
    timed_out = _map_preview_deadline_expired(deadline)
    app_logger.info(
        "Generated map preview payload: "
        f"user_id={user.id}, points={len(points)}, day_groups={len(day_groups)}, "
        f"segments={len(all_segments)}, destination={destination_hint or 'n/a'}, "
        f"elapsed_seconds={elapsed:.3f}, timed_out={timed_out}"
    )
    empty_result = not points and not any(day.points for day in day_groups)
    response = MapPreviewResponse(
        provider="amap-js" if settings.amap_web_js_key.strip() else "leaflet-osm",
        status="degraded" if (timed_out or empty_result) else "success",
        message=(
            "地图服务响应较慢，已先展示可定位到的地点。"
            if timed_out
            else "地图服务暂时没有响应，已保留文字路线。"
            if empty_result and geocoder_unavailable
            else "暂时没有定位到可展示的路线点，已保留文字路线。"
            if empty_result
            else "地图定位服务响应不稳定，已用已有坐标展示路线。"
            if geocoder_unavailable
            else ""
        ),
        elapsed_seconds=elapsed,
        center=center,
        points=points,
        days=day_groups,
        segments=all_segments,
    )
    if response.points or any(day.points for day in response.days):
        _preview_cache[cache_key] = (
            time.time() + PREVIEW_CACHE_TTL_SECONDS,
            MapPreviewResponse.model_validate(response.model_dump()),
        )
    return response
