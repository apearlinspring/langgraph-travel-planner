"""Pydantic contracts for lightweight approval governance."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.permissions import ApprovalStatus


class ApprovalPolicyResponse(BaseModel):
    action: str
    label: str
    category: str
    description: str
    requires_approval: bool
    is_blocking: bool
    default_ttl_seconds: int | None = None
    governance_boundary: str
    unsupported_without_integration: list[str] = Field(default_factory=list)
    future_reserved: bool = False


class ApprovalCreateRequest(BaseModel):
    action: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    conversation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_in_seconds: int | None = Field(default=None, ge=1, le=604800)


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ApprovalResponse(BaseModel):
    approval_id: str
    action: str
    label: str
    status: ApprovalStatus
    reason: str
    user_id: str
    conversation_id: str | None = None
    created_at: float
    updated_at: float
    expires_at: float | None = None
    requires_approval: bool
    is_blocking: bool
    governance_boundary: str
    unsupported_without_integration: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    decided_by: str | None = None
    decision_reason: str | None = None
    decided_at: float | None = None


class ApprovalEventResponse(BaseModel):
    approval_id: str
    action: str
    event_type: str
    from_status: ApprovalStatus | None = None
    to_status: ApprovalStatus
    actor_id: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]
    total: int


class ApprovalEventListResponse(BaseModel):
    events: list[ApprovalEventResponse]
    total: int


class ApprovalActionFilter(BaseModel):
    status: ApprovalStatus | None = None
    action: str | None = None
    conversation_id: str | None = None


ApprovalDecision = Literal["approve", "reject", "expire"]
