"""Lightweight approval governance API."""
from __future__ import annotations

import inspect

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_current_user
from app.core.approval import (
    ApprovalGovernanceManager,
    ApprovalNotFound,
    ApprovalPersistenceError,
    ApprovalStateError,
    ApprovalStore,
    DatabaseApprovalStore,
    approval_store,
)
from app.core.permissions import get_sensitive_action_policy, list_sensitive_action_policies
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
            detail=str(error),
        )
    if isinstance(error, ApprovalStateError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
    if isinstance(error, ApprovalPersistenceError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(error),
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
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """List the current user's approval records."""

    try:
        if action:
            get_sensitive_action_policy(action)
        records = await _maybe_await(
            approval_service.list_records(
                user_id=str(user.id),
                status=status_filter,
                action=action,
                conversation_id=conversation_id,
            )
        )
    except (ValueError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    approvals = [_record_response(record) for record in records]
    return ApprovalListResponse(approvals=approvals, total=len(approvals))


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
    if record.user_id != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="审批记录不存在",
        )
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

    try:
        record = await _maybe_await(approval_service.get(approval_id))
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        record = await _maybe_await(
            approval_service.approve(
                approval_id,
                decided_by=str(user.id),
                decision_reason=data.reason if data else None,
            )
        )
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


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

    try:
        record = await _maybe_await(approval_service.get(approval_id))
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        record = await _maybe_await(
            approval_service.reject(
                approval_id,
                decided_by=str(user.id),
                decision_reason=data.reason if data else None,
            )
        )
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


@router.post("/{approval_id}/expire", response_model=ApprovalResponse)
async def expire_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
    approval_service: DatabaseApprovalStore | ApprovalStore = Depends(
        get_approval_service
    ),
):
    """Manually expire a pending sensitive action."""

    try:
        record = await _maybe_await(approval_service.get(approval_id))
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        record = await _maybe_await(approval_service.expire(approval_id))
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


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
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        events = await _maybe_await(approval_service.list_events(approval_id))
    except (ApprovalNotFound, ApprovalStateError, ApprovalPersistenceError) as error:
        raise _approval_error_to_http(error) from error
    responses = [_event_response(event) for event in events]
    return ApprovalEventListResponse(events=responses, total=len(responses))
