from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agency.order_review_service import AgencyOrderReviewService
from app.agency.transaction_service import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
    AgencyTransactionService,
    IdempotencyState,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import IdempotencyRecord
from tests.agency_transaction_test_support import (
    AGENCY_ID,
    APPROVER_ID,
    CUSTOMER_ID,
    ORDER_ID,
    REVIEW_ID,
    ExecuteSequence,
    order_record,
    review_record,
)


@pytest.mark.asyncio
async def test_approver_can_read_order_snapshot_without_quote_write_permission():
    membership = SimpleNamespace(role="approver", status="active")
    order = order_record(status="pending_review", revision=2)
    read_service = AgencyTransactionService(  # type: ignore[arg-type]
        ExecuteSequence(order, membership, REVIEW_ID)
    )

    result = await read_service.get_order(
        actor_user_id=APPROVER_ID,
        order_id=ORDER_ID,
    )

    assert result is order

    write_service = AgencyTransactionService(  # type: ignore[arg-type]
        ExecuteSequence(membership)
    )
    with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
        await write_service._require_quote_manager(
            agency_id=AGENCY_ID,
            actor_user_id=APPROVER_ID,
            hide_resource=False,
        )

    assert exc_info.value.code == "agency_quote_permission_denied"


@pytest.mark.asyncio
async def test_approver_cannot_read_an_order_without_a_review_record():
    membership = SimpleNamespace(role="approver", status="active")
    order = order_record(status="draft", revision=1)
    service = AgencyTransactionService(  # type: ignore[arg-type]
        ExecuteSequence(order, membership, None)
    )

    with pytest.raises(AgencyTransactionNotFound):
        await service.get_order(
            actor_user_id=APPROVER_ID,
            order_id=ORDER_ID,
        )


@pytest.mark.asyncio
async def test_approver_order_list_is_limited_to_review_bound_orders():
    membership = SimpleNamespace(role="approver", status="active")
    order = order_record(status="pending_review", revision=2)
    db = ExecuteSequence(membership, [order], 1)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    orders, total = await service.list_orders(
        actor_user_id=APPROVER_ID,
        agency_id=AGENCY_ID,
        status_filter=None,
        limit=30,
        offset=0,
    )

    assert orders == [order]
    assert total == 1
    list_statement = str(db.statements[1])
    assert "agency_order.id IN (SELECT agency_order_review.order_id" in (
        list_statement
    )
    assert "agency_order.user_id =" not in list_statement


@pytest.mark.asyncio
async def test_submit_order_creates_a_review_bound_to_the_new_revision(
    monkeypatch: pytest.MonkeyPatch,
):
    order = order_record()
    idempotency = IdempotencyRecord(
        agency_id=AGENCY_ID,
        scope="order.submit",
        key="submit-review",
        request_hash="c" * 64,
        status="in_progress",
    )
    state = IdempotencyState(record=idempotency, replayed=False)
    db = SimpleNamespace(add=MagicMock())
    service = AgencyTransactionService(db)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_order",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        service,
        "_ensure_agency_active",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=state),
    )
    append_event = AsyncMock()
    monkeypatch.setattr(service, "_append_order_event", append_event)

    async def _flush_with_version_increment():
        if order.status == "pending_review" and order.revision == 1:
            order.revision = 2

    monkeypatch.setattr(service, "_flush", _flush_with_version_increment)

    result = await service.submit_order(
        actor_user_id=CUSTOMER_ID,
        order_id=ORDER_ID,
        expected_revision=1,
        idempotency_key="submit-review",
    )

    review = db.add.call_args.args[0]
    assert isinstance(review, AgencyOrderReview)
    assert result is order
    assert review.agency_id == order.agency_id
    assert review.order_id == order.id
    assert review.order_revision == order.revision == 2
    assert review.payload_hash == order.payload_hash
    assert review.total_amount == order.total_amount
    assert review.currency == order.currency
    assert review.requested_by_user_id == CUSTOMER_ID
    assert review.status == "pending"
    event_values = append_event.await_args.kwargs
    assert event_values["event_type"] == "order_submitted"
    assert event_values["event_metadata"] == {
        "review_id": str(review.id),
        "review_order_revision": 2,
        "external_actions_triggered": False,
    }
    assert idempotency.status == "completed"
    assert idempotency.resource_type == "agency_order"
    assert idempotency.resource_id == str(order.id)


@pytest.mark.parametrize("role", ["owner", "admin", "travel_advisor"])
@pytest.mark.asyncio
async def test_only_the_dedicated_tenant_approver_can_decide_reviews(
    role: str,
):
    membership = SimpleNamespace(role=role, status="active")
    service = AgencyOrderReviewService(  # type: ignore[arg-type]
        ExecuteSequence(membership)
    )

    with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
        await service._require_order_reviewer(
            agency_id=AGENCY_ID,
            actor_user_id=APPROVER_ID,
            hide_resource=False,
        )

    assert exc_info.value.code == "agency_order_review_permission_denied"


@pytest.mark.asyncio
async def test_dedicated_tenant_approver_role_is_accepted():
    membership = SimpleNamespace(role="approver", status="active")
    service = AgencyOrderReviewService(  # type: ignore[arg-type]
        ExecuteSequence(membership)
    )

    result = await service._require_order_reviewer(
        agency_id=AGENCY_ID,
        actor_user_id=APPROVER_ID,
        hide_resource=False,
    )

    assert result is membership


def test_order_review_binding_rejects_amount_or_hash_drift():
    order = order_record(status="pending_review", revision=2)
    review = review_record(total_amount=Decimal("1288.51"))

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        AgencyOrderReviewService._ensure_order_review_binding(order, review)

    assert exc_info.value.code == "order_review_binding_mismatch"


@pytest.mark.parametrize(
    ("decision", "reason", "review_status", "order_status", "event_type"),
    [
        (
            "approve",
            "已核对 sk-testvalue123456789",
            "approved",
            "approved",
            "order_review_approved",
        ),
        (
            "reject",
            "报价明细与客户确认不一致",
            "rejected",
            "review_rejected",
            "order_review_rejected",
        ),
    ],
)
@pytest.mark.asyncio
async def test_order_review_decision_is_atomic_bound_and_never_external(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    reason: str,
    review_status: str,
    order_status: str,
    event_type: str,
):
    order = order_record(status="pending_review", revision=2)
    review = AgencyOrderReview(
        id=REVIEW_ID,
        agency_id=AGENCY_ID,
        order_id=ORDER_ID,
        status="pending",
        order_revision=2,
        payload_hash=order.payload_hash,
        total_amount=order.total_amount,
        currency=order.currency,
        requested_by_user_id=CUSTOMER_ID,
    )
    idempotency = IdempotencyRecord(
        agency_id=AGENCY_ID,
        scope="order.review.decide",
        key=f"review-{decision}",
        request_hash="d" * 64,
        status="in_progress",
    )
    state = IdempotencyState(record=idempotency, replayed=False)
    service = AgencyOrderReviewService(SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_order",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        service,
        "_require_order_reviewer",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_ensure_agency_active",
        AsyncMock(),
    )
    begin_idempotency = AsyncMock(return_value=state)
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        begin_idempotency,
    )
    monkeypatch.setattr(
        service,
        "_get_order_review",
        AsyncMock(return_value=review),
    )
    append_event = AsyncMock()
    monkeypatch.setattr(service, "_append_order_event", append_event)

    async def _flush_with_version_increment():
        if order.status != "pending_review" and order.revision == 2:
            order.revision = 3

    monkeypatch.setattr(service, "_flush", _flush_with_version_increment)

    result = await service.decide_order_review(
        actor_user_id=APPROVER_ID,
        order_id=ORDER_ID,
        decision=decision,
        expected_revision=2,
        reason=reason,
        idempotency_key=f"review-{decision}",
    )

    assert result is review
    assert order.status == order_status
    assert order.revision == 3
    assert order.external_action_enabled is False
    assert review.status == review_status
    assert review.decision_order_revision == 3
    assert review.decided_by_user_id == APPROVER_ID
    assert review.decided_at is not None
    assert "sk-testvalue123456789" not in (review.decision_reason or "")
    begin_values = begin_idempotency.await_args.kwargs
    assert begin_values["scope"] == "order.review.decide"
    assert begin_values["request_payload"]["decision"] == decision
    event_values = append_event.await_args.kwargs
    assert event_values["event_type"] == event_type
    assert event_values["event_metadata"]["external_actions_triggered"] is False
    assert event_values["event_metadata"]["review_order_revision"] == 2
    assert event_values["event_metadata"]["decision_order_revision"] == 3
    assert idempotency.status == "completed"
    assert idempotency.resource_type == "agency_order_review"
    assert idempotency.resource_id == str(REVIEW_ID)


@pytest.mark.asyncio
async def test_order_customer_cannot_decide_own_review(
    monkeypatch: pytest.MonkeyPatch,
):
    order = order_record(status="pending_review", revision=2)
    review = review_record()
    state = IdempotencyState(
        record=IdempotencyRecord(
            agency_id=AGENCY_ID,
            scope="order.review.decide",
            key="self-review",
            request_hash="e" * 64,
            status="in_progress",
        ),
        replayed=False,
    )
    service = AgencyOrderReviewService(SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_order",
        AsyncMock(return_value=order),
    )
    monkeypatch.setattr(
        service,
        "_require_order_reviewer",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_ensure_agency_active",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=state),
    )
    monkeypatch.setattr(
        service,
        "_get_order_review",
        AsyncMock(return_value=review),
    )

    with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
        await service.decide_order_review(
            actor_user_id=CUSTOMER_ID,
            order_id=ORDER_ID,
            decision="approve",
            expected_revision=2,
            reason=None,
            idempotency_key="self-review",
        )

    assert exc_info.value.code == "order_review_self_decision_denied"
