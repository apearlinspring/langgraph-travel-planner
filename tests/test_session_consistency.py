import asyncio
import json
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("DASHSCOPE_API_KEY", "test-dashscope-key")
os.environ.setdefault("LANGSMITH_API_KEY", "test-langsmith-key")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")

from app.api.v1 import chat
from app.core.session_lock import (
    LocalSessionLockManager,
    RedisSessionLockManager,
    SessionLockBusy,
    acquire_session_lock,
    reset_session_locks_for_tests,
    session_lock_manager,
)
from app.evaluation.runtime_metrics import collect_runtime_metrics


def _decode_sse_frame(frame: str) -> dict:
    raw_data = frame.removeprefix("data: ").strip()
    return json.loads(raw_data)


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}

    async def set(self, key, value, nx=False, px=None):
        self._expire_if_needed(key)
        if nx and key in self.values:
            return None
        expires_at = time.time() + (px / 1000) if px is not None else None
        self.values[key] = (value, expires_at)
        return True

    async def get(self, key):
        self._expire_if_needed(key)
        item = self.values.get(key)
        if item is None:
            return None
        return item[0]

    async def pttl(self, key):
        self._expire_if_needed(key)
        item = self.values.get(key)
        if item is None:
            return -2
        expires_at = item[1]
        if expires_at is None:
            return -1
        return max(int((expires_at - time.time()) * 1000), 0)

    async def eval(self, _script, _numkeys, key, expected_value, *args):
        self._expire_if_needed(key)
        item = self.values.get(key)
        if item is None or item[0] != expected_value:
            return 0
        if args:
            ttl_ms = int(args[0])
            self.values[key] = (item[0], time.time() + ttl_ms / 1000)
            return 1
        self.values.pop(key, None)
        return 1

    def _expire_if_needed(self, key) -> None:
        item = self.values.get(key)
        if item is None:
            return
        expires_at = item[1]
        if expires_at is not None and expires_at <= time.time():
            self.values.pop(key, None)


@pytest.mark.asyncio
async def test_session_lock_rejects_concurrent_turn_for_same_conversation():
    await reset_session_locks_for_tests()
    lease = await acquire_session_lock("conversation-1")

    try:
        with pytest.raises(SessionLockBusy) as exc_info:
            await acquire_session_lock("conversation-1")

        assert exc_info.value.conversation_id == "conversation-1"
        assert exc_info.value.active_lock is not None
        assert exc_info.value.active_lock.conversation_id == "conversation-1"
    finally:
        await lease.release()


@pytest.mark.asyncio
async def test_session_lock_allows_different_conversations_in_parallel():
    await reset_session_locks_for_tests()
    first = await acquire_session_lock("conversation-1")
    second = await acquire_session_lock("conversation-2")

    try:
        assert session_lock_manager.is_locked("conversation-1") is True
        assert session_lock_manager.is_locked("conversation-2") is True
        assert session_lock_manager.active_count() == 2
    finally:
        await first.release()
        await second.release()


@pytest.mark.asyncio
async def test_session_lock_can_reacquire_after_release():
    await reset_session_locks_for_tests()
    first = await acquire_session_lock("conversation-1")
    await first.release()

    second = await acquire_session_lock("conversation-1")

    try:
        assert session_lock_manager.is_locked("conversation-1") is True
    finally:
        await second.release()


@pytest.mark.asyncio
async def test_session_lock_context_manager_releases_on_exception():
    await reset_session_locks_for_tests()

    with pytest.raises(RuntimeError):
        async with await acquire_session_lock("conversation-1"):
            raise RuntimeError("boom")

    assert session_lock_manager.is_locked("conversation-1") is False


@pytest.mark.asyncio
async def test_local_session_lock_expires_and_allows_new_owner():
    manager = LocalSessionLockManager(ttl_seconds=0.1)
    first = await manager.acquire("conversation-1")
    await asyncio.sleep(0.13)

    second = await manager.acquire("conversation-1")

    try:
        assert second.owner != first.owner
        assert manager.is_locked("conversation-1") is True
    finally:
        await first.release()
        await second.release()


@pytest.mark.asyncio
async def test_local_session_lock_auto_renew_keeps_lease_active():
    manager = LocalSessionLockManager(ttl_seconds=0.05)
    lease = await manager.acquire("conversation-1")
    lease.start_auto_renew(0.02)

    try:
        await asyncio.sleep(0.09)
        with pytest.raises(SessionLockBusy):
            await manager.acquire("conversation-1")
    finally:
        await lease.release()

    reacquired = await manager.acquire("conversation-1")
    await reacquired.release()


@pytest.mark.asyncio
async def test_redis_session_lock_rejects_concurrent_owner_for_same_conversation():
    fake_redis = FakeRedis()
    manager = RedisSessionLockManager(
        redis_url="redis://test",
        key_prefix="test:session_lock",
        ttl_seconds=1,
        redis_client=fake_redis,
    )
    lease = await manager.acquire("conversation-1")

    try:
        with pytest.raises(SessionLockBusy) as exc_info:
            await manager.acquire("conversation-1")

        assert lease.snapshot.backend == "redis"
        assert exc_info.value.active_lock is not None
        assert exc_info.value.active_lock.owner == lease.owner
    finally:
        await lease.release()

    assert await fake_redis.get("test:session_lock:conversation-1") is None


@pytest.mark.asyncio
async def test_redis_session_lock_expires_and_does_not_delete_new_owner():
    fake_redis = FakeRedis()
    manager = RedisSessionLockManager(
        redis_url="redis://test",
        key_prefix="test:session_lock",
        ttl_seconds=0.1,
        redis_client=fake_redis,
    )
    first = await manager.acquire("conversation-1")
    await asyncio.sleep(0.13)
    second = await manager.acquire("conversation-1")

    try:
        assert second.owner != first.owner
        await first.release()
        assert await fake_redis.get("test:session_lock:conversation-1") is not None
    finally:
        await second.release()

    assert await fake_redis.get("test:session_lock:conversation-1") is None


@pytest.mark.asyncio
async def test_redis_session_lock_renews_ttl_for_current_owner():
    fake_redis = FakeRedis()
    manager = RedisSessionLockManager(
        redis_url="redis://test",
        key_prefix="test:session_lock",
        ttl_seconds=0.1,
        redis_client=fake_redis,
    )
    lease = await manager.acquire("conversation-1")

    try:
        await asyncio.sleep(0.06)
        assert await lease.renew() is True
        assert await fake_redis.pttl("test:session_lock:conversation-1") > 50
    finally:
        await lease.release()


@pytest.mark.asyncio
async def test_chat_stream_returns_busy_event_without_saving_user_message(monkeypatch):
    await reset_session_locks_for_tests()
    lease = await acquire_session_lock("conversation-1")
    saved_messages = []

    async def fake_save_message(*args, **kwargs):
        saved_messages.append((args, kwargs))

    monkeypatch.setattr(chat, "save_message", fake_save_message)

    try:
        stream = chat.generate_sse_stream(
            "conversation-1",
            "继续规划",
            db=SimpleNamespace(),
            user=SimpleNamespace(id="user-1"),
        )

        busy_event = _decode_sse_frame(await anext(stream))
        done_event = _decode_sse_frame(await anext(stream))

        assert busy_event["type"] == "session_busy"
        assert "当前会话正在处理" in busy_event["content"]
        assert busy_event["lock_backend"] == "local"
        assert done_event == {"type": "done"}
        assert saved_messages == []

        metrics = collect_runtime_metrics(
            events=[busy_event, done_event],
            turns=[{"turn_index": 1, "user_message": "继续规划", "elapsed_seconds": 0.1}],
            assistant_text=busy_event["content"],
            elapsed_seconds=0.1,
        )
        assert metrics.session_busy_event_count == 1
    finally:
        await stream.aclose()
        await lease.release()


@pytest.mark.asyncio
async def test_chat_stream_releases_session_lock_when_generator_closes(monkeypatch):
    await reset_session_locks_for_tests()

    async def fake_save_message(*args, **kwargs):
        return SimpleNamespace()

    class SlowAgent:
        async def astream_events(self, *args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": SimpleNamespace(content="你好")},
            }
            await asyncio.sleep(60)

    async def fake_create_travel_agent():
        return SlowAgent()

    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "create_travel_agent", fake_create_travel_agent)

    stream = chat.generate_sse_stream(
        "conversation-1",
        "做个行程",
        db=SimpleNamespace(),
        user=SimpleNamespace(id="user-1"),
    )

    token_event = _decode_sse_frame(await anext(stream))
    assert token_event == {"type": "token", "content": "你好"}
    assert session_lock_manager.is_locked("conversation-1") is True

    await stream.aclose()

    assert session_lock_manager.is_locked("conversation-1") is False
