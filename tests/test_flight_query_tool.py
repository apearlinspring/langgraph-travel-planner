import pytest

from app.tools import flight_query


class FakeAviationTool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return self.result


def _mcp_text(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def test_resolve_city_iata_code_supports_chinese_city_and_existing_code():
    assert flight_query.resolve_city_iata_code("北京") == "BJS"
    assert flight_query.resolve_city_iata_code("上海市") == "SHA"
    assert flight_query.resolve_city_iata_code("sha") == "SHA"


def test_parse_prefixed_python_payload_extracts_variflight_data():
    payload = flight_query._parse_prefixed_python_payload(
        "Flight itineraries: {'code': 200, 'message': 'Success', 'data': '最低价:552元'}",
        "Flight itineraries:",
    )

    assert payload["code"] == 200
    assert payload["data"] == "最低价:552元"


@pytest.mark.asyncio
async def test_query_flight_options_formats_summary_and_low_price_candidates(monkeypatch):
    itinerary_tool = FakeAviationTool(
        _mcp_text(
            "Flight itineraries: {'code': 200, 'message': 'Success', "
            "'data': '查询到197条航班，最低价:552元，最短耗时:1h45m。"
            "其他推荐航班：公务舱 7650 元。'}"
        )
    )
    price_tool = FakeAviationTool(
        _mcp_text(
            "Flight prices: {'code': 200, 'message': 'Success', 'data': ["
            "{'flightno': 'MU5186', 'depaptcname': '北京首都', 'arraptcname': '上海虹桥', "
            "'flightdeptimeplandate': 1780047000, 'flightarrtimeplandate': 1780055700, "
            "'stopflag': 0, 'cabins': [{'classname': '经济舱', 'price': 552, 'seatnum': 9}]}, "
            "{'flightno': 'CA1835', 'depaptcname': '北京首都', 'arraptcname': '上海虹桥', "
            "'flightdeptimeplandate': 1780047600, 'flightarrtimeplandate': 1780056000, "
            "'stopflag': 0, 'cabins': [{'classname': '经济舱', 'price': 620, 'seatnum': 5}]}"
            "]}"
        )
    )

    async def fake_get_aviation_tool(tool_name: str):
        return {
            "searchFlightItineraries": itinerary_tool,
            "getFlightPriceByCities": price_tool,
        }.get(tool_name)

    monkeypatch.setattr(flight_query, "_get_aviation_tool", fake_get_aviation_tool)

    result = await flight_query.query_flight_options.ainvoke(
        {
            "origin_city": "北京",
            "destination_city": "上海",
            "departure_date": "2026-05-29",
            "max_results": 3,
        }
    )

    assert itinerary_tool.calls[0]["depCityCode"] == "BJS"
    assert itinerary_tool.calls[0]["arrCityCode"] == "SHA"
    assert price_tool.calls[0]["dep_city"] == "BJS"
    assert "查询到197条航班" in result
    assert "公务舱 7650" not in result
    assert "MU5186" in result
    assert "经济舱 约 552 元" in result
    assert "正式预订前需要再次核实" in result
