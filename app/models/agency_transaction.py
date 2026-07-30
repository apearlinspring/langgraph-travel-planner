"""旅行社交易域的最小持久化模型。

这些模型只提供租户、产品、报价、订单、支付尝试和履约记录的数据骨架。
真实外部动作标记默认关闭；后续只能由 fail-closed（故障时默认拒绝）的服务配置、
人工审批与幂等门禁显式放行，模型本身不会触发支付、锁库存或供应商履约。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    and_,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.models.base import Base
from app.models.agency_customer_lifecycle import AgencyCustomer


class Agency(Base):
    """独立经营和授权边界内的旅行社租户。"""

    __tablename__ = "agency"
    __table_args__ = (
        UniqueConstraint("agency_code", name="uq_agency_code"),
        CheckConstraint(
            "status IN ('draft', 'active', 'suspended', 'closed')",
            name="ck_agency_status",
        ),
        Index("ix_agency_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    memberships: Mapped[list["AgencyMembership"]] = relationship(
        back_populates="agency",
    )
    customers: Mapped[list["AgencyCustomer"]] = relationship(
        back_populates="agency",
    )
    products: Mapped[list["SupplierProduct"]] = relationship(
        back_populates="agency",
    )
    quotes: Mapped[list["AgencyQuote"]] = relationship(back_populates="agency")
    orders: Mapped[list["AgencyOrder"]] = relationship(back_populates="agency")
    order_events: Mapped[list["AgencyOrderEvent"]] = relationship(
        back_populates="agency",
    )
    idempotency_records: Mapped[list["IdempotencyRecord"]] = relationship(
        back_populates="agency",
    )


class AgencyMembership(Base):
    """用户在旅行社租户内的角色和有效状态。"""

    __tablename__ = "agency_membership"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "user_id",
            name="uq_agency_membership_agency_user",
        ),
        UniqueConstraint(
            "agency_id",
            "id",
            name="uq_agency_membership_agency_id",
        ),
        CheckConstraint(
            "role IN "
            "('travel_advisor', 'booking_operator', 'approver', 'finance', "
            "'auditor', 'branch_manager', 'admin', 'owner')",
            name="ck_agency_membership_role",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_agency_membership_status",
        ),
        Index("ix_agency_membership_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    role: Mapped[str] = mapped_column(String(24), default="travel_advisor")
    status: Mapped[str] = mapped_column(String(20), default="invited")
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    agency: Mapped[Agency] = relationship(back_populates="memberships")


class SupplierProduct(Base):
    """旅行社可销售的供应商产品。"""

    __tablename__ = "supplier_product"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "id",
            name="uq_supplier_product_agency_id",
        ),
        UniqueConstraint(
            "agency_id",
            "supplier_code",
            "external_product_code",
            name="uq_supplier_product_supplier_external",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'inactive', 'retired')",
            name="ck_supplier_product_status",
        ),
        Index(
            "ix_supplier_product_agency_type_status",
            "agency_id",
            "product_type",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
    )
    supplier_code: Mapped[str] = mapped_column(String(64))
    external_product_code: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    product_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    product_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    agency: Mapped[Agency] = relationship(back_populates="products")
    quotes: Mapped[list["AgencyQuote"]] = relationship(
        back_populates="product",
        primaryjoin=lambda: and_(
            SupplierProduct.agency_id == AgencyQuote.agency_id,
            SupplierProduct.id == foreign(AgencyQuote.product_id),
        ),
        foreign_keys=lambda: [AgencyQuote.product_id],
    )
    fulfillments: Mapped[list["FulfillmentRecord"]] = relationship(
        back_populates="product",
        primaryjoin=lambda: and_(
            SupplierProduct.agency_id == FulfillmentRecord.agency_id,
            SupplierProduct.id == foreign(FulfillmentRecord.product_id),
        ),
        foreign_keys=lambda: [FulfillmentRecord.product_id],
    )


class AgencyQuote(Base):
    """面向客户的报价及其不可依赖上游实时状态的快照。"""

    __tablename__ = "agency_quote"
    __table_args__ = (
        UniqueConstraint("quote_no", name="uq_agency_quote_no"),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "user_id",
            "id",
            name="uq_agency_quote_order_binding",
        ),
        UniqueConstraint(
            "agency_id",
            "idempotency_key",
            name="uq_agency_quote_agency_idempotency",
        ),
        ForeignKeyConstraint(
            ["agency_id", "product_id"],
            ["supplier_product.agency_id", "supplier_product.id"],
            name="fk_agency_quote_product_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_agency_quote_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id", "user_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
                "agency_customer.user_id",
            ],
            name="fk_agency_quote_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('draft', 'offered', 'accepted', 'expired', 'cancelled')",
            name="ck_agency_quote_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_agency_quote_amount"),
        CheckConstraint("revision >= 1", name="ck_agency_quote_revision"),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_quote_payload_hash",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_quote_currency",
        ),
        Index(
            "ix_agency_quote_agency_user_status",
            "agency_id",
            "user_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_quote_agency_status_created",
            "agency_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_quote_branch_customer_status",
            "agency_id",
            "branch_id",
            "customer_id",
            "status",
            "created_at",
            "id",
        ),
        Index("ix_agency_quote_valid_until", "valid_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    quote_no: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload_hash: Mapped[str] = mapped_column(String(64))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    snapshot_version: Mapped[str] = mapped_column(
        String(32),
        default="agency_quote.v1",
    )
    quote_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    agency: Mapped[Agency] = relationship(back_populates="quotes")
    product: Mapped[SupplierProduct | None] = relationship(
        back_populates="quotes",
        primaryjoin=lambda: and_(
            AgencyQuote.agency_id == SupplierProduct.agency_id,
            foreign(AgencyQuote.product_id) == SupplierProduct.id,
        ),
        foreign_keys=lambda: [AgencyQuote.product_id],
    )
    order: Mapped["AgencyOrder | None"] = relationship(
        back_populates="quote",
        primaryjoin=lambda: and_(
            AgencyQuote.agency_id == AgencyOrder.agency_id,
            AgencyQuote.branch_id == AgencyOrder.branch_id,
            AgencyQuote.customer_id == AgencyOrder.customer_id,
            AgencyQuote.user_id == AgencyOrder.user_id,
            AgencyQuote.id == foreign(AgencyOrder.quote_id),
        ),
        foreign_keys=lambda: [AgencyOrder.quote_id],
        uselist=False,
    )

    __mapper_args__ = {"version_id_col": revision}


class AgencyOrder(Base):
    """由已确认报价创建的旅行社订单。"""

    __tablename__ = "agency_order"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_agency_order_no"),
        UniqueConstraint("quote_id", name="uq_agency_order_quote"),
        UniqueConstraint(
            "agency_id",
            "id",
            name="uq_agency_order_agency_id",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "id",
            name="uq_agency_order_branch_id",
        ),
        UniqueConstraint(
            "agency_id",
            "idempotency_key",
            name="uq_agency_order_agency_idempotency",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "customer_id",
                "user_id",
                "quote_id",
            ],
            [
                "agency_quote.agency_id",
                "agency_quote.branch_id",
                "agency_quote.customer_id",
                "agency_quote.user_id",
                "agency_quote.id",
            ],
            name="fk_agency_order_quote_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_agency_order_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_order_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN "
            "('draft', 'pending_review', 'approved', 'review_rejected', "
            "'processing', 'manual_intervention', 'completed', 'failed', "
            "'cancellation_pending', 'cancelled')",
            name="ck_agency_order_status",
        ),
        CheckConstraint(
            "payment_status IN "
            "('not_started', 'pending', 'paid', 'failed', "
            "'partially_refunded', 'refunded')",
            name="ck_agency_order_payment_status",
        ),
        CheckConstraint(
            "fulfillment_status IN "
            "('not_started', 'pending', 'confirmed', 'in_progress', "
            "'completed', 'failed', 'cancelled')",
            name="ck_agency_order_fulfillment_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_agency_order_amount"),
        CheckConstraint("revision >= 1", name="ck_agency_order_revision"),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_payload_hash",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_currency",
        ),
        Index(
            "ix_agency_order_agency_user_status",
            "agency_id",
            "user_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_order_agency_status_created",
            "agency_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_order_branch_customer_status",
            "agency_id",
            "branch_id",
            "customer_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_order_payment_fulfillment",
            "payment_status",
            "fulfillment_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    order_no: Mapped[str] = mapped_column(String(40))
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload_hash: Mapped[str] = mapped_column(String(64))
    payment_status: Mapped[str] = mapped_column(
        String(24),
        default="not_started",
    )
    fulfillment_status: Mapped[str] = mapped_column(
        String(24),
        default="not_started",
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    quote_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    external_action_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    agency: Mapped[Agency] = relationship(back_populates="orders")
    quote: Mapped[AgencyQuote] = relationship(
        back_populates="order",
        primaryjoin=lambda: and_(
            AgencyOrder.agency_id == AgencyQuote.agency_id,
            AgencyOrder.branch_id == AgencyQuote.branch_id,
            AgencyOrder.customer_id == AgencyQuote.customer_id,
            AgencyOrder.user_id == AgencyQuote.user_id,
            foreign(AgencyOrder.quote_id) == AgencyQuote.id,
        ),
        foreign_keys=lambda: [AgencyOrder.quote_id],
    )
    payment_attempts: Mapped[list["PaymentAttempt"]] = relationship(
        back_populates="order",
        primaryjoin=lambda: and_(
            AgencyOrder.agency_id == PaymentAttempt.agency_id,
            AgencyOrder.id == foreign(PaymentAttempt.order_id),
        ),
        foreign_keys=lambda: [PaymentAttempt.order_id],
    )
    fulfillments: Mapped[list["FulfillmentRecord"]] = relationship(
        back_populates="order",
        primaryjoin=lambda: and_(
            AgencyOrder.agency_id == FulfillmentRecord.agency_id,
            AgencyOrder.id == foreign(FulfillmentRecord.order_id),
        ),
        foreign_keys=lambda: [FulfillmentRecord.order_id],
    )
    events: Mapped[list["AgencyOrderEvent"]] = relationship(
        back_populates="order",
        order_by="AgencyOrderEvent.event_sequence",
        primaryjoin=lambda: and_(
            AgencyOrder.agency_id == AgencyOrderEvent.agency_id,
            AgencyOrder.branch_id == AgencyOrderEvent.branch_id,
            AgencyOrder.id == foreign(AgencyOrderEvent.order_id),
        ),
        foreign_keys=lambda: [AgencyOrderEvent.order_id],
    )
    __mapper_args__ = {"version_id_col": revision}


class AgencyOrderEvent(Base):
    """订单状态和关键负载变更的只追加事件。"""

    __tablename__ = "agency_order_event"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "event_sequence",
            name="uq_agency_order_event_sequence",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "order_id"],
            [
                "agency_order.agency_id",
                "agency_order.branch_id",
                "agency_order.id",
            ],
            name="fk_agency_order_event_order_branch",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_order_event_sequence",
        ),
        CheckConstraint(
            "order_revision >= 1",
            name="ck_agency_order_event_revision",
        ),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_event_payload_hash",
        ),
        Index(
            "ix_agency_order_event_agency_order_created",
            "agency_id",
            "order_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
    )
    event_sequence: Mapped[int] = mapped_column(Integer)
    order_revision: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(48))
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )

    agency: Mapped[Agency] = relationship(back_populates="order_events")
    order: Mapped[AgencyOrder] = relationship(
        back_populates="events",
        primaryjoin=lambda: and_(
            AgencyOrderEvent.agency_id == AgencyOrder.agency_id,
            AgencyOrderEvent.branch_id == AgencyOrder.branch_id,
            foreign(AgencyOrderEvent.order_id) == AgencyOrder.id,
        ),
        foreign_keys=lambda: [AgencyOrderEvent.order_id],
    )


class IdempotencyRecord(Base):
    """跨交易动作复用的租户级幂等请求记录。"""

    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "scope",
            "key",
            name="uq_idempotency_agency_scope_key",
        ),
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed')",
            name="ck_idempotency_status",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_idempotency_request_hash",
        ),
        Index(
            "ix_idempotency_agency_scope_status",
            "agency_id",
            "scope",
            "status",
        ),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agency.id", ondelete="RESTRICT"),
    )
    scope: Mapped[str] = mapped_column(String(80))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    resource_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    agency: Mapped[Agency] = relationship(back_populates="idempotency_records")


class PaymentAttempt(Base):
    """支付尝试账本；当前实现不会调用真实外部支付。"""

    __tablename__ = "payment_attempt"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_payment_attempt_order_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "order_id",
            "attempt_no",
            name="uq_payment_attempt_order_sequence",
        ),
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_payment_attempt_order_idempotency",
        ),
        CheckConstraint(
            "status IN "
            "('not_started', 'approval_required', 'processing', 'succeeded', "
            "'failed', 'cancelled')",
            name="ck_payment_attempt_status",
        ),
        CheckConstraint("amount >= 0", name="ck_payment_attempt_amount"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_payment_attempt_currency",
        ),
        Index("ix_payment_attempt_order_status", "order_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    provider_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), default="not_started")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    external_action_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    provider_reference: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    order: Mapped[AgencyOrder] = relationship(
        back_populates="payment_attempts",
        primaryjoin=lambda: and_(
            PaymentAttempt.agency_id == AgencyOrder.agency_id,
            foreign(PaymentAttempt.order_id) == AgencyOrder.id,
        ),
        foreign_keys=lambda: [PaymentAttempt.order_id],
    )


class FulfillmentRecord(Base):
    """订单中一个供应商履约项的状态账本。"""

    __tablename__ = "fulfillment_record"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_fulfillment_order_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "product_id"],
            ["supplier_product.agency_id", "supplier_product.id"],
            name="fk_fulfillment_product_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "order_id",
            "line_item_key",
            name="uq_fulfillment_order_line_item",
        ),
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_fulfillment_order_idempotency",
        ),
        CheckConstraint(
            "status IN "
            "('not_started', 'approval_required', 'pending', 'confirmed', "
            "'in_progress', 'completed', 'failed', 'cancelled')",
            name="ck_fulfillment_status",
        ),
        Index("ix_fulfillment_order_status", "order_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    line_item_key: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    provider_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), default="not_started")
    external_action_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    provider_reference: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    fulfillment_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )

    order: Mapped[AgencyOrder] = relationship(
        back_populates="fulfillments",
        primaryjoin=lambda: and_(
            FulfillmentRecord.agency_id == AgencyOrder.agency_id,
            foreign(FulfillmentRecord.order_id) == AgencyOrder.id,
        ),
        foreign_keys=lambda: [FulfillmentRecord.order_id],
    )
    product: Mapped[SupplierProduct | None] = relationship(
        back_populates="fulfillments",
        primaryjoin=lambda: and_(
            FulfillmentRecord.agency_id == SupplierProduct.agency_id,
            foreign(FulfillmentRecord.product_id) == SupplierProduct.id,
        ),
        foreign_keys=lambda: [FulfillmentRecord.product_id],
    )
