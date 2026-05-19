"""Optional live enrichment for map-first journey drafts."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import math
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import has_real_env_value, settings
from app.utils.logger import app_logger


AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
AMAP_GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

LIVE_ENRICHMENT_TIMEOUT_SECONDS = 14.0
HTTP_TIMEOUT_SECONDS = 2.2
MAX_POI_LOOKUPS = 28
MAX_ROUTE_LOOKUPS = 18
MAX_WEATHER_CITIES = 5


_COMMON_CITY_ADCODES = {
    "北京": "110000",
    "上海": "310000",
    "广州": "440100",
    "深圳": "440300",
    "杭州": "330100",
    "南京": "320100",
    "武汉": "420100",
    "重庆": "500000",
    "成都": "510100",
    "西安": "610100",
    "长沙": "430100",
    "青岛": "370200",
    "厦门": "350200",
    "三亚": "460200",
    "苏州": "320500",
    "桂林": "450300",
    "昆明": "530100",
    "大理": "532900",
    "丽江": "530700",
    "拉萨": "540100",
    "林芝": "540400",
    "山南": "540500",
    "哈尔滨": "230100",
}


def _trace(
    *,
    phase: str,
    title: str,
    detail: str,
    status: str = "completed",
    count: int | None = None,
    city: str = "",
    date_range: str = "",
    evidence_type: str = "live_enrichment",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": phase,
        "status": status,
        "title": title,
        "detail": detail,
        "evidence_type": evidence_type,
    }
    if count is not None:
        payload["count"] = count
    if city:
        payload["city"] = city
    if date_range:
        payload["date_range"] = date_range
    return payload


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _parse_lng_lat(value: Any) -> tuple[float, float] | None:
    text = str(value or "").strip()
    if "," not in text:
        return None
    lng_text, lat_text = text.split(",", 1)
    lng = _as_float(lng_text)
    lat = _as_float(lat_text)
    if lng is None or lat is None:
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return lng, lat


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


def _clean_text(value: Any, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return text[:limit]


def _is_generic_seed_poi(poi: dict[str, Any]) -> bool:
    return bool(poi.get("is_generic_seed"))


def _is_useful_seed_candidate_name(name: Any, original_name: Any) -> bool:
    candidate = _clean_text(name, limit=80)
    original = _clean_text(original_name, limit=80)
    if not candidate or candidate == original:
        return False
    generic_tokens = ("省", "市", "区", "县", "自治州", "行政区划")
    return not (candidate.endswith(generic_tokens) and len(candidate) <= 12)


def _source_domains(results: list[dict[str, Any]]) -> list[str]:
    domains: list[str] = []
    for item in results:
        parsed = urlparse(str(item.get("url") or ""))
        domain = parsed.netloc.lower().lstrip("www.")
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:5]


def resolve_city_adcode(city: str) -> str | None:
    """Resolve the common city names used by visual journey plans."""

    normalized = str(city or "").strip()
    if normalized.isdigit() and len(normalized) == 6:
        return normalized
    for key, adcode in _COMMON_CITY_ADCODES.items():
        if key in normalized:
            return adcode
    return None


def amap_place_candidate_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract the first useful POI candidate from an AMap place/geocode payload."""

    pois = payload.get("pois") if isinstance(payload, dict) else None
    if isinstance(pois, list):
        for item in pois:
            if not isinstance(item, dict):
                continue
            lng_lat = _parse_lng_lat(item.get("location"))
            if not lng_lat:
                continue
            photos = item.get("photos") if isinstance(item.get("photos"), list) else []
            image_url = ""
            for photo in photos:
                if isinstance(photo, dict) and photo.get("url"):
                    image_url = str(photo["url"])
                    break
            lng, lat = lng_lat
            return {
                "source": "amap_place_text",
                "amap_poi_id": item.get("id") or "",
                "source_name": item.get("name") or "",
                "lng": lng,
                "lat": lat,
                "address": item.get("address") or item.get("adname") or "",
                "city": item.get("cityname") or "",
                "type": item.get("type") or "",
                "image_url": image_url,
            }

    geocodes = payload.get("geocodes") if isinstance(payload, dict) else None
    if isinstance(geocodes, list):
        for item in geocodes:
            if not isinstance(item, dict):
                continue
            lng_lat = _parse_lng_lat(item.get("location"))
            if not lng_lat:
                continue
            lng, lat = lng_lat
            return {
                "source": "amap_geocode",
                "source_name": item.get("formatted_address") or "",
                "lng": lng,
                "lat": lat,
                "address": item.get("formatted_address") or "",
                "city": item.get("city") or "",
                "type": "geocode",
                "image_url": "",
            }
    return {}


def merge_amap_candidate_into_poi(poi: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Merge a verified AMap candidate into one visual journey POI."""

    lng = _as_float(candidate.get("lng"))
    lat = _as_float(candidate.get("lat"))
    if lng is None or lat is None:
        return False

    poi["lng"] = lng
    poi["lat"] = lat
    poi["map_verified"] = True
    poi["verification_status"] = candidate.get("source") or "amap_verified"
    if candidate.get("amap_poi_id"):
        poi["amap_poi_id"] = str(candidate["amap_poi_id"])
    if candidate.get("source_name"):
        poi["amap_source_name"] = _clean_text(candidate["source_name"], limit=80)
    if candidate.get("address"):
        poi["address"] = _clean_text(candidate["address"], limit=120)
    if candidate.get("city"):
        poi["amap_city"] = _clean_text(candidate["city"], limit=40)
    if candidate.get("type"):
        poi["amap_type"] = _clean_text(candidate["type"], limit=80)
    if candidate.get("image_url") and not poi.get("image_url"):
        poi["image_url"] = str(candidate["image_url"])
    if (
        _is_generic_seed_poi(poi)
        and candidate.get("source") == "amap_place_text"
        and _is_useful_seed_candidate_name(candidate.get("source_name"), poi.get("name"))
    ):
        original_name = _clean_text(poi.get("name"), limit=80)
        source_name = _clean_text(candidate.get("source_name"), limit=80)
        poi["original_seed_name"] = original_name
        poi["name"] = source_name
        poi["map_query"] = f"{poi.get('city') or ''} {source_name}".strip()
        poi["verification_note"] = "已由高德地点搜索把通用占位点替换为真实地点，开放和预约仍需二次核验。"
    return True


def apply_route_payload_to_segment(segment: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Merge AMap driving route metrics into one journey segment."""

    route = payload.get("route") if isinstance(payload, dict) else None
    paths = route.get("paths") if isinstance(route, dict) else None
    if not isinstance(paths, list) or not paths:
        return False
    path = paths[0] if isinstance(paths[0], dict) else {}
    distance = _as_float(path.get("distance"))
    duration = _as_float(path.get("duration"))
    if not distance or not duration:
        return False

    segment["distance_meters"] = distance
    segment["duration_seconds"] = duration
    segment["distance_text"] = _format_distance(distance)
    segment["duration_text"] = _format_duration(duration)
    segment["confidence"] = "amap_driving"
    segment["source"] = "amap_direction_driving"
    return True


def _haversine_distance_meters(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    left_lng = _as_float(left.get("lng"))
    left_lat = _as_float(left.get("lat"))
    right_lng = _as_float(right.get("lng"))
    right_lat = _as_float(right.get("lat"))
    if None in {left_lng, left_lat, right_lng, right_lat}:
        return None
    radius = 6371000
    lat1 = math.radians(float(left_lat))
    lat2 = math.radians(float(right_lat))
    d_lat = math.radians(float(right_lat) - float(left_lat))
    d_lng = math.radians(float(right_lng) - float(left_lng))
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def apply_estimated_route_to_segment(
    segment: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    """Fill a visible distance/duration estimate when live routing is unavailable."""

    distance = _haversine_distance_meters(left, right)
    if not distance or distance <= 0:
        return False
    duration = distance / 1000 / 25 * 3600
    segment["distance_meters"] = round(distance, 1)
    segment["duration_seconds"] = round(duration, 1)
    segment["distance_text"] = f"约 {_format_distance(distance)}"
    segment["duration_text"] = f"约 {_format_duration(duration)}"
    segment["confidence"] = "estimated_straight_line"
    segment["source"] = "coordinate_estimate"
    segment["verification_note"] = "按两点坐标直线估算，真实驾车/步行路线待高德二次核验。"
    return True


def weather_summary_from_amap_payload(
    city: str,
    date_text: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a user-safe weather summary from an AMap forecast payload."""

    forecasts = payload.get("forecasts") if isinstance(payload, dict) else None
    if not isinstance(forecasts, list) or not forecasts:
        return {
            "city": city,
            "summary": "实时天气暂未返回可用预报，出发前需二次核验。",
            "confidence": "weather_unavailable",
        }
    forecast = forecasts[0] if isinstance(forecasts[0], dict) else {}
    casts = forecast.get("casts") if isinstance(forecast.get("casts"), list) else []
    exact = None
    for cast in casts:
        if isinstance(cast, dict) and date_text and cast.get("date") == date_text:
            exact = cast
            break
    chosen = exact or (casts[0] if casts and isinstance(casts[0], dict) else {})
    if not chosen:
        return {
            "city": city,
            "summary": "实时天气暂未返回可用预报，出发前需二次核验。",
            "confidence": "weather_unavailable",
            "report_time": forecast.get("reporttime") or "",
        }

    day_weather = chosen.get("dayweather") or "未知"
    night_weather = chosen.get("nightweather") or "未知"
    day_temp = chosen.get("daytemp") or "?"
    night_temp = chosen.get("nighttemp") or "?"
    wind = chosen.get("daywind") or "未知"
    power = chosen.get("daypower") or "未知"
    chosen_date = chosen.get("date") or "近期"
    base = (
        f"{chosen_date} 白天{day_weather}/夜间{night_weather}，"
        f"{night_temp}-{day_temp}°C，{wind}风 {power} 级。"
    )
    if exact:
        summary = base + "可据此微调室内外顺序。"
        confidence = "amap_weather_forecast"
    else:
        summary = base + "当前旅行日期超出可用预报窗口，出发前仍需临近复核。"
        confidence = "amap_weather_reference"
    return {
        "city": city,
        "summary": summary,
        "confidence": confidence,
        "report_time": forecast.get("reporttime") or "",
    }


def _flatten_days(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pois: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        pois.extend(poi for poi in day.get("pois") or [] if isinstance(poi, dict))
        segments.extend(segment for segment in day.get("segments") or [] if isinstance(segment, dict))
    return pois, segments


def _alternative_pois(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        poi
        for poi in plan.get("alternative_pois") or []
        if isinstance(poi, dict)
    ]


def _refresh_flattened_sections(plan: dict[str, Any]) -> None:
    pois, segments = _flatten_days(plan)
    poi_lookup = {
        str(poi.get("id")): poi
        for poi in pois
        if isinstance(poi, dict) and poi.get("id")
    }
    for segment in segments:
        left = poi_lookup.get(str(segment.get("from_poi_id") or ""))
        right = poi_lookup.get(str(segment.get("to_poi_id") or ""))
        if left and left.get("name"):
            segment["from_name"] = str(left["name"])
        if right and right.get("name"):
            segment["to_name"] = str(right["name"])
    plan["pois"] = pois
    plan["segments"] = segments


def _poi_by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pois, _segments = _flatten_days(plan)
    return {
        str(poi.get("id")): poi
        for poi in pois
        if poi.get("id")
    }


def estimate_remaining_route_segments(plan: dict[str, Any]) -> int:
    """Fill pending route segments with coordinate estimates where possible."""

    poi_lookup = _poi_by_id(plan)
    _pois, segments = _flatten_days(plan)
    estimated = 0
    for segment in segments:
        if segment.get("confidence") == "amap_driving":
            continue
        metric_text = f"{segment.get('distance_text') or ''} {segment.get('duration_text') or ''}"
        if metric_text.strip() and "待" not in metric_text and "needs" not in metric_text:
            continue
        left = poi_lookup.get(str(segment.get("from_poi_id"))) or {}
        right = poi_lookup.get(str(segment.get("to_poi_id"))) or {}
        if apply_estimated_route_to_segment(segment, left, right):
            estimated += 1
    if estimated:
        _refresh_flattened_sections(plan)
    return estimated


def estimate_missing_poi_coordinates_by_day(plan: dict[str, Any]) -> int:
    """Place unverified same-day POIs near a verified anchor so the map remains continuous."""

    estimated = 0
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        pois = [poi for poi in day.get("pois") or [] if isinstance(poi, dict)]
        anchor = next(
            (
                poi
                for poi in pois
                if _as_float(poi.get("lng")) is not None and _as_float(poi.get("lat")) is not None
            ),
            None,
        )
        if not anchor:
            continue
        anchor_lng = _as_float(anchor.get("lng"))
        anchor_lat = _as_float(anchor.get("lat"))
        if anchor_lng is None or anchor_lat is None:
            continue
        missing_index = 0
        for poi in pois:
            if _as_float(poi.get("lng")) is not None and _as_float(poi.get("lat")) is not None:
                continue
            missing_index += 1
            direction = -1 if missing_index % 2 else 1
            poi["lng"] = round(anchor_lng + direction * 0.012 * missing_index, 6)
            poi["lat"] = round(anchor_lat + 0.008 * missing_index, 6)
            poi["coordinate_estimated"] = True
            poi["verification_status"] = "estimated_nearby_verified_poi"
            poi["verification_note"] = "高德未在短超时内命中该点，暂按同日已核验地点附近落点展示，真实坐标待二次核验。"
            estimated += 1
    if estimated:
        _refresh_flattened_sections(plan)
    return estimated


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = (
        await client.post(url, json=json_body, params=params)
        if method == "POST"
        else await client.get(url, params=params)
    )
    if response.status_code >= 400:
        return {"error": f"http_{response.status_code}"}
    data = response.json()
    return data if isinstance(data, dict) else {}


async def _lookup_poi_candidate(
    client: httpx.AsyncClient,
    poi: dict[str, Any],
    *,
    api_key: str,
) -> dict[str, Any]:
    name = str(poi.get("name") or "").strip()
    city = str(poi.get("city") or "").strip()
    query = str(poi.get("map_query") or name).strip()
    search_keyword = str(poi.get("search_keyword") or name or query).strip()
    if not name and not query:
        return {}

    has_coordinates = _as_float(poi.get("lng")) is not None and _as_float(poi.get("lat")) is not None
    if _is_generic_seed_poi(poi) and search_keyword:
        place_payload = await _get_json(
            client,
            AMAP_PLACE_TEXT_URL,
            {
                "key": api_key,
                "keywords": search_keyword,
                "city": city,
                "offset": 1,
                "page": 1,
                "extensions": "all",
                "output": "JSON",
            },
        )
        candidate = amap_place_candidate_from_payload(place_payload)
        if candidate:
            return candidate

    if not has_coordinates:
        geocode_payload = await _get_json(
            client,
            AMAP_GEOCODE_URL,
            {
                "key": api_key,
                "address": query,
                "city": city,
                "output": "JSON",
            },
        )
        candidate = amap_place_candidate_from_payload(geocode_payload)
        if candidate:
            return candidate

    place_payload = await _get_json(
        client,
        AMAP_PLACE_TEXT_URL,
        {
            "key": api_key,
            "keywords": name or query,
            "city": city,
            "offset": 1,
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        },
    )
    candidate = amap_place_candidate_from_payload(place_payload)
    if candidate:
        return candidate

    if not has_coordinates:
        return {}

    geocode_payload = await _get_json(
        client,
        AMAP_GEOCODE_URL,
        {
            "key": api_key,
            "address": query,
            "city": city,
            "output": "JSON",
        },
    )
    return amap_place_candidate_from_payload(geocode_payload)


async def _enrich_pois_with_amap(
    plan: dict[str, Any],
    trace: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> int:
    pois, _segments = _flatten_days(plan)
    alternatives = _alternative_pois(plan)
    target_pois = (pois + alternatives)[:MAX_POI_LOOKUPS]
    semaphore = asyncio.Semaphore(4)

    async def _lookup_and_merge(poi: dict[str, Any]) -> bool:
        async with semaphore:
            try:
                candidate = await _lookup_poi_candidate(client, poi, api_key=api_key)
            except Exception as exc:
                app_logger.info(f"Visual journey AMap POI lookup failed: {poi.get('name')}: {exc}")
                return False
            return merge_amap_candidate_into_poi(poi, candidate)

    results = await asyncio.gather(*(_lookup_and_merge(poi) for poi in target_pois))
    verified = sum(1 for ok in results if ok)
    estimated = estimate_missing_poi_coordinates_by_day(plan)
    if verified:
        trace.append(
            _trace(
                phase="poi",
                title="高德地点已核验",
                detail=(
                    f"已用高德地点搜索/地理编码核验 {verified} 个地点坐标，包含主行程点和可替换备选点；"
                    f"另有 {estimated} 个同日点位按附近锚点临时落位并标注待核验。"
                ),
                count=verified,
                evidence_type="amap_poi",
            )
        )
    else:
        trace.append(
            _trace(
                phase="poi",
                title="高德地点核验降级",
                detail=(
                    "本轮未取得可用高德地点结果，继续使用草案点位和地图查询词，"
                    "地点开放与坐标待二次核验。"
                ),
                status="degraded",
                evidence_type="amap_poi",
            )
        )
    _refresh_flattened_sections(plan)
    return verified


async def _lookup_route_segment(
    client: httpx.AsyncClient,
    segment: dict[str, Any],
    *,
    poi_lookup: dict[str, dict[str, Any]],
    api_key: str,
) -> str:
    left = poi_lookup.get(str(segment.get("from_poi_id")))
    right = poi_lookup.get(str(segment.get("to_poi_id")))
    if not left or not right:
        return False
    left_lng = _as_float(left.get("lng"))
    left_lat = _as_float(left.get("lat"))
    right_lng = _as_float(right.get("lng"))
    right_lat = _as_float(right.get("lat"))
    if None in {left_lng, left_lat, right_lng, right_lat}:
        return "missing"

    payload = await _get_json(
        client,
        AMAP_DRIVING_URL,
        {
            "key": api_key,
            "origin": f"{left_lng},{left_lat}",
            "destination": f"{right_lng},{right_lat}",
            "extensions": "base",
            "output": "JSON",
        },
    )
    if apply_route_payload_to_segment(segment, payload):
        return "amap"
    if apply_estimated_route_to_segment(segment, left, right):
        return "estimated"
    return "missing"


async def _enrich_routes_with_amap(
    plan: dict[str, Any],
    trace: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> int:
    _pois, segments = _flatten_days(plan)
    target_segments = segments[:MAX_ROUTE_LOOKUPS]
    poi_lookup = _poi_by_id(plan)
    semaphore = asyncio.Semaphore(3)

    async def _lookup(segment: dict[str, Any]) -> str:
        async with semaphore:
            try:
                return await _lookup_route_segment(
                    client,
                    segment,
                    poi_lookup=poi_lookup,
                    api_key=api_key,
                )
            except Exception as exc:
                app_logger.info(
                    "Visual journey AMap route lookup failed: "
                    f"{segment.get('from_name')}->{segment.get('to_name')}: {exc}"
                )
                left = poi_lookup.get(str(segment.get("from_poi_id"))) or {}
                right = poi_lookup.get(str(segment.get("to_poi_id"))) or {}
                return "estimated" if apply_estimated_route_to_segment(segment, left, right) else "missing"

    results = await asyncio.gather(*(_lookup(segment) for segment in target_segments))
    verified = sum(1 for status in results if status == "amap")
    estimated = sum(1 for status in results if status == "estimated")
    estimated += estimate_remaining_route_segments(plan)
    if verified:
        trace.append(
            _trace(
                phase="route",
                title="高德路线距离已回填",
                detail=(
                    f"已用高德驾车路线核验 {verified} 段相邻 POI 距离和时长；"
                    f"另有 {estimated} 段按坐标估算并保留待核验标记。"
                ),
                count=verified,
                evidence_type="amap_direction",
            )
        )
    elif estimated:
        trace.append(
            _trace(
                phase="route",
                title="路线距离已估算",
                detail=f"本轮高德驾车路线未返回可用结果，已按坐标为 {estimated} 段路程估算距离/时长，并标注待核验。",
                status="degraded",
                count=estimated,
                evidence_type="route_coordinate_estimate",
            )
        )
    else:
        trace.append(
            _trace(
                phase="route",
                title="路线距离回填降级",
                detail="本轮未取得可用高德驾车路线，地图仍显示点位连线，距离和时长待二次核验。",
                status="degraded",
                evidence_type="amap_direction",
            )
        )
    _refresh_flattened_sections(plan)
    return verified


def _journey_cities(plan: dict[str, Any]) -> list[str]:
    cities: list[str] = []
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        city = str(day.get("city") or "").strip()
        if city and city not in cities:
            cities.append(city)
    return cities[:MAX_WEATHER_CITIES]


async def _fetch_weather(
    client: httpx.AsyncClient,
    city: str,
    *,
    api_key: str,
) -> dict[str, Any]:
    adcode = resolve_city_adcode(city)
    if not adcode:
        return {}
    return await _get_json(
        client,
        AMAP_WEATHER_URL,
        {
            "key": api_key,
            "city": adcode,
            "extensions": "all",
            "output": "JSON",
        },
    )


async def _enrich_weather_with_amap(
    plan: dict[str, Any],
    trace: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> int:
    cities = _journey_cities(plan)
    semaphore = asyncio.Semaphore(3)

    async def _lookup_weather(city: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            try:
                return city, await _fetch_weather(client, city, api_key=api_key)
            except Exception as exc:
                app_logger.info(f"Visual journey weather lookup failed: {city}: {exc}")
                return city, {}

    results = await asyncio.gather(*(_lookup_weather(city) for city in cities))
    weather_by_city: dict[str, dict[str, Any]] = {}
    for city, payload in results:
        if payload:
            weather_by_city[city] = payload

    applied = 0
    weather_items: list[dict[str, Any]] = []
    for day in plan.get("days") or []:
        if not isinstance(day, dict):
            continue
        city = str(day.get("city") or "").strip()
        payload = weather_by_city.get(city)
        if not payload:
            continue
        summary = weather_summary_from_amap_payload(city, str(day.get("date") or ""), payload)
        day["weather"] = summary
        applied += 1
    for city, payload in weather_by_city.items():
        summary = weather_summary_from_amap_payload(city, "", payload)
        weather_items.append(
            {
                "city": city,
                "date_range": (plan.get("overview") or {}).get("date_range") or "",
                "status": summary.get("confidence") or "amap_weather",
                "summary": summary.get("summary") or "",
                "report_time": summary.get("report_time") or "",
            }
        )
    if weather_items:
        plan["weather"] = weather_items

    if weather_by_city:
        trace.append(
            _trace(
                phase="weather",
                title="天气信息已查询",
                detail=f"已查询 {len(weather_by_city)} 个城市的高德天气；若旅行日期超出预报窗口，仍标注临近复核。",
                count=len(weather_by_city),
                city="、".join(weather_by_city),
                date_range=(plan.get("overview") or {}).get("date_range") or "",
                evidence_type="amap_weather",
            )
        )
    else:
        trace.append(
            _trace(
                phase="weather",
                title="天气查询降级",
                detail="本轮未取得可用高德天气，天气、开放和道路状况仍需出发前二次核验。",
                status="degraded",
                date_range=(plan.get("overview") or {}).get("date_range") or "",
                evidence_type="amap_weather",
            )
        )
    return applied


async def _enrich_public_search(
    plan: dict[str, Any],
    trace: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    key = settings.tavily_api_key.strip()
    if not has_real_env_value(key):
        trace.append(
            _trace(
                phase="search",
                title="公开搜索降级",
                detail="Tavily 搜索 Key 未配置或为占位值，本轮只使用路线样板和地图核验；不伪造小红书或全网来源。",
                status="degraded",
                evidence_type="public_search",
            )
        )
        return {"status": "degraded", "reason": "search_key_unavailable"}

    overview = plan.get("overview") if isinstance(plan.get("overview"), dict) else {}
    source_summary = plan.get("source_summary") if isinstance(plan.get("source_summary"), dict) else {}
    queries = source_summary.get("search_queries") if isinstance(source_summary.get("search_queries"), list) else []
    query = str(queries[0] if queries else "").strip()
    if not query:
        query = f"{overview.get('destination') or ''}{overview.get('duration_days') or ''}天经典旅游路线"
    query = f"{query} 小红书 全网攻略".strip()

    try:
        payload = await _get_json(
            client,
            TAVILY_SEARCH_URL,
            {},
            method="POST",
            json_body={
                "api_key": key,
                "query": query,
                "search_depth": "basic",
                "max_results": 4,
                "include_answer": True,
            },
        )
    except Exception as exc:
        app_logger.info(f"Visual journey public search failed: {exc}")
        trace.append(
            _trace(
                phase="search",
                title="公开搜索降级",
                detail="公开搜索暂时失败，本轮不伪造来源，开放、票价、预约和攻略细节需二次核验。",
                status="degraded",
                evidence_type="public_search",
            )
        )
        return {"status": "degraded", "reason": "search_failed"}

    results = [
        item
        for item in payload.get("results") or []
        if isinstance(item, dict) and (item.get("title") or item.get("url"))
    ]
    domains = _source_domains(results)
    has_xhs = any("xiaohongshu" in domain or "xhslink" in domain for domain in domains)
    source_note = (
        "其中包含可审计小红书相关页面。"
        if has_xhs
        else "未命中可审计小红书页面，摘要只标注为全网公开攻略命中。"
    )
    answer = _clean_text(payload.get("answer"), limit=240)
    trace.append(
        _trace(
            phase="search",
            title="公开攻略搜索已回填",
            detail=f"全网公开攻略命中 {len(results)} 条；{source_note}",
            count=len(results),
            evidence_type="public_search",
        )
    )
    return {
        "status": "completed" if results else "degraded",
        "query": query,
        "answer": answer,
        "result_count": len(results),
        "domains": domains,
        "sources": [
            {
                "title": _clean_text(item.get("title"), limit=120),
                "url": str(item.get("url") or ""),
            }
            for item in results[:4]
        ],
        "has_xiaohongshu_source": has_xhs,
    }


def _mark_source_summary(
    plan: dict[str, Any],
    *,
    search: dict[str, Any],
    poi_count: int,
    route_count: int,
    route_estimated_count: int,
    coordinate_estimated_poi_count: int,
    weather_day_count: int,
) -> None:
    summary = plan.get("source_summary")
    if not isinstance(summary, dict):
        summary = {}
        plan["source_summary"] = summary
    evidence_types = list(summary.get("evidence_types") or [])
    for evidence_type in [
        "public_search",
        "amap_poi",
        "amap_direction",
        "amap_weather",
    ]:
        if evidence_type not in evidence_types:
            evidence_types.append(evidence_type)
    summary["evidence_types"] = evidence_types
    summary["live_enrichment"] = {
        "public_search": search,
        "amap_poi_verified_count": poi_count,
        "coordinate_estimated_poi_count": coordinate_estimated_poi_count,
        "amap_route_verified_count": route_count,
        "route_estimated_count": route_estimated_count,
        "amap_weather_day_count": weather_day_count,
    }


def _add_pending_check_note(plan: dict[str, Any], *, route_count: int, weather_day_count: int) -> None:
    pending_checks = plan.get("pending_checks")
    if not isinstance(pending_checks, list):
        pending_checks = []
        plan["pending_checks"] = pending_checks
    if route_count:
        note = "部分地图路段已用高德路线核验，未覆盖路段的距离和时长仍需出发前复核。"
        if note not in pending_checks:
            pending_checks.append(note)
    if weather_day_count:
        note = "天气已做实时或近期窗口查询，超出预报窗口的出行日期仍需临近复核。"
        if note not in pending_checks:
            pending_checks.append(note)


async def _enrich_with_live_services(plan: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        search = await _enrich_public_search(plan, trace, client=client)

        amap_key = settings.amap_api_key.strip()
        if not has_real_env_value(amap_key):
            trace.append(
                _trace(
                    phase="map",
                    title="高德实时回填降级",
                    detail="AMAP_API_KEY 未配置或为占位值，本轮保留草案坐标和待核验路段。",
                    status="degraded",
                    evidence_type="amap_live_enrichment",
                )
            )
            _mark_source_summary(
                plan,
                search=search,
                poi_count=0,
                route_count=0,
                route_estimated_count=0,
                coordinate_estimated_poi_count=0,
                weather_day_count=0,
            )
            return

        poi_count = await _enrich_pois_with_amap(
            plan,
            trace,
            client=client,
            api_key=amap_key,
        )
        coordinate_estimated_poi_count = sum(
            1
            for poi in plan.get("pois") or []
            if isinstance(poi, dict) and poi.get("coordinate_estimated")
        )
        route_count = await _enrich_routes_with_amap(
            plan,
            trace,
            client=client,
            api_key=amap_key,
        )
        route_estimated_count = sum(
            1
            for segment in plan.get("segments") or []
            if isinstance(segment, dict) and segment.get("confidence") == "estimated_straight_line"
        )
        weather_day_count = await _enrich_weather_with_amap(
            plan,
            trace,
            client=client,
            api_key=amap_key,
        )
        _mark_source_summary(
            plan,
            search=search,
            poi_count=poi_count,
            route_count=route_count,
            route_estimated_count=route_estimated_count,
            coordinate_estimated_poi_count=coordinate_estimated_poi_count,
            weather_day_count=weather_day_count,
        )
        _add_pending_check_note(
            plan,
            route_count=route_count,
            weather_day_count=weather_day_count,
        )


async def enrich_visual_journey_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a live-enriched copy of a visual journey result when services respond."""

    plan = deepcopy(result.get("journey_plan") or {})
    trace = [dict(item) for item in result.get("planning_trace") or [] if isinstance(item, dict)]
    if not plan:
        return result
    try:
        await asyncio.wait_for(
            _enrich_with_live_services(plan, trace),
            timeout=LIVE_ENRICHMENT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        estimate_missing_poi_coordinates_by_day(plan)
        estimated = estimate_remaining_route_segments(plan)
        trace.append(
            _trace(
                phase="map",
                title="实时回填超时降级",
                detail=(
                    "公开搜索/高德路线/天气回填超过短超时窗口，"
                    f"已保留可视化草案并用现有坐标估算 {estimated} 段路线。"
                ),
                status="degraded",
                count=estimated,
                evidence_type="live_enrichment_timeout",
            )
        )
    except Exception as exc:
        app_logger.warning(f"Visual journey live enrichment failed: {exc}")
        estimate_missing_poi_coordinates_by_day(plan)
        estimated = estimate_remaining_route_segments(plan)
        trace.append(
            _trace(
                phase="map",
                title="实时回填异常降级",
                detail=(
                    "公开搜索/高德路线/天气回填暂时不可用，"
                    f"已保留可视化草案并用现有坐标估算 {estimated} 段路线。"
                ),
                status="degraded",
                count=estimated,
                evidence_type="live_enrichment_failed",
            )
        )
    return {"journey_plan": plan, "planning_trace": trace}
