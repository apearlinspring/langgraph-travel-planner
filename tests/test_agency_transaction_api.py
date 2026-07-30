from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.agency.branch_authorization import BranchAuthorization
from app.agency.transaction_service import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
    AgencyTransactionService,
    AgencyTransactionValidationError,
    canonical_payload_hash,
)
from app.api.dependencies import get_current_user
from app.api.v1 import agency_transactions as transaction_api
from app.models.agency_transaction import IdempotencyRecord
from app.schemas.agency_transaction import (
    AgencyOrderReviewDecisionRequest,
    AgencyQuoteCreateRequest,
)
from tests.agency_transaction_test_support import (
    AGENCY_ID,
    ADVISOR_ID,
    APPROVER_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    NOW,
    ORDER_ID,
    QUOTE_ID,
    ExecuteSequence as _ExecuteSequence,
    copy_record as _copy_record,
    event_record as _event_record,
    order_record as _order_record,
    quote_record as _quote_record,
    review_record as _review_record,
)


class _FakeTransactionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.errors: dict[str, Exception] = {}
        self.quote = _quote_record()
        self.order = _order_record()
        self.event = _event_record()
        self.review = _review_record()

    def _capture(self, name: str, values: dict) -> None:
        error = self.errors.get(name)
        if error is not None:
            raise error
        self.calls.append((name, values))

    async def create_quote(self, **kwargs):
        self._capture("create_quote", kwargs)
        return self.quote

    async def list_quotes(self, **kwargs):
        self._capture("list_quotes", kwargs)
        return [self.quote], 1

    async def get_quote(self, **kwargs):
        self._capture("get_quote", kwargs)
        return self.quote

    async def issue_quote(self, **kwargs):
        self._capture("issue_quote", kwargs)
        return _copy_record(
            self.quote,
            status="offered",
            revision=2,
            issued_at=NOW,
        )

    async def accept_quote(self, **kwargs):
        self._capture("accept_quote", kwargs)
        return _copy_record(
            self.quote,
            status="accepted",
            revision=3,
            issued_at=NOW,
            accepted_at=NOW,
        )

    async def create_order(self, **kwargs):
        self._capture("create_order", kwargs)
        return self.order

    async def list_orders(self, **kwargs):
        self._capture("list_orders", kwargs)
        return [self.order], 1

    async def get_order(self, **kwargs):
        self._capture("get_order", kwargs)
        return self.order

    async def list_order_events(self, **kwargs):
        self._capture("list_order_events", kwargs)
        return [self.event], 1

    async def submit_order(self, **kwargs):
        self._capture("submit_order", kwargs)
        return _copy_record(
            self.order,
            status="pending_review",
            revision=2,
        )

    async def list_order_reviews(self, **kwargs):
        self._capture("list_order_reviews", kwargs)
        return [self.review], 1

    async def get_order_review(self, **kwargs):
        self._capture("get_order_review", kwargs)
        return self.review

    async def decide_order_review(self, **kwargs):
        self._capture("decide_order_review", kwargs)
        approved = kwargs["decision"] == "approve"
        return _copy_record(
            self.review,
            status="approved" if approved else "rejected",
            decision_order_revision=3,
            decided_by_user_id=kwargs["actor_user_id"],
            decision_reason=kwargs["reason"],
            decided_at=NOW,
        )


def _build_client(
    service: _FakeTransactionService,
    *,
    user_id: uuid.UUID = CUSTOMER_ID,
) -> TestClient:
    app = FastAPI()
    app.include_router(transaction_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id,
        preferences={"role": "user"},
    )
    app.dependency_overrides[
        transaction_api.get_agency_transaction_service
    ] = lambda: service
    return TestClient(app)


def _quote_create_payload() -> dict:
    return {
        "agency_id": str(AGENCY_ID),
        "customer_id": str(BUSINESS_CUSTOMER_ID),
        "total_amount": "1288.50",
        "currency": "cny",
        "quote_snapshot": {"destination": "杭州", "days": 3},
        "valid_until": "2030-01-03T08:00:00Z",
    }


def test_quote_schema_rejects_non_ascii_currency_and_oversized_snapshot():
    with pytest.raises(ValueError, match="ASCII"):
        AgencyQuoteCreateRequest.model_validate(
            {
                **_quote_create_payload(),
                "currency": "人民币",
            }
        )

    with pytest.raises(ValueError, match="256 KiB"):
        AgencyQuoteCreateRequest.model_validate(
            {
                **_quote_create_payload(),
                "quote_snapshot": {"raw": "x" * (256 * 1024)},
            }
        )


def test_order_review_schema_requires_a_rejection_reason():
    with pytest.raises(ValueError, match="reason"):
        AgencyOrderReviewDecisionRequest.model_validate(
            {
                "decision": "reject",
                "expected_revision": 2,
                "reason": "   ",
            }
        )

    approved = AgencyOrderReviewDecisionRequest.model_validate(
        {
            "decision": "approve",
            "expected_revision": 2,
        }
    )
    assert approved.reason is None


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/agency/quotes", _quote_create_payload()),
        (
            f"/api/v1/agency/quotes/{QUOTE_ID}/issue",
            {"expected_revision": 1},
        ),
        (
            f"/api/v1/agency/quotes/{QUOTE_ID}/accept",
            {"expected_revision": 2},
        ),
        (
            "/api/v1/agency/orders",
            {
                "agency_id": str(AGENCY_ID),
                "quote_id": str(QUOTE_ID),
                "expected_quote_revision": 3,
            },
        ),
        (
            f"/api/v1/agency/orders/{ORDER_ID}/submit",
            {"expected_revision": 1},
        ),
        (
            f"/api/v1/agency/orders/{ORDER_ID}/review",
            {
                "decision": "approve",
                "expected_revision": 2,
            },
        ),
    ],
)
def test_all_transaction_posts_require_idempotency_key(path: str, payload: dict):
    client = _build_client(_FakeTransactionService())

    response = client.post(path, json=payload)

    assert response.status_code == 422


def test_transaction_router_has_no_external_execution_endpoint():
    routes = [
        route
        for route in transaction_api.router.routes
        if hasattr(route, "path")
    ]
    route_paths = {
        route.path
        for route in routes
    }

    assert len(route_paths) == 10
    assert sum(len(route.methods or set()) for route in routes) == 13
    assert sum("POST" in (route.methods or set()) for route in routes) == 6
    assert not any(
        action in path
        for path in route_paths
        for action in ("/payment", "/refund", "/booking", "/fulfillment")
    )


def test_quote_routes_forward_idempotency_revision_and_pagination():
    service = _FakeTransactionService()
    advisor_client = _build_client(service, user_id=ADVISOR_ID)
    customer_client = _build_client(service, user_id=CUSTOMER_ID)

    create_response = advisor_client.post(
        "/api/v1/agency/quotes",
        json=_quote_create_payload(),
        headers={"Idempotency-Key": "quote-create-1"},
    )
    list_response = customer_client.get(
        "/api/v1/agency/quotes",
        params={
            "agency_id": str(AGENCY_ID),
            "status": "draft",
            "limit": 10,
            "offset": 0,
        },
    )
    get_response = customer_client.get(f"/api/v1/agency/quotes/{QUOTE_ID}")
    issue_response = advisor_client.post(
        f"/api/v1/agency/quotes/{QUOTE_ID}/issue",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "quote-issue-1"},
    )
    accept_response = customer_client.post(
        f"/api/v1/agency/quotes/{QUOTE_ID}/accept",
        json={"expected_revision": 2},
        headers={"Idempotency-Key": "quote-accept-1"},
    )

    assert create_response.status_code == 201
    assert create_response.json()["total_amount"] == "1288.50"
    assert create_response.json()["branch_id"] == str(BRANCH_ID)
    assert create_response.json()["customer_id"] == str(BUSINESS_CUSTOMER_ID)
    assert "user_id" not in create_response.json()
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert issue_response.json()["status"] == "offered"
    assert issue_response.json()["revision"] == 2
    assert accept_response.json()["status"] == "accepted"
    assert accept_response.json()["revision"] == 3

    create_call = next(values for name, values in service.calls if name == "create_quote")
    issue_call = next(values for name, values in service.calls if name == "issue_quote")
    accept_call = next(values for name, values in service.calls if name == "accept_quote")
    assert create_call["idempotency_key"] == "quote-create-1"
    assert create_call["data"].currency == "CNY"
    assert issue_call["expected_revision"] == 1
    assert issue_call["idempotency_key"] == "quote-issue-1"
    assert accept_call["expected_revision"] == 2


def test_order_routes_keep_external_actions_disabled_and_expose_events():
    service = _FakeTransactionService()
    client = _build_client(service)

    create_response = client.post(
        "/api/v1/agency/orders",
        json={
            "agency_id": str(AGENCY_ID),
            "quote_id": str(QUOTE_ID),
            "expected_quote_revision": 3,
        },
        headers={"Idempotency-Key": "order-create-1"},
    )
    list_response = client.get(
        "/api/v1/agency/orders",
        params={"agency_id": str(AGENCY_ID), "limit": 5, "offset": 0},
    )
    get_response = client.get(f"/api/v1/agency/orders/{ORDER_ID}")
    events_response = client.get(
        f"/api/v1/agency/orders/{ORDER_ID}/events",
        params={"limit": 20, "offset": 0},
    )
    submit_response = client.post(
        f"/api/v1/agency/orders/{ORDER_ID}/submit",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "order-submit-1"},
    )

    assert create_response.status_code == 201
    assert create_response.json()["branch_id"] == str(BRANCH_ID)
    assert create_response.json()["customer_id"] == str(BUSINESS_CUSTOMER_ID)
    assert "user_id" not in create_response.json()
    assert create_response.json()["external_action_enabled"] is False
    assert create_response.json()["payment_status"] == "not_started"
    assert create_response.json()["fulfillment_status"] == "not_started"
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert events_response.json()["total"] == 1
    assert "actor_user_id" not in events_response.json()["events"][0]
    assert (
        events_response.json()["events"][0]["event_metadata"][
            "external_actions_triggered"
        ]
        is False
    )
    assert (
        "quote_snapshot"
        not in events_response.json()["events"][0]["event_metadata"]
    )
    assert submit_response.json()["status"] == "pending_review"
    assert submit_response.json()["revision"] == 2

    create_call = next(values for name, values in service.calls if name == "create_order")
    submit_call = next(values for name, values in service.calls if name == "submit_order")
    assert create_call["data"].expected_quote_revision == 3
    assert create_call["idempotency_key"] == "order-create-1"
    assert submit_call["expected_revision"] == 1
    assert submit_call["idempotency_key"] == "order-submit-1"


def test_order_review_routes_use_a_snapshot_free_dto_and_single_decision():
    service = _FakeTransactionService()
    approver_client = _build_client(service, user_id=APPROVER_ID)

    list_response = approver_client.get(
        "/api/v1/agency/order-reviews",
        params={
            "agency_id": str(AGENCY_ID),
            "status": "pending",
            "limit": 10,
            "offset": 0,
        },
    )
    get_response = approver_client.get(
        f"/api/v1/agency/orders/{ORDER_ID}/review"
    )
    decision_response = approver_client.post(
        f"/api/v1/agency/orders/{ORDER_ID}/review",
        json={
            "decision": "approve",
            "expected_revision": 2,
            "reason": "金额与行程已复核",
        },
        headers={"Idempotency-Key": "order-review-1"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert "quote_snapshot" not in list_response.json()["reviews"][0]
    assert list_response.json()["reviews"][0]["branch_id"] == str(BRANCH_ID)
    assert get_response.status_code == 200
    assert get_response.json()["order_revision"] == 2
    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"
    assert decision_response.json()["decision_order_revision"] == 3

    list_call = next(
        values
        for name, values in service.calls
        if name == "list_order_reviews"
    )
    decision_call = next(
        values
        for name, values in service.calls
        if name == "decide_order_review"
    )
    assert list_call["status_filter"] == "pending"
    assert decision_call == {
        "actor_user_id": APPROVER_ID,
        "order_id": ORDER_ID,
        "decision": "approve",
        "expected_revision": 2,
        "reason": "金额与行程已复核",
        "idempotency_key": "order-review-1",
    }


def test_order_review_api_maps_self_review_denial_without_leaking_snapshot():
    service = _FakeTransactionService()
    service.errors["decide_order_review"] = AgencyTransactionAccessDenied(
        "order_review_self_decision_denied",
        "订单客户或审核发起人不能审批自己的订单",
    )
    client = _build_client(service, user_id=CUSTOMER_ID)

    response = client.post(
        f"/api/v1/agency/orders/{ORDER_ID}/review",
        json={
            "decision": "approve",
            "expected_revision": 2,
        },
        headers={"Idempotency-Key": "self-review"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == (
        "order_review_self_decision_denied"
    )


def test_api_maps_hidden_access_and_idempotency_conflicts_to_stable_errors():
    service = _FakeTransactionService()
    client = _build_client(service)
    service.errors["get_order"] = AgencyTransactionNotFound(
        "agency_transaction_not_found",
        "交易资源不存在",
    )

    hidden_response = client.get(f"/api/v1/agency/orders/{ORDER_ID}")

    service.errors["create_quote"] = AgencyTransactionConflict(
        "idempotency_key_conflict",
        "同一 Idempotency-Key 已用于不同请求",
    )
    conflict_response = client.post(
        "/api/v1/agency/quotes",
        json=_quote_create_payload(),
        headers={"Idempotency-Key": "reused-key"},
    )

    assert hidden_response.status_code == 404
    assert hidden_response.json()["detail"]["code"] == "agency_transaction_not_found"
    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"]["code"] == "idempotency_key_conflict"


def test_canonical_payload_hash_is_order_stable_and_value_sensitive():
    first = {
        "amount": Decimal("1288.50"),
        "nested": {"city": "杭州", "days": 3},
    }
    reordered = {
        "nested": {"days": 3, "city": "杭州"},
        "amount": Decimal("1288.50"),
    }
    changed = {
        "amount": Decimal("1288.51"),
        "nested": {"city": "杭州", "days": 3},
    }

    assert canonical_payload_hash(first) == canonical_payload_hash(reordered)
    assert canonical_payload_hash(first) != canonical_payload_hash(changed)
    assert len(canonical_payload_hash(first)) == 64


@pytest.mark.asyncio
async def test_persisted_idempotency_replays_same_request_and_locks_record():
    request_payload = {
        "actor_user_id": CUSTOMER_ID,
        "quote_id": QUOTE_ID,
        "expected_revision": 2,
    }
    record = IdempotencyRecord(
        agency_id=AGENCY_ID,
        scope="quote.accept",
        key="accept-1",
        request_hash=canonical_payload_hash(
            {
                "scope": "quote.accept",
                "request": request_payload,
            }
        ),
        status="completed",
        resource_type="agency_quote",
        resource_id=str(QUOTE_ID),
    )
    db = _ExecuteSequence(None, record)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    state = await service._begin_idempotent_action(
        agency_id=AGENCY_ID,
        scope="quote.accept",
        key="accept-1",
        request_payload=request_payload,
    )

    assert state.replayed is True
    assert state.record is record
    assert db.statements[1]._for_update_arg is not None


@pytest.mark.asyncio
async def test_persisted_idempotency_rejects_same_key_with_different_request():
    original_payload = {
        "actor_user_id": CUSTOMER_ID,
        "quote_id": QUOTE_ID,
        "expected_revision": 2,
    }
    record = IdempotencyRecord(
        agency_id=AGENCY_ID,
        scope="quote.accept",
        key="accept-1",
        request_hash=canonical_payload_hash(
            {
                "scope": "quote.accept",
                "request": original_payload,
            }
        ),
        status="completed",
        resource_type="agency_quote",
        resource_id=str(QUOTE_ID),
    )
    db = _ExecuteSequence(None, record)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service._begin_idempotent_action(
            agency_id=AGENCY_ID,
            scope="quote.accept",
            key="accept-1",
            request_payload={
                **original_payload,
                "expected_revision": 3,
            },
        )

    assert exc_info.value.code == "idempotency_key_conflict"


@pytest.mark.asyncio
async def test_mutation_loaders_request_row_locks():
    quote = _quote_record()
    order = _order_record()
    db = _ExecuteSequence(quote, order)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    await service._get_quote(QUOTE_ID, for_update=True)
    await service._get_order(ORDER_ID, for_update=True)

    assert all(statement._for_update_arg is not None for statement in db.statements)
    assert all(
        statement.get_execution_options().get("populate_existing") is True
        for statement in db.statements
    )


@pytest.mark.asyncio
async def test_transaction_customer_lock_targets_only_customer_row():
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
        status="active",
        consent_status="granted",
        consent_evidence_hash="c" * 64,
    )
    db = _ExecuteSequence(customer)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    result = await service._get_transaction_customer(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        for_update=True,
    )

    assert result is customer
    sql = str(
        db.statements[0].compile(dialect=postgresql.dialect())
    ).upper()
    assert "FOR UPDATE OF AGENCY_CUSTOMER" in sql
    assert "FOR UPDATE OF AGENCY_CUSTOMER, AGENCY_BRANCH" not in sql
    assert (
        db.statements[0].get_execution_options().get("populate_existing")
        is True
    )


@pytest.mark.asyncio
async def test_self_service_branch_scope_uses_share_lock():
    db = _ExecuteSequence(BRANCH_ID)
    authorization = BranchAuthorization(db)  # type: ignore[arg-type]

    await authorization.lock_active_branch_scope(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
    )

    sql = str(
        db.statements[0].compile(dialect=postgresql.dialect())
    ).upper()
    assert "FOR SHARE" in sql


@pytest.mark.asyncio
async def test_agency_wide_command_scope_uses_share_lock():
    membership = SimpleNamespace(role="owner", status="active")
    db = _ExecuteSequence(membership)
    authorization = BranchAuthorization(db)  # type: ignore[arg-type]

    result = await authorization.require_agency_wide(
        agency_id=AGENCY_ID,
        actor_user_id=ADVISOR_ID,
        lock_scope=True,
    )

    assert result is membership
    sql = str(
        db.statements[0].compile(dialect=postgresql.dialect())
    ).upper()
    assert "FOR SHARE" in sql


@pytest.mark.asyncio
async def test_staff_membership_is_bound_to_an_active_agency():
    membership = SimpleNamespace(role="travel_advisor", status="active")
    service = AgencyTransactionService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    get_membership = AsyncMock(return_value=membership)
    service.authorization.get_active_membership = get_membership

    result = await service._get_active_membership(
        agency_id=AGENCY_ID,
        user_id=ADVISOR_ID,
    )

    assert result is membership
    get_membership.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        user_id=ADVISOR_ID,
    )


@pytest.mark.parametrize("assigned", [True, False])
@pytest.mark.asyncio
async def test_travel_advisor_quote_access_requires_active_customer_assignment(
    assigned: bool,
):
    membership = SimpleNamespace(
        id=uuid.uuid4(),
        role="travel_advisor",
        status="active",
    )
    grant = SimpleNamespace(id=uuid.uuid4(), role="travel_advisor")
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
    )
    authorization = BranchAuthorization(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    authorization.get_active_membership = AsyncMock(return_value=membership)
    authorization._has_active_assignment = AsyncMock(return_value=assigned)
    authorization._active_branch_grant = AsyncMock(return_value=grant)

    if assigned:
        access = await authorization.require_quote_manager(
            customer=customer,
            actor_user_id=ADVISOR_ID,
            hide_resource=False,
        )

        assert access.membership is membership
        assert access.grant is grant
        authorization._active_branch_grant.assert_awaited_once_with(
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            membership=membership,
            roles={"travel_advisor"},
        )
    else:
        with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
            await authorization.require_quote_manager(
                customer=customer,
                actor_user_id=ADVISOR_ID,
                hide_resource=False,
            )

        assert exc_info.value.code == "agency_quote_permission_denied"
        authorization._active_branch_grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_product_lookup_reuses_the_scoped_transaction_customer(
    monkeypatch: pytest.MonkeyPatch,
):
    product_id = uuid.UUID("70000000-0000-0000-0000-000000000001")
    data = AgencyQuoteCreateRequest.model_validate(
        {
            **_quote_create_payload(),
            "product_id": str(product_id),
        }
    )
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
        status="active",
        consent_status="granted",
        consent_evidence_hash="c" * 64,
    )
    db = _ExecuteSequence(product_id)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]
    get_customer = AsyncMock(return_value=customer)
    monkeypatch.setattr(service, "_get_transaction_customer", get_customer)

    result = await service._validate_quote_references(data)

    assert result is customer
    get_customer.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        for_update=True,
    )
    product_statement = str(db.statements[0])
    assert "supplier_product.agency_id" in product_statement
    assert "supplier_product.status" in product_statement


@pytest.mark.asyncio
async def test_issue_quote_rechecks_customer_relationship_before_authorization(
    monkeypatch: pytest.MonkeyPatch,
):
    quote = _quote_record()
    service = AgencyTransactionService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    monkeypatch.setattr(
        service,
        "_get_quote",
        AsyncMock(return_value=quote),
    )
    get_customer = AsyncMock(
        side_effect=AgencyTransactionValidationError(
            "quote_customer_not_active",
            "客户尚未完成账号关联、同意确认和业务关系激活",
        )
    )
    monkeypatch.setattr(service, "_get_transaction_customer", get_customer)
    authorize = AsyncMock()
    service.authorization.require_quote_manager = authorize

    with pytest.raises(AgencyTransactionValidationError) as exc_info:
        await service.issue_quote(
            actor_user_id=ADVISOR_ID,
            quote_id=QUOTE_ID,
            expected_revision=1,
            idempotency_key="issue-recheck",
        )

    assert exc_info.value.code == "quote_customer_not_active"
    get_customer.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        for_update=True,
    )
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_issue_quote_locks_customer_and_branch_before_quote_row(
    monkeypatch: pytest.MonkeyPatch,
):
    quote = _quote_record()
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
    )
    service = AgencyTransactionService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    calls: list[str] = []

    async def get_quote(_quote_id, *, for_update=False):
        calls.append("quote_lock" if for_update else "quote_preview")
        if for_update:
            raise AgencyTransactionConflict("stop_after_lock", "stop")
        return quote

    async def get_customer(**_kwargs):
        calls.append("customer_lock")
        return customer

    async def authorize(**kwargs):
        calls.append("branch_scope")
        assert kwargs["lock_scope"] is True

    monkeypatch.setattr(service, "_get_quote", get_quote)
    monkeypatch.setattr(service, "_get_transaction_customer", get_customer)
    service.authorization.require_quote_manager = authorize

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.issue_quote(
            actor_user_id=ADVISOR_ID,
            quote_id=QUOTE_ID,
            expected_revision=1,
            idempotency_key="issue-lock-order",
        )

    assert exc_info.value.code == "stop_after_lock"
    assert calls == [
        "quote_preview",
        "customer_lock",
        "branch_scope",
        "quote_lock",
    ]


@pytest.mark.asyncio
async def test_issue_quote_rejects_binding_drift_after_row_lock(
    monkeypatch: pytest.MonkeyPatch,
):
    quote_preview = _quote_record()
    quote_locked = _quote_record(branch_id=uuid.uuid4())
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
    )
    service = AgencyTransactionService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    monkeypatch.setattr(
        service,
        "_get_quote",
        AsyncMock(side_effect=[quote_preview, quote_locked]),
    )
    monkeypatch.setattr(
        service,
        "_get_transaction_customer",
        AsyncMock(return_value=customer),
    )
    service.authorization.require_quote_manager = AsyncMock()

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.issue_quote(
            actor_user_id=ADVISOR_ID,
            quote_id=QUOTE_ID,
            expected_revision=1,
            idempotency_key="issue-binding-drift",
        )

    assert exc_info.value.code == "transaction_binding_conflict"
    service.authorization.require_quote_manager.assert_awaited_once_with(
        customer=customer,
        actor_user_id=ADVISOR_ID,
        hide_resource=True,
        lock_scope=True,
    )


@pytest.mark.parametrize("role", ["auditor", "finance"])
@pytest.mark.asyncio
async def test_non_advisor_staff_cannot_read_full_order_snapshot(
    role: str,
    monkeypatch: pytest.MonkeyPatch,
):
    staff_id = uuid.uuid4()
    membership = SimpleNamespace(
        id=uuid.uuid4(),
        role=role,
        status="active",
    )
    order = _order_record()
    service = AgencyTransactionService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    monkeypatch.setattr(service, "_get_order", AsyncMock(return_value=order))
    service.authorization.get_active_membership = AsyncMock(
        return_value=membership
    )
    branch_grant = AsyncMock(return_value=None)
    service.authorization._active_branch_grant = branch_grant
    service.authorization._has_active_assignment_ids = AsyncMock(
        return_value=False
    )

    with pytest.raises(AgencyTransactionNotFound) as exc_info:
        await service.get_order(
            actor_user_id=staff_id,
            order_id=ORDER_ID,
        )

    assert exc_info.value.code == "agency_transaction_not_found"
    branch_grant.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        membership=membership,
        roles={"branch_manager", "approver"},
    )
