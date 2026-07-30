"""旅行社门店、客户生命周期与顾问分配模型。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

BRANCH_ROLES: tuple[str, ...] = (
    "travel_advisor",
    "booking_operator",
    "approver",
    "finance",
    "auditor",
    "branch_manager",
)


class AgencyBranch(Base):
    """旅行社租户内独立授权和客户归属的门店。"""

    __tablename__ = "agency_branch"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "id",
            name="uq_agency_branch_agency_id",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_code",
            name="uq_agency_branch_agency_code",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'closed')",
            name="ck_agency_branch_status",
        ),
        CheckConstraint(
            "length(trim(branch_code)) > 0",
            name="ck_agency_branch_code",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_agency_branch_revision",
        ),
        CheckConstraint(
            "deactivated_at IS NULL OR status <> 'active'",
            name="ck_agency_branch_deactivated",
        ),
        Index(
            "ix_agency_branch_agency_status",
            "agency_id",
            "status",
            "created_at",
            "id",
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
    branch_code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    deactivated_at: Mapped[datetime | None] = mapped_column(
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

    __mapper_args__ = {"version_id_col": revision}


class AgencyCustomer(Base):
    """旅行社门店内可授权、可停用的客户关系。"""

    __tablename__ = "agency_customer"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "user_id",
            name="uq_agency_customer_agency_user",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "id",
            name="uq_agency_customer_branch_id",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_no",
            name="uq_agency_customer_branch_no",
        ),
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "id",
            "user_id",
            name="uq_agency_customer_quote_binding",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_agency_customer_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "id",
                "claimed_invitation_id",
            ],
            [
                "agency_customer_invitation.agency_id",
                "agency_customer_invitation.branch_id",
                "agency_customer_invitation.customer_id",
                "agency_customer_invitation.id",
            ],
            name="fk_agency_customer_claimed_invitation",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "id",
                "current_consent_record_id",
            ],
            [
                "agency_customer_consent_record.agency_id",
                "agency_customer_consent_record.branch_id",
                "agency_customer_consent_record.customer_id",
                "agency_customer_consent_record.id",
            ],
            name="fk_agency_customer_current_consent_record",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint(
            "status IN "
            "('invited', 'prospect', 'active', 'inactive', 'blocked')",
            name="ck_agency_customer_status",
        ),
        CheckConstraint(
            "length(trim(customer_no)) > 0",
            name="ck_agency_customer_no",
        ),
        CheckConstraint(
            "length(trim(source_type)) > 0",
            name="ck_agency_customer_source",
        ),
        CheckConstraint(
            "consent_status IN "
            "('unknown', 'pending', 'granted', 'denied', 'revoked')",
            name="ck_agency_customer_consent_status",
        ),
        CheckConstraint(
            "consent_evidence_hash IS NULL "
            "OR length(consent_evidence_hash) = 64",
            name="ck_agency_customer_consent_evidence_hash",
        ),
        CheckConstraint(
            "(consent_status = 'unknown' "
            "AND consent_version IS NULL "
            "AND consent_evidence_hash IS NULL "
            "AND consent_updated_at IS NULL) "
            "OR (consent_status = 'pending' "
            "AND consent_version IS NOT NULL "
            "AND length(trim(consent_version)) > 0 "
            "AND consent_evidence_hash IS NULL "
            "AND consent_updated_at IS NOT NULL) "
            "OR (consent_status IN ('granted', 'denied', 'revoked') "
            "AND consent_version IS NOT NULL "
            "AND length(trim(consent_version)) > 0 "
            "AND consent_evidence_hash IS NOT NULL "
            "AND consent_updated_at IS NOT NULL)",
            name="ck_agency_customer_consent_evidence",
        ),
        CheckConstraint(
            "binding_provenance IN "
            "('unbound', 'legacy_direct', 'secure_claim')",
            name="ck_agency_customer_binding_provenance",
        ),
        CheckConstraint(
            "(binding_provenance = 'unbound' "
            "AND user_id IS NULL "
            "AND claimed_invitation_id IS NULL "
            "AND claimed_at IS NULL) "
            "OR (binding_provenance = 'legacy_direct' "
            "AND user_id IS NOT NULL "
            "AND claimed_invitation_id IS NULL "
            "AND claimed_at IS NULL) "
            "OR (binding_provenance = 'secure_claim' "
            "AND user_id IS NOT NULL "
            "AND claimed_invitation_id IS NOT NULL "
            "AND claimed_at IS NOT NULL)",
            name="ck_agency_customer_binding_evidence",
        ),
        CheckConstraint(
            "consent_evidence_origin IN "
            "('none', 'legacy_client_hash', 'server_canonical')",
            name="ck_agency_customer_consent_evidence_origin",
        ),
        CheckConstraint(
            "(consent_evidence_origin = 'none' "
            "AND current_consent_record_id IS NULL "
            "AND consent_evidence_hash IS NULL) "
            "OR (consent_evidence_origin = 'legacy_client_hash' "
            "AND current_consent_record_id IS NOT NULL "
            "AND consent_evidence_hash IS NOT NULL) "
            "OR (consent_evidence_origin = 'server_canonical' "
            "AND current_consent_record_id IS NOT NULL "
            "AND consent_evidence_hash IS NOT NULL)",
            name="ck_agency_customer_consent_record_projection",
        ),
        CheckConstraint(
            "status <> 'active' "
            "OR (binding_provenance = 'secure_claim' "
            "AND consent_status = 'granted' "
            "AND consent_evidence_origin = 'server_canonical')",
            name="ck_agency_customer_active_secure_claim",
        ),
        CheckConstraint(
            "lifecycle_revision >= 1",
            name="ck_agency_customer_lifecycle_revision",
        ),
        CheckConstraint(
            "deactivated_at IS NULL "
            "OR status IN ('inactive', 'blocked')",
            name="ck_agency_customer_deactivated",
        ),
        Index("ix_agency_customer_user_status", "user_id", "status"),
        Index(
            "ix_agency_customer_branch_status",
            "agency_id",
            "branch_id",
            "status",
            "created_at",
            "id",
        ),
        Index(
            "ix_agency_customer_claimed_invitation",
            "claimed_invitation_id",
        ),
        Index(
            "ix_agency_customer_current_consent_record",
            "current_consent_record_id",
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
    customer_no: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    binding_provenance: Mapped[str] = mapped_column(
        String(24),
        default="unbound",
    )
    claimed_invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_reference: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="invited")
    consent_status: Mapped[str] = mapped_column(String(20), default="unknown")
    consent_version: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    consent_evidence_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    current_consent_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    consent_evidence_origin: Mapped[str] = mapped_column(
        String(24),
        default="none",
    )
    consent_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lifecycle_revision: Mapped[int] = mapped_column(Integer, default=1)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
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

    agency: Mapped["Agency"] = relationship(back_populates="customers")

    __mapper_args__ = {"version_id_col": lifecycle_revision}


class AgencyBranchRoleGrant(Base):
    """成员在指定门店内获得的最小角色授权。"""

    __tablename__ = "agency_branch_role_grant"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "id",
            "membership_id",
            name="uq_branch_role_grant_assignment_binding",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_branch_role_grant_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "membership_id"],
            ["agency_membership.agency_id", "agency_membership.id"],
            name="fk_branch_role_grant_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role IN "
            "('travel_advisor', 'booking_operator', 'approver', 'finance', "
            "'auditor', 'branch_manager')",
            name="ck_branch_role_grant_role",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_branch_role_grant_status",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_branch_role_grant_revision",
        ),
        CheckConstraint(
            "(status = 'active' "
            "AND revoked_at IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (status = 'revoked' "
            "AND revoked_at IS NOT NULL "
            "AND revocation_reason IS NOT NULL "
            "AND length(trim(revocation_reason)) > 0)",
            name="ck_branch_role_grant_revocation",
        ),
        Index(
            "uq_branch_role_grant_active",
            "agency_id",
            "branch_id",
            "membership_id",
            "role",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_branch_role_grant_member_status",
            "agency_id",
            "membership_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AgencyCustomerEvent(Base):
    """客户生命周期变更的只追加审计事件。"""

    __tablename__ = "agency_customer_event"
    __table_args__ = (
        UniqueConstraint(
            "agency_id",
            "branch_id",
            "customer_id",
            "event_sequence",
            name="uq_agency_customer_event_sequence",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_agency_customer_event_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_agency_customer_event_customer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_sequence >= 1",
            name="ck_agency_customer_event_sequence",
        ),
        CheckConstraint(
            "customer_revision >= 1",
            name="ck_agency_customer_event_revision",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('invited', 'prospect', 'active', 'inactive', 'blocked')",
            name="ck_agency_customer_event_from_status",
        ),
        CheckConstraint(
            "to_status IS NULL OR to_status IN "
            "('invited', 'prospect', 'active', 'inactive', 'blocked')",
            name="ck_agency_customer_event_to_status",
        ),
        Index(
            "ix_agency_customer_event_customer_created",
            "agency_id",
            "branch_id",
            "customer_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    event_sequence: Mapped[int] = mapped_column(Integer)
    customer_revision: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(48))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )


class AgencyCustomerAdvisorAssignment(Base):
    """客户在门店内唯一有效的主顾问分配。"""

    __tablename__ = "agency_customer_advisor_assignment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agency_id", "branch_id"],
            ["agency_branch.agency_id", "agency_branch.id"],
            name="fk_customer_advisor_assignment_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agency_id", "branch_id", "customer_id"],
            [
                "agency_customer.agency_id",
                "agency_customer.branch_id",
                "agency_customer.id",
            ],
            name="fk_customer_advisor_assignment_customer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "agency_id",
                "branch_id",
                "advisor_role_grant_id",
                "advisor_membership_id",
            ],
            [
                "agency_branch_role_grant.agency_id",
                "agency_branch_role_grant.branch_id",
                "agency_branch_role_grant.id",
                "agency_branch_role_grant.membership_id",
            ],
            name="fk_customer_advisor_assignment_grant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active', 'ended')",
            name="ck_customer_advisor_assignment_status",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_customer_advisor_assignment_revision",
        ),
        CheckConstraint(
            "(status = 'active' "
            "AND ended_at IS NULL "
            "AND ended_reason IS NULL) "
            "OR (status = 'ended' "
            "AND ended_at IS NOT NULL "
            "AND ended_reason IS NOT NULL "
            "AND length(trim(ended_reason)) > 0)",
            name="ck_customer_advisor_assignment_ending",
        ),
        Index(
            "uq_customer_advisor_assignment_active",
            "agency_id",
            "branch_id",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_customer_advisor_assignment_advisor_status",
            "agency_id",
            "branch_id",
            "advisor_membership_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    advisor_role_grant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    advisor_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    assignment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
