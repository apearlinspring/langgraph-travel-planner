"""客户关系停用时的内部交易收口。

这里仅收紧平台内部报价与订单状态，不调用供应商、支付或退款适配器。
因此内部 ``cancelled`` 绝不代表供应商侧已经取消，也不代表已经退款。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.models.agency_customer_lifecycle import AgencyBranch, AgencyCustomer
from app.models.agency_transaction import AgencyOrder, AgencyQuote


class CustomerTransactionSettlementMixin:
    """为已持有客户行锁的生命周期命令收口内部交易。"""

    db: Any

    @staticmethod
    def _settlement_event_metadata(
        customer: AgencyCustomer,
    ) -> dict[str, Any]:
        return {
            "customer_id": str(customer.id),
            "external_actions_triggered": False,
            "supplier_cancellation_confirmed": False,
            "refund_confirmed": False,
        }

    async def _settle_customer_transactions(
        self,
        *,
        customer: AgencyCustomer,
        actor_user_id: uuid.UUID,
    ) -> dict[str, int | list[str]]:
        """按固定锁顺序收口客户的报价与订单，并返回审计摘要。

        调用方必须已用 ``FOR UPDATE`` 锁定 ``customer``。本方法随后按
        门店 ``FOR SHARE``、报价 ``FOR UPDATE``、订单 ``FOR UPDATE`` 的
        顺序加锁，避免同一客户的生命周期命令与交易写入交错。
        """

        with self.db.no_autoflush:
            branch_result = await self.db.execute(
                select(AgencyBranch.id)
                .where(AgencyBranch.agency_id == customer.agency_id)
                .where(AgencyBranch.id == customer.branch_id)
                .with_for_update(read=True)
            )
            branch_result.scalar_one()

            quote_result = await self.db.execute(
                select(AgencyQuote)
                .where(AgencyQuote.agency_id == customer.agency_id)
                .where(AgencyQuote.branch_id == customer.branch_id)
                .where(AgencyQuote.customer_id == customer.id)
                .order_by(AgencyQuote.id)
                .with_for_update()
            )
            quotes = list(quote_result.scalars().all())

            order_result = await self.db.execute(
                select(AgencyOrder)
                .where(AgencyOrder.agency_id == customer.agency_id)
                .where(AgencyOrder.branch_id == customer.branch_id)
                .where(AgencyOrder.customer_id == customer.id)
                .order_by(AgencyOrder.id)
                .with_for_update()
            )
            orders = list(order_result.scalars().all())
        ordered_quote_ids = {order.quote_id for order in orders}

        cancelled_quote_ids: list[str] = []
        for quote in quotes:
            should_cancel = quote.status in {"draft", "offered"} or (
                quote.status == "accepted"
                and quote.id not in ordered_quote_ids
            )
            if should_cancel:
                quote.status = "cancelled"
                cancelled_quote_ids.append(str(quote.id))
        if cancelled_quote_ids:
            await self._flush()

        cancelled_order_ids: list[str] = []
        cancellation_pending_order_ids: list[str] = []
        pending_review_order_ids: list[str] = []
        action_required_order_ids: list[str] = []
        event_metadata = self._settlement_event_metadata(customer)
        now = self._now()

        for order in orders:
            from_status = order.status
            pristine_internal_order = (
                order.external_action_enabled is False
                and order.payment_status == "not_started"
                and order.fulfillment_status == "not_started"
            )
            if (
                from_status in {"draft", "approved"}
                and pristine_internal_order
            ):
                order.status = "cancelled"
                order.cancellation_requested_at = now
                order.cancelled_at = now
                await self._flush()
                await self._append_order_event(
                    order=order,
                    event_type="order_customer_relationship_deactivated",
                    from_status=from_status,
                    to_status=order.status,
                    actor_user_id=actor_user_id,
                    event_metadata=event_metadata,
                )
                cancelled_order_ids.append(str(order.id))
            elif from_status == "pending_review":
                await self._append_order_event(
                    order=order,
                    event_type="order_customer_relationship_deactivated",
                    from_status=from_status,
                    to_status=from_status,
                    actor_user_id=actor_user_id,
                    event_metadata=event_metadata,
                )
                pending_review_order_ids.append(str(order.id))
            elif from_status in {
                "draft",
                "approved",
                "processing",
                "failed",
            }:
                order.status = "cancellation_pending"
                order.cancellation_requested_at = now
                order.cancelled_at = None
                await self._flush()
                await self._append_order_event(
                    order=order,
                    event_type="order_customer_relationship_deactivated",
                    from_status=from_status,
                    to_status=order.status,
                    actor_user_id=actor_user_id,
                    event_metadata=event_metadata,
                )
                cancellation_pending_order_ids.append(str(order.id))
            elif from_status in {
                "manual_intervention",
                "cancellation_pending",
            }:
                await self._append_order_event(
                    order=order,
                    event_type="order_customer_relationship_action_required",
                    from_status=from_status,
                    to_status=from_status,
                    actor_user_id=actor_user_id,
                    event_metadata=event_metadata,
                )
                action_required_order_ids.append(str(order.id))

        return {
            "cancelled_quote_count": len(cancelled_quote_ids),
            "cancelled_quote_ids": cancelled_quote_ids,
            "cancelled_order_count": len(cancelled_order_ids),
            "cancelled_order_ids": cancelled_order_ids,
            "cancellation_pending_order_count": len(
                cancellation_pending_order_ids
            ),
            "cancellation_pending_order_ids": (
                cancellation_pending_order_ids
            ),
            "pending_review_order_count": len(pending_review_order_ids),
            "pending_review_order_ids": pending_review_order_ids,
            "action_required_order_count": len(action_required_order_ids),
            "action_required_order_ids": action_required_order_ids,
            "external_cancellation_count": 0,
            "refund_count": 0,
        }
