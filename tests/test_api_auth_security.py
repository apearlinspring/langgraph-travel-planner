from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import users as users_api
from app.config import Settings, settings
from app.models.base import get_db


class _FakeResult:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class _FakeAsyncSession:
    def __init__(self):
        self.users = []

    def add(self, user):
        if getattr(user, "id", None) is None:
            user.id = uuid.uuid4()
        if getattr(user, "created_at", None) is None:
            user.created_at = datetime.now(UTC)
        if getattr(user, "updated_at", None) is None:
            user.updated_at = user.created_at
        self.users.append(user)

    async def commit(self):
        return None

    async def refresh(self, user):
        if getattr(user, "id", None) is None:
            user.id = uuid.uuid4()
        if getattr(user, "created_at", None) is None:
            user.created_at = datetime.now(UTC)
        if getattr(user, "updated_at", None) is None:
            user.updated_at = user.created_at

    async def execute(self, statement):
        matches = [
            user for user in self.users if _matches_clause(statement.whereclause, user)
        ]
        return _FakeResult(matches[0] if matches else None)


def _normalize_compare_value(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _extract_bound_value(node):
    if hasattr(node, "value"):
        return node.value
    if hasattr(node, "effective_value"):
        return node.effective_value
    return None


def _matches_clause(clause, user) -> bool:
    if clause is None:
        return True
    if hasattr(clause, "clauses"):
        return all(_matches_clause(item, user) for item in clause.clauses)
    left = getattr(clause, "left", None)
    right = getattr(clause, "right", None)
    if getattr(left, "key", None) is None:
        return True
    user_value = _normalize_compare_value(getattr(user, left.key, None))
    expected_value = _normalize_compare_value(_extract_bound_value(right))
    return user_value == expected_value


def _build_client(fake_db: _FakeAsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(users_api.router, prefix="/api/v1")

    async def _override_db():
        yield fake_db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_login_rate_limit_bucket():
    users_api._login_attempt_buckets.clear()
    yield
    users_api._login_attempt_buckets.clear()


def test_production_security_baseline_rejects_placeholder_jwt_secret():
    production_settings = Settings(
        APP_ENV="production",
        JWT_SECRET_KEY="dev-only-jwt-secret-change-me",
    )

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        production_settings.validate_security_baseline()


def test_register_sets_http_only_cookie_and_cookie_can_access_me():
    fake_db = _FakeAsyncSession()
    client = _build_client(fake_db)

    response = client.post(
        "/api/v1/users/register",
        json={
            "username": "traveler",
            "email": "traveler@example.com",
            "password": "strong-pass-123",
        },
    )

    assert response.status_code == 200
    assert settings.auth_cookie_name in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]

    me_response = client.get("/api/v1/users/me")

    assert me_response.status_code == 200
    assert me_response.json()["username"] == "traveler"


def test_logout_clears_auth_cookie():
    fake_db = _FakeAsyncSession()
    client = _build_client(fake_db)

    register_response = client.post(
        "/api/v1/users/register",
        json={
            "username": "logout-user",
            "email": "logout@example.com",
            "password": "strong-pass-123",
        },
    )
    assert register_response.status_code == 200

    logout_response = client.post("/api/v1/users/logout")

    assert logout_response.status_code == 200
    assert f"{settings.auth_cookie_name}=" in logout_response.headers["set-cookie"]
    assert "Max-Age=0" in logout_response.headers["set-cookie"]
    assert client.get("/api/v1/users/me").status_code == 401


def test_login_rate_limit_blocks_repeated_invalid_attempts(monkeypatch: pytest.MonkeyPatch):
    fake_db = _FakeAsyncSession()
    client = _build_client(fake_db)
    client.post(
        "/api/v1/users/register",
        json={
            "username": "rate-limit-user",
            "email": "rate-limit@example.com",
            "password": "correct-pass-123",
        },
    )

    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 2)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 600)

    for _ in range(2):
        response = client.post(
            "/api/v1/users/login",
            json={"username": "rate-limit-user", "password": "wrong-pass"},
        )
        assert response.status_code == 401

    limited_response = client.post(
        "/api/v1/users/login",
        json={"username": "rate-limit-user", "password": "wrong-pass"},
    )

    assert limited_response.status_code == 429
    assert limited_response.json()["detail"]["code"] == "too_many_login_attempts"
