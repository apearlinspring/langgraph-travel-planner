"""旅行社客户安全认领与服务端同意证据模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgencyCustomerInvitation(Base):
    """把既有平台用户安全绑定到旅行社客户关系的一次性邀请。"""

    __tablename__ = "agency_customer_invitation"
    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_agency_customer_invitation_token_digest",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "id",
            name="uq_agency_customer_invitation_customer_id",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_customer_invitation_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'revoked')",
            name="ck_agency_customer_invitation_status",
        ),
        CheckConstraint(
            "length(token_digest) = 64",
            name="ck_agency_customer_invitation_token_digest",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_agency_customer_invitation_revision",
        ),
        CheckConstraint(
            "expires_at > issued_at",
            name="ck_agency_customer_invitation_expiry",
        ),
        CheckConstraint(
            "(status = 'pending' "
            "AND claimed_by_user_id IS NULL "
            "AND claimed_at IS NULL "
            "AND revoked_by_user_id IS NULL "
            "AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (status = 'claimed' "
            "AND claimed_by_user_id IS NOT NULL "
            "AND claimed_by_user_id = target_user_id "
            "AND claimed_at IS NOT NULL "
            "AND claimed_at >= issued_at "
            "AND claimed_at <= expires_at "
            "AND revoked_by_user_id IS NULL "
            "AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (status = 'revoked' "
            "AND claimed_by_user_id IS NULL "
            "AND claimed_at IS NULL "
            "AND revoked_by_user_id IS NOT NULL "
            "AND revoked_at IS NOT NULL "
            "AND revoked_at >= issued_at "
            "AND revocation_reason IS NOT NULL "
            "AND length(trim(revocation_reason)) > 0)",
            name="ck_agency_customer_invitation_terminal_state",
        ),
        Index(
            "uq_agency_customer_invitation_pending",
            "agency_id",
            "branch_id",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_agency_customer_invitation_target_pending",
            "agency_id",
            "target_user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_agency_customer_invitation_target_status",
            "target_user_id",
            "status",
            "expires_at",
        ),
        Index(
            "ix_agency_customer_invitation_customer_status",
            "agency_id",
            "branch_id",
            "customer_id",
            "status",
            "issued_at",
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
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    token_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    issued_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        Text,
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

    __mapper_args__ = {"version_id_col": revision}


class AgencyCustomerConsentRecord(Base):
    """服务端生成并保持只追加的客户同意决定证据。"""

    __tablename__ = "agency_customer_consent_record"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "id",
            name="uq_agency_customer_consent_record_customer_id",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "consent_sequence",
            name="uq_agency_customer_consent_record_sequence",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "customer_revision",
            name="uq_agency_customer_consent_record_revision",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_customer_consent_record_customer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "customer_id",
                "invitation_id",
            ],
            [
                "agency_customer_invitation.agency_id",
                "agency_customer_invitation.branch_id",
                "agency_customer_invitation.customer_id",
                "agency_customer_invitation.id",
            ],
            name="fk_agency_customer_consent_record_invitation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('granted', 'denied', 'revoked')",
            name="ck_agency_customer_consent_record_decision",
        ),
        CheckConstraint(
            "consent_sequence >= 1",
            name="ck_agency_customer_consent_record_sequence",
        ),
        CheckConstraint(
            "customer_revision >= 1",
            name="ck_agency_customer_consent_record_customer_revision",
        ),
        CheckConstraint(
            "length(trim(consent_version)) > 0",
            name="ck_agency_customer_consent_record_version",
        ),
        CheckConstraint(
            "consent_document_hash IS NULL "
            "OR length(consent_document_hash) = 64",
            name="ck_agency_customer_consent_record_document_hash",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_agency_customer_consent_record_evidence_hash",
        ),
        CheckConstraint(
            "length(trim(evidence_schema_version)) > 0",
            name="ck_agency_customer_consent_record_schema_version",
        ),
        CheckConstraint(
            "evidence_origin IN ('legacy_client_hash', 'server_canonical')",
            name="ck_agency_customer_consent_record_origin",
        ),
        CheckConstraint(
            "(evidence_origin = 'legacy_client_hash' "
            "AND invitation_id IS NULL "
            "AND consent_document_hash IS NULL) "
            "OR (evidence_origin = 'server_canonical' "
            "AND user_id IS NOT NULL "
            "AND consent_document_hash IS NOT NULL "
            "AND (invitation_id IS NOT NULL "
            "OR decision IN ('denied', 'revoked')))",
            name="ck_agency_customer_consent_record_evidence_shape",
        ),
        Index(
            "ix_agency_customer_consent_record_customer_recorded",
            "agency_id",
            "branch_id",
            "customer_id",
            "recorded_at",
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
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    consent_sequence: Mapped[int] = mapped_column(Integer)
    customer_revision: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20))
    consent_version: Mapped[str] = mapped_column(String(40))
    consent_document_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    evidence_hash: Mapped[str] = mapped_column(String(64))
    evidence_schema_version: Mapped[str] = mapped_column(String(40))
    evidence_origin: Mapped[str] = mapped_column(String(24))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )


__all__ = [
    "AgencyCustomerConsentRecord",
    "AgencyCustomerInvitation",
]
