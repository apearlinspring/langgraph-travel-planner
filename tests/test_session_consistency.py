import pytest

from app.core.session_lock import (
    SessionLockBusy,
    acquire_session_lock,
    reset_session_locks_for_tests,
    session_lock_manager,
)


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
