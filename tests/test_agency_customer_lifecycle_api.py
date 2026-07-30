from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
)
from app.api.dependencies import get_current_user
from app.api.v1 import agency_customers as customer_api
from tests.agency_transaction_test_support import (
    AGENCY_ID,
    ADVISOR_ID,
    ASSIGNMENT_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    EVENT_ID,
    MEMBERSHIP_ID,
    NOW,
    ROLE_GRANT_ID,
    copy_record,
)


def _branch_record(**updates) -> SimpleNamespace:
    values = {
        "id": BRANCH_ID,
        "agency_id": AGENCY_ID,
        "branch_code": "SHA_01",
        "name": "上海一店",
        "status": "active",
        "revision": 1,
        "deactivated_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _role_grant_record(**updates) -> SimpleNamespace:
    values = {
        "id": ROLE_GRANT_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "membership_id": MEMBERSHIP_ID,
        "role": "travel_advisor",
        "status": "active",
        "revision": 1,
        "granted_by_user_id": CUSTOMER_ID,
        "reason": "响应中不得暴露授权原因",
        "granted_at": NOW,
        "revoked_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _customer_record(**updates) -> SimpleNamespace:
    values = {
        "id": BUSINESS_CUSTOMER_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "customer_no": "C-20300101-1234567890ABCDEF",
        "user_id": CUSTOMER_ID,
        "source_type": "manual",
        "source_reference": "internal-import-row-42",
        "status": "prospect",
        "consent_status": "pending",
        "consent_version": "privacy-v1",
        "consent_evidence_hash": "a" * 64,
        "consent_updated_at": NOW,
        "lifecycle_revision": 1,
        "invited_at": NOW,
        "activated_at": None,
        "deactivated_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _assignment_record(**updates) -> SimpleNamespace:
    values = {
        "id": ASSIGNMENT_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "advisor_role_grant_id": ROLE_GRANT_ID,
        "advisor_membership_id": MEMBERSHIP_ID,
        "status": "active",
        "revision": 1,
        "assigned_by_user_id": CUSTOMER_ID,
        "reason": "响应中不得暴露分配原因",
        "assigned_at": NOW,
        "ended_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _customer_event_record(**updates) -> SimpleNamespace:
    values = {
        "id": EVENT_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "event_sequence": 1,
        "customer_revision": 1,
        "event_type": "customer_created",
        "from_status": None,
        "to_status": "prospect",
        "actor_user_id": CUSTOMER_ID,
        "event_metadata": {
            "reason": "响应中不得暴露",
            "source_reference": "internal-import-row-42",
        },
        "created_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


class _FakeLifecycleService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.errors: dict[str, Exception] = {}
        self.branch = _branch_record()
        self.grant = _role_grant_record()
        self.customer = _customer_record()
        self.assignment = _assignment_record()
        self.event = _customer_event_record()

    def _capture(self, name: str, values: dict) -> None:
        error = self.errors.get(name)
        if error is not None:
            raise error
        self.calls.append((name, values))

    async def create_branch(self, **kwargs):
        self._capture("create_branch", kwargs)
        return self.branch

    async def list_branches(self, **kwargs):
        self._capture("list_branches", kwargs)
        return [self.branch], 1

    async def create_branch_role_grant(self, **kwargs):
        self._capture("create_branch_role_grant", kwargs)
        return self.grant

    async def list_branch_role_grants(self, **kwargs):
        self._capture("list_branch_role_grants", kwargs)
        return [self.grant], 1

    async def revoke_branch_role_grant(self, **kwargs):
        self._capture("revoke_branch_role_grant", kwargs)
        return copy_record(
            self.grant,
            status="revoked",
            revision=2,
            revoked_at=NOW,
        )

    async def create_customer(self, **kwargs):
        self._capture("create_customer", kwargs)
        return self.customer

    async def list_customers(self, **kwargs):
        self._capture("list_customers", kwargs)
        return [self.customer], 1

    async def get_customer(self, **kwargs):
        self._capture("get_customer", kwargs)
        return self.customer

    async def link_customer_user(self, **kwargs):
        self._capture("link_customer_user", kwargs)
        return copy_record(self.customer, lifecycle_revision=2)

    async def record_customer_consent(self, **kwargs):
        self._capture("record_customer_consent", kwargs)
        return copy_record(
            self.customer,
            consent_status="granted",
            lifecycle_revision=3,
        )

    async def activate_customer(self, **kwargs):
        self._capture("activate_customer", kwargs)
        return copy_record(
            self.customer,
            status="active",
            consent_status="granted",
            lifecycle_revision=4,
            activated_at=NOW,
        )

    async def deactivate_customer(self, **kwargs):
        self._capture("deactivate_customer", kwargs)
        return copy_record(
            self.customer,
            status="inactive",
            lifecycle_revision=5,
            deactivated_at=NOW,
        )

    async def assign_customer_advisor(self, **kwargs):
        self._capture("assign_customer_advisor", kwargs)
        return self.assignment

    async def end_customer_advisor_assignment(self, **kwargs):
        self._capture("end_customer_advisor_assignment", kwargs)
        return copy_record(
            self.assignment,
            status="ended",
            revision=2,
            ended_at=NOW,
        )

    async def list_customer_advisor_assignments(self, **kwargs):
        self._capture("list_customer_advisor_assignments", kwargs)
        return [self.assignment], 1

    async def list_customer_events(self, **kwargs):
        self._capture("list_customer_events", kwargs)
        return [self.event], 1


def _build_client(
    service: _FakeLifecycleService,
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


def _post_cases() -> list[tuple[str, dict]]:
    return [
        (
            "/api/v1/agency/branches",
            {
                "agency_id": str(AGENCY_ID),
                "branch_code": "sha_01",
                "name": "上海一店",
            },
        ),
        (
            f"/api/v1/agency/branches/{BRANCH_ID}/role-grants",
            {
                "membership_id": str(MEMBERSHIP_ID),
                "role": "travel_advisor",
            },
        ),
        (
            (
                f"/api/v1/agency/branches/{BRANCH_ID}/role-grants/"
                f"{ROLE_GRANT_ID}/revoke"
            ),
            {"expected_revision": 1, "reason": "人员调岗"},
        ),
        (
            "/api/v1/agency/customers",
            {
                "agency_id": str(AGENCY_ID),
                "branch_id": str(BRANCH_ID),
                "source_type": "manual",
            },
        ),
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/link-user",
            {"expected_revision": 1, "user_id": str(CUSTOMER_ID)},
        ),
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/consent",
            {
                "expected_revision": 2,
                "decision": "grant",
                "consent_version": "privacy-v1",
                "consent_evidence_hash": "A" * 64,
            },
        ),
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/activate",
            {"expected_revision": 3},
        ),
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/deactivate",
            {"expected_revision": 4, "reason": "客户主动终止服务"},
        ),
        (
            (
                f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
                "advisor-assignments"
            ),
            {
                "expected_revision": 5,
                "advisor_role_grant_id": str(ROLE_GRANT_ID),
                "reason": "转交目的地专家",
            },
        ),
        (
            (
                f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
                "advisor-assignments/end"
            ),
            {
                "expected_revision": 6,
                "reason": "顾问离职且暂无接替人",
            },
        ),
    ]


@pytest.mark.parametrize(("path", "payload"), _post_cases())
def test_all_ten_lifecycle_posts_require_idempotency_key(
    path: str,
    payload: dict,
):
    response = _build_client(_FakeLifecycleService()).post(path, json=payload)

    assert response.status_code == 422


def test_lifecycle_router_exposes_sixteen_operations_and_ten_posts():
    routes = [
        route
        for route in customer_api.router.routes
        if hasattr(route, "path")
    ]
    operations = sum(len(route.methods or set()) for route in routes)
    posts = sum("POST" in (route.methods or set()) for route in routes)

    assert len(routes) == 16
    assert operations == 16
    assert posts == 10


def test_lifecycle_commands_forward_revisions_and_idempotency():
    service = _FakeLifecycleService()
    client = _build_client(service, user_id=ADVISOR_ID)

    responses = [
        client.post(
            path,
            json=payload,
            headers={"Idempotency-Key": f"lifecycle-{index}"},
        )
        for index, (path, payload) in enumerate(_post_cases(), start=1)
    ]

    assert [response.status_code for response in responses] == [
        201,
        201,
        200,
        201,
        200,
        200,
        200,
        200,
        201,
        200,
    ]
    calls = {name: values for name, values in service.calls}
    assert calls["create_branch"]["data"].branch_code == "SHA_01"
    assert calls["create_branch"]["idempotency_key"] == "lifecycle-1"
    assert calls["create_branch_role_grant"]["branch_id"] == BRANCH_ID
    assert calls["revoke_branch_role_grant"] == {
        "actor_user_id": ADVISOR_ID,
        "branch_id": BRANCH_ID,
        "grant_id": ROLE_GRANT_ID,
        "expected_revision": 1,
        "reason": "人员调岗",
        "idempotency_key": "lifecycle-3",
    }
    assert calls["create_customer"]["data"].branch_id == BRANCH_ID
    assert calls["link_customer_user"]["expected_revision"] == 1
    assert calls["link_customer_user"]["user_id"] == CUSTOMER_ID
    assert calls["record_customer_consent"]["expected_revision"] == 2
    assert (
        calls["record_customer_consent"]["consent_evidence_hash"]
        == "a" * 64
    )
    assert calls["activate_customer"]["expected_revision"] == 3
    assert calls["deactivate_customer"]["expected_revision"] == 4
    assert calls["deactivate_customer"]["reason"] == "客户主动终止服务"
    assert calls["assign_customer_advisor"]["expected_revision"] == 5
    assert (
        calls["assign_customer_advisor"]["advisor_role_grant_id"]
        == ROLE_GRANT_ID
    )
    assert calls["end_customer_advisor_assignment"]["expected_revision"] == 6
    assert (
        calls["end_customer_advisor_assignment"]["reason"]
        == "顾问离职且暂无接替人"
    )


def test_lifecycle_reads_forward_scope_filters_and_pagination():
    service = _FakeLifecycleService()
    client = _build_client(service, user_id=ADVISOR_ID)

    responses = [
        client.get(
            "/api/v1/agency/branches",
            params={
                "agency_id": str(AGENCY_ID),
                "status": "active",
                "limit": 10,
                "offset": 1,
            },
        ),
        client.get(
            f"/api/v1/agency/branches/{BRANCH_ID}/role-grants",
            params={"status": "active", "limit": 11, "offset": 2},
        ),
        client.get(
            "/api/v1/agency/customers",
            params={
                "agency_id": str(AGENCY_ID),
                "branch_id": str(BRANCH_ID),
                "status": "prospect",
                "limit": 12,
                "offset": 3,
            },
        ),
        client.get(
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}",
        ),
        client.get(
            (
                f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
                "advisor-assignments"
            ),
            params={"status": "active", "limit": 13, "offset": 4},
        ),
        client.get(
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/events",
            params={"limit": 14, "offset": 5},
        ),
    ]

    assert all(response.status_code == 200 for response in responses)
    calls = {name: values for name, values in service.calls}
    assert calls["list_branches"]["status_filter"] == "active"
    assert calls["list_branches"]["limit"] == 10
    assert calls["list_branch_role_grants"]["branch_id"] == BRANCH_ID
    assert calls["list_branch_role_grants"]["offset"] == 2
    assert calls["list_customers"]["branch_id"] == BRANCH_ID
    assert calls["list_customers"]["status_filter"] == "prospect"
    assert calls["get_customer"]["customer_id"] == BUSINESS_CUSTOMER_ID
    assert (
        calls["list_customer_advisor_assignments"]["status_filter"]
        == "active"
    )
    assert calls["list_customer_events"]["limit"] == 14
    assert calls["list_customer_events"]["offset"] == 5


def test_lifecycle_responses_exclude_internal_identity_evidence_and_reasons():
    service = _FakeLifecycleService()
    client = _build_client(service)

    customer = client.get(
        f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}"
    ).json()
    grant = client.get(
        f"/api/v1/agency/branches/{BRANCH_ID}/role-grants"
    ).json()["grants"][0]
    assignment = client.get(
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
            "advisor-assignments"
        )
    ).json()["assignments"][0]
    event = client.get(
        f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/events"
    ).json()["events"][0]

    assert "user_id" not in customer
    assert "source_reference" not in customer
    assert "consent_evidence_hash" not in customer
    assert "granted_by_user_id" not in grant
    assert "reason" not in grant
    assert "assigned_by_user_id" not in assignment
    assert "reason" not in assignment
    assert "actor_user_id" not in event
    assert "event_metadata" not in event
    assert "reason" not in event


@pytest.mark.parametrize(
    ("method_name", "error", "expected_status", "expected_code"),
    [
        (
            "get_customer",
            AgencyTransactionNotFound(
                "agency_transaction_not_found",
                "交易资源不存在",
            ),
            404,
            "agency_transaction_not_found",
        ),
        (
            "assign_customer_advisor",
            AgencyTransactionConflict(
                "customer_advisor_assignment_conflict",
                "客户已由其他顾问负责",
            ),
            409,
            "customer_advisor_assignment_conflict",
        ),
    ],
)
def test_lifecycle_api_keeps_stable_not_found_and_conflict_mapping(
    method_name: str,
    error: Exception,
    expected_status: int,
    expected_code: str,
):
    service = _FakeLifecycleService()
    service.errors[method_name] = error
    client = _build_client(service)

    if method_name == "get_customer":
        response = client.get(
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}"
        )
    else:
        response = client.post(
            (
                f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
                "advisor-assignments"
            ),
            json={
                "expected_revision": 1,
                "advisor_role_grant_id": str(ROLE_GRANT_ID),
            },
            headers={"Idempotency-Key": "assignment-conflict"},
        )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
