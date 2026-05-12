import asyncio
import os

from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("DASHSCOPE_API_KEY", "test-dashscope-key")
os.environ.setdefault("LANGSMITH_API_KEY", "test-langsmith-key")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")

from app.core.approval import ApprovalGovernanceManager
from app.core.checkpointer import CheckpointerManager
from app.core.observability import TurnObservation, get_turn_observability_snapshot
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


READY_CHECKPOINTER = {
    "status": "ready",
    "initialized": True,
    "pool_open": True,
}
MISSING_CHECKPOINTER = {
    "status": "uninitialized",
    "initialized": False,
    "pool_open": False,
}
READY_STORE = {
    "status": "ready",
    "initialized": True,
    "pool_open": True,
}
HEALTHY_MCP = {
    "status": "healthy",
    "healthy_servers": 2,
    "unavailable_servers": 0,
    "uninitialized_servers": 0,
    "tool_count": 4,
    "servers": {},
}
DEGRADED_MCP = {
    "status": "degraded",
    "healthy_servers": 1,
    "unavailable_servers": 1,
    "uninitialized_servers": 0,
    "tool_count": 2,
    "servers": {},
}
READY_SESSION_LOCK = {
    "status": "ready",
    "backend": "redis",
    "configured_backend": "auto",
    "app_env": "production",
    "redis_available": True,
    "fallback_to_local": True,
    "active_locks": 0,
    "ttl_seconds": 300,
    "reason": None,
}
DEGRADED_SESSION_LOCK = {
    "status": "degraded",
    "backend": "degraded_local",
    "configured_backend": "auto",
    "app_env": "development",
    "redis_available": False,
    "fallback_to_local": True,
    "active_locks": 0,
    "ttl_seconds": 300,
    "reason": "redis is unavailable",
}
UNAVAILABLE_SESSION_LOCK = {
    "status": "unavailable",
    "backend": "redis",
    "configured_backend": "auto",
    "app_env": "production",
    "redis_available": False,
    "fallback_to_local": True,
    "active_locks": 0,
    "ttl_seconds": 300,
    "reason": "redis is unavailable",
}
READY_APPROVAL_GOVERNANCE = {
    "status": "ready",
    "ready": True,
    "storage": "postgres",
    "persistent": True,
    "hitl_closed_loop": True,
}
NOT_READY_APPROVAL_GOVERNANCE = {
    "status": "not_ready",
    "ready": False,
    "storage": "postgres",
    "persistent": False,
    "hitl_closed_loop": False,
    "last_error": "database unavailable",
}


def mock_readiness_dependencies(
    monkeypatch,
    *,
    checkpointer=READY_CHECKPOINTER,
    store=READY_STORE,
    mcp=HEALTHY_MCP,
    session_lock=READY_SESSION_LOCK,
    approval_governance=READY_APPROVAL_GOVERNANCE,
) -> None:
    monkeypatch.setattr(
        CheckpointerManager,
        "get_status_snapshot",
        classmethod(lambda cls: checkpointer),
    )
    monkeypatch.setattr(
        StoreManager,
        "get_status_snapshot",
        classmethod(lambda cls: store),
    )
    monkeypatch.setattr(
        MCPClientManager,
        "get_status_snapshot",
        classmethod(lambda cls: mcp),
    )
    monkeypatch.setattr(
        app_main.session_lock_manager,
        "get_status_snapshot",
        lambda: session_lock,
    )
    monkeypatch.setattr(
        ApprovalGovernanceManager,
        "get_status_snapshot",
        classmethod(lambda cls: approval_governance),
    )


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


def test_build_readiness_payload_reports_ready_when_all_core_dependencies_are_ready(
    monkeypatch,
):
    mock_readiness_dependencies(monkeypatch)

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["services"]["checkpointer"]["initialized"] is True
    assert payload["services"]["store"]["initialized"] is True
    assert payload["services"]["session_lock"]["status"] == "ready"
    assert payload["services"]["approval_governance"]["status"] == "ready"


def test_build_readiness_payload_reports_degraded_when_mcp_is_degraded(monkeypatch):
    mock_readiness_dependencies(monkeypatch, mcp=DEGRADED_MCP)

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 200
    assert payload["status"] == "degraded"
    assert payload["services"]["mcp"]["status"] == "degraded"
    assert payload["services"]["session_lock"]["backend"] == "redis"
    assert payload["services"]["approval_governance"]["status"] == "ready"


def test_build_readiness_payload_reports_not_ready_when_core_is_missing(monkeypatch):
    mock_readiness_dependencies(monkeypatch, checkpointer=MISSING_CHECKPOINTER)

    payload, status_code = build_readiness_payload(startup_complete=False)

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["startup_complete"] is False
    assert "startup" in payload["blocking_items"]
    assert "checkpointer" in payload["blocking_items"]
    assert "session_lock" in payload["services"]
    assert "approval_governance" in payload["services"]


def test_lifespan_exposes_live_while_startup_dependencies_are_pending(monkeypatch):
    async def wait_forever(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(
        CheckpointerManager,
        "get_instance",
        classmethod(wait_forever),
    )
    monkeypatch.setattr(
        StoreManager,
        "get_instance",
        classmethod(wait_forever),
    )
    monkeypatch.setattr(
        ApprovalGovernanceManager,
        "verify_database",
        classmethod(wait_forever),
    )
    monkeypatch.setattr(MCPClientManager, "refresh_server_configs", classmethod(lambda cls: None))
    monkeypatch.setattr(MCPClientManager, "SERVER_CONFIGS", {})

    with TestClient(app_main.app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert "startup" in ready.json()["blocking_items"]


def test_build_readiness_payload_reports_degraded_local_session_lock(monkeypatch):
    mock_readiness_dependencies(monkeypatch, session_lock=DEGRADED_SESSION_LOCK)

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 200
    assert payload["status"] == "degraded"
    assert payload["services"]["session_lock"]["backend"] == "degraded_local"
    assert payload["services"]["approval_governance"]["ready"] is True


def test_build_readiness_payload_fails_when_session_lock_is_unavailable(monkeypatch):
    mock_readiness_dependencies(monkeypatch, session_lock=UNAVAILABLE_SESSION_LOCK)

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["services"]["session_lock"]["backend"] == "redis"
    assert payload["services"]["approval_governance"]["ready"] is True


def test_build_readiness_payload_requires_persistent_approval_governance(monkeypatch):
    mock_readiness_dependencies(
        monkeypatch,
        approval_governance=NOT_READY_APPROVAL_GOVERNANCE,
    )

    payload, status_code = build_readiness_payload(startup_complete=True)

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["services"]["session_lock"]["status"] == "ready"
    assert payload["services"]["approval_governance"]["status"] == "not_ready"
    assert payload["services"]["approval_governance"]["hitl_closed_loop"] is False


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


def test_turn_observability_records_degraded_fallback_without_readiness_dependency():
    observation = TurnObservation(
        conversation_id="conversation-1",
        user_id="user-1",
        user_message="查一下真实酒店",
    )

    observation.record_tool_start("query_hotel_options")
    observation.mark_fallback("hotel_mcp_unavailable")
    snapshot = observation.finish("completed")

    assert snapshot["metrics"]["degradation_status"] == "degraded"
    assert snapshot["metrics"]["fallback_count"] == 1
    assert snapshot["metadata"]["current_step"] == "unknown"
    assert get_turn_observability_snapshot(observation.turn_id)["turn_id"] == observation.turn_id
