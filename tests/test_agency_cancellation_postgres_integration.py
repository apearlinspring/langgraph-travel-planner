"""PostgreSQL integration checks for the agency cancellation workflow.

The suite is opt-in, reuses the isolated-schema fixture, and never reads the
repository ``.env``. Run it only against a dedicated test/CI database:

    uv run python -m pytest --run-integration -q \
      tests/test_agency_cancellation_postgres_integration.py
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

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
class CancellationOperators:
    booking_operator_id: uuid.UUID
    finance_id: uuid.UUID
    auditor_id: uuid.UUID
    branch_manager_id: uuid.UUID


@dataclass(frozen=True)
class ApprovalControlActors:
    approver_id: uuid.UUID
    approver_membership_id: uuid.UUID
    approver_grant_id: uuid.UUID


async def _call(
    session_factory: async_sessionmaker[AsyncSession],
    operation: Callable[[AsyncSession], Awaitable[Any]],
) -> Any:
    async with session_factory() as session, session.begin():
        return await operation(session)


async def _seed_cancellation_operators(
    session_factory: async_sessionmaker[AsyncSession],
    actors: TenantActors,
) -> CancellationOperators:
    from app.models.agency_customer_lifecycle import AgencyBranchRoleGrant
    from app.models.agency_transaction import AgencyMembership
    from app.models.user import User

    unique = uuid.uuid4().hex
    now = datetime.now(UTC)
    roles = {
        "booking_operator": uuid.uuid4(),
        "finance": uuid.uuid4(),
        "auditor": uuid.uuid4(),
        "branch_manager": uuid.uuid4(),
    }
    memberships = {role: uuid.uuid4() for role in roles}
    async with session_factory() as session, session.begin():
        for role, user_id in roles.items():
            session.add(
                User(
                    id=user_id,
                    username=f"{role}-{unique}",
                    email=f"{role}-{unique}@example.test",
                    password_hash="integration-test-only",
                )
            )
        await session.flush()
        for role, user_id in roles.items():
            session.add(
                AgencyMembership(
                    id=memberships[role],
                    agency_id=actors.agency_id,
                    user_id=user_id,
                    role=role,
                    status="active",
                    joined_at=now,
                )
            )
        await session.flush()
        for role, membership_id in memberships.items():
            session.add(
                AgencyBranchRoleGrant(
                    agency_id=actors.agency_id,
                    branch_id=actors.branch_id,
                    membership_id=membership_id,
                    role=role,
                    status="active",
                    revision=1,
                    granted_at=now,
                )
            )

    return CancellationOperators(
        booking_operator_id=roles["booking_operator"],
        finance_id=roles["finance"],
        auditor_id=roles["auditor"],
        branch_manager_id=roles["branch_manager"],
    )


async def _seed_agency_owner(
    session_factory: async_sessionmaker[AsyncSession],
    actors: TenantActors,
) -> uuid.UUID:
    from app.models.agency_transaction import AgencyMembership
    from app.models.user import User

    unique = uuid.uuid4().hex
    now = datetime.now(UTC)
    owner_id = uuid.uuid4()
    owner_membership_id = uuid.uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            User(
                id=owner_id,
                username=f"owner-{unique}",
                email=f"owner-{unique}@example.test",
                password_hash="integration-test-only",
            )
        )
        await session.flush()
        session.add(
            AgencyMembership(
                id=owner_membership_id,
                agency_id=actors.agency_id,
                user_id=owner_id,
                role="owner",
                status="active",
                joined_at=now,
            )
        )
    return owner_id


async def _seed_replacement_approver(
    session_factory: async_sessionmaker[AsyncSession],
    actors: TenantActors,
    *,
    granted_by_user_id: uuid.UUID,
) -> ApprovalControlActors:
    from app.models.agency_customer_lifecycle import AgencyBranchRoleGrant
    from app.models.agency_transaction import AgencyMembership
    from app.models.user import User

    unique = uuid.uuid4().hex
    now = datetime.now(UTC)
    approver_id = uuid.uuid4()
    approver_membership_id = uuid.uuid4()
    approver_grant_id = uuid.uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            User(
                id=approver_id,
                username=f"second-approver-{unique}",
                email=f"second-approver-{unique}@example.test",
                password_hash="integration-test-only",
            )
        )
        await session.flush()
        session.add(
            AgencyMembership(
                id=approver_membership_id,
                agency_id=actors.agency_id,
                user_id=approver_id,
                role="approver",
                status="active",
                joined_at=now,
            )
        )
        await session.flush()
        session.add(
            AgencyBranchRoleGrant(
                id=approver_grant_id,
                agency_id=actors.agency_id,
                branch_id=actors.branch_id,
                membership_id=approver_membership_id,
                role="approver",
                status="active",
                revision=1,
                granted_by_user_id=granted_by_user_id,
                granted_at=now,
            )
        )

    return ApprovalControlActors(
        approver_id=approver_id,
        approver_membership_id=approver_membership_id,
        approver_grant_id=approver_grant_id,
    )


async def _create_order(
    session_factory: async_sessionmaker[AsyncSession],
    actors: TenantActors,
    *,
    approved: bool,
):
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.schemas.agency_transaction import AgencyOrderCreateRequest

    unique = uuid.uuid4().hex
    async with session_factory() as session, session.begin():
        service = AgencyOrderReviewService(session)
        quote = await service.create_quote(
            actor_user_id=actors.advisor_id,
            data=_quote_request(actors),
            idempotency_key=f"cancel-quote-{unique}",
        )
        quote = await service.issue_quote(
            actor_user_id=actors.advisor_id,
            quote_id=quote.id,
            expected_revision=quote.revision,
            idempotency_key=f"cancel-issue-{unique}",
        )

    async with session_factory() as session, session.begin():
        service = AgencyOrderReviewService(session)
        quote = await service.accept_quote(
            actor_user_id=actors.customer_user_id,
            quote_id=quote.id,
            expected_revision=quote.revision,
            idempotency_key=f"cancel-accept-{unique}",
        )
        order = await service.create_order(
            actor_user_id=actors.customer_user_id,
            data=AgencyOrderCreateRequest(
                agency_id=actors.agency_id,
                quote_id=quote.id,
                expected_quote_revision=quote.revision,
            ),
            idempotency_key=f"cancel-order-{unique}",
        )

    if not approved:
        return order

    async with session_factory() as session, session.begin():
        order = await AgencyOrderReviewService(session).submit_order(
            actor_user_id=actors.customer_user_id,
            order_id=order.id,
            expected_revision=order.revision,
            idempotency_key=f"cancel-submit-{unique}",
        )
    async with session_factory() as session, session.begin():
        await AgencyOrderReviewService(session).decide_order_review(
            actor_user_id=actors.approver_id,
            order_id=order.id,
            decision="approve",
            expected_revision=order.revision,
            reason=None,
            idempotency_key=f"cancel-approve-order-{unique}",
        )
    return await _get_order(session_factory, order.id)


async def _add_exposure(
    session_factory: async_sessionmaker[AsyncSession],
    order,
    *,
    payment: bool,
    fulfillment: bool,
) -> list[object]:
    from app.models.agency_transaction import (
        FulfillmentRecord,
        PaymentAttempt,
    )

    unique = uuid.uuid4().hex
    rows: list[object] = []
    if payment:
        rows.append(
            PaymentAttempt(
                agency_id=order.agency_id,
                order_id=order.id,
                attempt_no=1,
                idempotency_key=f"payment-{unique}",
                provider_code="integration-pay",
                status="succeeded",
                amount=order.total_amount,
                currency=order.currency,
                external_action_enabled=False,
                provider_reference=f"PAY-{unique}",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
    if fulfillment:
        rows.append(
            FulfillmentRecord(
                agency_id=order.agency_id,
                order_id=order.id,
                product_id=None,
                line_item_key="package-1",
                idempotency_key=f"fulfillment-{unique}",
                provider_code="integration-supplier",
                status="confirmed",
                external_action_enabled=False,
                provider_reference=f"BOOK-{unique}",
                confirmed_at=datetime.now(UTC),
            )
        )
    async with session_factory() as session, session.begin():
        session.add_all(rows)
    return rows


async def _request_case(
    session_factory: async_sessionmaker[AsyncSession],
    actors: TenantActors,
    order,
    *,
    requester_id: uuid.UUID | None = None,
):
    from app.agency.cancellation_service import CancellationService

    return await _call(
        session_factory,
        lambda session: CancellationService(session).request_cancellation(
            actor_user_id=requester_id or actors.customer_user_id,
            order_id=order.id,
            expected_revision=order.revision,
            reason_code="customer_request",
            reason_detail="integration cancellation request",
            idempotency_key=f"cancel-request-{uuid.uuid4().hex}",
        ),
    )


async def _review_case(
    session_factory: async_sessionmaker[AsyncSession],
    actors: TenantActors,
    case,
    *,
    refund_amount: Decimal | None,
):
    from app.agency.cancellation_service import CancellationService

    return await _call(
        session_factory,
        lambda session: CancellationService(session).review_cancellation(
            actor_user_id=actors.approver_id,
            case_id=case.id,
            decision="approve",
            expected_revision=case.revision,
            approved_refund_amount=refund_amount,
            approved_refund_currency=(
                case.currency if refund_amount is not None else None
            ),
            reason=None,
            idempotency_key=f"cancel-review-{uuid.uuid4().hex}",
        ),
    )


async def _get_case(
    session_factory: async_sessionmaker[AsyncSession],
    case_id: uuid.UUID,
):
    from app.models.agency_cancellation import AgencyOrderCancellationCase

    async with session_factory() as session:
        return await session.get(AgencyOrderCancellationCase, case_id)


async def _get_order(
    session_factory: async_sessionmaker[AsyncSession],
    order_id: uuid.UUID,
):
    from app.models.agency_transaction import AgencyOrder

    async with session_factory() as session:
        return await session.get(AgencyOrder, order_id)


async def _manual_result(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    actor_user_id: uuid.UUID,
    case,
    action_type: str,
    outcome: str,
    amount: Decimal | None,
):
    from app.agency.cancellation_service import CancellationService

    return await _call(
        session_factory,
        lambda session: CancellationService(session).record_manual_result(
            actor_user_id=actor_user_id,
            case_id=case.id,
            expected_revision=case.revision,
            action_type=action_type,
            outcome=outcome,
            external_reference_sha256="a" * 64,
            evidence_sha256="b" * 64,
            amount=amount,
            currency=case.currency if amount is not None else None,
            occurred_at=datetime.now(UTC),
            idempotency_key=f"cancel-result-{uuid.uuid4().hex}",
        ),
    )


async def _reconcile(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    auditor_id: uuid.UUID,
    case,
    record_id: uuid.UUID,
    outcome: str,
    observed_amount: Decimal | None = None,
    observed_currency: str | None = None,
):
    from app.agency.cancellation_service import CancellationService

    return await _call(
        session_factory,
        lambda session: CancellationService(session).reconcile_manual_result(
            actor_user_id=auditor_id,
            record_id=record_id,
            expected_revision=case.revision,
            outcome=outcome,
            observed_amount=observed_amount,
            observed_currency=observed_currency,
            evidence_sha256="c" * 64,
            idempotency_key=f"cancel-reconcile-{uuid.uuid4().hex}",
        ),
    )


async def _resume(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    manager_id: uuid.UUID,
    case,
):
    from app.agency.cancellation_service import CancellationService

    return await _call(
        session_factory,
        lambda session: CancellationService(session).resume_cancellation(
            actor_user_id=manager_id,
            case_id=case.id,
            expected_revision=case.revision,
            reason="verified retry",
            idempotency_key=f"cancel-resume-{uuid.uuid4().hex}",
        ),
    )


async def _assert_sql_rejected(
    engine,
    statement: str,
    params: dict[str, object],
    *,
    contains: str | None = None,
) -> str:
    with pytest.raises(DBAPIError) as captured:
        async with engine.begin() as connection:
            await connection.execute(text(statement), params)
    message = str(captured.value.orig)
    if contains is not None:
        assert contains in message
    return message


async def _assert_direct_case_insert_rejected(
    engine,
    *,
    order,
    requester_id: uuid.UUID,
    supplier_required: bool,
    refund_required: bool,
    contains: str,
) -> None:
    now = datetime.now(UTC)
    await _assert_sql_rejected(
        engine,
        "INSERT INTO agency_order_cancellation_case "
        "(id, agency_id, branch_id, order_id, customer_id, revision, "
        "status, order_revision_at_request, reason_code, reason_detail, "
        "supplier_cancel_required, refund_required, "
        "approved_refund_amount, currency, requested_by_user_id, "
        "requested_at, review_decision, reviewed_by_user_id, reviewed_at, "
        "review_note, external_action_triggered, completed_at, "
        "created_at, updated_at) "
        "VALUES (:case_id, :agency_id, :branch_id, :order_id, "
        ":customer_id, 1, 'approval_pending', :order_revision, "
        "'customer_request', NULL, :supplier_required, :refund_required, "
        "NULL, :currency, :requester_id, :now, NULL, NULL, NULL, NULL, "
        "false, NULL, :now, :now)",
        {
            "case_id": uuid.uuid4(),
            "agency_id": order.agency_id,
            "branch_id": order.branch_id,
            "order_id": order.id,
            "customer_id": order.customer_id,
            "order_revision": order.revision,
            "supplier_required": supplier_required,
            "refund_required": refund_required,
            "currency": order.currency,
            "requester_id": requester_id,
            "now": now,
        },
        contains=contains,
    )


@pytest.mark.asyncio
async def test_0007_upgrade_empty_downgrade_roundtrip_and_data_guard(
    postgres_schema: PostgresSandbox,
) -> None:
    command.upgrade(postgres_schema.alembic_config, "head")
    sync_engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
    )
    try:
        inspector = inspect(sync_engine)
        assert {
            "agency_order_cancellation_case",
            "agency_order_cancellation_event",
            "agency_order_compensation_record",
            "agency_order_reconciliation_record",
        }.issubset(inspector.get_table_names())
        assert "cancellation_requested_at" in {
            column["name"] for column in inspector.get_columns("agency_order")
        }
    finally:
        sync_engine.dispose()

    command.downgrade(postgres_schema.alembic_config, "20260730_0006")
    sync_engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
    )
    try:
        inspector = inspect(sync_engine)
        assert "agency_order_cancellation_case" not in (
            inspector.get_table_names()
        )
        assert "cancellation_requested_at" not in {
            column["name"] for column in inspector.get_columns("agency_order")
        }
    finally:
        sync_engine.dispose()

    command.upgrade(postgres_schema.alembic_config, "head")
    engine, session_factory = _session_factory(postgres_schema)
    try:
        actors = await _seed_tenant(session_factory)
        order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
        await _request_case(session_factory, actors, order)
    finally:
        await engine.dispose()

    with pytest.raises(DBAPIError) as guarded:
        command.downgrade(
            postgres_schema.alembic_config,
            "20260730_0006",
        )
    assert (
        "cannot downgrade 0007 after cancellation workflow data exists"
        in str(guarded.value.orig)
    )
    sync_engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
    )
    try:
        assert "agency_order_cancellation_case" in (
            inspect(sync_engine).get_table_names()
        )
    finally:
        sync_engine.dispose()


@pytest.mark.asyncio
async def test_0007_upgrades_legacy_pending_order_before_replacing_guard(
    postgres_schema: PostgresSandbox,
) -> None:
    command.upgrade(postgres_schema.alembic_config, "head")
    engine, session_factory = _session_factory(postgres_schema)
    try:
        actors = await _seed_tenant(session_factory)
        order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
    finally:
        await engine.dispose()

    command.downgrade(postgres_schema.alembic_config, "20260730_0006")
    legacy_requested_at = datetime.now(UTC)
    sync_engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
    )
    try:
        with sync_engine.begin() as connection:
            legacy_revision = connection.execute(
                text(
                    "UPDATE agency_order "
                    "SET status = 'cancellation_pending', "
                    "revision = revision + 1, "
                    "cancelled_at = :requested_at, "
                    "updated_at = :requested_at "
                    "WHERE id = :order_id "
                    "RETURNING revision"
                ),
                {
                    "order_id": order.id,
                    "requested_at": legacy_requested_at,
                },
            ).scalar_one()
    finally:
        sync_engine.dispose()

    command.upgrade(postgres_schema.alembic_config, "head")
    sync_engine = create_engine(
        postgres_schema.sync_url,
        poolclass=NullPool,
    )
    try:
        with sync_engine.connect() as connection:
            migrated = connection.execute(
                text(
                    "SELECT status, revision, cancellation_requested_at, "
                    "cancelled_at FROM agency_order WHERE id = :order_id"
                ),
                {"order_id": order.id},
            ).mappings().one()
        assert migrated["status"] == "cancellation_pending"
        assert migrated["revision"] == legacy_revision
        assert migrated["cancellation_requested_at"] == legacy_requested_at
        assert migrated["cancelled_at"] is None
    finally:
        sync_engine.dispose()


@pytest.mark.parametrize("approved", [False, True], ids=["draft", "approved"])
@pytest.mark.asyncio
async def test_clean_order_completes_case_and_sets_true_cancellation_time(
    migrated_postgres: PostgresSandbox,
    approved: bool,
) -> None:
    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        order = await _create_order(
            session_factory,
            actors,
            approved=approved,
        )
        starting_revision = order.revision
        case = await _request_case(session_factory, actors, order)
        assert case.status == "approval_pending"
        assert case.supplier_cancel_required is False
        assert case.refund_required is False
        assert (await _get_order(session_factory, order.id)).status == (
            "approved" if approved else "draft"
        )
        await _assert_sql_rejected(
            engine,
            "INSERT INTO payment_attempt "
            "(id, agency_id, order_id, attempt_no, idempotency_key, "
            "status, amount, currency, external_action_enabled, "
            "created_at, updated_at) "
            "VALUES (:id, :agency_id, :order_id, 1, :key, 'succeeded', "
            ":amount, :currency, false, :now, :now)",
            {
                "id": uuid.uuid4(),
                "agency_id": order.agency_id,
                "order_id": order.id,
                "key": f"pending-case-payment-{uuid.uuid4().hex}",
                "amount": order.total_amount,
                "currency": order.currency,
                "now": datetime.now(UTC),
            },
            contains="payment_attempt is frozen",
        )

        case = await _review_case(
            session_factory,
            actors,
            case,
            refund_amount=None,
        )
        stored_order = await _get_order(session_factory, order.id)
        assert case.status == "completed"
        assert case.completed_at is not None
        assert stored_order.status == "cancelled"
        assert stored_order.revision == starting_revision + 1
        assert (
            stored_order.cancellation_requested_at
            == stored_order.cancelled_at
            == case.completed_at
        )
        assert case.external_action_triggered is False
        assert stored_order.external_action_enabled is False
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("payment", "fulfillment", "expected"),
    [
        (True, False, (False, True)),
        (False, True, (True, False)),
    ],
    ids=["payment-only", "fulfillment-only"],
)
@pytest.mark.asyncio
async def test_case_required_flags_match_each_individual_ledger_exposure(
    migrated_postgres: PostgresSandbox,
    payment: bool,
    fulfillment: bool,
    expected: tuple[bool, bool],
) -> None:
    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        order = await _create_order(
            session_factory,
            actors,
            approved=True,
        )
        await _add_exposure(
            session_factory,
            order,
            payment=payment,
            fulfillment=fulfillment,
        )
        await _assert_direct_case_insert_rejected(
            engine,
            order=order,
            requester_id=actors.customer_user_id,
            supplier_required=False,
            refund_required=False,
            contains=(
                "new cancellation case required actions must match locked "
                "ledgers"
            ),
        )

        case = await _request_case(session_factory, actors, order)

        assert (
            case.supplier_cancel_required,
            case.refund_required,
        ) == expected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pending_case_preserves_eligible_approver_and_review_invariants(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.cancellation_service import CancellationService
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import AgencyTransactionConflict
    from app.agency.order_review_service import AgencyOrderReviewService

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
        owner_id = await _seed_agency_owner(session_factory, actors)
        now = datetime.now(UTC)
        await _assert_direct_case_insert_rejected(
            engine,
            order=order,
            requester_id=actors.approver_id,
            supplier_required=False,
            refund_required=False,
            contains="new cancellation case requires eligible branch approver",
        )

        case = await _request_case(session_factory, actors, order)
        with pytest.raises(AgencyTransactionConflict) as revoke_error:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).revoke_branch_role_grant(
                    actor_user_id=owner_id,
                    branch_id=actors.branch_id,
                    grant_id=actors.approver_grant_id,
                    expected_revision=1,
                    reason="must preserve cancellation reviewer",
                    idempotency_key=f"cancel-revoke-denied-{uuid.uuid4().hex}",
                ),
            )
        assert revoke_error.value.code == "branch_approver_grant_in_use"

        await _assert_sql_rejected(
            engine,
            "UPDATE agency_branch_role_grant "
            "SET status = 'revoked', revision = revision + 1, "
            "revoked_at = :now, revocation_reason = 'direct revoke' "
            "WHERE id = :grant_id",
            {"grant_id": actors.approver_grant_id, "now": now},
            contains=(
                "pending cancellation approval requires eligible "
                "replacement approver"
            ),
        )
        with pytest.raises(AgencyTransactionConflict) as submit_error:
            await _call(
                session_factory,
                lambda session: AgencyOrderReviewService(
                    session
                ).submit_order(
                    actor_user_id=actors.customer_user_id,
                    order_id=order.id,
                    expected_revision=order.revision,
                    idempotency_key=f"cancel-submit-denied-{uuid.uuid4().hex}",
                ),
            )
        assert submit_error.value.code == "cancellation_case_open"
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order "
            "SET status = 'pending_review', revision = revision + 1, "
            "updated_at = :now WHERE id = :order_id",
            {"order_id": order.id, "now": now},
            contains=(
                "agency_order cannot enter review while cancellation case "
                "is open"
            ),
        )

        controls = await _seed_replacement_approver(
            session_factory,
            actors,
            granted_by_user_id=owner_id,
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_membership SET user_id = :customer_id "
            "WHERE id = :membership_id",
            {
                "customer_id": actors.customer_user_id,
                "membership_id": controls.approver_membership_id,
            },
            contains="agency_membership binding is immutable",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_membership SET status = 'suspended' "
            "WHERE id = :membership_id",
            {"membership_id": controls.approver_membership_id},
            contains="active branch grants must be revoked first",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'rejected', revision = revision + 1, "
            "review_decision = 'rejected', "
            "reviewed_by_user_id = :reviewer_id, reviewed_at = :now, "
            "review_note = 'not an approver', updated_at = :now "
            "WHERE id = :case_id",
            {
                "case_id": case.id,
                "reviewer_id": actors.advisor_id,
                "now": datetime.now(UTC),
            },
            contains="cancellation review requires active branch approver",
        )

        revoked = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).revoke_branch_role_grant(
                actor_user_id=owner_id,
                branch_id=actors.branch_id,
                grant_id=actors.approver_grant_id,
                expected_revision=1,
                reason="replacement approver is active",
                idempotency_key=f"cancel-revoke-allowed-{uuid.uuid4().hex}",
            ),
        )
        assert revoked.status == "revoked"
        rejected = await _call(
            session_factory,
            lambda session: CancellationService(
                session
            ).review_cancellation(
                actor_user_id=controls.approver_id,
                case_id=case.id,
                decision="reject",
                expected_revision=case.revision,
                approved_refund_amount=None,
                approved_refund_currency=None,
                reason="customer will continue with the order",
                idempotency_key=f"cancel-review-reject-{uuid.uuid4().hex}",
            ),
        )
        assert rejected.status == "rejected"
        submitted = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).submit_order(
                actor_user_id=actors.customer_user_id,
                order_id=order.id,
                expected_revision=order.revision,
                idempotency_key=f"cancel-submit-after-reject-{uuid.uuid4().hex}",
            ),
        )
        assert submitted.status == "pending_review"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_lifecycle_settlement_can_be_followed_by_stale_case_rejection(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.cancellation_service import CancellationService
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.models.agency_customer_lifecycle import AgencyCustomer

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
        case = await _request_case(session_factory, actors, order)
        async with session_factory() as session:
            customer = await session.get(
                AgencyCustomer,
                actors.customer_record_id,
            )
            assert customer is not None
            customer_revision = customer.lifecycle_revision

        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_customer(
                actor_user_id=actors.customer_user_id,
                customer_id=actors.customer_record_id,
                expected_revision=customer_revision,
                reason="customer withdrew while cancellation was pending",
                idempotency_key=f"cancel-stale-close-{uuid.uuid4().hex}",
            ),
        )
        settled_order = await _get_order(session_factory, order.id)
        assert settled_order.status == "cancelled"
        assert settled_order.revision > case.order_revision_at_request

        rejected = await _call(
            session_factory,
            lambda session: CancellationService(
                session
            ).review_cancellation(
                actor_user_id=actors.approver_id,
                case_id=case.id,
                decision="reject",
                expected_revision=case.revision,
                approved_refund_amount=None,
                approved_refund_currency=None,
                reason="relationship already closed the internal order",
                idempotency_key=f"cancel-stale-reject-{uuid.uuid4().hex}",
            ),
        )
        final_order = await _get_order(session_factory, order.id)
        assert rejected.status == "rejected"
        assert final_order.status == "cancelled"
        assert final_order.revision == settled_order.revision
        assert final_order.cancelled_at == settled_order.cancelled_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_exposed_actions_reconcile_latest_redo_before_completion(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.models.agency_cancellation import (
        AgencyOrderCompensationRecord,
        AgencyOrderReconciliationRecord,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        operators = await _seed_cancellation_operators(
            session_factory,
            actors,
        )
        order = await _create_order(
            session_factory,
            actors,
            approved=True,
        )
        exposure_rows = await _add_exposure(
            session_factory,
            order,
            payment=True,
            fulfillment=True,
        )
        case = await _request_case(session_factory, actors, order)
        assert (
            case.supplier_cancel_required,
            case.refund_required,
        ) == (True, True)
        case = await _review_case(
            session_factory,
            actors,
            case,
            refund_amount=order.total_amount,
        )
        assert case.status == "action_pending"
        requested_at = (
            await _get_order(session_factory, order.id)
        ).cancellation_requested_at
        assert requested_at is not None
        payment_attempt, fulfillment_record = exposure_rows
        await _assert_sql_rejected(
            engine,
            "UPDATE payment_attempt SET status = 'failed' WHERE id = :id",
            {"id": payment_attempt.id},
            contains="payment_attempt is frozen",
        )
        await _assert_sql_rejected(
            engine,
            "DELETE FROM fulfillment_record WHERE id = :id",
            {"id": fulfillment_record.id},
            contains="fulfillment_record is frozen",
        )
        await _assert_sql_rejected(
            engine,
            "INSERT INTO payment_attempt "
            "(id, agency_id, order_id, attempt_no, idempotency_key, "
            "provider_code, status, amount, currency, "
            "external_action_enabled, provider_reference, failure_code, "
            "started_at, completed_at, created_at, updated_at) "
            "SELECT :new_id, agency_id, order_id, attempt_no + 1, :key, "
            "provider_code, status, amount, currency, "
            "external_action_enabled, provider_reference, failure_code, "
            "started_at, completed_at, created_at, updated_at "
            "FROM payment_attempt WHERE id = :source_id",
            {
                "new_id": uuid.uuid4(),
                "key": f"late-payment-{uuid.uuid4().hex}",
                "source_id": payment_attempt.id,
            },
            contains="payment_attempt is frozen",
        )

        supplier_result = await _manual_result(
            session_factory,
            actor_user_id=operators.booking_operator_id,
            case=case,
            action_type="supplier_cancel",
            outcome="succeeded",
            amount=None,
        )
        case = await _get_case(session_factory, case.id)
        assert case.status == "action_pending"
        first_refund = await _manual_result(
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
        assert case.status == "reconciliation_pending"
        first_refund_reconciliation = await _reconcile(
            session_factory,
            auditor_id=operators.auditor_id,
            case=case,
            record_id=first_refund.id,
            outcome="mismatched",
            observed_amount=Decimal("0.01"),
            observed_currency=order.currency,
        )
        case = await _get_case(session_factory, case.id)
        stored_order = await _get_order(session_factory, order.id)
        assert case.status == "manual_intervention"
        assert stored_order.status == "manual_intervention"

        case = await _resume(
            session_factory,
            manager_id=operators.branch_manager_id,
            case=case,
        )
        assert case.status == "action_pending"
        stored_order = await _get_order(session_factory, order.id)
        assert stored_order.status == "cancellation_pending"
        assert stored_order.cancellation_requested_at == requested_at

        second_refund = await _manual_result(
            session_factory,
            actor_user_id=operators.finance_id,
            case=case,
            action_type="refund",
            outcome="succeeded",
            amount=order.total_amount,
        )
        case = await _get_case(session_factory, case.id)
        assert case.status == "reconciliation_pending"
        final_reconciliation = await _reconcile(
            session_factory,
            auditor_id=operators.auditor_id,
            case=case,
            record_id=second_refund.id,
            outcome="matched",
            observed_amount=order.total_amount,
            observed_currency=order.currency,
        )
        case = await _get_case(session_factory, case.id)
        stored_order = await _get_order(session_factory, order.id)

        assert second_refund.record_sequence > first_refund.record_sequence
        assert case.status == "completed"
        assert stored_order.status == "cancelled"
        assert stored_order.cancelled_at == case.completed_at
        assert stored_order.cancellation_requested_at == requested_at
        assert supplier_result.system_external_action_triggered is False
        assert first_refund.system_external_action_triggered is False
        assert second_refund.system_external_action_triggered is False
        assert (
            first_refund_reconciliation.reconciled_by_user_id
            == operators.auditor_id
        )
        assert (
            final_reconciliation.reconciled_by_user_id
            == operators.auditor_id
        )

        async with session_factory() as session:
            refund_records = list(
                (
                    await session.execute(
                        select(AgencyOrderCompensationRecord)
                        .where(
                            AgencyOrderCompensationRecord.cancellation_case_id
                            == case.id
                        )
                        .where(
                            AgencyOrderCompensationRecord.action_type
                            == "refund"
                        )
                        .order_by(
                            AgencyOrderCompensationRecord.record_sequence
                        )
                    )
                )
                .scalars()
                .all()
            )
            reconciliations = list(
                (
                    await session.execute(
                        select(AgencyOrderReconciliationRecord).where(
                            AgencyOrderReconciliationRecord.cancellation_case_id
                            == case.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert [record.id for record in refund_records] == [
            first_refund.id,
            second_refund.id,
        ]
        assert {
            (item.compensation_record_id, item.outcome)
            for item in reconciliations
        }.issuperset(
            {
                (first_refund.id, "mismatched"),
                (second_refund.id, "matched"),
            }
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_rejects_tampering_and_scopes_legacy_pending(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.models.agency_cancellation import (
        AgencyOrderCancellationEvent,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        operators = await _seed_cancellation_operators(
            session_factory,
            actors,
        )
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
        await _assert_direct_case_insert_rejected(
            engine,
            order=order,
            requester_id=actors.customer_user_id,
            supplier_required=False,
            refund_required=False,
            contains=(
                "new cancellation case required actions must match locked "
                "ledgers"
            ),
        )
        case = await _request_case(session_factory, actors, order)

        review_params = {
            "case_id": case.id,
            "reviewer_id": actors.approver_id,
            "requester_id": actors.customer_user_id,
            "amount": order.total_amount,
            "now": datetime.now(UTC),
        }
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'rejected', revision = revision + 1, "
            "review_decision = 'rejected', "
            "reviewed_by_user_id = :requester_id, reviewed_at = :now, "
            "review_note = 'self review', updated_at = :now "
            "WHERE id = :case_id",
            review_params,
            contains="ck_agency_order_cancellation_case_four_eyes",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'rejected', revision = revision + 1, "
            "review_decision = NULL, "
            "reviewed_by_user_id = :reviewer_id, reviewed_at = :now, "
            "review_note = 'null decision', updated_at = :now "
            "WHERE id = :case_id",
            review_params,
            contains="ck_agency_order_cancellation_case_review_shape",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'rejected', revision = revision + 1, "
            "review_decision = 'rejected', "
            "reviewed_by_user_id = :reviewer_id, reviewed_at = :now, "
            "review_note = 'external flag', "
            "external_action_triggered = true, updated_at = :now "
            "WHERE id = :case_id",
            review_params,
            contains="binding is immutable",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'rejected', revision = revision + 2, "
            "review_decision = 'rejected', "
            "reviewed_by_user_id = :reviewer_id, reviewed_at = :now, "
            "review_note = 'skip revision', updated_at = :now "
            "WHERE id = :case_id",
            review_params,
            contains="revision must advance by one",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'reconciliation_pending', "
            "revision = revision + 1, review_decision = 'approved', "
            "reviewed_by_user_id = :reviewer_id, reviewed_at = :now, "
            "approved_refund_amount = :amount, updated_at = :now "
            "WHERE id = :case_id",
            review_params,
            contains="invalid agency_order_cancellation_case status transition",
        )

        staff_requested_order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
        staff_requested_case = await _request_case(
            session_factory,
            actors,
            staff_requested_order,
            requester_id=actors.advisor_id,
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_case "
            "SET status = 'rejected', revision = revision + 1, "
            "review_decision = 'rejected', "
            "reviewed_by_user_id = :customer_id, reviewed_at = :now, "
            "review_note = 'customer review', updated_at = :now "
            "WHERE id = :case_id",
            {
                "case_id": staff_requested_case.id,
                "customer_id": actors.customer_user_id,
                "now": datetime.now(UTC),
            },
            contains="order customer cannot review cancellation case",
        )

        case = await _review_case(
            session_factory,
            actors,
            case,
            refund_amount=order.total_amount,
        )
        insert_result_sql = (
            "INSERT INTO agency_order_compensation_record "
            "(id, agency_id, branch_id, order_id, customer_id, "
            "cancellation_case_id, record_sequence, case_revision, "
            "action_type, outcome, external_reference_hash, evidence_hash, "
            "amount, currency, occurred_at, recorded_by_user_id, "
            "system_external_action_triggered, created_at) "
            "VALUES (:id, :agency_id, :branch_id, :order_id, :customer_id, "
            ":case_id, 1, :case_revision, 'refund', 'succeeded', "
            ":reference_hash, :evidence_hash, :amount, :currency, :now, "
            ":recorder_id, :external_flag, :now)"
        )
        result_params = {
            "id": uuid.uuid4(),
            "agency_id": case.agency_id,
            "branch_id": case.branch_id,
            "order_id": case.order_id,
            "customer_id": case.customer_id,
            "case_id": case.id,
            "case_revision": case.revision,
            "reference_hash": "d" * 64,
            "evidence_hash": "e" * 64,
            "amount": order.total_amount - Decimal("1.00"),
            "currency": order.currency,
            "now": datetime.now(UTC),
            "recorder_id": operators.finance_id,
            "external_flag": False,
        }
        await _assert_sql_rejected(
            engine,
            insert_result_sql,
            result_params,
            contains="refund result must match approved cancellation amount",
        )
        await _assert_sql_rejected(
            engine,
            insert_result_sql,
            {
                **result_params,
                "id": uuid.uuid4(),
                "amount": order.total_amount,
                "currency": "USD",
            },
            contains="compensation currency must match cancellation case",
        )
        await _assert_sql_rejected(
            engine,
            insert_result_sql,
            {
                **result_params,
                "id": uuid.uuid4(),
                "amount": order.total_amount,
                "external_flag": True,
            },
            contains="system-triggered compensation action is disabled",
        )

        async with session_factory() as session:
            last_sequence = (
                await session.execute(
                    select(AgencyOrderCancellationEvent.event_sequence)
                    .where(
                        AgencyOrderCancellationEvent.cancellation_case_id
                        == case.id
                    )
                    .order_by(
                        AgencyOrderCancellationEvent.event_sequence.desc()
                    )
                    .limit(1)
                )
            ).scalar_one()
        await _assert_sql_rejected(
            engine,
            "INSERT INTO agency_order_cancellation_event "
            "(id, agency_id, branch_id, order_id, customer_id, "
            "cancellation_case_id, event_sequence, case_revision, "
            "event_type, actor_user_id, payload_hash, event_metadata, "
            "created_at) "
            "VALUES (:id, :agency_id, :branch_id, :order_id, :customer_id, "
            ":case_id, :sequence, :case_revision, 'cross_binding', "
            ":actor_id, :payload_hash, CAST(:metadata AS jsonb), :now)",
            {
                "id": uuid.uuid4(),
                "agency_id": case.agency_id,
                "branch_id": case.branch_id,
                "order_id": case.order_id,
                "customer_id": uuid.uuid4(),
                "case_id": case.id,
                "sequence": last_sequence + 1,
                "case_revision": case.revision,
                "actor_id": actors.approver_id,
                "payload_hash": "f" * 64,
                "metadata": "{}",
                "now": datetime.now(UTC),
            },
            contains="cancellation event must match current case revision",
        )

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
        await _assert_sql_rejected(
            engine,
            "INSERT INTO agency_order_reconciliation_record "
            "(id, agency_id, branch_id, order_id, customer_id, "
            "cancellation_case_id, compensation_record_id, case_revision, "
            "outcome, observed_amount, currency, reconciled_by_user_id, "
            "evidence_hash, reconciled_at, created_at) "
            "VALUES (:id, :agency_id, :branch_id, :order_id, :customer_id, "
            ":case_id, :record_id, :case_revision, 'mismatched', "
            ":observed_amount, NULL, :reconciler_id, :evidence_hash, "
            ":now, :now)",
            {
                "id": uuid.uuid4(),
                "agency_id": case.agency_id,
                "branch_id": case.branch_id,
                "order_id": case.order_id,
                "customer_id": case.customer_id,
                "case_id": case.id,
                "record_id": refund_result.id,
                "case_revision": case.revision,
                "observed_amount": order.total_amount,
                "reconciler_id": operators.auditor_id,
                "evidence_hash": "0" * 64,
                "now": datetime.now(UTC),
            },
            contains="ck_agency_order_reconciliation_record_amount",
        )
        await _assert_sql_rejected(
            engine,
            "INSERT INTO agency_order_reconciliation_record "
            "(id, agency_id, branch_id, order_id, customer_id, "
            "cancellation_case_id, compensation_record_id, case_revision, "
            "outcome, observed_amount, currency, reconciled_by_user_id, "
            "evidence_hash, reconciled_at, created_at) "
            "VALUES (:id, :agency_id, :branch_id, :order_id, :customer_id, "
            ":case_id, :record_id, :case_revision, 'matched', "
            ":observed_amount, :currency, :reconciler_id, :evidence_hash, "
            ":now, :now)",
            {
                "id": uuid.uuid4(),
                "agency_id": case.agency_id,
                "branch_id": case.branch_id,
                "order_id": case.order_id,
                "customer_id": case.customer_id,
                "case_id": case.id,
                "record_id": supplier_result.id,
                "case_revision": case.revision,
                "observed_amount": order.total_amount,
                "currency": order.currency,
                "reconciler_id": operators.auditor_id,
                "evidence_hash": "2" * 64,
                "now": datetime.now(UTC),
            },
            contains=(
                "supplier cancellation reconciliation cannot include amount"
            ),
        )
        await _assert_sql_rejected(
            engine,
            "INSERT INTO agency_order_reconciliation_record "
            "(id, agency_id, branch_id, order_id, customer_id, "
            "cancellation_case_id, compensation_record_id, case_revision, "
            "outcome, observed_amount, currency, reconciled_by_user_id, "
            "evidence_hash, reconciled_at, created_at) "
            "VALUES (:id, :agency_id, :branch_id, :order_id, :customer_id, "
            ":case_id, :record_id, :case_revision, 'matched', NULL, NULL, "
            ":reconciler_id, :evidence_hash, :now, :now)",
            {
                "id": uuid.uuid4(),
                "agency_id": case.agency_id,
                "branch_id": case.branch_id,
                "order_id": case.order_id,
                "customer_id": case.customer_id,
                "case_id": case.id,
                "record_id": supplier_result.id,
                "case_revision": case.revision,
                "reconciler_id": operators.booking_operator_id,
                "evidence_hash": "1" * 64,
                "now": datetime.now(UTC),
            },
            contains="compensation recorder cannot reconcile own result",
        )

        supplier_reconciliation = await _reconcile(
            session_factory,
            auditor_id=operators.auditor_id,
            case=case,
            record_id=supplier_result.id,
            outcome="matched",
        )
        case = await _get_case(session_factory, case.id)
        refund_reconciliation = await _reconcile(
            session_factory,
            auditor_id=operators.auditor_id,
            case=case,
            record_id=refund_result.id,
            outcome="matched",
            observed_amount=order.total_amount,
            observed_currency=order.currency,
        )
        case = await _get_case(session_factory, case.id)
        assert case.status == "completed"

        async with session_factory() as session:
            event_id = (
                await session.execute(
                    select(AgencyOrderCancellationEvent.id)
                    .where(
                        AgencyOrderCancellationEvent.cancellation_case_id
                        == case.id
                    )
                    .order_by(AgencyOrderCancellationEvent.event_sequence)
                    .limit(1)
                )
            ).scalar_one()
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_cancellation_event "
            "SET event_type = 'tampered' WHERE id = :id",
            {"id": event_id},
            contains="append-only",
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order_compensation_record "
            "SET outcome = 'failed' WHERE id = :id",
            {"id": supplier_result.id},
            contains="append-only",
        )
        await _assert_sql_rejected(
            engine,
            "DELETE FROM agency_order_reconciliation_record WHERE id = :id",
            {"id": refund_reconciliation.id},
            contains="append-only",
        )

        active_order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
        await _assert_sql_rejected(
            engine,
            "UPDATE agency_order SET status = 'cancellation_pending', "
            "revision = revision + 1, cancellation_requested_at = :now, "
            "cancelled_at = NULL, updated_at = :now WHERE id = :order_id",
            {
                "order_id": active_order.id,
                "now": datetime.now(UTC),
            },
            contains="active customer cancellation state requires case",
        )

        inactive_order = await _create_order(
            session_factory,
            actors,
            approved=False,
        )
        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE agency_customer_advisor_assignment "
                    "SET status = 'ended', revision = revision + 1, "
                    "ended_at = :now, ended_reason = 'integration close', "
                    "updated_at = :now "
                    "WHERE agency_id = :agency_id "
                    "AND customer_id = :customer_id AND status = 'active'"
                ),
                {
                    "now": now,
                    "agency_id": actors.agency_id,
                    "customer_id": actors.customer_record_id,
                },
            )
            await connection.execute(
                text(
                    "UPDATE agency_customer SET status = 'inactive', "
                    "lifecycle_revision = lifecycle_revision + 1, "
                    "deactivated_at = :now, updated_at = :now "
                    "WHERE id = :customer_id"
                ),
                {
                    "now": now,
                    "customer_id": actors.customer_record_id,
                },
            )
            await connection.execute(
                text(
                    "UPDATE agency_order "
                    "SET status = 'cancellation_pending', "
                    "revision = revision + 1, "
                    "cancellation_requested_at = :now, cancelled_at = NULL, "
                    "updated_at = :now WHERE id = :order_id"
                ),
                {"now": now, "order_id": inactive_order.id},
            )
        stored_inactive_order = await _get_order(
            session_factory,
            inactive_order.id,
        )
        assert stored_inactive_order.status == "cancellation_pending"
        assert stored_inactive_order.cancelled_at is None
        assert stored_inactive_order.cancellation_requested_at == now
        assert supplier_reconciliation.outcome == "matched"
    finally:
        await engine.dispose()
