import pytest

from app.api.v1.maps import (
    MapPoint,
    MapPreviewDay,
    MapPreviewRequest,
    MapPreviewStopRequest,
    _fallback_points_from_day_groups,
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
