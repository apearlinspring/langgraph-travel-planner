"""Shared contracts for tool governance and audit events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from typing_extensions import TypedDict


ToolAuditStatus = Literal["success", "failed", "timeout", "degraded", "skipped"]
ToolEvidenceType = Literal[
    "live_transport_query",
    "live_hotel_search",
    "mcp_live_query",
    "internal_rag_evidence",
    "public_rag_evidence",
    "internal_state_update",
    "unknown",
]
ToolRiskLevel = Literal["low", "medium", "high", "critical"]


class ToolAuditEvent(TypedDict):
    name: str
    started_at: float
    elapsed_seconds: float
    status: ToolAuditStatus
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_type: str | None
    retry_count: int
    evidence_type: ToolEvidenceType


@dataclass(frozen=True)
class ToolValidationResult:
    ok: bool
    error_type: str | None = None
    message: str = ""
    normalized_args: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResultValidation:
    status: ToolAuditStatus
    output_summary: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    message: str = ""


@dataclass(frozen=True)
class ToolPermissionDecision:
    allowed: bool
    reason: str = ""
    error_type: str | None = None


@dataclass(frozen=True)
class ToolExecutionGuardResult:
    status: ToolAuditStatus
    event: ToolAuditEvent
    output: Any = None
    message: str = ""
    error_type: str | None = None
    update: dict[str, Any] = field(default_factory=dict)
    approval_update: dict[str, Any] = field(default_factory=dict)
