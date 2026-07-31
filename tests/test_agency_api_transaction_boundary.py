from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import main as app_main
from app.agency.errors import AgencyTransactionConflict
from app.agency.transaction_service import AgencyTransactionService
from app.api.dependencies import get_current_user
from app.api.v1 import (
    agency_cancellations,
    agency_common,
    agency_customers,
    agency_transactions,
)


class _PostgresRaiseException(Exception):
    sqlstate = "P0001"


class _CommitFailingSession:
    def __init__(self, commit_error: Exception) -> None:
        self.rollback_count = 0
        self.commit_error = commit_error

    async def commit(self) -> None:
        raise self.commit_error

    async def rollback(self) -> None:
        self.rollback_count += 1


class _FlushFailingSession:
    async def flush(self) -> None:
        raise DBAPIError(
            "FLUSH",
            {},
            _PostgresRaiseException("synthetic trigger rejection"),
        )


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
        agency_cancellations.get_cancellation_service,
    ):
        dependency = inspect.signature(factory).parameters["db"].default

        assert dependency.dependency is agency_common.get_agency_db
        assert dependency.scope == "function"


@pytest.mark.parametrize(
    "commit_error",
    [
        IntegrityError(
            "COMMIT",
            {},
            RuntimeError("synthetic deferred constraint failure"),
        ),
        DBAPIError(
            "COMMIT",
            {},
            _PostgresRaiseException("synthetic deferred trigger rejection"),
        ),
    ],
    ids=["integrity-error", "postgres-raise-exception"],
)
def test_agency_commit_failure_is_returned_before_a_success_response(
    monkeypatch,
    commit_error,
):
    session = _CommitFailingSession(commit_error)
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


@pytest.mark.asyncio
async def test_postgres_trigger_rejection_during_flush_is_a_conflict():
    service = AgencyTransactionService(_FlushFailingSession())

    with pytest.raises(AgencyTransactionConflict) as captured:
        await service._flush()

    assert captured.value.code == "transaction_write_conflict"


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


def test_cancellation_validation_never_echoes_reason_or_evidence_input():
    sensitive_reason = "private-cancellation-reason-" + ("x" * 500)
    sensitive_field_name = "private-secret-token-in-field-name"
    app_main.app.dependency_overrides[get_current_user] = lambda: (
        SimpleNamespace(
            id=uuid.UUID(int=1),
            preferences={"role": "user"},
        )
    )
    try:
        response = TestClient(app_main.app).post(
            f"/api/v1/agency/orders/{uuid.UUID(int=2)}/cancellation-requests",
            json={
                "expected_order_revision": 1,
                "reason_code": "customer_request",
                "reason_detail": sensitive_reason,
                sensitive_field_name: "unexpected",
            },
            headers={"Idempotency-Key": "malformed-cancellation-reason"},
        )
    finally:
        app_main.app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 422
    assert sensitive_reason not in response.text
    assert sensitive_field_name not in response.text
    assert "[REDACTED]" in response.text
