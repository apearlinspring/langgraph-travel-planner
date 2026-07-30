"""PostgreSQL integration checks for secure customer claim and consent evidence."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.test_agency_transaction_postgres_integration import (
    PostgresSandbox,
    _seed_lifecycle_actors,
    _session_factory,
    migrated_postgres,
    postgres_schema,
)


pytestmark = [pytest.mark.integration, pytest.mark.slow]


@dataclass(frozen=True)
class LegacyCustomerActors:
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    owner_id: uuid.UUID
    customer_user_id: uuid.UUID
    customer_id: uuid.UUID


async def _call(session_factory, operation):
    async with session_factory() as session:
        async with session.begin():
            return await operation(session)


async def _create_prospect(session_factory):
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.schemas.agency_customer_lifecycle import (
        AgencyBranchCreateRequest,
        AgencyCustomerCreateRequest,
    )

    actors = await _seed_lifecycle_actors(session_factory)
    unique = uuid.uuid4().hex
    branch = await _call(
        session_factory,
        lambda session: CustomerLifecycleService(session).create_branch(
            actor_user_id=actors.owner_id,
            data=AgencyBranchCreateRequest(
                agency_id=actors.agency_id,
                branch_code=f"CLAIM-{unique[:12]}",
                name="安全认领集成测试门店",
            ),
            idempotency_key=f"claim-branch-{unique}",
        ),
    )
    customer = await _call(
        session_factory,
        lambda session: CustomerLifecycleService(session).create_customer(
            actor_user_id=actors.owner_id,
            data=AgencyCustomerCreateRequest(
                agency_id=actors.agency_id,
                branch_id=branch.id,
                source_type="manual",
                source_reference=f"claim-test-{unique}",
            ),
            idempotency_key=f"claim-customer-{unique}",
        ),
    )
    return actors, branch, customer


def _seed_active_legacy_customer(
    postgres_schema: PostgresSandbox,
) -> LegacyCustomerActors:
    """Create a real 0004 active row, then let 0005 classify it as legacy."""

    command.upgrade(postgres_schema.alembic_config, "20260726_0004")
    ids = LegacyCustomerActors(
        agency_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        customer_user_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
    )
    owner_membership_id = uuid.uuid4()
    unique = uuid.uuid4().hex
    now = datetime.now(UTC)
    engine = create_engine(postgres_schema.sync_url)
    try:
        with engine.begin() as connection:
            for user_id, role in (
                (ids.owner_id, "owner"),
                (ids.customer_user_id, "customer"),
            ):
                connection.execute(
                    text(
                        'INSERT INTO "user" '
                        "(id, username, email, password_hash, preferences, "
                        "created_at, updated_at) "
                        "VALUES (:id, :username, :email, 'test-only', NULL, "
                        ":now, :now)"
                    ),
                    {
                        "id": user_id,
                        "username": f"legacy-{role}-{unique}",
                        "email": f"legacy-{role}-{unique}@example.test",
                        "now": now,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO agency "
                    "(id, agency_code, name, status, created_at, updated_at) "
                    "VALUES (:id, :code, 'Legacy Claim Agency', 'active', "
                    ":now, :now)"
                ),
                {
                    "id": ids.agency_id,
                    "code": f"LEGACY-CLAIM-{unique[:12]}",
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_membership "
                    "(id, agency_id, user_id, role, status, joined_at, "
                    "created_at, updated_at) "
                    "VALUES (:id, :agency_id, :user_id, 'owner', 'active', "
                    ":now, :now, :now)"
                ),
                {
                    "id": owner_membership_id,
                    "agency_id": ids.agency_id,
                    "user_id": ids.owner_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_branch "
                    "(id, agency_id, branch_code, name, status, revision, "
                    "deactivated_at, created_at, updated_at) "
                    "VALUES (:id, :agency_id, 'LEGACY', 'Legacy Branch', "
                    "'active', 1, NULL, :now, :now)"
                ),
                {
                    "id": ids.branch_id,
                    "agency_id": ids.agency_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agency_customer "
                    "(id, agency_id, branch_id, customer_no, user_id, "
                    "source_type, source_reference, status, consent_status, "
                    "consent_version, consent_evidence_hash, "
                    "consent_updated_at, lifecycle_revision, invited_at, "
                    "activated_at, deactivated_at, created_at, updated_at) "
                    "VALUES (:id, :agency_id, :branch_id, :customer_no, "
                    ":user_id, 'legacy_test', 'migration-test', 'active', "
                    "'granted', 'legacy-consent.v1', :evidence_hash, :now, "
                    "1, :now, :now, NULL, :now, :now)"
                ),
                {
                    "id": ids.customer_id,
                    "agency_id": ids.agency_id,
                    "branch_id": ids.branch_id,
                    "customer_no": f"LEGACY-{unique[:20]}",
                    "user_id": ids.customer_user_id,
                    "evidence_hash": "c" * 64,
                    "now": now,
                },
            )
    finally:
        engine.dispose()

    command.upgrade(postgres_schema.alembic_config, "head")
    return ids


@pytest.mark.asyncio
async def test_target_has_only_one_pending_invitation_per_agency(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_claim_tokens import hash_claim_token
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import AgencyTransactionConflict
    from app.models.agency_customer_identity import AgencyCustomerInvitation
    from app.schemas.agency_customer_lifecycle import (
        AgencyBranchCreateRequest,
        AgencyCustomerCreateRequest,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors, _, first_customer = await _create_prospect(session_factory)
        unique = uuid.uuid4().hex
        second_branch = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).create_branch(
                actor_user_id=actors.owner_id,
                data=AgencyBranchCreateRequest(
                    agency_id=actors.agency_id,
                    branch_code=f"CLAIM-B-{unique[:10]}",
                    name="安全认领第二门店",
                ),
                idempotency_key=f"claim-second-branch-{unique}",
            ),
        )
        second_customer = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).create_customer(
                actor_user_id=actors.owner_id,
                data=AgencyCustomerCreateRequest(
                    agency_id=actors.agency_id,
                    branch_id=second_branch.id,
                    source_type="manual",
                    source_reference=f"claim-second-{unique}",
                ),
                idempotency_key=f"claim-second-customer-{unique}",
            ),
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=first_customer.id,
                expected_revision=1,
                target_user_id=actors.customer_user_id,
                idempotency_key=f"claim-first-target-{unique}",
            ),
        )

        with pytest.raises(AgencyTransactionConflict) as unavailable:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).issue_customer_claim_invitation(
                    actor_user_id=actors.owner_id,
                    customer_id=second_customer.id,
                    expected_revision=1,
                    target_user_id=actors.customer_user_id,
                    idempotency_key=f"claim-second-target-{unique}",
                ),
            )
        assert unavailable.value.code == "customer_claim_target_unavailable"

        async with session_factory() as session:
            pending_count = (
                await session.execute(
                    select(func.count())
                    .select_from(AgencyCustomerInvitation)
                    .where(
                        AgencyCustomerInvitation.agency_id
                        == actors.agency_id
                    )
                    .where(
                        AgencyCustomerInvitation.target_user_id
                        == actors.customer_user_id
                    )
                    .where(AgencyCustomerInvitation.status == "pending")
                )
            ).scalar_one()
        assert pending_count == 1

        now = datetime.now(UTC)
        with pytest.raises(IntegrityError) as direct_duplicate:
            async with session_factory() as session, session.begin():
                session.add(
                    AgencyCustomerInvitation(
                        agency_id=actors.agency_id,
                        branch_id=second_branch.id,
                        customer_id=second_customer.id,
                        target_user_id=actors.customer_user_id,
                        token_digest=hash_claim_token(
                            f"direct-duplicate-{unique}"
                        ),
                        status="pending",
                        revision=1,
                        issued_by_user_id=actors.owner_id,
                        issued_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                )
                await session.flush()
        assert (
            "uq_agency_customer_invitation_target_pending"
            in str(direct_duplicate.value.orig)
        )
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "revoke_before_claim",
    [False, True],
    ids=["active-legacy-claim", "legacy-revoke-claim-grant"],
)
@pytest.mark.asyncio
async def test_legacy_claim_resets_consent_before_new_grant(
    postgres_schema: PostgresSandbox,
    revoke_before_claim: bool,
) -> None:
    from app.agency.customer_consent import (
        CUSTOMER_CONSENT_DOCUMENT_SHA256,
        CUSTOMER_CONSENT_VERSION,
    )
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.models.agency_customer_identity import (
        AgencyCustomerConsentRecord,
    )
    from app.models.agency_customer_lifecycle import AgencyCustomer

    actors = _seed_active_legacy_customer(postgres_schema)
    engine, session_factory = _session_factory(postgres_schema)
    try:
        async with session_factory() as session:
            migrated = await session.get(AgencyCustomer, actors.customer_id)
        assert migrated is not None
        assert (
            migrated.status,
            migrated.binding_provenance,
            migrated.consent_status,
            migrated.consent_evidence_origin,
            migrated.lifecycle_revision,
        ) == (
            "active",
            "legacy_direct",
            "granted",
            "legacy_client_hash",
            1,
        )
        assert migrated.current_consent_record_id == actors.customer_id

        customer_revision = migrated.lifecycle_revision
        expected_old_record_count = 1
        if revoke_before_claim:
            revoked = await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).record_customer_consent(
                    actor_user_id=actors.customer_user_id,
                    customer_id=actors.customer_id,
                    expected_revision=customer_revision,
                    decision="revoke",
                    expected_notice_version=CUSTOMER_CONSENT_VERSION,
                    expected_notice_document_sha256=(
                        CUSTOMER_CONSENT_DOCUMENT_SHA256
                    ),
                    idempotency_key="legacy-claim-revoke",
                ),
            )
            assert (
                revoked.status,
                revoked.consent_status,
                revoked.binding_provenance,
                revoked.consent_evidence_origin,
                revoked.lifecycle_revision,
            ) == (
                "inactive",
                "revoked",
                "legacy_direct",
                "server_canonical",
                2,
            )
            customer_revision = revoked.lifecycle_revision
            expected_old_record_count = 2

        invitation, claim_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=actors.customer_id,
                expected_revision=customer_revision,
                target_user_id=actors.customer_user_id,
                idempotency_key="legacy-claim-issue",
            ),
        )
        assert claim_token is not None
        claimed = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).claim_customer(
                actor_user_id=actors.customer_user_id,
                claim_token=claim_token,
                idempotency_key="legacy-claim-complete",
            ),
        )
        assert (
            claimed.status,
            claimed.binding_provenance,
            claimed.claimed_invitation_id,
            claimed.consent_status,
            claimed.consent_version,
            claimed.consent_evidence_hash,
            claimed.current_consent_record_id,
            claimed.consent_evidence_origin,
        ) == (
            "inactive",
            "secure_claim",
            invitation.id,
            "unknown",
            None,
            None,
            None,
            "none",
        )
        assert claimed.lifecycle_revision == customer_revision + 1
        assert claimed.deactivated_at is not None

        async with session_factory() as session:
            old_records = list(
                (
                    await session.execute(
                        select(AgencyCustomerConsentRecord)
                        .where(
                            AgencyCustomerConsentRecord.customer_id
                            == actors.customer_id
                        )
                        .order_by(
                            AgencyCustomerConsentRecord.consent_sequence
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(old_records) == expected_old_record_count
        assert old_records[0].evidence_origin == "legacy_client_hash"
        if revoke_before_claim:
            assert (
                old_records[-1].decision,
                old_records[-1].evidence_origin,
            ) == ("revoked", "server_canonical")

        granted = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).record_customer_consent(
                actor_user_id=actors.customer_user_id,
                customer_id=actors.customer_id,
                expected_revision=claimed.lifecycle_revision,
                decision="grant",
                expected_notice_version=CUSTOMER_CONSENT_VERSION,
                expected_notice_document_sha256=(
                    CUSTOMER_CONSENT_DOCUMENT_SHA256
                ),
                idempotency_key="legacy-claim-new-grant",
            ),
        )
        activated = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).activate_customer(
                actor_user_id=actors.owner_id,
                customer_id=actors.customer_id,
                expected_revision=granted.lifecycle_revision,
                idempotency_key="legacy-claim-reactivate",
            ),
        )
        assert (
            activated.status,
            activated.binding_provenance,
            activated.consent_status,
            activated.consent_evidence_origin,
        ) == (
            "active",
            "secure_claim",
            "granted",
            "server_canonical",
        )
        expected_final_revision = 5 if revoke_before_claim else 4
        assert activated.lifecycle_revision == expected_final_revision
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_claim_token_digest_revocation_expiry_and_single_use(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_claim_tokens import hash_claim_token
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.agency.errors import AgencyTransactionConflict
    from app.models.agency_customer_identity import AgencyCustomerInvitation
    from app.models.agency_customer_lifecycle import AgencyCustomer

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors, _, customer = await _create_prospect(session_factory)
        first_invitation, first_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=1,
                target_user_id=actors.customer_user_id,
                idempotency_key="claim-pg-first-issue",
            ),
        )
        assert first_token is not None

        async with session_factory() as session:
            stored_invitation = await session.get(
                AgencyCustomerInvitation,
                first_invitation.id,
            )
            column_names = set(
                (
                    await session.execute(
                        text(
                            "SELECT column_name "
                            "FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name = 'agency_customer_invitation'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert stored_invitation is not None
        assert stored_invitation.token_digest == hash_claim_token(first_token)
        assert first_token != stored_invitation.token_digest
        assert {"claim_token", "raw_token", "token_secret"}.isdisjoint(
            column_names
        )

        for actor_user_id, claim_token, key in (
            (
                actors.customer_user_id,
                f"{first_token}-invalid",
                "claim-pg-invalid-token",
            ),
            (
                actors.advisor_one_id,
                first_token,
                "claim-pg-wrong-target",
            ),
        ):
            with pytest.raises(AgencyTransactionConflict) as unavailable:
                await _call(
                    session_factory,
                    lambda session,
                    actor_user_id=actor_user_id,
                    claim_token=claim_token,
                    key=key: CustomerLifecycleService(
                        session
                    ).claim_customer(
                        actor_user_id=actor_user_id,
                        claim_token=claim_token,
                        idempotency_key=key,
                    ),
                )
            assert unavailable.value.code == "customer_claim_unavailable"

        revoked_first = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).revoke_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                invitation_id=first_invitation.id,
                expected_revision=1,
                expected_invitation_revision=1,
                reason="首个邀请主动撤销",
                idempotency_key="claim-pg-first-revoke",
            ),
        )
        assert (revoked_first.status, revoked_first.revision) == (
            "revoked",
            2,
        )
        with pytest.raises(AgencyTransactionConflict) as revoked:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).claim_customer(
                    actor_user_id=actors.customer_user_id,
                    claim_token=first_token,
                    idempotency_key="claim-pg-revoked-token",
                ),
            )
        assert revoked.value.code == "customer_claim_unavailable"

        issued_in_past = datetime.now(UTC) - timedelta(days=2)
        expired_invitation, expired_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session,
                now_factory=lambda: issued_in_past,
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=1,
                target_user_id=actors.customer_user_id,
                idempotency_key="claim-pg-expired-issue",
            ),
        )
        assert expired_token is not None
        with pytest.raises(AgencyTransactionConflict) as expired:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).claim_customer(
                    actor_user_id=actors.customer_user_id,
                    claim_token=expired_token,
                    idempotency_key="claim-pg-expired-token",
                ),
            )
        assert expired.value.code == "customer_claim_unavailable"

        with pytest.raises(DBAPIError) as expired_direct_claim:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer_invitation "
                        "SET status = 'claimed', revision = revision + 1, "
                        "claimed_by_user_id = target_user_id, "
                        "claimed_at = issued_at, updated_at = now() "
                        "WHERE id = :invitation_id"
                    ),
                    {"invitation_id": expired_invitation.id},
                )
        assert (
            "expired agency_customer_invitation cannot be claimed"
            in str(expired_direct_claim.value.orig)
        )
        await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).revoke_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                invitation_id=expired_invitation.id,
                expected_revision=1,
                expected_invitation_revision=1,
                reason="过期邀请归档",
                idempotency_key="claim-pg-expired-revoke",
            ),
        )

        final_invitation, final_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=1,
                target_user_id=actors.customer_user_id,
                idempotency_key="claim-pg-final-issue",
            ),
        )
        assert final_token is not None
        claimed = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).claim_customer(
                actor_user_id=actors.customer_user_id,
                claim_token=final_token,
                idempotency_key="claim-pg-final-claim",
            ),
        )
        replayed = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).claim_customer(
                actor_user_id=actors.customer_user_id,
                claim_token=final_token,
                idempotency_key="claim-pg-final-claim",
            ),
        )
        assert replayed.id == claimed.id
        with pytest.raises(AgencyTransactionConflict) as reused:
            await _call(
                session_factory,
                lambda session: CustomerLifecycleService(
                    session
                ).claim_customer(
                    actor_user_id=actors.customer_user_id,
                    claim_token=final_token,
                    idempotency_key="claim-pg-final-claim-reused",
                ),
            )
        assert reused.value.code == "customer_claim_unavailable"

        async with session_factory() as session:
            stored_customer = await session.get(AgencyCustomer, customer.id)
            invitations = list(
                (
                    await session.execute(
                        select(AgencyCustomerInvitation)
                        .where(
                            AgencyCustomerInvitation.customer_id
                            == customer.id
                        )
                        .order_by(AgencyCustomerInvitation.issued_at)
                    )
                )
                .scalars()
                .all()
            )
        assert stored_customer is not None
        assert (
            stored_customer.user_id,
            stored_customer.binding_provenance,
            stored_customer.claimed_invitation_id,
            stored_customer.lifecycle_revision,
        ) == (
            actors.customer_user_id,
            "secure_claim",
            final_invitation.id,
            2,
        )
        assert [(item.status, item.revision) for item in invitations] == [
            ("revoked", 2),
            ("revoked", 2),
            ("claimed", 2),
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_direct_binding_and_consent_record_tampering(
    migrated_postgres: PostgresSandbox,
) -> None:
    from app.agency.customer_consent import (
        CUSTOMER_CONSENT_DOCUMENT_SHA256,
        CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
        CUSTOMER_CONSENT_VERSION,
    )
    from app.agency.customer_lifecycle_service import CustomerLifecycleService
    from app.models.agency_customer_identity import (
        AgencyCustomerConsentRecord,
    )
    from app.schemas.agency_customer_lifecycle import (
        AgencyCustomerCreateRequest,
    )

    engine, session_factory = _session_factory(migrated_postgres)
    try:
        actors, branch, customer = await _create_prospect(session_factory)
        invitation, claim_token = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).issue_customer_claim_invitation(
                actor_user_id=actors.owner_id,
                customer_id=customer.id,
                expected_revision=1,
                target_user_id=actors.customer_user_id,
                idempotency_key="claim-pg-guard-issue",
            ),
        )
        assert claim_token is not None
        claimed = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(session).claim_customer(
                actor_user_id=actors.customer_user_id,
                claim_token=claim_token,
                idempotency_key="claim-pg-guard-claim",
            ),
        )

        with pytest.raises(DBAPIError) as forged_projection:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer "
                        "SET consent_status = 'granted', "
                        "consent_version = 'forged.v1', "
                        "consent_evidence_hash = :evidence_hash, "
                        "current_consent_record_id = :record_id, "
                        "consent_evidence_origin = 'server_canonical', "
                        "consent_updated_at = now(), "
                        "lifecycle_revision = lifecycle_revision + 1 "
                        "WHERE id = :customer_id"
                    ),
                    {
                        "customer_id": customer.id,
                        "record_id": uuid.uuid4(),
                        "evidence_hash": "a" * 64,
                    },
                )
        assert any(
            message in str(forged_projection.value.orig)
            for message in (
                "server consent snapshot must match current record",
                "fk_agency_customer_current_consent_record",
            )
        )

        consented = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).record_customer_consent(
                actor_user_id=actors.customer_user_id,
                customer_id=customer.id,
                expected_revision=claimed.lifecycle_revision,
                decision="grant",
                expected_notice_version=CUSTOMER_CONSENT_VERSION,
                expected_notice_document_sha256=(
                    CUSTOMER_CONSENT_DOCUMENT_SHA256
                ),
                idempotency_key="claim-pg-guard-consent",
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
                idempotency_key="claim-pg-guard-activate",
            ),
        )
        assert (activated.status, activated.lifecycle_revision) == (
            "active",
            4,
        )

        async with session_factory() as session:
            record = (
                await session.execute(
                    select(AgencyCustomerConsentRecord).where(
                        AgencyCustomerConsentRecord.id
                        == activated.current_consent_record_id
                    )
                )
            ).scalar_one()
        assert record.invitation_id == invitation.id
        assert record.consent_version == CUSTOMER_CONSENT_VERSION
        assert (
            record.consent_document_hash
            == CUSTOMER_CONSENT_DOCUMENT_SHA256
        )
        assert record.evidence_schema_version == CUSTOMER_CONSENT_EVIDENCE_SCHEMA
        assert record.evidence_origin == "server_canonical"
        assert record.evidence_hash == activated.consent_evidence_hash

        for statement, parameters in (
            (
                "UPDATE agency_customer_consent_record "
                "SET evidence_hash = :evidence_hash WHERE id = :record_id",
                {"record_id": record.id, "evidence_hash": "b" * 64},
            ),
            (
                "DELETE FROM agency_customer_consent_record "
                "WHERE id = :record_id",
                {"record_id": record.id},
            ),
        ):
            with pytest.raises(DBAPIError) as append_only:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(statement),
                        parameters,
                    )
            assert (
                "agency_customer_consent_record is append-only"
                in str(append_only.value.orig)
            )

        second_customer = await _call(
            session_factory,
            lambda session: CustomerLifecycleService(
                session
            ).create_customer(
                actor_user_id=actors.owner_id,
                data=AgencyCustomerCreateRequest(
                    agency_id=actors.agency_id,
                    branch_id=branch.id,
                    source_type="manual",
                    source_reference="direct-binding-guard",
                ),
                idempotency_key="claim-pg-direct-binding-customer",
            ),
        )
        with pytest.raises(DBAPIError) as direct_binding:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE agency_customer "
                        "SET user_id = :user_id, status = 'invited', "
                        "binding_provenance = 'legacy_direct', "
                        "lifecycle_revision = lifecycle_revision + 1 "
                        "WHERE id = :customer_id"
                    ),
                    {
                        "customer_id": second_customer.id,
                        "user_id": actors.advisor_two_id,
                    },
                )
        assert (
            "new direct agency_customer binding is forbidden"
            in str(direct_binding.value.orig)
        )
    finally:
        await engine.dispose()
