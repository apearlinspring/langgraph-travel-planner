from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import false, true

from app.agency.cancellation_service import CancellationService
from app.agency.customer_lifecycle_service import CustomerLifecycleService
from app.agency.errors import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
    AgencyTransactionValidationError,
)
from app.agency.transaction_service import IdempotencyState
from app.models.agency_cancellation import (
    AgencyOrderCancellationCase,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)
from app.models.agency_transaction import AgencyOrder
from tests.agency_transaction_test_support import (
    ADVISOR_ID,
    AGENCY_ID,
    APPROVER_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    NOW,
    ORDER_ID,
    order_record,
)

CASE_ID = uuid.UUID("51000000-0000-0000-0000-000000000001")
RECORD_ID = uuid.UUID("61000000-0000-0000-0000-000000000001")
SECOND_RECORD_ID = uuid.UUID("61000000-0000-0000-0000-000000000002")
RECONCILIATION_ID = uuid.UUID(
    "71000000-0000-0000-0000-000000000001"
)
MANAGER_ID = uuid.UUID("81000000-0000-0000-0000-000000000001")
BOOKING_OPERATOR_ID = uuid.UUID(
    "81000000-0000-0000-0000-000000000002"
)
FINANCE_ID = uuid.UUID("81000000-0000-0000-0000-000000000003")
AUDITOR_ID = uuid.UUID("81000000-0000-0000-0000-000000000004")
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


class _ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class _Db:
    def __init__(self, *values) -> None:
        self.values = list(values)
        self.statements = []
        self.added = []
        self.compensation_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError(f"unexpected SQL: {statement}")
        return _ScalarResult(self.values.pop(0))

    def add(self, resource) -> None:
        if getattr(resource, "id", None) is None:
            if isinstance(resource, AgencyOrderCancellationCase):
                resource.id = CASE_ID
            elif isinstance(resource, AgencyOrderCompensationRecord):
                resource.id = (
                    RECORD_ID
                    if self.compensation_count == 0
                    else SECOND_RECORD_ID
                )
                self.compensation_count += 1
            elif isinstance(resource, AgencyOrderReconciliationRecord):
                resource.id = RECONCILIATION_ID
        self.added.append(resource)


def _customer(**updates):
    values = {
        "id": BUSINESS_CUSTOMER_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "user_id": CUSTOMER_ID,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _case(**updates):
    values = {
        "id": CASE_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "order_id": ORDER_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "revision": 1,
        "status": "approval_pending",
        "order_revision_at_request": 1,
        "reason_code": "customer_request",
        "reason_detail": None,
        "supplier_cancel_required": False,
        "refund_required": False,
        "approved_refund_amount": None,
        "currency": "CNY",
        "requested_by_user_id": CUSTOMER_ID,
        "requested_at": NOW,
        "review_decision": None,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "review_note": None,
        "external_action_triggered": False,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _record(**updates):
    values = {
        "id": RECORD_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "order_id": ORDER_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "cancellation_case_id": CASE_ID,
        "record_sequence": 1,
        "case_revision": 2,
        "action_type": "supplier_cancel",
        "outcome": "succeeded",
        "external_reference_hash": SHA_A,
        "evidence_hash": SHA_B,
        "amount": Decimal("0.00"),
        "currency": "CNY",
        "occurred_at": NOW,
        "recorded_by_user_id": BOOKING_OPERATOR_ID,
        "system_external_action_triggered": False,
        "created_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _reconciliation(**updates):
    values = {
        "id": RECONCILIATION_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "order_id": ORDER_ID,
        "customer_id": BUSINESS_CUSTOMER_ID,
        "cancellation_case_id": CASE_ID,
        "compensation_record_id": RECORD_ID,
        "case_revision": 3,
        "outcome": "matched",
        "observed_amount": None,
        "currency": None,
        "reconciled_by_user_id": AUDITOR_ID,
        "evidence_hash": SHA_C,
        "reconciled_at": NOW,
        "created_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _state(*, replayed: bool = False, resource_type: str | None = None):
    return IdempotencyState(
        record=SimpleNamespace(
            status="completed" if replayed else "in_progress",
            resource_type=resource_type,
            resource_id=None,
        ),
        replayed=replayed,
    )


async def _return_resource(
    _state_value,
    *,
    resource_type: str,
    resource,
):
    del resource_type
    return resource


def _service(db: _Db | None = None) -> CancellationService:
    service = CancellationService(  # type: ignore[arg-type]
        db or _Db(),
        now_factory=lambda: NOW,
    )
    service._begin_idempotent_action = AsyncMock(return_value=_state())
    service._finish_action = AsyncMock(side_effect=_return_resource)
    service._flush = AsyncMock()
    service._append_case_event = AsyncMock()
    service._append_order_event = AsyncMock()
    service._ensure_agency_active = AsyncMock()
    service._ensure_branch_has_active_approver = AsyncMock()
    return service


def _install_versioning_flush(
    service: CancellationService,
    *,
    case=None,
    order=None,
) -> None:
    case_status = getattr(case, "status", None)
    case_revision = getattr(case, "revision", None)
    order_status = getattr(order, "status", None)
    order_revision = getattr(order, "revision", None)

    async def _flush() -> None:
        if (
            case is not None
            and case.status != case_status
            and case.revision == case_revision
        ):
            case.revision += 1
        if (
            order is not None
            and order.status != order_status
            and order.revision == order_revision
        ):
            order.revision += 1

    service._flush = AsyncMock(side_effect=_flush)


@pytest.mark.asyncio
async def test_lock_order_context_uses_customer_first_ordered_lock_chain():
    log: list[str] = []
    payment = SimpleNamespace(id=uuid.uuid4())
    fulfillment = SimpleNamespace(id=uuid.uuid4())

    class _LedgerDb(_Db):
        async def execute(self, statement):
            log.append("payment" if not self.statements else "fulfillment")
            self.statements.append(statement)
            return _ScalarResult(
                [payment] if len(self.statements) == 1 else [fulfillment]
            )

    service = CancellationService(_LedgerDb())  # type: ignore[arg-type]
    preview = order_record()
    locked = order_record()
    customer = _customer()

    async def _get_order(_order_id, *, for_update=False):
        log.append("order_locked" if for_update else "order_preview")
        return locked if for_update else preview

    async def _get_customer_binding(**_kwargs):
        log.append("customer")
        return customer

    async def _authorize(**_kwargs):
        log.append("branch_auth")

    service._get_order = AsyncMock(side_effect=_get_order)
    service._get_customer_binding = AsyncMock(
        side_effect=_get_customer_binding
    )
    service._authorize_locked_context = AsyncMock(side_effect=_authorize)

    result = await service._lock_order_context(
        order_id=ORDER_ID,
        actor_user_id=CUSTOMER_ID,
        permission="request",
    )

    assert log == [
        "order_preview",
        "customer",
        "branch_auth",
        "order_locked",
        "payment",
        "fulfillment",
    ]
    assert result == (customer, locked, [payment], [fulfillment])


@pytest.mark.asyncio
async def test_lock_order_context_rechecks_binding_after_order_lock():
    service = CancellationService(_Db())  # type: ignore[arg-type]
    service._get_order = AsyncMock(
        side_effect=[
            order_record(),
            order_record(branch_id=uuid.uuid4()),
        ]
    )
    service._get_customer_binding = AsyncMock(return_value=_customer())
    service._authorize_locked_context = AsyncMock()

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service._lock_order_context(
            order_id=ORDER_ID,
            actor_user_id=CUSTOMER_ID,
            permission="request",
        )

    assert exc_info.value.code == "transaction_binding_conflict"


@pytest.mark.asyncio
async def test_case_lock_happens_after_order_ledgers_and_rechecks_binding():
    service = CancellationService(_Db())  # type: ignore[arg-type]
    case = _case()
    order = order_record()
    log: list[str] = []

    async def _get_case(_case_id, *, for_update=False):
        log.append("case_locked" if for_update else "case_preview")
        return case

    async def _lock_order_context(**_kwargs):
        log.append("order_and_ledgers")
        return _customer(), order, [], []

    service._get_case = AsyncMock(side_effect=_get_case)
    service._lock_order_context = AsyncMock(
        side_effect=_lock_order_context
    )

    result = await service._lock_case_context(
        case_id=CASE_ID,
        actor_user_id=APPROVER_ID,
        permission="review",
    )

    assert log == ["case_preview", "order_and_ledgers", "case_locked"]
    assert result == (case, order, [], [])


@pytest.mark.asyncio
async def test_request_authorization_accepts_customer_or_scoped_staff():
    service = CancellationService(_Db())  # type: ignore[arg-type]
    order = order_record()
    customer = _customer()
    service.authorization.lock_active_branch_scope = AsyncMock()
    service.authorization.require_quote_manager = AsyncMock()

    await service._authorize_locked_context(
        permission="request",
        actor_user_id=CUSTOMER_ID,
        customer=customer,
        order=order,
    )
    await service._authorize_locked_context(
        permission="request",
        actor_user_id=ADVISOR_ID,
        customer=customer,
        order=order,
    )

    service.authorization.lock_active_branch_scope.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
    )
    service.authorization.require_quote_manager.assert_awaited_once_with(
        customer=customer,
        actor_user_id=ADVISOR_ID,
        lock_scope=True,
    )


@pytest.mark.parametrize(
    ("permission", "role", "actor"),
    [
        ("booking_operator", "booking_operator", BOOKING_OPERATOR_ID),
        ("finance", "finance", FINANCE_ID),
        ("auditor", "auditor", AUDITOR_ID),
    ],
)
@pytest.mark.asyncio
async def test_operational_roles_never_inherit_agency_wide_permission(
    permission: str,
    role: str,
    actor: uuid.UUID,
):
    service = CancellationService(_Db())  # type: ignore[arg-type]
    require_role = AsyncMock()
    service.authorization.require_branch_role = require_role

    await service._authorize_locked_context(
        permission=permission,
        actor_user_id=actor,
        customer=_customer(),
        order=order_record(),
    )

    require_role.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=actor,
        roles={role},
        allow_agency_wide=False,
        lock_scope=True,
    )


@pytest.mark.asyncio
async def test_review_is_dedicated_approver_and_resume_is_manager_scoped():
    service = CancellationService(_Db())  # type: ignore[arg-type]
    service.authorization.require_branch_approver = AsyncMock()
    service.authorization.require_branch_role = AsyncMock()
    customer = _customer()
    order = order_record()

    await service._authorize_locked_context(
        permission="review",
        actor_user_id=APPROVER_ID,
        customer=customer,
        order=order,
    )
    await service._authorize_locked_context(
        permission="resume",
        actor_user_id=MANAGER_ID,
        customer=customer,
        order=order,
    )

    service.authorization.require_branch_approver.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=APPROVER_ID,
        lock_scope=True,
    )
    service.authorization.require_branch_role.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=MANAGER_ID,
        roles={"branch_manager"},
        allow_agency_wide=True,
        lock_scope=True,
    )


def test_required_actions_are_derived_from_locked_server_state():
    clean = order_record()
    assert CancellationService._derive_required_actions(clean, [], []) == (
        False,
        False,
    )

    payment = SimpleNamespace(
        status="succeeded",
        external_action_enabled=False,
        provider_reference=None,
    )
    fulfillment = SimpleNamespace(
        status="confirmed",
        external_action_enabled=False,
        provider_reference=None,
    )
    assert CancellationService._derive_required_actions(
        clean,
        [payment],
        [fulfillment],
    ) == (True, True)

    failed_without_exposure = SimpleNamespace(
        status="failed",
        external_action_enabled=False,
        provider_reference=None,
    )
    assert CancellationService._derive_required_actions(
        clean,
        [failed_without_exposure],
        [],
    ) == (False, False)

    legacy_pending = order_record(status="cancellation_pending")
    assert CancellationService._derive_required_actions(
        legacy_pending,
        [],
        [],
    ) == (True, False)

    refunded_projection = order_record(payment_status="refunded")
    assert CancellationService._derive_required_actions(
        refunded_projection,
        [],
        [],
    ) == (False, True)


def test_required_action_snapshot_fails_closed_when_exposure_changes():
    service = _service()
    case = _case(
        supplier_cancel_required=True,
        refund_required=False,
    )
    order = order_record(
        status="cancellation_pending",
        cancellation_requested_at=NOW,
    )
    new_payment = SimpleNamespace(
        status="succeeded",
        external_action_enabled=False,
        provider_reference=None,
    )

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        service._ensure_required_actions_unchanged(
            case=case,
            order=order,
            payments=[new_payment],
            fulfillments=[],
        )

    assert exc_info.value.code == "cancellation_order_exposure_changed"


def test_manual_result_time_rejects_more_than_five_minutes_in_future():
    service = _service()

    with pytest.raises(AgencyTransactionValidationError) as exc_info:
        service._occurred_at(NOW + timedelta(minutes=5, seconds=1))

    assert exc_info.value.code == "cancellation_occurred_at_in_future"
    assert service._occurred_at(NOW + timedelta(minutes=5)) == (
        NOW + timedelta(minutes=5)
    )


@pytest.mark.asyncio
async def test_pending_review_request_fails_closed_before_case_creation():
    db = _Db()
    service = _service(db)
    order = order_record(status="pending_review", revision=2)
    service._lock_order_context = AsyncMock(
        return_value=(_customer(), order, [], [])
    )

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.request_cancellation(
            actor_user_id=CUSTOMER_ID,
            order_id=ORDER_ID,
            expected_revision=2,
            reason_code="customer_request",
            reason_detail=None,
            idempotency_key="pending-review",
        )

    assert exc_info.value.code == "cancellation_order_review_pending"
    assert db.added == []


@pytest.mark.asyncio
async def test_request_persists_only_server_derived_flags_and_no_external_action():
    db = _Db(None)
    service = _service(db)
    order = order_record(status="approved", revision=4)
    payment = SimpleNamespace(
        status="succeeded",
        external_action_enabled=True,
        provider_reference="provider-reference-is-not-copied",
    )
    service._lock_order_context = AsyncMock(
        return_value=(_customer(), order, [payment], [])
    )

    result = await service.request_cancellation(
        actor_user_id=CUSTOMER_ID,
        order_id=ORDER_ID,
        expected_revision=4,
        reason_code="customer_request",
        reason_detail="联系 customer@example.test 取消",
        idempotency_key="create-case",
    )

    assert result is db.added[0]
    assert result.refund_required is True
    assert result.supplier_cancel_required is False
    assert result.external_action_triggered is False
    assert "customer@example.test" not in (result.reason_detail or "")
    assert order.status == "approved"
    assert order.revision == 4
    assert order.cancellation_requested_at is None
    service._ensure_branch_has_active_approver.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        excluded_user_ids=(CUSTOMER_ID,),
    )
    metadata = service._append_case_event.await_args.kwargs[
        "event_metadata"
    ]
    assert metadata["external_actions_triggered"] is False
    assert "provider-reference-is-not-copied" not in repr(metadata)


@pytest.mark.asyncio
async def test_last_approver_revoke_requires_eligible_replacement():
    db = _Db(
        None,
        [(CUSTOMER_ID, CUSTOMER_ID)],
        [CUSTOMER_ID],
    )
    service = CustomerLifecycleService(db)  # type: ignore[arg-type]
    branch = SimpleNamespace(id=BRANCH_ID, agency_id=AGENCY_ID)
    grant = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        role="approver",
        status="active",
        revision=1,
    )
    service._get_branch = AsyncMock(return_value=branch)
    service._get_grant = AsyncMock(return_value=grant)
    service.authorization.require_agency_wide = AsyncMock()
    service._begin_idempotent_action = AsyncMock(return_value=_state())

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.revoke_branch_role_grant(
            actor_user_id=MANAGER_ID,
            branch_id=BRANCH_ID,
            grant_id=grant.id,
            expected_revision=1,
            reason="preserve independent approval",
            idempotency_key="revoke-last-eligible-approver",
        )

    assert exc_info.value.code == "branch_approver_grant_in_use"
    assert grant.status == "active"
    pending_sql = str(db.statements[1])
    assert "UNION ALL" in pending_sql
    assert "agency_order_cancellation_case" in pending_sql


@pytest.mark.asyncio
async def test_approver_revoke_checks_each_pending_business_exclusions():
    first_replacement = uuid.UUID(
        "91000000-0000-0000-0000-000000000001"
    )
    second_replacement = uuid.UUID(
        "91000000-0000-0000-0000-000000000002"
    )
    db = _Db(
        None,
        [
            (first_replacement, second_replacement),
            (CUSTOMER_ID, MANAGER_ID),
        ],
        [first_replacement, second_replacement],
    )
    service = CustomerLifecycleService(db)  # type: ignore[arg-type]
    branch = SimpleNamespace(id=BRANCH_ID, agency_id=AGENCY_ID)
    grant = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        role="approver",
        status="active",
        revision=1,
    )
    service._get_branch = AsyncMock(return_value=branch)
    service._get_grant = AsyncMock(return_value=grant)
    service.authorization.require_agency_wide = AsyncMock()
    service._begin_idempotent_action = AsyncMock(return_value=_state())

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.revoke_branch_role_grant(
            actor_user_id=MANAGER_ID,
            branch_id=BRANCH_ID,
            grant_id=grant.id,
            expected_revision=1,
            reason="one pending item excludes both replacements",
            idempotency_key="revoke-multi-business-approver",
        )

    assert exc_info.value.code == "branch_approver_grant_in_use"
    assert grant.status == "active"


@pytest.mark.asyncio
async def test_completed_request_replays_before_terminal_order_validation():
    service = _service()
    order = order_record(
        status="cancelled",
        revision=9,
        cancellation_requested_at=NOW,
        cancelled_at=NOW,
    )
    completed = _case(status="completed", revision=2, completed_at=NOW)
    service._lock_order_context = AsyncMock(
        return_value=(_customer(), order, [], [])
    )
    service._begin_idempotent_action = AsyncMock(
        return_value=_state(
            replayed=True,
            resource_type="agency_order_cancellation_case",
        )
    )
    service._load_replayed_case = AsyncMock(return_value=completed)
    service._ensure_order_requestable = MagicMock(
        side_effect=AssertionError("terminal validation ran before replay")
    )

    result = await service.request_cancellation(
        actor_user_id=CUSTOMER_ID,
        order_id=ORDER_ID,
        expected_revision=1,
        reason_code="customer_request",
        reason_detail=None,
        idempotency_key="replay-completed",
    )

    assert result is completed
    service._ensure_order_requestable.assert_not_called()
    service._ensure_agency_active.assert_not_awaited()
    service._ensure_branch_has_active_approver.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_result_replay_precedes_required_action_revalidation():
    service = _service()
    case = _case(
        status="completed",
        revision=4,
        supplier_cancel_required=True,
        completed_at=NOW,
    )
    order = order_record(status="cancelled", revision=7, cancelled_at=NOW)
    record = _record(case_revision=3)
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._begin_idempotent_action = AsyncMock(
        return_value=_state(
            replayed=True,
            resource_type="agency_order_compensation_record",
        )
    )
    service._load_replayed_compensation = AsyncMock(return_value=record)
    service._ensure_required_actions_unchanged = MagicMock(
        side_effect=AssertionError(
            "required actions were revalidated before replay"
        )
    )

    result = await service.record_manual_result(
        actor_user_id=BOOKING_OPERATOR_ID,
        case_id=CASE_ID,
        expected_revision=2,
        action_type="supplier_cancel",
        outcome="succeeded",
        external_reference_sha256=SHA_A,
        evidence_sha256=SHA_B,
        amount=None,
        currency=None,
        occurred_at=NOW,
        idempotency_key="replay-manual-result",
    )

    assert result is record
    service._ensure_required_actions_unchanged.assert_not_called()


@pytest.mark.asyncio
async def test_final_reconciliation_replays_after_order_is_cancelled():
    service = _service()
    case = _case(
        status="completed",
        revision=4,
        supplier_cancel_required=True,
        completed_at=NOW,
    )
    order = order_record(status="cancelled", revision=7, cancelled_at=NOW)
    record = _record(case_revision=3)
    reconciliation = _reconciliation(case_revision=4)
    service._get_compensation = AsyncMock(return_value=record)
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._begin_idempotent_action = AsyncMock(
        return_value=_state(
            replayed=True,
            resource_type="agency_order_reconciliation_record",
        )
    )
    service._load_replayed_reconciliation = AsyncMock(
        return_value=reconciliation
    )
    service._ensure_required_actions_unchanged = MagicMock(
        side_effect=AssertionError(
            "required actions were revalidated before replay"
        )
    )

    result = await service.reconcile_manual_result(
        actor_user_id=AUDITOR_ID,
        record_id=RECORD_ID,
        expected_revision=3,
        outcome="matched",
        observed_amount=None,
        observed_currency=None,
        evidence_sha256=SHA_C,
        idempotency_key="replay-final-reconciliation",
    )

    assert result is reconciliation
    service._ensure_required_actions_unchanged.assert_not_called()


@pytest.mark.asyncio
async def test_resume_replay_precedes_required_action_revalidation():
    service = _service()
    case = _case(
        status="action_pending",
        revision=5,
        supplier_cancel_required=True,
    )
    order = order_record(
        status="cancellation_pending",
        revision=9,
        cancellation_requested_at=NOW,
    )
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._begin_idempotent_action = AsyncMock(
        return_value=_state(
            replayed=True,
            resource_type="agency_order_cancellation_case",
        )
    )
    service._load_replayed_case = AsyncMock(return_value=case)
    service._ensure_required_actions_unchanged = MagicMock(
        side_effect=AssertionError(
            "required actions were revalidated before replay"
        )
    )

    result = await service.resume_cancellation(
        actor_user_id=MANAGER_ID,
        case_id=CASE_ID,
        expected_revision=4,
        reason="resume after response loss",
        idempotency_key="replay-resume",
    )

    assert result is case
    service._ensure_required_actions_unchanged.assert_not_called()


@pytest.mark.parametrize("actor", [APPROVER_ID, CUSTOMER_ID])
@pytest.mark.asyncio
async def test_review_enforces_four_eyes_against_requester_and_customer(
    actor: uuid.UUID,
):
    service = _service()
    order = order_record()
    case = _case(
        requested_by_user_id=(
            APPROVER_ID if actor == APPROVER_ID else MANAGER_ID
        )
    )
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )

    with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
        await service.review_cancellation(
            actor_user_id=actor,
            case_id=CASE_ID,
            decision="approve",
            expected_revision=1,
            approved_refund_amount=None,
            approved_refund_currency=None,
            reason=None,
            idempotency_key="four-eyes",
        )

    assert exc_info.value.code == (
        "cancellation_review_self_decision_denied"
    )


@pytest.mark.parametrize(
    (
        "refund_required",
        "payment_status",
        "amount",
        "currency",
        "error_code",
    ),
    [
        (
            True,
            "paid",
            None,
            None,
            "cancellation_refund_approval_required",
        ),
        (
            True,
            "paid",
            Decimal("1288.51"),
            "CNY",
            "cancellation_refund_amount_exceeds_order",
        ),
        (
            True,
            "paid",
            Decimal("100.00"),
            "USD",
            "cancellation_refund_approval_required",
        ),
        (
            False,
            "not_started",
            Decimal("1.00"),
            "CNY",
            "cancellation_refund_not_required",
        ),
    ],
)
@pytest.mark.asyncio
async def test_review_enforces_refund_approval_boundary(
    refund_required: bool,
    payment_status: str,
    amount: Decimal | None,
    currency: str | None,
    error_code: str,
):
    service = _service()
    order = order_record(payment_status=payment_status)
    case = _case(refund_required=refund_required)
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )

    with pytest.raises(AgencyTransactionValidationError) as exc_info:
        await service.review_cancellation(
            actor_user_id=APPROVER_ID,
            case_id=CASE_ID,
            decision="approve",
            expected_revision=1,
            approved_refund_amount=amount,
            approved_refund_currency=currency,
            reason=None,
            idempotency_key=f"refund-boundary-{error_code}",
        )

    assert exc_info.value.code == error_code


@pytest.mark.asyncio
async def test_stale_request_can_be_rejected_but_not_approved():
    stale_order = order_record(
        status="cancelled",
        revision=2,
        cancellation_requested_at=NOW,
        cancelled_at=NOW,
    )

    reject_service = _service()
    rejected_case = _case(order_revision_at_request=1)
    reject_service._lock_case_context = AsyncMock(
        return_value=(rejected_case, stale_order, [], [])
    )
    _install_versioning_flush(reject_service, case=rejected_case)

    result = await reject_service.review_cancellation(
        actor_user_id=APPROVER_ID,
        case_id=CASE_ID,
        decision="reject",
        expected_revision=1,
        approved_refund_amount=None,
        approved_refund_currency=None,
        reason="订单已由客户生命周期流程收口",
        idempotency_key="reject-stale-cancellation",
    )

    assert result.status == "rejected"
    assert stale_order.status == "cancelled"

    approve_service = _service()
    pending_case = _case(order_revision_at_request=1)
    approve_service._lock_case_context = AsyncMock(
        return_value=(pending_case, stale_order, [], [])
    )

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await approve_service.review_cancellation(
            actor_user_id=APPROVER_ID,
            case_id=CASE_ID,
            decision="approve",
            expected_revision=1,
            approved_refund_amount=None,
            approved_refund_currency=None,
            reason=None,
            idempotency_key="approve-stale-cancellation",
        )

    assert exc_info.value.code == "cancellation_order_exposure_changed"


@pytest.mark.asyncio
async def test_clean_approval_completes_only_internal_cancellation():
    service = _service()
    order = order_record(status="approved", revision=4)
    case = _case(order_revision_at_request=4)
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    _install_versioning_flush(service, case=case, order=order)

    result = await service.review_cancellation(
        actor_user_id=APPROVER_ID,
        case_id=CASE_ID,
        decision="approve",
        expected_revision=1,
        approved_refund_amount=None,
        approved_refund_currency=None,
        reason="内部状态核对完成",
        idempotency_key="clean-completion",
    )

    assert result is case
    assert case.status == "completed"
    assert case.revision == 2
    assert case.external_action_triggered is False
    assert case.completed_at == NOW
    assert order.status == "cancelled"
    assert order.revision == 5
    assert order.cancellation_requested_at == NOW
    assert order.cancelled_at == NOW
    assert order.external_action_enabled is False
    order_metadata = service._append_order_event.await_args.kwargs[
        "event_metadata"
    ]
    assert order_metadata["external_actions_triggered"] is False


@pytest.mark.asyncio
async def test_first_of_two_successful_actions_keeps_case_revision_stable():
    db = _Db()
    service = _service(db)
    order = order_record(
        status="cancellation_pending",
        revision=5,
        payment_status="paid",
        fulfillment_status="confirmed",
        cancellation_requested_at=NOW,
    )
    case = _case(
        revision=2,
        status="action_pending",
        supplier_cancel_required=True,
        refund_required=True,
        approved_refund_amount=Decimal("12.34"),
        review_decision="approved",
    )
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._case_records = AsyncMock(return_value=([], []))
    _install_versioning_flush(service, case=case, order=order)

    result = await service.record_manual_result(
        actor_user_id=BOOKING_OPERATOR_ID,
        case_id=CASE_ID,
        expected_revision=2,
        action_type="supplier_cancel",
        outcome="succeeded",
        external_reference_sha256=SHA_A,
        evidence_sha256=SHA_B,
        amount=None,
        currency=None,
        occurred_at=NOW,
        idempotency_key="supplier-success",
    )

    assert result.action_type == "supplier_cancel"
    assert result.outcome == "succeeded"
    assert case.status == "action_pending"
    assert case.revision == 2
    assert result.case_revision == 2
    assert result.system_external_action_triggered is False
    assert result.amount == Decimal("0.00")
    metadata = service._append_case_event.await_args.kwargs[
        "event_metadata"
    ]
    assert metadata["system_external_action_triggered"] is False
    assert SHA_A not in repr(metadata)
    assert SHA_B not in repr(metadata)


@pytest.mark.asyncio
async def test_second_successful_action_advances_to_reconciliation():
    db = _Db()
    service = _service(db)
    order = order_record(
        status="cancellation_pending",
        revision=5,
        payment_status="paid",
        fulfillment_status="confirmed",
        cancellation_requested_at=NOW,
    )
    case = _case(
        revision=2,
        status="action_pending",
        supplier_cancel_required=True,
        refund_required=True,
        approved_refund_amount=Decimal("12.34"),
        review_decision="approved",
    )
    supplier_result = _record()
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._case_records = AsyncMock(
        return_value=([supplier_result], [])
    )
    _install_versioning_flush(service, case=case, order=order)

    result = await service.record_manual_result(
        actor_user_id=FINANCE_ID,
        case_id=CASE_ID,
        expected_revision=2,
        action_type="refund",
        outcome="succeeded",
        external_reference_sha256=SHA_A,
        evidence_sha256=SHA_B,
        amount=Decimal("12.34"),
        currency="CNY",
        occurred_at=NOW,
        idempotency_key="refund-success",
    )

    assert case.status == "reconciliation_pending"
    assert case.revision == 3
    assert result.case_revision == 3
    assert order.status == "cancellation_pending"
    assert order.revision == 5


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
@pytest.mark.asyncio
async def test_uncertain_manual_result_moves_case_and_order_to_manual(
    outcome: str,
):
    db = _Db()
    service = _service(db)
    order = order_record(
        status="cancellation_pending",
        revision=5,
        cancellation_requested_at=NOW,
    )
    case = _case(
        revision=2,
        status="action_pending",
        supplier_cancel_required=True,
        review_decision="approved",
    )
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._case_records = AsyncMock(return_value=([], []))
    _install_versioning_flush(service, case=case, order=order)

    result = await service.record_manual_result(
        actor_user_id=BOOKING_OPERATOR_ID,
        case_id=CASE_ID,
        expected_revision=2,
        action_type="supplier_cancel",
        outcome=outcome,
        external_reference_sha256=SHA_A,
        evidence_sha256=SHA_B,
        amount=None,
        currency=None,
        occurred_at=NOW,
        idempotency_key=f"supplier-{outcome}",
    )

    assert result.outcome == outcome
    assert case.status == "manual_intervention"
    assert case.revision == 3
    assert order.status == "manual_intervention"
    assert order.revision == 6


@pytest.mark.asyncio
async def test_latest_result_replaces_mismatched_attempt_for_progress():
    db = _Db()
    db.compensation_count = 1
    service = _service(db)
    order = order_record(
        status="cancellation_pending",
        revision=7,
        cancellation_requested_at=NOW,
    )
    case = _case(
        revision=4,
        status="action_pending",
        supplier_cancel_required=True,
        review_decision="approved",
    )
    old = _record()
    mismatch = _reconciliation(outcome="mismatched")
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._case_records = AsyncMock(return_value=([old], [mismatch]))
    _install_versioning_flush(service, case=case, order=order)

    result = await service.record_manual_result(
        actor_user_id=BOOKING_OPERATOR_ID,
        case_id=CASE_ID,
        expected_revision=4,
        action_type="supplier_cancel",
        outcome="succeeded",
        external_reference_sha256=SHA_A,
        evidence_sha256=SHA_B,
        amount=None,
        currency=None,
        occurred_at=NOW,
        idempotency_key="retry-supplier",
    )

    assert result.record_sequence == 2
    assert case.status == "reconciliation_pending"
    assert case.revision == 5

    new_matched = _reconciliation(
        compensation_record_id=result.id,
        outcome="matched",
    )
    assert CancellationService._progress(
        case,
        [old, result],
        [mismatch, new_matched],
    ) == "completed"


@pytest.mark.asyncio
async def test_auditor_cannot_reconcile_own_manual_result():
    service = _service()
    record = _record(recorded_by_user_id=AUDITOR_ID)
    case = _case(
        revision=3,
        status="reconciliation_pending",
        supplier_cancel_required=True,
        review_decision="approved",
    )
    order = order_record(
        status="cancellation_pending",
        cancellation_requested_at=NOW,
    )
    service._get_compensation = AsyncMock(return_value=record)
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )

    with pytest.raises(AgencyTransactionAccessDenied) as exc_info:
        await service.reconcile_manual_result(
            actor_user_id=AUDITOR_ID,
            record_id=RECORD_ID,
            expected_revision=3,
            outcome="matched",
            observed_amount=None,
            observed_currency=None,
            evidence_sha256=SHA_C,
            idempotency_key="self-reconcile",
        )

    assert exc_info.value.code == (
        "cancellation_reconciliation_self_review_denied"
    )


@pytest.mark.asyncio
async def test_matched_reconciliation_completes_case_and_cancels_order():
    db = _Db()
    service = _service(db)
    record = _record(
        action_type="refund",
        amount=Decimal("12.34"),
        recorded_by_user_id=FINANCE_ID,
    )
    case = _case(
        revision=3,
        status="reconciliation_pending",
        refund_required=True,
        approved_refund_amount=Decimal("12.34"),
        review_decision="approved",
    )
    order = order_record(
        status="cancellation_pending",
        revision=6,
        payment_status="paid",
        cancellation_requested_at=NOW,
    )
    service._get_compensation = AsyncMock(return_value=record)
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._case_records = AsyncMock(return_value=([record], []))
    _install_versioning_flush(service, case=case, order=order)

    result = await service.reconcile_manual_result(
        actor_user_id=AUDITOR_ID,
        record_id=RECORD_ID,
        expected_revision=3,
        outcome="matched",
        observed_amount=Decimal("12.34"),
        observed_currency="CNY",
        evidence_sha256=SHA_C,
        idempotency_key="matched-refund",
    )

    assert result.case_revision == 4
    assert result.observed_amount == Decimal("12.34")
    assert result.currency == "CNY"
    assert case.status == "completed"
    assert case.revision == 4
    assert case.completed_at == NOW
    assert order.status == "cancelled"
    assert order.revision == 7
    assert order.cancelled_at == NOW
    assert order.external_action_enabled is False
    metadata = service._append_order_event.await_args.kwargs[
        "event_metadata"
    ]
    assert metadata["external_actions_triggered"] is False


@pytest.mark.asyncio
async def test_resume_returns_manual_case_to_action_without_copying_reason():
    service = _service()
    failed = _record(outcome="failed")
    case = _case(
        revision=4,
        status="manual_intervention",
        supplier_cancel_required=True,
        review_decision="approved",
    )
    order = order_record(
        status="manual_intervention",
        revision=8,
        cancellation_requested_at=NOW,
    )
    service._lock_case_context = AsyncMock(
        return_value=(case, order, [], [])
    )
    service._case_records = AsyncMock(return_value=([failed], []))
    _install_versioning_flush(service, case=case, order=order)

    result = await service.resume_cancellation(
        actor_user_id=MANAGER_ID,
        case_id=CASE_ID,
        expected_revision=4,
        reason="联系 manager@example.test 继续处理",
        idempotency_key="resume-case",
    )

    assert result.status == "action_pending"
    assert result.revision == 5
    assert order.status == "cancellation_pending"
    assert order.revision == 9
    assert order.cancellation_requested_at == NOW
    metadata = service._append_case_event.await_args.kwargs[
        "event_metadata"
    ]
    assert "resume_reason" not in metadata
    assert "manager@example.test" not in repr(metadata)
    assert metadata["external_actions_triggered"] is False


@pytest.mark.asyncio
async def test_manual_result_queue_is_case_scoped_and_includes_reconciliation():
    record = _record()
    db = _Db([record], 1, [(record.id, "matched")])
    service = _service(db)
    case = _case(status="reconciliation_pending")
    order = order_record(status="cancellation_pending")
    service._get_case = AsyncMock(return_value=case)
    service._get_order = AsyncMock(return_value=order)
    service.authorization.require_branch_role = AsyncMock()

    results, total = await service.list_manual_results(
        actor_user_id=AUDITOR_ID,
        case_id=CASE_ID,
        limit=10,
        offset=0,
    )

    assert results == [(record, "matched")]
    assert total == 1
    service.authorization.require_branch_role.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=AUDITOR_ID,
        roles={"auditor"},
        allow_agency_wide=False,
    )
    assert "cancellation_case_id" in str(db.statements[0])


@pytest.mark.parametrize(
    "member_role",
    [None, "owner", "finance", "travel_advisor"],
)
@pytest.mark.asyncio
async def test_manual_result_queue_hides_without_exact_auditor_role(
    member_role: str | None,
):
    values: list[object] = [BRANCH_ID, None]
    if member_role is not None:
        values[1] = SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=AGENCY_ID,
            user_id=CUSTOMER_ID,
            role=member_role,
            status="active",
        )
        values.append(None)
    db = _Db(*values)
    service = _service(db)
    service._get_case = AsyncMock(
        return_value=_case(status="reconciliation_pending")
    )
    service._get_order = AsyncMock(
        return_value=order_record(status="cancellation_pending")
    )

    with pytest.raises(AgencyTransactionNotFound):
        await service.list_manual_results(
            actor_user_id=CUSTOMER_ID,
            case_id=CASE_ID,
            limit=10,
            offset=0,
        )

    assert all(
        "agency_order_compensation_record" not in str(statement)
        for statement in db.statements
    )


@pytest.mark.asyncio
async def test_case_visibility_falls_back_only_to_scoped_operation_roles():
    service = CancellationService(_Db())  # type: ignore[arg-type]
    case = _case()
    order = order_record()
    service.authorization.require_transaction_view = AsyncMock(
        side_effect=AgencyTransactionNotFound(
            "agency_transaction_not_found",
            "交易资源不存在",
        )
    )
    service.authorization.require_branch_role = AsyncMock()

    await service._ensure_case_visible(
        case=case,
        order=order,
        actor_user_id=FINANCE_ID,
    )

    service.authorization.require_branch_role.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=FINANCE_ID,
        roles={"booking_operator", "finance", "auditor"},
        allow_agency_wide=False,
    )


@pytest.mark.asyncio
async def test_case_list_combines_transaction_and_operation_visibility():
    case = _case()
    db = _Db([case], 1)
    service = CancellationService(db)  # type: ignore[arg-type]
    service.authorization.transaction_visibility_filter = AsyncMock(
        return_value=true()
    )
    service.authorization.branch_visibility_filter = AsyncMock(
        return_value=false()
    )

    cases, total = await service.list_cancellation_cases(
        actor_user_id=FINANCE_ID,
        agency_id=AGENCY_ID,
        status_filter="action_pending",
        limit=20,
        offset=0,
    )

    assert cases == [case]
    assert total == 1
    service.authorization.transaction_visibility_filter.assert_awaited_once_with(
        model=AgencyOrder,
        agency_id=AGENCY_ID,
        actor_user_id=FINANCE_ID,
        include_approver=True,
    )
    service.authorization.branch_visibility_filter.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        actor_user_id=FINANCE_ID,
        roles={"booking_operator", "finance", "auditor"},
        branch_column=AgencyOrderCancellationCase.branch_id,
    )
