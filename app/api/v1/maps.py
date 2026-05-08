"""
Map preview APIs for frontend route visualization.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.mcp_core.client import get_mcp_client
from app.models.user import User
from app.utils.logger import app_logger

router = APIRouter(prefix="/maps", tags=["地图预览"])


class MapPreviewRequest(BaseModel):
    origin: str | None = None
    destination: str | None = None
    stay: str | None = None
    highlights: list[str] = Field(default_factory=list)
    days: list["MapPreviewDayRequest"] = Field(default_factory=list)


class MapPreviewDayRequest(BaseModel):
    label: str
    waypoints: list[str] = Field(default_factory=list)


class MapPoint(BaseModel):
    kind: str
    label: str
    name: str
    lng: float
    lat: float
    address: str


class MapPreviewResponse(BaseModel):
    provider: str = "leaflet-osm"
    geocoder: str = "amap-mcp"
    center: dict[str, float] | None = None
    points: list[MapPoint] = Field(default_factory=list)
    days: list["MapPreviewDay"] = Field(default_factory=list)


class MapPreviewDay(BaseModel):
    key: str
    label: str
    points: list[MapPoint] = Field(default_factory=list)


MapPreviewRequest.model_rebuild()
MapPreviewResponse.model_rebuild()

PREVIEW_CACHE_TTL_SECONDS = 60 * 10
GEOCODE_CACHE_TTL_SECONDS = 60 * 60 * 12
GEOCODE_FAILURE_TTL_SECONDS = 60 * 15

_preview_cache: dict[str, tuple[float, "MapPreviewResponse"]] = {}
_geocode_cache: dict[str, tuple[float, "MapPoint | None"]] = {}


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
    compact = " ".join(text.replace("\n", " ").split()).strip()
    for token in ["待确认", "待继续", "交通待定", "住宿待补充"]:
        compact = compact.replace(token, "")
    compact = compact.strip("，。；、：:,. ")
    return compact[:40]


def _build_day_key(label: str, index: int) -> str:
    compact = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return compact or f"day-{index + 1}"


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


async def _get_amap_geo_tool():
    manager = await get_mcp_client(servers=["amap"])
    tools = await manager.get_tools(servers=["amap"])
    for tool_item in tools:
        if tool_item.name == "maps_geo":
            return tool_item
    raise RuntimeError("AMap geocoder tool not available")


def _make_geocode_cache_key(address: str, city: str | None = None) -> str:
    normalized_address = _normalize_query(address)
    normalized_city = _normalize_query(city)
    return f"{normalized_city}::{normalized_address}".strip(":")


def _clone_map_point(value: MapPoint | None) -> MapPoint | None:
    return value.model_copy(deep=True) if value else None


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
        result = await tool.ainvoke(payload)
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


@router.post("/preview", response_model=MapPreviewResponse)
async def get_map_preview(
    data: MapPreviewRequest,
    user: User = Depends(get_current_user),
):
    """Resolve frontend route-preview places into coordinates for live map rendering."""

    cache_key = json.dumps(
        {
            "origin": data.origin,
            "destination": data.destination,
            "stay": data.stay,
            "highlights": data.highlights[:4],
            "days": [
                {
                    "label": day.label,
                    "waypoints": day.waypoints[:8],
                }
                for day in data.days[:7]
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached_preview = _preview_cache.get(cache_key)
    if cached_preview and cached_preview[0] > time.time():
        return MapPreviewResponse.model_validate(cached_preview[1].model_dump())

    geo_tool = await _get_amap_geo_tool()
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

    day_groups: list[MapPreviewDay] = []
    for index, day in enumerate(data.days[:7]):
        seen_names: set[str] = set()
        day_points: list[MapPoint] = []
        for waypoint in day.waypoints[:8]:
            normalized_waypoint = _normalize_query(waypoint)
            if not normalized_waypoint:
                continue
            point = await _resolve_point(
                geo_tool,
                address=normalized_waypoint,
                label=_normalize_query(day.label) or f"Day {index + 1}",
                kind="day",
                city=None,
            )
            if not point and destination_hint and destination_hint not in normalized_waypoint:
                point = await _resolve_point(
                    geo_tool,
                    address=f"{destination_hint} {normalized_waypoint}".strip(),
                    label=_normalize_query(day.label) or f"Day {index + 1}",
                    kind="day",
                    city=destination_hint,
                )
            if not point:
                continue
            point = point.model_copy(update={"name": normalized_waypoint, "address": normalized_waypoint})
            dedupe_key = f"{point.lat:.5f},{point.lng:.5f}"
            if dedupe_key in seen_names:
                continue
            seen_names.add(dedupe_key)
            day_points.append(point)
        if day_points:
            day_groups.append(
                MapPreviewDay(
                    key=_build_day_key(day.label, index),
                    label=_normalize_query(day.label) or f"Day {index + 1}",
                    points=day_points,
                )
            )

    center_source = next(
        (item for item in points if item.kind == "destination"),
        points[0] if points else None,
    )
    center = (
        {"lng": center_source.lng, "lat": center_source.lat}
        if center_source
        else None
    )

    app_logger.info(
        "Generated map preview payload: "
        f"user_id={user.id}, points={len(points)}, day_groups={len(day_groups)}, "
        f"destination={destination_hint or 'n/a'}"
    )
    response = MapPreviewResponse(center=center, points=points, days=day_groups)
    _preview_cache[cache_key] = (
        time.time() + PREVIEW_CACHE_TTL_SECONDS,
        MapPreviewResponse.model_validate(response.model_dump()),
    )
    return response
