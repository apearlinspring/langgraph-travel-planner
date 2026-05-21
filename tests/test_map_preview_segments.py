from types import SimpleNamespace

import pytest

import app.api.v1.maps as maps
from app.api.v1.maps import (
    MapPoint,
    MapPreviewDay,
    MapPreviewResponse,
    MapPreviewRequest,
    MapPreviewStopRequest,
    _fallback_points_from_day_groups,
    _map_preview_deadline_expired,
    _point_from_stop_coordinates,
    _resolve_segment,
)


@pytest.mark.asyncio
async def test_resolve_segment_falls_back_to_estimated_distance_without_direction_tool():
    left = MapPoint(
        kind="day",
        label="Day 1",
        name="布达拉宫",
        lng=91.117,
        lat=29.657,
        address="布达拉宫",
    )
    right = MapPoint(
        kind="day",
        label="Day 1",
        name="大昭寺",
        lng=91.133,
        lat=29.65,
        address="大昭寺",
    )

    segment = await _resolve_segment(
        None,
        day_key="day-1",
        day_label="Day 1",
        left=left,
        right=right,
    )

    assert segment.from_name == "布达拉宫"
    assert segment.to_name == "大昭寺"
    assert segment.confidence == "estimated_straight_line"
    assert segment.distance_meters and segment.distance_meters > 0
    assert "约" in segment.distance_text
    assert segment.path == [
        {"lng": left.lng, "lat": left.lat},
        {"lng": right.lng, "lat": right.lat},
    ]


@pytest.mark.asyncio
async def test_resolve_segment_exposes_amap_route_path():
    class FakeDirectionTool:
        async def ainvoke(self, payload):
            assert payload["origin"] == "120.1,30.1"
            return (
                '{"paths":[{"distance":"1200","duration":"900","steps":['
                '{"polyline":"120.100000,30.100000;120.110000,30.105000"},'
                '{"polyline":"120.110000,30.105000;120.120000,30.110000"}]}]}'
            )

    left = MapPoint(
        kind="day",
        label="Day 1",
        name="西湖",
        lng=120.1,
        lat=30.1,
        address="西湖",
    )
    right = MapPoint(
        kind="day",
        label="Day 1",
        name="灵隐寺",
        lng=120.12,
        lat=30.11,
        address="灵隐寺",
    )

    segment = await _resolve_segment(
        FakeDirectionTool(),
        day_key="day-1",
        day_label="Day 1",
        left=left,
        right=right,
    )

    assert segment.confidence == "amap_driving"
    assert segment.distance_text == "1.2 公里"
    assert segment.path == [
        {"lng": 120.1, "lat": 30.1},
        {"lng": 120.11, "lat": 30.105},
        {"lng": 120.12, "lat": 30.11},
    ]


def test_point_from_stop_coordinates_uses_structured_poi_position():
    stop = MapPreviewStopRequest(
        id="d1-p1",
        name="巴松措",
        city="林芝",
        lng=93.9616,
        lat=30.0239,
    )

    point = _point_from_stop_coordinates(stop, label="05-28 周四")

    assert point
    assert point.name == "巴松措"
    assert point.address == "林芝"
    assert point.lng == 93.9616
    assert point.lat == 30.0239


def test_map_preview_request_accepts_structured_recommendation_points():
    request = MapPreviewRequest.model_validate(
        {
            "destination": "杭州",
            "recommendations": [
                {
                    "id": "alt-p1",
                    "name": "九溪烟树",
                    "city": "杭州",
                    "lng": 120.1019,
                    "lat": 30.2024,
                }
            ],
        }
    )

    point = _point_from_stop_coordinates(
        request.recommendations[0],
        label="推荐点",
        kind="recommendation",
    )

    assert point
    assert point.kind == "recommendation"
    assert point.label == "推荐点"
    assert point.name == "九溪烟树"
    assert point.address == "杭州"


def test_map_preview_response_exposes_timing_and_degraded_status():
    response = MapPreviewResponse(
        status="degraded",
        message="地图服务响应较慢，已先展示可定位到的地点。",
        elapsed_seconds=10.5,
    )

    assert response.status == "degraded"
    assert response.elapsed_seconds == 10.5
    assert _map_preview_deadline_expired(0.0) is False


@pytest.mark.asyncio
async def test_map_preview_uses_structured_coordinates_when_geocoder_unavailable(
    monkeypatch,
):
    async def fail_to_load_amap_tool(name):
        raise TimeoutError()

    monkeypatch.setattr(maps, "_get_amap_tool", fail_to_load_amap_tool)
    request = MapPreviewRequest.model_validate(
        {
            "destination": "南京",
            "days": [
                {
                    "label": "第1天",
                    "stops": [
                        {
                            "name": "南京博物院",
                            "city": "南京",
                            "lng": 118.848,
                            "lat": 32.043,
                        },
                        {
                            "name": "总统府",
                            "city": "南京",
                            "lng": 118.792,
                            "lat": 32.044,
                        },
                    ],
                }
            ],
        }
    )

    response = await maps.get_map_preview(
        request,
        user=SimpleNamespace(id="map-coordinate-test"),
    )

    assert response.status == "success"
    assert "已有坐标" in response.message
    assert response.points
    assert len(response.days) == 1
    assert response.days[0].points[0].name == "南京博物院"
    assert response.days[0].segments[0].confidence == "estimated_straight_line"


def test_fallback_points_from_day_groups_uses_real_day_coordinates():
    day_groups = [
        MapPreviewDay(
            key="visual-day-1",
            label="05-27 周三",
            points=[
                MapPoint(
                    kind="day",
                    label="05-27 周三",
                    name="宽窄巷子",
                    lng=104.056,
                    lat=30.674,
                    address="成都",
                ),
                MapPoint(
                    kind="day",
                    label="05-27 周三",
                    name="人民公园",
                    lng=104.059,
                    lat=30.659,
                    address="成都",
                ),
            ],
        )
    ]

    points = _fallback_points_from_day_groups(day_groups)

    assert [point.name for point in points] == ["宽窄巷子", "人民公园"]
    assert points[0].lng == 104.056
    assert points[0].label == "05-27 周三"
