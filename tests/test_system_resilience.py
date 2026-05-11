import asyncio
import os

import pytest

os.environ.setdefault("DASHSCOPE_API_KEY", "test-dashscope-key")
os.environ.setdefault("LANGSMITH_API_KEY", "test-langsmith-key")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")

from app.core.checkpointer import CheckpointerManager
from app.core.session_lock import SessionLockBusy, SessionLockManager
from app.core.store import StoreManager
import app.main as app_main
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


class FakeUnavailableRedis:
    def ping(self):
        raise ConnectionError("redis is unavailable")

    async def set(self, *args, **kwargs):
        raise ConnectionError("redis is unavailable")


class FakeAvailableRedis:
    def ping(self):
        return True

    async def set(self, *args, **kwargs):
        return True


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
    tools = await manager.get_tools(
        servers=["weather"],
        timeout_overrides={"weather": 0.01},
    )
    snapshot = MCPClientManager.get_status_snapshot()

    assert tools == []
    assert snapshot["status"] == "unavailable"
    assert snapshot["servers"]["weather"]["status"] == "unavailable"


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
    monkeypatch.setattr(
        app_main.session_lock_manager,
        "get_status_snapshot",
        lambda: {
            "status": "ready",
            "backend": "redis",
            "configured_backend": "auto",
            "app_env": "production",
            "redis_available": True,
            "fallback_to_local": True,
            "active_locks": 0,
            "ttl_seconds": 300,
            "reason": None,
        },
    )

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 200
    assert payload["status"] == "degraded"
    assert payload["services"]["mcp"]["status"] == "degraded"
    assert payload["services"]["session_lock"]["backend"] == "redis"


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
    monkeypatch.setattr(
        app_main.session_lock_manager,
        "get_status_snapshot",
        lambda: {
            "status": "ready",
            "backend": "local",
            "configured_backend": "local",
            "app_env": "development",
            "redis_available": None,
            "fallback_to_local": True,
            "active_locks": 0,
            "ttl_seconds": 300,
            "reason": None,
        },
    )

    payload, status_code = build_readiness_payload(startup_complete=False)

    assert status_code == 503
    assert payload["status"] == "not_ready"


def test_build_readiness_payload_reports_degraded_local_session_lock(monkeypatch):
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
                "status": "healthy",
                "healthy_servers": 2,
                "unavailable_servers": 0,
                "uninitialized_servers": 0,
                "tool_count": 4,
                "servers": {},
            }
        ),
    )
    monkeypatch.setattr(
        app_main.session_lock_manager,
        "get_status_snapshot",
        lambda: {
            "status": "degraded",
            "backend": "degraded_local",
            "configured_backend": "auto",
            "app_env": "development",
            "redis_available": False,
            "fallback_to_local": True,
            "active_locks": 0,
            "ttl_seconds": 300,
            "reason": "redis is unavailable",
        },
    )

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 200
    assert payload["status"] == "degraded"
    assert payload["services"]["session_lock"]["backend"] == "degraded_local"


def test_build_readiness_payload_fails_when_session_lock_is_unavailable(monkeypatch):
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
                "status": "healthy",
                "healthy_servers": 2,
                "unavailable_servers": 0,
                "uninitialized_servers": 0,
                "tool_count": 4,
                "servers": {},
            }
        ),
    )
    monkeypatch.setattr(
        app_main.session_lock_manager,
        "get_status_snapshot",
        lambda: {
            "status": "unavailable",
            "backend": "redis",
            "configured_backend": "auto",
            "app_env": "production",
            "redis_available": False,
            "fallback_to_local": True,
            "active_locks": 0,
            "ttl_seconds": 300,
            "reason": "redis is unavailable",
        },
    )

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["services"]["session_lock"]["backend"] == "redis"


@pytest.mark.asyncio
async def test_session_lock_manager_degrades_to_local_when_redis_is_unavailable():
    manager = SessionLockManager(backend="auto", redis_client=FakeUnavailableRedis())
    lease = await manager.acquire("conversation-1")

    try:
        assert lease.snapshot.backend == "local"
        with pytest.raises(SessionLockBusy):
            await manager.acquire("conversation-1")
    finally:
        await lease.release()

    assert manager.is_locked("conversation-1") is False


@pytest.mark.asyncio
async def test_session_lock_manager_does_not_degrade_for_production_auto_backend():
    manager = SessionLockManager(
        backend="auto",
        redis_client=FakeUnavailableRedis(),
        app_env="production",
    )

    with pytest.raises(ConnectionError):
        await manager.acquire("conversation-1")


@pytest.mark.asyncio
async def test_session_lock_manager_does_not_degrade_for_explicit_redis_backend():
    manager = SessionLockManager(
        backend="redis",
        redis_client=FakeUnavailableRedis(),
        app_env="development",
    )

    with pytest.raises(ConnectionError):
        await manager.acquire("conversation-1")


def test_session_lock_status_degrades_only_for_development_auto_backend():
    manager = SessionLockManager(
        backend="auto",
        redis_client=FakeUnavailableRedis(),
        app_env="development",
    )

    snapshot = manager.get_status_snapshot()

    assert snapshot["status"] == "degraded"
    assert snapshot["backend"] == "degraded_local"


def test_session_lock_status_fails_for_production_auto_backend():
    manager = SessionLockManager(
        backend="auto",
        redis_client=FakeUnavailableRedis(),
        app_env="production",
    )

    snapshot = manager.get_status_snapshot()

    assert snapshot["status"] == "unavailable"
    assert snapshot["backend"] == "redis"


def test_session_lock_status_fails_for_explicit_redis_backend():
    manager = SessionLockManager(
        backend="redis",
        redis_client=FakeUnavailableRedis(),
        app_env="development",
    )

    snapshot = manager.get_status_snapshot()

    assert snapshot["status"] == "unavailable"
    assert snapshot["backend"] == "redis"


def test_session_lock_status_reports_redis_when_available():
    manager = SessionLockManager(
        backend="auto",
        redis_client=FakeAvailableRedis(),
        app_env="production",
    )

    snapshot = manager.get_status_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["backend"] == "redis"
