import asyncio
import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DASHSCOPE_API_KEY", "test-dashscope-key")
os.environ.setdefault("LANGSMITH_API_KEY", "test-langsmith-key")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")

from app.api.v1 import chat
from app.core.session_lock import (
    SessionLockBusy,
    acquire_session_lock,
    reset_session_locks_for_tests,
    session_lock_manager,
)
from app.evaluation.runtime_metrics import collect_runtime_metrics


def _decode_sse_frame(frame: str) -> dict:
    raw_data = frame.removeprefix("data: ").strip()
    return json.loads(raw_data)


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
