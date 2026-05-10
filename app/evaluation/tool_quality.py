"""Deterministic quality checks for live tool-call behavior."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from app.evaluation.report_quality import CriterionResult


FAILURE_STATUSES = {"failed", "failure", "timeout", "degraded", "error"}


@dataclass(frozen=True)
class ToolCallRecord:
    """Normalized tool-call event captured from a live snapshot."""

    tool: str
    turn_index: int | None = None
    status: str | None = None
    elapsed_since_scenario_start: float | None = None
    raw_event_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolQualityResult:
    """Full deterministic evaluation result for tool-call quality."""

    total_score: float
    max_score: float
    normalized_score: float
    grade: str
    passed: bool
    criteria: list[CriterionResult]
    summary: list[str]
    tool_counts: dict[str, int] = field(default_factory=dict)
    redundant_calls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "grade": self.grade,
            "passed": self.passed,
            "summary": self.summary,
            "tool_counts": self.tool_counts,
            "redundant_calls": self.redundant_calls,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
        }


def _grade(normalized_score: float) -> str:
    if normalized_score >= 90:
        return "A"
    if normalized_score >= 80:
        return "B"
    if normalized_score >= 70:
        return "C"
    if normalized_score >= 60:
        return "D"
    return "F"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _score(condition: bool, points: float, findings: list[str], message: str) -> float:
    if condition:
        return points
    findings.append(message)
    return 0.0


def _tool_name_from_event(event: dict[str, Any]) -> str:
    for key in ("tool", "name", "tool_name"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _turn_index_from_event(event: dict[str, Any]) -> int | None:
    value = event.get("turn_index")
    return value if isinstance(value, int) else None


def _elapsed_from_event(event: dict[str, Any]) -> float | None:
    value = event.get("elapsed_since_scenario_start")
    return float(value) if isinstance(value, (int, float)) else None


def extract_tool_events(events: list[dict[str, Any]]) -> list[ToolCallRecord]:
    """Normalize tool-call events from saved SSE snapshots."""

    records: list[ToolCallRecord] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = event.get("type") or event.get("event")
        is_tool_event = event_type in {"tool_call", "on_tool_start", "on_tool_end"} or bool(event.get("tool_name"))
        if not is_tool_event:
            continue
        tool_name = _tool_name_from_event(event)
        if not tool_name:
            continue
        status = event.get("status")
        records.append(
            ToolCallRecord(
                tool=tool_name,
                turn_index=_turn_index_from_event(event),
                status=str(status).lower() if isinstance(status, str) and status else None,
                elapsed_since_scenario_start=_elapsed_from_event(event),
                raw_event_type=str(event_type) if event_type else None,
            )
        )
    return records


def tool_call_counts(records: list[ToolCallRecord]) -> dict[str, int]:
    """Return tool-call counts by tool name."""

    return dict(Counter(record.tool for record in records))


def redundant_tool_calls(
    records: list[ToolCallRecord],
    *,
    max_duplicate_calls: int = 1,
) -> list[str]:
    """Return tool/turn pairs that exceed the allowed duplicate-call count."""

    grouped: dict[tuple[int | None, str], int] = defaultdict(int)
    for record in records:
        grouped[(record.turn_index, record.tool)] += 1

    redundant = []
    for (turn_index, tool), count in sorted(grouped.items(), key=lambda item: (item[0][0] or 0, item[0][1])):
        if count > max_duplicate_calls:
            turn_label = "unknown-turn" if turn_index is None else f"turn-{turn_index}"
            redundant.append(f"{turn_label}:{tool} called {count} times")
    return redundant


def _pending_checks(report_data: dict[str, Any] | None) -> list[Any]:
    if not isinstance(report_data, dict):
        return []
    tool_audit = _as_dict(report_data.get("tool_audit_summary"))
    budget_confidence = _as_dict(report_data.get("budget_confidence"))
    pending = _as_list(tool_audit.get("pending_checks"))
    verification = _as_list(budget_confidence.get("verification_items"))
    return [*pending, *verification]


def _unsupported_actions(report_data: dict[str, Any] | None) -> list[Any]:
    if not isinstance(report_data, dict):
        return []
    return _as_list(_as_dict(report_data.get("tool_audit_summary")).get("unsupported_actions"))


def _used_sources(report_data: dict[str, Any] | None) -> list[Any]:
    if not isinstance(report_data, dict):
        return []
    return _as_list(_as_dict(report_data.get("tool_audit_summary")).get("used_sources"))


def _has_failure_signal(events: list[dict[str, Any]], records: list[ToolCallRecord]) -> bool:
    if any((record.status or "") in FAILURE_STATUSES for record in records):
        return True
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or event.get("event") or "").lower()
        status = str(event.get("status") or "").lower()
        if event_type == "error" or status in FAILURE_STATUSES:
            return True
    return False


def _criterion_intent_coverage(
    records: list[ToolCallRecord],
    expected_tools: set[str],
) -> CriterionResult:
    findings: list[str] = []
    called_tools = {record.tool for record in records}
    if not expected_tools:
        score = 30
    else:
        missing = sorted(expected_tools - called_tools)
        score = _score(not missing, 30, findings, f"Missing expected tool calls: {', '.join(missing)}")
    return CriterionResult("tool_intent_coverage", score, 30, findings)


def _criterion_forbidden_tools(
    records: list[ToolCallRecord],
    forbidden_tools: set[str],
) -> CriterionResult:
    findings: list[str] = []
    called_forbidden = sorted({record.tool for record in records} & forbidden_tools)
    score = _score(
        not called_forbidden,
        20,
        findings,
        f"Unexpected forbidden tool calls: {', '.join(called_forbidden)}",
    )
    return CriterionResult("tool_forbidden_avoidance", score, 20, findings)


def _criterion_redundancy(
    records: list[ToolCallRecord],
    max_duplicate_calls: int,
) -> CriterionResult:
    findings: list[str] = []
    redundant = redundant_tool_calls(records, max_duplicate_calls=max_duplicate_calls)
    score = _score(
        not redundant,
        20,
        findings,
        "Redundant tool calls detected: " + "; ".join(redundant[:5]),
    )
    return CriterionResult("tool_redundancy", score, 20, findings)


def _criterion_failure_fallback(
    events: list[dict[str, Any]],
    records: list[ToolCallRecord],
    report_data: dict[str, Any] | None,
    requires_fallback: bool,
) -> CriterionResult:
    findings: list[str] = []
    needs_fallback = requires_fallback or _has_failure_signal(events, records)
    score = _score(
        not needs_fallback or bool(_pending_checks(report_data)),
        20,
        findings,
        "Tool failure or fallback scenario should produce pending verification checks",
    )
    return CriterionResult("tool_failure_fallback", score, 20, findings)


def _criterion_audit_surface(report_data: dict[str, Any] | None) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(
        bool(_pending_checks(report_data)),
        4,
        findings,
        "tool_audit_summary or budget_confidence should expose pending checks",
    )
    score += _score(
        bool(_used_sources(report_data)),
        3,
        findings,
        "tool_audit_summary.used_sources should describe data sources",
    )
    score += _score(
        bool(_unsupported_actions(report_data)),
        3,
        findings,
        "tool_audit_summary.unsupported_actions should state unsupported actions",
    )
    return CriterionResult("tool_audit_surface", score, 10, findings)


def evaluate_tool_quality(
    events: list[dict[str, Any]],
    *,
    report_data: dict[str, Any] | None = None,
    expected_tools: set[str] | None = None,
    forbidden_tools: set[str] | None = None,
    max_duplicate_calls: int = 1,
    requires_fallback: bool = False,
    pass_threshold: float = 80.0,
) -> ToolQualityResult:
    """Evaluate tool-call intent matching, redundancy, and fallback quality."""

    if not isinstance(events, list):
        raise TypeError("events must be a list")
    expected_tools = expected_tools or set()
    forbidden_tools = forbidden_tools or set()
    records = extract_tool_events(events)
    criteria = [
        _criterion_intent_coverage(records, expected_tools),
        _criterion_forbidden_tools(records, forbidden_tools),
        _criterion_redundancy(records, max_duplicate_calls),
        _criterion_failure_fallback(events, records, report_data, requires_fallback),
        _criterion_audit_surface(report_data),
    ]
    total_score = round(sum(criterion.score for criterion in criteria), 2)
    max_score = round(sum(criterion.max_score for criterion in criteria), 2)
    normalized_score = round((total_score / max_score) * 100, 2) if max_score else 0.0
    failed_findings = [
        f"{criterion.name}: {finding}"
        for criterion in criteria
        for finding in criterion.findings
    ]
    summary = (
        ["Tool calls satisfy the current quality gate."]
        if normalized_score >= pass_threshold and not failed_findings
        else failed_findings[:10]
    )
    return ToolQualityResult(
        total_score=total_score,
        max_score=max_score,
        normalized_score=normalized_score,
        grade=_grade(normalized_score),
        passed=normalized_score >= pass_threshold and not failed_findings,
        criteria=criteria,
        summary=summary,
        tool_counts=tool_call_counts(records),
        redundant_calls=redundant_tool_calls(records, max_duplicate_calls=max_duplicate_calls),
    )
