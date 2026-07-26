"""旅行社订单内部审核模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgencyOrderReview(Base):
    """与订单版本、金额和负载摘要绑定的旅行社内部审核。"""

    __tablename__ = "agency_order_review"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "order_id"],
            ["agency_order.agency_id", "agency_order.id"],
            name="fk_agency_order_review_order_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "agency_id",
            "order_id",
            "order_revision",
            name="uq_agency_order_review_order_revision",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_agency_order_review_status",
        ),
        CheckConstraint(
            "order_revision >= 1",
            name="ck_agency_order_review_revision",
        ),
        CheckConstraint(
            "decision_order_revision IS NULL "
            "OR decision_order_revision = order_revision + 1",
            name="ck_agency_order_review_decision_revision",
        ),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_review_payload_hash",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_agency_order_review_amount",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_review_currency",
        ),
        CheckConstraint(
            "decided_by_user_id IS NULL "
            "OR decided_by_user_id <> requested_by_user_id",
            name="ck_agency_order_review_four_eyes",
        ),
        CheckConstraint(
            "(status = 'pending' "
            "AND decided_by_user_id IS NULL "
            "AND decided_at IS NULL "
            "AND decision_reason IS NULL "
            "AND decision_order_revision IS NULL) "
            "OR (status IN ('approved', 'rejected') "
            "AND decided_by_user_id IS NOT NULL "
            "AND decided_at IS NOT NULL "
            "AND decision_order_revision IS NOT NULL)",
            name="ck_agency_order_review_decision_fields",
        ),
        CheckConstraint(
            "status <> 'rejected' "
            "OR (decision_reason IS NOT NULL "
            "AND length(trim(decision_reason)) > 0)",
            name="ck_agency_order_review_rejection_reason",
        ),
        Index(
            "ix_agency_order_review_agency_status_created",
            "agency_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_order_review_order_status",
            "order_id",
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
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    order_revision: Mapped[int] = mapped_column(Integer)
    decision_order_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
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
