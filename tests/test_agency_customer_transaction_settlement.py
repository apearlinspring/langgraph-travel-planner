from __future__ import annotations

import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.agency.customer_lifecycle_service import CustomerLifecycleService
from app.agency.errors import AgencyTransactionConflict
from app.agency.transaction_service import IdempotencyState
from app.models.agency_transaction import IdempotencyRecord
from tests.agency_transaction_test_support import (
    ADVISOR_ID,
    AGENCY_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    NOW,
    ExecuteSequence,
)


def _uuid(value: int) -> uuid.UUID:
    return uuid.UUID(int=value)


def _quote(value: int, status: str) -> SimpleNamespace:
    return SimpleNamespace(id=_uuid(value), status=status, revision=1)


def _order(
    value: int,
    *,
    quote_id: uuid.UUID,
    status: str,
    external_action_enabled: bool = False,
    payment_status: str = "not_started",
    fulfillment_status: str = "not_started",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=_uuid(value),
        quote_id=quote_id,
        status=status,
        revision=1,
        external_action_enabled=external_action_enabled,
        payment_status=payment_status,
        fulfillment_status=fulfillment_status,
        cancelled_at=None,
    )


def _customer(*, status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
        status=status,
        consent_status="granted" if status == "active" else "unknown",
        consent_version="consent.v1" if status == "active" else None,
        consent_evidence_hash="a" * 64 if status == "active" else None,
        consent_updated_at=NOW if status == "active" else None,
        lifecycle_revision=1,
        activated_at=NOW if status == "active" else None,
        deactivated_at=None,
    )


def _idempotency_state(
    *,
    scope: str,
    key: str,
    replayed: bool = False,
) -> IdempotencyState:
    record = IdempotencyRecord(
        agency_id=AGENCY_ID,
        scope=scope,
        key=key,
        request_hash="d" * 64,
        status="completed" if replayed else "in_progress",
        resource_type="agency_customer" if replayed else None,
        resource_id=str(BUSINESS_CUSTOMER_ID) if replayed else None,
    )
    return IdempotencyState(record=record, replayed=replayed)


@pytest.mark.asyncio
async def test_customer_settlement_locks_and_closes_internal_transactions(
    monkeypatch: pytest.MonkeyPatch,
):
    offered = _quote(101, "offered")
    accepted_with_order = _quote(102, "accepted")
    accepted_without_order = _quote(103, "accepted")
    expired = _quote(104, "expired")
    order_quotes = [
        accepted_with_order,
        *[_quote(value, "accepted") for value in range(105, 114)],
    ]
    quotes = [offered, accepted_without_order, expired, *order_quotes]
    orders = [
        _order(
            201,
            quote_id=order_quotes[0].id,
            status="draft",
        ),
        _order(
            202,
            quote_id=order_quotes[1].id,
            status="approved",
        ),
        _order(
            203,
            quote_id=order_quotes[2].id,
            status="pending_review",
        ),
        _order(
            204,
            quote_id=order_quotes[3].id,
            status="processing",
        ),
        _order(
            205,
            quote_id=order_quotes[4].id,
            status="failed",
        ),
        _order(
            206,
            quote_id=order_quotes[5].id,
            status="draft",
            payment_status="pending",
        ),
        _order(
            207,
            quote_id=order_quotes[6].id,
            status="manual_intervention",
        ),
        _order(
            208,
            quote_id=order_quotes[7].id,
            status="cancellation_pending",
        ),
        _order(
            209,
            quote_id=order_quotes[8].id,
            status="review_rejected",
        ),
        _order(
            210,
            quote_id=order_quotes[9].id,
            status="completed",
        ),
        _order(
            211,
            quote_id=_uuid(114),
            status="cancelled",
        ),
    ]
    db = ExecuteSequence(BRANCH_ID, quotes, orders)
    db.no_autoflush = nullcontext()
    service = CustomerLifecycleService(  # type: ignore[arg-type]
        db,
        now_factory=lambda: NOW,
    )

    tracked = [*quotes, *orders]
    last_status = {item.id: item.status for item in tracked}

    async def flush_with_revisions() -> None:
        for item in tracked:
            if item.status != last_status[item.id]:
                item.revision += 1
                last_status[item.id] = item.status

    appended_events: list[dict] = []

    async def append_order_event(**kwargs) -> None:
        appended_events.append(
            {
                **kwargs,
                "order_revision": kwargs["order"].revision,
            }
        )

    monkeypatch.setattr(service, "_flush", flush_with_revisions)
    monkeypatch.setattr(service, "_append_order_event", append_order_event)

    summary = await service._settle_customer_transactions(
        customer=_customer(),
        actor_user_id=CUSTOMER_ID,
    )

    assert offered.status == "cancelled"
    assert accepted_without_order.status == "cancelled"
    assert accepted_with_order.status == "accepted"
    assert expired.status == "expired"
    assert [order.status for order in orders] == [
        "cancelled",
        "cancelled",
        "pending_review",
        "cancellation_pending",
        "cancellation_pending",
        "cancellation_pending",
        "manual_intervention",
        "cancellation_pending",
        "review_rejected",
        "completed",
        "cancelled",
    ]
    assert orders[0].cancelled_at == NOW
    assert orders[1].cancelled_at == NOW
    assert all(order.cancelled_at == NOW for order in orders[3:6])
    assert orders[2].cancelled_at is None
    assert all(event["order_revision"] == 2 for event in appended_events[:2])
    assert appended_events[2]["order_revision"] == 1
    assert [
        event["event_type"] for event in appended_events
    ] == [
        "order_customer_relationship_deactivated",
        "order_customer_relationship_deactivated",
        "order_customer_relationship_deactivated",
        "order_customer_relationship_deactivated",
        "order_customer_relationship_deactivated",
        "order_customer_relationship_deactivated",
        "order_customer_relationship_action_required",
        "order_customer_relationship_action_required",
    ]
    assert all(
        event["event_metadata"]["external_actions_triggered"] is False
        and event["event_metadata"]["supplier_cancellation_confirmed"] is False
        and event["event_metadata"]["refund_confirmed"] is False
        for event in appended_events
    )
    assert summary == {
        "cancelled_quote_count": 2,
        "cancelled_quote_ids": [str(offered.id), str(accepted_without_order.id)],
        "cancelled_order_count": 2,
        "cancelled_order_ids": [str(orders[0].id), str(orders[1].id)],
        "cancellation_pending_order_count": 3,
        "cancellation_pending_order_ids": [
            str(orders[3].id),
            str(orders[4].id),
            str(orders[5].id),
        ],
        "pending_review_order_count": 1,
        "pending_review_order_ids": [str(orders[2].id)],
        "action_required_order_count": 2,
        "action_required_order_ids": [str(orders[6].id), str(orders[7].id)],
        "external_cancellation_count": 0,
        "refund_count": 0,
    }

    statements = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in db.statements
    ]
    assert "FROM agency_branch" in statements[0]
    assert statements[0].endswith("FOR SHARE")
    assert "FROM agency_quote" in statements[1]
    assert "ORDER BY agency_quote.id FOR UPDATE" in statements[1]
    assert "FROM agency_order" in statements[2]
    assert "ORDER BY agency_order.id FOR UPDATE" in statements[2]


@pytest.mark.parametrize(
    ("decision", "consent_status"),
    [("deny", "denied"), ("revoke", "revoked")],
)
@pytest.mark.asyncio
async def test_active_consent_shutdown_settles_once_across_idempotent_replay(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    consent_status: str,
):
    customer = _customer()
    idempotency_key = f"{decision}-once"
    state = _idempotency_state(
        scope="customer.consent",
        key=idempotency_key,
    )
    replay_state = IdempotencyState(record=state.record, replayed=True)
    service = CustomerLifecycleService(SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(side_effect=[state, replay_state]),
    )
    monkeypatch.setattr(
        service,
        "_end_active_assignment",
        AsyncMock(return_value=None),
    )
    settlement = {
        "cancelled_quote_count": 1,
        "cancelled_quote_ids": [str(_uuid(101))],
    }
    settle_transactions = AsyncMock(return_value=settlement)
    monkeypatch.setattr(
        service,
        "_settle_customer_transactions",
        settle_transactions,
    )
    monkeypatch.setattr(service, "_flush", AsyncMock())
    append_customer_event = AsyncMock()
    monkeypatch.setattr(
        service,
        "_append_customer_event",
        append_customer_event,
    )

    for _ in range(2):
        result = await service.record_customer_consent(
            actor_user_id=CUSTOMER_ID,
            customer_id=BUSINESS_CUSTOMER_ID,
            expected_revision=1,
            decision=decision,
            consent_version="consent.v2",
            consent_evidence_hash="b" * 64,
            idempotency_key=idempotency_key,
        )
        assert result is customer

    assert customer.consent_status == consent_status
    settle_transactions.assert_awaited_once_with(
        customer=customer,
        actor_user_id=CUSTOMER_ID,
    )
    append_customer_event.assert_awaited_once()
    assert (
        append_customer_event.await_args.kwargs["event_metadata"][
            "transaction_settlement"
        ]
        == settlement
    )


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        ("active", "grant"),
        ("inactive", "deny"),
    ],
)
@pytest.mark.asyncio
async def test_consent_without_active_relationship_shutdown_does_not_settle(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    decision: str,
):
    customer = _customer(status=status)
    if decision == "grant":
        customer.consent_status = "unknown"
        customer.consent_version = None
        customer.consent_evidence_hash = None
    service = CustomerLifecycleService(SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(
            return_value=_idempotency_state(
                scope="customer.consent",
                key=f"{status}-{decision}",
            )
        ),
    )
    settle_transactions = AsyncMock()
    monkeypatch.setattr(
        service,
        "_settle_customer_transactions",
        settle_transactions,
    )
    monkeypatch.setattr(service, "_flush", AsyncMock())
    monkeypatch.setattr(service, "_append_customer_event", AsyncMock())

    await service.record_customer_consent(
        actor_user_id=CUSTOMER_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        expected_revision=1,
        decision=decision,
        consent_version="consent.v2",
        consent_evidence_hash="c" * 64,
        idempotency_key=f"{status}-{decision}",
    )

    settle_transactions.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivate_customer_embeds_internal_settlement_summary(
    monkeypatch: pytest.MonkeyPatch,
):
    customer = _customer()
    service = CustomerLifecycleService(SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(
            return_value=_idempotency_state(
                scope="customer.deactivate",
                key="deactivate-settle",
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_end_active_assignment",
        AsyncMock(return_value=None),
    )
    settlement = {
        "cancelled_order_count": 1,
        "cancelled_order_ids": [str(_uuid(201))],
        "external_cancellation_count": 0,
        "refund_count": 0,
    }
    settle_transactions = AsyncMock(return_value=settlement)
    monkeypatch.setattr(
        service,
        "_settle_customer_transactions",
        settle_transactions,
    )
    monkeypatch.setattr(service, "_flush", AsyncMock())
    append_customer_event = AsyncMock()
    monkeypatch.setattr(
        service,
        "_append_customer_event",
        append_customer_event,
    )

    await service.deactivate_customer(
        actor_user_id=CUSTOMER_ID,
        customer_id=BUSINESS_CUSTOMER_ID,
        expected_revision=1,
        reason="客户主动终止服务",
        idempotency_key="deactivate-settle",
    )

    settle_transactions.assert_awaited_once_with(
        customer=customer,
        actor_user_id=CUSTOMER_ID,
    )
    metadata = append_customer_event.await_args.kwargs["event_metadata"]
    assert metadata["transaction_settlement"] == settlement
    assert metadata["consent_revoked"] is True


@pytest.mark.asyncio
async def test_customer_cannot_reactivate_before_pending_review_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    customer = _customer(status="inactive")
    customer.consent_status = "granted"
    customer.consent_version = "consent.v2"
    customer.consent_evidence_hash = "e" * 64
    customer.consent_updated_at = NOW
    db = ExecuteSequence(_uuid(201))
    service = CustomerLifecycleService(  # type: ignore[arg-type]
        db,
        now_factory=lambda: NOW,
    )
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service.authorization,
        "require_customer_manager",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(
            return_value=_idempotency_state(
                scope="customer.activate",
                key="reactivate-with-pending-review",
            )
        ),
    )

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.activate_customer(
            actor_user_id=ADVISOR_ID,
            customer_id=BUSINESS_CUSTOMER_ID,
            expected_revision=1,
            idempotency_key="reactivate-with-pending-review",
        )

    assert exc_info.value.code == (
        "customer_pending_review_requires_resolution"
    )
    statement = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "agency_order.status = " in statement
    assert "pending_review" in statement
