import asyncio

import pytest

from app.core.checkpointer import CheckpointerManager
from app.core.store import StoreManager
from app.main import build_readiness_payload
from app.mcp_core.client import MCPClientManager


class DummyTool:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeMultiServerMCPClient:
    def __init__(self, configs):
        self.server_name = next(iter(configs))

    async def get_tools(self):
        if self.server_name == "weather":
            return [DummyTool("get_weather_forecast")]
        if self.server_name == "search":
            raise RuntimeError("search server is down")
        return []


class FakeRetryThenRecoverMCPClient:
    attempts: dict[str, int] = {}

    def __init__(self, configs):
        self.server_name = next(iter(configs))

    async def get_tools(self):
        current_attempt = self.attempts.get(self.server_name, 0) + 1
        self.attempts[self.server_name] = current_attempt
        if self.server_name == "weather" and current_attempt == 1:
            raise RuntimeError("transient startup failure")
        return [DummyTool(f"{self.server_name}-tool")]


class FakeHangingMCPClient:
    def __init__(self, configs):
        self.server_name = next(iter(configs))

    async def get_tools(self):
        await asyncio.sleep(3600)
        return []


@pytest.fixture(autouse=True)
def reset_mcp_singleton():
    MCPClientManager.reset_instance()
    yield
    MCPClientManager.reset_instance()


@pytest.mark.asyncio
async def test_mcp_manager_keeps_healthy_servers_when_one_server_fails(monkeypatch):
    monkeypatch.setattr(
        "app.mcp_core.client.MultiServerMCPClient",
        FakeMultiServerMCPClient,
    )

    manager = await MCPClientManager.get_instance()
    tools = await manager.get_tools(servers=["weather", "search"])
    snapshot = MCPClientManager.get_status_snapshot()

    assert [tool.name for tool in tools] == ["get_weather_forecast"]
    assert snapshot["status"] == "degraded"
    assert snapshot["healthy_servers"] == 1
    assert snapshot["unavailable_servers"] == 1
    assert snapshot["servers"]["weather"]["status"] == "healthy"
    assert snapshot["servers"]["search"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_mcp_manager_retries_transient_server_failure(monkeypatch):
    FakeRetryThenRecoverMCPClient.attempts = {}
    monkeypatch.setattr(
        "app.mcp_core.client.MultiServerMCPClient",
        FakeRetryThenRecoverMCPClient,
    )
    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.mcp_core.client.asyncio.sleep", fake_sleep)

    manager = await MCPClientManager.get_instance()
    tools = await manager.get_tools(servers=["weather"])
    snapshot = MCPClientManager.get_status_snapshot()

    assert [tool.name for tool in tools] == ["weather-tool"]
    assert FakeRetryThenRecoverMCPClient.attempts["weather"] == 2
    assert snapshot["servers"]["weather"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_optional_server_times_out_without_blocking_other_servers(monkeypatch):
    monkeypatch.setattr(
        "app.mcp_core.client.MultiServerMCPClient",
        FakeHangingMCPClient,
    )
    async def fake_wait_for(awaitable, timeout):
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise asyncio.TimeoutError(f"timed out after {timeout}")

    monkeypatch.setattr("app.mcp_core.client.asyncio.wait_for", fake_wait_for)

    manager = await MCPClientManager.get_instance()
    tools = await manager.get_tools(servers=["aigohotel-mcp"])
    snapshot = MCPClientManager.get_status_snapshot()

    assert tools == []
    assert snapshot["status"] == "unavailable"
    assert snapshot["servers"]["aigohotel-mcp"]["status"] == "unavailable"


def test_build_readiness_payload_reports_degraded_when_mcp_is_degraded(monkeypatch):
    monkeypatch.setattr(
        CheckpointerManager,
        "get_status_snapshot",
        classmethod(lambda cls: {"status": "ready", "initialized": True, "pool_open": True}),
    )
    monkeypatch.setattr(
        StoreManager,
        "get_status_snapshot",
        classmethod(lambda cls: {"status": "ready", "initialized": True, "pool_open": True}),
    )
    monkeypatch.setattr(
        MCPClientManager,
        "get_status_snapshot",
        classmethod(
            lambda cls: {
                "status": "degraded",
                "healthy_servers": 1,
                "unavailable_servers": 1,
                "uninitialized_servers": 0,
                "tool_count": 2,
                "servers": {},
            }
        ),
    )

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 200
    assert payload["status"] == "degraded"
    assert payload["services"]["mcp"]["status"] == "degraded"


def test_build_readiness_payload_reports_not_ready_when_core_is_missing(monkeypatch):
    monkeypatch.setattr(
        CheckpointerManager,
        "get_status_snapshot",
        classmethod(
            lambda cls: {"status": "uninitialized", "initialized": False, "pool_open": False}
        ),
    )
    monkeypatch.setattr(
        StoreManager,
        "get_status_snapshot",
        classmethod(lambda cls: {"status": "ready", "initialized": True, "pool_open": True}),
    )
    monkeypatch.setattr(
        MCPClientManager,
        "get_status_snapshot",
        classmethod(
            lambda cls: {
                "status": "healthy",
                "healthy_servers": 2,
                "unavailable_servers": 0,
                "uninitialized_servers": 0,
                "tool_count": 4,
                "servers": {},
            }
        ),
    )

    payload, status_code = build_readiness_payload(startup_complete=False)

    assert status_code == 503
    assert payload["status"] == "not_ready"
