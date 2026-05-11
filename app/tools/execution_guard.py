"""Unified execution guard for planner-facing tools."""
from __future__ import annotations

import asyncio
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

    @property
    def ok(self) -> bool:
        return self.blocked_event is None


def _runtime_state(runtime: Optional[ToolRuntime]) -> dict[str, Any]:
    return dict(runtime.state) if runtime and runtime.state else {}


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

    return attempt


def build_guard_event(
    attempt: ToolExecutionAttempt,
    *,
    status: ToolAuditStatus,
    output_summary: dict[str, Any] | None = None,
    error_type: str | None = None,
    retry_count: int = 0,
) -> ToolAuditEvent:
    return build_tool_audit_event(
        attempt.context,
        status=status,
        input_summary=attempt.input_summary,
        output_summary=output_summary,
        error_type=error_type,
        retry_count=retry_count,
        evidence_type=attempt.evidence_type,
    )


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
