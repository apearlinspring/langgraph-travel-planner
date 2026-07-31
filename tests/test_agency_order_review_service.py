from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import false, true
from sqlalchemy.dialects import postgresql

from app.agency.order_review_service import AgencyOrderReviewService
from app.agency.transaction_service import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
    AgencyTransactionService,
    IdempotencyState,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import AgencyOrder, IdempotencyRecord
from tests.agency_transaction_test_support import (
    AGENCY_ID,
    APPROVER_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    ORDER_ID,
    REVIEW_ID,
    ExecuteSequence,
    order_record,
    review_record,
)


@pytest.mark.asyncio
async def test_approver_can_read_only_a_review_bound_order_snapshot():
    membership = SimpleNamespace(role="approver", status="active")
    order = order_record(status="pending_review", revision=2)
    db = ExecuteSequence(REVIEW_ID)
    read_service = AgencyTransactionService(db)  # type: ignore[arg-type]
    read_service._get_order = AsyncMock(return_value=order)
    review_access = SimpleNamespace(membership=membership, grant=object())
    require_view = AsyncMock(return_value=review_access)
    read_service.authorization.require_transaction_view = require_view

    result = await read_service.get_order(
        actor_user_id=APPROVER_ID,
        order_id=ORDER_ID,
    )

    assert result is order
    require_view.assert_awaited_once_with(
        resource=order,
        actor_user_id=APPROVER_ID,
        include_approver=True,
    )
    review_statement = str(db.statements[0])
    assert "agency_order_review.branch_id" in review_statement
    assert "agency_order_review.order_id" in review_statement


@pytest.mark.asyncio
async def test_approver_cannot_read_an_order_without_a_review_record():
    membership = SimpleNamespace(role="approver", status="active")
    order = order_record(status="draft", revision=1)
    service = AgencyTransactionService(  # type: ignore[arg-type]
        ExecuteSequence(None)
    )
    service._get_order = AsyncMock(return_value=order)
    service.authorization.require_transaction_view = AsyncMock(
        return_value=SimpleNamespace(membership=membership, grant=object())
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
    db = ExecuteSequence([order], 1)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]
    service._get_active_membership = AsyncMock(return_value=membership)
    visibility = AsyncMock(side_effect=[false(), true()])
    service.authorization.transaction_visibility_filter = visibility

    orders, total = await service.list_orders(
        actor_user_id=APPROVER_ID,
        agency_id=AGENCY_ID,
        status_filter=None,
        limit=30,
        offset=0,
    )

    assert orders == [order]
    assert total == 1
    assert visibility.await_count == 2
    assert visibility.await_args_list[0].kwargs == {
        "model": AgencyOrder,
        "agency_id": AGENCY_ID,
        "actor_user_id": APPROVER_ID,
    }
    assert visibility.await_args_list[1].kwargs == {
        "model": AgencyOrder,
        "agency_id": AGENCY_ID,
        "actor_user_id": APPROVER_ID,
        "include_approver": True,
    }
    list_statement = str(db.statements[0])
    assert "agency_order.id IN (SELECT agency_order_review.order_id" in (
        list_statement
    )
    assert "agency_order_review.branch_id = agency_order.branch_id" in (
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
    ensure_approver = AsyncMock()
    monkeypatch.setattr(
        service,
        "_ensure_branch_has_active_approver",
        ensure_approver,
    )
    ensure_no_open_cancellation = AsyncMock()
    monkeypatch.setattr(
        service,
        "_ensure_order_has_no_open_cancellation_case",
        ensure_no_open_cancellation,
    )
    get_customer = AsyncMock(
        return_value=SimpleNamespace(
            id=BUSINESS_CUSTOMER_ID,
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            user_id=CUSTOMER_ID,
        )
    )
    monkeypatch.setattr(service, "_get_transaction_customer", get_customer)
    lock_branch = AsyncMock()
    service.authorization.lock_active_branch_scope = lock_branch
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
    assert review.branch_id == order.branch_id
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
    get_customer.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        for_update=True,
    )
    lock_branch.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
    )
    ensure_approver.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        excluded_user_ids=(CUSTOMER_ID,),
    )
    ensure_no_open_cancellation.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        order_id=ORDER_ID,
    )


@pytest.mark.asyncio
async def test_order_submission_requires_active_branch_approver():
    db = ExecuteSequence(None)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service._ensure_branch_has_active_approver(
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            excluded_user_ids=(CUSTOMER_ID,),
        )

    assert exc_info.value.code == "branch_approver_required"
    statement = str(
        db.statements[0].compile(dialect=postgresql.dialect())
    )
    assert "agency_branch_role_grant" in statement
    assert "agency_membership" in statement
    assert "agency_membership.user_id NOT IN" in statement
    assert statement.endswith("FOR SHARE")


@pytest.mark.asyncio
async def test_order_submission_rejects_an_open_cancellation_case():
    db = ExecuteSequence(ORDER_ID)
    service = AgencyTransactionService(db)  # type: ignore[arg-type]

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service._ensure_order_has_no_open_cancellation_case(
            agency_id=AGENCY_ID,
            order_id=ORDER_ID,
        )

    assert exc_info.value.code == "cancellation_case_open"
    statement = str(
        db.statements[0].compile(dialect=postgresql.dialect())
    )
    assert "agency_order_cancellation_case" in statement
    assert "agency_order_cancellation_case.status IN" in statement


@pytest.mark.asyncio
async def test_reviewer_gate_is_bound_to_the_order_branch():
    service = AgencyOrderReviewService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    require_branch_role = AsyncMock(
        side_effect=AgencyTransactionAccessDenied(
            "agency_branch_permission_denied",
            "当前用户没有该门店的有效角色授权",
        )
    )
    service.authorization.require_branch_role = require_branch_role

    with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
        await service._require_order_reviewer(
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            actor_user_id=APPROVER_ID,
            hide_resource=False,
        )

    assert exc_info.value.code == "agency_branch_permission_denied"
    require_branch_role.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=APPROVER_ID,
        roles={"approver"},
        hide_resource=False,
        allow_agency_wide=False,
        lock_scope=False,
    )


@pytest.mark.asyncio
async def test_dedicated_tenant_approver_role_is_accepted():
    membership = SimpleNamespace(role="approver", status="active")
    service = AgencyOrderReviewService(  # type: ignore[arg-type]
        SimpleNamespace()
    )
    require_branch_role = AsyncMock(
        return_value=SimpleNamespace(membership=membership, grant=object())
    )
    service.authorization.require_branch_role = require_branch_role

    result = await service._require_order_reviewer(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=APPROVER_ID,
        hide_resource=False,
    )

    assert result is membership
    require_branch_role.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=APPROVER_ID,
        roles={"approver"},
        hide_resource=False,
        allow_agency_wide=False,
        lock_scope=False,
    )


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
        branch_id=BRANCH_ID,
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
    get_customer = AsyncMock(
        return_value=SimpleNamespace(
            id=BUSINESS_CUSTOMER_ID,
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            user_id=CUSTOMER_ID,
        )
    )
    monkeypatch.setattr(service, "_get_transaction_customer", get_customer)
    get_customer_binding = AsyncMock(return_value=get_customer.return_value)
    monkeypatch.setattr(
        service,
        "_get_customer_binding",
        get_customer_binding,
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
    if decision == "approve":
        get_customer.assert_awaited_once_with(
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            customer_id=BUSINESS_CUSTOMER_ID,
            for_update=True,
        )
        get_customer_binding.assert_not_awaited()
    else:
        get_customer.assert_not_awaited()
        get_customer_binding.assert_awaited_once_with(
            agency_id=AGENCY_ID,
            branch_id=BRANCH_ID,
            customer_id=BUSINESS_CUSTOMER_ID,
            for_update=True,
        )
    service._require_order_reviewer.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=APPROVER_ID,
        hide_resource=True,
        lock_scope=True,
    )


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
    monkeypatch.setattr(
        service,
        "_get_transaction_customer",
        AsyncMock(
            return_value=SimpleNamespace(
                id=BUSINESS_CUSTOMER_ID,
                agency_id=AGENCY_ID,
                branch_id=BRANCH_ID,
                user_id=CUSTOMER_ID,
            )
        ),
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
