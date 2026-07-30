"""PostgreSQL integration checks for agency branch permission boundaries."""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_agency_customer_lifecycle_postgres_integration import _call
from tests.test_agency_transaction_postgres_integration import (
    PostgresSandbox,
    _quote_request,
    _seed_tenant,
    _session_factory,
    migrated_postgres,
)


pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.asyncio
async def test_branch_access_matrix_approver_queue_and_inactive_fail_closed(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import (
        AgencyTransactionConflict,
        AgencyTransactionNotFound,
    )
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.models.agency_customer_lifecycle import (
        AgencyBranch,
        AgencyBranchRoleGrant,
    )
    from app.models.agency_transaction import (
        AgencyCustomer,
        AgencyMembership,
    )
    from app.models.user import User
    from app.schemas.agency_transaction import AgencyOrderCreateRequest

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        owner_id, manager_id = uuid.uuid4(), uuid.uuid4()
        manager_membership_id, manager_grant_id = uuid.uuid4(), uuid.uuid4()
        other_branch_id, other_customer_id = uuid.uuid4(), uuid.uuid4()
        unique, now = uuid.uuid4().hex, datetime.now(UTC)
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    User(
                        id=owner_id,
                        username=f"matrix-owner-{unique}",
                        email=f"matrix-owner-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                    User(
                        id=manager_id,
                        username=f"matrix-manager-{unique}",
                        email=f"matrix-manager-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                ]
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
                    AgencyMembership(
                        id=manager_membership_id,
                        agency_id=actors.agency_id,
                        user_id=manager_id,
                        role="branch_manager",
                        status="active",
                        joined_at=now,
                    ),
                    AgencyBranch(
                        id=other_branch_id,
                        agency_id=actors.agency_id,
                        branch_code="SECOND",
                        name="Second Branch",
                        status="active",
                        revision=1,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    AgencyBranchRoleGrant(
                        id=manager_grant_id,
                        agency_id=actors.agency_id,
                        branch_id=actors.branch_id,
                        membership_id=manager_membership_id,
                        role="branch_manager",
                        status="active",
                        revision=1,
                        granted_at=now,
                    ),
                    AgencyCustomer(
                        id=other_customer_id,
                        agency_id=actors.agency_id,
                        branch_id=other_branch_id,
                        customer_no=f"CUST-{unique[:20]}",
                        user_id=None,
                        source_type="manual",
                        status="prospect",
                        consent_status="unknown",
                        lifecycle_revision=1,
                        invited_at=now,
                    ),
                ]
            )

        async def visible_customers(actor_id):
            return await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).list_customers(
                    actor_user_id=actor_id,
                    agency_id=actors.agency_id,
                    branch_id=None,
                    status_filter=None,
                    limit=20,
                    offset=0,
                ),
            )

        manager_rows, _ = await visible_customers(manager_id)
        advisor_rows, _ = await visible_customers(actors.advisor_id)
        owner_rows, _ = await visible_customers(owner_id)
        approver_rows, _ = await visible_customers(actors.approver_id)
        assert {item.id for item in manager_rows} == {
            actors.customer_record_id
        }
        assert {item.id for item in advisor_rows} == {
            actors.customer_record_id
        }
        assert {item.id for item in owner_rows} == {
            actors.customer_record_id,
            other_customer_id,
        }
        assert approver_rows == []
        with pytest.raises(AgencyTransactionNotFound):
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).get_customer(
                    actor_user_id=manager_id,
                    customer_id=other_customer_id,
                ),
            )

        quote = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).create_quote(
                actor_user_id=actors.advisor_id,
                data=_quote_request(actors),
                idempotency_key=f"matrix-quote-{unique}",
            ),
        )
        await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).issue_quote(
                actor_user_id=actors.advisor_id,
                quote_id=quote.id,
                expected_revision=1,
                idempotency_key=f"matrix-issue-{unique}",
            ),
        )
        accepted = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).accept_quote(
                actor_user_id=actors.customer_user_id,
                quote_id=quote.id,
                expected_revision=2,
                idempotency_key=f"matrix-accept-{unique}",
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
                idempotency_key=f"matrix-order-{unique}",
            ),
        )
        await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).submit_order(
                actor_user_id=actors.customer_user_id,
                order_id=order.id,
                expected_revision=1,
                idempotency_key=f"matrix-submit-{unique}",
            ),
        )
        reviews, total = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(
                session
            ).list_order_reviews(
                actor_user_id=actors.approver_id,
                agency_id=actors.agency_id,
                status_filter="pending",
                limit=20,
                offset=0,
            ),
        )
        assert total == 1
        assert [item.order_id for item in reviews] == [order.id]

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_branch SET status = 'inactive', "
                        "revision = revision + 1, deactivated_at = now() "
                        "WHERE id = :branch_id"
                    ),
                    {"branch_id": actors.branch_id},
                )
        with pytest.raises(AgencyTransactionConflict) as pending_revoke:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).revoke_branch_role_grant(
                    actor_user_id=owner_id,
                    branch_id=actors.branch_id,
                    grant_id=actors.approver_grant_id,
                    expected_revision=1,
                    reason="门店停用前撤销审批权限",
                    idempotency_key=f"pending-approver-{unique}",
                ),
            )
        assert pending_revoke.value.code == "branch_approver_grant_in_use"
        rejected = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(
                session
            ).decide_order_review(
                actor_user_id=actors.approver_id,
                order_id=order.id,
                decision="reject",
                expected_revision=2,
                reason="门店停用前关闭未执行订单",
                idempotency_key=f"close-review-{unique}",
            ),
        )
        assert rejected.status == "rejected"

        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).end_customer_advisor_assignment(
                actor_user_id=owner_id,
                customer_id=actors.customer_record_id,
                expected_revision=1,
                reason="门店停用前解除顾问分配",
                idempotency_key=f"close-assignment-{unique}",
            ),
        )
        deactivated = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_customer(
                actor_user_id=owner_id,
                customer_id=actors.customer_record_id,
                expected_revision=2,
                reason="门店停用前结束客户服务",
                idempotency_key=f"close-customer-{unique}",
            ),
        )
        assert deactivated.lifecycle_revision == 3
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE agency_customer SET status = 'blocked', "
                    "lifecycle_revision = lifecycle_revision + 1 "
                    "WHERE id = :customer_id"
                ),
                {"customer_id": actors.customer_record_id},
            )
        with pytest.raises(AgencyTransactionConflict) as blocked:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).deactivate_customer(
                    actor_user_id=owner_id,
                    customer_id=actors.customer_record_id,
                    expected_revision=4,
                    reason="不得绕过独立风险复核",
                    idempotency_key=f"blocked-customer-{unique}",
                ),
            )
        assert blocked.value.code == "customer_blocked"
        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer SET status = 'inactive', "
                        "lifecycle_revision = lifecycle_revision + 1 "
                        "WHERE id = :customer_id"
                    ),
                    {"customer_id": actors.customer_record_id},
                )
        for grant_id, suffix in (
            (actors.advisor_grant_id, "advisor"),
            (actors.approver_grant_id, "approver"),
            (manager_grant_id, "manager"),
        ):
            await _call(
                session_factory,
                lambda session, grant_id=grant_id, suffix=suffix: (
                    CustomerLifecycleService(
                        session
                    ).revoke_branch_role_grant(
                        actor_user_id=owner_id,
                        branch_id=actors.branch_id,
                        grant_id=grant_id,
                        expected_revision=1,
                        reason="门店停用前撤销授权",
                        idempotency_key=f"close-grant-{suffix}-{unique}",
                    )
                ),
            )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE agency_branch SET status = 'inactive', "
                    "revision = revision + 1, deactivated_at = now() "
                    "WHERE id = :branch_id"
                ),
                {"branch_id": actors.branch_id},
            )
        assert (await visible_customers(actors.advisor_id))[1] == 0
        reviews_after, total_after = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(
                session
            ).list_order_reviews(
                actor_user_id=actors.approver_id,
                agency_id=actors.agency_id,
                status_filter=None,
                limit=20,
                offset=0,
            ),
        )
        assert reviews_after == []
        assert total_after == 0
        with pytest.raises(AgencyTransactionNotFound):
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).assign_customer_advisor(
                    actor_user_id=owner_id,
                    customer_id=actors.customer_record_id,
                    expected_revision=4,
                    advisor_role_grant_id=actors.advisor_grant_id,
                    reason=None,
                    idempotency_key=f"inactive-assign-{unique}",
                ),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_approver_revocations_preserve_review_coverage(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import AgencyTransactionConflict
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.models.agency_customer_lifecycle import AgencyBranchRoleGrant
    from app.models.agency_transaction import AgencyMembership
    from app.models.user import User
    from app.schemas.agency_transaction import AgencyOrderCreateRequest

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        owner_id = uuid.uuid4()
        second_approver_id = uuid.uuid4()
        second_membership_id = uuid.uuid4()
        second_grant_id = uuid.uuid4()
        unique, now = uuid.uuid4().hex, datetime.now(UTC)
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    User(
                        id=owner_id,
                        username=f"race-owner-{unique}",
                        email=f"race-owner-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                    User(
                        id=second_approver_id,
                        username=f"race-approver-{unique}",
                        email=f"race-approver-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                ]
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
                    AgencyMembership(
                        id=second_membership_id,
                        agency_id=actors.agency_id,
                        user_id=second_approver_id,
                        role="approver",
                        status="active",
                        joined_at=now,
                    ),
                ]
            )
            await session.flush()
            session.add(
                AgencyBranchRoleGrant(
                    id=second_grant_id,
                    agency_id=actors.agency_id,
                    branch_id=actors.branch_id,
                    membership_id=second_membership_id,
                    role="approver",
                    status="active",
                    revision=1,
                    granted_by_user_id=owner_id,
                    granted_at=now,
                )
            )

        quote = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).create_quote(
                actor_user_id=actors.advisor_id,
                data=_quote_request(actors),
                idempotency_key=f"race-quote-{unique}",
            ),
        )
        offered = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).issue_quote(
                actor_user_id=actors.advisor_id,
                quote_id=quote.id,
                expected_revision=1,
                idempotency_key=f"race-issue-{unique}",
            ),
        )
        accepted = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).accept_quote(
                actor_user_id=actors.customer_user_id,
                quote_id=quote.id,
                expected_revision=offered.revision,
                idempotency_key=f"race-accept-{unique}",
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
                idempotency_key=f"race-order-{unique}",
            ),
        )
        await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).submit_order(
                actor_user_id=actors.customer_user_id,
                order_id=order.id,
                expected_revision=1,
                idempotency_key=f"race-submit-{unique}",
            ),
        )

        barrier = asyncio.Barrier(2)

        class BarrierLifecycleService(CustomerLifecycleService):
            async def _get_branch(self, branch_id, *, for_update=False):
                if for_update:
                    await barrier.wait()
                return await super()._get_branch(
                    branch_id,
                    for_update=for_update,
                )

        async def revoke(grant_id: uuid.UUID, suffix: str) -> str:
            try:
                await _call(
                    session_factory,
                    lambda session: BarrierLifecycleService(
                        session
                    ).revoke_branch_role_grant(
                        actor_user_id=owner_id,
                        branch_id=actors.branch_id,
                        grant_id=grant_id,
                        expected_revision=1,
                        reason="并发审批员撤权测试",
                        idempotency_key=f"race-revoke-{suffix}-{unique}",
                    ),
                )
                return "revoked"
            except AgencyTransactionConflict as error:
                return error.code

        outcomes = await asyncio.gather(
            revoke(actors.approver_grant_id, "first"),
            revoke(second_grant_id, "second"),
        )
        assert sorted(outcomes) == [
            "branch_approver_grant_in_use",
            "revoked",
        ]
        remaining_approver_id = (
            second_approver_id
            if outcomes[0] == "revoked"
            else actors.approver_id
        )
        reviews, total = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(
                session
            ).list_order_reviews(
                actor_user_id=remaining_approver_id,
                agency_id=actors.agency_id,
                status_filter="pending",
                limit=20,
                offset=0,
            ),
        )
        assert total == 1
        assert [review.order_id for review in reviews] == [order.id]
    finally:
        await engine.dispose()
