"""Lightweight approval records for sensitive action governance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock
from time import time
from typing import Any
from uuid import uuid4

from app.core.permissions import (
    ApprovalStatus,
    get_sensitive_action_policy,
    sanitize_approval_metadata,
)


class ApprovalError(ValueError):
    """Base error for approval governance."""


class ApprovalNotFound(ApprovalError):
    """Raised when an approval record cannot be found."""


class ApprovalStateError(ApprovalError):
    """Raised when a status transition is invalid."""


@dataclass
class ApprovalRecord:
    """A process-local audit record for one sensitive action."""

    approval_id: str
    action: str
    label: str
    status: ApprovalStatus
    reason: str
    user_id: str
    conversation_id: str | None
    created_at: float
    updated_at: float
    expires_at: float | None
    requires_approval: bool
    is_blocking: bool
    governance_boundary: str
    unsupported_without_integration: list[str]
    metadata: dict[str, Any]
    decided_by: str | None = None
    decision_reason: str | None = None
    decided_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> float:
    return time()


def _next_status_for_policy(requires_approval: bool) -> ApprovalStatus:
    return "pending" if requires_approval else "none"


class ApprovalStore:
    """In-memory approval store for the current application process."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, ApprovalRecord] = {}

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def mark_sensitive_action(
        self,
        *,
        action: str,
        reason: str,
        user_id: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        expires_in_seconds: int | None = None,
        now: float | None = None,
    ) -> ApprovalRecord:
        policy = get_sensitive_action_policy(action)
        timestamp = _now() if now is None else now
        ttl_seconds = (
            expires_in_seconds
            if expires_in_seconds is not None
            else policy.default_ttl_seconds
        )
        expires_at = (
            timestamp + ttl_seconds
            if policy.requires_approval and ttl_seconds is not None
            else None
        )
        record = ApprovalRecord(
            approval_id=f"APR-{uuid4().hex[:12].upper()}",
            action=policy.action,
            label=policy.label,
            status=_next_status_for_policy(policy.requires_approval),
            reason=reason.strip() or policy.description,
            user_id=str(user_id),
            conversation_id=str(conversation_id) if conversation_id else None,
            created_at=timestamp,
            updated_at=timestamp,
            expires_at=expires_at,
            requires_approval=policy.requires_approval,
            is_blocking=policy.is_blocking,
            governance_boundary=policy.governance_boundary,
            unsupported_without_integration=list(policy.unsupported_without_integration),
            metadata=sanitize_approval_metadata(metadata),
        )
        with self._lock:
            self._records[record.approval_id] = record
        return record

    def get(self, approval_id: str, *, now: float | None = None) -> ApprovalRecord:
        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
            self._expire_if_due(record, _now() if now is None else now)
            return record

    def list_records(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        action: str | None = None,
        conversation_id: str | None = None,
        now: float | None = None,
    ) -> list[ApprovalRecord]:
        timestamp = _now() if now is None else now
        with self._lock:
            for record in self._records.values():
                self._expire_if_due(record, timestamp)
            records = list(self._records.values())

        if user_id is not None:
            records = [record for record in records if record.user_id == str(user_id)]
        if status:
            records = [record for record in records if record.status == status]
        if action:
            canonical_action = get_sensitive_action_policy(action).action
            records = [record for record in records if record.action == canonical_action]
        if conversation_id is not None:
            records = [
                record
                for record in records
                if record.conversation_id == str(conversation_id)
            ]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def approve(
        self,
        approval_id: str,
        *,
        decided_by: str,
        decision_reason: str | None = None,
        now: float | None = None,
    ) -> ApprovalRecord:
        return self._decide(
            approval_id,
            status="approved",
            decided_by=decided_by,
            decision_reason=decision_reason,
            now=now,
        )

    def reject(
        self,
        approval_id: str,
        *,
        decided_by: str,
        decision_reason: str | None = None,
        now: float | None = None,
    ) -> ApprovalRecord:
        return self._decide(
            approval_id,
            status="rejected",
            decided_by=decided_by,
            decision_reason=decision_reason,
            now=now,
        )

    def expire(
        self,
        approval_id: str,
        *,
        now: float | None = None,
    ) -> ApprovalRecord:
        timestamp = _now() if now is None else now
        with self._lock:
            record = self.get(approval_id, now=timestamp)
            if record.status != "pending":
                raise ApprovalStateError(
                    f"只有 pending 状态可以过期，当前状态为 {record.status}。"
                )
            record.status = "expired"
            record.updated_at = timestamp
            record.decided_at = timestamp
            record.decision_reason = "审批已过期"
            return record

    def _decide(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decided_by: str,
        decision_reason: str | None,
        now: float | None = None,
    ) -> ApprovalRecord:
        timestamp = _now() if now is None else now
        with self._lock:
            record = self.get(approval_id, now=timestamp)
            if record.status != "pending":
                raise ApprovalStateError(
                    f"只有 pending 状态可以审批，当前状态为 {record.status}。"
                )
            record.status = status
            record.updated_at = timestamp
            record.decided_at = timestamp
            record.decided_by = str(decided_by)
            record.decision_reason = (decision_reason or "").strip() or None
            return record

    @staticmethod
    def _expire_if_due(record: ApprovalRecord, now: float) -> None:
        if (
            record.status == "pending"
            and record.expires_at is not None
            and record.expires_at <= now
        ):
            record.status = "expired"
            record.updated_at = now
            record.decided_at = now
            record.decision_reason = "审批已过期"


approval_store = ApprovalStore()


def mark_sensitive_action(
    *,
    action: str,
    reason: str,
    user_id: str,
    conversation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    expires_in_seconds: int | None = None,
) -> ApprovalRecord:
    return approval_store.mark_sensitive_action(
        action=action,
        reason=reason,
        user_id=user_id,
        conversation_id=conversation_id,
        metadata=metadata,
        expires_in_seconds=expires_in_seconds,
    )


def approval_state_update(record: ApprovalRecord) -> dict[str, Any]:
    """Return TravelState fields for the latest sensitive action marker."""

    return {
        "approval_pending": record.status == "pending",
        "approval_reason": record.reason,
        "approval_action": record.action,
        "approval_expires_at": record.expires_at,
        "approval_status": record.status,
        "approval_record_id": record.approval_id,
        "approval_required": record.requires_approval,
        "approval_governance": {
            "label": record.label,
            "record_only": not record.requires_approval,
            "is_blocking": record.is_blocking,
            "boundary": record.governance_boundary,
            "unsupported_without_integration": list(
                record.unsupported_without_integration
            ),
        },
    }
