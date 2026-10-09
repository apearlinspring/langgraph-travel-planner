"""Lightweight approval governance API."""
from __future__ import annotations

import inspect
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import api_error, error_detail, get_current_user
from app.core.approval import (
    ApprovalGovernanceManager,
    ApprovalNotFound,
    ApprovalPersistenceError,
    ApprovalStateError,
    ApprovalStore,
    DatabaseApprovalStore,
    approval_store,
)
from app.core.permissions import (
    can_decide_approval_record,
    can_list_all_approval_records,
    can_view_approval_record,
    get_sensitive_action_policy,
    get_user_role,
    list_sensitive_action_policies,
)
from app.models.base import async_session_maker
from app.models.user import User
from app.schemas.approval import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalEventListResponse,
    ApprovalEventResponse,
    ApprovalListResponse,
    ApprovalPolicyResponse,
    ApprovalResponse,
)

router = APIRouter(prefix="/approvals", tags=["审批治理"])


def _record_response(record) -> ApprovalResponse:
    return ApprovalResponse.model_validate(record.to_dict())


def _event_response(event) -> ApprovalEventResponse:
    return ApprovalEventResponse.model_validate(event.to_dict())


def _approval_matches_query(record, query_text: str | None) -> bool:
    keyword = str(query_text or "").strip().lower()
    if not keyword:
        return True
    searchable_values = [
        record.approval_id,
        record.action,
        record.label,
        record.status,
        record.reason,
        record.user_id,
        record.conversation_id,
    ]
    return any(
        keyword in str(value or "").lower()
        for value in searchable_values
    )


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def get_approval_service():
    if ApprovalGovernanceManager.should_use_memory_fallback():
        yield approval_store
        return

    async with async_session_maker() as db:
        yield DatabaseApprovalStore(db)


def _approval_error_to_http(error: Exception) -> HTTPException:
    if isinstance(error, ApprovalNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("approval_not_found", str(error)),
        )
    if isinstance(error, ApprovalStateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("approval_state_conflict", str(error)),
        )
    if isinstance(error, ApprovalPersistenceError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("approval_persistence_unavailable", str(error)),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=error_detail("approval_validation_failed", str(error)),
    )


def _permission_denied(
    user: User,
    *,
    code: str,
    message: str,
    required_roles: list[str] | None = None,
) -> HTTPException:
    return api_error(
        status_code=status.HTTP_403_FORBIDDEN,
        code=code,
        message=message,
        required_roles=required_roles,
        current_role=get_user_role(user),
    )


def _ensure_can_view_approval(user: User, record) -> None:
    if can_view_approval_record(user, record.user_id):
        return
    raise _permission_denied(
        user,
        code="approval_view_denied",
        message="当前用户无权查看该审批记录",
    )


def _ensure_can_decide_approval(user: User, record) -> None:
    if can_decide_approval_record(user, record.user_id):
        return
    raise _permission_denied(
        user,
        code="approval_decision_denied",
        message="只有审批操作者或管理员可以批准、拒绝或手动过期审批记录",
        required_roles=["approver", "admin"],
    )


@router.get("/policies", response_model=list[ApprovalPolicyResponse])
async def list_approval_policies(
    user: User = Depends(get_current_user),
):
    """List supported sensitive actions and their approval policy."""

    return [
        ApprovalPolicyResponse.model_validate(policy.to_dict())
        for policy in list_sensitive_action_policies()
    ]


@router.post("", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def mark_sensitive_action(
    data: ApprovalCreateRequest,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """Mark a sensitive action and create an approval record when required."""

    try:
        record = await _maybe_await(
            approval_service.mark_sensitive_action(
                action=data.action,
                reason=data.reason,
                user_id=str(user.id),
                conversation_id=data.conversation_id,
                metadata=data.metadata,
                expires_in_seconds=data.expires_in_seconds,
            )
        )
    except (ValueError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    action: str | None = None,
    conversation_id: str | None = None,
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    query_text: str | None = Query(default=None, alias="q"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """List approval records within the caller's permitted scope."""

    try:
        if action:
            get_sensitive_action_policy(action)
        list_user_id = str(user.id)
        if scope == "all":
            if not can_list_all_approval_records(user):
                raise _permission_denied(
                    user,
                    code="approval_list_all_denied",
                    message="只有审批操作者或管理员可以查看全部审批记录",
                    required_roles=["approver", "admin"],
                )
            list_user_id = None
        records = await _maybe_await(
            approval_service.list_records(
                user_id=list_user_id,
                status=status_filter,
                action=action,
                conversation_id=conversation_id,
            )
        )
    except (ValueError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    filtered_records = [
        record
        for record in records
        if _approval_matches_query(record, query_text)
    ]
    page_records = filtered_records[offset : offset + limit]
    approvals = [_record_response(record) for record in page_records]
    return ApprovalListResponse(
        approvals=approvals,
        total=len(filtered_records),
        offset=offset,
        limit=limit,
    )


async def _decide_approval_record(
    approval_service: DatabaseApprovalStore | ApprovalStore,
    approval_id: str,
    user: User,
    decision: Literal["approve", "reject", "expire"],
    reason: str | None = None,
) -> ApprovalResponse:
    try:
        record = await _maybe_await(approval_service.get(approval_id))
        _ensure_can_decide_approval(user, record)
        if decision == "expire":
            record = await _maybe_await(approval_service.expire(approval_id))
        else:
            record = await _maybe_await(
                getattr(approval_service, decision)(
                    approval_id,
                    decided_by=str(user.id),
                    decision_reason=reason,
                )
            )
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """Get one approval record owned by the current user."""

    try:
        record = await _maybe_await(approval_service.get(approval_id))
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    _ensure_can_view_approval(user, record)
    return _record_response(record)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_approval(
    approval_id: str,
    data: ApprovalDecisionRequest | None = None,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """Approve a pending sensitive action."""
    return await _decide_approval_record(
        approval_service, approval_id, user, "approve", data.reason if data else None
    )


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_approval(
    approval_id: str,
    data: ApprovalDecisionRequest | None = None,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """Reject a pending sensitive action."""
    return await _decide_approval_record(
        approval_service, approval_id, user, "reject", data.reason if data else None
    )


@router.post("/{approval_id}/expire", response_model=ApprovalResponse)
async def expire_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """Manually expire a pending sensitive action."""
    return await _decide_approval_record(approval_service, approval_id, user, "expire")


@router.get("/{approval_id}/events", response_model=ApprovalEventListResponse)
async def list_approval_events(
    approval_id: str,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """List append-only events for one approval record owned by the current user."""

    try:
        record = await _maybe_await(approval_service.get(approval_id))
        _ensure_can_view_approval(user, record)
        events = await _maybe_await(approval_service.list_events(approval_id))
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    responses = [_event_response(event) for event in events]
    return ApprovalEventListResponse(events=responses, total=len(responses))
