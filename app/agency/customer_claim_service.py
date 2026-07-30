"""客户一次性邀请、账号认领与服务端同意证据服务。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import NoReturn

from sqlalchemy import desc, func, select

from app.agency.customer_claim_tokens import (
    generate_claim_token,
    hash_claim_token,
    verify_claim_token,
)
from app.agency.customer_consent import (
    CONSENT_DECISION_TO_STATUS,
    CUSTOMER_CONSENT_DOCUMENT_SHA256,
    CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
    CUSTOMER_CONSENT_VERSION,
    build_customer_consent_evidence,
)
from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.models.agency_customer_identity import (
    AgencyCustomerConsentRecord,
    AgencyCustomerInvitation,
)
from app.models.agency_customer_lifecycle import AgencyCustomer
from app.models.user import User


CUSTOMER_CLAIM_TOKEN_TTL = timedelta(hours=24)


class CustomerClaimServiceMixin:
    """复用客户聚合锁、门店授权、幂等记录和只追加事件。"""

    @staticmethod
    def _claim_unavailable() -> NoReturn:
        raise AgencyTransactionConflict(
            "customer_claim_unavailable",
            "客户认领邀请无效、已失效或已使用",
        )

    async def issue_customer_claim_invitation(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        target_user_id: uuid.UUID,
        idempotency_key: str,
    ) -> tuple[AgencyCustomerInvitation, str | None]:
        customer = await self._get_customer(customer_id, for_update=True)
        await self.authorization.require_customer_manager(
            customer=customer,
            actor_user_id=actor_user_id,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.claim_invitation.issue",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
                "target_user_id": target_user_id,
            },
        )
        if state.replayed:
            invitation = await self._load_replayed_resource(
                state,
                model=AgencyCustomerInvitation,
                resource_type="agency_customer_invitation",
                agency_id=customer.agency_id,
                resource_label="客户认领邀请",
            )
            return invitation, None

        self._ensure_revision(
            customer.lifecycle_revision,
            expected_revision,
        )
        if customer.status == "blocked":
            raise AgencyTransactionConflict(
                "customer_blocked",
                "blocked 客户必须先完成独立风险复核",
            )
        if customer.binding_provenance == "secure_claim":
            raise AgencyTransactionConflict(
                "customer_already_claimed",
                "客户关系已经完成安全认领",
            )
        if customer.binding_provenance == "unbound":
            if customer.user_id is not None or customer.status != "prospect":
                raise AgencyTransactionConflict(
                    "customer_claim_state_conflict",
                    "当前客户状态不能签发认领邀请",
                )
        elif (
            customer.binding_provenance != "legacy_direct"
            or customer.user_id != target_user_id
        ):
            raise AgencyTransactionConflict(
                "customer_claim_state_conflict",
                "遗留绑定只能由原关联账户重新认领",
            )

        user_result = await self.db.execute(
            select(User.id)
            .where(User.id == target_user_id)
            .with_for_update()
        )
        if user_result.scalar_one_or_none() is None:
            raise AgencyTransactionConflict(
                "customer_claim_target_unavailable",
                "目标账户当前不可签发客户认领邀请",
            )
        existing_customer_result = await self.db.execute(
            select(AgencyCustomer.id)
            .where(AgencyCustomer.agency_id == customer.agency_id)
            .where(AgencyCustomer.user_id == target_user_id)
            .where(AgencyCustomer.id != customer.id)
            .limit(1)
        )
        if existing_customer_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "customer_claim_target_unavailable",
                "目标账户当前不可签发客户认领邀请",
            )
        target_pending_result = await self.db.execute(
            select(AgencyCustomerInvitation.id)
            .where(
                AgencyCustomerInvitation.agency_id == customer.agency_id
            )
            .where(
                AgencyCustomerInvitation.target_user_id == target_user_id
            )
            .where(AgencyCustomerInvitation.status == "pending")
            .limit(1)
            .with_for_update()
        )
        if target_pending_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "customer_claim_target_unavailable",
                "目标账户当前不可签发客户认领邀请",
            )

        now = self._now()
        pending_result = await self.db.execute(
            select(AgencyCustomerInvitation)
            .where(
                AgencyCustomerInvitation.agency_id == customer.agency_id
            )
            .where(
                AgencyCustomerInvitation.branch_id == customer.branch_id
            )
            .where(
                AgencyCustomerInvitation.customer_id == customer.id
            )
            .where(AgencyCustomerInvitation.status == "pending")
            .with_for_update()
        )
        previous_invitation = pending_result.scalar_one_or_none()
        if previous_invitation is not None:
            raise AgencyTransactionConflict(
                "customer_claim_invitation_pending",
                "客户已有待认领邀请，请先撤销后再重新签发",
            )

        claim_token = generate_claim_token()
        invitation = AgencyCustomerInvitation(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            customer_id=customer.id,
            target_user_id=target_user_id,
            token_digest=hash_claim_token(claim_token),
            status="pending",
            revision=1,
            issued_by_user_id=actor_user_id,
            issued_at=now,
            expires_at=now + CUSTOMER_CLAIM_TOKEN_TTL,
        )
        self.db.add(invitation)
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_claim_invitation_issued",
            from_status=customer.status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "invitation_id": str(invitation.id),
                "expires_at": invitation.expires_at.isoformat(),
                "notification_sent": False,
            },
        )
        await self._finish_action(
            state,
            resource_type="agency_customer_invitation",
            resource=invitation,
        )
        return invitation, claim_token

    async def list_customer_claim_invitations(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyCustomerInvitation], int]:
        customer = await self._get_customer(customer_id)
        await self.authorization.require_customer_manager(
            customer=customer,
            actor_user_id=actor_user_id,
        )
        filters = (
            AgencyCustomerInvitation.agency_id == customer.agency_id,
            AgencyCustomerInvitation.branch_id == customer.branch_id,
            AgencyCustomerInvitation.customer_id == customer.id,
        )
        return await self._page(
            statement=select(AgencyCustomerInvitation)
            .where(*filters)
            .order_by(
                desc(AgencyCustomerInvitation.issued_at),
                desc(AgencyCustomerInvitation.id),
            )
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyCustomerInvitation)
            .where(*filters),
        )

    async def revoke_customer_claim_invitation(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        invitation_id: uuid.UUID,
        expected_revision: int,
        expected_invitation_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> AgencyCustomerInvitation:
        safe_reason = self._safe_reason(reason)
        customer = await self._get_customer(customer_id, for_update=True)
        await self.authorization.require_customer_manager(
            customer=customer,
            actor_user_id=actor_user_id,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.claim_invitation.revoke",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "invitation_id": invitation_id,
                "expected_revision": expected_revision,
                "expected_invitation_revision": (
                    expected_invitation_revision
                ),
                "reason": safe_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyCustomerInvitation,
                resource_type="agency_customer_invitation",
                agency_id=customer.agency_id,
                resource_label="客户认领邀请",
            )

        self._ensure_revision(
            customer.lifecycle_revision,
            expected_revision,
        )
        invitation_result = await self.db.execute(
            select(AgencyCustomerInvitation)
            .where(AgencyCustomerInvitation.id == invitation_id)
            .where(
                AgencyCustomerInvitation.agency_id == customer.agency_id
            )
            .where(
                AgencyCustomerInvitation.branch_id == customer.branch_id
            )
            .where(
                AgencyCustomerInvitation.customer_id == customer.id
            )
            .with_for_update()
        )
        invitation = invitation_result.scalar_one_or_none()
        if invitation is None:
            raise hidden_not_found()
        self._ensure_revision(
            invitation.revision,
            expected_invitation_revision,
        )
        if invitation.status != "pending":
            raise AgencyTransactionConflict(
                "customer_claim_invitation_state_conflict",
                "只有待认领邀请可以撤销",
            )

        now = self._now()
        invitation.status = "revoked"
        invitation.revoked_by_user_id = actor_user_id
        invitation.revoked_at = now
        invitation.revocation_reason = safe_reason
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_claim_invitation_revoked",
            from_status=customer.status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "invitation_id": str(invitation.id),
                "reason": safe_reason,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer_invitation",
            resource=invitation,
        )

    async def claim_customer(
        self,
        *,
        actor_user_id: uuid.UUID,
        claim_token: str,
        idempotency_key: str,
    ) -> AgencyCustomer:
        token_digest = hash_claim_token(claim_token)
        preview_result = await self.db.execute(
            select(
                AgencyCustomerInvitation.id,
                AgencyCustomerInvitation.agency_id,
                AgencyCustomerInvitation.branch_id,
                AgencyCustomerInvitation.customer_id,
            ).where(
                AgencyCustomerInvitation.token_digest == token_digest
            )
        )
        preview = preview_result.one_or_none()
        if preview is None:
            self._claim_unavailable()

        customer = await self._get_customer(
            preview.customer_id,
            for_update=True,
        )
        if (
            customer.agency_id != preview.agency_id
            or customer.branch_id != preview.branch_id
        ):
            self._claim_unavailable()
        await self.authorization.lock_active_branch_scope(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
        )
        actor_result = await self.db.execute(
            select(User.id)
            .where(User.id == actor_user_id)
            .with_for_update()
        )
        if actor_result.scalar_one_or_none() is None:
            self._claim_unavailable()
        invitation_result = await self.db.execute(
            select(AgencyCustomerInvitation)
            .where(AgencyCustomerInvitation.id == preview.id)
            .where(
                AgencyCustomerInvitation.token_digest == token_digest
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        invitation = invitation_result.scalar_one_or_none()
        if invitation is None or not verify_claim_token(
            claim_token,
            invitation.token_digest,
        ):
            self._claim_unavailable()

        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.claim",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "claim_token_digest": token_digest,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_customer",
                resource_id=customer.id,
            )
            return customer

        now = self._now()
        if (
            invitation.status != "pending"
            or invitation.target_user_id != actor_user_id
            or now >= invitation.expires_at
            or customer.status == "blocked"
        ):
            self._claim_unavailable()
        if customer.binding_provenance == "secure_claim":
            self._claim_unavailable()
        is_legacy_upgrade = customer.binding_provenance == "legacy_direct"
        if is_legacy_upgrade:
            if customer.user_id != actor_user_id:
                self._claim_unavailable()
        elif (
            customer.binding_provenance != "unbound"
            or customer.user_id is not None
            or customer.status != "prospect"
        ):
            self._claim_unavailable()

        existing_customer_result = await self.db.execute(
            select(AgencyCustomer.id)
            .where(AgencyCustomer.agency_id == customer.agency_id)
            .where(AgencyCustomer.user_id == actor_user_id)
            .where(AgencyCustomer.id != customer.id)
            .limit(1)
        )
        if existing_customer_result.scalar_one_or_none() is not None:
            self._claim_unavailable()

        from_status = customer.status
        invitation.status = "claimed"
        invitation.claimed_by_user_id = actor_user_id
        invitation.claimed_at = now
        customer.user_id = actor_user_id
        customer.binding_provenance = "secure_claim"
        customer.claimed_invitation_id = invitation.id
        customer.claimed_at = now
        ended_assignment = None
        transaction_settlement = None
        if is_legacy_upgrade:
            if customer.status == "active":
                customer.status = "inactive"
                customer.deactivated_at = now
            elif customer.status == "prospect":
                customer.status = "invited"
            customer.consent_status = "unknown"
            customer.consent_version = None
            customer.consent_evidence_hash = None
            customer.current_consent_record_id = None
            customer.consent_evidence_origin = "none"
            customer.consent_updated_at = None
            if from_status == "active":
                ended_assignment = await self._end_active_assignment(
                    customer=customer,
                    ended_at=now,
                    reason="legacy_binding_secure_claim_upgrade",
                )
                transaction_settlement = (
                    await self._settle_customer_transactions(
                        customer=customer,
                        actor_user_id=actor_user_id,
                    )
                )
        else:
            customer.status = "invited"
            customer.consent_status = "unknown"
            customer.consent_version = None
            customer.consent_evidence_hash = None
            customer.current_consent_record_id = None
            customer.consent_evidence_origin = "none"
            customer.consent_updated_at = None
            customer.activated_at = None
            customer.deactivated_at = None
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_secure_claimed",
            from_status=from_status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "invitation_id": str(invitation.id),
                "legacy_binding_upgraded": is_legacy_upgrade,
                "assignment_ended": (
                    str(ended_assignment.id)
                    if ended_assignment is not None
                    else None
                ),
                "transaction_settlement": transaction_settlement,
                "notification_sent": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer",
            resource=customer,
        )

    async def _create_customer_consent_record(
        self,
        *,
        customer: AgencyCustomer,
        decision: str,
        recorded_at: datetime,
    ) -> AgencyCustomerConsentRecord:
        target_status = CONSENT_DECISION_TO_STATUS.get(decision)
        if target_status is None:
            raise AgencyTransactionValidationError(
                "customer_consent_decision_invalid",
                "客户授权决定必须是 grant、deny 或 revoke",
            )
        if customer.user_id is None:
            raise hidden_not_found()
        if customer.binding_provenance == "secure_claim":
            invitation_id = customer.claimed_invitation_id
            if invitation_id is None:
                raise AgencyTransactionConflict(
                    "customer_claim_required",
                    "客户关系必须先完成安全认领",
                )
        elif (
            customer.binding_provenance == "legacy_direct"
            and target_status in {"denied", "revoked"}
        ):
            invitation_id = None
        else:
            raise AgencyTransactionConflict(
                "customer_claim_required",
                "客户关系必须先完成安全认领",
            )

        sequence_result = await self.db.execute(
            select(
                func.coalesce(
                    func.max(
                        AgencyCustomerConsentRecord.consent_sequence
                    ),
                    0,
                )
            )
            .where(
                AgencyCustomerConsentRecord.agency_id
                == customer.agency_id
            )
            .where(
                AgencyCustomerConsentRecord.branch_id
                == customer.branch_id
            )
            .where(
                AgencyCustomerConsentRecord.customer_id == customer.id
            )
        )
        _, evidence_hash = build_customer_consent_evidence(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            customer_id=customer.id,
            user_id=customer.user_id,
            claim_invitation_id=invitation_id,
            decision=decision,
            recorded_at=recorded_at,
        )
        record = AgencyCustomerConsentRecord(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            customer_id=customer.id,
            user_id=customer.user_id,
            invitation_id=invitation_id,
            consent_sequence=int(sequence_result.scalar_one()) + 1,
            customer_revision=customer.lifecycle_revision + 1,
            decision=target_status,
            consent_version=CUSTOMER_CONSENT_VERSION,
            consent_document_hash=CUSTOMER_CONSENT_DOCUMENT_SHA256,
            evidence_hash=evidence_hash,
            evidence_schema_version=CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
            evidence_origin="server_canonical",
            recorded_at=recorded_at,
        )
        self.db.add(record)
        await self._flush()
        return record

    async def record_customer_consent(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        decision: str,
        expected_notice_version: str,
        expected_notice_document_sha256: str,
        idempotency_key: str,
    ) -> AgencyCustomer:
        target_status = CONSENT_DECISION_TO_STATUS.get(decision)
        if target_status is None:
            raise AgencyTransactionValidationError(
                "customer_consent_decision_invalid",
                "客户授权决定必须是 grant、deny 或 revoke",
            )
        if (
            expected_notice_version != CUSTOMER_CONSENT_VERSION
            or expected_notice_document_sha256.lower()
            != CUSTOMER_CONSENT_DOCUMENT_SHA256
        ):
            raise AgencyTransactionConflict(
                "customer_consent_notice_changed",
                "客户授权告知已更新，请重新读取后再提交决定",
            )
        customer = await self._get_customer(customer_id, for_update=True)
        if customer.user_id != actor_user_id:
            raise hidden_not_found()
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.consent",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
                "decision": decision,
                "expected_notice_version": expected_notice_version,
                "expected_notice_document_sha256": (
                    expected_notice_document_sha256.lower()
                ),
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_customer",
                resource_id=customer.id,
            )
            return customer

        self._ensure_revision(
            customer.lifecycle_revision,
            expected_revision,
        )
        if (
            customer.consent_status == target_status
            and customer.consent_version == CUSTOMER_CONSENT_VERSION
            and customer.consent_evidence_origin == "server_canonical"
        ):
            raise AgencyTransactionConflict(
                "customer_consent_state_conflict",
                "该客户授权决定已经记录",
            )

        now = self._now()
        record = await self._create_customer_consent_record(
            customer=customer,
            decision=decision,
            recorded_at=now,
        )
        from_status = customer.status
        ended_assignment = None
        transaction_settlement = None
        customer.consent_status = target_status
        customer.consent_version = record.consent_version
        customer.consent_evidence_hash = record.evidence_hash
        customer.current_consent_record_id = record.id
        customer.consent_evidence_origin = "server_canonical"
        customer.consent_updated_at = now
        if target_status in {"denied", "revoked"} and customer.status == "active":
            customer.status = "inactive"
            customer.deactivated_at = now
            ended_assignment = await self._end_active_assignment(
                customer=customer,
                ended_at=now,
                reason=f"consent_{target_status}",
            )
            transaction_settlement = (
                await self._settle_customer_transactions(
                    customer=customer,
                    actor_user_id=actor_user_id,
                )
            )
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type=f"customer_consent_{target_status}",
            from_status=from_status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "consent_record_id": str(record.id),
                "consent_version": record.consent_version,
                "consent_document_hash": (
                    record.consent_document_hash
                ),
                "consent_evidence_hash": record.evidence_hash,
                "evidence_schema_version": (
                    record.evidence_schema_version
                ),
                "assignment_ended": (
                    str(ended_assignment.id)
                    if ended_assignment is not None
                    else None
                ),
                "transaction_settlement": transaction_settlement,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer",
            resource=customer,
        )


__all__ = [
    "CUSTOMER_CLAIM_TOKEN_TTL",
    "CustomerClaimServiceMixin",
]
