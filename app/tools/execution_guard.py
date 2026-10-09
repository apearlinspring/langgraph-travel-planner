"""Unified execution guard for planner-facing tools."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from langchain.tools import ToolRuntime
from langgraph.types import Command

from app.core.approval import approval_state_update, mark_sensitive_action
from app.core.permissions import (
    ToolExecutionPolicy,
    decide_tool_execution_permission,
    get_tool_execution_policy,
)
from app.core.state import TravelState
from app.tools.audit import (
    ToolAuditContext,
    append_tool_audit_event,
    build_tool_audit_event,
    start_tool_audit,
    summarize_tool_input,
)
from app.tools.contracts import (
    ToolAuditEvent,
    ToolAuditStatus,
    ToolEvidenceType,
    ToolExecutionGuardResult,
    ToolResultValidation,
    ToolValidationResult,
)
from app.tools.result_validation import classify_exception
from app.utils.logger import app_logger


ToolArgsValidator = Callable[[dict[str, Any]], ToolValidationResult]
ToolResultValidator = Callable[[Any], ToolResultValidation]
GuardedAsyncCall = Callable[[dict[str, Any]], Awaitable[Any]]


SINGLE_CALL_PER_TURN_TOOLS = frozenset(
    {
        "query_destination_info",
        "query_hotel_options",
        "query_transport_options",
    }
)

ARG_FINGERPRINT_PER_TURN_TOOLS = frozenset(
    {
        "query_driving_route",
        "query_flight_options",
        "query_train_options",
        "search_accommodation_info",
        "search_agency_pricing_rules",
        "search_agency_product_templates",
        "search_agency_report_standards",
        "search_agency_risk_playbook",
        "search_agency_service_sop",
        "search_destination_guide",
        "search_food_recommendations",
        "search_travel_tips",
    }
)

_LOOP_GUARD_MEMORY_TTL_SECONDS = 30 * 60
_LOOP_GUARD_MAX_TURNS = 256
_LOOP_GUARD_MEMORY: dict[str, dict[str, float]] = {}


@dataclass
class ToolExecutionAttempt:
    name: str
    args: dict[str, Any]
    runtime: Optional[ToolRuntime]
    context: ToolAuditContext
    input_summary: dict[str, Any]
    policy: ToolExecutionPolicy
    evidence_type: ToolEvidenceType
    state: dict[str, Any] = field(default_factory=dict)
    approval_update: dict[str, Any] = field(default_factory=dict)
    blocked_event: ToolAuditEvent | None = None
    blocked_message: str = ""
    loop_guard_key: str | None = None

    @property
    def ok(self) -> bool:
        return self.blocked_event is None


def _runtime_state(runtime: Optional[ToolRuntime]) -> dict[str, Any]:
    return dict(runtime.state) if runtime and runtime.state else {}


def _stable_payload(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _tool_loop_guard_key(name: str, args: dict[str, Any]) -> str | None:
    if name in SINGLE_CALL_PER_TURN_TOOLS:
        return f"{name}:single"
    if name in ARG_FINGERPRINT_PER_TURN_TOOLS:
        return f"{name}:{_stable_payload(args)}"
    return None


def _current_turn_id(state: dict[str, Any]) -> str:
    turn_id = state.get("turn_id")
    return str(turn_id).strip() if turn_id else ""


def _state_loop_guard_keys(state: dict[str, Any], turn_id: str) -> set[str]:
    guard = state.get("tool_loop_guard")
    if not isinstance(guard, dict) or str(guard.get("turn_id") or "") != turn_id:
        return set()
    calls = guard.get("calls") or []
    return {
        str(item.get("key"))
        for item in calls
        if isinstance(item, dict) and item.get("key")
    }


def _prune_loop_guard_memory(now: float) -> None:
    stale_turns = [
        turn_id
        for turn_id, keys in _LOOP_GUARD_MEMORY.items()
        if not keys or max(keys.values()) + _LOOP_GUARD_MEMORY_TTL_SECONDS < now
    ]
    for turn_id in stale_turns:
        _LOOP_GUARD_MEMORY.pop(turn_id, None)
    if len(_LOOP_GUARD_MEMORY) <= _LOOP_GUARD_MAX_TURNS:
        return
    oldest_turns = sorted(
        _LOOP_GUARD_MEMORY,
        key=lambda turn_id: max(_LOOP_GUARD_MEMORY[turn_id].values() or [0.0]),
    )
    for turn_id in oldest_turns[: len(_LOOP_GUARD_MEMORY) - _LOOP_GUARD_MAX_TURNS]:
        _LOOP_GUARD_MEMORY.pop(turn_id, None)


def _memory_loop_guard_seen(turn_id: str, key: str) -> bool:
    now = time.time()
    _prune_loop_guard_memory(now)
    keys = _LOOP_GUARD_MEMORY.setdefault(turn_id, {})
    if key in keys:
        keys[key] = now
        return True
    keys[key] = now
    return False


def _duplicate_tool_loop_message(name: str) -> str:
    if name == "query_hotel_options":
        return (
            "本轮已经执行过酒店真实查询，为避免循环和长时间占用会话锁，"
            "不会再次查询。请基于已有酒店结果总结；如果结果为空，请说明可在下一轮放宽预算、区域或偏好后重试。"
        )
    if name == "query_transport_options":
        return (
            "本轮已经执行过交通真实查询，为避免重复调用和长回合超时，"
            "不会再次查询。请基于已有交通结果比较推荐；需要刷新时请在下一轮重新发起。"
        )
    if name == "query_destination_info":
        return (
            "本轮已经执行过目的地信息查询，不会再次调用等价查询；"
            "请基于已有攻略、天气或搜索结果继续总结。"
        )
    if name.startswith("search_"):
        return (
            "本轮已经执行过等价 RAG 检索，不会重复读取同一批知识；"
            "请基于已有证据继续回答，并把动态价格、库存、开放时间标注为待二次核实。"
        )
    return "本轮已经执行过等价工具调用，已跳过重复执行以避免循环。"


def _mark_event_loop_guard(
    event: ToolAuditEvent,
    *,
    attempt: ToolExecutionAttempt,
) -> ToolAuditEvent:
    turn_id = _current_turn_id(attempt.state)
    if turn_id:
        event["turn_id"] = turn_id
    if attempt.loop_guard_key:
        event["loop_guard_key"] = attempt.loop_guard_key
    return event


def _updated_loop_guard_state(
    state: dict[str, Any],
    event: ToolAuditEvent,
) -> dict[str, Any]:
    turn_id = str(event.get("turn_id") or "")
    key = str(event.get("loop_guard_key") or "")
    if not turn_id or not key:
        return state.get("tool_loop_guard") or {}

    existing = state.get("tool_loop_guard")
    calls: list[dict[str, Any]] = []
    if isinstance(existing, dict) and str(existing.get("turn_id") or "") == turn_id:
        calls = [item for item in existing.get("calls") or [] if isinstance(item, dict)]

    if not any(str(item.get("key") or "") == key for item in calls):
        calls.append(
            {
                "key": key,
                "tool": event.get("name"),
                "status": event.get("status"),
                "recorded_at": event.get("started_at"),
            }
        )
    return {"turn_id": turn_id, "calls": calls[-40:]}


def _policy_evidence_type(policy: ToolExecutionPolicy) -> ToolEvidenceType:
    if policy.category == "live_hotel_search":
        return "live_hotel_search"
    if policy.category == "live_transport_query":
        return "live_transport_query"
    if policy.category == "internal_rag":
        return "internal_rag_evidence"
    if policy.category == "public_rag":
        return "public_rag_evidence"
    if policy.category == "mcp_external_query":
        return "mcp_live_query"
    if policy.category == "destination_router_query":
        return "destination_router_evidence"
    if policy.category in {
        "record_only_sensitive_action",
        "future_sensitive_action",
    }:
        return "internal_state_update"
    return "unknown"


def _approved_by_state(state: dict[str, Any], policy: ToolExecutionPolicy) -> bool:
    return (
        policy.approval_action is not None
        and state.get("approval_action") == policy.approval_action
        and state.get("approval_status") == "approved"
    )


def _approval_block(
    *,
    name: str,
    args: dict[str, Any],
    state: dict[str, Any],
    policy: ToolExecutionPolicy,
) -> tuple[str, dict[str, Any], str]:
    existing_status = state.get("approval_status")
    if (
        policy.approval_action is not None
        and state.get("approval_action") == policy.approval_action
        and existing_status in {"rejected", "expired", "pending"}
    ):
        return (
            f"{policy.description} 当前审批状态为 {existing_status}，本轮不会继续执行真实外部动作。",
            {},
            f"approval_{existing_status}",
        )

    record = mark_sensitive_action(
        action=str(policy.approval_action),
        reason=policy.description,
        user_id=str(state.get("user_id") or "anonymous"),
        conversation_id=(
            str(state.get("session_id")) if state.get("session_id") else None
        ),
        metadata={"tool_name": name, **args},
    )
    update = approval_state_update(record)
    return (
        f"{policy.description} 需要先完成人工审批；审批通过前，本轮不会执行真实外部动作。",
        update,
        "approval_required",
    )


def _blocked_attempt(
    attempt: ToolExecutionAttempt,
    *,
    message: str,
    error_type: str | None,
    status: ToolAuditStatus = "skipped",
    output_summary: dict[str, Any] | None = None,
    approval_update: dict[str, Any] | None = None,
) -> ToolExecutionAttempt:
    attempt.blocked_message = message
    attempt.approval_update = approval_update or {}
    attempt.blocked_event = build_tool_audit_event(
        attempt.context,
        status=status,
        input_summary=attempt.input_summary,
        output_summary=output_summary or {"message": message},
        error_type=error_type,
        evidence_type=attempt.evidence_type,
    )
    _mark_event_loop_guard(attempt.blocked_event, attempt=attempt)
    return attempt


def begin_tool_execution(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    runtime: Optional[ToolRuntime[None, TravelState]] = None,
    input_validator: ToolArgsValidator | None = None,
    evidence_type: ToolEvidenceType | None = None,
) -> ToolExecutionAttempt:
    """Run pre-call permission, approval and argument checks for one tool call."""

    normalized_args = dict(args or {})
    policy = get_tool_execution_policy(name)
    context = start_tool_audit(name)
    input_summary = summarize_tool_input(normalized_args)
    attempt = ToolExecutionAttempt(
        name=name,
        args=normalized_args,
        runtime=runtime,
        context=context,
        input_summary=input_summary,
        policy=policy,
        evidence_type=evidence_type or _policy_evidence_type(policy),
        state=_runtime_state(runtime),
    )

    permission = decide_tool_execution_permission(name, attempt.state)
    if not permission.allowed:
        return _blocked_attempt(
            attempt,
            message=permission.reason or f"工具 {name} 当前无执行权限。",
            error_type=permission.error_type or "tool_permission_denied",
        )

    if policy.requires_approval and not _approved_by_state(attempt.state, policy):
        message, approval_update, error_type = _approval_block(
            name=name,
            args=normalized_args,
            state=attempt.state,
            policy=policy,
        )
        return _blocked_attempt(
            attempt,
            message=message,
            error_type=error_type,
            status="approval_required",
            approval_update=approval_update,
        )

    if input_validator is not None:
        validation = input_validator(normalized_args)
        if not validation.ok:
            return _blocked_attempt(
                attempt,
                message=validation.message,
                error_type=validation.error_type,
                output_summary={"message": validation.message},
            )
        attempt.args = validation.normalized_args or normalized_args
        attempt.input_summary = summarize_tool_input(attempt.args)

    loop_guard_key = _tool_loop_guard_key(name, attempt.args)
    turn_id = _current_turn_id(attempt.state)
    if loop_guard_key and turn_id:
        attempt.loop_guard_key = loop_guard_key
        already_seen = (
            loop_guard_key in _state_loop_guard_keys(attempt.state, turn_id)
            or _memory_loop_guard_seen(turn_id, loop_guard_key)
        )
        if already_seen:
            message = _duplicate_tool_loop_message(name)
            return _blocked_attempt(
                attempt,
                message=message,
                error_type="duplicate_tool_call_same_turn",
                output_summary={"message": message, "loop_guard_key": loop_guard_key},
            )

    return attempt


def build_guard_event(
    attempt: ToolExecutionAttempt,
    *,
    status: ToolAuditStatus,
    output_summary: dict[str, Any] | None = None,
    error_type: str | None = None,
    retry_count: int = 0,
) -> ToolAuditEvent:
    event = build_tool_audit_event(
        attempt.context,
        status=status,
        input_summary=attempt.input_summary,
        output_summary=output_summary,
        error_type=error_type,
        retry_count=retry_count,
        evidence_type=attempt.evidence_type,
    )
    return _mark_event_loop_guard(event, attempt=attempt)


def finalize_tool_execution(
    attempt: ToolExecutionAttempt,
    validation: ToolResultValidation,
    *,
    retry_count: int = 0,
    output_summary: dict[str, Any] | None = None,
) -> ToolAuditEvent:
    return build_guard_event(
        attempt,
        status=validation.status,
        output_summary=output_summary or validation.output_summary,
        error_type=validation.error_type,
        retry_count=retry_count,
    )


def fail_tool_execution(
    attempt: ToolExecutionAttempt,
    exc: BaseException,
    *,
    output_summary: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> ToolAuditEvent:
    status, error_type = classify_exception(exc)
    message = str(exc).strip() or exc.__class__.__name__
    return build_guard_event(
        attempt,
        status=status,
        output_summary=output_summary or {"message": message},
        error_type=error_type,
        retry_count=retry_count,
    )


def audited_command(
    update: dict[str, Any],
    runtime: Optional[ToolRuntime],
    event: ToolAuditEvent,
    *,
    approval_update: dict[str, Any] | None = None,
) -> Command:
    state = _runtime_state(runtime)
    merged_update = {**(approval_update or {}), **update}
    if event.get("loop_guard_key") and event.get("turn_id"):
        merged_update["tool_loop_guard"] = _updated_loop_guard_state(state, event)
    return Command(update=append_tool_audit_event(state, merged_update, event))


async def execute_guarded_call(
    name: str,
    args: dict[str, Any] | None,
    call: GuardedAsyncCall,
    *,
    runtime: Optional[ToolRuntime[None, TravelState]] = None,
    input_validator: ToolArgsValidator | None = None,
    result_validator: ToolResultValidator | None = None,
    evidence_type: ToolEvidenceType | None = None,
    timeout_seconds: float | None = None,
    retry_count: int = 0,
) -> ToolExecutionGuardResult:
    """Execute a tool coroutine with guardrails, timeout, result validation and audit."""

    attempt = begin_tool_execution(
        name,
        args,
        runtime=runtime,
        input_validator=input_validator,
        evidence_type=evidence_type,
    )
    if not attempt.ok and attempt.blocked_event is not None:
        return ToolExecutionGuardResult(
            status=attempt.blocked_event["status"],
            event=attempt.blocked_event,
            output=None,
            message=attempt.blocked_message,
            error_type=attempt.blocked_event.get("error_type"),
            approval_update=attempt.approval_update,
        )

    timeout = timeout_seconds
    if timeout is None:
        timeout = attempt.policy.default_timeout_seconds

    try:
        if timeout is None:
            output = await call(attempt.args)
        else:
            output = await asyncio.wait_for(call(attempt.args), timeout=timeout)
    except Exception as exc:
        event = fail_tool_execution(attempt, exc, retry_count=retry_count)
        app_logger.warning(
            "Tool execution guarded failure: "
            f"name={name}, status={event['status']}, error={event.get('error_type')}"
        )
        return ToolExecutionGuardResult(
            status=event["status"],
            event=event,
            output=None,
            message=str(exc).strip() or exc.__class__.__name__,
            error_type=event.get("error_type"),
        )

    validation = (
        result_validator(output)
        if result_validator is not None
        else ToolResultValidation(status="success")
    )
    event = finalize_tool_execution(
        attempt,
        validation,
        retry_count=retry_count,
    )
    return ToolExecutionGuardResult(
        status=event["status"],
        event=event,
        output=output,
        message=validation.message,
        error_type=event.get("error_type"),
    )
