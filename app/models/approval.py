"""
审批治理与工具审计模型。
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApprovalRequest(Base):
    """敏感动作审批请求表。"""

    __tablename__ = "approval_request"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    approval_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    governance_boundary: Mapped[str] = mapped_column(Text)
    unsupported_without_integration: Mapped[list[str]] = mapped_column(JSON, default=list)
    request_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
    )


class ApprovalEvent(Base):
    """审批事件表，只追加，不更新历史事件。"""

    __tablename__ = "approval_event"
    __table_args__ = (
        Index("ix_approval_event_approval_created", "approval_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    approval_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        index=True,
    )


class ToolAuditEvent(Base):
    """工具调用审计事件表。"""

    __tablename__ = "tool_audit_event"
    __table_args__ = (
        Index("ix_tool_audit_user_conversation", "user_id", "conversation_id"),
        Index("ix_tool_audit_name_status", "name", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(160), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), index=True)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_type: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        index=True,
    )
