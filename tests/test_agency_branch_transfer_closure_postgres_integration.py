"""PostgreSQL integration checks for branch transfer and closure governance.

The suite is intentionally opt-in and reuses the isolated-schema fixture whose
database-name gate requires a standalone ``test`` or ``ci`` segment:

    uv run python -m pytest --run-integration -q \
      tests/test_agency_branch_transfer_closure_postgres_integration.py
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from tests.test_agency_cancellation_postgres_integration import (
    _add_exposure,
    _create_order,
    _get_case,
    _get_order,
    _manual_result,
    _reconcile,
    _request_case,
    _review_case,
    _seed_agency_owner,
    _seed_cancellation_operators,
)
from tests.test_agency_customer_lifecycle_postgres_integration import _call
from tests.test_agency_transaction_postgres_integration import (
    PostgresSandbox,
    TenantActors,
    _quote_request,
    _seed_tenant,
    _session_factory,
    migrated_postgres,
    postgres_schema,
)


pytestmark = [pytest.mark.integration, pytest.mark.slow]


@dataclass(frozen=True)
class GovernanceActors:
    owner_id: uuid.UUID
    target_branch_id: uuid.UUID
    target_advisor_grant_id: uuid.UUID | None


async def _seed_owner_and_target_branch(
    session_factory,
    actors: TenantActors,
    *,
    with_target_advisor: bool = True,
) -> GovernanceActors:
    from app.models.agency_customer_lifecycle import (
        AgencyBranch,
        AgencyBranchRoleGrant,
    )
    from app.models.agency_transaction import AgencyMembership
    from app.models.user import User

    unique = uuid.uuid4().hex
    owner_id = uuid.uuid4()
    target_branch_id = uuid.uuid4()
    target_advisor_grant_id = (
        uuid.uuid4() if with_target_advisor else None
    )
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            User(
                id=owner_id,
                username=f"governance-owner-{unique}",
                email=f"governance-owner-{unique}@example.test",
                password_hash="integration-test-only",
            )
        )
        await session.flush()
        session.add_all(
            [
                AgencyMembership(
                    agency_id=actors.agency_id,
                    user_id=owner_id,
                    role="owner",
                    status="active",
                    joined_at=now,
                ),
                AgencyBranch(
                    id=target_branch_id,
                    agency_id=actors.agency_id,
                    branch_code=f"TARGET-{unique[:12]}",
                    name="Transfer Target Branch",
                    status="active",
                    revision=1,
                ),
            ]
        )
        await session.flush()
        if target_advisor_grant_id is not None:
            session.add(
                AgencyBranchRoleGrant(
                    id=target_advisor_grant_id,
                    agency_id=actors.agency_id,
                    branch_id=target_branch_id,
                    membership_id=actors.advisor_membership_id,
                    role="travel_advisor",
                    status="active",
                    revision=1,
                    granted_by_user_id=owner_id,
                    granted_at=now,
                )
            )
    return GovernanceActors(
        owner_id=owner_id,
        target_branch_id=target_branch_id,
        target_advisor_grant_id=target_advisor_grant_id,
    )


async def _seed_additional_active_branch(
    session_factory,
    *,
    agency_id: uuid.UUID,
) -> uuid.UUID:
    from app.models.agency_customer_lifecycle import AgencyBranch

    branch_id = uuid.uuid4()
    unique = uuid.uuid4().hex
    async with session_factory() as session, session.begin():
        session.add(
            AgencyBranch(
                id=branch_id,
                agency_id=agency_id,
                branch_code=f"EXTRA-{unique[:12]}",
                name="Additional Active Branch",
                status="active",
                revision=1,
            )
        )
    return branch_id


async def _customer_revision(
    session_factory,
    customer_id: uuid.UUID,
) -> int:
    from app.models.agency_customer_lifecycle import AgencyCustomer

    async with session_factory() as session:
        return int(
            (
                await session.execute(
                    select(AgencyCustomer.lifecycle_revision).where(
                        AgencyCustomer.id == customer_id
                    )
                )
            ).scalar_one()
        )


async def _create_submitted_order(
    session_factory,
    actors: TenantActors,
) -> tuple[uuid.UUID, object]:
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.schemas.agency_transaction import AgencyOrderCreateRequest

    unique = uuid.uuid4().hex
    quote = await _call(
        session_factory,
        lambda session: AgencyOrderReviewService(session).create_quote(
            actor_user_id=actors.advisor_id,
            data=_quote_request(actors),
            idempotency_key=f"transfer-history-quote-{unique}",
        ),
    )
    offered = await _call(
        session_factory,
        lambda session: AgencyOrderReviewService(session).issue_quote(
            actor_user_id=actors.advisor_id,
            quote_id=quote.id,
            expected_revision=quote.revision,
            idempotency_key=f"transfer-history-issue-{unique}",
        ),
    )
    accepted = await _call(
        session_factory,
        lambda session: AgencyOrderReviewService(session).accept_quote(
            actor_user_id=actors.customer_user_id,
            quote_id=quote.id,
            expected_revision=offered.revision,
            idempotency_key=f"transfer-history-accept-{unique}",
        ),
    )
    order = await _call(
        session_factory,
        lambda session: AgencyOrderReviewService(session).create_order(
            actor_user_id=actors.customer_user_id,
            data=AgencyOrderCreateRequest(
                agency_id=actors.agency_id,
                quote_id=quote.id,
                expected_quote_revision=accepted.revision,
            ),
            idempotency_key=f"transfer-history-order-{unique}",
        ),
    )
    submitted = await _call(
        session_factory,
        lambda session: AgencyOrderReviewService(session).submit_order(
            actor_user_id=actors.customer_user_id,
            order_id=order.id,
            expected_revision=order.revision,
            idempotency_key=f"transfer-history-submit-{unique}",
        ),
    )
    return quote.id, submitted


async def _create_rejected_order(
    session_factory,
    actors: TenantActors,
) -> tuple[uuid.UUID, uuid.UUID]:
    from app.agency.order_review_service import AgencyOrderReviewService

    quote_id, submitted = await _create_submitted_order(
        session_factory,
        actors,
    )
    await _call(
        session_factory,
        lambda session: AgencyOrderReviewService(
            session
        ).decide_order_review(
            actor_user_id=actors.approver_id,
            order_id=submitted.id,
            decision="reject",
            expected_revision=submitted.revision,
            reason="转店前终止未执行订单",
            idempotency_key=f"transfer-history-reject-{uuid.uuid4().hex}",
        ),
    )
    return quote_id, submitted.id


def test_upgrade_rejects_legacy_closed_branch_with_customer(
    postgres_schema: PostgresSandbox,
) -> None:
    command.upgrade(postgres_schema.alembic_config, "20260730_0007")
    agency_id = uuid.uuid4()
    branch_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    unique = uuid.uuid4().hex
    engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agency "
                    "(id, agency_code, name, status, created_at, updated_at) "
                    "VALUES (:id, :code, :name, 'active', now(), now())"
                ),
                {
                    "id": agency_id,
                    "code": f"LEGACY-{unique[:12]}",
                    "name": "Legacy Closed Branch Agency",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_branch "
                    "(id, agency_id, branch_code, name, status, revision, "
                    "deactivated_at, created_at, updated_at) "
                    "VALUES (:id, :agency_id, :code, :name, 'closed', 1, "
                    "now(), now(), now())"
                ),
                {
                    "id": branch_id,
                    "agency_id": agency_id,
                    "code": f"CLOSED-{unique[:12]}",
                    "name": "Legacy Closed Branch",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_customer "
                    "(id, agency_id, branch_id, customer_no, user_id, "
                    "binding_provenance, claimed_invitation_id, claimed_at, "
                    "source_type, source_reference, status, consent_status, "
                    "consent_version, consent_evidence_hash, "
                    "current_consent_record_id, consent_evidence_origin, "
                    "consent_updated_at, lifecycle_revision, invited_at, "
                    "activated_at, deactivated_at, created_at, updated_at) "
                    "VALUES (:id, :agency_id, :branch_id, :customer_no, "
                    "NULL, 'unbound', NULL, NULL, 'manual', NULL, "
                    "'prospect', 'unknown', NULL, NULL, NULL, 'none', "
                    "NULL, 1, now(), NULL, NULL, now(), now())"
                ),
                {
                    "id": customer_id,
                    "agency_id": agency_id,
                    "branch_id": branch_id,
                    "customer_no": f"LEGACY-{unique[:16]}",
                },
            )

        with pytest.raises(DBAPIError) as rejected:
            command.upgrade(postgres_schema.alembic_config, "head")
        assert (
            "cannot upgrade 0008: legacy closed agency_branch "
            "has current customers or open work"
        ) in str(rejected.value.orig)
        assert getattr(rejected.value.orig, "sqlstate", None) == "P0001"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_inactive_is_drain_state_and_close_stays_blocked(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import AgencyTransactionConflict
    from app.schemas.agency_customer_lifecycle import AgencyCustomerCreateRequest

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
            with_target_advisor=False,
        )
        deactivated = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
                expected_revision=1,
                reason="停止接收新业务并清理存量",
                idempotency_key=f"deactivate-{uuid.uuid4().hex}",
            ),
        )
        assert deactivated.status == "inactive"
        assert deactivated.revision == 2

        readiness = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).get_branch_closure_readiness(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
            ),
        )
        assert readiness.ready is False
        assert readiness.current_customer_count == 1
        assert readiness.active_assignment_count == 1
        assert readiness.active_role_grant_count == 2

        with pytest.raises(AgencyTransactionConflict) as new_business:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).create_customer(
                    actor_user_id=governance.owner_id,
                    data=AgencyCustomerCreateRequest(
                        agency_id=actors.agency_id,
                        branch_id=actors.branch_id,
                        source_type="manual",
                    ),
                    idempotency_key=f"inactive-customer-{uuid.uuid4().hex}",
                ),
            )
        assert new_business.value.code == "agency_branch_not_active"

        with pytest.raises(AgencyTransactionConflict) as close_blocked:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).close_branch(
                    actor_user_id=governance.owner_id,
                    branch_id=actors.branch_id,
                    expected_revision=2,
                    reason="错误地尝试跳过存量清理",
                    idempotency_key=f"blocked-close-{uuid.uuid4().hex}",
                ),
            )
        assert close_blocked.value.code == "branch_close_blocked"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_branch_rejects_pending_review_but_not_approval(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.order_review_service import AgencyOrderReviewService

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
            with_target_advisor=False,
        )
        _quote_id, rejected_order = await _create_submitted_order(
            session_factory,
            actors,
        )
        _quote_id, approval_order = await _create_submitted_order(
            session_factory,
            actors,
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
                expected_revision=1,
                reason="审核队列进入只拒绝清场",
                idempotency_key=f"review-drain-{uuid.uuid4().hex}",
            ),
        )

        rejected = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(
                session
            ).decide_order_review(
                actor_user_id=actors.approver_id,
                order_id=rejected_order.id,
                decision="reject",
                expected_revision=rejected_order.revision,
                reason="inactive 门店只允许终止存量审核",
                idempotency_key=f"review-drain-reject-{uuid.uuid4().hex}",
            ),
        )
        assert rejected.status == "rejected"

        with pytest.raises(DBAPIError) as approval:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_order "
                        "SET status = 'approved', revision = revision + 1, "
                        "updated_at = now() "
                        "WHERE id = :order_id"
                    ),
                    {"order_id": approval_order.id},
                )
                await connection.execute(
                    text(
                        "UPDATE agency_order_review "
                        "SET status = 'approved', "
                        "decision_order_revision = order_revision + 1, "
                        "decided_by_user_id = :approver_id, "
                        "decided_at = now(), updated_at = now() "
                        "WHERE order_id = :order_id AND status = 'pending'"
                    ),
                    {
                        "approver_id": actors.approver_id,
                        "order_id": approval_order.id,
                    },
                )
        assert "agency_order_review requires eligible branch approver" in str(
            approval.value.orig
        )
        assert getattr(approval.value.orig, "sqlstate", None) == "P0001"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_branch_ends_assignment_and_rejects_inactive_reassignment(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.models.agency_customer_lifecycle import (
        AgencyCustomerAdvisorAssignment,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
                expected_revision=1,
                reason="结束顾问分配前进入清场",
                idempotency_key=f"assignment-drain-{uuid.uuid4().hex}",
            ),
        )
        before_revision = await _customer_revision(
            session_factory,
            actors.customer_record_id,
        )
        ended = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).end_customer_advisor_assignment(
                actor_user_id=governance.owner_id,
                customer_id=actors.customer_record_id,
                expected_revision=before_revision,
                reason="inactive 门店结束存量顾问分配",
                idempotency_key=f"assignment-end-{uuid.uuid4().hex}",
            ),
        )
        assert ended.status == "ended"
        assert (
            await _customer_revision(
                session_factory,
                actors.customer_record_id,
            )
            == before_revision + 1
        )

        inactive_customer = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_customer(
                actor_user_id=governance.owner_id,
                customer_id=actors.customer_record_id,
                expected_revision=before_revision + 1,
                reason="转店前停用客户关系",
                idempotency_key=f"customer-drain-{uuid.uuid4().hex}",
            ),
        )
        assert inactive_customer.status == "inactive"

        with pytest.raises(DBAPIError) as invalid_assignment:
            async with session_factory() as session, session.begin():
                transfer = await CustomerLifecycleService(
                    session
                ).transfer_customer_branch(
                    actor_user_id=governance.owner_id,
                    customer_id=actors.customer_record_id,
                    expected_revision=inactive_customer.lifecycle_revision,
                    target_branch_id=governance.target_branch_id,
                    target_advisor_role_grant_id=None,
                    reason="inactive 客户仅迁移归属，不得恢复顾问",
                    idempotency_key=f"inactive-transfer-{uuid.uuid4().hex}",
                )
                session.add(
                    AgencyCustomerAdvisorAssignment(
                        agency_id=actors.agency_id,
                        branch_id=transfer.to_branch_id,
                        customer_id=actors.customer_record_id,
                        advisor_role_grant_id=(
                            governance.target_advisor_grant_id
                        ),
                        advisor_membership_id=actors.advisor_membership_id,
                        status="active",
                        revision=1,
                        assigned_by_user_id=governance.owner_id,
                        assignment_reason="恶意绕过 inactive 客户限制",
                        assigned_at=datetime.now(UTC),
                    )
                )
        assert "active advisor assignment requires active customer" in str(
            invalid_assignment.value.orig
        )
        assert (
            getattr(invalid_assignment.value.orig, "sqlstate", None)
            == "P0001"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_branch_completes_cancellation_closeout(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        operators = await _seed_cancellation_operators(
            session_factory,
            actors,
        )
        owner_id = await _seed_agency_owner(session_factory, actors)
        order = await _create_order(
            session_factory,
            actors,
            approved=True,
        )
        await _add_exposure(
            session_factory,
            order,
            payment=True,
            fulfillment=True,
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=owner_id,
                branch_id=actors.branch_id,
                expected_revision=1,
                reason="保留取消清场能力并停止新交易",
                idempotency_key=f"cancel-drain-{uuid.uuid4().hex}",
            ),
        )

        case = await _request_case(session_factory, actors, order)
        assert (case.supplier_cancel_required, case.refund_required) == (
            True,
            True,
        )
        case = await _review_case(
            session_factory,
            actors,
            case,
            refund_amount=order.total_amount,
        )
        assert case.status == "action_pending"
        supplier_result = await _manual_result(
            session_factory,
            actor_user_id=operators.booking_operator_id,
            case=case,
            action_type="supplier_cancel",
            outcome="succeeded",
            amount=None,
        )
        case = await _get_case(session_factory, case.id)
        refund_result = await _manual_result(
            session_factory,
            actor_user_id=operators.finance_id,
            case=case,
            action_type="refund",
            outcome="succeeded",
            amount=order.total_amount,
        )
        case = await _get_case(session_factory, case.id)
        assert case.status == "reconciliation_pending"

        await _reconcile(
            session_factory,
            auditor_id=operators.auditor_id,
            case=case,
            record_id=supplier_result.id,
            outcome="matched",
        )
        case = await _get_case(session_factory, case.id)
        await _reconcile(
            session_factory,
            auditor_id=operators.auditor_id,
            case=case,
            record_id=refund_result.id,
            outcome="matched",
            observed_amount=Decimal(order.total_amount),
            observed_currency=order.currency,
        )
        completed_case = await _get_case(session_factory, case.id)
        cancelled_order = await _get_order(session_factory, order.id)
        assert completed_case.status == "completed"
        assert cancelled_order.status == "cancelled"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_transfer_preserves_history_and_moves_assignment(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.models.agency_customer_identity import (
        AgencyCustomerConsentRecord,
    )
    from app.models.agency_customer_lifecycle import (
        AgencyCustomer,
        AgencyCustomerAdvisorAssignment,
        AgencyCustomerBranchTransfer,
        AgencyCustomerEvent,
    )
    from app.models.agency_transaction import (
        AgencyOrder,
        AgencyOrderEvent,
        AgencyQuote,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
        )
        quote_id, order_id = await _create_rejected_order(
            session_factory,
            actors,
        )
        before_revision = await _customer_revision(
            session_factory,
            actors.customer_record_id,
        )

        transfer = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).transfer_customer_branch(
                actor_user_id=governance.owner_id,
                customer_id=actors.customer_record_id,
                expected_revision=before_revision,
                target_branch_id=governance.target_branch_id,
                target_advisor_role_grant_id=(
                    governance.target_advisor_grant_id
                ),
                reason="由目标门店继续服务",
                idempotency_key=f"customer-transfer-{uuid.uuid4().hex}",
            ),
        )
        assert transfer.from_branch_id == actors.branch_id
        assert transfer.to_branch_id == governance.target_branch_id
        assert transfer.customer_revision == before_revision + 1

        async with session_factory() as session:
            customer = (
                await session.execute(
                    select(AgencyCustomer).where(
                        AgencyCustomer.id == actors.customer_record_id
                    )
                )
            ).scalar_one()
            assignments = (
                await session.execute(
                    select(AgencyCustomerAdvisorAssignment)
                    .where(
                        AgencyCustomerAdvisorAssignment.customer_id
                        == actors.customer_record_id
                    )
                    .order_by(AgencyCustomerAdvisorAssignment.created_at)
                )
            ).scalars().all()
            consent_branches = (
                await session.execute(
                    select(AgencyCustomerConsentRecord.branch_id).where(
                        AgencyCustomerConsentRecord.customer_id
                        == actors.customer_record_id
                    )
                )
            ).scalars().all()
            quote_branch = (
                await session.execute(
                    select(AgencyQuote.branch_id).where(
                        AgencyQuote.id == quote_id
                    )
                )
            ).scalar_one()
            order_branch = (
                await session.execute(
                    select(AgencyOrder.branch_id).where(
                        AgencyOrder.id == order_id
                    )
                )
            ).scalar_one()
            order_event_branches = (
                await session.execute(
                    select(AgencyOrderEvent.branch_id).where(
                        AgencyOrderEvent.order_id == order_id
                    )
                )
            ).scalars().all()
            transfer_event = (
                await session.execute(
                    select(AgencyCustomerEvent)
                    .where(
                        AgencyCustomerEvent.customer_id
                        == actors.customer_record_id
                    )
                    .where(
                        AgencyCustomerEvent.event_type
                        == "customer_branch_transferred"
                    )
                )
            ).scalar_one()
            stored_transfer = (
                await session.execute(
                    select(AgencyCustomerBranchTransfer).where(
                        AgencyCustomerBranchTransfer.id == transfer.id
                    )
                )
            ).scalar_one()

        assert customer.branch_id == governance.target_branch_id
        assert customer.lifecycle_revision == before_revision + 1
        assert {
            assignment.branch_id: assignment.status
            for assignment in assignments
        } == {
            actors.branch_id: "ended",
            governance.target_branch_id: "active",
        }
        assert set(consent_branches) == {actors.branch_id}
        assert quote_branch == actors.branch_id
        assert order_branch == actors.branch_id
        assert set(order_event_branches) == {actors.branch_id}
        assert transfer_event.branch_id == governance.target_branch_id
        assert stored_transfer.customer_revision == customer.lifecycle_revision
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_transfer_rejects_blockers_target_and_stale_revision(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import (
        AgencyTransactionConflict,
        AgencyTransactionValidationError,
    )
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.models.user import User
    from app.schemas.agency_customer_lifecycle import AgencyCustomerCreateRequest

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
            with_target_advisor=False,
        )
        revision = await _customer_revision(
            session_factory,
            actors.customer_record_id,
        )

        with pytest.raises(AgencyTransactionConflict) as stale:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).transfer_customer_branch(
                    actor_user_id=governance.owner_id,
                    customer_id=actors.customer_record_id,
                    expected_revision=revision + 1,
                    target_branch_id=governance.target_branch_id,
                    target_advisor_role_grant_id=None,
                    reason="陈旧 revision 不得转店",
                    idempotency_key=f"stale-transfer-{uuid.uuid4().hex}",
                ),
            )
        assert stale.value.code == "transaction_revision_conflict"

        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=governance.owner_id,
                branch_id=governance.target_branch_id,
                expected_revision=1,
                reason="目标门店停止接收新业务",
                idempotency_key=f"inactive-target-{uuid.uuid4().hex}",
            ),
        )
        with pytest.raises(AgencyTransactionValidationError) as inactive:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).transfer_customer_branch(
                    actor_user_id=governance.owner_id,
                    customer_id=actors.customer_record_id,
                    expected_revision=revision,
                    target_branch_id=governance.target_branch_id,
                    target_advisor_role_grant_id=None,
                    reason="不可转入 inactive 门店",
                    idempotency_key=f"inactive-transfer-{uuid.uuid4().hex}",
                ),
            )
        assert inactive.value.code == "customer_branch_transfer_target_invalid"

        active_target_id = await _seed_additional_active_branch(
            session_factory,
            agency_id=actors.agency_id,
        )
        await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).create_quote(
                actor_user_id=actors.advisor_id,
                data=_quote_request(actors),
                idempotency_key=f"open-transfer-quote-{uuid.uuid4().hex}",
            ),
        )
        with pytest.raises(AgencyTransactionConflict) as open_work:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).transfer_customer_branch(
                    actor_user_id=governance.owner_id,
                    customer_id=actors.customer_record_id,
                    expected_revision=revision,
                    target_branch_id=active_target_id,
                    target_advisor_role_grant_id=None,
                    reason="开放报价不得跟随当前归属漂移",
                    idempotency_key=f"open-work-transfer-{uuid.uuid4().hex}",
                ),
            )
        assert open_work.value.code == "customer_branch_transfer_open_work"

        invitee_id = uuid.uuid4()
        unique = uuid.uuid4().hex
        async with session_factory() as session, session.begin():
            session.add(
                User(
                    id=invitee_id,
                    username=f"pending-invitee-{unique}",
                    email=f"pending-transfer-invitee-{unique}@example.test",
                    password_hash="integration-test-only",
                )
            )
        prospect = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).create_customer(
                actor_user_id=governance.owner_id,
                data=AgencyCustomerCreateRequest(
                    agency_id=actors.agency_id,
                    branch_id=actors.branch_id,
                    source_type="manual",
                ),
                idempotency_key=f"pending-prospect-{uuid.uuid4().hex}",
            ),
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=governance.owner_id,
                customer_id=prospect.id,
                expected_revision=prospect.lifecycle_revision,
                target_user_id=invitee_id,
                idempotency_key=f"pending-invitation-{uuid.uuid4().hex}",
            ),
        )
        with pytest.raises(AgencyTransactionConflict) as pending_invitation:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).transfer_customer_branch(
                    actor_user_id=governance.owner_id,
                    customer_id=prospect.id,
                    expected_revision=prospect.lifecycle_revision,
                    target_branch_id=active_target_id,
                    target_advisor_role_grant_id=None,
                    reason="邀请未处理时不得转店",
                    idempotency_key=f"pending-transfer-{uuid.uuid4().hex}",
                ),
            )
        assert (
            pending_invitation.value.code
            == "customer_branch_transfer_pending_invitation"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_drained_inactive_branch_closes_and_closed_is_terminal(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import AgencyTransactionConflict

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
        )
        await _create_rejected_order(session_factory, actors)
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
                expected_revision=1,
                reason="门店进入存量清理期",
                idempotency_key=f"drain-deactivate-{uuid.uuid4().hex}",
            ),
        )
        customer_revision = await _customer_revision(
            session_factory,
            actors.customer_record_id,
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).transfer_customer_branch(
                actor_user_id=governance.owner_id,
                customer_id=actors.customer_record_id,
                expected_revision=customer_revision,
                target_branch_id=governance.target_branch_id,
                target_advisor_role_grant_id=(
                    governance.target_advisor_grant_id
                ),
                reason="存量客户转入继续营业门店",
                idempotency_key=f"drain-transfer-{uuid.uuid4().hex}",
            ),
        )
        for grant_id, suffix in (
            (actors.advisor_grant_id, "advisor"),
            (actors.approver_grant_id, "approver"),
        ):
            await _call(
                session_factory,
                lambda session, grant_id=grant_id, suffix=suffix: (
                    CustomerLifecycleService(
                        session
                    ).revoke_branch_role_grant(
                        actor_user_id=governance.owner_id,
                        branch_id=actors.branch_id,
                        grant_id=grant_id,
                        expected_revision=1,
                        reason="关店前撤销门店岗位授权",
                        idempotency_key=(
                            f"drain-revoke-{suffix}-{uuid.uuid4().hex}"
                        ),
                    )
                ),
            )
        readiness = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).get_branch_closure_readiness(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
            ),
        )
        assert readiness.ready is True
        assert (
            readiness.current_customer_count
            == readiness.active_assignment_count
            == readiness.active_role_grant_count
            == readiness.pending_review_count
            == readiness.open_quote_count
            == readiness.open_order_count
            == readiness.open_cancellation_case_count
            == 0
        )
        closed = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).close_branch(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
                expected_revision=2,
                reason="确认无客户、授权或开放业务",
                idempotency_key=f"drain-close-{uuid.uuid4().hex}",
            ),
        )
        assert closed.status == "closed"
        assert closed.revision == 3
        assert closed.closed_at is not None

        with pytest.raises(AgencyTransactionConflict) as repeated:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).deactivate_branch(
                    actor_user_id=governance.owner_id,
                    branch_id=actors.branch_id,
                    expected_revision=3,
                    reason="closed 门店不可恢复",
                    idempotency_key=f"closed-deactivate-{uuid.uuid4().hex}",
                ),
            )
        assert repeated.value.code == "branch_state_conflict"

        with pytest.raises(DBAPIError) as direct_mutation:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_branch "
                        "SET name = 'Forbidden Reopen', "
                        "revision = revision + 1 "
                        "WHERE id = :branch_id"
                    ),
                    {"branch_id": actors.branch_id},
                )
        assert "closed agency_branch is immutable" in str(
            direct_mutation.value.orig
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_guards_reject_unpaired_transfer_and_branch_transitions(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        governance = await _seed_owner_and_target_branch(
            session_factory,
            actors,
            with_target_advisor=False,
        )
        revision = await _customer_revision(
            session_factory,
            actors.customer_record_id,
        )

        with pytest.raises(DBAPIError) as unpaired_customer:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer "
                        "SET branch_id = :target_branch_id, "
                        "lifecycle_revision = lifecycle_revision + 1, "
                        "updated_at = now() "
                        "WHERE id = :customer_id"
                    ),
                    {
                        "target_branch_id": governance.target_branch_id,
                        "customer_id": actors.customer_record_id,
                    },
                )
        assert "branch change requires matching transfer" in str(
            unpaired_customer.value.orig
        )

        with pytest.raises(DBAPIError) as orphan_transfer:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO agency_customer_branch_transfer "
                        "(id, agency_id, customer_id, from_branch_id, "
                        "to_branch_id, customer_revision, "
                        "transferred_by_user_id, reason, transferred_at, "
                        "created_at) VALUES "
                        "(:id, :agency_id, :customer_id, :from_branch_id, "
                        ":to_branch_id, :customer_revision, :actor_id, "
                        ":reason, now(), now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "agency_id": actors.agency_id,
                        "customer_id": actors.customer_record_id,
                        "from_branch_id": actors.branch_id,
                        "to_branch_id": governance.target_branch_id,
                        "customer_revision": revision + 1,
                        "actor_id": governance.owner_id,
                        "reason": "孤立转店事实必须被拒绝",
                    },
                )
        assert "must match final customer state" in str(
            orphan_transfer.value.orig
        )

        with pytest.raises(DBAPIError) as missing_branch_event:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_branch "
                        "SET status = 'inactive', "
                        "revision = revision + 1, "
                        "deactivated_at = now(), "
                        "updated_at = now() "
                        "WHERE id = :branch_id"
                    ),
                    {"branch_id": actors.branch_id},
                )
        assert "transition requires audit event" in str(
            missing_branch_event.value.orig
        )

        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_branch(
                actor_user_id=governance.owner_id,
                branch_id=actors.branch_id,
                expected_revision=1,
                reason="为直接 SQL 关店阻断测试进入清理期",
                idempotency_key=f"guard-deactivate-{uuid.uuid4().hex}",
            ),
        )
        with pytest.raises(DBAPIError) as close_with_blockers:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO agency_branch_lifecycle_event "
                        "(id, agency_id, branch_id, event_sequence, "
                        "branch_revision, event_type, actor_user_id, "
                        "reason, created_at) VALUES "
                        "(:id, :agency_id, :branch_id, 2, 3, 'closed', "
                        ":actor_id, :reason, now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "agency_id": actors.agency_id,
                        "branch_id": actors.branch_id,
                        "actor_id": governance.owner_id,
                        "reason": "即使有事件也不能绕过关店阻断项",
                    },
                )
                await connection.execute(
                    text(
                        "UPDATE agency_branch "
                        "SET status = 'closed', "
                        "revision = revision + 1, "
                        "closed_at = now(), "
                        "updated_at = now() "
                        "WHERE id = :branch_id"
                    ),
                    {"branch_id": actors.branch_id},
                )
        assert "closure requires zero current customers and open work" in str(
            close_with_blockers.value.orig
        )
    finally:
        await engine.dispose()
