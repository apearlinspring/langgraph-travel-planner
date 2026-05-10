"""Lightweight approval records for sensitive action governance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import RLock
from time import time
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    ApprovalStatus,
    get_sensitive_action_policy,
    sanitize_approval_metadata,
)
from app.models.approval import ApprovalEvent, ApprovalRequest


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


@dataclass
class ApprovalEventRecord:
    """Append-only event for one approval status transition."""

    approval_id: str
    action: str
    event_type: str
    from_status: ApprovalStatus | None
    to_status: ApprovalStatus
    actor_id: str | None
    reason: str | None
    metadata: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> float:
    return time()


def _approval_id() -> str:
    return f"APR-{uuid4().hex[:12].upper()}"


def _next_status_for_policy(requires_approval: bool) -> ApprovalStatus:
    return "pending" if requires_approval else "none"


def _datetime_from_timestamp(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


def _timestamp_from_datetime(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


class ApprovalStore:
    """In-memory approval store for the current application process."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, ApprovalRecord] = {}
        self._events: list[ApprovalEventRecord] = []

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._events.clear()

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
            approval_id=_approval_id(),
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
            self._append_event(
                record,
                event_type="created",
                from_status=None,
                to_status=record.status,
                actor_id=record.user_id,
                reason=record.reason,
                metadata={"requires_approval": record.requires_approval},
                now=timestamp,
            )
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

    def list_events(self, approval_id: str) -> list[ApprovalEventRecord]:
        with self._lock:
            if approval_id not in self._records:
                raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
            return [
                event
                for event in self._events
                if event.approval_id == approval_id
            ]

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
            from_status = record.status
            record.status = "expired"
            record.updated_at = timestamp
            record.decided_at = timestamp
            record.decision_reason = "审批已过期"
            self._append_event(
                record,
                event_type="expired",
                from_status=from_status,
                to_status="expired",
                actor_id=None,
                reason=record.decision_reason,
                metadata={},
                now=timestamp,
            )
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
            from_status = record.status
            record.status = status
            record.updated_at = timestamp
            record.decided_at = timestamp
            record.decided_by = str(decided_by)
            record.decision_reason = (decision_reason or "").strip() or None
            self._append_event(
                record,
                event_type=status,
                from_status=from_status,
                to_status=status,
                actor_id=record.decided_by,
                reason=record.decision_reason,
                metadata={},
                now=timestamp,
            )
            return record

    def _expire_if_due(self, record: ApprovalRecord, now: float) -> None:
        if (
            record.status == "pending"
            and record.expires_at is not None
            and record.expires_at <= now
        ):
            from_status = record.status
            record.status = "expired"
            record.updated_at = now
            record.decided_at = now
            record.decision_reason = "审批已过期"
            self._append_event(
                record,
                event_type="expired",
                from_status=from_status,
                to_status="expired",
                actor_id=None,
                reason=record.decision_reason,
                metadata={"auto_expired": True},
                now=now,
            )

    def _append_event(
        self,
        record: ApprovalRecord,
        *,
        event_type: str,
        from_status: ApprovalStatus | None,
        to_status: ApprovalStatus,
        actor_id: str | None,
        reason: str | None,
        metadata: dict[str, Any],
        now: float,
    ) -> None:
        self._events.append(
            ApprovalEventRecord(
                approval_id=record.approval_id,
                action=record.action,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_id=actor_id,
                reason=reason,
                metadata=sanitize_approval_metadata(metadata),
                created_at=now,
            )
        )


class DatabaseApprovalStore:
    """PostgreSQL-backed approval store with append-only events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mark_sensitive_action(
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
        created_at = _datetime_from_timestamp(timestamp)
        ttl_seconds = (
            expires_in_seconds
            if expires_in_seconds is not None
            else policy.default_ttl_seconds
        )
        expires_at = (
            _datetime_from_timestamp(timestamp + ttl_seconds)
            if policy.requires_approval and ttl_seconds is not None
            else None
        )
        status = _next_status_for_policy(policy.requires_approval)
        approval = ApprovalRequest(
            approval_id=_approval_id(),
            action=policy.action,
            label=policy.label,
            status=status,
            reason=reason.strip() or policy.description,
            user_id=str(user_id),
            conversation_id=str(conversation_id) if conversation_id else None,
            requires_approval=policy.requires_approval,
            is_blocking=policy.is_blocking,
            governance_boundary=policy.governance_boundary,
            unsupported_without_integration=list(
                policy.unsupported_without_integration
            ),
            request_metadata=sanitize_approval_metadata(metadata),
            expires_at=expires_at,
            created_at=created_at,
            updated_at=created_at,
        )
        self._session.add(approval)
        self._append_event_model(
            approval,
            event_type="created",
            from_status=None,
            to_status=status,
            actor_id=str(user_id),
            reason=approval.reason,
            metadata={"requires_approval": approval.requires_approval},
            created_at=created_at,
        )
        await self._session.commit()
        await self._session.refresh(approval)
        return self._record_from_model(approval)

    async def get(self, approval_id: str, *, now: float | None = None) -> ApprovalRecord:
        approval = await self._get_model(approval_id)
        changed = self._expire_if_due_model(approval, _now() if now is None else now)
        if changed:
            await self._session.commit()
            await self._session.refresh(approval)
        return self._record_from_model(approval)

    async def list_records(
        self,
        *,
        user_id: str | None = None,
        status: str | None = None,
        action: str | None = None,
        conversation_id: str | None = None,
        now: float | None = None,
    ) -> list[ApprovalRecord]:
        await self._expire_due_records(_now() if now is None else now)
        stmt = select(ApprovalRequest).order_by(desc(ApprovalRequest.created_at))
        if user_id is not None:
            stmt = stmt.where(ApprovalRequest.user_id == str(user_id))
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        if action:
            canonical_action = get_sensitive_action_policy(action).action
            stmt = stmt.where(ApprovalRequest.action == canonical_action)
        if conversation_id is not None:
            stmt = stmt.where(ApprovalRequest.conversation_id == str(conversation_id))
        result = await self._session.execute(stmt)
        return [self._record_from_model(model) for model in result.scalars().all()]

    async def list_events(self, approval_id: str) -> list[ApprovalEventRecord]:
        await self._get_model(approval_id)
        result = await self._session.execute(
            select(ApprovalEvent)
            .where(ApprovalEvent.approval_id == approval_id)
            .order_by(ApprovalEvent.created_at)
        )
        return [
            self._event_from_model(model)
            for model in result.scalars().all()
        ]

    async def approve(
        self,
        approval_id: str,
        *,
        decided_by: str,
        decision_reason: str | None = None,
        now: float | None = None,
    ) -> ApprovalRecord:
        return await self._decide(
            approval_id,
            status="approved",
            decided_by=decided_by,
            decision_reason=decision_reason,
            now=now,
        )

    async def reject(
        self,
        approval_id: str,
        *,
        decided_by: str,
        decision_reason: str | None = None,
        now: float | None = None,
    ) -> ApprovalRecord:
        return await self._decide(
            approval_id,
            status="rejected",
            decided_by=decided_by,
            decision_reason=decision_reason,
            now=now,
        )

    async def expire(
        self,
        approval_id: str,
        *,
        now: float | None = None,
    ) -> ApprovalRecord:
        timestamp = _now() if now is None else now
        approval = await self._get_model(approval_id)
        if approval.status != "pending":
            raise ApprovalStateError(
                f"只有 pending 状态可以过期，当前状态为 {approval.status}。"
            )
        self._transition_model(
            approval,
            status="expired",
            actor_id=None,
            decision_reason="审批已过期",
            event_type="expired",
            timestamp=timestamp,
        )
        await self._session.commit()
        await self._session.refresh(approval)
        return self._record_from_model(approval)

    async def _decide(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decided_by: str,
        decision_reason: str | None,
        now: float | None = None,
    ) -> ApprovalRecord:
        timestamp = _now() if now is None else now
        approval = await self._get_model(approval_id)
        if self._expire_if_due_model(approval, timestamp):
            await self._session.commit()
            await self._session.refresh(approval)
        if approval.status != "pending":
            raise ApprovalStateError(
                f"只有 pending 状态可以审批，当前状态为 {approval.status}。"
            )
        self._transition_model(
            approval,
            status=status,
            actor_id=str(decided_by),
            decision_reason=(decision_reason or "").strip() or None,
            event_type=status,
            timestamp=timestamp,
        )
        await self._session.commit()
        await self._session.refresh(approval)
        return self._record_from_model(approval)

    async def _get_model(self, approval_id: str) -> ApprovalRequest:
        result = await self._session.execute(
            select(ApprovalRequest).where(ApprovalRequest.approval_id == approval_id)
        )
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalNotFound(f"审批记录不存在：{approval_id}")
        return approval

    async def _expire_due_records(self, now: float) -> None:
        now_dt = _datetime_from_timestamp(now)
        result = await self._session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending")
            .where(ApprovalRequest.expires_at.is_not(None))
            .where(ApprovalRequest.expires_at <= now_dt)
        )
        changed = False
        for approval in result.scalars().all():
            changed = self._expire_if_due_model(approval, now) or changed
        if changed:
            await self._session.commit()

    def _expire_if_due_model(self, approval: ApprovalRequest, now: float) -> bool:
        expires_at = _timestamp_from_datetime(approval.expires_at)
        if approval.status == "pending" and expires_at is not None and expires_at <= now:
            self._transition_model(
                approval,
                status="expired",
                actor_id=None,
                decision_reason="审批已过期",
                event_type="expired",
                timestamp=now,
                metadata={"auto_expired": True},
            )
            return True
        return False

    def _transition_model(
        self,
        approval: ApprovalRequest,
        *,
        status: ApprovalStatus,
        actor_id: str | None,
        decision_reason: str | None,
        event_type: str,
        timestamp: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        from_status = approval.status
        approval.status = status
        approval.updated_at = _datetime_from_timestamp(timestamp)
        approval.decided_at = _datetime_from_timestamp(timestamp)
        approval.decided_by = actor_id
        approval.decision_reason = decision_reason
        self._append_event_model(
            approval,
            event_type=event_type,
            from_status=from_status,
            to_status=status,
            actor_id=actor_id,
            reason=decision_reason,
            metadata=metadata or {},
            created_at=_datetime_from_timestamp(timestamp),
        )

    def _append_event_model(
        self,
        approval: ApprovalRequest,
        *,
        event_type: str,
        from_status: ApprovalStatus | None,
        to_status: ApprovalStatus,
        actor_id: str | None,
        reason: str | None,
        metadata: dict[str, Any],
        created_at: datetime | None,
    ) -> None:
        self._session.add(
            ApprovalEvent(
                approval_id=approval.approval_id,
                action=approval.action,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                actor_id=actor_id,
                reason=reason,
                event_metadata=sanitize_approval_metadata(metadata),
                created_at=created_at,
            )
        )

    @staticmethod
    def _record_from_model(approval: ApprovalRequest) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=approval.approval_id,
            action=approval.action,
            label=approval.label,
            status=approval.status,  # type: ignore[arg-type]
            reason=approval.reason,
            user_id=approval.user_id,
            conversation_id=approval.conversation_id,
            created_at=_timestamp_from_datetime(approval.created_at) or 0.0,
            updated_at=_timestamp_from_datetime(approval.updated_at) or 0.0,
            expires_at=_timestamp_from_datetime(approval.expires_at),
            requires_approval=approval.requires_approval,
            is_blocking=approval.is_blocking,
            governance_boundary=approval.governance_boundary,
            unsupported_without_integration=list(
                approval.unsupported_without_integration or []
            ),
            metadata=dict(approval.request_metadata or {}),
            decided_by=approval.decided_by,
            decision_reason=approval.decision_reason,
            decided_at=_timestamp_from_datetime(approval.decided_at),
        )

    @staticmethod
    def _event_from_model(event: ApprovalEvent) -> ApprovalEventRecord:
        return ApprovalEventRecord(
            approval_id=event.approval_id,
            action=event.action,
            event_type=event.event_type,
            from_status=event.from_status,  # type: ignore[arg-type]
            to_status=event.to_status,  # type: ignore[arg-type]
            actor_id=event.actor_id,
            reason=event.reason,
            metadata=dict(event.event_metadata or {}),
            created_at=_timestamp_from_datetime(event.created_at) or 0.0,
        )


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
