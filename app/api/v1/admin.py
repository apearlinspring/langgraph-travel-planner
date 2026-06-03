"""Lightweight admin dashboard API."""
from __future__ import annotations

from datetime import datetime, UTC
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_user_role
from app.core.permissions import get_user_role, normalize_user_role
from app.models.approval import ApprovalRequest
from app.models.base import get_db
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.schemas.admin import (
    AdminApprovalSummary,
    AdminConversationDetailResponse,
    AdminConversationListResponse,
    AdminConversationMessageSummary,
    AdminConversationRuntimeSummary,
    AdminConversationSummary,
    AdminOverviewResponse,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserRuntimeSummary,
    AdminUserSummary,
)
from app.utils.security import redact_sensitive_text

router = APIRouter(prefix="/admin", tags=["后台管理"])


def _build_conversation_summary(
    *,
    conversation: Conversation,
    username: str,
    email: str,
    preferences: dict | None,
    message_count: int,
) -> AdminConversationSummary:
    return AdminConversationSummary(
        id=conversation.id,
        user_id=conversation.user_id,
        username=username,
        email=email,
        role=normalize_user_role((preferences or {}).get("role")),
        title=conversation.title,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=int(message_count or 0),
    )


def _preview_message_content(content: str, *, max_chars: int = 160) -> str:
    compact = " ".join(str(content or "").split())
    redacted = redact_sensitive_text(compact)
    if len(redacted) <= max_chars:
        return redacted
    return f"{redacted[: max_chars - 1]}…"


async def _build_admin_overview(db: AsyncSession) -> AdminOverviewResponse:
    total_users = (
        await db.execute(select(func.count(User.id)))
    ).scalar_one()
    total_conversations = (
        await db.execute(select(func.count(Conversation.id)))
    ).scalar_one()
    active_conversations = (
        await db.execute(
            select(func.count(Conversation.id)).where(Conversation.status == "active")
        )
    ).scalar_one()
    pending_approvals = (
        await db.execute(
            select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending")
        )
    ).scalar_one()

    return AdminOverviewResponse(
        total_users=int(total_users or 0),
        total_conversations=int(total_conversations or 0),
        active_conversations=int(active_conversations or 0),
        pending_approvals=int(pending_approvals or 0),
        generated_at=datetime.now(UTC),
    )


async def _list_admin_users(
    db: AsyncSession,
    *,
    limit: int,
    query_text: str | None,
    role_filter: str | None,
) -> AdminUserListResponse:
    query = (
        select(
            User,
            func.count(Conversation.id).label("conversation_count"),
        )
        .outerjoin(Conversation, Conversation.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
    )
    normalized_role = normalize_user_role(role_filter) if role_filter and role_filter != "all" else None
    if query_text:
        keyword = f"%{query_text.strip()}%"
        query = query.where(
            or_(
                User.username.ilike(keyword),
                User.email.ilike(keyword),
            )
        )
    if normalized_role:
        query = query.where(User.preferences["role"].as_string() == normalized_role)

    rows = (await db.execute(query)).all()
    users = [
        AdminUserSummary(
            id=user.id,
            username=user.username,
            email=user.email,
            role=get_user_role(user),
            created_at=user.created_at,
            conversation_count=int(conversation_count or 0),
        )
        for user, conversation_count in rows
    ]
    return AdminUserListResponse(users=users, total=len(users))


async def _list_admin_conversations(
    db: AsyncSession,
    *,
    limit: int,
    status_filter: str | None,
    query_text: str | None,
    role_filter: str | None,
) -> AdminConversationListResponse:
    message_count_subquery = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    query = (
        select(
            Conversation,
            User.username,
            User.email,
            User.preferences,
            func.coalesce(message_count_subquery.c.message_count, 0).label("message_count"),
        )
        .join(User, User.id == Conversation.user_id)
        .outerjoin(
            message_count_subquery,
            message_count_subquery.c.conversation_id == Conversation.id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    if status_filter and status_filter != "all":
        query = query.where(Conversation.status == status_filter)
    if query_text:
        keyword = f"%{query_text.strip()}%"
        query = query.where(
            or_(
                Conversation.title.ilike(keyword),
                User.username.ilike(keyword),
                User.email.ilike(keyword),
            )
        )
    normalized_role = normalize_user_role(role_filter) if role_filter and role_filter != "all" else None
    if normalized_role:
        query = query.where(User.preferences["role"].as_string() == normalized_role)

    rows = (await db.execute(query)).all()
    conversations = [
        _build_conversation_summary(
            conversation=conversation,
            username=username,
            email=email,
            preferences=preferences,
            message_count=int(message_count or 0),
        )
        for conversation, username, email, preferences, message_count in rows
    ]
    return AdminConversationListResponse(
        conversations=conversations,
        total=len(conversations),
    )


async def _get_admin_conversation_detail(
    db: AsyncSession,
    *,
    conversation_id: str,
) -> AdminConversationDetailResponse:
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        ) from exc

    message_count_subquery = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )

    conversation_row = (
        await db.execute(
            select(
                Conversation,
                User.username,
                User.email,
                User.preferences,
                func.coalesce(message_count_subquery.c.message_count, 0).label("message_count"),
            )
            .join(User, User.id == Conversation.user_id)
            .outerjoin(
                message_count_subquery,
                message_count_subquery.c.conversation_id == Conversation.id,
            )
            .where(Conversation.id == conversation_uuid)
        )
    ).one_or_none()

    if not conversation_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在",
        )

    conversation, username, email, preferences, message_count = conversation_row
    message_rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(6)
        )
    ).scalars().all()
    recent_messages = [
        AdminConversationMessageSummary(
            id=message.id,
            role=message.role,
            content_preview=_preview_message_content(message.content),
            created_at=message.created_at,
            has_journey_data=isinstance((message.extra_info or {}).get("journey_data"), dict),
            has_report_data=isinstance((message.extra_info or {}).get("report_data"), dict),
        )
        for message in message_rows
    ]

    approval_rows = (
        await db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.conversation_id == str(conversation.id))
            .order_by(ApprovalRequest.created_at.desc())
            .limit(6)
        )
    ).scalars().all()
    related_approvals = [
        AdminApprovalSummary(
            approval_id=approval.approval_id,
            action=approval.action,
            label=approval.label,
            status=approval.status,
            reason=redact_sensitive_text(approval.reason or ""),
            created_at=approval.created_at,
            decided_at=approval.decided_at,
        )
        for approval in approval_rows
    ]

    role_counts = (
        await db.execute(
            select(Message.role, func.count(Message.id))
            .where(Message.conversation_id == conversation.id)
            .group_by(Message.role)
        )
    ).all()
    message_breakdown = {str(role): int(count) for role, count in role_counts}
    extra_info = conversation.extra_info or {}
    latest_report_data = extra_info.get("latest_report_data")
    if not isinstance(latest_report_data, dict):
        latest_report_data = next(
            (
                (message.extra_info or {}).get("report_data")
                for message in message_rows
                if isinstance((message.extra_info or {}).get("report_data"), dict)
            ),
            None,
        )
    runtime = AdminConversationRuntimeSummary(
        active_workflow=str(extra_info.get("active_workflow") or "-"),
        current_step=str(extra_info.get("current_step") or "-"),
        message_breakdown=message_breakdown,
        has_latest_journey=isinstance(extra_info.get("latest_journey_data"), dict),
        has_final_report=isinstance(latest_report_data, dict),
        latest_journey_saved_at=extra_info.get("latest_journey_saved_at"),
        latest_report_title=(
            str((latest_report_data or {}).get("title") or "")
            if isinstance(latest_report_data, dict)
            else None
        ) or None,
    )

    return AdminConversationDetailResponse(
        conversation=_build_conversation_summary(
            conversation=conversation,
            username=username,
            email=email,
            preferences=preferences,
            message_count=int(message_count or 0),
        ),
        runtime=runtime,
        recent_messages=recent_messages,
        related_approvals=related_approvals,
    )


async def _get_admin_user_detail(
    db: AsyncSession,
    *,
    user_id: str,
) -> AdminUserDetailResponse:
    try:
        user_uuid = uuid.UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        ) from exc

    user_row = (
        await db.execute(
            select(
                User,
                func.count(Conversation.id).label("conversation_count"),
            )
            .outerjoin(Conversation, Conversation.user_id == User.id)
            .where(User.id == user_uuid)
            .group_by(User.id)
        )
    ).one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    user, conversation_count = user_row
    summary = AdminUserSummary(
        id=user.id,
        username=user.username,
        email=user.email,
        role=get_user_role(user),
        created_at=user.created_at,
        conversation_count=int(conversation_count or 0),
    )

    active_conversation_count = (
        await db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.user_id == user.id,
                Conversation.status == "active",
            )
        )
    ).scalar_one()
    pending_approval_count = (
        await db.execute(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.user_id == str(user.id),
                ApprovalRequest.status == "pending",
            )
        )
    ).scalar_one()

    message_count_subquery = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    recent_conversation_rows = (
        await db.execute(
            select(
                Conversation,
                func.coalesce(message_count_subquery.c.message_count, 0).label("message_count"),
            )
            .outerjoin(
                message_count_subquery,
                message_count_subquery.c.conversation_id == Conversation.id,
            )
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(6)
        )
    ).all()
    recent_conversations = [
        _build_conversation_summary(
            conversation=conversation,
            username=user.username,
            email=user.email,
            preferences=user.preferences,
            message_count=int(message_count or 0),
        )
        for conversation, message_count in recent_conversation_rows
    ]

    recent_approval_rows = (
        await db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.user_id == str(user.id))
            .order_by(ApprovalRequest.created_at.desc())
            .limit(6)
        )
    ).scalars().all()
    recent_approvals = [
        AdminApprovalSummary(
            approval_id=approval.approval_id,
            action=approval.action,
            label=approval.label,
            status=approval.status,
            reason=redact_sensitive_text(approval.reason or ""),
            created_at=approval.created_at,
            decided_at=approval.decided_at,
        )
        for approval in recent_approval_rows
    ]

    return AdminUserDetailResponse(
        user=summary,
        runtime=AdminUserRuntimeSummary(
            active_conversation_count=int(active_conversation_count or 0),
            pending_approval_count=int(pending_approval_count or 0),
            latest_conversation_at=recent_conversations[0].updated_at
            if recent_conversations
            else None,
        ),
        recent_conversations=recent_conversations,
        recent_approvals=recent_approvals,
    )


@router.get("/overview", response_model=AdminOverviewResponse)
async def get_admin_overview(
    _: User = Depends(require_user_role("approver", "admin")),
    db: AsyncSession = Depends(get_db),
):
    return await _build_admin_overview(db)


@router.get("/users", response_model=AdminUserListResponse)
async def list_admin_users(
    limit: int = Query(default=20, ge=1, le=100),
    query_text: str | None = Query(default=None, alias="q"),
    role_filter: str | None = Query(default="all", alias="role"),
    _: User = Depends(require_user_role("approver", "admin")),
    db: AsyncSession = Depends(get_db),
):
    return await _list_admin_users(
        db,
        limit=limit,
        query_text=query_text,
        role_filter=role_filter,
    )


@router.get("/conversations", response_model=AdminConversationListResponse)
async def list_admin_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    status_filter: str | None = Query(default="active", alias="status"),
    query_text: str | None = Query(default=None, alias="q"),
    role_filter: str | None = Query(default="all", alias="role"),
    _: User = Depends(require_user_role("approver", "admin")),
    db: AsyncSession = Depends(get_db),
):
    return await _list_admin_conversations(
        db,
        limit=limit,
        status_filter=status_filter,
        query_text=query_text,
        role_filter=role_filter,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AdminConversationDetailResponse,
)
async def get_admin_conversation_detail(
    conversation_id: str,
    _: User = Depends(require_user_role("approver", "admin")),
    db: AsyncSession = Depends(get_db),
):
    return await _get_admin_conversation_detail(
        db,
        conversation_id=conversation_id,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_admin_user_detail(
    user_id: str,
    _: User = Depends(require_user_role("approver", "admin")),
    db: AsyncSession = Depends(get_db),
):
    return await _get_admin_user_detail(
        db,
        user_id=user_id,
    )
