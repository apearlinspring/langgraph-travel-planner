from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.api.v1 import agency_customers as customer_api
from tests.agency_transaction_test_support import (
    AGENCY_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    NOW,
    ROLE_GRANT_ID,
)


TARGET_BRANCH_ID = uuid.UUID("12345678-1234-5678-8234-567812345678")
TRANSFER_ID = uuid.UUID("12345678-1234-5678-8234-567812345679")


def _branch_record(**updates) -> SimpleNamespace:
    values = {
        "id": BRANCH_ID,
        "agency_id": AGENCY_ID,
        "branch_code": "SHA_01",
        "name": "上海一店",
        "status": "active",
        "revision": 1,
        "deactivated_at": None,
        "closed_at": None,
        "deactivated_by_user_id": CUSTOMER_ID,
        "closed_by_user_id": CUSTOMER_ID,
        "reason": "响应不得暴露门店状态变更原因",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _transfer_record() -> SimpleNamespace:
    return SimpleNamespace(
        id=TRANSFER_ID,
        agency_id=AGENCY_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        from_branch_id=BRANCH_ID,
        to_branch_id=TARGET_BRANCH_ID,
        customer_revision=8,
        transferred_by_user_id=CUSTOMER_ID,
        reason="响应不得暴露客户转店原因",
        transferred_at=NOW,
        created_at=NOW,
    )


def _readiness_record() -> dict:
    return {
        "branch_id": BRANCH_ID,
        "status": "inactive",
        "revision": 2,
        "ready": False,
        "current_customer_count": 2,
        "pending_invitation_count": 1,
        "active_assignment_count": 1,
        "active_role_grant_count": 3,
        "pending_review_count": 1,
        "open_quote_count": 1,
        "open_order_count": 1,
        "open_cancellation_case_count": 0,
        "actor_user_id": str(CUSTOMER_ID),
        "reason": "响应不得暴露关闭检查内部原因",
        "customer_ids": [str(BUSINESS_CUSTOMER_ID)],
    }


class _FakeBranchLifecycleService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _capture(self, name: str, values: dict) -> None:
        self.calls.append((name, values))

    async def deactivate_branch(self, **kwargs):
        self._capture("deactivate_branch", kwargs)
        return _branch_record(
            status="inactive",
            revision=2,
            deactivated_at=NOW,
        )

    async def get_branch_closure_readiness(self, **kwargs):
        self._capture("get_branch_closure_readiness", kwargs)
        return _readiness_record()

    async def close_branch(self, **kwargs):
        self._capture("close_branch", kwargs)
        return _branch_record(
            status="closed",
            revision=3,
            deactivated_at=NOW,
            closed_at=NOW,
        )

    async def transfer_customer_branch(self, **kwargs):
        self._capture("transfer_customer_branch", kwargs)
        return _transfer_record()


def _build_client(
    service: _FakeBranchLifecycleService,
    *,
    user_id: uuid.UUID = CUSTOMER_ID,
) -> TestClient:
    app = FastAPI()
    app.include_router(customer_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id,
        preferences={"role": "user"},
    )
    app.dependency_overrides[
        customer_api.get_customer_lifecycle_service
    ] = lambda: service
    return TestClient(app)


def _response_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(_response_keys(item) for item in value.values()),
            set(),
        )
    if isinstance(value, list):
        return set().union(*(_response_keys(item) for item in value), set())
    return set()


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        (
            f"/api/v1/agency/branches/{BRANCH_ID}/deactivate",
            {"expected_revision": 1, "reason": "停止接收新业务"},
        ),
        (
            f"/api/v1/agency/branches/{BRANCH_ID}/close",
            {"expected_revision": 2, "reason": "存量业务已清理"},
        ),
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/transfer",
            {
                "expected_revision": 7,
                "target_branch_id": str(TARGET_BRANCH_ID),
                "reason": "转入目标门店",
            },
        ),
    ),
)
def test_branch_lifecycle_writes_require_idempotency_key(path, payload):
    service = _FakeBranchLifecycleService()

    response = _build_client(service).post(path, json=payload)

    assert response.status_code == 422
    assert service.calls == []


def test_branch_lifecycle_routes_forward_all_command_parameters():
    service = _FakeBranchLifecycleService()
    client = _build_client(service)

    deactivate = client.post(
        f"/api/v1/agency/branches/{BRANCH_ID}/deactivate",
        json={"expected_revision": 1, "reason": "停止接收新业务"},
        headers={"Idempotency-Key": "branch-deactivate-1"},
    )
    readiness = client.get(
        f"/api/v1/agency/branches/{BRANCH_ID}/closure-readiness"
    )
    close = client.post(
        f"/api/v1/agency/branches/{BRANCH_ID}/close",
        json={"expected_revision": 2, "reason": "存量业务已清理"},
        headers={"Idempotency-Key": "branch-close-1"},
    )
    transfer = client.post(
        f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/transfer",
        json={
            "expected_revision": 7,
            "target_branch_id": str(TARGET_BRANCH_ID),
            "target_advisor_role_grant_id": str(ROLE_GRANT_ID),
            "reason": "转入目标门店",
        },
        headers={"Idempotency-Key": "customer-transfer-1"},
    )

    assert [
        deactivate.status_code,
        readiness.status_code,
        close.status_code,
        transfer.status_code,
    ] == [200, 200, 200, 201]
    assert service.calls == [
        (
            "deactivate_branch",
            {
                "actor_user_id": CUSTOMER_ID,
                "branch_id": BRANCH_ID,
                "expected_revision": 1,
                "reason": "停止接收新业务",
                "idempotency_key": "branch-deactivate-1",
            },
        ),
        (
            "get_branch_closure_readiness",
            {
                "actor_user_id": CUSTOMER_ID,
                "branch_id": BRANCH_ID,
            },
        ),
        (
            "close_branch",
            {
                "actor_user_id": CUSTOMER_ID,
                "branch_id": BRANCH_ID,
                "expected_revision": 2,
                "reason": "存量业务已清理",
                "idempotency_key": "branch-close-1",
            },
        ),
        (
            "transfer_customer_branch",
            {
                "actor_user_id": CUSTOMER_ID,
                "customer_id": BUSINESS_CUSTOMER_ID,
                "expected_revision": 7,
                "target_branch_id": TARGET_BRANCH_ID,
                "target_advisor_role_grant_id": ROLE_GRANT_ID,
                "reason": "转入目标门店",
                "idempotency_key": "customer-transfer-1",
            },
        ),
    ]


def test_branch_lifecycle_responses_redact_internal_fields_and_ids():
    client = _build_client(_FakeBranchLifecycleService())

    deactivate = client.post(
        f"/api/v1/agency/branches/{BRANCH_ID}/deactivate",
        json={"expected_revision": 1, "reason": "停止接收新业务"},
        headers={"Idempotency-Key": "branch-deactivate-redaction"},
    ).json()
    readiness = client.get(
        f"/api/v1/agency/branches/{BRANCH_ID}/closure-readiness"
    ).json()
    close = client.post(
        f"/api/v1/agency/branches/{BRANCH_ID}/close",
        json={"expected_revision": 2, "reason": "存量业务已清理"},
        headers={"Idempotency-Key": "branch-close-redaction"},
    ).json()
    transfer = client.post(
        f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/transfer",
        json={
            "expected_revision": 7,
            "target_branch_id": str(TARGET_BRANCH_ID),
            "reason": "转入目标门店",
        },
        headers={"Idempotency-Key": "customer-transfer-redaction"},
    ).json()

    forbidden = {
        "reason",
        "actor_user_id",
        "transferred_by_user_id",
        "deactivated_by_user_id",
        "closed_by_user_id",
        "customer_ids",
        "order_ids",
        "event_metadata",
    }
    assert _response_keys(deactivate).isdisjoint(forbidden)
    assert _response_keys(readiness).isdisjoint(forbidden)
    assert _response_keys(close).isdisjoint(forbidden)
    assert _response_keys(transfer).isdisjoint(forbidden)
    assert transfer["from_branch_id"] == str(BRANCH_ID)
    assert transfer["to_branch_id"] == str(TARGET_BRANCH_ID)
