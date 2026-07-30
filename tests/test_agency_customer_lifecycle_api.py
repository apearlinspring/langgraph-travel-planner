from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agency.customer_consent import (
    CUSTOMER_CONSENT_DOCUMENT_SHA256,
    CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
    CUSTOMER_CONSENT_NOTICE_MARKDOWN,
    CUSTOMER_CONSENT_VERSION,
)
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

INVITATION_ID = uuid.UUID("12345678-1234-5678-9234-567812345678")
CLAIM_TOKEN = "A" * 43


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
        "user_id": None,
        "binding_provenance": "unbound",
        "claimed_invitation_id": None,
        "claimed_at": None,
        "source_type": "manual",
        "source_reference": "internal-import-row-42",
        "status": "prospect",
        "consent_status": "unknown",
        "consent_version": None,
        "consent_evidence_hash": None,
        "current_consent_record_id": None,
        "consent_evidence_origin": "none",
        "consent_updated_at": None,
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


def _claim_invitation_record(**updates) -> SimpleNamespace:
    values = {
        "id": INVITATION_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "target_user_id": CUSTOMER_ID,
        "token_digest": "b" * 64,
        "status": "pending",
        "revision": 1,
        "issued_by_user_id": ADVISOR_ID,
        "claimed_by_user_id": None,
        "revoked_by_user_id": None,
        "revocation_reason": None,
        "issued_at": NOW,
        "expires_at": NOW,
        "claimed_at": None,
        "revoked_at": None,
        "created_at": NOW,
        "updated_at": NOW,
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
        self.invitation = _claim_invitation_record()
        self.issue_count = 0

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

    async def issue_customer_claim_invitation(self, **kwargs):
        self._capture("issue_customer_claim_invitation", kwargs)
        self.issue_count += 1
        claim_token = CLAIM_TOKEN if self.issue_count == 1 else None
        return self.invitation, claim_token

    async def list_customer_claim_invitations(self, **kwargs):
        self._capture("list_customer_claim_invitations", kwargs)
        return [self.invitation], 1

    async def revoke_customer_claim_invitation(self, **kwargs):
        self._capture("revoke_customer_claim_invitation", kwargs)
        return copy_record(
            self.invitation,
            status="revoked",
            revision=2,
            revoked_by_user_id=ADVISOR_ID,
            revocation_reason="客户要求重新发送",
            revoked_at=NOW,
        )

    async def claim_customer(self, **kwargs):
        self._capture("claim_customer", kwargs)
        return copy_record(
            self.customer,
            user_id=CUSTOMER_ID,
            binding_provenance="secure_claim",
            claimed_invitation_id=INVITATION_ID,
            claimed_at=NOW,
            status="invited",
            lifecycle_revision=2,
        )

    async def record_customer_consent(self, **kwargs):
        self._capture("record_customer_consent", kwargs)
        return copy_record(
            self.customer,
            user_id=CUSTOMER_ID,
            binding_provenance="secure_claim",
            claimed_invitation_id=INVITATION_ID,
            claimed_at=NOW,
            status="invited",
            consent_status="granted",
            consent_version=CUSTOMER_CONSENT_VERSION,
            consent_evidence_hash="a" * 64,
            current_consent_record_id=uuid.uuid4(),
            consent_evidence_origin="server_canonical",
            consent_updated_at=NOW,
            lifecycle_revision=3,
        )

    async def activate_customer(self, **kwargs):
        self._capture("activate_customer", kwargs)
        return copy_record(
            self.customer,
            user_id=CUSTOMER_ID,
            binding_provenance="secure_claim",
            claimed_invitation_id=INVITATION_ID,
            claimed_at=NOW,
            status="active",
            consent_status="granted",
            consent_version=CUSTOMER_CONSENT_VERSION,
            consent_evidence_hash="a" * 64,
            current_consent_record_id=uuid.uuid4(),
            consent_evidence_origin="server_canonical",
            consent_updated_at=NOW,
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


def _response_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(
            *(_response_keys(item) for item in value.values()),
            set(),
        )
    if isinstance(value, list):
        return set().union(*(_response_keys(item) for item in value), set())
    return set()


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
            (
                f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
                "claim-invitations"
            ),
            {
                "expected_revision": 1,
                "target_user_id": str(CUSTOMER_ID),
            },
        ),
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/consent",
            {
                "expected_revision": 2,
                "decision": "grant",
                "expected_notice_version": CUSTOMER_CONSENT_VERSION,
                "expected_notice_document_sha256": (
                    CUSTOMER_CONSENT_DOCUMENT_SHA256
                ),
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
        (
            (
                f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
                f"claim-invitations/{INVITATION_ID}/revoke"
            ),
            {
                "expected_revision": 7,
                "expected_invitation_revision": 1,
                "reason": "客户要求重新发送",
            },
        ),
        (
            "/api/v1/agency/customer-claims",
            {"claim_token": CLAIM_TOKEN},
        ),
    ]


@pytest.mark.parametrize(("path", "payload"), _post_cases())
def test_all_twelve_lifecycle_posts_require_idempotency_key(
    path: str,
    payload: dict,
):
    response = _build_client(_FakeLifecycleService()).post(path, json=payload)

    assert response.status_code == 422


def test_lifecycle_router_exposes_twenty_operations_and_twelve_posts():
    routes = [
        route
        for route in customer_api.router.routes
        if hasattr(route, "path")
    ]
    operations = sum(len(route.methods or set()) for route in routes)
    posts = sum("POST" in (route.methods or set()) for route in routes)

    assert len(routes) == 20
    assert operations == 20
    assert posts == 12


def test_customer_create_rejects_direct_user_binding():
    service = _FakeLifecycleService()
    response = _build_client(service).post(
        "/api/v1/agency/customers",
        json={
            "agency_id": str(AGENCY_ID),
            "branch_id": str(BRANCH_ID),
            "source_type": "manual",
            "user_id": str(CUSTOMER_ID),
        },
        headers={"Idempotency-Key": "customer-direct-user-forbidden"},
    )

    assert response.status_code == 422
    assert service.calls == []


def test_customer_link_user_route_is_removed():
    route_paths = {
        route.path
        for route in customer_api.router.routes
        if hasattr(route, "path")
    }

    assert "/agency/customers/{customer_id}/link-user" not in route_paths


def test_customer_consent_rejects_client_supplied_evidence():
    service = _FakeLifecycleService()
    response = _build_client(service).post(
        f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/consent",
        json={
            "expected_revision": 2,
            "decision": "grant",
            "expected_notice_version": CUSTOMER_CONSENT_VERSION,
            "expected_notice_document_sha256": (
                CUSTOMER_CONSENT_DOCUMENT_SHA256
            ),
            "consent_version": "privacy-v1",
            "consent_evidence_hash": "a" * 64,
        },
        headers={"Idempotency-Key": "consent-client-evidence-forbidden"},
    )

    assert response.status_code == 422
    assert service.calls == []


def test_customer_consent_notice_exposes_the_fixed_display_contract():
    response = _build_client(_FakeLifecycleService()).get(
        "/api/v1/agency/customer-consent-notice"
    )

    assert response.status_code == 200
    assert response.json() == {
        "consent_version": CUSTOMER_CONSENT_VERSION,
        "consent_document_sha256": CUSTOMER_CONSENT_DOCUMENT_SHA256,
        "evidence_schema_version": CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
        "channel": "authenticated_api",
        "notice_markdown": CUSTOMER_CONSENT_NOTICE_MARKDOWN,
    }


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
        201,
        200,
        200,
        200,
        201,
        200,
        200,
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
    assert not hasattr(calls["create_customer"]["data"], "user_id")
    assert calls["issue_customer_claim_invitation"] == {
        "actor_user_id": ADVISOR_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "expected_revision": 1,
        "target_user_id": CUSTOMER_ID,
        "idempotency_key": "lifecycle-5",
    }
    assert calls["record_customer_consent"] == {
        "actor_user_id": ADVISOR_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "expected_revision": 2,
        "decision": "grant",
        "expected_notice_version": CUSTOMER_CONSENT_VERSION,
        "expected_notice_document_sha256": (
            CUSTOMER_CONSENT_DOCUMENT_SHA256
        ),
        "idempotency_key": "lifecycle-6",
    }
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
    assert calls["revoke_customer_claim_invitation"] == {
        "actor_user_id": ADVISOR_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "invitation_id": INVITATION_ID,
        "expected_revision": 7,
        "expected_invitation_revision": 1,
        "reason": "客户要求重新发送",
        "idempotency_key": "lifecycle-11",
    }
    assert calls["claim_customer"] == {
        "actor_user_id": ADVISOR_ID,
        "claim_token": CLAIM_TOKEN,
        "idempotency_key": "lifecycle-12",
    }


def test_claim_invitation_token_is_returned_once_and_never_by_list():
    service = _FakeLifecycleService()
    client = _build_client(service, user_id=ADVISOR_ID)
    path = (
        f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
        "claim-invitations"
    )
    payload = {
        "expected_revision": 1,
        "target_user_id": str(CUSTOMER_ID),
    }
    headers = {"Idempotency-Key": "claim-invitation-replay"}

    first = client.post(path, json=payload, headers=headers)
    replay = client.post(path, json=payload, headers=headers)
    listed = client.get(path)

    assert first.status_code == 201
    assert first.json()["claim_token"] == CLAIM_TOKEN
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["pragma"] == "no-cache"
    assert replay.status_code == 201
    assert replay.json().get("claim_token") is None
    assert listed.status_code == 200
    assert "claim_token" not in _response_keys(listed.json())

    forbidden_keys = {
        "user_id",
        "target_user_id",
        "token_hash",
        "token_digest",
        "issued_by_user_id",
        "claimed_by_user_id",
        "revoked_by_user_id",
        "revocation_reason",
    }
    assert _response_keys(first.json()).isdisjoint(forbidden_keys)
    assert _response_keys(replay.json()).isdisjoint(forbidden_keys)
    assert _response_keys(listed.json()).isdisjoint(forbidden_keys)


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
                "claim-invitations"
            ),
            params={"limit": 15, "offset": 6},
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
        calls["list_customer_claim_invitations"]["customer_id"]
        == BUSINESS_CUSTOMER_ID
    )
    assert calls["list_customer_claim_invitations"]["limit"] == 15
    assert calls["list_customer_claim_invitations"]["offset"] == 6
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
    invitation_list = client.get(
        (
            f"/api/v1/agency/customers/{BUSINESS_CUSTOMER_ID}/"
            "claim-invitations"
        )
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
    assert _response_keys(invitation_list).isdisjoint(
        {
            "claim_token",
            "user_id",
            "target_user_id",
            "token_hash",
            "token_digest",
            "issued_by_user_id",
            "claimed_by_user_id",
            "revoked_by_user_id",
            "revocation_reason",
        }
    )
    assert "granted_by_user_id" not in grant
    assert "reason" not in grant
    assert "assigned_by_user_id" not in assignment
    assert "reason" not in assignment
    assert "actor_user_id" not in event
    assert "user_id" not in event
    assert "event_metadata" not in event
    assert "reason" not in event
    assert "claim_token" not in event
    assert "token_hash" not in event
    assert "token_digest" not in event
    assert "target_user_id" not in event


def test_customer_claim_error_does_not_echo_token_hash_or_user_identity():
    service = _FakeLifecycleService()
    service.errors["claim_customer"] = AgencyTransactionConflict(
        "customer_claim_invalid",
        "认领凭据无效、已使用或已过期",
    )
    response = _build_client(service).post(
        "/api/v1/agency/customer-claims",
        json={"claim_token": CLAIM_TOKEN},
        headers={"Idempotency-Key": "customer-claim-invalid"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "customer_claim_invalid",
        "message": "认领凭据无效、已使用或已过期",
    }
    assert CLAIM_TOKEN not in response.text
    assert _response_keys(response.json()).isdisjoint(
        {
            "claim_token",
            "token_hash",
            "token_digest",
            "target_user_id",
            "user_id",
        }
    )


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
