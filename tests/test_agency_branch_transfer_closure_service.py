from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agency.branch_administration import BranchClosureReadiness
from app.agency.customer_lifecycle_service import CustomerLifecycleService
from app.agency.errors import AgencyTransactionConflict
from app.agency.transaction_service import IdempotencyState
from app.schemas.agency_customer_lifecycle import (
    AgencyBranchClosureReadinessResponse,
)


NOW = datetime(2026, 7, 31, 9, 0, tzinfo=UTC)
AGENCY_ID = uuid.UUID(int=1)
SOURCE_BRANCH_ID = uuid.UUID(int=2)
TARGET_BRANCH_ID = uuid.UUID(int=3)
CUSTOMER_ID = uuid.UUID(int=4)
ACTOR_ID = uuid.UUID(int=5)
ASSIGNMENT_ID = uuid.UUID(int=6)
TRANSFER_ID = uuid.UUID(int=7)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value

    def __iter__(self):
        return iter(self.value)


class _Db:
    def __init__(self, *values):
        self.values = list(values)
        self.added = []
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError(f"unexpected SQL: {statement}")
        return _Result(self.values.pop(0))

    def add(self, resource):
        if resource.__class__.__name__ == "AgencyCustomerBranchTransfer":
            resource.id = TRANSFER_ID
        self.added.append(resource)


def _idempotency_state(*, replayed: bool = False) -> IdempotencyState:
    return IdempotencyState(
        record=SimpleNamespace(
            status="completed" if replayed else "in_progress",
            resource_type=(
                "agency_customer_branch_transfer" if replayed else None
            ),
            resource_id=str(TRANSFER_ID) if replayed else None,
        ),
        replayed=replayed,
    )


def _customer(**updates):
    values = {
        "id": CUSTOMER_ID,
        "agency_id": AGENCY_ID,
        "branch_id": SOURCE_BRANCH_ID,
        "customer_no": "CUST-TEST",
        "status": "active",
        "lifecycle_revision": 3,
        "updated_at": NOW,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _branch(branch_id: uuid.UUID, *, status: str):
    return SimpleNamespace(
        id=branch_id,
        agency_id=AGENCY_ID,
        status=status,
        revision=1,
        deactivated_at=None,
        closed_at=None,
    )


@pytest.mark.asyncio
async def test_transfer_moves_current_branch_without_rewriting_old_assignment(
    monkeypatch: pytest.MonkeyPatch,
):
    customer = _customer()
    source = _branch(SOURCE_BRANCH_ID, status="inactive")
    target = _branch(TARGET_BRANCH_ID, status="active")
    old_assignment = SimpleNamespace(
        id=ASSIGNMENT_ID,
        status="active",
        ended_at=None,
        ended_reason=None,
    )
    db = _Db([source, target], None, old_assignment)
    service = CustomerLifecycleService(db, now_factory=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service.authorization,
        "require_agency_wide",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=_idempotency_state()),
    )
    monkeypatch.setattr(
        service,
        "_ensure_customer_transfer_has_no_open_work",
        AsyncMock(),
    )
    monkeypatch.setattr(service, "_flush", AsyncMock())
    append_event = AsyncMock()
    monkeypatch.setattr(service, "_append_customer_event", append_event)
    monkeypatch.setattr(
        service,
        "_finish_action",
        AsyncMock(side_effect=lambda _state, **kwargs: kwargs["resource"]),
    )

    transfer = await service.transfer_customer_branch(
        actor_user_id=ACTOR_ID,
        customer_id=CUSTOMER_ID,
        expected_revision=3,
        target_branch_id=TARGET_BRANCH_ID,
        target_advisor_role_grant_id=None,
        reason="原门店停止营业",
        idempotency_key="transfer-once",
    )

    assert transfer.id == TRANSFER_ID
    assert transfer.from_branch_id == SOURCE_BRANCH_ID
    assert transfer.to_branch_id == TARGET_BRANCH_ID
    assert transfer.customer_revision == 4
    assert customer.branch_id == TARGET_BRANCH_ID
    assert customer.lifecycle_revision == 4
    assert old_assignment.status == "ended"
    assert old_assignment.ended_at == NOW
    assert old_assignment.ended_reason == "原门店停止营业"
    event_call = append_event.await_args.kwargs
    assert event_call["event_type"] == "customer_branch_transferred"
    assert event_call["customer"] is customer
    assert event_call["event_metadata"]["from_branch_id"] == str(
        SOURCE_BRANCH_ID
    )
    assert event_call["event_metadata"]["external_action_triggered"] is False


@pytest.mark.asyncio
async def test_transfer_replay_succeeds_after_customer_is_already_in_target(
    monkeypatch: pytest.MonkeyPatch,
):
    customer = _customer(branch_id=TARGET_BRANCH_ID, lifecycle_revision=4)
    replayed_transfer = SimpleNamespace(id=TRANSFER_ID)
    service = CustomerLifecycleService(_Db())  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service.authorization,
        "require_agency_wide",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=_idempotency_state(replayed=True)),
    )
    monkeypatch.setattr(
        service,
        "_load_replayed_resource",
        AsyncMock(return_value=replayed_transfer),
    )

    result = await service.transfer_customer_branch(
        actor_user_id=ACTOR_ID,
        customer_id=CUSTOMER_ID,
        expected_revision=3,
        target_branch_id=TARGET_BRANCH_ID,
        target_advisor_role_grant_id=None,
        reason="原门店停止营业",
        idempotency_key="transfer-once",
    )

    assert result is replayed_transfer


@pytest.mark.asyncio
async def test_transfer_fails_closed_on_pending_invitation():
    service = CustomerLifecycleService(_Db(uuid.uuid4()))  # type: ignore[arg-type]

    with pytest.raises(
        AgencyTransactionConflict,
        match="待认领邀请",
    ) as raised:
        await service._ensure_customer_transfer_has_no_open_work(_customer())

    assert raised.value.code == "customer_branch_transfer_pending_invitation"


@pytest.mark.asyncio
async def test_deactivate_enters_drain_period_without_readiness_precondition(
    monkeypatch: pytest.MonkeyPatch,
):
    branch = _branch(SOURCE_BRANCH_ID, status="active")
    service = CustomerLifecycleService(_Db(), now_factory=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_get_branch", AsyncMock(return_value=branch))
    monkeypatch.setattr(
        service.authorization,
        "require_agency_wide",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=_idempotency_state()),
    )
    append_event = AsyncMock()
    monkeypatch.setattr(
        service,
        "_append_branch_lifecycle_event",
        append_event,
    )
    monkeypatch.setattr(
        service,
        "_finish_action",
        AsyncMock(side_effect=lambda _state, **kwargs: kwargs["resource"]),
    )

    result = await service.deactivate_branch(
        actor_user_id=ACTOR_ID,
        branch_id=SOURCE_BRANCH_ID,
        expected_revision=1,
        reason="停止接收新业务",
        idempotency_key="deactivate-branch",
    )

    assert result is branch
    assert branch.status == "inactive"
    assert branch.revision == 2
    assert branch.deactivated_at == NOW
    assert branch.closed_at is None
    assert append_event.await_args.kwargs["event_type"] == "deactivated"


@pytest.mark.asyncio
async def test_close_refuses_any_remaining_current_customer(
    monkeypatch: pytest.MonkeyPatch,
):
    branch = _branch(SOURCE_BRANCH_ID, status="inactive")
    branch.revision = 2
    service = CustomerLifecycleService(_Db())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_get_branch", AsyncMock(return_value=branch))
    monkeypatch.setattr(
        service.authorization,
        "require_agency_wide",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=_idempotency_state()),
    )
    monkeypatch.setattr(
        service,
        "_branch_closure_readiness",
        AsyncMock(
            return_value=BranchClosureReadiness(
                branch_id=SOURCE_BRANCH_ID,
                status="inactive",
                revision=2,
                ready=False,
                current_customer_count=1,
                pending_invitation_count=0,
                active_assignment_count=0,
                active_role_grant_count=0,
                pending_review_count=0,
                open_quote_count=0,
                open_order_count=0,
                open_cancellation_case_count=0,
            )
        ),
    )

    with pytest.raises(
        AgencyTransactionConflict,
        match="必须先完成清理",
    ) as raised:
        await service.close_branch(
            actor_user_id=ACTOR_ID,
            branch_id=SOURCE_BRANCH_ID,
            expected_revision=2,
            reason="清理完成",
            idempotency_key="close-branch",
        )

    assert raised.value.code == "branch_close_blocked"
    assert branch.status == "inactive"


@pytest.mark.asyncio
async def test_closure_readiness_returns_counts_without_resource_ids():
    db = _Db(2, 1, 1, 3, 1, 2, 1, 1)
    service = CustomerLifecycleService(db)  # type: ignore[arg-type]
    branch = _branch(SOURCE_BRANCH_ID, status="inactive")
    branch.revision = 2

    readiness = await service._branch_closure_readiness(branch)

    assert readiness.current_customer_count == 2
    assert readiness.active_role_grant_count == 3
    assert readiness.open_cancellation_case_count == 1
    assert readiness.ready is False
    assert "customer_id" not in readiness.__dict__
    assert "order_id" not in readiness.__dict__
    response = AgencyBranchClosureReadinessResponse.model_validate(readiness)
    assert response.current_customer_count == 2
