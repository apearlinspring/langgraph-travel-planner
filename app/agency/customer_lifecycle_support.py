"""客户生命周期服务的内部查询与事件辅助方法。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.models.agency_customer_lifecycle import (
    AgencyBranch,
    AgencyBranchRoleGrant,
    AgencyCustomer,
    AgencyCustomerAdvisorAssignment,
    AgencyCustomerEvent,
)
from app.utils.security import redact_sensitive_text


class CustomerLifecycleSupportMixin:
    """封装客户生命周期服务复用的底层辅助操作。"""

    async def _get_branch(
        self,
        branch_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyBranch:
        statement = select(AgencyBranch).where(AgencyBranch.id == branch_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        branch = result.scalar_one_or_none()
        if branch is None:
            raise hidden_not_found()
        return branch

    async def _get_grant(
        self,
        *,
        branch_id: uuid.UUID,
        grant_id: uuid.UUID,
        for_update: bool = False,
    ) -> AgencyBranchRoleGrant:
        statement = (
            select(AgencyBranchRoleGrant)
            .where(AgencyBranchRoleGrant.id == grant_id)
            .where(AgencyBranchRoleGrant.branch_id == branch_id)
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        grant = result.scalar_one_or_none()
        if grant is None:
            raise hidden_not_found()
        return grant

    async def _get_customer(
        self,
        customer_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyCustomer:
        statement = select(AgencyCustomer).where(
            AgencyCustomer.id == customer_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        customer = result.scalar_one_or_none()
        if customer is None:
            raise hidden_not_found()
        return customer

    @staticmethod
    def _ensure_branch_active(branch: AgencyBranch) -> None:
        if branch.status != "active":
            raise AgencyTransactionConflict(
                "agency_branch_not_active",
                "门店当前不可执行写操作",
            )

    @staticmethod
    def _safe_reason(reason: str) -> str:
        safe_reason = redact_sensitive_text(str(reason or "")).strip()
        if not safe_reason:
            raise AgencyTransactionValidationError(
                "reason_required",
                "原因不能为空",
            )
        return safe_reason[:500]

    async def _append_customer_event(
        self,
        *,
        customer: AgencyCustomer,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        actor_user_id: uuid.UUID | None,
        event_metadata: dict[str, Any],
    ) -> AgencyCustomerEvent:
        sequence_result = await self.db.execute(
            select(
                func.coalesce(
                    func.max(AgencyCustomerEvent.event_sequence),
                    0,
                )
            )
            .where(AgencyCustomerEvent.agency_id == customer.agency_id)
            .where(AgencyCustomerEvent.branch_id == customer.branch_id)
            .where(AgencyCustomerEvent.customer_id == customer.id)
        )
        event = AgencyCustomerEvent(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            customer_id=customer.id,
            event_sequence=int(sequence_result.scalar_one()) + 1,
            customer_revision=customer.lifecycle_revision,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            event_metadata=event_metadata,
        )
        self.db.add(event)
        return event

    async def _end_active_assignment(
        self,
        *,
        customer: AgencyCustomer,
        ended_at: datetime,
        reason: str,
    ) -> AgencyCustomerAdvisorAssignment | None:
        result = await self.db.execute(
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
        assignment = result.scalar_one_or_none()
        if assignment is not None:
            assignment.status = "ended"
            assignment.ended_at = ended_at
            assignment.ended_reason = reason
        return assignment
