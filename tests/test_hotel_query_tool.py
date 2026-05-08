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
    assert "北京王府井天伦王朝酒店" in result
    assert "实际检索地：Beijing" in result
    assert "酒店ID：43615" in result
    assert command.update["accommodation_options"][0]["hotel_id"] == 43615
    assert command.update["accommodation_options"][0]["price_per_night"] == 1740.0


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
