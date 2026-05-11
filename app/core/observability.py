"""Turn-level production observability helpers for Agent chat runs."""
from __future__ import annotations

import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.utils.security import is_sensitive_key, redact_sensitive_text


TURN_OBSERVABILITY_VERSION = "turn_observability.v1"
PUBLIC_TURN_OBSERVABILITY_VERSION = "turn_observability.public.v1"
PUBLIC_TOOL_AUDIT_VERSION = "tool_audit.public.v1"
OBSERVABILITY_CONTEXT_VERSION = "observability_context.v1"

TOOL_FAILURE_STATUSES = {"failed", "timeout", "degraded", "skipped"}

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def estimate_token_count(text: str) -> int:
    """Estimate token usage with a stable character-based approximation."""

    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4) + math.ceil(non_ascii_chars / 2))


def _is_sensitive_key(key: Any) -> bool:
    return is_sensitive_key(key)


def sanitize_observability_value(
    value: Any,
    *,
    max_text_length: int = 120,
    max_list_items: int = 5,
) -> Any:
    """Return a bounded, secret-safe value for logs and snapshots."""

    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else sanitize_observability_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = [
            sanitize_observability_value(item)
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            items.append(f"...(+{len(value) - max_list_items})")
        return items
    if isinstance(value, str):
        compact = redact_sensitive_text(" ".join(value.split()))
        return compact[:max_text_length] + ("..." if len(compact) > max_text_length else "")
    return value


def new_turn_id() -> str:
    return f"turn_{uuid.uuid4().hex}"


def _round_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def build_observability_context(
    *,
    turn_id: str | None,
    current_step: str | None,
    planning_mode: str | None,
    planning_mode_source: str | None = None,
    planning_mode_confirmed: bool | None = None,
    available_tool_count: int | None = None,
) -> dict[str, Any]:
    """Build a state-level context summary without user prompt content."""

    return {
        "version": OBSERVABILITY_CONTEXT_VERSION,
        "turn_id": turn_id,
        "current_step": current_step or "unknown",
        "planning_mode": planning_mode or "unknown",
        "planning_mode_source": planning_mode_source or "unknown",
        "planning_mode_confirmed": planning_mode_confirmed,
        "available_tool_count": available_tool_count,
        "updated_at": utc_now_iso(),
    }


def public_tool_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    """Expose only coarse tool status over SSE; keep arguments and outputs internal."""

    status = str(event.get("status") or "unknown")
    return {
        "type": "tool_audit",
        "version": PUBLIC_TOOL_AUDIT_VERSION,
        "tool": str(event.get("name") or "unknown_tool"),
        "status": status,
        "elapsed_seconds": _round_seconds(event.get("elapsed_seconds")),
        "retry_count": max(int(event.get("retry_count") or 0), 0),
        "evidence_type": str(event.get("evidence_type") or "unknown"),
        "error_type": (
            str(event.get("error_type"))
            if event.get("error_type") is not None and status in TOOL_FAILURE_STATUSES
            else None
        ),
        "degraded": status in TOOL_FAILURE_STATUSES,
    }


@dataclass
class TurnObservation:
    """Mutable collector for one user-message turn."""

    conversation_id: str
    user_id: str
    user_message: str
    turn_id: str = field(default_factory=new_turn_id)
    current_step: str = "unknown"
    planning_mode: str = "unknown"
    planning_mode_source: str = "unknown"
    started_at: float = field(default_factory=time.time)
    perf_counter_started_at: float = field(default_factory=time.perf_counter)
    finished_at: float | None = None
    first_token_seconds: float | None = None
    token_event_count: int = 0
    assistant_chars: int = 0
    estimated_output_token_count: int = 0
    tool_call_count: int = 0
    tool_failure_count: int = 0
    fallback_count: int = 0
    error_event_count: int = 0
    status: str = "running"
    error_type: str | None = None
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    degradation_reasons: list[str] = field(default_factory=list)

    @property
    def user_message_chars(self) -> int:
        return len(self.user_message or "")

    @property
    def estimated_input_tokens(self) -> int:
        return estimate_token_count(self.user_message or "")

    @property
    def estimated_output_tokens(self) -> int:
        return self.estimated_output_token_count

    @property
    def estimated_total_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens

    @property
    def total_elapsed_seconds(self) -> float:
        end = self.finished_at or time.time()
        return round(end - self.started_at, 3)

    @property
    def degradation_status(self) -> str:
        if self.status == "failed" or self.error_event_count > 0:
            return "failed"
        if self.status in {"busy", "cancelled"}:
            return "degraded"
        if self.tool_failure_count > 0 or self.fallback_count > 0 or self.degradation_reasons:
            return "degraded"
        return "ok"

    def update_context(
        self,
        *,
        current_step: str | None = None,
        planning_mode: str | None = None,
        planning_mode_source: str | None = None,
    ) -> None:
        if current_step:
            self.current_step = str(current_step)
        if planning_mode:
            self.planning_mode = str(planning_mode)
        if planning_mode_source:
            self.planning_mode_source = str(planning_mode_source)

    def record_token(self, token: str) -> None:
        if self.first_token_seconds is None:
            self.first_token_seconds = time.perf_counter() - self.perf_counter_started_at
        self.token_event_count += 1
        self.assistant_chars += len(token or "")
        self.estimated_output_token_count += estimate_token_count(token or "")

    def ensure_assistant_text_observed(self, content: str) -> None:
        """Account for non-token report output without storing the text itself."""

        if self.assistant_chars or not content:
            return
        self.assistant_chars = len(content)
        self.estimated_output_token_count = estimate_token_count(content)

    def record_tool_start(self, tool_name: str | None) -> None:
        self.tool_call_count += 1
        if not tool_name:
            self.mark_degraded("tool_start_missing_name")

    def record_tool_audit_event(self, event: dict[str, Any]) -> None:
        public_event = public_tool_audit_event(event)
        self.tool_events.append(public_event)
        if public_event["status"] in TOOL_FAILURE_STATUSES:
            self.tool_failure_count += 1
            self.fallback_count += 1
            self.mark_degraded(f"tool_{public_event['status']}:{public_event['tool']}")

    def mark_fallback(self, reason: str) -> None:
        self.fallback_count += 1
        self.mark_degraded(f"fallback:{reason}")

    def mark_degraded(self, reason: str) -> None:
        safe_reason = str(sanitize_observability_value(reason))
        if safe_reason not in self.degradation_reasons:
            self.degradation_reasons.append(safe_reason)

    def mark_error(self, error_type: str | None) -> None:
        self.error_event_count += 1
        self.error_type = str(error_type or "UnknownError")
        self.status = "failed"

    def finish(self, status: str = "completed", error_type: str | None = None) -> dict[str, Any]:
        if self.finished_at is None:
            self.finished_at = time.time()
        if self.status == "running":
            self.status = status
        if error_type:
            self.error_type = str(error_type)
        snapshot = self.to_internal_snapshot()
        record_turn_snapshot(snapshot)
        return snapshot

    def to_public_summary(self) -> dict[str, Any]:
        return {
            "version": PUBLIC_TURN_OBSERVABILITY_VERSION,
            "turn_id": self.turn_id,
            "status": self.status,
            "step": self.current_step,
            "planning_mode": self.planning_mode,
            "first_token_seconds": _round_seconds(self.first_token_seconds),
            "total_elapsed_seconds": self.total_elapsed_seconds,
            "tool_call_count": self.tool_call_count,
            "tool_failure_count": self.tool_failure_count,
            "fallback_count": self.fallback_count,
            "degradation_status": self.degradation_status,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "estimated_total_tokens": self.estimated_total_tokens,
        }

    def to_internal_snapshot(self) -> dict[str, Any]:
        return {
            "version": TURN_OBSERVABILITY_VERSION,
            "turn_id": self.turn_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "started_at": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(),
            "finished_at": (
                datetime.fromtimestamp(self.finished_at, timezone.utc).isoformat()
                if self.finished_at is not None
                else None
            ),
            "metadata": {
                "current_step": self.current_step,
                "planning_mode": self.planning_mode,
                "planning_mode_source": self.planning_mode_source,
                "user_message_chars": self.user_message_chars,
            },
            "metrics": self.to_public_summary(),
            "tool_events": list(self.tool_events),
            "degradation_reasons": list(self.degradation_reasons),
            "error_type": self.error_type,
        }

    def to_sse_event(self) -> dict[str, Any]:
        return {
            "type": "turn_observability",
            "observability": self.to_public_summary(),
        }


_RECENT_TURN_OBSERVATIONS: deque[dict[str, Any]] = deque(maxlen=500)
_RECENT_TURN_LOCK = Lock()


def record_turn_snapshot(snapshot: dict[str, Any]) -> None:
    with _RECENT_TURN_LOCK:
        _RECENT_TURN_OBSERVATIONS.append(dict(snapshot))


def get_turn_observability_snapshot(turn_id: str) -> dict[str, Any] | None:
    with _RECENT_TURN_LOCK:
        for snapshot in reversed(_RECENT_TURN_OBSERVATIONS):
            if snapshot.get("turn_id") == turn_id:
                return dict(snapshot)
    return None


def list_recent_turn_observations(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(int(limit or 0), 0)
    with _RECENT_TURN_LOCK:
        items = list(_RECENT_TURN_OBSERVATIONS)[-safe_limit:] if safe_limit else []
    return [dict(item) for item in items]


def reset_observability_store_for_tests() -> None:
    with _RECENT_TURN_LOCK:
        _RECENT_TURN_OBSERVATIONS.clear()
