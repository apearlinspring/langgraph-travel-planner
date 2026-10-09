import pytest

from app.tools import train_query


class FakeRailwayTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return self.result


def _mcp_text(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def test_find_station_code_supports_city_mapping_payload():
    payload = {
        "北京": {"station_name": "北京", "station_code": "BJP"},
        "北京南": {"station_name": "北京南", "station_code": "VNP"},
    }

    assert train_query._find_station_code(payload, "北京") == "BJP"


def test_loose_payload_parser_handles_prefixed_python_text():
    payload = train_query._parse_loose_payload("Station codes: {'北京': {'code': 'BJP'}}")

    assert payload["北京"]["code"] == "BJP"


@pytest.mark.asyncio
async def test_query_train_options_resolves_codes_and_queries_direct(monkeypatch):
    city_tool = FakeRailwayTool(
        "get-station-code-of-citys",
        _mcp_text("{'北京': {'station_code': 'BJP'}, '上海': {'station_code': 'SHH'}}"),
    )
    tickets_tool = FakeRailwayTool(
        "get-tickets",
        _mcp_text("G1 北京南 07:00 -> 上海虹桥 11:29，二等座有票 553元"),
    )

    async def fake_get_railway_tool(tool_name: str):
        return {
            "get-station-code-of-citys": city_tool,
            "get-tickets": tickets_tool,
            "get-interline-tickets": None,
        }.get(tool_name)

    monkeypatch.setattr(train_query, "_get_railway_tool", fake_get_railway_tool)

    result = await train_query.query_train_options.ainvoke(
        {
            "origin_city": "北京",
            "destination_city": "上海",
            "departure_date": "2026-05-29",
            "max_results": 3,
        }
    )

    assert city_tool.calls[0]["citys"] == "北京"
    assert city_tool.calls[1]["citys"] == "上海"
    assert tickets_tool.calls[0]["fromStation"] == "BJP"
    assert tickets_tool.calls[0]["toStation"] == "SHH"
    assert "直达车次候选" in result
    assert "G1 北京南" in result
    assert "正式购票前需要再次核实" in result


@pytest.mark.asyncio
async def test_query_train_options_uses_transfer_when_direct_empty(monkeypatch):
    city_tool = FakeRailwayTool(
        "get-station-code-of-citys",
        _mcp_text("{'北京': {'station_code': 'BJP'}, '大理': {'station_code': 'DKM'}}"),
    )
    tickets_tool = FakeRailwayTool("get-tickets", _mcp_text("未查询到直达车次"))
    transfer_tool = FakeRailwayTool(
        "get-interline-tickets",
        _mcp_text("北京 -> 昆明 -> 大理，换乘时间 1小时20分"),
    )

    async def fake_get_railway_tool(tool_name: str):
        return {
            "get-station-code-of-citys": city_tool,
            "get-tickets": tickets_tool,
            "get-interline-tickets": transfer_tool,
        }.get(tool_name)

    monkeypatch.setattr(train_query, "_get_railway_tool", fake_get_railway_tool)

    result = await train_query.query_train_options.ainvoke(
        {
            "origin_city": "北京",
            "destination_city": "大理",
            "departure_date": "2026-05-29",
            "max_results": 3,
        }
    )

    assert transfer_tool.calls[0]["fromStation"] == "BJP"
    assert transfer_tool.calls[0]["toStation"] == "DKM"
    assert "中转/接续候选" in result
    assert "昆明" in result
