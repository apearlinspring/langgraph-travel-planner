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
    assistant_chars: int
    user_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    tool_turn_elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeBudget:
    """Deterministic budget thresholds for a live Agent run."""

    max_total_elapsed_seconds: float = 900.0
    max_first_token_seconds: float | None = 60.0
    max_tool_call_count: int = 32
    max_estimated_total_tokens: int = 120000
    max_error_event_count: int = 0
    max_tool_turn_elapsed_seconds: float | None = None
    warning_total_elapsed_ratio: float = 0.8
    warning_first_token_ratio: float = 0.8
    warning_tool_call_ratio: float = 0.8
    warning_token_ratio: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_RUNTIME_BUDGET = RuntimeBudget()


@dataclass(frozen=True)
class RuntimeBudgetGateResult:
    """Pass/fail result for the deterministic runtime budget gate."""

    passed: bool
    violations: list[str]
    warnings: list[str]
    budget: RuntimeBudget

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "warnings": self.warnings,
            "budget": self.budget.to_dict(),
        }


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
    budget_gate: RuntimeBudgetGateResult
    governance_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "grade": self.grade,
            "passed": self.passed,
            "summary": self.summary,
            "metrics": self.metrics.to_dict(),
            "budget_gate": self.budget_gate.to_dict(),
            "governance_summary": self.governance_summary,
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


def _coerce_optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or float(value) < 0:
        raise ValueError(f"Runtime budget field {field_name!r} must be a non-negative number or null")
    return float(value)


def _coerce_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"Runtime budget field {field_name!r} must be a non-negative integer")
    return value


def _coerce_ratio(value: Any, *, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError(f"Runtime budget field {field_name!r} must be a ratio between 0 and 1")
    return float(value)


def runtime_budget_from_dict(
    payload: dict[str, Any] | None,
    *,
    base: RuntimeBudget | None = None,
) -> RuntimeBudget:
    """Build a runtime budget from optional overrides."""

    budget = base or DEFAULT_RUNTIME_BUDGET
    if payload is None:
        return budget
    if not isinstance(payload, dict):
        raise TypeError("runtime budget payload must be a dictionary")

    allowed_fields = set(RuntimeBudget.__dataclass_fields__)
    unknown_fields = sorted(set(payload) - allowed_fields)
    if unknown_fields:
        raise ValueError(f"Unknown runtime budget fields: {', '.join(unknown_fields)}")

    values = budget.to_dict()
    for key, value in payload.items():
        if key == "max_total_elapsed_seconds":
            values[key] = _coerce_optional_float(value, field_name=key)
            if values[key] is None:
                raise ValueError("Runtime budget field 'max_total_elapsed_seconds' cannot be null")
        elif key in {"max_first_token_seconds", "max_tool_turn_elapsed_seconds"}:
            values[key] = _coerce_optional_float(value, field_name=key)
        elif key in {"max_tool_call_count", "max_estimated_total_tokens", "max_error_event_count"}:
            values[key] = _coerce_int(value, field_name=key)
        elif key.startswith("warning_"):
            values[key] = _coerce_ratio(value, field_name=key)
    return RuntimeBudget(**values)


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
        assistant_chars=assistant_chars,
        user_chars=user_chars,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_total_tokens=input_tokens + output_tokens,
        tool_turn_elapsed_seconds=_tool_turn_elapsed(turns),
    )


def _ratio(value: float, limit: float | int | None) -> float | None:
    if limit is None or float(limit) <= 0:
        return None
    return value / float(limit)


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{round(value * 100, 1)}%"


def evaluate_runtime_budget(
    metrics: RuntimeMetrics,
    budget: RuntimeBudget | None = None,
) -> RuntimeBudgetGateResult:
    """Evaluate runtime metrics against deterministic budget thresholds."""

    runtime_budget = budget or DEFAULT_RUNTIME_BUDGET
    violations: list[str] = []
    warnings: list[str] = []

    if metrics.total_elapsed_seconds > runtime_budget.max_total_elapsed_seconds:
        violations.append(
            "Total elapsed seconds "
            f"{metrics.total_elapsed_seconds} exceeds budget {runtime_budget.max_total_elapsed_seconds}"
        )
    elif (
        _ratio(metrics.total_elapsed_seconds, runtime_budget.max_total_elapsed_seconds)
        is not None
        and _ratio(metrics.total_elapsed_seconds, runtime_budget.max_total_elapsed_seconds)
        >= runtime_budget.warning_total_elapsed_ratio
    ):
        warnings.append(
            "Total elapsed seconds used "
            f"{_format_ratio(_ratio(metrics.total_elapsed_seconds, runtime_budget.max_total_elapsed_seconds))} "
            "of runtime budget"
        )

    if runtime_budget.max_first_token_seconds is not None:
        if metrics.first_token_seconds is None:
            warnings.append("First token timing is missing; first-token budget could not be asserted")
        elif metrics.first_token_seconds > runtime_budget.max_first_token_seconds:
            violations.append(
                "First token seconds "
                f"{metrics.first_token_seconds} exceeds budget {runtime_budget.max_first_token_seconds}"
            )
        elif (
            _ratio(metrics.first_token_seconds, runtime_budget.max_first_token_seconds)
            is not None
            and _ratio(metrics.first_token_seconds, runtime_budget.max_first_token_seconds)
            >= runtime_budget.warning_first_token_ratio
        ):
            warnings.append(
                "First token seconds used "
                f"{_format_ratio(_ratio(metrics.first_token_seconds, runtime_budget.max_first_token_seconds))} "
                "of first-token budget"
            )

    if metrics.tool_call_count > runtime_budget.max_tool_call_count:
        violations.append(
            f"Tool call count {metrics.tool_call_count} exceeds budget {runtime_budget.max_tool_call_count}"
        )
    elif (
        _ratio(metrics.tool_call_count, runtime_budget.max_tool_call_count)
        is not None
        and _ratio(metrics.tool_call_count, runtime_budget.max_tool_call_count)
        >= runtime_budget.warning_tool_call_ratio
    ):
        warnings.append(
            "Tool call count used "
            f"{_format_ratio(_ratio(metrics.tool_call_count, runtime_budget.max_tool_call_count))} "
            "of tool-call budget"
        )

    if metrics.estimated_total_tokens > runtime_budget.max_estimated_total_tokens:
        violations.append(
            "Estimated total tokens "
            f"{metrics.estimated_total_tokens} exceeds budget {runtime_budget.max_estimated_total_tokens}"
        )
    elif (
        _ratio(metrics.estimated_total_tokens, runtime_budget.max_estimated_total_tokens)
        is not None
        and _ratio(metrics.estimated_total_tokens, runtime_budget.max_estimated_total_tokens)
        >= runtime_budget.warning_token_ratio
    ):
        warnings.append(
            "Estimated total tokens used "
            f"{_format_ratio(_ratio(metrics.estimated_total_tokens, runtime_budget.max_estimated_total_tokens))} "
            "of token budget"
        )

    if metrics.error_event_count > runtime_budget.max_error_event_count:
        violations.append(
            f"Error event count {metrics.error_event_count} exceeds budget {runtime_budget.max_error_event_count}"
        )

    if (
        runtime_budget.max_tool_turn_elapsed_seconds is not None
        and metrics.tool_turn_elapsed_seconds > runtime_budget.max_tool_turn_elapsed_seconds
    ):
        violations.append(
            "Tool-turn elapsed seconds "
            f"{metrics.tool_turn_elapsed_seconds} exceeds budget "
            f"{runtime_budget.max_tool_turn_elapsed_seconds}"
        )

    return RuntimeBudgetGateResult(
        passed=not violations,
        violations=violations,
        warnings=warnings,
        budget=runtime_budget,
    )


def build_runtime_governance_summary(
    metrics: RuntimeMetrics,
    *,
    budget: RuntimeBudget | None = None,
    budget_gate: RuntimeBudgetGateResult | None = None,
    tool_counts: dict[str, int] | None = None,
    redundant_calls: list[str] | None = None,
) -> dict[str, Any]:
    """Summarize latency, cost, and tool-use risks for operators."""

    runtime_budget = budget or DEFAULT_RUNTIME_BUDGET
    gate = budget_gate or evaluate_runtime_budget(metrics, runtime_budget)
    elapsed_ratio = _ratio(metrics.total_elapsed_seconds, runtime_budget.max_total_elapsed_seconds)
    first_token_ratio = _ratio(metrics.first_token_seconds or 0.0, runtime_budget.max_first_token_seconds)
    token_ratio = _ratio(metrics.estimated_total_tokens, runtime_budget.max_estimated_total_tokens)
    tool_ratio = _ratio(metrics.tool_call_count, runtime_budget.max_tool_call_count)
    tool_turn_ratio = _ratio(metrics.tool_turn_elapsed_seconds, metrics.total_elapsed_seconds)

    slow_findings: list[str] = []
    if elapsed_ratio is not None and elapsed_ratio >= runtime_budget.warning_total_elapsed_ratio:
        slow_findings.append(
            f"Total run time used {_format_ratio(elapsed_ratio)} of the configured budget"
        )
    if metrics.first_token_seconds is None:
        slow_findings.append("First token timing is missing")
    elif (
        first_token_ratio is not None
        and first_token_ratio >= runtime_budget.warning_first_token_ratio
    ):
        slow_findings.append(
            f"First token latency used {_format_ratio(first_token_ratio)} of the configured budget"
        )
    if tool_turn_ratio is not None and tool_turn_ratio >= 0.5:
        slow_findings.append(
            f"Tool-bearing turns account for {_format_ratio(tool_turn_ratio)} of total run time"
        )

    cost_findings: list[str] = []
    if token_ratio is not None and token_ratio >= runtime_budget.warning_token_ratio:
        cost_findings.append(
            f"Estimated tokens used {_format_ratio(token_ratio)} of the configured budget"
        )
    if metrics.estimated_input_tokens > 0 and metrics.estimated_output_tokens > metrics.estimated_input_tokens * 2:
        cost_findings.append("Estimated output tokens are more than twice the input estimate")
    if tool_ratio is not None and tool_ratio >= runtime_budget.warning_tool_call_ratio:
        cost_findings.append(f"Tool calls used {_format_ratio(tool_ratio)} of the configured budget")

    tool_findings = list(redundant_calls or [])
    if metrics.tool_call_count > runtime_budget.max_tool_call_count:
        tool_findings.append("Tool calls exceeded the configured runtime budget")
    sorted_tool_counts = dict(sorted((tool_counts or {}).items(), key=lambda item: (-item[1], item[0])))

    error_findings: list[str] = []
    if metrics.error_event_count > runtime_budget.max_error_event_count:
        error_findings.append("Error events exceeded the configured runtime budget")

    return {
        "version": "runtime_governance_summary.v1",
        "status": "pass" if gate.passed else "fail",
        "budget": runtime_budget.to_dict(),
        "budget_violations": gate.violations,
        "budget_warnings": gate.warnings,
        "slow_path": {
            "total_elapsed_seconds": metrics.total_elapsed_seconds,
            "first_token_seconds": metrics.first_token_seconds,
            "tool_turn_elapsed_seconds": metrics.tool_turn_elapsed_seconds,
            "tool_turn_elapsed_ratio": round(tool_turn_ratio, 3) if tool_turn_ratio is not None else None,
            "findings": slow_findings,
        },
        "cost_risk": {
            "estimated_input_tokens": metrics.estimated_input_tokens,
            "estimated_output_tokens": metrics.estimated_output_tokens,
            "estimated_total_tokens": metrics.estimated_total_tokens,
            "estimated_total_token_ratio": round(token_ratio, 3) if token_ratio is not None else None,
            "findings": cost_findings,
        },
        "tool_usage": {
            "tool_call_count": metrics.tool_call_count,
            "tool_call_ratio": round(tool_ratio, 3) if tool_ratio is not None else None,
            "tool_counts": sorted_tool_counts,
            "redundant_calls": redundant_calls or [],
            "findings": tool_findings,
        },
        "errors": {
            "error_event_count": metrics.error_event_count,
            "max_error_event_count": runtime_budget.max_error_event_count,
            "findings": error_findings,
        },
    }


def _criterion_task_completion(metrics: RuntimeMetrics) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(metrics.report_event_count >= 1, 20, findings, "No report_data event captured")
    score += _score(metrics.error_event_count == 0, 10, findings, "Error events were captured")
    return CriterionResult("runtime_task_completion", score, 30, findings)


def _criterion_latency(metrics: RuntimeMetrics, budget: RuntimeBudget) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(
        0 < metrics.total_elapsed_seconds <= budget.max_total_elapsed_seconds,
        15,
        findings,
        f"Total elapsed seconds must be within budget {budget.max_total_elapsed_seconds}",
    )
    score += _score(
        (
            metrics.first_token_seconds is None
            or budget.max_first_token_seconds is None
            or metrics.first_token_seconds <= budget.max_first_token_seconds
            or metrics.report_event_count > 0
        ),
        10,
        findings,
        f"First token seconds must be within budget {budget.max_first_token_seconds}",
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


def _criterion_cost_estimate(metrics: RuntimeMetrics, budget: RuntimeBudget) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    score += _score(metrics.estimated_total_tokens > 0, 5, findings, "Estimated token usage is missing")
    score += _score(
        metrics.estimated_total_tokens <= budget.max_estimated_total_tokens,
        5,
        findings,
        f"Estimated token usage exceeds budget {budget.max_estimated_total_tokens}",
    )
    score += _score(metrics.user_chars > 0, 5, findings, "User prompt characters are missing")
    score += _score(
        metrics.estimated_output_tokens >= 0,
        5,
        findings,
        "Estimated output tokens must be non-negative",
    )
    return CriterionResult("runtime_cost_estimate", score, 20, findings)


def _criterion_budget_gate(gate: RuntimeBudgetGateResult) -> CriterionResult:
    findings = list(gate.violations)
    score = _score(gate.passed, 20, findings, "Runtime budget gate failed")
    return CriterionResult("runtime_budget_gate", score, 20, findings)


def evaluate_runtime_metrics(
    metrics: RuntimeMetrics,
    *,
    timeout_seconds: float = 900.0,
    budget: RuntimeBudget | None = None,
    pass_threshold: float = 80.0,
) -> RuntimeQualityResult:
    """Evaluate live-run observability, latency, and token-cost estimates."""

    runtime_budget = budget or runtime_budget_from_dict(
        {"max_total_elapsed_seconds": timeout_seconds},
        base=DEFAULT_RUNTIME_BUDGET,
    )
    budget_gate = evaluate_runtime_budget(metrics, runtime_budget)
    governance_summary = build_runtime_governance_summary(
        metrics,
        budget=runtime_budget,
        budget_gate=budget_gate,
    )
    criteria = [
        _criterion_task_completion(metrics),
        _criterion_latency(metrics, runtime_budget),
        _criterion_observability(metrics),
        _criterion_cost_estimate(metrics, runtime_budget),
        _criterion_budget_gate(budget_gate),
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
        ["Runtime metrics satisfy the current quality gate.", *budget_gate.warnings[:5]]
        if normalized_score >= pass_threshold and not failed_findings and budget_gate.passed
        else failed_findings[:10]
    )
    return RuntimeQualityResult(
        total_score=total_score,
        max_score=max_score,
        normalized_score=normalized_score,
        grade=_grade(normalized_score),
        passed=normalized_score >= pass_threshold and not failed_findings and budget_gate.passed,
        criteria=criteria,
        summary=summary,
        metrics=metrics,
        budget_gate=budget_gate,
        governance_summary=governance_summary,
    )
