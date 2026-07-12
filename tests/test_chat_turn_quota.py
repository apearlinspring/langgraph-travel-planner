from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import chat as chat_api
from app.config import settings


class _CountResult:
    def __init__(self, count: int) -> None:
        self.count = count

    def scalar_one(self) -> int:
        return self.count


class _CountSession:
    def __init__(self, count: int) -> None:
        self.count = count
        self.executed = False

    async def execute(self, statement):
        self.executed = True
        self.statement = statement
        return _CountResult(self.count)


def _user(role: str = "user") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), preferences={"role": role})


@pytest.mark.asyncio
async def test_chat_turn_quota_disabled_does_not_query_database(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "chat_turn_quota_enabled", False)
    db = _CountSession(count=99)

    decision = await chat_api._enforce_chat_turn_quota(db, _user())

    assert decision.enabled is False
    assert db.executed is False


@pytest.mark.asyncio
async def test_chat_turn_quota_allows_until_daily_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "chat_turn_quota_enabled", True)
    monkeypatch.setattr(settings, "chat_turn_quota_daily_limit", 2)
    monkeypatch.setattr(settings, "chat_turn_quota_admin_exempt", False)

    decision = await chat_api._enforce_chat_turn_quota(
        _CountSession(count=1),
        _user(),
        now=datetime(2026, 7, 3, 12, 0, 0),
    )

    assert decision.enabled is True
    assert decision.limit == 2
    assert decision.used == 1
    assert decision.remaining_after_accept == 0
    assert decision.retry_after_seconds == 12 * 60 * 60


@pytest.mark.asyncio
async def test_chat_turn_quota_blocks_after_daily_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "chat_turn_quota_enabled", True)
    monkeypatch.setattr(settings, "chat_turn_quota_daily_limit", 2)
    monkeypatch.setattr(settings, "chat_turn_quota_admin_exempt", False)

    with pytest.raises(HTTPException) as exc_info:
        await chat_api._enforce_chat_turn_quota(
            _CountSession(count=2),
            _user(),
            now=datetime(2026, 7, 3, 23, 59, 30),
        )

    exc = exc_info.value
    assert exc.status_code == 429
    assert exc.detail["code"] == "chat_daily_quota_exceeded"
    assert exc.headers["Retry-After"] == "30"
    assert exc.headers["X-ChatQuota-Remaining"] == "0"


@pytest.mark.asyncio
async def test_chat_turn_quota_can_exempt_admin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "chat_turn_quota_enabled", True)
    monkeypatch.setattr(settings, "chat_turn_quota_daily_limit", 2)
    monkeypatch.setattr(settings, "chat_turn_quota_admin_exempt", True)
    db = _CountSession(count=99)

    decision = await chat_api._enforce_chat_turn_quota(db, _user("admin"))

    assert decision.enabled is True
    assert decision.remaining_after_accept == 2
    assert db.executed is False
