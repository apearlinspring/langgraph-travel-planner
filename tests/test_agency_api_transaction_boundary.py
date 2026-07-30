from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_current_user
from app.api.v1 import (
    agency_common,
    agency_customers,
    agency_transactions,
)
from app import main as app_main


class _CommitFailingSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    async def commit(self) -> None:
        raise IntegrityError(
            "COMMIT",
            {},
            RuntimeError("synthetic deferred constraint failure"),
        )

    async def rollback(self) -> None:
        self.rollback_count += 1


class _SessionContext:
    def __init__(self, session: _CommitFailingSession) -> None:
        self.session = session

    async def __aenter__(self) -> _CommitFailingSession:
        return self.session

    async def __aexit__(self, *_args) -> None:
        return None


def test_all_agency_services_use_function_scoped_transaction_dependency():
    for factory in (
        agency_customers.get_customer_lifecycle_service,
        agency_transactions.get_agency_transaction_service,
    ):
        dependency = inspect.signature(factory).parameters["db"].default

        assert dependency.dependency is agency_common.get_agency_db
        assert dependency.scope == "function"


def test_agency_commit_failure_is_returned_before_a_success_response(
    monkeypatch,
):
    session = _CommitFailingSession()
    monkeypatch.setattr(
        agency_common,
        "async_session_maker",
        lambda: _SessionContext(session),
    )
    app = FastAPI()

    @app.post("/write")
    async def write(
        _session=Depends(agency_common.get_agency_db, scope="function"),
    ):
        return {"ok": True}

    response = TestClient(app, raise_server_exceptions=False).post("/write")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "transaction_write_conflict"
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"claim_token": "synthetic-secret-token"},
        "synthetic-secret-token",
        ["synthetic-secret-token"],
        {"code": "synthetic-secret-token"},
    ],
)
def test_customer_claim_validation_never_echoes_token_and_is_not_cached(
    payload,
):
    token = "synthetic-secret-token"
    app_main.app.dependency_overrides[get_current_user] = lambda: (
        SimpleNamespace(
            id=uuid.UUID(int=1),
            preferences={"role": "user"},
        )
    )
    try:
        response = TestClient(app_main.app).post(
            "/api/v1/agency/customer-claims",
            json=payload,
            headers={"Idempotency-Key": "malformed-claim-token"},
        )
    finally:
        app_main.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 422
    assert token not in response.text
    assert "[REDACTED]" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
