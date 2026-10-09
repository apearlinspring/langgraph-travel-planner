from types import SimpleNamespace

import pytest

import app.api.v1.maps as maps
from app.api.v1.maps import (
    MapPoint,
    MapPreviewDay,
    MapPreviewResponse,
    MapPreviewRequest,
    MapPreviewSegmentRequest,
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
    assert segment.verification_status == "estimated"
    assert segment.selected_mode == "taxi"
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
    assert segment.source == "amap_direction_driving"
    assert segment.verification_status == "verified"
    assert segment.selected_mode == "taxi"
    assert segment.distance_text == "1.2 公里"
    assert segment.path == [
        {"lng": 120.1, "lat": 30.1},
        {"lng": 120.11, "lat": 30.105},
        {"lng": 120.12, "lat": 30.11},
    ]


@pytest.mark.asyncio
async def test_resolve_segment_marks_taxi_preference_verified_with_amap_route():
    class FakeDirectionTool:
        async def ainvoke(self, payload):
            return '{"paths":[{"distance":"1800","duration":"720","steps":[]}]}'

    left = MapPoint(
        kind="day",
        label="Day 1",
        name="宽窄巷子",
        lng=104.056,
        lat=30.674,
        address="宽窄巷子",
    )
    right = MapPoint(
        kind="day",
        label="Day 1",
        name="人民公园",
        lng=104.059,
        lat=30.659,
        address="人民公园",
    )
    preference = MapPreviewSegmentRequest(
        selected_mode="taxi",
        recommended_mode="walking",
        locked_by_user=True,
        alternatives=[
            {
                "mode": "taxi",
                "duration_text": "约10-20分钟",
                "cost_text": "费用待核验",
                "reason": "省体力",
            }
        ],
    )

    segment = await _resolve_segment(
        FakeDirectionTool(),
        day_key="day-1",
        day_label="Day 1",
        left=left,
        right=right,
        preference=preference,
    )

    assert segment.selected_mode == "taxi"
    assert segment.recommended_mode == "walking"
    assert segment.locked_by_user is True
    assert segment.verification_status == "verified"
    assert segment.verification_label == "已核验"
    assert segment.duration_text == "12分钟"
    assert segment.alternatives[0]["mode"] == "taxi"


@pytest.mark.asyncio
async def test_resolve_segment_keeps_transit_preference_pending_without_driving_metrics():
    class FakeDirectionTool:
        async def ainvoke(self, payload):
            raise AssertionError("transit preference must not call driving route")

    left = MapPoint(
        kind="day",
        label="Day 1",
        name="南京博物院",
        lng=118.848,
        lat=32.043,
        address="南京博物院",
    )
    right = MapPoint(
        kind="day",
        label="Day 1",
        name="总统府",
        lng=118.792,
        lat=32.044,
        address="总统府",
    )

    segment = await _resolve_segment(
        FakeDirectionTool(),
        day_key="day-1",
        day_label="Day 1",
        left=left,
        right=right,
        preference=MapPreviewSegmentRequest(selected_mode="transit", locked_by_user=True),
    )

    assert segment.selected_mode == "transit"
    assert segment.mode_label == "公交/地铁"
    assert segment.locked_by_user is True
    assert segment.confidence == "needs_live_route"
    assert segment.verification_status == "needs_live_route"
    assert segment.distance_text == "待高德路线核验"
    assert segment.duration_text == "待高德路线核验"


@pytest.mark.asyncio
async def test_resolve_segment_verifies_walking_preference_with_amap_tool():
    class FakeWalkingTool:
        async def ainvoke(self, payload):
            assert payload["origin"] == "120.1489,30.2596"
            assert payload["destination"] == "120.1482,30.2631"
            return (
                '{"route":{"paths":[{"distance":"1074","duration":"859","steps":['
                '{"polyline":"120.148900,30.259600;120.148200,30.263100"}]}]}}'
            )

    left = MapPoint(
        kind="day",
        label="Day 1",
        name="西湖",
        lng=120.1489,
        lat=30.2596,
        address="杭州",
    )
    right = MapPoint(
        kind="day",
        label="Day 1",
        name="断桥残雪",
        lng=120.1482,
        lat=30.2631,
        address="杭州",
    )

    segment = await _resolve_segment(
        {"walking": FakeWalkingTool()},
        day_key="day-1",
        day_label="Day 1",
        left=left,
        right=right,
        preference=MapPreviewSegmentRequest(selected_mode="walking", locked_by_user=True),
    )

    assert segment.selected_mode == "walking"
    assert segment.mode_label == "步行"
    assert segment.locked_by_user is True
    assert segment.confidence == "amap_walking"
    assert segment.source == "amap_direction_walking"
    assert segment.verification_status == "verified"
    assert segment.distance_text == "1.1 公里"
    assert segment.duration_text == "14分钟"
    assert segment.path == [
        {"lng": left.lng, "lat": left.lat},
        {"lng": right.lng, "lat": right.lat},
    ]


@pytest.mark.asyncio
async def test_resolve_segment_verifies_transit_preference_with_city_context():
    class FakeTransitTool:
        async def ainvoke(self, payload):
            assert payload == {
                "origin": "120.1489,30.2596",
                "destination": "119.9907,30.3927",
                "city": "杭州",
                "cityd": "杭州",
            }
            return (
                '{"distance":"19354","transits":[{"duration":"7397",'
                '"walking_distance":"3632","segments":[{}, {}, {}]}]}'
            )

    left = MapPoint(
        kind="day",
        label="Day 3",
        name="西湖",
        lng=120.1489,
        lat=30.2596,
        address="杭州",
    )
    right = MapPoint(
        kind="day",
        label="Day 3",
        name="良渚古城遗址公园",
        lng=119.9907,
        lat=30.3927,
        address="杭州",
    )

    segment = await _resolve_segment(
        {"transit": FakeTransitTool()},
        day_key="day-3",
        day_label="Day 3",
        left=left,
        right=right,
        preference=MapPreviewSegmentRequest(selected_mode="transit", locked_by_user=True),
        city="杭州",
        cityd="杭州",
    )

    assert segment.selected_mode == "transit"
    assert segment.mode_label == "公交/地铁"
    assert segment.confidence == "amap_transit"
    assert segment.source == "amap_direction_transit_integrated"
    assert segment.verification_status == "verified"
    assert segment.distance_text == "19.4 公里"
    assert segment.duration_text == "2小时3分钟"
    assert "班次" in segment.verification_note


@pytest.mark.asyncio
async def test_resolve_segment_keeps_transit_pending_without_city_context():
    class FakeTransitTool:
        async def ainvoke(self, payload):
            raise AssertionError("transit route requires city context first")

    left = MapPoint(
        kind="day",
        label="Day 1",
        name="西湖",
        lng=120.1489,
        lat=30.2596,
        address="杭州",
    )
    right = MapPoint(
        kind="day",
        label="Day 1",
        name="良渚古城遗址公园",
        lng=119.9907,
        lat=30.3927,
        address="杭州",
    )

    segment = await _resolve_segment(
        {"transit": FakeTransitTool()},
        day_key="day-1",
        day_label="Day 1",
        left=left,
        right=right,
        preference=MapPreviewSegmentRequest(selected_mode="transit"),
    )

    assert segment.selected_mode == "transit"
    assert segment.verification_status == "needs_live_route"
    assert segment.distance_text == "待高德路线核验"
    assert "城市信息不足" in segment.verification_note


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
    assert response.days[0].segments[0].verification_status == "estimated"


@pytest.mark.asyncio
async def test_map_preview_accepts_day_segment_preferences(monkeypatch):
    async def fail_to_load_amap_tool(name):
        raise TimeoutError()

    monkeypatch.setattr(maps, "_get_amap_tool", fail_to_load_amap_tool)
    request = MapPreviewRequest.model_validate(
        {
            "destination": "南京",
            "days": [
                {
                    "key": "visual-day-1",
                    "label": "第1天",
                    "stops": [
                        {
                            "id": "d1-p1",
                            "name": "南京博物院",
                            "city": "南京",
                            "lng": 118.848,
                            "lat": 32.043,
                        },
                        {
                            "id": "d1-p2",
                            "name": "总统府",
                            "city": "南京",
                            "lng": 118.792,
                            "lat": 32.044,
                        },
                    ],
                    "segments": [
                        {
                            "id": "d1-s1",
                            "selected_mode": "transit",
                            "recommended_mode": "taxi",
                            "locked_by_user": True,
                        }
                    ],
                }
            ],
        }
    )

    response = await maps.get_map_preview(
        request,
        user=SimpleNamespace(id="map-segment-preference-test"),
    )

    segment = response.days[0].segments[0]
    assert segment.selected_mode == "transit"
    assert segment.recommended_mode == "taxi"
    assert segment.locked_by_user is True
    assert segment.verification_status == "needs_live_route"
    assert "公交/地铁" in segment.verification_note


@pytest.mark.asyncio
async def test_map_preview_verifies_transit_segment_when_tool_and_city_exist(monkeypatch):
    maps._preview_cache.clear()

    class FakeGeoTool:
        async def ainvoke(self, payload):
            return '{"results":[{"location":"120.1489,30.2596","formatted_address":"杭州"}]}'

    class FakeTransitTool:
        async def ainvoke(self, payload):
            assert payload["city"] == "杭州"
            assert payload["cityd"] == "杭州"
            return '{"distance":"19354","transits":[{"duration":"7397","segments":[{},{}]}]}'

    async def fake_get_amap_tool(name):
        assert name == "maps_geo"
        return FakeGeoTool()

    async def fake_get_optional_amap_tool(name):
        if name == "maps_direction_transit_integrated":
            return FakeTransitTool()
        return None

    monkeypatch.setattr(maps, "_get_amap_tool", fake_get_amap_tool)
    monkeypatch.setattr(maps, "_get_optional_amap_tool", fake_get_optional_amap_tool)
    request = MapPreviewRequest.model_validate(
        {
            "destination": "杭州",
            "days": [
                {
                    "key": "visual-day-1",
                    "label": "第1天",
                    "stops": [
                        {
                            "id": "d1-p1",
                            "name": "西湖",
                            "city": "杭州",
                            "lng": 120.1489,
                            "lat": 30.2596,
                        },
                        {
                            "id": "d1-p2",
                            "name": "良渚古城遗址公园",
                            "city": "杭州",
                            "lng": 119.9907,
                            "lat": 30.3927,
                        },
                    ],
                    "segments": [
                        {
                            "id": "d1-s1",
                            "selected_mode": "transit",
                            "locked_by_user": True,
                        }
                    ],
                }
            ],
        }
    )

    response = await maps.get_map_preview(
        request,
        user=SimpleNamespace(id="map-transit-route-test"),
    )

    segment = response.days[0].segments[0]
    assert segment.selected_mode == "transit"
    assert segment.confidence == "amap_transit"
    assert segment.verification_status == "verified"
    assert segment.distance_text == "19.4 公里"
    assert segment.duration_text == "2小时3分钟"


@pytest.mark.asyncio
async def test_map_preview_preserves_sparse_days_and_connects_available_points(
    monkeypatch,
):
    async def fail_to_load_amap_tool(name):
        raise TimeoutError()

    monkeypatch.setattr(maps, "_get_amap_tool", fail_to_load_amap_tool)
    request = MapPreviewRequest.model_validate(
        {
            "destination": "杭州",
            "days": [
                {
                    "label": "Day 1",
                    "stops": [
                        {
                            "name": "西湖",
                            "city": "杭州",
                            "lng": 120.14,
                            "lat": 30.25,
                        },
                        {
                            "name": "灵隐寺",
                            "city": "杭州",
                            "lng": 120.10,
                            "lat": 30.24,
                        },
                    ],
                },
                {
                    "label": "Day 2",
                    "waypoints": ["待核验路线"],
                },
                {
                    "label": "Day 3",
                    "stops": [
                        {
                            "name": "西溪湿地",
                            "city": "杭州",
                            "lng": 120.06,
                            "lat": 30.27,
                        }
                    ],
                },
            ],
        }
    )

    response = await maps.get_map_preview(
        request,
        user=SimpleNamespace(id="map-sparse-day-test"),
    )

    assert [day.label for day in response.days] == ["Day 1", "Day 2", "Day 3"]
    assert response.days[0].segments
    assert response.days[1].points == []
    assert response.days[1].segments == []
    assert response.days[2].points[0].name == "西溪湿地"


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
