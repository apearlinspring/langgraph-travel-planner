"""旅行社订单人工取消、补偿结果与独立对账服务。

本模块只编排人工流程和保存摘要证据，不调用供应商、支付、退款或通知
适配器，也不会开启任何 external-action 标记。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, desc, func, or_, select

from app.agency.cancellation_support import (
    _CASE_OPERATION_ROLES,
    _REQUIRED_ACTIONS,
    CancellationSupportMixin,
)
from app.agency.errors import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionPersistenceError,
    AgencyTransactionValidationError,
)
from app.agency.transaction_service import AgencyTransactionService
from app.models.agency_cancellation import (
    AgencyOrderCancellationCase,
    AgencyOrderCancellationEvent,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)
from app.models.agency_transaction import AgencyOrder


class CancellationService(
    CancellationSupportMixin,
    AgencyTransactionService,
):
    """在同一数据库事务内推进订单人工取消状态机。"""

    async def request_cancellation(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        expected_revision: int,
        reason_code: str,
        reason_detail: str | None,
        idempotency_key: str,
    ) -> AgencyOrderCancellationCase:
        normalized_reason_code = self._reason_code(reason_code)
        safe_reason_detail = self._safe_optional_text(reason_detail)
        _, order, payments, fulfillments = await self._lock_order_context(
            order_id=order_id,
            actor_user_id=actor_user_id,
            permission="request",
        )
        state = await self._begin_idempotent_action(
            agency_id=order.agency_id,
            scope="order.cancellation.request",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "order_id": order.id,
                "expected_revision": expected_revision,
                "reason_code": normalized_reason_code,
                "reason_detail": safe_reason_detail,
            },
        )
        if state.replayed:
            return await self._load_replayed_case(
                state,
                agency_id=order.agency_id,
                order_id=order.id,
            )
        excluded_approver_ids = (
            (actor_user_id,)
            if actor_user_id == order.user_id
            else (actor_user_id, order.user_id)
        )
        await self._ensure_agency_active(order.agency_id)
        await self._ensure_branch_has_active_approver(
            agency_id=order.agency_id,
            branch_id=order.branch_id,
            excluded_user_ids=excluded_approver_ids,
        )
        self._ensure_order_requestable(order)
        self._ensure_revision(order.revision, expected_revision)
        existing_result = await self.db.execute(
            select(AgencyOrderCancellationCase.id)
            .where(
                AgencyOrderCancellationCase.agency_id == order.agency_id
            )
            .where(AgencyOrderCancellationCase.order_id == order.id)
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
            .limit(1)
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "cancellation_case_open",
                "该订单已有未完成的取消案件",
            )
        supplier_required, refund_required = (
            self._derive_required_actions(order, payments, fulfillments)
        )
        now = self._now()
        case = AgencyOrderCancellationCase(
            agency_id=order.agency_id,
            branch_id=order.branch_id,
            order_id=order.id,
            customer_id=order.customer_id,
            revision=1,
            status="approval_pending",
            order_revision_at_request=order.revision,
            reason_code=normalized_reason_code,
            reason_detail=safe_reason_detail,
            supplier_cancel_required=supplier_required,
            refund_required=refund_required,
            approved_refund_amount=None,
            currency=order.currency,
            requested_by_user_id=actor_user_id,
            requested_at=now,
            external_action_triggered=False,
        )
        self.db.add(case)
        await self._flush()
        await self._append_case_event(
            case=case,
            order=order,
            event_type="cancellation_requested",
            actor_user_id=actor_user_id,
            event_metadata={
                "supplier_cancel_required": supplier_required,
                "refund_required": refund_required,
                "external_actions_triggered": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_order_cancellation_case",
            resource=case,
        )

    async def review_cancellation(
        self,
        *,
        actor_user_id: uuid.UUID,
        case_id: uuid.UUID,
        decision: str,
        expected_revision: int,
        approved_refund_amount: Decimal | None,
        approved_refund_currency: str | None,
        reason: str | None,
        idempotency_key: str,
    ) -> AgencyOrderCancellationCase:
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in {"approve", "reject"}:
            raise AgencyTransactionValidationError(
                "cancellation_review_decision_invalid",
                "取消审批决定只能是 approve 或 reject",
            )
        amount = self._money(
            approved_refund_amount,
            field="approved_refund_amount",
        )
        currency = self._currency(
            approved_refund_currency,
            required=amount is not None,
        )
        safe_reason = self._safe_optional_text(reason)
        if normalized_decision == "reject" and safe_reason is None:
            raise AgencyTransactionValidationError(
                "cancellation_review_reason_required",
                "拒绝取消申请时必须填写原因",
            )
        case, order, payments, fulfillments = await self._lock_case_context(
            case_id=case_id,
            actor_user_id=actor_user_id,
            permission="review",
        )
        state = await self._begin_idempotent_action(
            agency_id=case.agency_id,
            scope="order.cancellation.review",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "case_id": case.id,
                "decision": normalized_decision,
                "expected_revision": expected_revision,
                "approved_refund_amount": amount,
                "approved_refund_currency": currency,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_case(
                state,
                agency_id=case.agency_id,
                order_id=case.order_id,
            )
        self._ensure_revision(case.revision, expected_revision)
        if case.status != "approval_pending":
            raise AgencyTransactionConflict(
                "cancellation_review_state_conflict",
                "只有 approval_pending 取消案件可以审批",
            )
        if (
            actor_user_id == case.requested_by_user_id
            or actor_user_id == order.user_id
        ):
            raise AgencyTransactionAccessDenied(
                "cancellation_review_self_decision_denied",
                "取消申请发起人或订单客户不能审批该申请",
            )
        if normalized_decision == "approve":
            if case.order_revision_at_request != order.revision:
                raise AgencyTransactionConflict(
                    "cancellation_order_exposure_changed",
                    "订单版本或外部暴露迹象已变化，必须重新创建取消申请",
                )
            self._ensure_required_actions_unchanged(
                case=case,
                order=order,
                payments=payments,
                fulfillments=fulfillments,
            )
        if normalized_decision == "reject":
            if amount is not None or currency is not None:
                raise AgencyTransactionValidationError(
                    "cancellation_rejected_refund_forbidden",
                    "拒绝取消申请时不能批准退款金额",
                )
        elif case.refund_required:
            if amount is None or currency != order.currency:
                raise AgencyTransactionValidationError(
                    "cancellation_refund_approval_required",
                    "存在支付或退款暴露时，必须批准待人工核验的同币种金额",
                )
            if amount > order.total_amount:
                raise AgencyTransactionValidationError(
                    "cancellation_refund_amount_exceeds_order",
                    "批准退款金额不能超过订单总额",
                )
        else:
            if amount is not None and amount > 0:
                raise AgencyTransactionValidationError(
                    "cancellation_refund_not_required",
                    "该订单没有退款需求，不能批准正数退款金额",
                )
            if currency is not None and currency != order.currency:
                raise AgencyTransactionValidationError(
                    "cancellation_refund_currency_mismatch",
                    "批准退款币种必须与订单币种一致",
                )
            amount = None

        now = self._now()
        case.review_decision = (
            "approved" if normalized_decision == "approve" else "rejected"
        )
        case.reviewed_by_user_id = actor_user_id
        case.reviewed_at = now
        case.review_note = safe_reason
        case.approved_refund_amount = (
            amount if normalized_decision == "approve" else None
        )
        event_type = "cancellation_rejected"
        order_from_status: str | None = None
        if normalized_decision == "reject":
            case.status = "rejected"
        elif case.supplier_cancel_required or case.refund_required:
            case.status = "action_pending"
            if order.status != "cancellation_pending":
                order_from_status = order.status
                order.status = "cancellation_pending"
                order.cancellation_requested_at = (
                    order.cancellation_requested_at or now
                )
            event_type = "cancellation_approved_for_manual_action"
        else:
            if order.status not in {"draft", "approved"}:
                raise AgencyTransactionConflict(
                    "cancellation_direct_completion_conflict",
                    "只有未暴露外部状态的 draft 或 approved 订单可以直接取消",
                )
            case.status = "completed"
            case.completed_at = now
            order_from_status = order.status
            order.status = "cancelled"
            order.cancellation_requested_at = (
                order.cancellation_requested_at or now
            )
            order.cancelled_at = now
            event_type = "cancellation_completed_internally"

        await self._flush()
        if order_from_status is not None:
            await self._append_order_event(
                order=order,
                event_type=event_type,
                from_status=order_from_status,
                to_status=order.status,
                actor_user_id=actor_user_id,
                event_metadata={
                    "cancellation_case_id": str(case.id),
                    "external_actions_triggered": False,
                },
            )
        await self._append_case_event(
            case=case,
            order=order,
            event_type=event_type,
            actor_user_id=actor_user_id,
            event_metadata={
                "decision": case.review_decision,
                "supplier_cancel_required": case.supplier_cancel_required,
                "refund_required": case.refund_required,
                "external_actions_triggered": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_order_cancellation_case",
            resource=case,
        )

    async def record_manual_result(
        self,
        *,
        actor_user_id: uuid.UUID,
        case_id: uuid.UUID,
        expected_revision: int,
        action_type: str,
        outcome: str,
        external_reference_sha256: str,
        evidence_sha256: str,
        amount: Decimal | None,
        currency: str | None,
        occurred_at: datetime,
        idempotency_key: str,
    ) -> AgencyOrderCompensationRecord:
        normalized_action = str(action_type or "").strip().lower()
        normalized_outcome = str(outcome or "").strip().lower()
        if normalized_action not in _REQUIRED_ACTIONS:
            raise AgencyTransactionValidationError(
                "cancellation_action_type_invalid",
                "人工结果类型只能是 supplier_cancel 或 refund",
            )
        if normalized_outcome not in {"succeeded", "failed", "unknown"}:
            raise AgencyTransactionValidationError(
                "cancellation_manual_outcome_invalid",
                "人工结果只能是 succeeded、failed 或 unknown",
            )
        reference_hash = self._sha256(
            external_reference_sha256,
            field="external_reference_sha256",
        )
        evidence_hash = self._sha256(
            evidence_sha256,
            field="evidence_sha256",
        )
        normalized_amount = self._money(amount, field="amount")
        normalized_currency = self._currency(
            currency,
            required=normalized_action == "refund",
        )
        occurred = self._occurred_at(occurred_at)
        if normalized_action == "supplier_cancel":
            if normalized_amount is not None or normalized_currency is not None:
                raise AgencyTransactionValidationError(
                    "cancellation_supplier_amount_forbidden",
                    "供应商取消结果不能携带退款金额或币种",
                )
            stored_amount = Decimal("0.00")
        else:
            if normalized_amount is None:
                raise AgencyTransactionValidationError(
                    "cancellation_refund_result_amount_required",
                    "退款结果必须提供金额与币种",
                )
            stored_amount = normalized_amount

        case, order, payments, fulfillments = await self._lock_case_context(
            case_id=case_id,
            actor_user_id=actor_user_id,
            permission=(
                "booking_operator"
                if normalized_action == "supplier_cancel"
                else "finance"
            ),
        )
        state = await self._begin_idempotent_action(
            agency_id=case.agency_id,
            scope=f"order.cancellation.result.{normalized_action}",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "case_id": case.id,
                "expected_revision": expected_revision,
                "action_type": normalized_action,
                "outcome": normalized_outcome,
                "external_reference_sha256": reference_hash,
                "evidence_sha256": evidence_hash,
                "amount": stored_amount,
                "currency": normalized_currency,
                "occurred_at": occurred,
            },
        )
        if state.replayed:
            return await self._load_replayed_compensation(
                state,
                agency_id=case.agency_id,
                case_id=case.id,
            )
        self._ensure_required_actions_unchanged(
            case=case,
            order=order,
            payments=payments,
            fulfillments=fulfillments,
        )
        self._ensure_revision(case.revision, expected_revision)
        if case.status != "action_pending":
            raise AgencyTransactionConflict(
                "cancellation_manual_result_state_conflict",
                "只有 action_pending 取消案件可以登记人工结果",
            )
        if not getattr(case, f"{normalized_action}_required"):
            raise AgencyTransactionValidationError(
                "cancellation_action_not_required",
                "该取消案件不需要此类人工结果",
            )
        if normalized_action == "refund" and (
            normalized_currency != case.currency
            or case.approved_refund_amount is None
            or stored_amount != case.approved_refund_amount
        ):
            raise AgencyTransactionValidationError(
                "cancellation_refund_result_mismatch",
                "退款结果金额和币种必须与已批准退款一致",
            )

        records, reconciliations = await self._case_records(
            case,
            for_update=True,
        )
        latest_same_action = next(
            (
                item
                for item in reversed(records)
                if item.action_type == normalized_action
            ),
            None,
        )
        if latest_same_action is not None and latest_same_action.outcome == "succeeded":
            existing_reconciliation = next(
                (
                    item
                    for item in reconciliations
                    if item.compensation_record_id == latest_same_action.id
                ),
                None,
            )
            if (
                existing_reconciliation is None
                or existing_reconciliation.outcome == "matched"
            ):
                raise AgencyTransactionConflict(
                    "cancellation_action_already_succeeded",
                    "该人工动作已有成功结果，必须先完成或继续对账",
                )

        next_sequence = (
            max((item.record_sequence for item in records), default=0) + 1
        )
        record = AgencyOrderCompensationRecord(
            agency_id=case.agency_id,
            branch_id=case.branch_id,
            order_id=case.order_id,
            customer_id=case.customer_id,
            cancellation_case_id=case.id,
            record_sequence=next_sequence,
            case_revision=case.revision,
            action_type=normalized_action,
            outcome=normalized_outcome,
            external_reference_hash=reference_hash,
            evidence_hash=evidence_hash,
            amount=stored_amount,
            currency=normalized_currency or case.currency,
            occurred_at=occurred,
            recorded_by_user_id=actor_user_id,
            system_external_action_triggered=False,
        )
        now = self._now()
        if normalized_outcome != "succeeded":
            next_status = "manual_intervention"
        else:
            next_status = self._progress(
                case,
                records,
                reconciliations,
                record_override=record,
            )
        case_changed = next_status != case.status
        target_revision = case.revision + 1 if case_changed else case.revision
        record.case_revision = target_revision
        self.db.add(record)
        if case_changed:
            case.status = next_status
            case.updated_at = now

        order_from_status: str | None = None
        if next_status == "manual_intervention":
            order_from_status = order.status
            order.status = "manual_intervention"
        await self._flush()
        if case.revision != target_revision:
            raise AgencyTransactionPersistenceError(
                "cancellation_case_revision_invalid",
                "取消案件版本未按预期推进",
            )
        if order_from_status is not None:
            await self._append_order_event(
                order=order,
                event_type="cancellation_manual_intervention_required",
                from_status=order_from_status,
                to_status=order.status,
                actor_user_id=actor_user_id,
                event_metadata={
                    "cancellation_case_id": str(case.id),
                    "action_type": normalized_action,
                    "outcome": normalized_outcome,
                    "external_actions_triggered": False,
                },
            )
        await self._append_case_event(
            case=case,
            order=order,
            event_type="cancellation_manual_result_recorded",
            actor_user_id=actor_user_id,
            event_metadata={
                "record_id": str(record.id),
                "record_sequence": record.record_sequence,
                "action_type": normalized_action,
                "outcome": normalized_outcome,
                "system_external_action_triggered": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_order_compensation_record",
            resource=record,
        )

    async def reconcile_manual_result(
        self,
        *,
        actor_user_id: uuid.UUID,
        record_id: uuid.UUID,
        expected_revision: int,
        outcome: str,
        observed_amount: Decimal | None,
        observed_currency: str | None,
        evidence_sha256: str,
        idempotency_key: str,
    ) -> AgencyOrderReconciliationRecord:
        normalized_outcome = str(outcome or "").strip().lower()
        if normalized_outcome not in {
            "matched",
            "mismatched",
            "unverifiable",
        }:
            raise AgencyTransactionValidationError(
                "cancellation_reconciliation_outcome_invalid",
                "对账结果只能是 matched、mismatched 或 unverifiable",
            )
        evidence_hash = self._sha256(
            evidence_sha256,
            field="evidence_sha256",
        )
        normalized_observed_amount = self._money(
            observed_amount,
            field="observed_amount",
        )
        normalized_observed_currency = self._currency(
            observed_currency,
            required=False,
        )
        if (normalized_observed_amount is None) != (
            normalized_observed_currency is None
        ):
            raise AgencyTransactionValidationError(
                "cancellation_reconciliation_observation_pair_required",
                "observed_amount 与 observed_currency 必须同时提供",
            )
        record_preview = await self._get_compensation(record_id)
        case, order, payments, fulfillments = await self._lock_case_context(
            case_id=record_preview.cancellation_case_id,
            actor_user_id=actor_user_id,
            permission="auditor",
        )
        record = await self._get_compensation(record_id, for_update=True)
        self._ensure_compensation_binding(record, case)
        if record.action_type == "supplier_cancel":
            if (
                normalized_observed_amount is not None
                or normalized_observed_currency is not None
            ):
                raise AgencyTransactionValidationError(
                    "cancellation_supplier_observation_forbidden",
                    "供应商取消对账不能提供观察金额或币种",
                )
        elif normalized_outcome == "matched" and (
            normalized_observed_amount is None
            or normalized_observed_currency != record.currency
            or normalized_observed_amount != record.amount
        ):
            raise AgencyTransactionValidationError(
                "cancellation_refund_observation_mismatch",
                "匹配的退款对账必须提交与人工结果一致的金额和币种",
            )
        state = await self._begin_idempotent_action(
            agency_id=case.agency_id,
            scope="order.cancellation.reconcile",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "record_id": record.id,
                "expected_revision": expected_revision,
                "outcome": normalized_outcome,
                "observed_amount": normalized_observed_amount,
                "observed_currency": normalized_observed_currency,
                "evidence_sha256": evidence_hash,
            },
        )
        if state.replayed:
            return await self._load_replayed_reconciliation(
                state,
                agency_id=case.agency_id,
                record_id=record.id,
            )
        self._ensure_required_actions_unchanged(
            case=case,
            order=order,
            payments=payments,
            fulfillments=fulfillments,
        )
        self._ensure_revision(case.revision, expected_revision)
        if case.status != "reconciliation_pending":
            raise AgencyTransactionConflict(
                "cancellation_reconciliation_state_conflict",
                "只有 reconciliation_pending 取消案件可以登记对账",
            )
        if record.outcome != "succeeded":
            raise AgencyTransactionConflict(
                "cancellation_reconciliation_result_not_successful",
                "只有 succeeded 人工结果可以进入对账",
            )
        if actor_user_id == record.recorded_by_user_id:
            raise AgencyTransactionAccessDenied(
                "cancellation_reconciliation_self_review_denied",
                "人工结果登记人不能复核自己的结果",
            )
        records, reconciliations = await self._case_records(
            case,
            for_update=True,
        )
        latest_for_action = next(
            (
                item
                for item in reversed(records)
                if item.action_type == record.action_type
            ),
            None,
        )
        if latest_for_action is None or latest_for_action.id != record.id:
            raise AgencyTransactionConflict(
                "cancellation_reconciliation_stale_result",
                "该人工结果已被同类型的新记录替代",
            )
        if any(
            item.compensation_record_id == record.id
            for item in reconciliations
        ):
            raise AgencyTransactionConflict(
                "cancellation_reconciliation_exists",
                "该人工结果已经完成对账",
            )

        now = self._now()
        reconciliation = AgencyOrderReconciliationRecord(
            agency_id=case.agency_id,
            branch_id=case.branch_id,
            order_id=case.order_id,
            customer_id=case.customer_id,
            cancellation_case_id=case.id,
            compensation_record_id=record.id,
            case_revision=case.revision,
            outcome=normalized_outcome,
            observed_amount=normalized_observed_amount,
            currency=normalized_observed_currency,
            reconciled_by_user_id=actor_user_id,
            evidence_hash=evidence_hash,
            reconciled_at=now,
        )
        if normalized_outcome != "matched":
            next_status = "manual_intervention"
        else:
            next_status = self._progress(
                case,
                records,
                reconciliations,
                reconciliation_override=reconciliation,
            )
        case_changed = next_status != case.status
        target_revision = case.revision + 1 if case_changed else case.revision
        reconciliation.case_revision = target_revision
        self.db.add(reconciliation)
        if case_changed:
            case.status = next_status
            case.updated_at = now

        order_from_status: str | None = None
        if next_status == "manual_intervention":
            order_from_status = order.status
            order.status = "manual_intervention"
        elif next_status == "completed":
            order_from_status = order.status
            order.status = "cancelled"
            order.cancelled_at = now
            case.completed_at = now
        await self._flush()
        if case.revision != target_revision:
            raise AgencyTransactionPersistenceError(
                "cancellation_case_revision_invalid",
                "取消案件版本未按预期推进",
            )
        event_type = (
            "cancellation_reconciliation_matched"
            if normalized_outcome == "matched"
            else "cancellation_manual_intervention_required"
        )
        if order_from_status is not None:
            await self._append_order_event(
                order=order,
                event_type=event_type,
                from_status=order_from_status,
                to_status=order.status,
                actor_user_id=actor_user_id,
                event_metadata={
                    "cancellation_case_id": str(case.id),
                    "compensation_record_id": str(record.id),
                    "reconciliation_outcome": normalized_outcome,
                    "external_actions_triggered": False,
                },
            )
        await self._append_case_event(
            case=case,
            order=order,
            event_type=event_type,
            actor_user_id=actor_user_id,
            event_metadata={
                "compensation_record_id": str(record.id),
                "reconciliation_id": str(reconciliation.id),
                "outcome": normalized_outcome,
                "external_actions_triggered": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_order_reconciliation_record",
            resource=reconciliation,
        )

    async def resume_cancellation(
        self,
        *,
        actor_user_id: uuid.UUID,
        case_id: uuid.UUID,
        expected_revision: int,
        reason: str | None,
        idempotency_key: str,
    ) -> AgencyOrderCancellationCase:
        safe_reason = self._safe_optional_text(reason)
        case, order, payments, fulfillments = await self._lock_case_context(
            case_id=case_id,
            actor_user_id=actor_user_id,
            permission="resume",
        )
        state = await self._begin_idempotent_action(
            agency_id=case.agency_id,
            scope="order.cancellation.resume",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "case_id": case.id,
                "expected_revision": expected_revision,
                "reason": safe_reason,
            },
        )
        if state.replayed:
            return await self._load_replayed_case(
                state,
                agency_id=case.agency_id,
                order_id=case.order_id,
            )
        self._ensure_required_actions_unchanged(
            case=case,
            order=order,
            payments=payments,
            fulfillments=fulfillments,
        )
        self._ensure_revision(case.revision, expected_revision)
        if case.status != "manual_intervention":
            raise AgencyTransactionConflict(
                "cancellation_resume_state_conflict",
                "只有 manual_intervention 取消案件可以恢复",
            )
        records, reconciliations = await self._case_records(
            case,
            for_update=True,
        )
        next_status = self._progress(case, records, reconciliations)
        if next_status != "action_pending":
            raise AgencyTransactionConflict(
                "cancellation_resume_not_required",
                "该取消案件没有可恢复的人工动作",
            )
        now = self._now()
        case.status = next_status
        case.updated_at = now
        order_from_status = order.status
        order.status = "cancellation_pending"
        await self._flush()
        await self._append_order_event(
            order=order,
            event_type="cancellation_resumed",
            from_status=order_from_status,
            to_status=order.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "cancellation_case_id": str(case.id),
                "next_status": next_status,
                "external_actions_triggered": False,
            },
        )
        await self._append_case_event(
            case=case,
            order=order,
            event_type="cancellation_resumed",
            actor_user_id=actor_user_id,
            event_metadata={
                "next_status": next_status,
                "external_actions_triggered": False,
            },
        )
        return await self._finish_action(
            state,
            resource_type="agency_order_cancellation_case",
            resource=case,
        )

    async def get_cancellation_case(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> AgencyOrderCancellationCase:
        order = await self._get_order(order_id)
        case = await self._get_case_for_order(order_id)
        self._ensure_case_binding(case, order)
        await self._ensure_case_visible(
            case=case,
            order=order,
            actor_user_id=actor_user_id,
        )
        return case

    async def list_cancellation_cases(
        self,
        *,
        actor_user_id: uuid.UUID,
        agency_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyOrderCancellationCase], int]:
        transaction_visibility = (
            await self.authorization.transaction_visibility_filter(
                model=AgencyOrder,
                agency_id=agency_id,
                actor_user_id=actor_user_id,
                include_approver=True,
            )
        )
        operation_visibility = (
            await self.authorization.branch_visibility_filter(
                agency_id=agency_id,
                actor_user_id=actor_user_id,
                roles=_CASE_OPERATION_ROLES,
                branch_column=AgencyOrderCancellationCase.branch_id,
            )
        )
        join_condition = and_(
            AgencyOrderCancellationCase.agency_id == AgencyOrder.agency_id,
            AgencyOrderCancellationCase.branch_id == AgencyOrder.branch_id,
            AgencyOrderCancellationCase.order_id == AgencyOrder.id,
            AgencyOrderCancellationCase.customer_id
            == AgencyOrder.customer_id,
        )
        filters = [
            AgencyOrderCancellationCase.agency_id == agency_id,
            or_(transaction_visibility, operation_visibility),
        ]
        if status_filter is not None:
            filters.append(
                AgencyOrderCancellationCase.status == status_filter
            )
        return await self._page(
            statement=select(AgencyOrderCancellationCase)
            .join(AgencyOrder, join_condition)
            .where(*filters)
            .order_by(
                desc(AgencyOrderCancellationCase.created_at),
                desc(AgencyOrderCancellationCase.id),
            )
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyOrderCancellationCase)
            .join(AgencyOrder, join_condition)
            .where(*filters),
        )

    async def list_manual_results(
        self,
        *,
        actor_user_id: uuid.UUID,
        case_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[
        list[tuple[AgencyOrderCompensationRecord, str | None]],
        int,
    ]:
        case = await self._get_case(case_id)
        order = await self._get_order(case.order_id)
        self._ensure_case_binding(case, order)
        await self.authorization.require_branch_role(
            agency_id=case.agency_id,
            branch_id=case.branch_id,
            actor_user_id=actor_user_id,
            roles={"auditor"},
            allow_agency_wide=False,
        )
        filters = [
            AgencyOrderCompensationRecord.agency_id == case.agency_id,
            AgencyOrderCompensationRecord.cancellation_case_id == case.id,
        ]
        records_result = await self.db.execute(
            select(AgencyOrderCompensationRecord)
            .where(*filters)
            .order_by(
                desc(AgencyOrderCompensationRecord.record_sequence),
                desc(AgencyOrderCompensationRecord.id),
            )
            .limit(limit)
            .offset(offset)
        )
        count_result = await self.db.execute(
            select(func.count())
            .select_from(AgencyOrderCompensationRecord)
            .where(*filters)
        )
        records = list(records_result.scalars().all())
        reconciliations: dict[uuid.UUID, str] = {}
        if records:
            reconciliation_result = await self.db.execute(
                select(
                    AgencyOrderReconciliationRecord.compensation_record_id,
                    AgencyOrderReconciliationRecord.outcome,
                )
                .where(
                    AgencyOrderReconciliationRecord.agency_id
                    == case.agency_id
                )
                .where(
                    AgencyOrderReconciliationRecord.cancellation_case_id
                    == case.id
                )
                .where(
                    AgencyOrderReconciliationRecord.compensation_record_id.in_(
                        [record.id for record in records]
                    )
                )
            )
            reconciliations = dict(reconciliation_result.all())
        return (
            [
                (record, reconciliations.get(record.id))
                for record in records
            ],
            int(count_result.scalar_one()),
        )

    async def list_cancellation_events(
        self,
        *,
        actor_user_id: uuid.UUID,
        case_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyOrderCancellationEvent], int]:
        case = await self._get_case(case_id)
        order = await self._get_order(case.order_id)
        self._ensure_case_binding(case, order)
        await self._ensure_case_visible(
            case=case,
            order=order,
            actor_user_id=actor_user_id,
        )
        filters = [
            AgencyOrderCancellationEvent.agency_id == case.agency_id,
            AgencyOrderCancellationEvent.cancellation_case_id == case.id,
        ]
        return await self._page(
            statement=select(AgencyOrderCancellationEvent)
            .where(*filters)
            .order_by(AgencyOrderCancellationEvent.event_sequence)
            .limit(limit)
            .offset(offset),
            count_statement=select(func.count())
            .select_from(AgencyOrderCancellationEvent)
            .where(*filters),
        )
