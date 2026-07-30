"""旅行社门店、客户生命周期与主顾问分配服务。

所有命令都复用交易域的持久化幂等记录。服务只维护内部业务事实，不发送
邀请通知，也不会把“客户已激活”解释为已经下单、付款或锁定供应商库存。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agency.branch_administration import BranchAdministrationMixin
from app.agency.branch_authorization import (
    CUSTOMER_MANAGER_ROLES,
    BranchAuthorization,
)
from app.agency.customer_transaction_settlement import (
    CustomerTransactionSettlementMixin,
)
from app.agency.customer_claim_service import CustomerClaimServiceMixin
from app.agency.customer_lifecycle_support import CustomerLifecycleSupportMixin
from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.agency.transaction_service import (
    AgencyTransactionService,
)
from app.models.agency_customer_lifecycle import (
    AgencyBranchRoleGrant,
    AgencyCustomer,
    AgencyCustomerAdvisorAssignment,
    AgencyCustomerEvent,
)
from app.models.agency_transaction import AgencyMembership, AgencyOrder
from app.schemas.agency_customer_lifecycle import AgencyCustomerCreateRequest


class CustomerLifecycleService(
    BranchAdministrationMixin,
    CustomerLifecycleSupportMixin,
    CustomerClaimServiceMixin,
    CustomerTransactionSettlementMixin,
    AgencyTransactionService,
):
    """在同一 ``AsyncSession`` 事务中维护旅行社客户聚合。"""

    def __init__(self, db: AsyncSession, **kwargs: Any) -> None:
        super().__init__(db, **kwargs)
        self.authorization = BranchAuthorization(db)

    async def create_customer(
        self,
        *,
        actor_user_id: uuid.UUID,
        data: AgencyCustomerCreateRequest,
        idempotency_key: str,
    ) -> AgencyCustomer:
        branch = await self._get_branch(data.branch_id, for_update=True)
        if branch.agency_id != data.agency_id:
            raise hidden_not_found()
        self._ensure_branch_active(branch)
        await self.authorization.require_branch_role(
            agency_id=branch.agency_id,
            branch_id=branch.id,
            actor_user_id=actor_user_id,
            roles=CUSTOMER_MANAGER_ROLES,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=branch.agency_id,
            scope="customer.create",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "agency_id": branch.agency_id,
                "branch_id": branch.id,
                "source_type": data.source_type,
                "source_reference": data.source_reference,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyCustomer,
                resource_type="agency_customer",
                agency_id=branch.agency_id,
            )

        customer = AgencyCustomer(
            agency_id=branch.agency_id,
            branch_id=branch.id,
            customer_no=f"CUST-{uuid.uuid4().hex[:20].upper()}",
            source_type=data.source_type,
            source_reference=data.source_reference,
            status="prospect",
            binding_provenance="unbound",
            consent_status="unknown",
            consent_evidence_origin="none",
            lifecycle_revision=1,
            invited_at=self._now(),
        )
        self.db.add(customer)
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_created",
            from_status=None,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "source_type": customer.source_type,
                "linked_user": False,
                "notification_sent": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer",
            resource=customer,
        )

    async def list_customers(
        self,
        *,
        actor_user_id: uuid.UUID,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID | None,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyCustomer], int]:
        visibility = await self.authorization.customer_visibility_filter(
            agency_id=agency_id,
            actor_user_id=actor_user_id,
        )
        filters = [
            AgencyCustomer.agency_id == agency_id,
            visibility,
        ]
        if branch_id is not None:
            filters.append(AgencyCustomer.branch_id == branch_id)
        if status_filter is not None:
            filters.append(AgencyCustomer.status == status_filter)
        return await self._page(
            statement=select(AgencyCustomer)
            .where(*filters)
            .order_by(
                desc(AgencyCustomer.created_at),
                desc(AgencyCustomer.id),
            )
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyCustomer)
            .where(*filters),
        )

    async def get_customer(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
    ) -> AgencyCustomer:
        customer = await self._get_customer(customer_id)
        await self.authorization.require_customer_view(
            customer=customer,
            actor_user_id=actor_user_id,
        )
        return customer

    async def activate_customer(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgencyCustomer:
        customer = await self._get_customer(customer_id, for_update=True)
        await self.authorization.require_customer_manager(
            customer=customer,
            actor_user_id=actor_user_id,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.activate",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
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
        if customer.status == "active":
            raise AgencyTransactionConflict(
                "customer_state_conflict",
                "客户关系已经处于 active 状态",
            )
        if customer.status == "blocked":
            raise AgencyTransactionConflict(
                "customer_state_conflict",
                "blocked 客户必须先完成独立风险复核，不能直接激活",
            )
        if customer.user_id is None:
            raise AgencyTransactionValidationError(
                "customer_user_link_required",
                "客户关系必须先关联平台用户才能激活",
            )
        if (
            customer.binding_provenance != "secure_claim"
            or customer.claimed_invitation_id is None
            or customer.claimed_at is None
        ):
            raise AgencyTransactionValidationError(
                "customer_claim_required",
                "客户关系必须先完成一次性邀请认领才能激活",
            )
        if (
            customer.consent_status != "granted"
            or customer.consent_version is None
            or customer.consent_evidence_hash is None
            or customer.current_consent_record_id is None
            or customer.consent_evidence_origin != "server_canonical"
        ):
            raise AgencyTransactionValidationError(
                "customer_consent_required",
                "客户本人服务端同意证据是激活前置条件",
            )
        pending_review_result = await self.db.execute(
            select(AgencyOrder.id)
            .where(AgencyOrder.agency_id == customer.agency_id)
            .where(AgencyOrder.branch_id == customer.branch_id)
            .where(AgencyOrder.customer_id == customer.id)
            .where(AgencyOrder.status == "pending_review")
            .limit(1)
        )
        if pending_review_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "customer_pending_review_requires_resolution",
                "客户停用前的待审核订单必须先由门店审批员明确拒绝",
            )

        from_status = customer.status
        now = self._now()
        customer.status = "active"
        customer.activated_at = now
        customer.deactivated_at = None
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_activated",
            from_status=from_status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={},
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer",
            resource=customer,
        )

    async def deactivate_customer(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> AgencyCustomer:
        safe_reason = self._safe_reason(reason)
        customer = await self._get_customer(customer_id, for_update=True)
        is_self = customer.user_id == actor_user_id
        if not is_self:
            await self.authorization.require_customer_cleanup_manager(
                customer=customer,
                actor_user_id=actor_user_id,
            )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.deactivate",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
                "reason": safe_reason,
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
        if customer.status == "inactive":
            raise AgencyTransactionConflict(
                "customer_state_conflict",
                "客户关系已经处于 inactive 状态",
            )
        if customer.status == "blocked":
            raise AgencyTransactionConflict(
                "customer_blocked",
                "blocked 客户只能通过独立风险复核流程解除，不能直接停用",
            )

        now = self._now()
        from_status = customer.status
        consent_record = None
        if is_self:
            consent_record = await self._create_customer_consent_record(
                customer=customer,
                decision="revoke",
                recorded_at=now,
            )
        customer.status = "inactive"
        customer.deactivated_at = now
        if consent_record is not None:
            customer.consent_status = "revoked"
            customer.consent_version = consent_record.consent_version
            customer.consent_evidence_hash = consent_record.evidence_hash
            customer.current_consent_record_id = consent_record.id
            customer.consent_evidence_origin = "server_canonical"
            customer.consent_updated_at = now
        ended_assignment = await self._end_active_assignment(
            customer=customer,
            ended_at=now,
            reason=safe_reason,
        )
        transaction_settlement = await self._settle_customer_transactions(
            customer=customer,
            actor_user_id=actor_user_id,
        )
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type=(
                "customer_self_deactivated"
                if is_self
                else "customer_deactivated"
            ),
            from_status=from_status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "reason": safe_reason,
                "consent_revoked": is_self,
                "consent_evidence_hash": (
                    customer.consent_evidence_hash if is_self else None
                ),
                "consent_record_id": (
                    str(consent_record.id)
                    if consent_record is not None
                    else None
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

    async def assign_customer_advisor(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        advisor_role_grant_id: uuid.UUID,
        reason: str | None,
        idempotency_key: str,
    ) -> AgencyCustomerAdvisorAssignment:
        safe_reason = self._safe_reason(reason) if reason else None
        customer = await self._get_customer(customer_id, for_update=True)
        await self.authorization.require_customer_manager(
            customer=customer,
            actor_user_id=actor_user_id,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.advisor_assign",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
                "advisor_role_grant_id": advisor_role_grant_id,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyCustomerAdvisorAssignment,
                resource_type="agency_customer_advisor_assignment",
                agency_id=customer.agency_id,
            )

        self._ensure_revision(
            customer.lifecycle_revision,
            expected_revision,
        )
        if customer.status != "active":
            raise AgencyTransactionConflict(
                "customer_not_active",
                "只有 active 客户可以分配主顾问",
            )
        grant_result = await self.db.execute(
            select(AgencyBranchRoleGrant)
            .join(
                AgencyMembership,
                AgencyMembership.id
                == AgencyBranchRoleGrant.membership_id,
            )
            .where(AgencyBranchRoleGrant.id == advisor_role_grant_id)
            .where(
                AgencyBranchRoleGrant.agency_id == customer.agency_id
            )
            .where(
                AgencyBranchRoleGrant.branch_id == customer.branch_id
            )
            .where(AgencyBranchRoleGrant.role == "travel_advisor")
            .where(AgencyBranchRoleGrant.status == "active")
            .where(AgencyMembership.agency_id == customer.agency_id)
            .where(AgencyMembership.status == "active")
            .where(AgencyMembership.role == "travel_advisor")
            .with_for_update()
        )
        grant = grant_result.scalar_one_or_none()
        if grant is None:
            raise AgencyTransactionValidationError(
                "customer_advisor_grant_invalid",
                "顾问授权不存在、未激活或不属于该客户门店",
            )

        current_result = await self.db.execute(
            select(AgencyCustomerAdvisorAssignment)
            .where(
                AgencyCustomerAdvisorAssignment.agency_id
                == customer.agency_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.branch_id
                == customer.branch_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.customer_id == customer.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
            .with_for_update()
        )
        current = current_result.scalar_one_or_none()
        if (
            current is not None
            and current.advisor_role_grant_id == grant.id
        ):
            raise AgencyTransactionConflict(
                "customer_advisor_state_conflict",
                "该顾问已经是客户当前主顾问",
            )
        if current is not None and not safe_reason:
            raise AgencyTransactionValidationError(
                "customer_advisor_transfer_reason_required",
                "更换主顾问必须记录原因",
            )

        now = self._now()
        if current is not None:
            current.status = "ended"
            current.ended_at = now
            current.ended_reason = safe_reason
        assignment = AgencyCustomerAdvisorAssignment(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            customer_id=customer.id,
            advisor_role_grant_id=grant.id,
            advisor_membership_id=grant.membership_id,
            status="active",
            revision=1,
            assigned_by_user_id=actor_user_id,
            assignment_reason=safe_reason,
            assigned_at=now,
        )
        self.db.add(assignment)
        customer.lifecycle_revision += 1
        customer.updated_at = now
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type=(
                "customer_advisor_reassigned"
                if current is not None
                else "customer_advisor_assigned"
            ),
            from_status=customer.status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "assignment_id": str(assignment.id),
                "previous_assignment_id": (
                    str(current.id) if current is not None else None
                ),
                "reason": safe_reason,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer_advisor_assignment",
            resource=assignment,
        )

    async def end_customer_advisor_assignment(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> AgencyCustomerAdvisorAssignment:
        safe_reason = self._safe_reason(reason)
        customer = await self._get_customer(customer_id, for_update=True)
        await self.authorization.require_customer_cleanup_manager(
            customer=customer,
            actor_user_id=actor_user_id,
        )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.advisor_assignment.end",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyCustomerAdvisorAssignment,
                resource_type="agency_customer_advisor_assignment",
                agency_id=customer.agency_id,
            )

        self._ensure_revision(
            customer.lifecycle_revision,
            expected_revision,
        )
        now = self._now()
        assignment = await self._end_active_assignment(
            customer=customer,
            ended_at=now,
            reason=safe_reason,
        )
        if assignment is None:
            raise AgencyTransactionConflict(
                "customer_advisor_assignment_missing",
                "客户当前没有可结束的主顾问分配",
            )
        customer.lifecycle_revision += 1
        customer.updated_at = now
        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_advisor_unassigned",
            from_status=customer.status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "assignment_id": str(assignment.id),
                "reason": safe_reason,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer_advisor_assignment",
            resource=assignment,
        )

    async def list_customer_advisor_assignments(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyCustomerAdvisorAssignment], int]:
        customer = await self._get_customer(customer_id)
        await self.authorization.require_customer_view(
            customer=customer,
            actor_user_id=actor_user_id,
        )
        filters = [
            AgencyCustomerAdvisorAssignment.agency_id
            == customer.agency_id,
            AgencyCustomerAdvisorAssignment.branch_id
            == customer.branch_id,
            AgencyCustomerAdvisorAssignment.customer_id == customer.id,
        ]
        if status_filter is not None:
            filters.append(
                AgencyCustomerAdvisorAssignment.status == status_filter
            )
        return await self._page(
            statement=select(AgencyCustomerAdvisorAssignment)
            .where(*filters)
            .order_by(
                desc(AgencyCustomerAdvisorAssignment.assigned_at),
                desc(AgencyCustomerAdvisorAssignment.id),
            )
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyCustomerAdvisorAssignment)
            .where(*filters),
        )

    async def list_customer_events(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyCustomerEvent], int]:
        customer = await self._get_customer(customer_id)
        await self.authorization.require_customer_view(
            customer=customer,
            actor_user_id=actor_user_id,
        )
        filters = [
            AgencyCustomerEvent.agency_id == customer.agency_id,
            AgencyCustomerEvent.branch_id == customer.branch_id,
            AgencyCustomerEvent.customer_id == customer.id,
        ]
        return await self._page(
            statement=select(AgencyCustomerEvent)
            .where(*filters)
            .order_by(AgencyCustomerEvent.event_sequence)
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyCustomerEvent)
            .where(*filters),
        )
