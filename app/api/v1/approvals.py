"""Lightweight approval governance API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_current_user
from app.core.approval import (
    ApprovalNotFound,
    ApprovalStateError,
    approval_store,
)
from app.core.permissions import get_sensitive_action_policy, list_sensitive_action_policies
from app.models.user import User
from app.schemas.approval import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalListResponse,
    ApprovalPolicyResponse,
    ApprovalResponse,
)

router = APIRouter(prefix="/approvals", tags=["审批治理"])


def _record_response(record) -> ApprovalResponse:
    return ApprovalResponse.model_validate(record.to_dict())


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
):
    """Mark a sensitive action and create an approval record when required."""

    try:
        record = approval_store.mark_sensitive_action(
            action=data.action,
            reason=data.reason,
            user_id=str(user.id),
            conversation_id=data.conversation_id,
            metadata=data.metadata,
            expires_in_seconds=data.expires_in_seconds,
        )
    except ValueError as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    status_filter: str | None = Query(default=None, alias="status"),
    action: str | None = None,
    conversation_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """List the current user's approval records."""

    try:
        if action:
            get_sensitive_action_policy(action)
        records = approval_store.list_records(
            user_id=str(user.id),
            status=status_filter,
            action=action,
            conversation_id=conversation_id,
        )
    except ValueError as error:
        raise _approval_error_to_http(error) from error
    approvals = [_record_response(record) for record in records]
    return ApprovalListResponse(approvals=approvals, total=len(approvals))


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
):
    """Get one approval record owned by the current user."""

    try:
        record = approval_store.get(approval_id)
    except (ApprovalNotFound, ApprovalStateError) as error:
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
):
    """Approve a pending sensitive action."""

    try:
        record = approval_store.get(approval_id)
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        record = approval_store.approve(
            approval_id,
            decided_by=str(user.id),
            decision_reason=data.reason if data else None,
        )
    except (ApprovalNotFound, ApprovalStateError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_approval(
    approval_id: str,
    data: ApprovalDecisionRequest | None = None,
    user: User = Depends(get_current_user),
):
    """Reject a pending sensitive action."""

    try:
        record = approval_store.get(approval_id)
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        record = approval_store.reject(
            approval_id,
            decided_by=str(user.id),
            decision_reason=data.reason if data else None,
        )
    except (ApprovalNotFound, ApprovalStateError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)


@router.post("/{approval_id}/expire", response_model=ApprovalResponse)
async def expire_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
):
    """Manually expire a pending sensitive action."""

    try:
        record = approval_store.get(approval_id)
        if record.user_id != str(user.id):
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        record = approval_store.expire(approval_id)
    except (ApprovalNotFound, ApprovalStateError) as error:
        raise _approval_error_to_http(error) from error
    return _record_response(record)
