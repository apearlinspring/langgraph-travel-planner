from copy import deepcopy
from datetime import date

from langchain.tools import ToolRuntime
from langgraph.types import Command

from app.api.v1.chat import (
    _journey_extra_info_from_tool_output,
    _latest_journey_data_from_conversation_extra,
    _merge_journey_draft_extra_info,
)
from app.core.middleware import _looks_like_visual_journey_request
from app.journey.enrichment import (
    MAX_POI_LOOKUPS,
    _refresh_flattened_sections,
    amap_place_candidate_from_payload,
    apply_estimated_route_to_segment,
    apply_route_payload_to_segment,
    estimate_missing_poi_coordinates_by_day,
    estimate_remaining_route_segments,
    merge_amap_candidate_into_poi,
    resolve_city_adcode,
    weather_summary_from_amap_payload,
)
from app.journey.visual_planner import (
    JOURNEY_PLAN_VERSION,
    build_visual_journey_plan,
    parse_relative_departure_date,
    validate_journey_plan,
)
from app.reports.builder import format_report_route_label
from app.tools.state_transition import generate_itinerary_tool


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )


def test_parse_relative_departure_date_next_wednesday_from_2026_05_18():
    parsed = parse_relative_departure_date(
        "下周三，7天，经典线吧",
        base_date=date(2026, 5, 18),
    )

    assert parsed == date(2026, 5, 27)


def test_tibet_visual_journey_contract_contains_classic_route_points():
    result = build_visual_journey_plan(
        destination="西藏",
        date_text="下周三，7天，经典线吧",
        style_query="经典线",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]
    ok, findings = validate_journey_plan(plan)

    assert ok, findings
    assert plan["version"] == JOURNEY_PLAN_VERSION
    assert plan["overview"]["start_date"] == "2026-05-27"
    assert plan["overview"]["end_date"] == "2026-06-02"
    assert "林芝进拉萨出" in plan["overview"]["route_label"]
    poi_names = {poi["name"] for poi in plan["pois"]}
    assert {"拉萨", "林芝", "巴松措", "雅鲁藏布大峡谷", "布达拉宫"} & poi_names
    assert {"巴松措", "布达拉宫", "羊卓雍措"}.issubset(poi_names)
    basum = next(poi for poi in plan["pois"] if poi["name"] == "巴松措")
    assert 93 < basum["lng"] < 95
    assert 29 < basum["lat"] < 31
    assert basum["map_query"] == "林芝 巴松措"
    assert len(plan["days"]) == 7
    alternative_names = {poi["name"] for poi in plan["alternative_pois"]}
    assert "罗布林卡" in alternative_names
    assert alternative_names.isdisjoint(poi_names)
    assert all(poi.get("is_alternative") is True for poi in plan["alternative_pois"])
    assert plan["source_summary"]["alternative_poi_count"] == len(plan["alternative_pois"])
    assert len(result["planning_trace"]) >= 6
    assert any(item["phase"] == "route" for item in result["planning_trace"])


def test_generic_visual_journey_uses_real_city_poi_seeds_for_map():
    result = build_visual_journey_plan(
        destination="成都",
        date_text="下周三，4天，经典线吧",
        style_query="经典线",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]
    ok, findings = validate_journey_plan(plan)
    poi_names = {poi["name"] for poi in plan["pois"]}
    poi_text = "\n".join(poi_names)
    positioned = [
        poi for poi in plan["pois"] if isinstance(poi.get("lng"), (int, float)) and isinstance(poi.get("lat"), (int, float))
    ]

    assert ok, findings
    assert {"成都东站", "宽窄巷子", "武侯祠", "锦里"}.issubset(poi_names)
    assert "核心景点" not in poi_text
    assert "特色街区" not in poi_text
    assert len(positioned) >= 6
    assert all(poi.get("map_query") for poi in plan["pois"])
    assert plan["alternative_pois"]
    assert all(poi.get("map_query") for poi in plan["alternative_pois"])


def test_visual_journey_includes_replacement_candidate_pool_for_hangzhou():
    result = build_visual_journey_plan(
        destination="杭州",
        date_text="下周三，3天，经典线吧",
        style_query="经典线",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]
    ok, findings = validate_journey_plan(plan)
    active_names = {poi["name"] for poi in plan["pois"]}
    alternative_names = {poi["name"] for poi in plan["alternative_pois"]}
    jiuxi = next(poi for poi in plan["alternative_pois"] if poi["name"] == "九溪烟树")

    assert ok, findings
    assert "九溪烟树" in alternative_names
    assert alternative_names.isdisjoint(active_names)
    assert jiuxi["map_query"] == "杭州 九溪烟树"
    assert isinstance(jiuxi["lng"], float)
    assert jiuxi["candidate_reason"].startswith("可用于替换")


def test_unknown_destination_visual_journey_uses_geocodable_real_map_queries():
    result = build_visual_journey_plan(
        destination="哈尔滨",
        date_text="下周三，3天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]
    poi_names = [poi["name"] for poi in plan["pois"]]

    assert "哈尔滨市中心" in poi_names
    assert "哈尔滨博物馆" in poi_names
    assert "哈尔滨公园" in poi_names
    assert "哈尔滨步行街" in poi_names
    assert len(set(poi_names)) == len(poi_names)
    assert all(poi.get("map_query", "").startswith("哈尔滨") for poi in plan["pois"])
    assert not any("核心景点" in name or "特色街区" in name for name in poi_names)
    alternative_names = {poi["name"] for poi in plan["alternative_pois"]}
    assert alternative_names >= {"哈尔滨城市公园", "哈尔滨老街夜市", "哈尔滨观景台"}
    assert alternative_names.isdisjoint(poi_names)


def test_live_poi_lookup_budget_covers_seven_day_primary_journey():
    result = build_visual_journey_plan(
        destination="贵阳",
        date_text="下周三，7天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]

    assert len(plan["pois"]) == 21
    assert MAX_POI_LOOKUPS >= len(plan["pois"])


def test_amap_place_candidate_can_enrich_unknown_destination_poi():
    result = build_visual_journey_plan(
        destination="哈尔滨",
        date_text="下周三，3天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    poi = result["journey_plan"]["days"][0]["pois"][0]
    payload = {
        "status": "1",
        "pois": [
            {
                "id": "B-test",
                "name": "哈尔滨市中心",
                "location": "126.6425,45.7560",
                "address": "黑龙江省哈尔滨市道里区",
                "cityname": "哈尔滨市",
                "type": "商务住宅;商务住宅相关",
                "photos": [{"url": "https://example.com/harbin.jpg"}],
            }
        ],
    }

    candidate = amap_place_candidate_from_payload(payload)
    merged = merge_amap_candidate_into_poi(poi, candidate)

    assert merged
    assert poi["map_verified"] is True
    assert poi["verification_status"] == "amap_place_text"
    assert poi["amap_poi_id"] == "B-test"
    assert poi["lng"] == 126.6425
    assert poi["lat"] == 45.7560
    assert poi["image_url"] == "https://example.com/harbin.jpg"


def test_generic_seed_poi_can_be_replaced_by_verified_amap_place_name():
    result = build_visual_journey_plan(
        destination="哈尔滨",
        date_text="下周三，3天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]
    poi = plan["days"][0]["pois"][0]
    segment = plan["days"][0]["segments"][0]
    payload = {
        "status": "1",
        "pois": [
            {
                "id": "B-central-street",
                "name": "中央大街",
                "location": "126.6177,45.7719",
                "address": "黑龙江省哈尔滨市道里区",
                "cityname": "哈尔滨市",
                "type": "风景名胜;风景名胜相关;旅游景点",
            }
        ],
    }

    candidate = amap_place_candidate_from_payload(payload)
    merged = merge_amap_candidate_into_poi(poi, candidate)
    _refresh_flattened_sections(plan)

    assert merged
    assert poi["original_seed_name"] == "哈尔滨市中心"
    assert poi["name"] == "中央大街"
    assert poi["map_query"] == "哈尔滨 中央大街"
    assert segment["from_name"] == "中央大街"
    assert "真实地点" in poi["verification_note"]


def test_amap_route_payload_updates_segment_metrics():
    segment = {
        "from_name": "宽窄巷子",
        "to_name": "人民公园",
        "distance_text": "待高德路线核验",
        "duration_text": "待高德路线核验",
        "confidence": "needs_live_route",
    }
    payload = {
        "status": "1",
        "route": {
            "paths": [
                {
                    "distance": "1800",
                    "duration": "900",
                }
            ]
        },
    }

    updated = apply_route_payload_to_segment(segment, payload)

    assert updated
    assert segment["distance_text"] == "1.8 公里"
    assert segment["duration_text"] == "15分钟"
    assert segment["confidence"] == "amap_driving"
    assert segment["source"] == "amap_direction_driving"


def test_estimated_route_payload_keeps_visible_distance_with_pending_note():
    segment = {
        "from_name": "哈尔滨博物馆",
        "to_name": "哈尔滨老街",
        "distance_text": "待高德路线核验",
        "duration_text": "待高德路线核验",
        "confidence": "needs_live_route",
    }

    updated = apply_estimated_route_to_segment(
        segment,
        {"lng": 126.64, "lat": 45.75},
        {"lng": 126.66, "lat": 45.76},
    )

    assert updated
    assert segment["distance_text"].startswith("约 ")
    assert segment["duration_text"].startswith("约 ")
    assert segment["confidence"] == "estimated_straight_line"
    assert "待高德二次核验" in segment["verification_note"]


def test_remaining_route_segments_are_estimated_from_existing_coordinates():
    result = build_visual_journey_plan(
        destination="成都",
        date_text="下周三，3天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    plan = result["journey_plan"]

    estimated = estimate_remaining_route_segments(plan)

    assert estimated >= 3
    assert any(
        segment.get("confidence") == "estimated_straight_line"
        for segment in plan["segments"]
    )
    assert all("待高德路线核验" not in segment["distance_text"] for segment in plan["segments"][:estimated])


def test_missing_same_day_poi_coordinates_use_verified_anchor_estimate():
    plan = {
        "days": [
            {
                "pois": [
                    {"id": "p1", "name": "已核验点", "lng": 126.64, "lat": 45.75},
                    {"id": "p2", "name": "待落点"},
                ],
                "segments": [
                    {
                        "from_poi_id": "p1",
                        "to_poi_id": "p2",
                        "distance_text": "待高德路线核验",
                        "duration_text": "待高德路线核验",
                        "confidence": "needs_live_route",
                    }
                ],
            }
        ]
    }

    coordinate_count = estimate_missing_poi_coordinates_by_day(plan)
    route_count = estimate_remaining_route_segments(plan)

    assert coordinate_count == 1
    assert route_count == 1
    assert plan["days"][0]["pois"][1]["coordinate_estimated"] is True
    assert plan["days"][0]["segments"][0]["confidence"] == "estimated_straight_line"


def test_weather_summary_marks_forecast_window_mismatch():
    payload = {
        "forecasts": [
            {
                "city": "哈尔滨市",
                "reporttime": "2026-05-18 20:00:00",
                "casts": [
                    {
                        "date": "2026-05-19",
                        "dayweather": "晴",
                        "nightweather": "多云",
                        "daytemp": "23",
                        "nighttemp": "12",
                        "daywind": "西南",
                        "daypower": "3",
                    }
                ],
            }
        ],
    }

    summary = weather_summary_from_amap_payload("哈尔滨", "2026-05-27", payload)

    assert summary["confidence"] == "amap_weather_reference"
    assert "超出可用预报窗口" in summary["summary"]
    assert resolve_city_adcode("哈尔滨") == "230100"


def test_journey_extra_info_from_command_output_is_persistable():
    result = build_visual_journey_plan(
        destination="西藏",
        date_text="下周三，7天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    command = Command(
        update={
            "journey_plan": result["journey_plan"],
            "planning_trace": result["planning_trace"],
        }
    )

    extra = _journey_extra_info_from_tool_output(command)

    assert extra["message_type"] == "journey_plan"
    assert extra["journey_data"]["version"] == JOURNEY_PLAN_VERSION
    assert extra["planning_trace"][0]["phase"] == "date"


def test_merge_journey_draft_extra_info_preserves_trace_and_marks_editor():
    result = build_visual_journey_plan(
        destination="西藏",
        date_text="下周三，7天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    existing = {
        "message_type": "journey_plan",
        "planning_trace": [{"phase": "search"}],
    }

    extra = _merge_journey_draft_extra_info(
        existing,
        result["journey_plan"],
        source="frontend_editor_test",
    )

    assert extra["message_type"] == "journey_plan"
    assert extra["planning_trace"] == [{"phase": "search"}]
    assert extra["journey_data"]["version"] == JOURNEY_PLAN_VERSION
    assert extra["journey_editor"]["source"] == "frontend_editor_test"
    assert isinstance(extra["journey_editor"]["saved_at"], int)


def test_latest_journey_data_from_conversation_extra_validates_contract():
    result = build_visual_journey_plan(
        destination="西藏",
        date_text="下周三，7天，经典线吧",
        base_date=date(2026, 5, 18),
    )

    extracted = _latest_journey_data_from_conversation_extra(
        {"latest_journey_data": result["journey_plan"]}
    )

    assert extracted["version"] == JOURNEY_PLAN_VERSION
    assert _latest_journey_data_from_conversation_extra(
        {"latest_journey_data": {"version": JOURNEY_PLAN_VERSION}}
    ) == {}


def test_generate_itinerary_tool_uses_edited_visual_journey_order():
    result = build_visual_journey_plan(
        destination="西藏",
        date_text="下周三，7天，经典线吧",
        base_date=date(2026, 5, 18),
    )
    edited_plan = deepcopy(result["journey_plan"])
    day_two_pois = list(reversed(edited_plan["days"][1]["pois"]))
    for index, poi in enumerate(day_two_pois, start=1):
        poi["order"] = index
    edited_plan["days"][1]["pois"] = day_two_pois
    edited_plan["pois"] = [
        poi
        for day in edited_plan["days"]
        for poi in day.get("pois", [])
    ]

    state = {
        "current_step": "itinerary_generation",
        "user_requirement": {
            "departure_city": "上海",
            "departure_date": "2026-05-27",
            "departure_date_confirmed": True,
            "destination": "西藏",
            "travel_days": 7,
            "adult_count": 2,
            "children_count": 0,
            "travel_styles": ["classic"],
            "budget_max": 18000,
        },
        "selected_destination": "西藏",
        "selected_transport": "flight",
        "selected_transport_option": {
            "title": "上海飞林芝，拉萨返程待核验",
            "price": 3200,
            "source": "user_or_rule",
        },
        "selected_accommodation_types": ["star_hotel"],
        "selected_accommodation_option": {
            "name": "拉萨/林芝交通便利区域酒店",
            "source": "user_or_rule",
        },
        "selected_food_types": ["local"],
        "journey_plan": edited_plan,
    }

    command = generate_itinerary_tool.invoke({"runtime": _build_runtime(state)})
    itinerary = command.update["itinerary"]

    assert command.update["current_step"] == "budget_summarization"
    assert len(itinerary) == 7
    assert itinerary[1]["route_points"][:2] == ["鲁朗林海", "巴松措"]
    assert "可视化旅程草案" in itinerary[1]["route_note"]
    assert "林芝进拉萨出" in format_report_route_label(state, state["user_requirement"])


def test_visual_journey_intent_is_narrower_than_structured_itinerary_record():
    assert _looks_like_visual_journey_request("下周三，7天，经典线吧")
    assert _looks_like_visual_journey_request("先给我地图路线和可视化行程")
    assert not _looks_like_visual_journey_request("请生成并记录3天2晚结构化行程，动线要合理。")
