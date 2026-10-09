from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agency.customer_claim_tokens import hash_claim_token
from app.agency.customer_consent import (
    CUSTOMER_CONSENT_DOCUMENT_SHA256,
    CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
    CUSTOMER_CONSENT_NOTICE_MARKDOWN,
    CUSTOMER_CONSENT_VERSION,
    build_customer_consent_evidence,
)
from app.agency.errors import AgencyTransactionConflict
from app.agency.customer_lifecycle_service import CustomerLifecycleService
from app.agency.transaction_service import IdempotencyState


NOW = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
AGENCY_ID = uuid.UUID(int=1)
BRANCH_ID = uuid.UUID(int=2)
CUSTOMER_ID = uuid.UUID(int=3)
TARGET_USER_ID = uuid.UUID(int=4)
MANAGER_USER_ID = uuid.UUID(int=5)
INVITATION_ID = uuid.UUID(int=6)
CONSENT_RECORD_ID = uuid.UUID(int=7)
RAW_TOKEN = "claim-token-with-32-bytes-of-test-entropy"


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def one_or_none(self):
        return self.value


class _SequenceDb:
    def __init__(self, *values):
        self.values = list(values)
        self.added = []
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.values.pop(0))

    def add(self, resource):
        if getattr(resource, "id", None) is None:
            resource.id = (
                INVITATION_ID
                if resource.__class__.__name__ == "AgencyCustomerInvitation"
                else CONSENT_RECORD_ID
            )
        self.added.append(resource)


def _customer(**overrides):
    values = {
        "id": CUSTOMER_ID,
        "agency_id": AGENCY_ID,
        "branch_id": BRANCH_ID,
        "user_id": None,
        "status": "prospect",
        "binding_provenance": "unbound",
        "claimed_invitation_id": None,
        "claimed_at": None,
        "consent_status": "unknown",
        "consent_version": None,
        "consent_evidence_hash": None,
        "current_consent_record_id": None,
        "consent_evidence_origin": "none",
        "consent_updated_at": None,
        "lifecycle_revision": 1,
        "activated_at": None,
        "deactivated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _idempotency_state() -> IdempotencyState:
    return IdempotencyState(
        record=SimpleNamespace(
            status="in_progress",
            resource_type=None,
            resource_id=None,
        ),
        replayed=False,
    )


@pytest.mark.asyncio
async def test_invitation_issue_returns_raw_token_once_but_persists_only_digest(
    monkeypatch: pytest.MonkeyPatch,
):
    customer = _customer()
    db = _SequenceDb(TARGET_USER_ID, None, None, None)
    service = CustomerLifecycleService(db, now_factory=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "app.agency.customer_claim_service.generate_claim_token",
        lambda: RAW_TOKEN,
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
        AsyncMock(return_value=_idempotency_state()),
    )
    monkeypatch.setattr(service, "_flush", AsyncMock())
    append_event = AsyncMock()
    monkeypatch.setattr(service, "_append_customer_event", append_event)

    invitation, returned_token = (
        await service.issue_customer_claim_invitation(
            actor_user_id=MANAGER_USER_ID,
            customer_id=CUSTOMER_ID,
            expected_revision=1,
            target_user_id=TARGET_USER_ID,
            idempotency_key="issue-claim",
        )
    )

    assert returned_token == RAW_TOKEN
    assert invitation.token_digest == hash_claim_token(RAW_TOKEN)
    assert RAW_TOKEN not in repr(invitation.__dict__)
    metadata = append_event.await_args.kwargs["event_metadata"]
    assert RAW_TOKEN not in repr(metadata)
    assert invitation.token_digest not in repr(metadata)
    assert TARGET_USER_ID.hex not in repr(metadata)


@pytest.mark.asyncio
async def test_claim_binds_only_the_authenticated_invitation_target(
    monkeypatch: pytest.MonkeyPatch,
):
    digest = hash_claim_token(RAW_TOKEN)
    invitation = SimpleNamespace(
        id=INVITATION_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=CUSTOMER_ID,
        target_user_id=TARGET_USER_ID,
        token_digest=digest,
        status="pending",
        revision=1,
        claimed_by_user_id=None,
        claimed_at=None,
        expires_at=NOW + timedelta(hours=1),
    )
    preview = SimpleNamespace(
        id=INVITATION_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=CUSTOMER_ID,
    )
    db = _SequenceDb(preview, TARGET_USER_ID, invitation, None)
    customer = _customer()
    service = CustomerLifecycleService(db, now_factory=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service.authorization,
        "lock_active_branch_scope",
        AsyncMock(),
    )
    begin_action = AsyncMock(return_value=_idempotency_state())
    monkeypatch.setattr(service, "_begin_idempotent_action", begin_action)
    monkeypatch.setattr(service, "_flush", AsyncMock())
    append_event = AsyncMock()
    monkeypatch.setattr(service, "_append_customer_event", append_event)

    result = await service.claim_customer(
        actor_user_id=TARGET_USER_ID,
        claim_token=RAW_TOKEN,
        idempotency_key="claim-customer",
    )

    assert result is customer
    assert invitation.status == "claimed"
    assert invitation.claimed_by_user_id == TARGET_USER_ID
    assert customer.user_id == TARGET_USER_ID
    assert customer.binding_provenance == "secure_claim"
    assert customer.claimed_invitation_id == INVITATION_ID
    assert customer.status == "invited"
    request_payload = begin_action.await_args.kwargs["request_payload"]
    assert request_payload["claim_token_digest"] == digest
    assert RAW_TOKEN not in repr(request_payload)
    assert digest not in repr(append_event.await_args.kwargs["event_metadata"])


@pytest.mark.asyncio
async def test_legacy_active_claim_resets_consent_and_settles_relationship(
    monkeypatch: pytest.MonkeyPatch,
):
    digest = hash_claim_token(RAW_TOKEN)
    invitation = SimpleNamespace(
        id=INVITATION_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=CUSTOMER_ID,
        target_user_id=TARGET_USER_ID,
        token_digest=digest,
        status="pending",
        revision=1,
        claimed_by_user_id=None,
        claimed_at=None,
        expires_at=NOW + timedelta(hours=1),
    )
    preview = SimpleNamespace(
        id=INVITATION_ID,
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=CUSTOMER_ID,
    )
    customer = _customer(
        user_id=TARGET_USER_ID,
        status="active",
        binding_provenance="legacy_direct",
        consent_status="granted",
        consent_version="legacy.v1",
        consent_evidence_hash="a" * 64,
        current_consent_record_id=uuid.UUID(int=8),
        consent_evidence_origin="legacy_client_hash",
        consent_updated_at=NOW,
        activated_at=NOW,
    )
    db = _SequenceDb(preview, TARGET_USER_ID, invitation, None)
    service = CustomerLifecycleService(db, now_factory=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_get_customer",
        AsyncMock(return_value=customer),
    )
    monkeypatch.setattr(
        service.authorization,
        "lock_active_branch_scope",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service,
        "_begin_idempotent_action",
        AsyncMock(return_value=_idempotency_state()),
    )
    monkeypatch.setattr(service, "_flush", AsyncMock())
    ended_assignment = SimpleNamespace(id=uuid.UUID(int=9))
    end_assignment = AsyncMock(return_value=ended_assignment)
    settle_transactions = AsyncMock(return_value={"cancelled_order_count": 1})
    monkeypatch.setattr(service, "_end_active_assignment", end_assignment)
    monkeypatch.setattr(
        service,
        "_settle_customer_transactions",
        settle_transactions,
    )
    append_event = AsyncMock()
    monkeypatch.setattr(service, "_append_customer_event", append_event)

    result = await service.claim_customer(
        actor_user_id=TARGET_USER_ID,
        claim_token=RAW_TOKEN,
        idempotency_key="legacy-secure-claim",
    )

    assert result.status == "inactive"
    assert result.binding_provenance == "secure_claim"
    assert result.consent_status == "unknown"
    assert result.consent_version is None
    assert result.consent_evidence_hash is None
    assert result.current_consent_record_id is None
    assert result.consent_evidence_origin == "none"
    assert result.consent_updated_at is None
    assert result.deactivated_at == NOW
    end_assignment.assert_awaited_once()
    settle_transactions.assert_awaited_once()
    metadata = append_event.await_args.kwargs["event_metadata"]
    assert metadata["assignment_ended"] == str(ended_assignment.id)
    assert metadata["transaction_settlement"] == {
        "cancelled_order_count": 1
    }


@pytest.mark.asyncio
async def test_consent_rejects_stale_notice_before_loading_customer():
    service = CustomerLifecycleService(SimpleNamespace())  # type: ignore[arg-type]

    with pytest.raises(AgencyTransactionConflict) as exc_info:
        await service.record_customer_consent(
            actor_user_id=TARGET_USER_ID,
            customer_id=CUSTOMER_ID,
            expected_revision=1,
            decision="grant",
            expected_notice_version="stale.v0",
            expected_notice_document_sha256="0" * 64,
            idempotency_key="stale-notice",
        )

    assert exc_info.value.code == "customer_consent_notice_changed"


@pytest.mark.asyncio
async def test_server_consent_record_is_derived_from_fixed_notice(
    monkeypatch: pytest.MonkeyPatch,
):
    db = _SequenceDb(0)
    customer = _customer(
        user_id=TARGET_USER_ID,
        status="invited",
        binding_provenance="secure_claim",
        claimed_invitation_id=INVITATION_ID,
        claimed_at=NOW,
        lifecycle_revision=4,
    )
    service = CustomerLifecycleService(db, now_factory=lambda: NOW)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_flush", AsyncMock())

    record = await service._create_customer_consent_record(
        customer=customer,
        decision="grant",
        recorded_at=NOW,
    )

    _, expected_hash = build_customer_consent_evidence(
        agency_id=AGENCY_ID,
        branch_id=BRANCH_ID,
        customer_id=CUSTOMER_ID,
        user_id=TARGET_USER_ID,
        claim_invitation_id=INVITATION_ID,
        decision="grant",
        recorded_at=NOW,
    )
    assert record.id == CONSENT_RECORD_ID
    assert record.customer_revision == 5
    assert record.consent_sequence == 1
    assert record.consent_version == CUSTOMER_CONSENT_VERSION
    assert record.consent_document_hash == CUSTOMER_CONSENT_DOCUMENT_SHA256
    assert record.evidence_schema_version == CUSTOMER_CONSENT_EVIDENCE_SCHEMA
    assert record.evidence_hash == expected_hash
    assert record.evidence_origin == "server_canonical"


def test_server_consent_document_hash_matches_committed_notice():
    notice_path = Path(
        "docs/架构与流程/customer-consent-notice-v1.md"
    )
    notice = notice_path.read_bytes()

    assert hashlib.sha256(notice).hexdigest() == (
        CUSTOMER_CONSENT_DOCUMENT_SHA256
    )
    assert notice_path.read_text(encoding="utf-8") == (
        CUSTOMER_CONSENT_NOTICE_MARKDOWN
    )
