"""PostgreSQL integration checks for branch-scoped customer lifecycle."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.test_agency_transaction_postgres_integration import (
    PostgresSandbox,
    _quote_request,
    _seed_lifecycle_actors,
    _seed_tenant,
    _session_factory,
    migrated_postgres,
    postgres_schema,
)


pytestmark = [pytest.mark.integration, pytest.mark.slow]


async def _call(session_factory, operation):
    async with session_factory() as session:
        async with session.begin():
            return await operation(session)


def test_nonempty_0003_upgrade_backfills_branch_without_fake_consent(
    postgres_schema: PostgresSandbox,
) -> None:
    command.upgrade(postgres_schema.alembic_config, "20260726_0003")
    ids = {
        name: uuid.uuid4()
        for name in (
            "agency",
            "advisor",
            "approver",
            "customer_user",
            "advisor_membership",
            "approver_membership",
            "customer",
            "quote",
            "order",
            "order_event",
            "review",
        )
    }
    now = datetime.now(UTC)
    engine = create_engine(postgres_schema.sync_url)
    try:
        with engine.begin() as connection:
            for role in ("advisor", "approver", "customer_user"):
                connection.execute(
                    text(
                        'INSERT INTO "user" '
                        "(id, username, email, password_hash, preferences, "
                        "created_at, updated_at) "
                        "VALUES (:id, :username, :email, 'test-only', NULL, "
                        ":now, :now)"
                    ),
                    {
                        "id": ids[role],
                        "username": f"{role}-{ids[role].hex[:12]}",
                        "email": f"{role}-{ids[role].hex[:12]}@example.test",
                        "now": now,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO agency "
                    "(id, agency_code, name, status, created_at, updated_at) "
                    "VALUES (:id, :code, 'Legacy Agency', 'active', :now, :now)"
                ),
                {
                    "id": ids["agency"],
                    "code": f"LEGACY-{ids['agency'].hex[:16]}",
                    "now": now,
                },
            )
            for role, membership_key, user_key in (
                ("travel_advisor", "advisor_membership", "advisor"),
                ("approver", "approver_membership", "approver"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO agency_membership "
                        "(id, agency_id, user_id, role, status, joined_at, "
                        "created_at, updated_at) "
                        "VALUES (:id, :agency, :user_id, :role, 'active', "
                        ":now, :now, :now)"
                    ),
                    {
                        "id": ids[membership_key],
                        "agency": ids["agency"],
                        "user_id": ids[user_key],
                        "role": role,
                        "now": now,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO agency_customer "
                    "(id, agency_id, user_id, status, activated_at, "
                    "created_at, updated_at) "
                    "VALUES (:id, :agency, :user_id, 'active', :now, :now, :now)"
                ),
                {
                    "id": ids["customer"],
                    "agency": ids["agency"],
                    "user_id": ids["customer_user"],
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_quote "
                    "(id, quote_no, idempotency_key, agency_id, user_id, "
                    "conversation_id, product_id, status, revision, "
                    "payload_hash, total_amount, currency, snapshot_version, "
                    "quote_snapshot, valid_until, issued_at, accepted_at, "
                    "created_at, updated_at) VALUES "
                    "(:id, :number, :key, :agency, :user_id, NULL, NULL, "
                    "'accepted', 1, :hash, 100, 'CNY', 'agency_quote.v1', "
                    "'{}'::json, :valid_until, :now, :now, :now, :now)"
                ),
                {
                    "id": ids["quote"],
                    "number": f"Q-{ids['quote'].hex[:20]}",
                    "key": f"quote-{ids['quote'].hex}",
                    "agency": ids["agency"],
                    "user_id": ids["customer_user"],
                    "hash": "a" * 64,
                    "valid_until": now + timedelta(days=1),
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_order "
                    "(id, order_no, agency_id, quote_id, user_id, "
                    "idempotency_key, status, revision, payload_hash, "
                    "payment_status, fulfillment_status, total_amount, "
                    "currency, quote_snapshot, external_action_enabled, "
                    "confirmed_at, cancelled_at, completed_at, created_at, "
                    "updated_at) VALUES "
                    "(:id, :number, :agency, :quote, :user_id, :key, "
                    "'pending_review', 1, :hash, 'not_started', "
                    "'not_started', 100, 'CNY', '{}'::json, false, NULL, "
                    "NULL, NULL, :now, :now)"
                ),
                {
                    "id": ids["order"],
                    "number": f"ORDER-{ids['order'].hex[:16]}",
                    "agency": ids["agency"],
                    "quote": ids["quote"],
                    "user_id": ids["customer_user"],
                    "key": f"order-{ids['order'].hex}",
                    "hash": "a" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_order_event "
                    "(id, agency_id, order_id, event_sequence, order_revision, "
                    "event_type, from_status, to_status, actor_user_id, "
                    "payload_hash, event_metadata, created_at) VALUES "
                    "(:id, :agency, :order_id, 1, 1, 'order_created', NULL, "
                    "'draft', :actor, :hash, '{}'::json, :now)"
                ),
                {
                    "id": ids["order_event"],
                    "agency": ids["agency"],
                    "order_id": ids["order"],
                    "actor": ids["customer_user"],
                    "hash": "a" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_order_review "
                    "(id, agency_id, order_id, status, order_revision, "
                    "decision_order_revision, payload_hash, total_amount, "
                    "currency, requested_by_user_id, decided_by_user_id, "
                    "decision_reason, decided_at, created_at, updated_at) "
                    "VALUES (:id, :agency, :order_id, 'pending', 1, NULL, "
                    ":hash, 100, 'CNY', :requester, NULL, NULL, NULL, :now, :now)"
                ),
                {
                    "id": ids["review"],
                    "agency": ids["agency"],
                    "order_id": ids["order"],
                    "hash": "a" * 64,
                    "requester": ids["customer_user"],
                    "now": now,
                },
            )

        command.upgrade(postgres_schema.alembic_config, "head")
        with engine.connect() as connection:
            customer = connection.execute(
                text(
                    "SELECT branch_id, customer_no, consent_status, "
                    "consent_version, consent_evidence_hash, lifecycle_revision, "
                    "binding_provenance, claimed_invitation_id, "
                    "consent_evidence_origin, current_consent_record_id "
                    "FROM agency_customer WHERE id = :id"
                ),
                {"id": ids["customer"]},
            ).mappings().one()
            transaction_binding = connection.execute(
                text(
                    "SELECT quote.branch_id AS quote_branch, "
                    "quote.customer_id AS quote_customer, "
                    "order_row.branch_id AS order_branch, "
                    "order_row.customer_id AS order_customer, "
                    "review.branch_id AS review_branch, "
                    "event_row.branch_id AS event_branch "
                    "FROM agency_quote quote "
                    "JOIN agency_order order_row ON order_row.quote_id = quote.id "
                    "JOIN agency_order_review review "
                    "ON review.order_id = order_row.id "
                    "JOIN agency_order_event event_row "
                    "ON event_row.order_id = order_row.id "
                    "WHERE quote.id = :quote_id"
                ),
                {"quote_id": ids["quote"]},
            ).mappings().one()
            grants = connection.execute(
                text(
                    "SELECT role, branch_id FROM agency_branch_role_grant "
                    "WHERE agency_id = :agency ORDER BY role"
                ),
                {"agency": ids["agency"]},
            ).all()

        assert customer["branch_id"] == ids["agency"]
        assert customer["customer_no"].startswith("LEGACY-")
        assert customer["consent_status"] == "unknown"
        assert customer["consent_version"] is None
        assert customer["consent_evidence_hash"] is None
        assert customer["lifecycle_revision"] == 1
        assert customer["binding_provenance"] == "legacy_direct"
        assert customer["claimed_invitation_id"] is None
        assert customer["consent_evidence_origin"] == "none"
        assert customer["current_consent_record_id"] is None
        assert set(transaction_binding.values()) == {
            ids["agency"],
            ids["customer"],
        }
        assert grants == [
            ("approver", ids["agency"]),
            ("travel_advisor", ids["agency"]),
        ]

        command.downgrade(
            postgres_schema.alembic_config,
            "20260726_0003",
        )
        with engine.connect() as connection:
            for table_name, row_id in (
                ("agency_customer", ids["customer"]),
                ("agency_quote", ids["quote"]),
                ("agency_order", ids["order"]),
                ("agency_order_event", ids["order_event"]),
                ("agency_order_review", ids["review"]),
            ):
                assert connection.execute(
                    text(
                        f"SELECT 1 FROM {table_name} "
                        "WHERE id = :row_id"
                    ),
                    {"row_id": row_id},
                ).scalar_one() == 1
            removed_column = connection.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND ("
                    "(table_name = 'agency_customer' AND column_name IN ("
                    "'branch_id', 'customer_no', 'consent_status', "
                    "'lifecycle_revision')) OR "
                    "(table_name IN ('agency_quote', 'agency_order') "
                    "AND column_name IN ('branch_id', 'customer_id')) OR "
                    "(table_name IN ("
                    "'agency_order_event', 'agency_order_review') "
                    "AND column_name = 'branch_id')) LIMIT 1"
                )
            ).scalar_one_or_none()
            assert removed_column is None
            assert connection.execute(
                text("SELECT to_regclass('agency_branch')")
            ).scalar_one_or_none() is None
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_offline_customer_lifecycle_assignment_replay_and_reassign(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_consent import (
        CUSTOMER_CONSENT_DOCUMENT_SHA256,
        CUSTOMER_CONSENT_VERSION,
    )
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import (
        AgencyTransactionConflict,
        AgencyTransactionNotFound,
    )
    from app.models.agency_customer_lifecycle import (
        AgencyCustomer,
        AgencyCustomerAdvisorAssignment,
        AgencyCustomerEvent,
    )
    from app.models.agency_customer_identity import (
        AgencyCustomerConsentRecord,
    )
    from app.schemas.agency_customer_lifecycle import (
        AgencyBranchCreateRequest,
        AgencyBranchRoleGrantCreateRequest,
        AgencyCustomerCreateRequest,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_lifecycle_actors(session_factory)
        branch = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).create_branch(
                actor_user_id=actors.owner_id,
                data=AgencyBranchCreateRequest(
                    agency_id=actors.agency_id,
                    branch_code="SHA-01",
                    name="上海一店",
                ),
                idempotency_key="lifecycle-branch",
            ),
        )
        grant_one = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).create_branch_role_grant(
                actor_user_id=actors.owner_id,
                branch_id=branch.id,
                data=AgencyBranchRoleGrantCreateRequest(
                    membership_id=actors.advisor_one_membership_id,
                    role="travel_advisor",
                ),
                idempotency_key="advisor-one-grant",
            ),
        )
        grant_two = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).create_branch_role_grant(
                actor_user_id=actors.owner_id,
                branch_id=branch.id,
                data=AgencyBranchRoleGrantCreateRequest(
                    membership_id=actors.advisor_two_membership_id,
                    role="travel_advisor",
                ),
                idempotency_key="advisor-two-grant",
            ),
        )
        create_request = AgencyCustomerCreateRequest(
            agency_id=actors.agency_id,
            branch_id=branch.id,
            source_type="staff_import",
            source_reference="opaque-import-row",
        )
        customer = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).create_customer(
                actor_user_id=actors.owner_id,
                data=create_request,
                idempotency_key="offline-customer",
            ),
        )
        replayed_customer = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).create_customer(
                actor_user_id=actors.owner_id,
                data=create_request,
                idempotency_key="offline-customer",
            ),
        )
        assert replayed_customer.id == customer.id
        assert customer.user_id is None
        assert customer.status == "prospect"
        assert customer.consent_status == "unknown"

        wrong_invitation, wrong_claim_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=1,
                target_user_id=actors.advisor_two_id,
                idempotency_key="issue-wrong-customer-claim",
            ),
        )
        assert wrong_claim_token is not None
        assert (wrong_invitation.status, wrong_invitation.revision) == (
            "pending",
            1,
        )
        with pytest.raises(AgencyTransactionNotFound):
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).get_customer(
                    actor_user_id=actors.advisor_two_id,
                    customer_id=customer.id,
                ),
            )
        revoked_invitation = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).revoke_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                invitation_id=wrong_invitation.id,
                expected_revision=1,
                expected_invitation_revision=1,
                reason="目标账户录入错误",
                idempotency_key="revoke-wrong-customer-claim",
            ),
        )
        assert (revoked_invitation.status, revoked_invitation.revision) == (
            "revoked",
            2,
        )
        invitation, claim_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=1,
                target_user_id=actors.customer_user_id,
                idempotency_key="issue-customer-claim",
            ),
        )
        assert claim_token is not None
        claimed = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).claim_customer(
                actor_user_id=actors.customer_user_id,
                claim_token=claim_token,
                idempotency_key="claim-customer",
            ),
        )
        assert (
            claimed.user_id,
            claimed.binding_provenance,
            claimed.status,
            claimed.lifecycle_revision,
        ) == (
            actors.customer_user_id,
            "secure_claim",
            "invited",
            2,
        )
        assert claimed.claimed_invitation_id == invitation.id
        with pytest.raises(AgencyTransactionConflict) as stale:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).record_customer_consent(
                    actor_user_id=actors.customer_user_id,
                    customer_id=customer.id,
                    expected_revision=1,
                    decision="grant",
                    expected_notice_version=CUSTOMER_CONSENT_VERSION,
                    expected_notice_document_sha256=(
                        CUSTOMER_CONSENT_DOCUMENT_SHA256
                    ),
                    idempotency_key="stale-consent",
                ),
            )
        assert stale.value.code == "transaction_revision_conflict"

        with pytest.raises(AgencyTransactionConflict) as changed_notice:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).record_customer_consent(
                    actor_user_id=actors.customer_user_id,
                    customer_id=customer.id,
                    expected_revision=2,
                    decision="grant",
                    expected_notice_version="stale-consent-notice.v0",
                    expected_notice_document_sha256=(
                        CUSTOMER_CONSENT_DOCUMENT_SHA256
                    ),
                    idempotency_key="stale-consent-notice",
                ),
            )
        assert changed_notice.value.code == "customer_consent_notice_changed"

        consented = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).record_customer_consent(
                actor_user_id=actors.customer_user_id,
                customer_id=customer.id,
                expected_revision=2,
                decision="grant",
                expected_notice_version=CUSTOMER_CONSENT_VERSION,
                expected_notice_document_sha256=(
                    CUSTOMER_CONSENT_DOCUMENT_SHA256
                ),
                idempotency_key="customer-consent",
            ),
        )
        activated = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).activate_customer(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=consented.lifecycle_revision,
                idempotency_key="activate-customer",
            ),
        )
        assignment_now = datetime(2030, 1, 1, tzinfo=UTC)

        def assignment_service(session):
            return CustomerLifecycleService(
                session,
                now_factory=lambda: assignment_now,
            )

        assignment_one = await _call(
            session_factory,
            lambda session: assignment_service(
                session
            ).assign_customer_advisor(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=activated.lifecycle_revision,
                advisor_role_grant_id=grant_one.id,
                reason=None,
                idempotency_key="assign-advisor-one",
            ),
        )
        assignment_replay = await _call(
            session_factory,
            lambda session: assignment_service(
                session
            ).assign_customer_advisor(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=activated.lifecycle_revision,
                advisor_role_grant_id=grant_one.id,
                reason=None,
                idempotency_key="assign-advisor-one",
            ),
        )
        assert assignment_replay.id == assignment_one.id
        with pytest.raises(AgencyTransactionConflict) as idem_conflict:
            await _call(
                session_factory,
                lambda session: assignment_service(
                    session
                ).assign_customer_advisor(
                    actor_user_id=actors.owner_id,
                    customer_id=customer.id,
                    expected_revision=activated.lifecycle_revision,
                    advisor_role_grant_id=grant_two.id,
                    reason="different payload",
                    idempotency_key="assign-advisor-one",
                ),
            )
        assert idem_conflict.value.code == "idempotency_key_conflict"

        reassigned = await _call(
            session_factory,
            lambda session: assignment_service(
                session
            ).assign_customer_advisor(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=activated.lifecycle_revision + 1,
                advisor_role_grant_id=grant_two.id,
                reason="顾问排班调整",
                idempotency_key="assign-advisor-two",
            ),
        )
        ended = await _call(
            session_factory,
            lambda session: assignment_service(
                session
            ).end_customer_advisor_assignment(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=6,
                reason="顾问离职且暂无接替人",
                idempotency_key="end-advisor-two",
            ),
        )
        ended_replay = await _call(
            session_factory,
            lambda session: assignment_service(
                session
            ).end_customer_advisor_assignment(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=6,
                reason="顾问离职且暂无接替人",
                idempotency_key="end-advisor-two",
            ),
        )
        assert ended_replay.id == ended.id
        async with session_factory() as session:
            stored_customer = await session.get(AgencyCustomer, customer.id)
            assignments = list(
                (
                    await session.execute(
                        select(AgencyCustomerAdvisorAssignment)
                        .where(
                            AgencyCustomerAdvisorAssignment.customer_id
                            == customer.id
                        )
                        .order_by(
                            AgencyCustomerAdvisorAssignment.assigned_at
                        )
                    )
                )
                .scalars()
                .all()
            )
            events = list(
                (
                    await session.execute(
                        select(AgencyCustomerEvent)
                        .where(AgencyCustomerEvent.customer_id == customer.id)
                        .order_by(AgencyCustomerEvent.event_sequence)
                    )
                )
                .scalars()
                .all()
            )
            consent_records = list(
                (
                    await session.execute(
                        select(AgencyCustomerConsentRecord)
                        .where(
                            AgencyCustomerConsentRecord.customer_id
                            == customer.id
                        )
                        .order_by(
                            AgencyCustomerConsentRecord.consent_sequence
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert stored_customer is not None
        assert (stored_customer.status, stored_customer.lifecycle_revision) == (
            "active",
            7,
        )
        assert reassigned.status == "active"
        assert [(item.status, item.ended_reason) for item in assignments] == [
            ("ended", "顾问排班调整"),
            ("ended", "顾问离职且暂无接替人"),
        ]
        assert [event.event_sequence for event in events] == list(
            range(1, len(events) + 1)
        )
        assert [event.event_type for event in events] == [
            "customer_created",
            "customer_claim_invitation_issued",
            "customer_claim_invitation_revoked",
            "customer_claim_invitation_issued",
            "customer_secure_claimed",
            "customer_consent_granted",
            "customer_activated",
            "customer_advisor_assigned",
            "customer_advisor_reassigned",
            "customer_advisor_unassigned",
        ]
        assert len(consent_records) == 1
        assert consent_records[0].evidence_origin == "server_canonical"
        assert (
            events[5].event_metadata["consent_evidence_hash"]
            == stored_customer.consent_evidence_hash
            == consent_records[0].evidence_hash
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_cross_branch_and_customer_user_misbinding(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_consent import (
        CUSTOMER_CONSENT_DOCUMENT_SHA256,
        CUSTOMER_CONSENT_VERSION,
    )
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.order_review_service import AgencyOrderReviewService
    from app.models.agency_customer_lifecycle import AgencyBranch
    from app.models.agency_transaction import AgencyQuote
    from app.models.user import User
    from app.schemas.agency_transaction import AgencyOrderCreateRequest

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        other_branch_id = uuid.uuid4()
        wrong_user_id = uuid.uuid4()
        unique = uuid.uuid4().hex
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    AgencyBranch(
                        id=other_branch_id,
                        agency_id=actors.agency_id,
                        branch_code="OTHER",
                        name="Other Branch",
                        status="active",
                        revision=1,
                    ),
                    User(
                        id=wrong_user_id,
                        username=f"wrong-{unique}",
                        email=f"wrong-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                ]
            )

        def invalid_quote(*, branch_id, user_id):
            quote_id = uuid.uuid4()
            return AgencyQuote(
                id=quote_id,
                quote_no=f"Q-{quote_id.hex[:20]}",
                idempotency_key=f"invalid-{quote_id.hex}",
                agency_id=actors.agency_id,
                branch_id=branch_id,
                customer_id=actors.customer_record_id,
                user_id=user_id,
                status="draft",
                revision=1,
                payload_hash="e" * 64,
                total_amount=Decimal("1.00"),
                currency="CNY",
                snapshot_version="agency_quote.v1",
                quote_snapshot={},
                valid_until=datetime.now(UTC) + timedelta(days=1),
            )

        with pytest.raises(DBAPIError):
            async with session_factory() as session, session.begin():
                session.add(
                    invalid_quote(
                        branch_id=other_branch_id,
                        user_id=actors.customer_user_id,
                    )
                )
                await session.flush()
        with pytest.raises(DBAPIError):
            async with session_factory() as session, session.begin():
                session.add(
                    invalid_quote(
                        branch_id=actors.branch_id,
                        user_id=wrong_user_id,
                    )
                )
                await session.flush()

        async def create_and_issue(session):
            service = AgencyOrderReviewService(session)
            quote = await service.create_quote(
                actor_user_id=actors.advisor_id,
                data=_quote_request(actors),
                idempotency_key=f"guard-quote-{uuid.uuid4().hex}",
            )
            return await service.issue_quote(
                actor_user_id=actors.advisor_id,
                quote_id=quote.id,
                expected_revision=quote.revision,
                idempotency_key=f"guard-issue-{uuid.uuid4().hex}",
            )

        offered_quote = await _call(session_factory, create_and_issue)
        with pytest.raises(DBAPIError) as unaccepted_order:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO agency_order ("
                        "id, order_no, agency_id, branch_id, customer_id, "
                        "quote_id, user_id, idempotency_key, status, revision, "
                        "payload_hash, payment_status, fulfillment_status, "
                        "total_amount, currency, quote_snapshot, "
                        "external_action_enabled, created_at, updated_at"
                        ") SELECT :id, :order_no, agency_id, branch_id, "
                        "customer_id, id, user_id, :key, 'draft', 1, :hash, "
                        "'not_started', 'not_started', total_amount, currency, "
                        "quote_snapshot, false, now(), now() "
                        "FROM agency_quote WHERE id = :quote_id"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "order_no": f"ORDER-GUARD-{uuid.uuid4().hex[:16]}",
                        "key": f"guard-order-{uuid.uuid4().hex}",
                        "hash": "a" * 64,
                        "quote_id": offered_quote.id,
                    },
                )
        assert (
            "new agency_order requires accepted valid matching agency_quote"
            in str(unaccepted_order.value.orig)
        )

        async def accept_and_create_order(session):
            service = AgencyOrderReviewService(session)
            accepted = await service.accept_quote(
                actor_user_id=actors.customer_user_id,
                quote_id=offered_quote.id,
                expected_revision=offered_quote.revision,
                idempotency_key=f"guard-accept-{uuid.uuid4().hex}",
            )
            return await service.create_order(
                actor_user_id=actors.customer_user_id,
                data=AgencyOrderCreateRequest(
                    agency_id=actors.agency_id,
                    quote_id=accepted.id,
                    expected_quote_revision=accepted.revision,
                ),
                idempotency_key=f"guard-create-order-{uuid.uuid4().hex}",
            )

        order = await _call(session_factory, accept_and_create_order)
        with pytest.raises(DBAPIError) as ordered_quote_cancel:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_quote SET status = 'cancelled', "
                        "revision = revision + 1, updated_at = now() "
                        "WHERE id = :quote_id"
                    ),
                    {"quote_id": offered_quote.id},
                )
        assert "invalid agency_quote status transition" in str(
            ordered_quote_cancel.value.orig
        )

        submitted = await _call(
            session_factory,
            lambda session: AgencyOrderReviewService(session).submit_order(
                actor_user_id=actors.customer_user_id,
                order_id=order.id,
                expected_revision=order.revision,
                idempotency_key=f"guard-submit-{uuid.uuid4().hex}",
            ),
        )
        with pytest.raises(DBAPIError) as order_without_review_decision:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_order SET status = 'approved', "
                        "revision = revision + 1, updated_at = now() "
                        "WHERE id = :order_id"
                    ),
                    {"order_id": submitted.id},
                )
        assert "agency_order requires matching final review state" in str(
            order_without_review_decision.value.orig
        )

        with pytest.raises(DBAPIError) as review_without_order_decision:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_order_review SET status = 'approved', "
                        "decision_order_revision = order_revision + 1, "
                        "decided_by_user_id = :approver_id, "
                        "decided_at = now(), updated_at = now() "
                        "WHERE order_id = :order_id"
                    ),
                    {
                        "approver_id": actors.approver_id,
                        "order_id": submitted.id,
                    },
                )
        assert "terminal agency_order_review does not match order" in str(
            review_without_order_decision.value.orig
        )

        deactivated = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).deactivate_customer(
                actor_user_id=actors.customer_user_id,
                customer_id=actors.customer_record_id,
                expected_revision=3,
                reason="客户撤回待审核订单",
                idempotency_key=f"guard-deactivate-{uuid.uuid4().hex}",
            ),
        )
        assert deactivated.status == "inactive"
        reconsented = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).record_customer_consent(
                actor_user_id=actors.customer_user_id,
                customer_id=actors.customer_record_id,
                expected_revision=deactivated.lifecycle_revision,
                decision="grant",
                expected_notice_version=CUSTOMER_CONSENT_VERSION,
                expected_notice_document_sha256=(
                    CUSTOMER_CONSENT_DOCUMENT_SHA256
                ),
                idempotency_key=f"guard-reconsent-{uuid.uuid4().hex}",
            ),
        )
        with pytest.raises(DBAPIError) as stale_review_reactivation:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer SET status = 'active', "
                        "activated_at = now(), deactivated_at = NULL, "
                        "lifecycle_revision = lifecycle_revision + 1 "
                        "WHERE id = :customer_id"
                    ),
                    {"customer_id": actors.customer_record_id},
                )
        assert (
            "pending customer order review must be rejected before reactivation"
            in str(stale_review_reactivation.value.orig)
        )
        assert reconsented.status == "inactive"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_illegal_branch_role_and_fake_active_customer(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.models.agency_customer_lifecycle import AgencyBranchRoleGrant
    from app.models.agency_transaction import AgencyCustomer, AgencyMembership
    from app.models.user import User

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        owner_id = uuid.uuid4()
        owner_membership_id = uuid.uuid4()
        unconsented_user_id = uuid.uuid4()
        unique = uuid.uuid4().hex
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    User(
                        id=owner_id,
                        username=f"owner-{unique}",
                        email=f"owner-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                    User(
                        id=unconsented_user_id,
                        username=f"unconsented-{unique}",
                        email=f"unconsented-{unique}@example.test",
                        password_hash="integration-test-only",
                    ),
                ]
            )
            await session.flush()
            session.add(
                AgencyMembership(
                    id=owner_membership_id,
                    agency_id=actors.agency_id,
                    user_id=owner_id,
                    role="owner",
                    status="active",
                    joined_at=datetime.now(UTC),
                )
            )

        with pytest.raises(IntegrityError):
            async with session_factory() as session, session.begin():
                session.add(
                    AgencyBranchRoleGrant(
                        agency_id=actors.agency_id,
                        branch_id=actors.branch_id,
                        membership_id=owner_membership_id,
                        role="owner",
                        status="active",
                        revision=1,
                        granted_at=datetime.now(UTC),
                    )
                )
                await session.flush()

        with pytest.raises(DBAPIError):
            async with session_factory() as session, session.begin():
                session.add(
                    AgencyCustomer(
                        agency_id=actors.agency_id,
                        branch_id=actors.branch_id,
                        customer_no=f"CUST-{uuid.uuid4().hex[:20]}",
                        user_id=unconsented_user_id,
                        source_type="registered_user",
                        status="active",
                        consent_status="unknown",
                        lifecycle_revision=1,
                        invited_at=datetime.now(UTC),
                        activated_at=datetime.now(UTC),
                    )
                )
                await session.flush()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_customer_event_is_append_only_and_customer_binding_is_immutable(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.models.agency_customer_lifecycle import AgencyCustomerEvent

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors = await _seed_tenant(session_factory)
        event_id = uuid.uuid4()
        async with session_factory() as session, session.begin():
            session.add(
                AgencyCustomerEvent(
                    id=event_id,
                    agency_id=actors.agency_id,
                    branch_id=actors.branch_id,
                    customer_id=actors.customer_record_id,
                    event_sequence=1,
                    customer_revision=1,
                    event_type="integration_seeded",
                    from_status=None,
                    to_status="active",
                    actor_user_id=actors.advisor_id,
                    event_metadata={},
                )
            )

        for statement in (
            "UPDATE agency_customer_event "
            "SET event_type = 'tampered' WHERE id = :id",
            "DELETE FROM agency_customer_event WHERE id = :id",
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(statement),
                        {"id": event_id},
                    )

        with pytest.raises(DBAPIError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer SET user_id = NULL, "
                        "lifecycle_revision = lifecycle_revision + 1 "
                        "WHERE id = :id"
                    ),
                    {"id": actors.customer_record_id},
                )
    finally:
        await engine.dispose()
