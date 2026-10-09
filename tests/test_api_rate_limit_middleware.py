import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import ApiRateLimitMiddleware, ApiRateLimiter


def _client(*, enabled=True, limiter=None, limit=2, protected_prefixes=("/api/v1",), exempt_paths=()):
    app = FastAPI()
    app.add_middleware(
        ApiRateLimitMiddleware,
        enabled=enabled,
        requests_per_window=limit,
        window_seconds=60,
        backend="local",
        redis_url="redis://localhost:6379/0",
        protected_prefixes=protected_prefixes,
        exempt_paths=exempt_paths,
        local_fallback=False,
        limiter=limiter,
    )

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/api/v1/exempt/ping")
    async def exempt_ping():
        return {"ok": True}

    @app.get("/api/v1/mock-checkout/ORDER-ABC12345/status")
    async def mock_checkout_status():
        return {
            "status": "demo_only",
            "real_payment": False,
            "real_booking": False,
            "inventory_locked": False,
            "fulfillment_triggered": False,
        }

    return TestClient(app)


def test_api_rate_limit_returns_429_after_window_limit():
    client = _client(limit=2)

    first = client.get("/api/v1/ping")
    second = client.get("/api/v1/ping")
    third = client.get("/api/v1/ping")

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "api_rate_limited"
    assert "Retry-After" in third.headers


def test_api_rate_limit_does_not_limit_health_or_exempt_paths():
    client = _client(limit=1, exempt_paths=("/api/v1/exempt",))

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/live").status_code == 200
    assert client.get("/api/v1/exempt/ping").status_code == 200
    assert client.get("/api/v1/exempt/ping").status_code == 200


def test_api_rate_limit_disabled_bypasses_api_requests():
    client = _client(enabled=False, limit=1)

    assert client.get("/api/v1/ping").status_code == 200
    assert client.get("/api/v1/ping").status_code == 200


def test_api_rate_limit_protects_mock_checkout_status_endpoint():
    client = _client(limit=1)

    first = client.get("/api/v1/mock-checkout/ORDER-ABC12345/status")
    second = client.get("/api/v1/mock-checkout/ORDER-ABC12345/status")

    assert first.status_code == 200
    assert first.json()["real_payment"] is False
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "api_rate_limited"
    assert "Retry-After" in second.headers


class FailingRedisStore:
    async def increment(self, *args, **kwargs):
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_redis_backend_without_fallback_fails_closed():
    limiter = ApiRateLimiter(
        limit=2,
        window_seconds=60,
        backend="redis",
        redis_url="redis://localhost:6379/0",
        key_prefix="test",
        local_fallback=False,
        operation_timeout_seconds=0.01,
        redis_store=FailingRedisStore(),
    )

    decision = await limiter.check(client_key="127.0.0.1", path="/api/v1/ping")

    assert decision.allowed is False
    assert decision.backend == "redis_unavailable"
    assert decision.degraded is True


@pytest.mark.asyncio
async def test_redis_backend_with_local_fallback_allows_and_marks_degraded():
    limiter = ApiRateLimiter(
        limit=2,
        window_seconds=60,
        backend="redis",
        redis_url="redis://localhost:6379/0",
        key_prefix="test",
        local_fallback=True,
        operation_timeout_seconds=0.01,
        redis_store=FailingRedisStore(),
    )

    decision = await limiter.check(client_key="127.0.0.1", path="/api/v1/ping")

    assert decision.allowed is True
    assert decision.backend == "local_fallback"
    assert decision.degraded is True
