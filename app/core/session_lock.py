"""Conversation-scoped leases for serializing chat turns."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import socket
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import settings
from app.utils.logger import app_logger


DEFAULT_LOCK_TTL_SECONDS = 300.0
DEFAULT_RENEW_INTERVAL_SECONDS = 30.0
DEFAULT_REDIS_OPERATION_TIMEOUT_SECONDS = 0.5
DEFAULT_REDIS_RETRY_INTERVAL_SECONDS = 5.0

_RELEASE_IF_OWNER_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""

_RENEW_IF_OWNER_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class SessionLockSnapshot:
    """Observable metadata for an acquired conversation lock."""

    conversation_id: str
    acquired_at: float
    wait_seconds: float
    owner: str
    backend: str
    ttl_seconds: float
    expires_at: float | None = None
    owner_task: str | None = None


class SessionLockBusy(RuntimeError):
    """Raised when a conversation already has an active turn."""

    def __init__(
        self,
        conversation_id: str,
        active_lock: SessionLockSnapshot | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.active_lock = active_lock
        super().__init__(f"conversation {conversation_id} is already processing")


class _SessionLockBackend(Protocol):
    async def acquire(
        self,
        conversation_id: str,
        *,
        wait_seconds: float = 0.0,
    ) -> "SessionLockLease":
        ...

    async def release(self, lease: "SessionLockLease") -> None:
        ...

    async def renew(self, lease: "SessionLockLease") -> bool:
        ...

    def is_locked(self, conversation_id: str) -> bool:
        ...

    def active_snapshot(self, conversation_id: str) -> SessionLockSnapshot | None:
        ...

    def active_count(self) -> int:
        ...

    async def reset_for_tests(self) -> None:
        ...


@dataclass(slots=True)
class SessionLockLease:
    """A releasable and renewable lease for one conversation lock."""

    conversation_id: str
    owner: str
    snapshot: SessionLockSnapshot
    _manager: _SessionLockBackend
    _released: bool = False
    _renew_task: asyncio.Task | None = None

    async def __aenter__(self) -> "SessionLockLease":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.release()

    def start_auto_renew(self, interval_seconds: float | None = None) -> None:
        """Start a background renewal task for long-running streams."""

        if self._released or self._renew_task is not None:
            return

        interval = _positive_float(
            interval_seconds,
            default=DEFAULT_RENEW_INTERVAL_SECONDS,
            minimum=0.1,
        )
        self._renew_task = asyncio.create_task(
            self._auto_renew(interval),
            name=f"session-lock-renew:{self.conversation_id}",
        )

    async def renew(self) -> bool:
        """Renew the lease if this owner still holds it."""

        if self._released:
            return False
        return await self._manager.renew(self)

    async def release(self) -> None:
        if self._released:
            return

        self._released = True
        renew_task = self._renew_task
        self._renew_task = None
        if renew_task is not None:
            renew_task.cancel()
            with suppress(asyncio.CancelledError):
                await renew_task

        try:
            await self._manager.release(self)
        except Exception as exc:  # pragma: no cover - defensive fallback
            app_logger.warning(
                "Session lock release failed; relying on TTL expiry: "
                f"conversation_id={self.conversation_id}, "
                f"backend={self.snapshot.backend}, error={exc}"
            )

    async def _auto_renew(self, interval_seconds: float) -> None:
        while not self._released:
            await asyncio.sleep(interval_seconds)
            if self._released:
                return
            try:
                renewed = await self.renew()
            except Exception as exc:  # pragma: no cover - defensive fallback
                renewed = False
                app_logger.warning(
                    "Session lock renew failed: "
                    f"conversation_id={self.conversation_id}, "
                    f"backend={self.snapshot.backend}, error={exc}"
                )
            if not renewed:
                app_logger.warning(
                    "Session lock renew skipped because owner no longer matches: "
                    f"conversation_id={self.conversation_id}, "
                    f"backend={self.snapshot.backend}"
                )
                return


class LocalSessionLockManager:
    """Conversation-level async locks scoped to the current Python process."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
        backend_name: str = "local",
    ) -> None:
        self._ttl_seconds = _positive_float(
            ttl_seconds,
            default=DEFAULT_LOCK_TTL_SECONDS,
            minimum=0.1,
        )
        self._backend_name = backend_name
        self._locks: dict[str, asyncio.Lock] = {}
        self._active: dict[str, SessionLockSnapshot] = {}
        self._guard = asyncio.Lock()

    async def acquire(
        self,
        conversation_id: str,
        *,
        wait_seconds: float = 0.0,
    ) -> SessionLockLease:
        """Acquire a lock for ``conversation_id`` or raise ``SessionLockBusy``."""

        normalized_id = _normalize_conversation_id(conversation_id)
        started_at = time.perf_counter()
        wait = max(wait_seconds, 0.0)

        async with self._guard:
            lock = self._locks.get(normalized_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[normalized_id] = lock

            self._expire_if_needed(normalized_id, lock)
            if not lock.locked():
                await lock.acquire()
                return self._lease(normalized_id, started_at)

            if wait <= 0:
                raise SessionLockBusy(normalized_id, self._active.get(normalized_id))

        try:
            await asyncio.wait_for(lock.acquire(), timeout=wait)
        except asyncio.TimeoutError:
            async with self._guard:
                self._expire_if_needed(normalized_id, lock)
                active_lock = self._active.get(normalized_id)
            raise SessionLockBusy(normalized_id, active_lock) from None

        async with self._guard:
            return self._lease(normalized_id, started_at)

    async def release(self, lease: SessionLockLease) -> None:
        """Release a previously acquired lease if it is still current."""

        async with self._guard:
            active = self._active.get(lease.conversation_id)
            lock = self._locks.get(lease.conversation_id)
            if (
                active is None
                or active.owner != lease.owner
                or lock is None
                or not lock.locked()
            ):
                return
            self._active.pop(lease.conversation_id, None)
            lock.release()

    async def renew(self, lease: SessionLockLease) -> bool:
        """Extend a local lease if the same owner still holds it."""

        async with self._guard:
            active = self._active.get(lease.conversation_id)
            if active is None or active.owner != lease.owner:
                return False
            self._active[lease.conversation_id] = _copy_snapshot_with_expiry(
                active,
                ttl_seconds=self._ttl_seconds,
            )
            return True

    def is_locked(self, conversation_id: str) -> bool:
        snapshot = self.active_snapshot(conversation_id)
        return snapshot is not None

    def active_snapshot(self, conversation_id: str) -> SessionLockSnapshot | None:
        normalized_id = str(conversation_id).strip()
        snapshot = self._active.get(normalized_id)
        if _is_expired(snapshot):
            return None
        return snapshot

    def active_count(self) -> int:
        return sum(1 for snapshot in self._active.values() if not _is_expired(snapshot))

    async def reset_for_tests(self) -> None:
        """Clear lock bookkeeping for isolated unit tests."""

        async with self._guard:
            self._locks.clear()
            self._active.clear()

    def _lease(self, conversation_id: str, started_at: float) -> SessionLockLease:
        owner = _new_owner()
        snapshot = SessionLockSnapshot(
            conversation_id=conversation_id,
            acquired_at=time.time(),
            wait_seconds=round(time.perf_counter() - started_at, 6),
            owner=owner,
            backend=self._backend_name,
            ttl_seconds=self._ttl_seconds,
            expires_at=time.time() + self._ttl_seconds,
            owner_task=_current_task_name(),
        )
        self._active[conversation_id] = snapshot
        return SessionLockLease(
            conversation_id=conversation_id,
            owner=owner,
            snapshot=snapshot,
            _manager=self,
        )

    def _expire_if_needed(self, conversation_id: str, lock: asyncio.Lock) -> None:
        snapshot = self._active.get(conversation_id)
        if not _is_expired(snapshot):
            return
        self._active.pop(conversation_id, None)
        if lock.locked():
            lock.release()


class RedisSessionLockManager:
    """Redis-backed conversation leases safe across workers and instances."""

    def __init__(
        self,
        *,
        redis_url: str,
        key_prefix: str,
        ttl_seconds: float = DEFAULT_LOCK_TTL_SECONDS,
        operation_timeout_seconds: float = DEFAULT_REDIS_OPERATION_TIMEOUT_SECONDS,
        redis_client: Any | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._key_prefix = key_prefix.rstrip(":") or "zhixing:session_lock"
        self._ttl_seconds = _positive_float(
            ttl_seconds,
            default=DEFAULT_LOCK_TTL_SECONDS,
            minimum=0.1,
        )
        self._operation_timeout_seconds = _positive_float(
            operation_timeout_seconds,
            default=DEFAULT_REDIS_OPERATION_TIMEOUT_SECONDS,
            minimum=0.05,
        )
        self._client = redis_client
        self._owns_client = redis_client is None
        self._active: dict[str, SessionLockSnapshot] = {}
        self._guard = asyncio.Lock()

    async def acquire(
        self,
        conversation_id: str,
        *,
        wait_seconds: float = 0.0,
    ) -> SessionLockLease:
        """Acquire a Redis lease or raise ``SessionLockBusy``."""

        normalized_id = _normalize_conversation_id(conversation_id)
        started_at = time.perf_counter()
        wait = max(wait_seconds, 0.0)
        deadline = time.perf_counter() + wait
        client = await self._get_client()
        key = self._key(normalized_id)
        owner = _new_owner()
        owner_value = _owner_value(owner)
        ttl_ms = _ttl_ms(self._ttl_seconds)

        while True:
            acquired = await self._redis_call(
                client.set(key, owner_value, nx=True, px=ttl_ms)
            )
            if acquired:
                snapshot = SessionLockSnapshot(
                    conversation_id=normalized_id,
                    acquired_at=time.time(),
                    wait_seconds=round(time.perf_counter() - started_at, 6),
                    owner=owner,
                    backend="redis",
                    ttl_seconds=self._ttl_seconds,
                    expires_at=time.time() + self._ttl_seconds,
                    owner_task=_current_task_name(),
                )
                async with self._guard:
                    self._active[normalized_id] = snapshot
                return SessionLockLease(
                    conversation_id=normalized_id,
                    owner=owner,
                    snapshot=snapshot,
                    _manager=self,
                )

            active_lock = await self._redis_snapshot(
                client,
                key=key,
                conversation_id=normalized_id,
            )
            if wait <= 0 or time.perf_counter() >= deadline:
                raise SessionLockBusy(normalized_id, active_lock)

            remaining = max(deadline - time.perf_counter(), 0.0)
            await asyncio.sleep(min(0.05, remaining))

    async def release(self, lease: SessionLockLease) -> None:
        """Release only if the Redis value still belongs to this owner."""

        client = await self._get_client()
        key = self._key(lease.conversation_id)
        expected_value = _owner_value(lease.owner)
        await self._redis_call(
            client.eval(_RELEASE_IF_OWNER_LUA, 1, key, expected_value)
        )
        async with self._guard:
            active = self._active.get(lease.conversation_id)
            if active is not None and active.owner == lease.owner:
                self._active.pop(lease.conversation_id, None)

    async def renew(self, lease: SessionLockLease) -> bool:
        """Extend the Redis TTL only when this owner still holds the key."""

        client = await self._get_client()
        key = self._key(lease.conversation_id)
        expected_value = _owner_value(lease.owner)
        renewed = await self._redis_call(
            client.eval(
                _RENEW_IF_OWNER_LUA,
                1,
                key,
                expected_value,
                str(_ttl_ms(self._ttl_seconds)),
            )
        )
        if int(renewed or 0) <= 0:
            async with self._guard:
                active = self._active.get(lease.conversation_id)
                if active is not None and active.owner == lease.owner:
                    self._active.pop(lease.conversation_id, None)
            return False

        async with self._guard:
            active = self._active.get(lease.conversation_id)
            if active is not None and active.owner == lease.owner:
                self._active[lease.conversation_id] = _copy_snapshot_with_expiry(
                    active,
                    ttl_seconds=self._ttl_seconds,
                )
        return True

    def is_locked(self, conversation_id: str) -> bool:
        snapshot = self.active_snapshot(conversation_id)
        return snapshot is not None

    def active_snapshot(self, conversation_id: str) -> SessionLockSnapshot | None:
        normalized_id = str(conversation_id).strip()
        snapshot = self._active.get(normalized_id)
        if _is_expired(snapshot):
            return None
        return snapshot

    def active_count(self) -> int:
        return sum(1 for snapshot in self._active.values() if not _is_expired(snapshot))

    async def reset_for_tests(self) -> None:
        async with self._guard:
            self._active.clear()

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        import redis.asyncio as redis_asyncio

        self._client = redis_asyncio.Redis.from_url(
            self._redis_url,
            decode_responses=False,
            socket_connect_timeout=self._operation_timeout_seconds,
            socket_timeout=self._operation_timeout_seconds,
        )
        await self._redis_call(self._client.ping())
        return self._client

    async def _redis_call(self, result_or_awaitable: Any) -> Any:
        if inspect.isawaitable(result_or_awaitable):
            return await asyncio.wait_for(
                result_or_awaitable,
                timeout=self._operation_timeout_seconds,
            )
        return result_or_awaitable

    async def _redis_snapshot(
        self,
        client: Any,
        *,
        key: str,
        conversation_id: str,
    ) -> SessionLockSnapshot | None:
        raw_value = await self._redis_call(client.get(key))
        if raw_value is None:
            return None

        pttl = await self._redis_call(client.pttl(key))
        ttl_seconds = max(float(pttl) / 1000.0, 0.0) if int(pttl) >= 0 else 0.0
        owner_payload = _parse_owner_value(raw_value)
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        acquired_at = time.time() - max(self._ttl_seconds - ttl_seconds, 0.0)
        return SessionLockSnapshot(
            conversation_id=conversation_id,
            acquired_at=float(owner_payload.get("acquired_at") or acquired_at),
            wait_seconds=0.0,
            owner=str(owner_payload.get("owner") or "unknown"),
            backend="redis",
            ttl_seconds=ttl_seconds,
            expires_at=expires_at,
            owner_task=owner_payload.get("task"),
        )

    def _key(self, conversation_id: str) -> str:
        return f"{self._key_prefix}:{conversation_id}"


class SessionLockManager:
    """Facade that prefers Redis and degrades to local process locks."""

    def __init__(
        self,
        *,
        backend: str | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._configured_backend = _normalize_backend(
            backend or settings.session_lock_backend
        )
        self._redis_url = settings.redis_url
        self._key_prefix = settings.session_lock_key_prefix
        self._ttl_seconds = settings.session_lock_ttl_seconds
        self._operation_timeout_seconds = (
            settings.session_lock_redis_operation_timeout_seconds
        )
        self._fallback_to_local = settings.session_lock_redis_fallback_to_local
        self._redis_retry_interval_seconds = (
            settings.session_lock_redis_retry_interval_seconds
        )
        self._redis_cooldown_until = 0.0
        self._redis_client = redis_client
        self._build_backends()

    async def acquire(
        self,
        conversation_id: str,
        *,
        wait_seconds: float | None = None,
    ) -> SessionLockLease:
        """Acquire a distributed lease, falling back locally when configured."""

        wait = (
            settings.session_lock_acquire_wait_seconds
            if wait_seconds is None
            else wait_seconds
        )

        if self._configured_backend == "local":
            return await self._local.acquire(conversation_id, wait_seconds=wait)

        if self._should_try_redis():
            try:
                assert self._redis is not None
                return await self._redis.acquire(conversation_id, wait_seconds=wait)
            except SessionLockBusy:
                raise
            except ValueError:
                raise
            except Exception as exc:
                if not self._fallback_to_local:
                    raise
                self._redis_cooldown_until = (
                    time.monotonic() + self._redis_retry_interval_seconds
                )
                app_logger.warning(
                    "Redis session lock unavailable; degrading to local locks: "
                    f"backend={self._configured_backend}, error={exc}"
                )

        return await self._local.acquire(conversation_id, wait_seconds=wait)

    async def release(self, lease: SessionLockLease) -> None:
        await lease._manager.release(lease)

    async def renew(self, lease: SessionLockLease) -> bool:
        return await lease._manager.renew(lease)

    def is_locked(self, conversation_id: str) -> bool:
        return self._local.is_locked(conversation_id) or (
            self._redis is not None and self._redis.is_locked(conversation_id)
        )

    def active_snapshot(self, conversation_id: str) -> SessionLockSnapshot | None:
        return self._local.active_snapshot(conversation_id) or (
            self._redis.active_snapshot(conversation_id)
            if self._redis is not None
            else None
        )

    def active_count(self) -> int:
        redis_count = self._redis.active_count() if self._redis is not None else 0
        return self._local.active_count() + redis_count

    async def reset_for_tests(
        self,
        *,
        backend: str | None = "local",
        redis_client: Any | None = None,
    ) -> None:
        """Reset lock state and optionally force a test backend."""

        if backend is not None:
            self._configured_backend = _normalize_backend(backend)
        if redis_client is not None:
            self._redis_client = redis_client
        self._redis_cooldown_until = 0.0
        self._build_backends()
        await self._local.reset_for_tests()
        if self._redis is not None:
            await self._redis.reset_for_tests()

    def _build_backends(self) -> None:
        self._local = LocalSessionLockManager(
            ttl_seconds=self._ttl_seconds,
            backend_name="local",
        )
        self._redis = None
        if self._configured_backend in {"auto", "redis"}:
            self._redis = RedisSessionLockManager(
                redis_url=self._redis_url,
                key_prefix=self._key_prefix,
                ttl_seconds=self._ttl_seconds,
                operation_timeout_seconds=self._operation_timeout_seconds,
                redis_client=self._redis_client,
            )

    def _should_try_redis(self) -> bool:
        if self._redis is None:
            return False
        if self._local.active_count() > 0:
            return False
        return time.monotonic() >= self._redis_cooldown_until


def _normalize_conversation_id(conversation_id: str) -> str:
    normalized_id = str(conversation_id).strip()
    if not normalized_id:
        raise ValueError("conversation_id must not be empty")
    return normalized_id


def _normalize_backend(backend: str) -> str:
    normalized = str(backend).strip().lower()
    if normalized not in {"auto", "redis", "local"}:
        raise ValueError(
            "SESSION_LOCK_BACKEND must be one of: auto, redis, local"
        )
    return normalized


def _positive_float(
    value: float | int | str | None,
    *,
    default: float,
    minimum: float,
) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, minimum)


def _ttl_ms(ttl_seconds: float) -> int:
    return max(int(ttl_seconds * 1000), 1)


def _current_task_name() -> str | None:
    task = asyncio.current_task()
    if task is None:
        return None
    return task.get_name()


def _new_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def _owner_value(owner: str) -> str:
    return owner


def _parse_owner_value(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8", errors="replace")
    if not isinstance(raw_value, str):
        return {"owner": str(raw_value)}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {"owner": raw_value}
    if not isinstance(payload, dict):
        return {"owner": raw_value}
    return payload


def _is_expired(snapshot: SessionLockSnapshot | None) -> bool:
    return bool(
        snapshot
        and snapshot.expires_at is not None
        and snapshot.expires_at <= time.time()
    )


def _copy_snapshot_with_expiry(
    snapshot: SessionLockSnapshot,
    *,
    ttl_seconds: float,
) -> SessionLockSnapshot:
    return SessionLockSnapshot(
        conversation_id=snapshot.conversation_id,
        acquired_at=snapshot.acquired_at,
        wait_seconds=snapshot.wait_seconds,
        owner=snapshot.owner,
        backend=snapshot.backend,
        ttl_seconds=ttl_seconds,
        expires_at=time.time() + ttl_seconds,
        owner_task=snapshot.owner_task,
    )


session_lock_manager = SessionLockManager()


async def acquire_session_lock(
    conversation_id: str,
    *,
    wait_seconds: float | None = None,
) -> SessionLockLease:
    return await session_lock_manager.acquire(
        conversation_id,
        wait_seconds=wait_seconds,
    )


async def reset_session_locks_for_tests(
    *,
    backend: str | None = "local",
    redis_client: Any | None = None,
) -> None:
    await session_lock_manager.reset_for_tests(
        backend=backend,
        redis_client=redis_client,
    )
