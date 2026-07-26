"""旅行社报价与订单的最小持久化服务。

本服务覆盖报价、客户确认、订单草稿和提交审核，并在提交时生成强类型
审核记录；审核决定由 ``order_review_service`` 处理。两个服务都不会调用
供应商、支付、退款或通知适配器，所有订单的 ``external_action_enabled``
都保持关闭。
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.agency.transaction_payloads import (
    build_quote_payload,
    canonical_money_text as _money_text,
    canonical_payload_hash,
)
from app.models.agency_order_review import AgencyOrderReview
from app.models.agency_transaction import (
    Agency,
    AgencyCustomer,
    AgencyMembership,
    AgencyOrder,
    AgencyOrderEvent,
    AgencyQuote,
    IdempotencyRecord,
    SupplierProduct,
)
from app.models.conversation import Conversation
from app.schemas.agency_transaction import (
    AgencyOrderCreateRequest,
    AgencyQuoteCreateRequest,
)


QUOTE_MANAGER_ROLES = frozenset({"owner", "admin", "travel_advisor"})


class AgencyTransactionError(Exception):
    """可安全映射到 API 的交易域错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgencyTransactionNotFound(AgencyTransactionError):
    """资源不存在，或调用方无权知道该资源是否存在。"""


class AgencyTransactionAccessDenied(AgencyTransactionError):
    """调用方没有租户级操作权限。"""


class AgencyTransactionConflict(AgencyTransactionError):
    """幂等、版本或状态机冲突。"""


class AgencyTransactionValidationError(AgencyTransactionError):
    """请求字段可解析，但不满足交易域约束。"""


class AgencyTransactionPersistenceError(AgencyTransactionError):
    """数据库暂时无法可靠完成交易。"""


@dataclass(frozen=True)
class IdempotencyState:
    record: IdempotencyRecord
    replayed: bool


def _hidden_not_found() -> AgencyTransactionNotFound:
    return AgencyTransactionNotFound(
        "agency_transaction_not_found",
        "交易资源不存在",
    )


class AgencyTransactionService:
    """在一个 ``AsyncSession`` 事务内执行旅行社交易域命令。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _normalize_idempotency_key(key: str) -> str:
        normalized = str(key or "").strip()
        if not normalized:
            raise AgencyTransactionValidationError(
                "idempotency_key_required",
                "Idempotency-Key 不能为空",
            )
        if len(normalized) > 128:
            raise AgencyTransactionValidationError(
                "idempotency_key_too_long",
                "Idempotency-Key 不能超过 128 个字符",
            )
        return normalized

    async def _flush(self) -> None:
        try:
            await self.db.flush()
        except (IntegrityError, StaleDataError) as error:
            raise AgencyTransactionConflict(
                "transaction_write_conflict",
                "交易数据已变化或存在重复记录，请刷新后重试",
            ) from error
        except SQLAlchemyError as error:
            raise AgencyTransactionPersistenceError(
                "transaction_persistence_unavailable",
                "交易数据暂时无法保存，请稍后重试",
            ) from error

    async def _get_active_membership(
        self,
        *,
        agency_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgencyMembership | None:
        result = await self.db.execute(
            select(AgencyMembership)
            .join(Agency, Agency.id == AgencyMembership.agency_id)
            .where(AgencyMembership.agency_id == agency_id)
            .where(AgencyMembership.user_id == user_id)
            .where(AgencyMembership.status == "active")
            .where(Agency.status == "active")
        )
        return result.scalar_one_or_none()

    async def _ensure_agency_active(self, agency_id: uuid.UUID) -> None:
        result = await self.db.execute(
            select(Agency.id)
            .where(Agency.id == agency_id)
            .where(Agency.status == "active")
        )
        if result.scalar_one_or_none() is None:
            raise AgencyTransactionConflict(
                "agency_not_active",
                "旅行社租户当前不可执行交易写操作",
            )

    async def _require_quote_manager(
        self,
        *,
        agency_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        hide_resource: bool,
    ) -> AgencyMembership:
        membership = await self._get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if membership is not None and membership.role in QUOTE_MANAGER_ROLES:
            return membership
        if hide_resource:
            raise _hidden_not_found()
        raise AgencyTransactionAccessDenied(
            "agency_quote_permission_denied",
            "只有本旅行社的旅行顾问、管理员或负责人可以管理报价",
        )

    async def _ensure_can_view(
        self,
        *,
        agency_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        full_snapshot: bool = True,
    ) -> None:
        if actor_user_id == owner_user_id:
            return
        membership = await self._get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if membership is not None and (
            not full_snapshot or membership.role in QUOTE_MANAGER_ROLES
        ):
            return
        raise _hidden_not_found()

    async def _ensure_can_view_order(
        self,
        *,
        order: AgencyOrder,
        actor_user_id: uuid.UUID,
    ) -> None:
        if actor_user_id == order.user_id:
            return
        membership = await self._get_active_membership(
            agency_id=order.agency_id,
            user_id=actor_user_id,
        )
        if membership is not None and membership.role in QUOTE_MANAGER_ROLES:
            return
        if membership is not None and membership.role == "approver":
            review_result = await self.db.execute(
                select(AgencyOrderReview.id)
                .where(AgencyOrderReview.agency_id == order.agency_id)
                .where(AgencyOrderReview.order_id == order.id)
                .limit(1)
            )
            if review_result.scalar_one_or_none() is not None:
                return
        raise _hidden_not_found()

    async def _validate_quote_references(
        self,
        data: AgencyQuoteCreateRequest,
    ) -> None:
        customer_result = await self.db.execute(
            select(AgencyCustomer.user_id)
            .where(AgencyCustomer.agency_id == data.agency_id)
            .where(AgencyCustomer.user_id == data.customer_user_id)
            .where(AgencyCustomer.status == "active")
        )
        if customer_result.scalar_one_or_none() is None:
            raise AgencyTransactionValidationError(
                "quote_customer_not_active",
                "客户尚未在当前旅行社建立有效业务关系",
            )

        if data.conversation_id is not None:
            conversation_result = await self.db.execute(
                select(Conversation.id)
                .where(Conversation.id == data.conversation_id)
                .where(Conversation.user_id == data.customer_user_id)
                .where(Conversation.status != "deleted")
            )
            if conversation_result.scalar_one_or_none() is None:
                raise AgencyTransactionValidationError(
                    "quote_conversation_invalid",
                    "会话不存在或不属于报价客户",
                )

        if data.product_id is not None:
            product_result = await self.db.execute(
                select(SupplierProduct.id)
                .where(SupplierProduct.id == data.product_id)
                .where(SupplierProduct.agency_id == data.agency_id)
                .where(SupplierProduct.status == "active")
            )
            if product_result.scalar_one_or_none() is None:
                raise AgencyTransactionValidationError(
                    "quote_product_invalid",
                    "供应商产品不存在、未启用或不属于当前旅行社",
                )

    async def _begin_idempotent_action(
        self,
        *,
        agency_id: uuid.UUID,
        scope: str,
        key: str,
        request_payload: dict[str, Any],
    ) -> IdempotencyState:
        normalized_key = self._normalize_idempotency_key(key)
        request_hash = canonical_payload_hash(
            {
                "scope": scope,
                "request": request_payload,
            }
        )
        record_id = uuid.uuid4()
        try:
            insert_result = await self.db.execute(
                postgresql_insert(IdempotencyRecord)
                .values(
                    id=record_id,
                    agency_id=agency_id,
                    scope=scope,
                    key=normalized_key,
                    request_hash=request_hash,
                    status="in_progress",
                )
                .on_conflict_do_nothing(
                    constraint="uq_idempotency_agency_scope_key"
                )
                .returning(IdempotencyRecord.id)
            )
            created_id = insert_result.scalar_one_or_none()
            record_result = await self.db.execute(
                select(IdempotencyRecord)
                .where(IdempotencyRecord.agency_id == agency_id)
                .where(IdempotencyRecord.scope == scope)
                .where(IdempotencyRecord.key == normalized_key)
                .with_for_update()
            )
            record = record_result.scalar_one_or_none()
        except SQLAlchemyError as error:
            raise AgencyTransactionPersistenceError(
                "idempotency_persistence_unavailable",
                "幂等记录暂时不可用，请勿重复提交并稍后重试",
            ) from error

        if record is None:
            raise AgencyTransactionPersistenceError(
                "idempotency_record_missing",
                "幂等记录未能可靠建立，请稍后重试",
            )
        if record.request_hash != request_hash:
            raise AgencyTransactionConflict(
                "idempotency_key_conflict",
                "同一 Idempotency-Key 已用于不同请求",
            )
        if created_id is not None:
            return IdempotencyState(record=record, replayed=False)
        if record.status == "completed":
            return IdempotencyState(record=record, replayed=True)
        if record.status == "in_progress":
            raise AgencyTransactionConflict(
                "idempotency_request_in_progress",
                "相同幂等请求正在处理中，请稍后重试",
            )
        raise AgencyTransactionConflict(
            "idempotency_request_failed",
            "该幂等请求此前未成功完成，请更换 Idempotency-Key 后重试",
        )

    @staticmethod
    def _complete_idempotency(
        state: IdempotencyState,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> None:
        state.record.status = "completed"
        state.record.resource_type = resource_type
        state.record.resource_id = str(resource_id)

    @staticmethod
    def _ensure_replay_matches(
        state: IdempotencyState,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
    ) -> None:
        if (
            state.record.resource_type != resource_type
            or state.record.resource_id != str(resource_id)
        ):
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录与当前交易资源不匹配",
            )

    async def _load_replayed_quote(
        self,
        state: IdempotencyState,
        *,
        agency_id: uuid.UUID,
    ) -> AgencyQuote:
        if state.record.resource_type != "agency_quote":
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录不属于报价资源",
            )
        try:
            resource_id = uuid.UUID(str(state.record.resource_id))
        except (TypeError, ValueError) as error:
            raise AgencyTransactionPersistenceError(
                "idempotency_resource_missing",
                "幂等记录缺少有效的报价资源",
            ) from error
        result = await self.db.execute(
            select(AgencyQuote)
            .where(AgencyQuote.id == resource_id)
            .where(AgencyQuote.agency_id == agency_id)
        )
        quote = result.scalar_one_or_none()
        if quote is None:
            raise AgencyTransactionPersistenceError(
                "idempotency_resource_missing",
                "幂等记录对应的报价资源不存在",
            )
        return quote

    async def _load_replayed_order(
        self,
        state: IdempotencyState,
        *,
        agency_id: uuid.UUID,
    ) -> AgencyOrder:
        if state.record.resource_type != "agency_order":
            raise AgencyTransactionConflict(
                "idempotency_resource_conflict",
                "幂等记录不属于订单资源",
            )
        try:
            resource_id = uuid.UUID(str(state.record.resource_id))
        except (TypeError, ValueError) as error:
            raise AgencyTransactionPersistenceError(
                "idempotency_resource_missing",
                "幂等记录缺少有效的订单资源",
            ) from error
        result = await self.db.execute(
            select(AgencyOrder)
            .where(AgencyOrder.id == resource_id)
            .where(AgencyOrder.agency_id == agency_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise AgencyTransactionPersistenceError(
                "idempotency_resource_missing",
                "幂等记录对应的订单资源不存在",
            )
        return order

    async def _get_quote(
        self,
        quote_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyQuote:
        statement = select(AgencyQuote).where(AgencyQuote.id == quote_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        quote = result.scalar_one_or_none()
        if quote is None:
            raise _hidden_not_found()
        return quote

    async def _get_order(
        self,
        order_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyOrder:
        statement = select(AgencyOrder).where(AgencyOrder.id == order_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        order = result.scalar_one_or_none()
        if order is None:
            raise _hidden_not_found()
        return order

    @staticmethod
    def _ensure_revision(actual: int, expected: int) -> None:
        if actual != expected:
            raise AgencyTransactionConflict(
                "transaction_revision_conflict",
                "交易资源版本已变化，请刷新后使用最新 revision 重试",
            )

    async def _append_order_event(
        self,
        *,
        order: AgencyOrder,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        actor_user_id: uuid.UUID | None,
        event_metadata: dict[str, Any],
    ) -> AgencyOrderEvent:
        sequence_result = await self.db.execute(
            select(func.coalesce(func.max(AgencyOrderEvent.event_sequence), 0))
            .where(AgencyOrderEvent.order_id == order.id)
        )
        event = AgencyOrderEvent(
            agency_id=order.agency_id,
            order_id=order.id,
            event_sequence=int(sequence_result.scalar_one()) + 1,
            order_revision=order.revision,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor_user_id,
            payload_hash=order.payload_hash,
            event_metadata=event_metadata,
        )
        self.db.add(event)
        return event

    async def create_quote(
        self,
        *,
        actor_user_id: uuid.UUID,
        data: AgencyQuoteCreateRequest,
        idempotency_key: str,
    ) -> AgencyQuote:
        await self._require_quote_manager(
            agency_id=data.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=False,
        )

        quote_payload = build_quote_payload(data)
        state = await self._begin_idempotent_action(
            agency_id=data.agency_id,
            scope="quote.create",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "quote": quote_payload,
            },
        )
        if state.replayed:
            return await self._load_replayed_quote(
                state,
                agency_id=data.agency_id,
            )

        await self._validate_quote_references(data)
        if data.valid_until.astimezone(UTC) <= self._now():
            raise AgencyTransactionValidationError(
                "quote_validity_invalid",
                "报价有效期必须晚于当前时间",
            )
        now = self._now()
        quote = AgencyQuote(
            quote_no=f"Q-{now:%Y%m%d}-{uuid.uuid4().hex[:16].upper()}",
            idempotency_key=self._normalize_idempotency_key(idempotency_key),
            agency_id=data.agency_id,
            user_id=data.customer_user_id,
            conversation_id=data.conversation_id,
            product_id=data.product_id,
            status="draft",
            revision=1,
            payload_hash=canonical_payload_hash(quote_payload),
            total_amount=data.total_amount,
            currency=data.currency,
            snapshot_version=data.snapshot_version,
            quote_snapshot=deepcopy(data.quote_snapshot),
            valid_until=data.valid_until,
        )
        self.db.add(quote)
        await self._flush()
        self._complete_idempotency(
            state,
            resource_type="agency_quote",
            resource_id=quote.id,
        )
        await self._flush()
        return quote

    async def list_quotes(
        self,
        *,
        actor_user_id: uuid.UUID,
        agency_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyQuote], int]:
        membership = await self._get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        filters = [AgencyQuote.agency_id == agency_id]
        if membership is None or membership.role not in QUOTE_MANAGER_ROLES:
            filters.append(AgencyQuote.user_id == actor_user_id)
        if status_filter is not None:
            filters.append(AgencyQuote.status == status_filter)

        result = await self.db.execute(
            select(AgencyQuote)
            .where(*filters)
            .order_by(
                desc(AgencyQuote.created_at),
                desc(AgencyQuote.id),
            )
            .limit(limit)
            .offset(offset)
        )
        count_result = await self.db.execute(
            select(func.count())
            .select_from(AgencyQuote)
            .where(*filters)
        )
        return list(result.scalars().all()), int(count_result.scalar_one())

    async def get_quote(
        self,
        *,
        actor_user_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> AgencyQuote:
        quote = await self._get_quote(quote_id)
        await self._ensure_can_view(
            agency_id=quote.agency_id,
            owner_user_id=quote.user_id,
            actor_user_id=actor_user_id,
        )
        return quote

    async def issue_quote(
        self,
        *,
        actor_user_id: uuid.UUID,
        quote_id: uuid.UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgencyQuote:
        quote = await self._get_quote(quote_id, for_update=True)
        await self._require_quote_manager(
            agency_id=quote.agency_id,
            actor_user_id=actor_user_id,
            hide_resource=True,
        )
        await self._ensure_agency_active(quote.agency_id)
        state = await self._begin_idempotent_action(
            agency_id=quote.agency_id,
            scope="quote.issue",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "quote_id": quote_id,
                "expected_revision": expected_revision,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_quote",
                resource_id=quote.id,
            )
            return quote

        self._ensure_revision(quote.revision, expected_revision)
        if quote.status != "draft":
            raise AgencyTransactionConflict(
                "quote_state_conflict",
                "只有 draft 状态的报价可以发布",
            )
        now = self._now()
        if quote.valid_until.astimezone(UTC) <= now:
            raise AgencyTransactionConflict(
                "quote_expired",
                "报价已过有效期，不能发布",
            )
        quote.status = "offered"
        quote.issued_at = now
        await self._flush()
        self._complete_idempotency(
            state,
            resource_type="agency_quote",
            resource_id=quote.id,
        )
        await self._flush()
        return quote

    async def accept_quote(
        self,
        *,
        actor_user_id: uuid.UUID,
        quote_id: uuid.UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgencyQuote:
        quote = await self._get_quote(quote_id, for_update=True)
        if actor_user_id != quote.user_id:
            raise _hidden_not_found()
        await self._ensure_agency_active(quote.agency_id)
        state = await self._begin_idempotent_action(
            agency_id=quote.agency_id,
            scope="quote.accept",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "quote_id": quote_id,
                "expected_revision": expected_revision,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_quote",
                resource_id=quote.id,
            )
            return quote

        self._ensure_revision(quote.revision, expected_revision)
        if quote.status != "offered":
            raise AgencyTransactionConflict(
                "quote_state_conflict",
                "只有 offered 状态的报价可以由客户接受",
            )
        now = self._now()
        if quote.valid_until.astimezone(UTC) <= now:
            raise AgencyTransactionConflict(
                "quote_expired",
                "报价已过有效期，请联系旅行顾问重新报价",
            )
        quote.status = "accepted"
        quote.accepted_at = now
        await self._flush()
        self._complete_idempotency(
            state,
            resource_type="agency_quote",
            resource_id=quote.id,
        )
        await self._flush()
        return quote

    async def create_order(
        self,
        *,
        actor_user_id: uuid.UUID,
        data: AgencyOrderCreateRequest,
        idempotency_key: str,
    ) -> AgencyOrder:
        quote = await self._get_quote(data.quote_id, for_update=True)
        if quote.agency_id != data.agency_id or quote.user_id != actor_user_id:
            raise _hidden_not_found()
        await self._ensure_agency_active(quote.agency_id)
        state = await self._begin_idempotent_action(
            agency_id=quote.agency_id,
            scope="order.create",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "agency_id": data.agency_id,
                "quote_id": data.quote_id,
                "expected_quote_revision": data.expected_quote_revision,
            },
        )
        if state.replayed:
            return await self._load_replayed_order(
                state,
                agency_id=quote.agency_id,
            )

        self._ensure_revision(quote.revision, data.expected_quote_revision)
        if quote.status != "accepted":
            raise AgencyTransactionConflict(
                "quote_state_conflict",
                "只有客户已接受的报价可以创建订单",
            )
        if quote.valid_until.astimezone(UTC) <= self._now():
            raise AgencyTransactionConflict(
                "quote_expired",
                "报价已过有效期，不能创建订单",
            )
        existing_result = await self.db.execute(
            select(AgencyOrder.id).where(AgencyOrder.quote_id == quote.id)
        )
        if existing_result.scalar_one_or_none() is not None:
            raise AgencyTransactionConflict(
                "order_already_exists",
                "该报价已经创建过订单",
            )

        now = self._now()
        order_payload = {
            "agency_id": quote.agency_id,
            "quote_id": quote.id,
            "quote_revision": quote.revision,
            "quote_payload_hash": quote.payload_hash,
            "customer_user_id": quote.user_id,
            "total_amount": _money_text(quote.total_amount),
            "currency": quote.currency,
            "quote_snapshot": quote.quote_snapshot,
        }
        order = AgencyOrder(
            order_no=f"ORDER-{now:%Y%m%d}-{uuid.uuid4().hex[:16].upper()}",
            agency_id=quote.agency_id,
            quote_id=quote.id,
            user_id=quote.user_id,
            idempotency_key=self._normalize_idempotency_key(idempotency_key),
            status="draft",
            revision=1,
            payload_hash=canonical_payload_hash(order_payload),
            payment_status="not_started",
            fulfillment_status="not_started",
            total_amount=quote.total_amount,
            currency=quote.currency,
            quote_snapshot=deepcopy(quote.quote_snapshot),
            external_action_enabled=False,
        )
        self.db.add(order)
        await self._flush()
        await self._append_order_event(
            order=order,
            event_type="order_created",
            from_status=None,
            to_status="draft",
            actor_user_id=actor_user_id,
            event_metadata={"quote_id": str(quote.id)},
        )
        self._complete_idempotency(
            state,
            resource_type="agency_order",
            resource_id=order.id,
        )
        await self._flush()
        return order

    async def list_orders(
        self,
        *,
        actor_user_id: uuid.UUID,
        agency_id: uuid.UUID,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyOrder], int]:
        membership = await self._get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        filters = [AgencyOrder.agency_id == agency_id]
        if membership is not None and membership.role == "approver":
            filters.append(
                AgencyOrder.id.in_(
                    select(AgencyOrderReview.order_id).where(
                        AgencyOrderReview.agency_id == agency_id
                    )
                )
            )
        elif membership is None or membership.role not in QUOTE_MANAGER_ROLES:
            filters.append(AgencyOrder.user_id == actor_user_id)
        if status_filter is not None:
            filters.append(AgencyOrder.status == status_filter)

        result = await self.db.execute(
            select(AgencyOrder)
            .where(*filters)
            .order_by(
                desc(AgencyOrder.created_at),
                desc(AgencyOrder.id),
            )
            .limit(limit)
            .offset(offset)
        )
        count_result = await self.db.execute(
            select(func.count())
            .select_from(AgencyOrder)
            .where(*filters)
        )
        return list(result.scalars().all()), int(count_result.scalar_one())

    async def get_order(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
    ) -> AgencyOrder:
        order = await self._get_order(order_id)
        await self._ensure_can_view_order(
            order=order,
            actor_user_id=actor_user_id,
        )
        return order

    async def list_order_events(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[AgencyOrderEvent], int]:
        order = await self._get_order(order_id)
        await self._ensure_can_view(
            agency_id=order.agency_id,
            owner_user_id=order.user_id,
            actor_user_id=actor_user_id,
            full_snapshot=False,
        )
        result = await self.db.execute(
            select(AgencyOrderEvent)
            .where(AgencyOrderEvent.order_id == order.id)
            .order_by(AgencyOrderEvent.event_sequence)
            .limit(limit)
            .offset(offset)
        )
        count_result = await self.db.execute(
            select(func.count())
            .select_from(AgencyOrderEvent)
            .where(AgencyOrderEvent.order_id == order.id)
        )
        return list(result.scalars().all()), int(count_result.scalar_one())

    async def submit_order(
        self,
        *,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> AgencyOrder:
        order = await self._get_order(order_id, for_update=True)
        if actor_user_id != order.user_id:
            raise _hidden_not_found()
        await self._ensure_agency_active(order.agency_id)
        state = await self._begin_idempotent_action(
            agency_id=order.agency_id,
            scope="order.submit",
            key=idempotency_key,
            request_payload={
                "actor_user_id": actor_user_id,
                "order_id": order_id,
                "expected_revision": expected_revision,
            },
        )
        if state.replayed:
            self._ensure_replay_matches(
                state,
                resource_type="agency_order",
                resource_id=order.id,
            )
            return order

        self._ensure_revision(order.revision, expected_revision)
        if order.status != "draft":
            raise AgencyTransactionConflict(
                "order_state_conflict",
                "只有 draft 状态的订单可以提交审核",
            )
        from_status = order.status
        order.status = "pending_review"
        await self._flush()
        review = AgencyOrderReview(
            id=uuid.uuid4(),
            agency_id=order.agency_id,
            order_id=order.id,
            status="pending",
            order_revision=order.revision,
            payload_hash=order.payload_hash,
            total_amount=order.total_amount,
            currency=order.currency,
            requested_by_user_id=actor_user_id,
        )
        self.db.add(review)
        await self._append_order_event(
            order=order,
            event_type="order_submitted",
            from_status=from_status,
            to_status=order.status,
            actor_user_id=actor_user_id,
            event_metadata={
                "review_id": str(review.id),
                "review_order_revision": review.order_revision,
                "external_actions_triggered": False,
            },
        )
        self._complete_idempotency(
            state,
            resource_type="agency_order",
            resource_id=order.id,
        )
        await self._flush()
        return order
