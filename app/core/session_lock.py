"""Lightweight in-process session locks for conversation turns."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionLockSnapshot:
    """Observable metadata for an acquired conversation lock."""

    conversation_id: str
    acquired_at: float
    wait_seconds: float
    owner_task: str | None


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


@dataclass(slots=True)
class SessionLockLease:
    """A releasable lease for one conversation lock."""

    conversation_id: str
    snapshot: SessionLockSnapshot
    _manager: "SessionLockManager"
    _released: bool = False

    async def __aenter__(self) -> "SessionLockLease":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.release()

    async def release(self) -> None:
        if self._released:
            return
        await self._manager.release(self)
        self._released = True


class SessionLockManager:
    """Conversation-level async locks scoped to the current Python process."""

    def __init__(self) -> None:
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

        normalized_id = str(conversation_id).strip()
        if not normalized_id:
            raise ValueError("conversation_id must not be empty")

        started_at = time.perf_counter()
        async with self._guard:
            lock = self._locks.get(normalized_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[normalized_id] = lock

            if not lock.locked():
                await lock.acquire()
                return self._lease(normalized_id, started_at)

            if wait_seconds <= 0:
                raise SessionLockBusy(normalized_id, self._active.get(normalized_id))

        try:
            await asyncio.wait_for(lock.acquire(), timeout=wait_seconds)
        except TimeoutError:
            async with self._guard:
                active_lock = self._active.get(normalized_id)
            raise SessionLockBusy(normalized_id, active_lock) from None

        async with self._guard:
            return self._lease(normalized_id, started_at)

    async def release(self, lease: SessionLockLease) -> None:
        """Release a previously acquired lease if it is still current."""

        async with self._guard:
            active = self._active.get(lease.conversation_id)
            lock = self._locks.get(lease.conversation_id)
            if active != lease.snapshot or lock is None or not lock.locked():
                return
            self._active.pop(lease.conversation_id, None)
            lock.release()

    def is_locked(self, conversation_id: str) -> bool:
        lock = self._locks.get(str(conversation_id).strip())
        return bool(lock and lock.locked())

    def active_snapshot(self, conversation_id: str) -> SessionLockSnapshot | None:
        return self._active.get(str(conversation_id).strip())

    def active_count(self) -> int:
        return len(self._active)

    async def reset_for_tests(self) -> None:
        """Clear lock bookkeeping for isolated unit tests."""

        async with self._guard:
            self._locks.clear()
            self._active.clear()

    def _lease(self, conversation_id: str, started_at: float) -> SessionLockLease:
        snapshot = SessionLockSnapshot(
            conversation_id=conversation_id,
            acquired_at=time.time(),
            wait_seconds=round(time.perf_counter() - started_at, 6),
            owner_task=_current_task_name(),
        )
        self._active[conversation_id] = snapshot
        return SessionLockLease(
            conversation_id=conversation_id,
            snapshot=snapshot,
            _manager=self,
        )


def _current_task_name() -> str | None:
    task = asyncio.current_task()
    if task is None:
        return None
    return task.get_name()


session_lock_manager = SessionLockManager()


async def acquire_session_lock(
    conversation_id: str,
    *,
    wait_seconds: float = 0.0,
) -> SessionLockLease:
    return await session_lock_manager.acquire(
        conversation_id,
        wait_seconds=wait_seconds,
    )


async def reset_session_locks_for_tests() -> None:
    await session_lock_manager.reset_for_tests()
