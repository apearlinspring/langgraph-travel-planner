import json

import pytest
from langchain.tools import ToolRuntime

from app.tools import hotel_query


def _mcp_result(payload: dict) -> list[dict]:
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


class FakeHotelSearchTool:
    def __init__(self):
        self.calls: list[str] = []
        self.payloads: list[dict] = []

    async def ainvoke(self, payload: dict):
        self.calls.append(payload["place"])
        self.payloads.append(payload)
        if payload["place"] == "北京":
            return _mcp_result({"message": "酒店搜索成功", "hotelInformationList": []})

        return _mcp_result(
            {
                "message": "酒店搜索成功",
                "hotelInformationList": [
                    {
                        "hotelId": 43615,
                        "name": "北京王府井天伦王朝酒店",
                        "address": "王府井大街50号",
                        "starRating": 5.0,
                        "distanceInMeters": 2669,
                        "price": {
                            "lowestPrice": 1740.0,
                            "currency": "CNY",
                        },
                        "tags": ["亲子酒店", "提供家庭房", "儿童玩乐设施"],
                    }
                ],
            }
        )


class PreferenceAwareFakeHotelSearchTool:
    def __init__(self):
        self.calls: list[str] = []
        self.payloads: list[dict] = []

    async def ainvoke(self, payload: dict):
        self.calls.append(payload["place"])
        self.payloads.append(payload)
        return _mcp_result(
            {
                "message": "酒店搜索成功",
                "hotelInformationList": [
                    {
                        "hotelId": 1001,
                        "name": "长沙湘江景观酒店",
                        "address": "长沙市湘江中路",
                        "starRating": 4.8,
                        "distanceInMeters": 800,
                        "price": {"lowestPrice": 680.0, "currency": "CNY"},
                        "tags": ["江景房", "景观房"],
                    }
                ],
            }
        )


class HangingHotelSearchTool:
    def __init__(self):
        self.calls: list[str] = []

    async def ainvoke(self, payload: dict):
        self.calls.append(payload["place"])
        raise TimeoutError("upstream hung")


def test_expand_place_candidates_adds_english_alias_for_common_city():
    assert hotel_query._expand_place_candidates("北京市") == ["北京市", "北京", "Beijing"]


def test_expand_place_candidates_adds_scenic_area_fallbacks():
    assert hotel_query._expand_place_candidates("\u56db\u59d1\u5a18\u5c71\u9547") == [
        "\u56db\u59d1\u5a18\u5c71\u9547",
        "\u56db\u59d1\u5a18\u5c71",
        "\u65e5\u9686\u9547",
        "\u56db\u59d1\u5a18\u5c71\u666f\u533a",
    ]


def test_expand_place_candidates_adds_city_fallback_for_specific_area():
    assert hotel_query._expand_place_candidates("\u957f\u6c99\u6e58\u6c5f\u4e2d\u8def") == [
        "\u957f\u6c99\u6e58\u6c5f\u4e2d\u8def",
        "\u957f\u6c99",
        "Changsha",
    ]


def test_infer_preferred_tags_matches_water_view_fuzzy_words():
    tags = hotel_query._infer_preferred_tags("\u60f3\u8981\u6c5f\u666f\u7684\u623f", 0)

    assert "\u6c5f\u666f\u623f" in tags
    assert "\u666f\u89c2\u623f" in tags


def test_split_destination_keeps_room_view_in_preferences():
    destination, preferences = hotel_query._split_destination_and_preferences(
        "长沙湘江中路附近，想住江景房/江景的房",
        "",
        "长沙",
    )

    assert destination == "长沙湘江中路"
    assert "江景房/江景的房" in preferences


def test_split_destination_handles_family_and_subway_preferences():
    destination, preferences = hotel_query._split_destination_and_preferences(
        "北京亲子游，想住安静、交通方便、靠地铁的酒店",
        "",
        "北京",
    )

    assert destination == "北京"
    assert "亲子游" in preferences
    assert "靠地铁" in preferences


def test_build_place_candidates_infers_detailed_address():
    candidates = hotel_query._build_place_candidates("长沙湘江中路", "城市")

    assert candidates[0] == {"place": "长沙湘江中路", "place_type": "详细地址"}
    assert {"place": "长沙", "place_type": "城市"} in candidates


def test_split_destination_keeps_nearby_specific_location_as_destination():
    destination, preferences = hotel_query._split_destination_and_preferences(
        "长沙湘江中路附近",
        "想住江景房/江景的房",
        "长沙",
    )

    assert destination == "长沙湘江中路"
    assert preferences == "想住江景房/江景的房"


def test_hotel_matches_destination_filters_out_wrong_city_result():
    hotel = {
        "name": "Grand Mirage Dhanbad",
        "address": "Dhansar Chowk Near MG Motor Showroom",
        "description": "Dhanbad city center hotel",
    }
    assert not hotel_query._hotel_matches_destination(hotel, "\u4e39\u5df4")


def test_hotel_matches_destination_supports_case_insensitive_english_alias():
    hotel = {
        "name": "beijing wangfujing hotel",
        "address": "wangfujing street",
    }
    assert hotel_query._hotel_matches_destination(hotel, "北京")


@pytest.mark.asyncio
async def test_query_hotel_options_falls_back_to_english_alias(monkeypatch):
    fake_tool = FakeHotelSearchTool()

    async def fake_get_hotel_tool(tool_name: str):
        assert tool_name == "searchHotels"
        return fake_tool

    monkeypatch.setattr(hotel_query, "_get_hotel_tool", fake_get_hotel_tool)

    command = await hotel_query.query_hotel_options.ainvoke(
        {
            "destination": "北京",
            "check_in_date": "2026-06-01",
            "stay_nights": 2,
            "adult_count": 2,
            "children_count": 1,
            "budget_level": "comfort",
            "preferences": "亲子友好、交通方便、尽量安静",
        }
    )

    result = command.update["messages"][0].content
    assert fake_tool.calls == ["北京", "Beijing"]
    assert fake_tool.payloads[0]["placeType"] == "城市"
    assert "北京王府井天伦王朝酒店" in result
    assert "实际检索地：Beijing" in result
    assert "酒店ID：43615" in result
    assert command.update["accommodation_options"][0]["hotel_id"] == 43615
    assert command.update["accommodation_options"][0]["price_per_night"] == 1740.0
    audit_event = command.update["tool_audit_events"][0]
    assert audit_event["name"] == "query_hotel_options"
    assert audit_event["status"] == "success"
    assert audit_event["evidence_type"] == "live_hotel_search"


@pytest.mark.asyncio
async def test_query_hotel_options_uses_state_when_llm_passes_placeholders(monkeypatch):
    fake_tool = FakeHotelSearchTool()

    async def fake_get_hotel_tool(tool_name: str):
        assert tool_name == "searchHotels"
        return fake_tool

    monkeypatch.setattr(hotel_query, "_get_hotel_tool", fake_get_hotel_tool)
    runtime = ToolRuntime(
        state={
            "selected_destination": "北京",
            "user_requirement": {
                "departure_date": "2026-06-01",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 1,
                "budget_level": "comfort",
                "special_needs": "亲子友好，尽量安静",
            },
        },
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )

    command = await hotel_query.query_hotel_options.ainvoke(
        {
            "destination": "目的地",
            "check_in_date": "入住日期",
            "stay_nights": 3,
            "adult_count": 0,
            "children_count": -1,
            "budget_level": "预算等级",
            "preferences": "",
            "runtime": runtime,
        }
    )

    assert fake_tool.calls == ["北京", "Beijing"]
    payload = fake_tool.payloads[0]
    assert payload["checkInParam"]["checkInDate"] == "2026-06-01"
    assert payload["checkInParam"]["stayNights"] == 2
    assert payload["checkInParam"]["adultCount"] == 2
    assert "亲子友好" in payload["originQuery"]
    assert "北京王府井天伦王朝酒店" in command.update["messages"][0].content


@pytest.mark.asyncio
async def test_query_hotel_options_treats_room_view_as_preference_not_destination(monkeypatch):
    fake_tool = PreferenceAwareFakeHotelSearchTool()

    async def fake_get_hotel_tool(tool_name: str):
        assert tool_name == "searchHotels"
        return fake_tool

    monkeypatch.setattr(hotel_query, "_get_hotel_tool", fake_get_hotel_tool)
    runtime = ToolRuntime(
        state={
            "selected_destination": "长沙",
            "user_requirement": {
                "departure_date": "2026-06-01",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_level": "comfort",
            },
        },
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )

    command = await hotel_query.query_hotel_options.ainvoke(
        {
            "destination": "江景房",
            "check_in_date": "入住日期",
            "stay_nights": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_level": "comfort",
            "preferences": "",
            "runtime": runtime,
        }
    )

    assert fake_tool.calls[0] == "长沙"
    assert "江景房" in fake_tool.payloads[0]["originQuery"]
    assert "江景房" in fake_tool.payloads[0]["hotelTags"]["preferredTags"]
    assert "长沙湘江景观酒店" in command.update["messages"][0].content


@pytest.mark.asyncio
async def test_query_hotel_options_splits_specific_area_and_preferences(monkeypatch):
    fake_tool = PreferenceAwareFakeHotelSearchTool()

    async def fake_get_hotel_tool(tool_name: str):
        assert tool_name == "searchHotels"
        return fake_tool

    monkeypatch.setattr(hotel_query, "_get_hotel_tool", fake_get_hotel_tool)

    command = await hotel_query.query_hotel_options.ainvoke(
        {
            "destination": "长沙湘江中路附近，想住江景房/江景的房",
            "check_in_date": "2026-06-01",
            "stay_nights": 2,
            "adult_count": 2,
            "children_count": 0,
            "budget_level": "comfort",
            "preferences": "",
        }
    )

    payload = fake_tool.payloads[0]
    assert payload["place"] == "长沙湘江中路"
    assert payload["placeType"] == "详细地址"
    assert payload["filterOptions"]["distanceInMeter"] == 8000
    assert "江景房/江景的房" in payload["originQuery"]
    assert "长沙湘江景观酒店" in command.update["messages"][0].content


@pytest.mark.asyncio
async def test_query_hotel_options_times_out_with_honest_fallback(monkeypatch):
    fake_tool = HangingHotelSearchTool()

    async def fake_get_hotel_tool(tool_name: str):
        assert tool_name == "searchHotels"
        return fake_tool

    monkeypatch.setattr(hotel_query, "_get_hotel_tool", fake_get_hotel_tool)
    monkeypatch.setattr(hotel_query, "HOTEL_SEARCH_CALL_TIMEOUT_SECONDS", 0.01)

    command = await hotel_query.query_hotel_options.ainvoke(
        {
            "destination": "南京",
            "check_in_date": "2026-06-01",
            "stay_nights": 2,
            "adult_count": 2,
            "children_count": 0,
            "budget_level": "comfort",
            "preferences": "安静、靠地铁",
        }
    )

    result = command.update["messages"][0].content
    assert fake_tool.calls == ["南京", "Nanjing", "南京"]
    assert "暂时没有查到符合条件的酒店" in result
    assert "酒店搜索上游响应超时" in result
    assert "accommodation_options" not in command.update
    audit_event = command.update["tool_audit_events"][0]
    assert audit_event["status"] == "timeout"
    assert audit_event["error_type"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_query_hotel_options_skips_invalid_args_before_mcp(monkeypatch):
    async def fail_get_hotel_tool(tool_name: str):
        raise AssertionError("MCP should not be touched for invalid args")

    monkeypatch.setattr(hotel_query, "_get_hotel_tool", fail_get_hotel_tool)

    command = await hotel_query.query_hotel_options.ainvoke(
        {
            "destination": "目的地",
            "check_in_date": "入住日期",
            "stay_nights": 0,
            "adult_count": 0,
            "children_count": -1,
            "budget_level": "vip",
            "preferences": "",
        }
    )

    result = command.update["messages"][0].content
    audit_event = command.update["tool_audit_events"][0]
    assert "酒店真实查询参数不完整" in result
    assert audit_event["status"] == "skipped"
    assert audit_event["error_type"] == "invalid_hotel_query_args"
