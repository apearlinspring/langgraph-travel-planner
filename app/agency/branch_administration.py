"""旅行社门店与门店角色授权管理服务。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, desc, exists, func, or_, select

from app.agency.branch_authorization import (
    ALLOWED_BRANCH_GRANT_ROLES,
    BRANCH_DRAIN_STATUSES,
    CUSTOMER_MANAGER_ROLES,
)
from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.models.agency_cancellation import AgencyOrderCancellationCase
from app.models.agency_customer_identity import AgencyCustomerInvitation
from app.models.agency_customer_lifecycle import (
    AgencyBranch,
    AgencyBranchLifecycleEvent,
    AgencyBranchRoleGrant,
    AgencyCustomer,
    AgencyCustomerAdvisorAssignment,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import (
    AgencyMembership,
    AgencyOrder,
    AgencyQuote,
)


@dataclass(frozen=True)
class BranchClosureReadiness:
    """不暴露具体客户、员工或交易 ID 的关店阻断汇总。"""

    branch_id: uuid.UUID
    status: str
    revision: int
    ready: bool
    current_customer_count: int
    pending_invitation_count: int
    active_assignment_count: int
    active_role_grant_count: int
    pending_review_count: int
    open_quote_count: int
    open_order_count: int
    open_cancellation_case_count: int


class BranchAdministrationMixin:
    """供客户生命周期服务复用的门店与授权 CRUD。"""

    async def create_branch(
        self,
        *,
        actor_user_id: uuid.UUID,
        data: Any,
        idempotency_key: str,
    ) -> AgencyBranch:
        await self.authorization.require_agency_wide(
            agency_id=data.agency_id,
            actor_user_id=actor_user_id,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=data.agency_id,
            scope="branch.create",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "agency_id": data.agency_id,
                "branch_code": data.branch_code,
                "name": data.name,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyBranch,
                resource_type="agency_branch",
                agency_id=data.agency_id,
            )
        branch = AgencyBranch(
            agency_id=data.agency_id,
            branch_code=data.branch_code,
            name=data.name,
            status="active",
            revision=1,
        )
        self.db.add(branch)
        await self._flush()
        return await self._finish_action(
            state,
            resource_type="agency_branch",
            resource=branch,
        )

    async def list_branches(
        self,
        *,
        actor_user_id: uuid.UUID,
        agency_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyBranch], int]:
        visibility = await self.authorization.branch_visibility_filter(
            agency_id=agency_id,
            actor_user_id=actor_user_id,
        )
        filters = [AgencyBranch.agency_id == agency_id, visibility]
        if status_filter is not None:
            filters.append(AgencyBranch.status == status_filter)
        return await self._page(
            statement=select(AgencyBranch)
            .where(*filters)
            .order_by(desc(AgencyBranch.created_at), desc(AgencyBranch.id))
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyBranch)
            .where(*filters),
        )

    async def deactivate_branch(
        self,
        *,
        actor_user_id: uuid.UUID,
        branch_id: uuid.UUID,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> AgencyBranch:
        """把门店置为存量清理期，不把它误报为已经关店。"""

        safe_reason = self._safe_reason(reason)
        branch = await self._get_branch(branch_id, for_update=True)
        await self.authorization.require_agency_wide(
            agency_id=branch.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=branch.agency_id,
            scope="branch.deactivate",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "branch_id": branch.id,
                "expected_revision": expected_revision,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_branch",
                resource_id=branch.id,
            )
            return branch

        self._ensure_revision(branch.revision, expected_revision)
        if branch.status != "active":
            raise AgencyTransactionConflict(
                "branch_state_conflict",
                "只有 active 门店可以进入 inactive 清理期",
            )
        now = self._now()
        branch.status = "inactive"
        branch.revision += 1
        branch.deactivated_at = now
        branch.closed_at = None
        await self._append_branch_lifecycle_event(
            branch=branch,
            event_type="deactivated",
            actor_user_id=actor_user_id,
            reason=safe_reason,
        )
        return await self._finish_action(
            state,
            resource_type="agency_branch",
            resource=branch,
        )

    async def get_branch_closure_readiness(
        self,
        *,
        actor_user_id: uuid.UUID,
        branch_id: uuid.UUID,
    ) -> BranchClosureReadiness:
        branch = await self._get_branch(branch_id)
        await self.authorization.require_branch_role(
            agency_id=branch.agency_id,
            branch_id=branch.id,
            actor_user_id=actor_user_id,
            roles=CUSTOMER_MANAGER_ROLES,
            allowed_branch_statuses={"active", "inactive", "closed"},
        )
        return await self._branch_closure_readiness(branch)

    async def close_branch(
        self,
        *,
        actor_user_id: uuid.UUID,
        branch_id: uuid.UUID,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> AgencyBranch:
        """在全部阻断项清零后把 inactive 门店置为不可逆 closed。"""

        safe_reason = self._safe_reason(reason)
        branch = await self._get_branch(branch_id, for_update=True)
        await self.authorization.require_agency_wide(
            agency_id=branch.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=branch.agency_id,
            scope="branch.close",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "branch_id": branch.id,
                "expected_revision": expected_revision,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_branch",
                resource_id=branch.id,
            )
            return branch

        self._ensure_revision(branch.revision, expected_revision)
        if branch.status != "inactive":
            raise AgencyTransactionConflict(
                "branch_state_conflict",
                "只有 inactive 清理期门店可以执行最终关闭",
            )
        readiness = await self._branch_closure_readiness(branch)
        if not readiness.ready:
            raise AgencyTransactionConflict(
                "branch_close_blocked",
                "门店仍有客户、岗位授权或开放业务，必须先完成清理",
            )

        now = self._now()
        branch.status = "closed"
        branch.revision += 1
        branch.closed_at = now
        await self._append_branch_lifecycle_event(
            branch=branch,
            event_type="closed",
            actor_user_id=actor_user_id,
            reason=safe_reason,
        )
        return await self._finish_action(
            state,
            resource_type="agency_branch",
            resource=branch,
        )

    async def create_branch_role_grant(
        self,
        *,
        actor_user_id: uuid.UUID,
        branch_id: uuid.UUID,
        data: Any,
        idempotency_key: str,
    ) -> AgencyBranchRoleGrant:
        branch = await self._get_branch(branch_id, for_update=True)
        self._ensure_branch_active(branch)
        await self.authorization.require_agency_wide(
            agency_id=branch.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
            lock_scope=True,
        )
        if data.role not in ALLOWED_BRANCH_GRANT_ROLES:
            raise AgencyTransactionValidationError(
                "branch_role_invalid",
                "owner 和 admin 是旅行社全域角色，不能创建门店授权",
            )
        state = await self._begin_idempotent_action(
            agency_id=branch.agency_id,
            scope="branch_role_grant.create",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "branch_id": branch.id,
                "membership_id": data.membership_id,
                "role": data.role,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyBranchRoleGrant,
                resource_type="agency_branch_role_grant",
                agency_id=branch.agency_id,
            )
        membership_result = await self.db.execute(
            select(AgencyMembership)
            .where(AgencyMembership.id == data.membership_id)
            .where(AgencyMembership.agency_id == branch.agency_id)
            .where(AgencyMembership.status == "active")
            .where(AgencyMembership.role == data.role)
            .with_for_update()
        )
        if membership_result.scalar_one_or_none() is None:
            raise AgencyTransactionValidationError(
                "branch_role_membership_invalid",
                "成员不存在、未激活、跨旅行社或其租户角色不匹配",
            )
        existing_result = await self.db.execute(
            select(AgencyBranchRoleGrant.id)
            .where(AgencyBranchRoleGrant.agency_id == branch.agency_id)
            .where(AgencyBranchRoleGrant.branch_id == branch.id)
            .where(
                AgencyBranchRoleGrant.membership_id == data.membership_id
            )
            .where(AgencyBranchRoleGrant.role == data.role)
            .where(AgencyBranchRoleGrant.status == "active")
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "branch_role_grant_exists",
                "该成员已拥有此门店角色",
            )
        now = self._now()
        grant = AgencyBranchRoleGrant(
            agency_id=branch.agency_id,
            branch_id=branch.id,
            membership_id=data.membership_id,
            role=data.role,
            status="active",
            revision=1,
            granted_by_user_id=actor_user_id,
            granted_at=now,
        )
        self.db.add(grant)
        await self._flush()
        return await self._finish_action(
            state,
            resource_type="agency_branch_role_grant",
            resource=grant,
        )

    async def list_branch_role_grants(
        self,
        *,
        actor_user_id: uuid.UUID,
        branch_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyBranchRoleGrant], int]:
        branch = await self._get_branch(branch_id)
        await self.authorization.require_branch_role(
            agency_id=branch.agency_id,
            branch_id=branch.id,
            actor_user_id=actor_user_id,
            roles=CUSTOMER_MANAGER_ROLES,
            allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
        )
        filters = [
            AgencyBranchRoleGrant.agency_id == branch.agency_id,
            AgencyBranchRoleGrant.branch_id == branch.id,
        ]
        if status_filter is not None:
            filters.append(AgencyBranchRoleGrant.status == status_filter)
        return await self._page(
            statement=select(AgencyBranchRoleGrant)
            .where(*filters)
            .order_by(
                desc(AgencyBranchRoleGrant.created_at),
                desc(AgencyBranchRoleGrant.id),
            )
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyBranchRoleGrant)
            .where(*filters),
        )

    async def revoke_branch_role_grant(
        self,
        *,
        actor_user_id: uuid.UUID,
        branch_id: uuid.UUID,
        grant_id: uuid.UUID,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> AgencyBranchRoleGrant:
        safe_reason = self._safe_reason(reason)
        branch = await self._get_branch(branch_id, for_update=True)
        grant = await self._get_grant(
            branch_id=branch_id,
            grant_id=grant_id,
            for_update=True,
        )
        if grant.agency_id != branch.agency_id:
            raise hidden_not_found()
        await self.authorization.require_agency_wide(
            agency_id=grant.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
            lock_scope=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=grant.agency_id,
            scope="branch_role_grant.revoke",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "branch_id": branch_id,
                "grant_id": grant_id,
                "expected_revision": expected_revision,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_branch_role_grant",
                resource_id=grant.id,
            )
            return grant
        self._ensure_revision(grant.revision, expected_revision)
        if grant.status != "active":
            raise AgencyTransactionConflict(
                "branch_role_grant_state_conflict",
                "只有 active 状态的门店角色授权可以撤销",
            )
        assignment_result = await self.db.execute(
            select(AgencyCustomerAdvisorAssignment.id)
            .where(
                AgencyCustomerAdvisorAssignment.advisor_role_grant_id
                == grant.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
            .limit(1)
        )
        if assignment_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "branch_role_grant_in_use",
                "该顾问仍有有效客户分配，必须先完成客户转移",
            )
        if grant.role == "approver":
            pending_review_participants = (
                select(
                    AgencyOrderReview.requested_by_user_id,
                    AgencyOrder.user_id,
                )
                .join(
                    AgencyOrder,
                    and_(
                        AgencyOrder.agency_id
                        == AgencyOrderReview.agency_id,
                        AgencyOrder.branch_id
                        == AgencyOrderReview.branch_id,
                        AgencyOrder.id == AgencyOrderReview.order_id,
                    ),
                )
                .where(AgencyOrderReview.agency_id == grant.agency_id)
                .where(AgencyOrderReview.branch_id == grant.branch_id)
                .where(AgencyOrderReview.status == "pending")
            )
            pending_cancellation_participants = (
                select(
                    AgencyOrderCancellationCase.requested_by_user_id,
                    AgencyOrder.user_id,
                )
                .join(
                    AgencyOrder,
                    and_(
                        AgencyOrder.agency_id
                        == AgencyOrderCancellationCase.agency_id,
                        AgencyOrder.branch_id
                        == AgencyOrderCancellationCase.branch_id,
                        AgencyOrder.id
                        == AgencyOrderCancellationCase.order_id,
                    ),
                )
                .where(
                    AgencyOrderCancellationCase.agency_id == grant.agency_id
                )
                .where(
                    AgencyOrderCancellationCase.branch_id == grant.branch_id
                )
                .where(
                    AgencyOrderCancellationCase.status == "approval_pending"
                )
            )
            pending_result = await self.db.execute(
                pending_review_participants.union_all(
                    pending_cancellation_participants
                )
            )
            pending_participants = pending_result.all()
            if pending_participants:
                replacement_result = await self.db.execute(
                    select(AgencyMembership.user_id)
                    .join(
                        AgencyBranchRoleGrant,
                        and_(
                            AgencyBranchRoleGrant.agency_id
                            == AgencyMembership.agency_id,
                            AgencyBranchRoleGrant.membership_id
                            == AgencyMembership.id,
                        ),
                    )
                    .where(
                        AgencyBranchRoleGrant.agency_id == grant.agency_id
                    )
                    .where(
                        AgencyBranchRoleGrant.branch_id == grant.branch_id
                    )
                    .where(AgencyBranchRoleGrant.role == "approver")
                    .where(AgencyBranchRoleGrant.status == "active")
                    .where(AgencyBranchRoleGrant.id != grant.id)
                    .where(AgencyMembership.role == "approver")
                    .where(AgencyMembership.status == "active")
                )
                replacement_user_ids = set(
                    replacement_result.scalars().all()
                )
                uncovered_approval_exists = any(
                    not (
                        replacement_user_ids
                        - {requester_user_id, customer_user_id}
                    )
                    for requester_user_id, customer_user_id
                    in pending_participants
                )
                if uncovered_approval_exists:
                    raise AgencyTransactionConflict(
                        "branch_approver_grant_in_use",
                        "该门店仍有待审批业务，必须保留与发起人、客户相互独立的审批员",
                    )
        grant.status = "revoked"
        grant.revoked_at = self._now()
        grant.revocation_reason = safe_reason
        await self._flush()
        return await self._finish_action(
            state,
            resource_type="agency_branch_role_grant",
            resource=grant,
        )

    async def _append_branch_lifecycle_event(
        self,
        *,
        branch: AgencyBranch,
        event_type: str,
        actor_user_id: uuid.UUID,
        reason: str,
    ) -> AgencyBranchLifecycleEvent:
        sequence_result = await self.db.execute(
            select(
                func.coalesce(
                    func.max(AgencyBranchLifecycleEvent.event_sequence),
                    0,
                )
            )
            .where(
                AgencyBranchLifecycleEvent.agency_id == branch.agency_id
            )
            .where(AgencyBranchLifecycleEvent.branch_id == branch.id)
        )
        event = AgencyBranchLifecycleEvent(
            agency_id=branch.agency_id,
            branch_id=branch.id,
            event_sequence=int(sequence_result.scalar_one()) + 1,
            branch_revision=branch.revision,
            event_type=event_type,
            actor_user_id=actor_user_id,
            reason=reason,
        )
        self.db.add(event)
        return event

    async def _branch_closure_readiness(
        self,
        branch: AgencyBranch,
    ) -> BranchClosureReadiness:
        async def count(statement: Any) -> int:
            result = await self.db.execute(statement)
            return int(result.scalar_one())

        current_customer_count = await count(
            select(func.count())
            .select_from(AgencyCustomer)
            .where(AgencyCustomer.agency_id == branch.agency_id)
            .where(AgencyCustomer.branch_id == branch.id)
        )
        pending_invitation_count = await count(
            select(func.count())
            .select_from(AgencyCustomerInvitation)
            .where(
                AgencyCustomerInvitation.agency_id == branch.agency_id
            )
            .where(AgencyCustomerInvitation.branch_id == branch.id)
            .where(AgencyCustomerInvitation.status == "pending")
        )
        active_assignment_count = await count(
            select(func.count())
            .select_from(AgencyCustomerAdvisorAssignment)
            .where(
                AgencyCustomerAdvisorAssignment.agency_id
                == branch.agency_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.branch_id == branch.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
        )
        active_role_grant_count = await count(
            select(func.count())
            .select_from(AgencyBranchRoleGrant)
            .where(AgencyBranchRoleGrant.agency_id == branch.agency_id)
            .where(AgencyBranchRoleGrant.branch_id == branch.id)
            .where(AgencyBranchRoleGrant.status == "active")
        )
        pending_review_count = await count(
            select(func.count())
            .select_from(AgencyOrderReview)
            .where(AgencyOrderReview.agency_id == branch.agency_id)
            .where(AgencyOrderReview.branch_id == branch.id)
            .where(AgencyOrderReview.status == "pending")
        )
        accepted_without_order = and_(
            AgencyQuote.status == "accepted",
            ~exists(
                select(AgencyOrder.id)
                .where(AgencyOrder.agency_id == AgencyQuote.agency_id)
                .where(AgencyOrder.quote_id == AgencyQuote.id)
            ),
        )
        open_quote_count = await count(
            select(func.count())
            .select_from(AgencyQuote)
            .where(AgencyQuote.agency_id == branch.agency_id)
            .where(AgencyQuote.branch_id == branch.id)
            .where(
                or_(
                    AgencyQuote.status.in_(("draft", "offered")),
                    accepted_without_order,
                )
            )
        )
        open_order_count = await count(
            select(func.count())
            .select_from(AgencyOrder)
            .where(AgencyOrder.agency_id == branch.agency_id)
            .where(AgencyOrder.branch_id == branch.id)
            .where(
                AgencyOrder.status.not_in(
                    ("review_rejected", "completed", "cancelled")
                )
            )
        )
        open_cancellation_case_count = await count(
            select(func.count())
            .select_from(AgencyOrderCancellationCase)
            .where(
                AgencyOrderCancellationCase.agency_id == branch.agency_id
            )
            .where(
                AgencyOrderCancellationCase.branch_id == branch.id
            )
            .where(
                AgencyOrderCancellationCase.status.in_(
                    (
                        "approval_pending",
                        "action_pending",
                        "reconciliation_pending",
                        "manual_intervention",
                    )
                )
            )
        )
        blocker_counts = (
            current_customer_count,
            pending_invitation_count,
            active_assignment_count,
            active_role_grant_count,
            pending_review_count,
            open_quote_count,
            open_order_count,
            open_cancellation_case_count,
        )
        return BranchClosureReadiness(
            branch_id=branch.id,
            status=branch.status,
            revision=branch.revision,
            ready=branch.status == "inactive" and not any(blocker_counts),
            current_customer_count=current_customer_count,
            pending_invitation_count=pending_invitation_count,
            active_assignment_count=active_assignment_count,
            active_role_grant_count=active_role_grant_count,
            pending_review_count=pending_review_count,
            open_quote_count=open_quote_count,
            open_order_count=open_order_count,
            open_cancellation_case_count=open_cancellation_case_count,
        )
