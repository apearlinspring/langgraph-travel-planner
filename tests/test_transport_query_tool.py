import pytest
from types import SimpleNamespace

from app.tools import transport_query


class FakeCoordinator:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, payload, config=None):
        self.calls.append(payload)
        self.config = config
        return {"messages": [SimpleNamespace(content="ok")]}


@pytest.mark.asyncio
async def test_query_transport_options_treats_transport_type_as_preference(monkeypatch):
    coordinator = FakeCoordinator()

    async def fake_create_transport_coordinator():
        return coordinator

    monkeypatch.setattr(
        transport_query,
        "create_transport_coordinator",
        fake_create_transport_coordinator,
    )

    command = await transport_query.query_transport_options.ainvoke(
        {
            "origin_city": "西安",
            "destination_city": "眉县",
            "departure_date": "2026-05-16",
            "transport_type": "train",
        }
    )

    result = command.update["messages"][0].content
    assert result == "ok"
    assert coordinator.config["recursion_limit"] > 25
    assert command.update["tool_audit_events"][0]["status"] == "success"
    assert command.update["tool_audit_events"][0]["evidence_type"] == "live_transport_query"
    content = coordinator.calls[0]["messages"][0]["content"]
    assert "更偏向 高铁" in content
    assert "不要因为我提到了 高铁 就默认排除其他交通方式" in content


@pytest.mark.asyncio
async def test_query_transport_options_without_preference_requests_general_recommendation(monkeypatch):
    coordinator = FakeCoordinator()

    async def fake_create_transport_coordinator():
        return coordinator

    monkeypatch.setattr(
        transport_query,
        "create_transport_coordinator",
        fake_create_transport_coordinator,
    )

    command = await transport_query.query_transport_options.ainvoke(
        {
            "origin_city": "西安",
            "destination_city": "眉县",
            "departure_date": "2026-05-16",
        }
    )

    assert command.update["tool_audit_events"][0]["status"] == "success"
    content = coordinator.calls[0]["messages"][0]["content"]
    assert "推荐合适的交通方式" in content
    assert "更偏向" not in content


@pytest.mark.asyncio
async def test_query_transport_options_skips_invalid_args_without_calling_coordinator(monkeypatch):
    async def fail_create_transport_coordinator():
        raise AssertionError("coordinator should not be created")

    monkeypatch.setattr(
        transport_query,
        "create_transport_coordinator",
        fail_create_transport_coordinator,
    )

    command = await transport_query.query_transport_options.ainvoke(
        {
            "origin_city": "出发地",
            "destination_city": "目的地",
            "departure_date": "日期",
            "transport_type": "boat",
        }
    )

    result = command.update["messages"][0].content
    event = command.update["tool_audit_events"][0]
    assert "交通真实查询参数不完整" in result
    assert event["status"] == "skipped"
    assert event["error_type"] == "invalid_transport_query_args"
