"""Runtime metrics and deterministic quality checks for live evaluation snapshots."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.evaluation.report_quality import CriterionResult


@dataclass(frozen=True)
class RuntimeMetrics:
    """Observable runtime metrics captured or estimated from a live snapshot."""

    total_elapsed_seconds: float
    first_token_seconds: float | None
    turn_count: int
    event_count: int
    token_event_count: int
    tool_call_count: int
    report_event_count: int
    error_event_count: int
    session_busy_event_count: int
    assistant_chars: int
    user_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    tool_turn_elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeQualityResult:
    """Full deterministic evaluation result for runtime observability."""

    total_score: float
    max_score: float
    normalized_score: float
    grade: str
    passed: bool
    criteria: list[CriterionResult]
    summary: list[str]
    metrics: RuntimeMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "grade": self.grade,
            "passed": self.passed,
            "summary": self.summary,
            "metrics": self.metrics.to_dict(),
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


def _score(condition: bool, points: float, findings: list[str], message: str) -> float:
    if condition:
        return points
    findings.append(message)
    return 0.0


def estimate_token_count(text: str) -> int:
    """Estimate token usage with a stable character-based approximation."""

    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4) + math.ceil(non_ascii_chars / 2))


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or "")


def _first_token_seconds(events: list[dict[str, Any]]) -> float | None:
    for event in events:
        if not isinstance(event, dict) or _event_type(event) != "token":
            continue
        elapsed = event.get("elapsed_since_scenario_start")
        if isinstance(elapsed, (int, float)):
            return round(float(elapsed), 3)
    return None


def _turn_user_chars(turns: list[dict[str, Any]]) -> int:
    total = 0
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        message = turn.get("user_message")
        if isinstance(message, str):
            total += len(message)
    return total


def _tool_turn_elapsed(turns: list[dict[str, Any]]) -> float:
    total = 0.0
    for turn in turns:
        if not isinstance(turn, dict) or not turn.get("tool_call_count"):
            continue
        elapsed = turn.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)):
            total += float(elapsed)
    return round(total, 3)


def collect_runtime_metrics(
    *,
    events: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    assistant_text: str,
    elapsed_seconds: float,
) -> RuntimeMetrics:
    """Collect runtime metrics from a live snapshot payload."""

    if not isinstance(events, list):
        raise TypeError("events must be a list")
    if not isinstance(turns, list):
        raise TypeError("turns must be a list")

    event_types = [_event_type(event) for event in events if isinstance(event, dict)]
    user_chars = _turn_user_chars(turns)
    assistant_chars = len(assistant_text)
    input_tokens = estimate_token_count(
        "\n".join(
            str(turn.get("user_message"))
            for turn in turns
            if isinstance(turn, dict) and isinstance(turn.get("user_message"), str)
        )
    )
    output_tokens = estimate_token_count(assistant_text)
    return RuntimeMetrics(
        total_elapsed_seconds=round(float(elapsed_seconds), 3),
        first_token_seconds=_first_token_seconds(events),
        turn_count=len(turns),
        event_count=len(events),
        token_event_count=sum(1 for event_type in event_types if event_type == "token"),
        tool_call_count=sum(1 for event_type in event_types if event_type == "tool_call"),
        report_event_count=sum(1 for event_type in event_types if event_type == "report_data"),
        error_event_count=sum(1 for event_type in event_types if event_type == "error"),
        session_busy_event_count=sum(1 for event_type in event_types if event_type == "session_busy"),
        assistant_chars=assistant_chars,
        user_chars=user_chars,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_total_tokens=input_tokens + output_tokens,
        tool_turn_elapsed_seconds=_tool_turn_elapsed(turns),
    )


def _criterion_task_completion(metrics: RuntimeMetrics) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(metrics.report_event_count >= 1, 20, findings, "No report_data event captured")
    score += _score(metrics.error_event_count == 0, 10, findings, "Error events were captured")
    return CriterionResult("runtime_task_completion", score, 30, findings)


def _criterion_latency(metrics: RuntimeMetrics, timeout_seconds: float) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(
        0 < metrics.total_elapsed_seconds <= timeout_seconds,
        15,
        findings,
        f"Total elapsed seconds must be within timeout {timeout_seconds}",
    )
    score += _score(
        metrics.first_token_seconds is not None or metrics.report_event_count > 0,
        10,
        findings,
        "Snapshot should include first token timing or report_data completion",
    )
    score += _score(
        metrics.tool_turn_elapsed_seconds <= metrics.total_elapsed_seconds,
        5,
        findings,
        "Tool-turn elapsed seconds cannot exceed total elapsed seconds",
    )
    return CriterionResult("runtime_latency", score, 30, findings)


def _criterion_observability(metrics: RuntimeMetrics) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(metrics.turn_count >= 1, 7, findings, "Snapshot must include turn summaries")
    score += _score(metrics.event_count >= metrics.report_event_count, 7, findings, "Event count is inconsistent")
    score += _score(
        metrics.assistant_chars > 0 or metrics.report_event_count > 0,
        6,
        findings,
        "Snapshot should contain assistant text or report_data",
    )
    return CriterionResult("runtime_observability", score, 20, findings)


def _criterion_cost_estimate(metrics: RuntimeMetrics) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(metrics.estimated_total_tokens > 0, 5, findings, "Estimated token usage is missing")
    score += _score(
        metrics.estimated_total_tokens < 120000,
        5,
        findings,
        "Estimated token usage exceeds local regression budget",
    )
    score += _score(metrics.user_chars > 0, 5, findings, "User prompt characters are missing")
    score += _score(
        metrics.estimated_output_tokens >= 0,
        5,
        findings,
        "Estimated output tokens must be non-negative",
    )
    return CriterionResult("runtime_cost_estimate", score, 20, findings)


def evaluate_runtime_metrics(
    metrics: RuntimeMetrics,
    *,
    timeout_seconds: float = 900.0,
    pass_threshold: float = 80.0,
) -> RuntimeQualityResult:
    """Evaluate live-run observability, latency, and token-cost estimates."""

    criteria = [
        _criterion_task_completion(metrics),
        _criterion_latency(metrics, timeout_seconds),
        _criterion_observability(metrics),
        _criterion_cost_estimate(metrics),
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
        ["Runtime metrics satisfy the current quality gate."]
        if normalized_score >= pass_threshold and not failed_findings
        else failed_findings[:10]
    )
    return RuntimeQualityResult(
        total_score=total_score,
        max_score=max_score,
        normalized_score=normalized_score,
        grade=_grade(normalized_score),
        passed=normalized_score >= pass_threshold and not failed_findings,
        criteria=criteria,
        summary=summary,
        metrics=metrics,
    )
