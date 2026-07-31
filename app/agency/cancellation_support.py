"""旅行社订单人工取消服务的内部支撑逻辑。

集中保存输入校验、锁定查询、授权、幂等回放、暴露派生和进度计算；
公开业务操作及状态机仍由 cancellation_service 模块编排。
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, func, select

from app.agency.branch_authorization import BRANCH_DRAIN_STATUSES
from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionNotFound,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.agency.transaction_service import IdempotencyState
from app.models.agency_cancellation import (
    AgencyOrderCancellationCase,
    AgencyOrderCancellationEvent,
    AgencyOrderCompensationRecord,
    AgencyOrderReconciliationRecord,
)
from app.models.agency_customer_lifecycle import AgencyCustomer
from app.models.agency_transaction import (
    AgencyOrder,
    FulfillmentRecord,
    PaymentAttempt,
)
from app.utils.security import redact_sensitive_text


_REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CANCELLATION_REASON_CODES = frozenset(
    {
        "customer_request",
        "customer_consent_withdrawn",
        "agency_unable_to_fulfill",
        "supplier_unavailable",
        "duplicate_order",
        "pricing_or_booking_error",
        "force_majeure",
        "compliance_or_risk",
    }
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUESTABLE_ORDER_STATUSES = frozenset(
    {
        "draft",
        "approved",
        "processing",
        "failed",
        "cancellation_pending",
        "manual_intervention",
    }
)
_CASE_OPERATION_ROLES = frozenset(
    {"booking_operator", "finance", "auditor"}
)
_REQUIRED_ACTIONS = frozenset({"supplier_cancel", "refund"})


class CancellationSupportMixin:
    """为取消服务提供无公开入口的可复用支撑方法。"""

    @staticmethod
    def _reason_code(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if (
            not _REASON_CODE_PATTERN.fullmatch(normalized)
            or normalized not in _CANCELLATION_REASON_CODES
        ):
            raise AgencyTransactionValidationError(
                "cancellation_reason_code_invalid",
                "取消原因代码不在允许列表中",
            )
        return normalized

    @staticmethod
    def _safe_optional_text(
        value: str | None,
        *,
        limit: int = 500,
    ) -> str | None:
        normalized = redact_sensitive_text(str(value or "")).strip()
        return normalized[:limit] or None

    @staticmethod
    def _sha256(value: str, *, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _SHA256_PATTERN.fullmatch(normalized):
            raise AgencyTransactionValidationError(
                f"cancellation_{field}_invalid",
                f"{field} 必须是 64 位 SHA-256 十六进制摘要",
            )
        return normalized

    @staticmethod
    def _money(value: Decimal | None, *, field: str) -> Decimal | None:
        if value is None:
            return None
        try:
            normalized = Decimal(str(value))
            quantized = normalized.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as error:
            raise AgencyTransactionValidationError(
                f"cancellation_{field}_invalid",
                f"{field} 必须是最多两位小数的非负金额",
            ) from error
        if normalized < 0 or normalized != quantized:
            raise AgencyTransactionValidationError(
                f"cancellation_{field}_invalid",
                f"{field} 必须是最多两位小数的非负金额",
            )
        return quantized

    @staticmethod
    def _currency(value: str | None, *, required: bool) -> str | None:
        normalized = str(value or "").strip().upper()
        if not normalized:
            if not required:
                return None
            raise AgencyTransactionValidationError(
                "cancellation_currency_required",
                "退款币种不能为空",
            )
        if (
            len(normalized) != 3
            or not normalized.isascii()
            or not normalized.isalpha()
        ):
            raise AgencyTransactionValidationError(
                "cancellation_currency_invalid",
                "币种必须是 3 位 ASCII 字母",
            )
        return normalized

    def _occurred_at(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AgencyTransactionValidationError(
                "cancellation_occurred_at_timezone_required",
                "人工结果发生时间必须包含时区",
            )
        normalized = value.astimezone(UTC)
        if normalized > self._now() + timedelta(minutes=5):
            raise AgencyTransactionValidationError(
                "cancellation_occurred_at_in_future",
                "人工结果发生时间不能超过服务端当前时间 5 分钟",
            )
        return normalized

    async def _get_case(
        self,
        case_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyOrderCancellationCase:
        statement = select(AgencyOrderCancellationCase).where(
            AgencyOrderCancellationCase.id == case_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.db.execute(statement)
        case = result.scalar_one_or_none()
        if case is None:
            raise hidden_not_found()
        return case

    async def _get_case_for_order(
        self,
        order_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyOrderCancellationCase:
        statement = (
            select(AgencyOrderCancellationCase)
            .where(AgencyOrderCancellationCase.order_id == order_id)
            .order_by(
                desc(AgencyOrderCancellationCase.created_at),
                desc(AgencyOrderCancellationCase.id),
            )
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.db.execute(statement)
        case = result.scalar_one_or_none()
        if case is None:
            raise hidden_not_found()
        return case

    async def _get_compensation(
        self,
        record_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyOrderCompensationRecord:
        statement = select(AgencyOrderCompensationRecord).where(
            AgencyOrderCompensationRecord.id == record_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.db.execute(statement)
        record = result.scalar_one_or_none()
        if record is None:
            raise hidden_not_found()
        return record

    @staticmethod
    def _ensure_case_binding(
        case: AgencyOrderCancellationCase,
        order: AgencyOrder,
    ) -> None:
        if (
            case.agency_id,
            case.branch_id,
            case.order_id,
            case.customer_id,
        ) != (
            order.agency_id,
            order.branch_id,
            order.id,
            order.customer_id,
        ):
            raise AgencyTransactionConflict(
                "cancellation_case_binding_conflict",
                "取消案件与订单绑定已变化，请刷新后重试",
            )

    @staticmethod
    def _ensure_compensation_binding(
        record: AgencyOrderCompensationRecord,
        case: AgencyOrderCancellationCase,
    ) -> None:
        if (
            record.agency_id,
            record.branch_id,
            record.order_id,
            record.customer_id,
            record.cancellation_case_id,
        ) != (
            case.agency_id,
            case.branch_id,
            case.order_id,
            case.customer_id,
            case.id,
        ):
            raise AgencyTransactionConflict(
                "cancellation_result_binding_conflict",
                "人工结果与取消案件绑定已变化，请刷新后重试",
            )

    async def _authorize_locked_context(
        self,
        *,
        permission: str,
        actor_user_id: uuid.UUID,
        customer: AgencyCustomer,
        order: AgencyOrder,
    ) -> None:
        if permission == "request":
            if actor_user_id == order.user_id:
                await self.authorization.lock_branch_scope(
                    agency_id=order.agency_id,
                    branch_id=order.branch_id,
                    allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
                )
                return
            await self.authorization.require_quote_manager(
                customer=customer,
                actor_user_id=actor_user_id,
                lock_scope=True,
                allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
            )
            return
        if permission == "review":
            await self.authorization.require_branch_approver(
                agency_id=order.agency_id,
                branch_id=order.branch_id,
                actor_user_id=actor_user_id,
                lock_scope=True,
                allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
            )
            return
        if permission in {"booking_operator", "finance", "auditor"}:
            await self.authorization.require_branch_role(
                agency_id=order.agency_id,
                branch_id=order.branch_id,
                actor_user_id=actor_user_id,
                roles={permission},
                allow_agency_wide=False,
                lock_scope=True,
                allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
            )
            return
        if permission == "resume":
            await self.authorization.require_branch_role(
                agency_id=order.agency_id,
                branch_id=order.branch_id,
                actor_user_id=actor_user_id,
                roles={"branch_manager"},
                allow_agency_wide=True,
                lock_scope=True,
                allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
            )
            return
        raise RuntimeError(f"unknown cancellation permission: {permission}")

    async def _lock_order_context(
        self,
        *,
        order_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        permission: str,
    ) -> tuple[
        AgencyCustomer,
        AgencyOrder,
        list[PaymentAttempt],
        list[FulfillmentRecord],
    ]:
        """按 customer -> branch/auth -> order -> ledgers 顺序锁定。"""

        order_preview = await self._get_order(order_id)
        binding = self._transaction_binding(order_preview)
        customer = await self._get_customer_binding(
            agency_id=binding[0],
            branch_id=binding[1],
            customer_id=binding[2],
            for_update=True,
        )
        self._ensure_customer_binding(customer, binding)
        await self._authorize_locked_context(
            permission=permission,
            actor_user_id=actor_user_id,
            customer=customer,
            order=order_preview,
        )
        order = await self._get_order(order_id, for_update=True)
        self._ensure_transaction_binding(order, binding)
        self._ensure_customer_binding(customer, binding)

        payment_result = await self.db.execute(
            select(PaymentAttempt)
            .where(PaymentAttempt.agency_id == order.agency_id)
            .where(PaymentAttempt.order_id == order.id)
            .order_by(PaymentAttempt.id)
            .with_for_update()
        )
        fulfillment_result = await self.db.execute(
            select(FulfillmentRecord)
            .where(FulfillmentRecord.agency_id == order.agency_id)
            .where(FulfillmentRecord.order_id == order.id)
            .order_by(FulfillmentRecord.id)
            .with_for_update()
        )
        return (
            customer,
            order,
            list(payment_result.scalars().all()),
            list(fulfillment_result.scalars().all()),
        )

    async def _lock_case_context(
        self,
        *,
        case_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        permission: str,
    ) -> tuple[
        AgencyOrderCancellationCase,
        AgencyOrder,
        list[PaymentAttempt],
        list[FulfillmentRecord],
    ]:
        case_preview = await self._get_case(case_id)
        _, order, payments, fulfillments = await self._lock_order_context(
            order_id=case_preview.order_id,
            actor_user_id=actor_user_id,
            permission=permission,
        )
        case = await self._get_case(case_id, for_update=True)
        self._ensure_case_binding(case, order)
        return case, order, payments, fulfillments

    @staticmethod
    def _has_reference(value: str | None) -> bool:
        return bool(str(value or "").strip())

    @classmethod
    def _derive_required_actions(
        cls,
        order: AgencyOrder,
        payments: list[PaymentAttempt],
        fulfillments: list[FulfillmentRecord],
    ) -> tuple[bool, bool]:
        """从锁定投影和明细派生，矛盾或未知暴露一律走人工路径。

        两个 ``*_required`` 标记都表示必须由对应岗位登记现状摘要并由
        审计员核验，不表示本服务要再次取消供应商订单或再次退款；本服务
        没有外部执行能力。
        """

        refund_required = order.payment_status != "not_started" or any(
            attempt.status in {"processing", "succeeded"}
            or attempt.external_action_enabled
            or cls._has_reference(attempt.provider_reference)
            for attempt in payments
        )
        supplier_cancel_required = (
            order.fulfillment_status != "not_started"
            or any(
                record.status != "not_started"
                or record.external_action_enabled
                or cls._has_reference(record.provider_reference)
                for record in fulfillments
            )
        )
        if order.external_action_enabled:
            refund_required = True
            supplier_cancel_required = True
        if (
            order.status
            in {
                "processing",
                "failed",
                "cancellation_pending",
                "manual_intervention",
            }
            and not refund_required
            and not supplier_cancel_required
        ):
            supplier_cancel_required = True
        return supplier_cancel_required, refund_required

    def _ensure_required_actions_unchanged(
        self,
        *,
        case: AgencyOrderCancellationCase,
        order: AgencyOrder,
        payments: list[PaymentAttempt],
        fulfillments: list[FulfillmentRecord],
    ) -> None:
        current = self._derive_required_actions(
            order,
            payments,
            fulfillments,
        )
        expected = (
            case.supplier_cancel_required,
            case.refund_required,
        )
        if current != expected:
            raise AgencyTransactionConflict(
                "cancellation_order_exposure_changed",
                "订单外部暴露迹象已变化，必须重新创建取消申请",
            )

    @staticmethod
    def _ensure_order_requestable(order: AgencyOrder) -> None:
        if order.status == "pending_review":
            raise AgencyTransactionConflict(
                "cancellation_order_review_pending",
                "订单仍在原内部审核中，必须先由原审核流程明确拒绝",
            )
        if order.status not in _REQUESTABLE_ORDER_STATUSES:
            raise AgencyTransactionConflict(
                "cancellation_order_state_conflict",
                "当前订单状态不能创建取消申请",
            )

    async def _append_case_event(
        self,
        *,
        case: AgencyOrderCancellationCase,
        order: AgencyOrder,
        event_type: str,
        actor_user_id: uuid.UUID,
        event_metadata: dict[str, Any],
    ) -> AgencyOrderCancellationEvent:
        sequence_result = await self.db.execute(
            select(
                func.coalesce(
                    func.max(
                        AgencyOrderCancellationEvent.event_sequence
                    ),
                    0,
                )
            )
            .where(
                AgencyOrderCancellationEvent.agency_id == case.agency_id
            )
            .where(
                AgencyOrderCancellationEvent.cancellation_case_id == case.id
            )
        )
        event = AgencyOrderCancellationEvent(
            agency_id=case.agency_id,
            branch_id=case.branch_id,
            order_id=case.order_id,
            customer_id=case.customer_id,
            cancellation_case_id=case.id,
            event_sequence=int(sequence_result.scalar_one()) + 1,
            case_revision=case.revision,
            event_type=event_type,
            actor_user_id=actor_user_id,
            payload_hash=order.payload_hash,
            event_metadata=event_metadata,
        )
        self.db.add(event)
        return event

    async def _load_replayed_case(
        self,
        state: IdempotencyState,
        *,
        agency_id: uuid.UUID,
        order_id: uuid.UUID | None = None,
    ) -> AgencyOrderCancellationCase:
        case = await self._load_replayed_resource(
            state,
            model=AgencyOrderCancellationCase,
            resource_type="agency_order_cancellation_case",
            agency_id=agency_id,
            resource_label="取消案件",
        )
        if order_id is not None and case.order_id != order_id:
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录与当前订单取消案件不匹配",
            )
        return case

    async def _load_replayed_compensation(
        self,
        state: IdempotencyState,
        *,
        agency_id: uuid.UUID,
        case_id: uuid.UUID,
    ) -> AgencyOrderCompensationRecord:
        record = await self._load_replayed_resource(
            state,
            model=AgencyOrderCompensationRecord,
            resource_type="agency_order_compensation_record",
            agency_id=agency_id,
            resource_label="人工取消结果",
        )
        if record.cancellation_case_id != case_id:
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录与当前取消案件不匹配",
            )
        return record

    async def _load_replayed_reconciliation(
        self,
        state: IdempotencyState,
        *,
        agency_id: uuid.UUID,
        record_id: uuid.UUID,
    ) -> AgencyOrderReconciliationRecord:
        reconciliation = await self._load_replayed_resource(
            state,
            model=AgencyOrderReconciliationRecord,
            resource_type="agency_order_reconciliation_record",
            agency_id=agency_id,
            resource_label="人工取消对账",
        )
        if reconciliation.compensation_record_id != record_id:
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录与当前人工结果不匹配",
            )
        return reconciliation

    async def _case_records(
        self,
        case: AgencyOrderCancellationCase,
        *,
        for_update: bool = False,
    ) -> tuple[
        list[AgencyOrderCompensationRecord],
        list[AgencyOrderReconciliationRecord],
    ]:
        record_statement = (
            select(AgencyOrderCompensationRecord)
            .where(
                AgencyOrderCompensationRecord.agency_id == case.agency_id
            )
            .where(
                AgencyOrderCompensationRecord.cancellation_case_id == case.id
            )
            .order_by(AgencyOrderCompensationRecord.record_sequence)
        )
        reconciliation_statement = (
            select(AgencyOrderReconciliationRecord)
            .where(
                AgencyOrderReconciliationRecord.agency_id == case.agency_id
            )
            .where(
                AgencyOrderReconciliationRecord.cancellation_case_id
                == case.id
            )
            .order_by(AgencyOrderReconciliationRecord.created_at)
        )
        if for_update:
            record_statement = record_statement.with_for_update()
            reconciliation_statement = (
                reconciliation_statement.with_for_update()
            )
        record_result = await self.db.execute(record_statement)
        reconciliation_result = await self.db.execute(
            reconciliation_statement
        )
        return (
            list(record_result.scalars().all()),
            list(reconciliation_result.scalars().all()),
        )

    @staticmethod
    def _progress(
        case: AgencyOrderCancellationCase,
        records: list[AgencyOrderCompensationRecord],
        reconciliations: list[AgencyOrderReconciliationRecord],
        *,
        record_override: AgencyOrderCompensationRecord | None = None,
        reconciliation_override: AgencyOrderReconciliationRecord | None = None,
    ) -> str:
        latest: dict[str, AgencyOrderCompensationRecord] = {}
        for record in [*records, *([record_override] if record_override else [])]:
            current = latest.get(record.action_type)
            if current is None or record.record_sequence > current.record_sequence:
                latest[record.action_type] = record
        reconciliation_by_record = {
            item.compensation_record_id: item for item in reconciliations
        }
        if reconciliation_override is not None:
            reconciliation_by_record[
                reconciliation_override.compensation_record_id
            ] = reconciliation_override

        needs_action = False
        needs_reconciliation = False
        required = {
            action
            for action, enabled in (
                ("supplier_cancel", case.supplier_cancel_required),
                ("refund", case.refund_required),
            )
            if enabled
        }
        for action in required:
            record = latest.get(action)
            if record is None or record.outcome != "succeeded":
                needs_action = True
                continue
            reconciliation = reconciliation_by_record.get(record.id)
            if reconciliation is None:
                needs_reconciliation = True
            elif reconciliation.outcome != "matched":
                needs_action = True
        if needs_action:
            return "action_pending"
        if needs_reconciliation:
            return "reconciliation_pending"
        return "completed"

    async def _ensure_case_visible(
        self,
        *,
        case: AgencyOrderCancellationCase,
        order: AgencyOrder,
        actor_user_id: uuid.UUID,
    ) -> None:
        try:
            await self.authorization.require_transaction_view(
                resource=order,
                actor_user_id=actor_user_id,
                include_approver=True,
            )
            return
        except AgencyTransactionNotFound:
            pass
        await self.authorization.require_branch_role(
            agency_id=case.agency_id,
            branch_id=case.branch_id,
            actor_user_id=actor_user_id,
            roles=_CASE_OPERATION_ROLES,
            allow_agency_wide=False,
            allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
        )
