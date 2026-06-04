from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel


class AdminOverviewResponse(BaseModel):
    total_users: int
    total_conversations: int
    active_conversations: int
    pending_approvals: int
    generated_at: datetime


class AdminUserSummary(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    created_at: datetime
    conversation_count: int


class AdminUserListResponse(BaseModel):
    users: list[AdminUserSummary]
    total: int
    offset: int = 0
    limit: int = 0


class AdminConversationSummary(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    email: str
    role: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class AdminConversationListResponse(BaseModel):
    conversations: list[AdminConversationSummary]
    total: int
    offset: int = 0
    limit: int = 0


class AdminConversationMessageSummary(BaseModel):
    id: uuid.UUID
    role: str
    content_preview: str
    created_at: datetime
    has_journey_data: bool = False
    has_report_data: bool = False


class AdminApprovalSummary(BaseModel):
    approval_id: str
    action: str
    label: str
    status: str
    reason: str
    created_at: datetime
    decided_at: datetime | None = None


class AdminConversationRuntimeSummary(BaseModel):
    active_workflow: str
    current_step: str
    message_breakdown: dict[str, int]
    has_latest_journey: bool
    has_final_report: bool
    latest_journey_saved_at: int | None = None
    latest_report_title: str | None = None


class AdminConversationDetailResponse(BaseModel):
    conversation: AdminConversationSummary
    runtime: AdminConversationRuntimeSummary
    recent_messages: list[AdminConversationMessageSummary]
    related_approvals: list[AdminApprovalSummary]


class AdminUserRuntimeSummary(BaseModel):
    active_conversation_count: int
    pending_approval_count: int
    latest_conversation_at: datetime | None = None


class AdminUserDetailResponse(BaseModel):
    user: AdminUserSummary
    runtime: AdminUserRuntimeSummary
    recent_conversations: list[AdminConversationSummary]
    recent_approvals: list[AdminApprovalSummary]
