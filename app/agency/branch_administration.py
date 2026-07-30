"""旅行社门店与门店角色授权管理服务。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, func, select

from app.agency.branch_authorization import (
    ALLOWED_BRANCH_GRANT_ROLES,
    CUSTOMER_MANAGER_ROLES,
)
from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.models.agency_customer_lifecycle import (
    AgencyBranch,
    AgencyBranchRoleGrant,
    AgencyCustomerAdvisorAssignment,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import AgencyMembership


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
            pending_result = await self.db.execute(
                select(AgencyOrderReview.id)
                .where(AgencyOrderReview.agency_id == grant.agency_id)
                .where(AgencyOrderReview.branch_id == grant.branch_id)
                .where(AgencyOrderReview.status == "pending")
                .limit(1)
            )
            if pending_result.scalar_one_or_none() is not None:
                replacement_result = await self.db.execute(
                    select(AgencyBranchRoleGrant.id)
                    .where(
                        AgencyBranchRoleGrant.agency_id == grant.agency_id
                    )
                    .where(
                        AgencyBranchRoleGrant.branch_id == grant.branch_id
                    )
                    .where(AgencyBranchRoleGrant.role == "approver")
                    .where(AgencyBranchRoleGrant.status == "active")
                    .where(AgencyBranchRoleGrant.id != grant.id)
                    .limit(1)
                )
                if replacement_result.scalar_one_or_none() is None:
                    raise AgencyTransactionConflict(
                        "branch_approver_grant_in_use",
                        "该门店仍有待审核订单，必须先完成审核或保留另一名审批员",
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
