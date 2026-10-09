"""API rate limiting middleware for M1 overload protection."""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


DEFAULT_LIMITED_METHODS = {"GET", "POST", "PATCH", "DELETE"}


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Decision returned by a rate-limit backend."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_after_seconds: int
    backend: str
    degraded: bool = False


class LocalFixedWindowRateLimitStore:
    """In-process fixed-window counter used for tests and single-node fallback."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    async def increment(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[int, int]:
        now = int(self._clock())
        window_start = now - (now % window_seconds)
        reset_after = max(1, window_seconds - (now - window_start))
        async with self._lock:
            bucket_start, count = self._buckets.get(key, (window_start, 0))
            if bucket_start != window_start:
                bucket_start, count = window_start, 0
            count += 1
            self._buckets[key] = (bucket_start, count)
        return count, reset_after

    async def reset_for_tests(self) -> None:
        async with self._lock:
            self._buckets.clear()


class RedisFixedWindowRateLimitStore:
    """Redis fixed-window counter safe across workers and instances."""

    def __init__(self, *, redis_url: str, operation_timeout_seconds: float = 0.5) -> None:
        self._redis_url = redis_url
        self._operation_timeout_seconds = operation_timeout_seconds
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()

    async def increment(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[int, int]:
        client = await self._get_client()
        now = int(time.time())
        reset_after = max(1, window_seconds - (now % window_seconds))
        async def operation() -> tuple[int, int]:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, reset_after)
            ttl = await client.ttl(key)
            return int(count), max(1, int(ttl if ttl and ttl > 0 else reset_after))

        return await asyncio.wait_for(operation(), timeout=self._operation_timeout_seconds)

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            import redis.asyncio as redis

            self._client = redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=self._operation_timeout_seconds,
                socket_timeout=self._operation_timeout_seconds,
            )
            return self._client


class ApiRateLimiter:
    """Fixed-window API limiter with Redis primary and local fallback support."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        backend: str,
        redis_url: str,
        key_prefix: str,
        local_fallback: bool,
        operation_timeout_seconds: float,
        local_store: LocalFixedWindowRateLimitStore | None = None,
        redis_store: RedisFixedWindowRateLimitStore | None = None,
    ) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self.backend = (backend or "local").strip().lower()
        self.key_prefix = key_prefix.strip() or "zhixing:rate_limit"
        self.local_fallback = bool(local_fallback)
        self._local_store = local_store or LocalFixedWindowRateLimitStore()
        self._redis_store = redis_store or RedisFixedWindowRateLimitStore(
            redis_url=redis_url,
            operation_timeout_seconds=operation_timeout_seconds,
        )

    async def check(self, *, client_key: str, path: str) -> RateLimitDecision:
        key = self._key(client_key=client_key, path=path)
        if self.backend == "redis":
            try:
                count, reset_after = await self._redis_store.increment(
                    key,
                    limit=self.limit,
                    window_seconds=self.window_seconds,
                )
                return self._decision(count=count, reset_after=reset_after, backend="redis")
            except Exception:
                if not self.local_fallback:
                    return RateLimitDecision(
                        allowed=False,
                        limit=self.limit,
                        remaining=0,
                        retry_after_seconds=1,
                        reset_after_seconds=1,
                        backend="redis_unavailable",
                        degraded=True,
                    )
                count, reset_after = await self._local_store.increment(
                    key,
                    limit=self.limit,
                    window_seconds=self.window_seconds,
                )
                return self._decision(
                    count=count,
                    reset_after=reset_after,
                    backend="local_fallback",
                    degraded=True,
                )

        count, reset_after = await self._local_store.increment(
            key,
            limit=self.limit,
            window_seconds=self.window_seconds,
        )
        return self._decision(count=count, reset_after=reset_after, backend="local")

    def _decision(
        self,
        *,
        count: int,
        reset_after: int,
        backend: str,
        degraded: bool = False,
    ) -> RateLimitDecision:
        remaining = max(0, self.limit - count)
        allowed = count <= self.limit
        return RateLimitDecision(
            allowed=allowed,
            limit=self.limit,
            remaining=remaining,
            retry_after_seconds=reset_after if not allowed else 0,
            reset_after_seconds=reset_after,
            backend=backend,
            degraded=degraded,
        )

    def _key(self, *, client_key: str, path: str) -> str:
        normalized = f"{client_key}|{path}".encode("utf-8", "replace")
        digest = hashlib.sha256(normalized).hexdigest()
        window = int(time.time()) // self.window_seconds
        return f"{self.key_prefix}:{window}:{digest}"


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply API rate limits while keeping health probes and static pages exempt."""

    def __init__(
        self,
        app: Any,
        *,
        enabled: bool,
        requests_per_window: int,
        window_seconds: int,
        backend: str,
        redis_url: str,
        key_prefix: str = "zhixing:rate_limit",
        protected_prefixes: Iterable[str] = ("/api/v1",),
        exempt_paths: Iterable[str] = (),
        local_fallback: bool = False,
        operation_timeout_seconds: float = 0.5,
        limiter: ApiRateLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self.enabled = bool(enabled)
        self.protected_prefixes = tuple(_normalize_prefix(item) for item in protected_prefixes if item)
        self.exempt_paths = tuple(_normalize_prefix(item) for item in exempt_paths if item)
        self.limiter = limiter or ApiRateLimiter(
            limit=requests_per_window,
            window_seconds=window_seconds,
            backend=backend,
            redis_url=redis_url,
            key_prefix=key_prefix,
            local_fallback=local_fallback,
            operation_timeout_seconds=operation_timeout_seconds,
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._should_limit(request):
            return await call_next(request)

        decision = await self.limiter.check(
            client_key=_client_key(request),
            path=request.url.path,
        )
        if not decision.allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": {
                        "code": "api_rate_limited",
                        "message": "Too many requests. Please retry later.",
                    }
                },
            )
            _apply_rate_limit_headers(response, decision)
            return response

        response = await call_next(request)
        _apply_rate_limit_headers(response, decision)
        return response

    def _should_limit(self, request: Request) -> bool:
        if not self.enabled:
            return False
        if request.method.upper() not in DEFAULT_LIMITED_METHODS:
            return False
        path = request.url.path
        if any(path == exempt or path.startswith(exempt + "/") for exempt in self.exempt_paths):
            return False
        return any(path == prefix or path.startswith(prefix + "/") for prefix in self.protected_prefixes)


def _apply_rate_limit_headers(response: Response, decision: RateLimitDecision) -> None:
    response.headers.setdefault("X-RateLimit-Limit", str(decision.limit))
    response.headers.setdefault("X-RateLimit-Remaining", str(decision.remaining))
    response.headers.setdefault("X-RateLimit-Reset", str(decision.reset_after_seconds))
    response.headers.setdefault("X-RateLimit-Backend", decision.backend)
    if decision.degraded:
        response.headers.setdefault("X-RateLimit-Degraded", "true")
    if not decision.allowed:
        response.headers.setdefault("Retry-After", str(decision.retry_after_seconds))


def _client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _normalize_prefix(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("/"):
        text = "/" + text
    return text.rstrip("/") or "/"
