"""旅行社订单人工取消、补偿结果与对账的持久化模型。

该模块只记录人工受控流程及外部结果证据，不直接调用供应商、支付或退款接口。
所有可触发外部动作的标记在数据库层固定为 ``false``。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.agency_transaction import AgencyOrder


class AgencyOrderCancellationCase(Base):
    """一笔订单的人工取消审批与补偿编排状态。"""

    __tablename__ = "agency_order_cancellation_case"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "id",
            name="uq_agency_order_cancellation_case_binding",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id", "order_id"],
            [
                "agency_order.agency_id",
                "agency_order.branch_id",
                "agency_order.customer_id",
                "agency_order.id",
            ],
            name="fk_agency_order_cancellation_case_order",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN "
            "('approval_pending', 'rejected', 'action_pending', "
            "'reconciliation_pending', 'manual_intervention', 'completed')",
            name="ck_agency_order_cancellation_case_status",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_agency_order_cancellation_case_revision",
        ),
        CheckConstraint(
            "order_revision_at_request >= 1",
            name="ck_agency_order_cancellation_case_order_revision",
        ),
        CheckConstraint(
            "reason_code IN "
            "('customer_request', 'customer_consent_withdrawn', "
            "'agency_unable_to_fulfill', 'supplier_unavailable', "
            "'duplicate_order', 'pricing_or_booking_error', "
            "'force_majeure', 'compliance_or_risk')",
            name="ck_agency_order_cancellation_case_reason_code",
        ),
        CheckConstraint(
            "reason_detail IS NULL "
            "OR (length(trim(reason_detail)) BETWEEN 1 AND 500)",
            name="ck_agency_order_cancellation_case_reason_detail",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_cancellation_case_currency",
        ),
        CheckConstraint(
            "approved_refund_amount IS NULL "
            "OR approved_refund_amount >= 0",
            name="ck_agency_order_cancellation_case_refund_amount",
        ),
        CheckConstraint(
            "NOT external_action_triggered",
            name="ck_agency_order_cancellation_case_external_action",
        ),
        CheckConstraint(
            "reviewed_by_user_id IS NULL "
            "OR reviewed_by_user_id <> requested_by_user_id",
            name="ck_agency_order_cancellation_case_four_eyes",
        ),
        CheckConstraint(
            "review_note IS NULL "
            "OR (length(trim(review_note)) BETWEEN 1 AND 500)",
            name="ck_agency_order_cancellation_case_review_note",
        ),
        CheckConstraint(
            "(status = 'approval_pending' "
            "AND review_decision IS NULL "
            "AND reviewed_by_user_id IS NULL "
            "AND reviewed_at IS NULL "
            "AND approved_refund_amount IS NULL "
            "AND completed_at IS NULL) "
            "OR (status = 'rejected' "
            "AND review_decision IS NOT NULL "
            "AND review_decision = 'rejected' "
            "AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL "
            "AND approved_refund_amount IS NULL "
            "AND completed_at IS NULL) "
            "OR (status IN "
            "('action_pending', 'reconciliation_pending', "
            "'manual_intervention') "
            "AND review_decision IS NOT NULL "
            "AND review_decision = 'approved' "
            "AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL "
            "AND completed_at IS NULL) "
            "OR (status = 'completed' "
            "AND review_decision IS NOT NULL "
            "AND review_decision = 'approved' "
            "AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_agency_order_cancellation_case_review_shape",
        ),
        CheckConstraint(
            "(refund_required "
            "AND (review_decision <> 'approved' "
            "OR approved_refund_amount IS NOT NULL)) "
            "OR (NOT refund_required AND approved_refund_amount IS NULL)",
            name="ck_agency_order_cancellation_case_refund_shape",
        ),
        CheckConstraint(
            "status NOT IN "
            "('action_pending', 'reconciliation_pending', "
            "'manual_intervention') "
            "OR supplier_cancel_required OR refund_required",
            name="ck_agency_order_cancellation_case_action_required",
        ),
        Index(
            "uq_agency_order_cancellation_case_open",
            "agency_id",
            "order_id",
            unique=True,
            postgresql_where=text(
                "status IN ('approval_pending', 'action_pending', "
                "'reconciliation_pending', 'manual_intervention')"
            ),
            sqlite_where=text(
                "status IN ('approval_pending', 'action_pending', "
                "'reconciliation_pending', 'manual_intervention')"
            ),
        ),
        Index(
            "ix_agency_order_cancellation_case_branch_status",
            "agency_id",
            "branch_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_order_cancellation_case_customer",
            "agency_id",
            "branch_id",
            "customer_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(32),
        default="approval_pending",
    )
    order_revision_at_request: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(64))
    reason_detail: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    supplier_cancel_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    refund_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    approved_refund_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    review_decision: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_note: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    external_action_triggered: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
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

    order: Mapped["AgencyOrder"] = relationship(
        back_populates="cancellation_cases",
    )
    events: Mapped[list["AgencyOrderCancellationEvent"]] = relationship(
        back_populates="cancellation_case",
        order_by="AgencyOrderCancellationEvent.event_sequence",
    )
    compensation_records: Mapped[list["AgencyOrderCompensationRecord"]] = (
        relationship(
            back_populates="cancellation_case",
            order_by="AgencyOrderCompensationRecord.record_sequence",
        )
    )
    reconciliation_records: Mapped[
        list["AgencyOrderReconciliationRecord"]
    ] = relationship(
        back_populates="cancellation_case",
        order_by="AgencyOrderReconciliationRecord.created_at",
    )

    __mapper_args__ = {"version_id_col": revision}


class AgencyOrderCancellationEvent(Base):
    """取消 case 的只追加审计事件。"""

    __tablename__ = "agency_order_cancellation_event"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "event_sequence",
            name="uq_agency_order_cancellation_event_sequence",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "order_id",
                "customer_id",
                "cancellation_case_id",
            ],
            [
                "agency_order_cancellation_case.agency_id",
                "agency_order_cancellation_case.branch_id",
                "agency_order_cancellation_case.order_id",
                "agency_order_cancellation_case.customer_id",
                "agency_order_cancellation_case.id",
            ],
            name="fk_agency_order_cancellation_event_case",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_order_cancellation_event_sequence",
        ),
        CheckConstraint(
            "case_revision >= 1",
            name="ck_agency_order_cancellation_event_revision",
        ),
        CheckConstraint(
            "length(trim(event_type)) BETWEEN 1 AND 64",
            name="ck_agency_order_cancellation_event_type",
        ),
        CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_agency_order_cancellation_event_payload_hash",
        ),
        Index(
            "ix_agency_order_cancellation_event_case_created",
            "agency_id",
            "cancellation_case_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    cancellation_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    event_sequence: Mapped[int] = mapped_column(Integer)
    case_revision: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )

    cancellation_case: Mapped[AgencyOrderCancellationCase] = relationship(
        back_populates="events",
    )


class AgencyOrderCompensationRecord(Base):
    """人工执行供应商取消或退款后写入的只追加结果。"""

    __tablename__ = "agency_order_compensation_record"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "id",
            name="uq_agency_order_compensation_record_binding",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "order_id",
            "customer_id",
            "cancellation_case_id",
            "record_sequence",
            name="uq_agency_order_compensation_record_sequence",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "order_id",
                "customer_id",
                "cancellation_case_id",
            ],
            [
                "agency_order_cancellation_case.agency_id",
                "agency_order_cancellation_case.branch_id",
                "agency_order_cancellation_case.order_id",
                "agency_order_cancellation_case.customer_id",
                "agency_order_cancellation_case.id",
            ],
            name="fk_agency_order_compensation_record_case",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "record_sequence >= 1",
            name="ck_agency_order_compensation_record_sequence",
        ),
        CheckConstraint(
            "case_revision >= 1",
            name="ck_agency_order_compensation_record_revision",
        ),
        CheckConstraint(
            "action_type IN ('supplier_cancel', 'refund')",
            name="ck_agency_order_compensation_record_action",
        ),
        CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'unknown')",
            name="ck_agency_order_compensation_record_outcome",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_agency_order_compensation_record_amount",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_agency_order_compensation_record_currency",
        ),
        CheckConstraint(
            "external_reference_hash IS NULL "
            "OR length(external_reference_hash) = 64",
            name="ck_agency_order_compensation_record_reference_hash",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_agency_order_compensation_record_evidence_hash",
        ),
        CheckConstraint(
            "NOT system_external_action_triggered",
            name="ck_agency_order_compensation_record_external_action",
        ),
        CheckConstraint(
            "action_type <> 'supplier_cancel' OR amount = 0",
            name="ck_agency_order_compensation_record_supplier_amount",
        ),
        Index(
            "ix_agency_order_compensation_record_case_action",
            "agency_id",
            "cancellation_case_id",
            "action_type",
            "record_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    cancellation_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    record_sequence: Mapped[int] = mapped_column(Integer)
    case_revision: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(24))
    outcome: Mapped[str] = mapped_column(String(20))
    external_reference_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    evidence_hash: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    system_external_action_triggered: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )

    cancellation_case: Mapped[AgencyOrderCancellationCase] = relationship(
        back_populates="compensation_records",
    )
    reconciliation_record: Mapped[
        "AgencyOrderReconciliationRecord | None"
    ] = relationship(
        back_populates="compensation_record",
        uselist=False,
        overlaps="reconciliation_records",
    )


class AgencyOrderReconciliationRecord(Base):
    """对一个人工补偿结果进行独立核对的只追加证据。"""

    __tablename__ = "agency_order_reconciliation_record"
    __table_args__ = (
        UniqueConstraint(
            "compensation_record_id",
            name="uq_agency_order_reconciliation_compensation",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "order_id",
                "customer_id",
                "cancellation_case_id",
            ],
            [
                "agency_order_cancellation_case.agency_id",
                "agency_order_cancellation_case.branch_id",
                "agency_order_cancellation_case.order_id",
                "agency_order_cancellation_case.customer_id",
                "agency_order_cancellation_case.id",
            ],
            name="fk_agency_order_reconciliation_record_case",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "order_id",
                "customer_id",
                "cancellation_case_id",
                "compensation_record_id",
            ],
            [
                "agency_order_compensation_record.agency_id",
                "agency_order_compensation_record.branch_id",
                "agency_order_compensation_record.order_id",
                "agency_order_compensation_record.customer_id",
                "agency_order_compensation_record.cancellation_case_id",
                "agency_order_compensation_record.id",
            ],
            name="fk_agency_order_reconciliation_record_compensation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "case_revision >= 1",
            name="ck_agency_order_reconciliation_record_revision",
        ),
        CheckConstraint(
            "outcome IN ('matched', 'mismatched', 'unverifiable')",
            name="ck_agency_order_reconciliation_record_outcome",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_agency_order_reconciliation_record_evidence_hash",
        ),
        CheckConstraint(
            "(observed_amount IS NULL AND currency IS NULL) "
            "OR (observed_amount IS NOT NULL "
            "AND currency IS NOT NULL "
            "AND observed_amount >= 0 "
            "AND length(currency) = 3 "
            "AND currency = upper(currency))",
            name="ck_agency_order_reconciliation_record_amount",
        ),
        Index(
            "ix_agency_order_reconciliation_record_case_created",
            "agency_id",
            "cancellation_case_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    cancellation_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    compensation_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    case_revision: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    observed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    reconciled_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    evidence_hash: Mapped[str] = mapped_column(String(64))
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )

    cancellation_case: Mapped[AgencyOrderCancellationCase] = relationship(
        back_populates="reconciliation_records",
        overlaps="compensation_record,reconciliation_record",
    )
    compensation_record: Mapped[AgencyOrderCompensationRecord] = relationship(
        back_populates="reconciliation_record",
        overlaps="cancellation_case,reconciliation_records",
    )
