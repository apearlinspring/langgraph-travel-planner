from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.agency.branch_authorization import (
    BRANCH_DRAIN_STATUSES,
    BRANCH_NEW_WORK_STATUSES,
    BranchAuthorization,
)
from app.agency.cancellation_service import CancellationService
from app.agency.order_review_service import AgencyOrderReviewService
from app.models.agency_customer_lifecycle import AgencyBranch
from app.models.agency_transaction import AgencyOrder
from tests.agency_transaction_test_support import (
    ADVISOR_ID,
    AGENCY_ID,
    APPROVER_ID,
    BRANCH_ID,
    BUSINESS_CUSTOMER_ID,
    CUSTOMER_ID,
    ORDER_ID,
    ExecuteSequence,
    order_record,
)


def _postgres_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_branch_role_default_is_active_but_drain_scope_is_explicit():
    membership = SimpleNamespace(
        id=ADVISOR_ID,
        role="branch_manager",
        status="active",
    )
    grant = SimpleNamespace(role="branch_manager", status="active")
    active_db = ExecuteSequence(BRANCH_ID, membership, grant)
    active_authorization = BranchAuthorization(active_db)  # type: ignore[arg-type]

    await active_authorization.require_branch_role(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=ADVISOR_ID,
        roles={"branch_manager"},
        allow_agency_wide=False,
    )

    active_sql = _postgres_sql(active_db.statements[0])
    assert "agency_branch.status IN ('active')" in active_sql

    drain_db = ExecuteSequence(BRANCH_ID, membership, grant)
    drain_authorization = BranchAuthorization(drain_db)  # type: ignore[arg-type]
    await drain_authorization.require_branch_role(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        actor_user_id=ADVISOR_ID,
        roles={"branch_manager"},
        allow_agency_wide=False,
        allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
    )

    drain_sql = _postgres_sql(drain_db.statements[0])
    assert "agency_branch.status IN" in drain_sql
    assert "'active'" in drain_sql
    assert "'inactive'" in drain_sql


@pytest.mark.asyncio
async def test_active_branch_lock_remains_a_new_work_wrapper():
    authorization = BranchAuthorization(SimpleNamespace())  # type: ignore[arg-type]
    authorization.lock_branch_scope = AsyncMock()

    await authorization.lock_active_branch_scope(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
    )

    authorization.lock_branch_scope.assert_awaited_once_with(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        allowed_branch_statuses=BRANCH_NEW_WORK_STATUSES,
        hide_resource=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "visibility_method",
    [
        "branch_visibility_filter",
        "transaction_visibility_filter",
        "customer_visibility_filter",
    ],
)
async def test_staff_visibility_includes_inactive_branch(
    visibility_method: str,
):
    membership = SimpleNamespace(
        id=ADVISOR_ID,
        role="branch_manager",
        status="active",
    )
    authorization = BranchAuthorization(  # type: ignore[arg-type]
        ExecuteSequence(membership)
    )
    kwargs = {
        "agency_id": AGENCY_ID,
        "actor_user_id": ADVISOR_ID,
    }
    if visibility_method == "transaction_visibility_filter":
        kwargs["model"] = AgencyOrder
    expression = await getattr(authorization, visibility_method)(**kwargs)
    sql = _postgres_sql(
        select(AgencyBranch.id).where(expression)
    )

    assert "'active'" in sql
    assert "'inactive'" in sql


@pytest.mark.asyncio
async def test_cancellation_operations_use_drain_authorization():
    service = CancellationService(SimpleNamespace())  # type: ignore[arg-type]
    order = order_record()
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
    )
    service.authorization.lock_branch_scope = AsyncMock()
    service.authorization.require_quote_manager = AsyncMock()
    service.authorization.require_branch_approver = AsyncMock()
    service.authorization.require_branch_role = AsyncMock()

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
    await service._authorize_locked_context(
        permission="review",
        actor_user_id=APPROVER_ID,
        customer=customer,
        order=order,
    )
    await service._authorize_locked_context(
        permission="finance",
        actor_user_id=ADVISOR_ID,
        customer=customer,
        order=order,
    )
    await service._authorize_locked_context(
        permission="resume",
        actor_user_id=ADVISOR_ID,
        customer=customer,
        order=order,
    )

    assert (
        service.authorization.lock_branch_scope.await_args.kwargs[
            "allowed_branch_statuses"
        ]
        == BRANCH_DRAIN_STATUSES
    )
    assert (
        service.authorization.require_quote_manager.await_args.kwargs[
            "allowed_branch_statuses"
        ]
        == BRANCH_DRAIN_STATUSES
    )
    assert (
        service.authorization.require_branch_approver.await_args.kwargs[
            "allowed_branch_statuses"
        ]
        == BRANCH_DRAIN_STATUSES
    )
    assert all(
        call.kwargs["allowed_branch_statuses"]
        == BRANCH_DRAIN_STATUSES
        for call in service.authorization.require_branch_role.await_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected_statuses"),
    [
        ("approve", BRANCH_NEW_WORK_STATUSES),
        ("reject", BRANCH_DRAIN_STATUSES),
    ],
)
async def test_order_review_decision_separates_new_work_and_drain(
    decision: str,
    expected_statuses: frozenset[str],
):
    service = AgencyOrderReviewService(SimpleNamespace())  # type: ignore[arg-type]
    order = order_record(status="pending_review", revision=2)
    customer = SimpleNamespace(
        id=BUSINESS_CUSTOMER_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        user_id=CUSTOMER_ID,
    )
    service._get_order = AsyncMock(return_value=order)
    service._get_transaction_customer = AsyncMock(return_value=customer)
    service._get_customer_binding = AsyncMock(return_value=customer)
    service._require_order_reviewer = AsyncMock(
        side_effect=RuntimeError("authorization-stop")
    )

    with pytest.raises(RuntimeError, match="authorization-stop"):
        await service.decide_order_review(
            actor_user_id=APPROVER_ID,
            order_id=ORDER_ID,
            decision=decision,
            expected_revision=2,
            reason="拒绝原因" if decision == "reject" else None,
            idempotency_key=f"review-{decision}",
        )

    assert (
        service._require_order_reviewer.await_args.kwargs[
            "allowed_branch_statuses"
        ]
        == expected_statuses
    )
