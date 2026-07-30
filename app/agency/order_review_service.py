"""旅行社订单内部审核服务。"""
from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select

from app.agency.errors import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionPersistenceError,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.agency.transaction_service import (
    AgencyTransactionService,
    IdempotencyState,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import AgencyMembership, AgencyOrder
from app.utils.security import redact_sensitive_text


ORDER_REVIEWER_ROLES = frozenset({"approver"})


class AgencyOrderReviewService(AgencyTransactionService):
    """在报价与订单服务上增加强类型、四眼制的内部审核。"""

    async def _require_order_reviewer(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        hide_resource: bool,
        lock_scope: bool = False,
    ) -> AgencyMembership:
        access = await self.authorization.require_branch_approver(
            agency_id=agency_id,
            branch_id=branch_id,
            actor_user_id=actor_user_id,
            hide_resource=hide_resource,
            lock_scope=lock_scope,
        )
        return access.membership

    async def _load_replayed_order_review(
        self,
        state: IdempotencyState,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> AgencyOrderReview:
        if state.record.resource_type != "agency_order_review":
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录不属于订单审核资源",
            )
        try:
            resource_id = uuid.UUID(str(state.record.resource_id))
        except (TypeError, ValueError) as error:
            raise AgencyTransactionPersistenceError(
                "idempotency_resource_missing",
                "幂等记录缺少有效的订单审核资源",
            ) from error
        result = await self.db.execute(
            select(AgencyOrderReview)
            .where(AgencyOrderReview.id == resource_id)
            .where(AgencyOrderReview.agency_id == agency_id)
            .where(AgencyOrderReview.branch_id == branch_id)
            .where(AgencyOrderReview.order_id == order_id)
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise AgencyTransactionPersistenceError(
                "idempotency_resource_missing",
                "幂等记录对应的订单审核资源不存在",
            )
        return review

    async def _get_order_review(
        self,
        order_id: uuid.UUID,
        *,
        agency_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        for_update: bool = False,
    ) -> AgencyOrderReview:
        statement = (
            select(AgencyOrderReview)
            .where(AgencyOrderReview.order_id == order_id)
            .order_by(desc(AgencyOrderReview.order_revision))
            .limit(1)
        )
        if agency_id is not None:
            statement = statement.where(
                AgencyOrderReview.agency_id == agency_id
            )
        if branch_id is not None:
            statement = statement.where(
                AgencyOrderReview.branch_id == branch_id
            )
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        review = result.scalar_one_or_none()
        if review is None:
            raise hidden_not_found()
        return review

    @staticmethod
    def _ensure_order_review_binding(
        order: AgencyOrder,
        review: AgencyOrderReview,
    ) -> None:
        binding_matches = (
            review.agency_id == order.agency_id
            and review.branch_id == order.branch_id
            and review.order_id == order.id
            and review.order_revision == order.revision
            and review.payload_hash == order.payload_hash
            and review.total_amount == order.total_amount
            and review.currency == order.currency
        )
        if not binding_matches:
            raise AgencyTransactionConflict(
                "order_review_binding_mismatch",
                "订单审核绑定的数据已变化，必须重新报价并创建新订单",
            )

    async def list_order_reviews(
        self,
        *,
        actor_user_id: uuid.UUID,
        agency_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyOrderReview], int]:
        membership = await self._get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if membership is None or membership.role not in ORDER_REVIEWER_ROLES:
            raise AgencyTransactionAccessDenied(
                "agency_order_review_permission_denied",
                "只有本旅行社具备门店授权的专职审批员可以查看审核队列",
            )
        visibility = await self.authorization.branch_visibility_filter(
            agency_id=agency_id,
            actor_user_id=actor_user_id,
            roles=ORDER_REVIEWER_ROLES,
            branch_column=AgencyOrderReview.branch_id,
        )
        filters = [
            AgencyOrderReview.agency_id == agency_id,
            visibility,
        ]
        if status_filter is not None:
            filters.append(AgencyOrderReview.status == status_filter)
        return await self._page(
            statement=select(AgencyOrderReview)
            .where(*filters)
            .order_by(
                desc(AgencyOrderReview.created_at),
                desc(AgencyOrderReview.id),
            )
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyOrderReview)
            .where(*filters),
        )

    async def get_order_review(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> AgencyOrderReview:
        order = await self._get_order(order_id)
        await self._require_order_reviewer(
            agency_id=order.agency_id,
            branch_id=order.branch_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
        )
        return await self._get_order_review(
            order.id,
            agency_id=order.agency_id,
            branch_id=order.branch_id,
        )

    async def decide_order_review(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        decision: str,
        expected_revision: int,
        reason: str | None,
        idempotency_key: str,
    ) -> AgencyOrderReview:
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"approve", "reject"}:
            raise AgencyTransactionValidationError(
                "order_review_decision_invalid",
                "订单审核决定只能是 approve 或 reject",
            )
        normalized_reason = str(reason or "").strip() or None
        if normalized_decision == "reject" and normalized_reason is None:
            raise AgencyTransactionValidationError(
                "order_review_reason_required",
                "拒绝订单审核时必须填写原因",
            )

        order_preview = await self._get_order(order_id)
        binding = self._transaction_binding(order_preview)
        if normalized_decision == "approve":
            customer = await self._get_transaction_customer(
                agency_id=binding[0],
                branch_id=binding[1],
                customer_id=binding[2],
                for_update=True,
            )
        else:
            customer = await self._get_customer_binding(
                agency_id=binding[0],
                branch_id=binding[1],
                customer_id=binding[2],
                for_update=True,
            )
        self._ensure_customer_binding(customer, binding)
        await self._require_order_reviewer(
            agency_id=binding[0],
            branch_id=binding[1],
            actor_user_id=actor_user_id,
            hide_resource=True,
            lock_scope=True,
        )
        order = await self._get_order(order_id, for_update=True)
        self._ensure_transaction_binding(order, binding)
        await self._ensure_agency_active(order.agency_id)
        state = await self._begin_idempotent_action(
            agency_id=order.agency_id,
            scope="order.review.decide",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "order_id": order_id,
                "decision": normalized_decision,
                "expected_revision": expected_revision,
                "reason": normalized_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_order_review(
                state,
                agency_id=order.agency_id,
                branch_id=order.branch_id,
                order_id=order.id,
            )

        review = await self._get_order_review(
            order.id,
            agency_id=order.agency_id,
            branch_id=order.branch_id,
            for_update=True,
        )
        self._ensure_revision(order.revision, expected_revision)
        if order.status != "pending_review" or review.status != "pending":
            raise AgencyTransactionConflict(
                "order_review_state_conflict",
                "只有 pending_review 订单的 pending 审核可以处理",
            )
        if (
            actor_user_id == order.user_id
            or actor_user_id == review.requested_by_user_id
        ):
            raise AgencyTransactionAccessDenied(
                "order_review_self_decision_denied",
                "订单客户或审核发起人不能审批自己的订单",
            )
        self._ensure_order_review_binding(order, review)
        if (
            order.external_action_enabled
            or order.payment_status != "not_started"
            or order.fulfillment_status != "not_started"
        ):
            raise AgencyTransactionConflict(
                "order_review_external_state_conflict",
                "订单已进入外部交易状态，不能继续执行内部审核",
            )

        from_status = order.status
        order.status = (
            "approved"
            if normalized_decision == "approve"
            else "review_rejected"
        )
        await self._flush()

        review.status = (
            "approved"
            if normalized_decision == "approve"
            else "rejected"
        )
        review.decision_order_revision = order.revision
        review.decided_by_user_id = actor_user_id
        review.decision_reason = (
            redact_sensitive_text(normalized_reason)
            if normalized_reason
            else None
        )
        review.decided_at = self._now()
        await self._append_order_event(
            order=order,
            event_type=f"order_review_{review.status}",
            from_status=from_status,
            to_status=order.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "review_id": str(review.id),
                "review_order_revision": review.order_revision,
                "decision_order_revision": review.decision_order_revision,
                "external_actions_triggered": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_order_review",
            resource=review,
        )
