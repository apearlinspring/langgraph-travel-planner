from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
        "customer_user_id": str(CUSTOMER_ID),
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
    assert create_response.json()["external_action_enabled"] is False
    assert create_response.json()["payment_status"] == "not_started"
    assert create_response.json()["fulfillment_status"] == "not_started"
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert events_response.json()["total"] == 1
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


@pytest.mark.asyncio
async def test_staff_membership_is_bound_to_an_active_agency():
    membership = SimpleNamespace(role="travel_advisor", status="active")
    db = _ExecuteSequence(membership)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    result = await service._get_active_membership(
        agency_id=AGENCY_ID,
        user_id=ADVISOR_ID,
    )

    statement_text = str(db.statements[0])
    assert result is membership
    assert "JOIN agency" in statement_text
    assert "agency_membership.status" in statement_text
    assert "agency.status" in statement_text


@pytest.mark.asyncio
async def test_quote_product_lookup_is_scoped_to_the_same_agency():
    product_id = uuid.UUID("70000000-0000-0000-0000-000000000001")
    data = AgencyQuoteCreateRequest.model_validate(
        {
            **_quote_create_payload(),
            "product_id": str(product_id),
        }
    )
    db = _ExecuteSequence(CUSTOMER_ID, product_id)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    await service._validate_quote_references(data)

    customer_statement = str(db.statements[0])
    product_statement = str(db.statements[1])
    assert "agency_customer.agency_id" in customer_statement
    assert "agency_customer.status" in customer_statement
    assert "supplier_product.agency_id" in product_statement
    assert "supplier_product.status" in product_statement


@pytest.mark.asyncio
async def test_quote_requires_an_active_customer_relationship():
    data = AgencyQuoteCreateRequest.model_validate(_quote_create_payload())
    db = _ExecuteSequence(None)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    with pytest.raises(AgencyTransactionValidationError) as exc_info:
        await service._validate_quote_references(data)

    assert exc_info.value.code == "quote_customer_not_active"
    statement_text = str(db.statements[0])
    assert "agency_customer.agency_id" in statement_text
    assert "agency_customer.user_id" in statement_text
    assert "agency_customer.status" in statement_text


@pytest.mark.parametrize("role", ["auditor", "finance"])
@pytest.mark.asyncio
async def test_non_advisor_staff_cannot_read_full_order_snapshot(role: str):
    staff_id = uuid.uuid4()
    membership = SimpleNamespace(role=role, status="active")
    db = _ExecuteSequence(_order_record(), membership)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    with pytest.raises(AgencyTransactionNotFound) as exc_info:
        await service.get_order(
            actor_user_id=staff_id,
            order_id=ORDER_ID,
        )

    assert exc_info.value.code == "agency_transaction_not_found"
