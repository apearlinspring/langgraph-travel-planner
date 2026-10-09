"""旅行社客户当前服务门店转移。

转店只改变客户的当前服务门店和可选主顾问，不改写邀请、同意、事件、
报价、订单或取消记录的历史门店。首版仅允许旅行社 ``owner/admin``
执行，跨门店经理交接审批不在本模块内暗含实现。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, exists, or_, select

from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.models.agency_cancellation import AgencyOrderCancellationCase
from app.models.agency_customer_identity import AgencyCustomerInvitation
from app.models.agency_customer_lifecycle import (
    AgencyBranch,
    AgencyBranchRoleGrant,
    AgencyCustomer,
    AgencyCustomerAdvisorAssignment,
    AgencyCustomerBranchTransfer,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import (
    AgencyMembership,
    AgencyOrder,
    AgencyQuote,
)


OPEN_ORDER_STATUSES = frozenset(
    {
        "draft",
        "pending_review",
        "approved",
        "processing",
        "manual_intervention",
        "failed",
        "cancellation_pending",
    }
)
OPEN_CANCELLATION_STATUSES = frozenset(
    {
        "approval_pending",
        "action_pending",
        "reconciliation_pending",
        "manual_intervention",
    }
)


class CustomerBranchTransferMixin:
    """原子完成客户当前门店与主顾问迁移。"""

    async def transfer_customer_branch(
        self,
        *,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        expected_revision: int,
        target_branch_id: uuid.UUID,
        target_advisor_role_grant_id: uuid.UUID | None,
        reason: str,
        idempotency_key: str,
    ) -> AgencyCustomerBranchTransfer:
        safe_reason = self._safe_reason(reason)
        customer = await self._get_customer(customer_id, for_update=True)

        # 重放也必须重新验证当前调用者仍是该旅行社的全域管理员。
        await self.authorization.require_agency_wide(
            agency_id=customer.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
        )
        state = await self._begin_idempotent_action(
            agency_id=customer.agency_id,
            scope="customer.branch_transfer",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "customer_id": customer.id,
                "expected_revision": expected_revision,
                "target_branch_id": target_branch_id,
                "target_advisor_role_grant_id": (
                    target_advisor_role_grant_id
                ),
                "reason": safe_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_resource(
                state,
                model=AgencyCustomerBranchTransfer,
                resource_type="agency_customer_branch_transfer",
                agency_id=customer.agency_id,
                resource_label="客户转店记录",
            )

        self._ensure_revision(
            customer.lifecycle_revision,
            expected_revision,
        )
        if target_branch_id == customer.branch_id:
            raise AgencyTransactionValidationError(
                "customer_branch_transfer_same_branch",
                "目标门店不能与客户当前门店相同",
            )

        source_branch_id = customer.branch_id
        branch_result = await self.db.execute(
            select(AgencyBranch)
            .where(AgencyBranch.agency_id == customer.agency_id)
            .where(AgencyBranch.id.in_((source_branch_id, target_branch_id)))
            .order_by(AgencyBranch.id)
            .with_for_update()
        )
        branches = {branch.id: branch for branch in branch_result.scalars()}
        source_branch = branches.get(source_branch_id)
        target_branch = branches.get(target_branch_id)
        if (
            source_branch is None
            or target_branch is None
            or source_branch.agency_id != customer.agency_id
            or target_branch.agency_id != customer.agency_id
        ):
            raise hidden_not_found()
        if source_branch.status not in {"active", "inactive"}:
            raise AgencyTransactionConflict(
                "customer_branch_transfer_state_conflict",
                "客户只能从 active 或 inactive 门店转出",
            )
        if target_branch.status != "active":
            raise AgencyTransactionValidationError(
                "customer_branch_transfer_target_invalid",
                "目标门店不存在、跨旅行社或不是 active 状态",
            )

        # 固定授权所依赖的成员范围，锁顺序保持 customer -> branches -> membership。
        await self.authorization.require_agency_wide(
            agency_id=customer.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
            lock_scope=True,
        )
        await self._ensure_customer_transfer_has_no_open_work(customer)

        duplicate_number_result = await self.db.execute(
            select(AgencyCustomer.id)
            .where(AgencyCustomer.agency_id == customer.agency_id)
            .where(AgencyCustomer.branch_id == target_branch.id)
            .where(AgencyCustomer.customer_no == customer.customer_no)
            .where(AgencyCustomer.id != customer.id)
            .limit(1)
        )
        if duplicate_number_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "customer_branch_transfer_number_conflict",
                "目标门店已存在相同客户编号，请先处理编号冲突",
            )

        target_grant = None
        if target_advisor_role_grant_id is not None:
            if customer.status != "active":
                raise AgencyTransactionValidationError(
                    "customer_branch_transfer_advisor_invalid",
                    "只有 active 客户可以在转店时建立新的主顾问分配",
                )
            grant_result = await self.db.execute(
                select(AgencyBranchRoleGrant)
                .join(
                    AgencyMembership,
                    and_(
                        AgencyMembership.agency_id
                        == AgencyBranchRoleGrant.agency_id,
                        AgencyMembership.id
                        == AgencyBranchRoleGrant.membership_id,
                    ),
                )
                .where(
                    AgencyBranchRoleGrant.id
                    == target_advisor_role_grant_id
                )
                .where(
                    AgencyBranchRoleGrant.agency_id == customer.agency_id
                )
                .where(
                    AgencyBranchRoleGrant.branch_id == target_branch.id
                )
                .where(AgencyBranchRoleGrant.role == "travel_advisor")
                .where(AgencyBranchRoleGrant.status == "active")
                .where(AgencyMembership.status == "active")
                .where(AgencyMembership.role == "travel_advisor")
                .with_for_update()
            )
            target_grant = grant_result.scalar_one_or_none()
            if target_grant is None:
                raise AgencyTransactionValidationError(
                    "customer_branch_transfer_advisor_invalid",
                    "目标主顾问授权不存在、未激活或不属于目标门店",
                )

        now = self._now()
        current_assignment_result = await self.db.execute(
            select(AgencyCustomerAdvisorAssignment)
            .where(
                AgencyCustomerAdvisorAssignment.agency_id
                == customer.agency_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.customer_id == customer.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
            .with_for_update()
        )
        current_assignment = current_assignment_result.scalar_one_or_none()
        if current_assignment is not None:
            current_assignment.status = "ended"
            current_assignment.ended_at = now
            current_assignment.ended_reason = safe_reason

        next_revision = customer.lifecycle_revision + 1
        transfer = AgencyCustomerBranchTransfer(
            agency_id=customer.agency_id,
            customer_id=customer.id,
            from_branch_id=source_branch.id,
            to_branch_id=target_branch.id,
            customer_revision=next_revision,
            transferred_by_user_id=actor_user_id,
            reason=safe_reason,
            transferred_at=now,
        )
        self.db.add(transfer)
        customer.branch_id = target_branch.id
        customer.lifecycle_revision = next_revision
        customer.updated_at = now

        new_assignment = None
        if target_grant is not None:
            new_assignment = AgencyCustomerAdvisorAssignment(
                agency_id=customer.agency_id,
                branch_id=target_branch.id,
                customer_id=customer.id,
                advisor_role_grant_id=target_grant.id,
                advisor_membership_id=target_grant.membership_id,
                status="active",
                revision=1,
                assigned_by_user_id=actor_user_id,
                assignment_reason=safe_reason,
                assigned_at=now,
            )
            self.db.add(new_assignment)

        await self._flush()
        await self._append_customer_event(
            customer=customer,
            event_type="customer_branch_transferred",
            from_status=customer.status,
            to_status=customer.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "transfer_id": str(transfer.id),
                "from_branch_id": str(source_branch.id),
                "to_branch_id": str(target_branch.id),
                "ended_assignment_id": (
                    str(current_assignment.id)
                    if current_assignment is not None
                    else None
                ),
                "new_assignment_id": (
                    str(new_assignment.id)
                    if new_assignment is not None
                    else None
                ),
                "reason": safe_reason,
                "external_action_triggered": False,
                "notification_sent": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_customer_branch_transfer",
            resource=transfer,
        )

    async def _ensure_customer_transfer_has_no_open_work(
        self,
        customer: Any,
    ) -> None:
        pending_invitation_result = await self.db.execute(
            select(AgencyCustomerInvitation.id)
            .where(
                AgencyCustomerInvitation.agency_id == customer.agency_id
            )
            .where(AgencyCustomerInvitation.customer_id == customer.id)
            .where(AgencyCustomerInvitation.status == "pending")
            .limit(1)
            .with_for_update()
        )
        if pending_invitation_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "customer_branch_transfer_pending_invitation",
                "客户仍有待认领邀请，必须先撤销或完成认领",
            )

        unbound_accepted_quote = and_(
            AgencyQuote.status == "accepted",
            ~exists(
                select(AgencyOrder.id)
                .where(AgencyOrder.agency_id == AgencyQuote.agency_id)
                .where(AgencyOrder.quote_id == AgencyQuote.id)
            ),
        )
        quote_result = await self.db.execute(
            select(AgencyQuote.id)
            .where(AgencyQuote.agency_id == customer.agency_id)
            .where(AgencyQuote.customer_id == customer.id)
            .where(
                or_(
                    AgencyQuote.status.in_(("draft", "offered")),
                    unbound_accepted_quote,
                )
            )
            .limit(1)
            .with_for_update()
        )
        order_result = await self.db.execute(
            select(AgencyOrder.id)
            .where(AgencyOrder.agency_id == customer.agency_id)
            .where(AgencyOrder.customer_id == customer.id)
            .where(AgencyOrder.status.in_(tuple(OPEN_ORDER_STATUSES)))
            .limit(1)
            .with_for_update()
        )
        review_result = await self.db.execute(
            select(AgencyOrderReview.id)
            .join(
                AgencyOrder,
                and_(
                    AgencyOrder.agency_id == AgencyOrderReview.agency_id,
                    AgencyOrder.branch_id == AgencyOrderReview.branch_id,
                    AgencyOrder.id == AgencyOrderReview.order_id,
                ),
            )
            .where(AgencyOrder.agency_id == customer.agency_id)
            .where(AgencyOrder.customer_id == customer.id)
            .where(AgencyOrderReview.status == "pending")
            .limit(1)
            .with_for_update()
        )
        cancellation_result = await self.db.execute(
            select(AgencyOrderCancellationCase.id)
            .where(
                AgencyOrderCancellationCase.agency_id == customer.agency_id
            )
            .where(
                AgencyOrderCancellationCase.customer_id == customer.id
            )
            .where(
                AgencyOrderCancellationCase.status.in_(
                    tuple(OPEN_CANCELLATION_STATUSES)
                )
            )
            .limit(1)
            .with_for_update()
        )
        blockers = (
            quote_result.scalar_one_or_none(),
            order_result.scalar_one_or_none(),
            review_result.scalar_one_or_none(),
            cancellation_result.scalar_one_or_none(),
        )
        if any(blocker is not None for blocker in blockers):
            raise AgencyTransactionConflict(
                "customer_branch_transfer_open_work",
                "客户仍有开放报价、订单、审核或取消业务，必须先完成清理",
            )
