"""Acceptance quality gate aggregation for first-stage project verification."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.evaluation.preflight import ACCEPTANCE_STATUSES
from app.evaluation.scenarios import ACCEPTANCE_CORE_TAG, EvaluationScenario


ACCEPTANCE_GATE_VERSION = "acceptance_quality_gate.v1"
ACCEPTANCE_SUMMARY_VERSION = "acceptance_run_summary.v1"


@dataclass(frozen=True)
class AcceptanceThresholds:
    """Thresholds used by the auditable first-stage acceptance quality gate."""

    min_agent_score: float = 82.0
    min_report_score: float = 80.0
    min_rag_score: float = 80.0
    min_tool_score: float = 80.0
    min_runtime_score: float = 80.0
    min_budget_confidence_score: float = 100.0
    min_tool_audit_score: float = 100.0
    min_internal_evidence_categories: int = 3
    require_runtime_budget_pass: bool = True
    require_internal_evidence_for_agency: bool = True
    require_tool_audit_surface: bool = True
    require_turn_observability: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_ACCEPTANCE_THRESHOLDS = AcceptanceThresholds()


DIMENSION_LABELS = {
    "agent_quality": "Agent aggregate quality",
    "report_quality": "Report quality",
    "rag_quality": "RAG evidence quality",
    "tool_quality": "Tool governance quality",
    "runtime_quality": "Runtime metrics quality",
    "runtime_budget": "Runtime budget gate",
    "runtime_observability": "Production observability surface",
    "budget_confidence": "Budget confidence contract",
    "internal_evidence": "Internal evidence references",
    "tool_audit": "Tool audit surface",
    "live_run": "Live scenario execution",
    "preflight": "Preflight environment check",
    "environment_dependencies": "Environment dependencies",
    "llm_judge": "LLM judge supplement",
}


DIMENSION_SUGGESTIONS = {
    "agent_quality": (
        "Check the per-dimension scores first; the aggregate gate usually fails "
        "because one report, RAG, tool, or runtime dimension is already failing."
    ),
    "report_quality": (
        "Inspect report_data structure, itinerary/map parity, budget items, risks, "
        "and app/reports contract rendering."
    ),
    "rag_quality": (
        "Inspect agency_context.evidence and evidence_bundle coverage; agency-plan "
        "scenarios should cite product, SOP, pricing, and risk evidence."
    ),
    "tool_quality": (
        "Inspect SSE tool_call events, forbidden tools, duplicate high-cost calls, "
        "and fallback pending checks."
    ),
    "runtime_quality": (
        "Inspect total elapsed time, first-token latency, error events, tool-call "
        "count, and estimated token pressure."
    ),
    "runtime_budget": (
        "Inspect runtime_budget violations; slow or repeated external tools usually "
        "need either a code fix or a scenario-specific budget override."
    ),
    "runtime_observability": (
        "Inspect SSE turn_observability events and app/core/observability.py; every "
        "live turn should expose a safe turn-level metrics summary."
    ),
    "budget_confidence": (
        "Inspect budget_confidence; it must expose a level, confirmed or estimated "
        "items, and verification items."
    ),
    "internal_evidence": (
        "Inspect internal evidence category coverage; agency-plan reports need at "
        "least three agency evidence categories."
    ),
    "tool_audit": (
        "Inspect tool_audit_summary; it must expose used sources, pending checks, "
        "and unsupported actions."
    ),
    "live_run": (
        "Inspect the saved snapshot, backend logs, SSE stream events, and the final "
        "state-transition turn that should produce report_data."
    ),
    "preflight": (
        "Inspect missing required environment variables, backend health, and scenario "
        "requirements before running live acceptance."
    ),
    "environment_dependencies": (
        "Inspect the preflight readiness checks, required environment variable names, "
        "backend health endpoints, and declared scenario dependency requirements."
    ),
    "llm_judge": (
        "Inspect the redacted judge result as qualitative feedback only; deterministic "
        "acceptance dimensions remain the source of truth for pass/fail."
    ),
}


def acceptance_thresholds_from_dict(
    payload: dict[str, Any] | None,
    *,
    base: AcceptanceThresholds | None = None,
) -> AcceptanceThresholds:
    """Build thresholds from optional CLI or test overrides."""

    thresholds = base or DEFAULT_ACCEPTANCE_THRESHOLDS
    if payload is None:
        return thresholds
    if not isinstance(payload, dict):
        raise TypeError("acceptance thresholds payload must be a dictionary")

    allowed_fields = set(AcceptanceThresholds.__dataclass_fields__)
    unknown_fields = sorted(set(payload) - allowed_fields)
    if unknown_fields:
        raise ValueError(f"Unknown acceptance threshold fields: {', '.join(unknown_fields)}")

    values = thresholds.to_dict()
    for key, value in payload.items():
        if key == "min_internal_evidence_categories":
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"Acceptance threshold field {key!r} must be a non-negative integer")
            values[key] = value
        elif key.startswith("require_"):
            if not isinstance(value, bool):
                raise ValueError(f"Acceptance threshold field {key!r} must be a boolean")
            values[key] = value
        else:
            if not isinstance(value, (int, float)) or not 0 <= float(value) <= 100:
                raise ValueError(f"Acceptance threshold field {key!r} must be between 0 and 100")
            values[key] = float(value)
    return AcceptanceThresholds(**values)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return int(value) if isinstance(value, int) else None


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _score_bool(parts: Iterable[bool]) -> float:
    checks = list(parts)
    if not checks:
        return 0.0
    return round(sum(1 for item in checks if item) / len(checks) * 100, 2)


def _result_findings(result: dict[str, Any]) -> list[str]:
    summary_items = (
        []
        if result.get("passed") is True
        else [str(item) for item in _as_list(result.get("summary")) if str(item).strip()]
    )
    criteria_findings = [
        f"{criterion.get('name')}: {finding}"
        for criterion in _as_list(result.get("criteria"))
        if isinstance(criterion, dict)
        for finding in _as_list(criterion.get("findings"))
    ]
    return [*summary_items, *criteria_findings][:10]


def _dimension_result(
    *,
    key: str,
    score: float | None,
    threshold: float | None,
    passed: bool,
    status: str | None = None,
    findings: list[str] | None = None,
) -> dict[str, Any]:
    resolved_status = status or ("passed" if passed else "failed")
    if resolved_status not in ACCEPTANCE_STATUSES:
        raise ValueError(f"Unknown acceptance status: {resolved_status}")
    return {
        "key": key,
        "label": DIMENSION_LABELS.get(key, key),
        "status": resolved_status,
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "findings": findings or [],
        "suggestion": DIMENSION_SUGGESTIONS.get(key, "Inspect this dimension's detailed result."),
    }


def _scored_quality_dimension(
    key: str,
    result: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
    score = result.get("normalized_score")
    numeric_score = float(score) if isinstance(score, (int, float)) else None
    findings = _result_findings(result)
    passed = (
        bool(result.get("passed"))
        and numeric_score is not None
        and numeric_score >= threshold
        and not findings
    )
    if numeric_score is not None and numeric_score < threshold:
        findings = [
            f"{DIMENSION_LABELS[key]} score {numeric_score} is below threshold {threshold}",
            *findings,
        ]
    if not result:
        findings = [f"{DIMENSION_LABELS[key]} result is missing"]
    return _dimension_result(
        key=key,
        score=numeric_score,
        threshold=threshold,
        passed=passed,
        findings=findings[:10],
    )


def _budget_confidence_dimension(
    report_data: dict[str, Any] | None,
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    budget_confidence = _as_dict(_as_dict(report_data).get("budget_confidence"))
    has_level = _has_text(budget_confidence.get("level"))
    has_status_items = bool(
        _as_list(budget_confidence.get("confirmed_items"))
        or _as_list(budget_confidence.get("estimated_items"))
    )
    has_verification = bool(_as_list(budget_confidence.get("verification_items")))
    checks = [has_level, has_status_items, has_verification]
    score = _score_bool(checks)
    findings: list[str] = []
    if not has_level:
        findings.append("budget_confidence.level is missing")
    if not has_status_items:
        findings.append("budget_confidence needs confirmed_items or estimated_items")
    if not has_verification:
        findings.append("budget_confidence.verification_items is missing")
    return _dimension_result(
        key="budget_confidence",
        score=score,
        threshold=thresholds.min_budget_confidence_score,
        passed=score >= thresholds.min_budget_confidence_score and not findings,
        findings=findings,
    )


def _internal_evidence_categories(report_data: dict[str, Any] | None) -> set[str]:
    report = _as_dict(report_data)
    agency_context = _as_dict(report.get("agency_context"))
    categories: set[str] = set()
    for item in _as_list(agency_context.get("evidence")):
        evidence = _as_dict(item)
        if evidence.get("source_type") == "agency_internal" and _has_text(evidence.get("category")):
            categories.add(str(evidence["category"]).strip())

    for category, value in _as_dict(agency_context.get("categories")).items():
        if _has_text(category) and value:
            categories.add(str(category).strip())

    bundle_categories = _as_dict(_as_dict(report.get("evidence_bundle")).get("agency_categories"))
    for category, value in bundle_categories.items():
        if _has_text(category) and isinstance(value, (int, float)) and value > 0:
            categories.add(str(category).strip())
    return categories


def _internal_evidence_dimension(
    scenario: EvaluationScenario,
    report_data: dict[str, Any] | None,
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    if scenario.expected_mode != "agency_plan" or not thresholds.require_internal_evidence_for_agency:
        return _dimension_result(
            key="internal_evidence",
            score=100.0,
            threshold=None,
            passed=True,
            findings=[],
        )

    categories = _internal_evidence_categories(report_data)
    required = thresholds.min_internal_evidence_categories
    score = 100.0 if required == 0 else round(min(len(categories) / required, 1.0) * 100, 2)
    findings = []
    if len(categories) < required:
        findings.append(
            "Internal evidence category coverage "
            f"{len(categories)} is below required {required}; covered={sorted(categories)}"
        )
    return _dimension_result(
        key="internal_evidence",
        score=score,
        threshold=100.0,
        passed=len(categories) >= required,
        findings=findings,
    )


def _tool_audit_dimension(
    report_data: dict[str, Any] | None,
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    if not thresholds.require_tool_audit_surface:
        return _dimension_result(
            key="tool_audit",
            score=100.0,
            threshold=None,
            passed=True,
            findings=[],
        )

    tool_audit = _as_dict(_as_dict(report_data).get("tool_audit_summary"))
    has_used_sources = bool(_as_list(tool_audit.get("used_sources")))
    has_pending_checks = bool(_as_list(tool_audit.get("pending_checks")))
    has_unsupported_actions = bool(_as_list(tool_audit.get("unsupported_actions")))
    checks = [has_used_sources, has_pending_checks, has_unsupported_actions]
    score = _score_bool(checks)
    findings: list[str] = []
    if not has_used_sources:
        findings.append("tool_audit_summary.used_sources is missing")
    if not has_pending_checks:
        findings.append("tool_audit_summary.pending_checks is missing")
    if not has_unsupported_actions:
        findings.append("tool_audit_summary.unsupported_actions is missing")
    return _dimension_result(
        key="tool_audit",
        score=score,
        threshold=thresholds.min_tool_audit_score,
        passed=score >= thresholds.min_tool_audit_score and not findings,
        findings=findings,
    )


def _llm_judge_supplement_dimension(
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    if not result:
        return _dimension_result(
            key="llm_judge",
            score=None,
            threshold=None,
            passed=False,
            status="skipped",
            findings=["LLM judge was not requested for this run."],
        )

    score = result.get("normalized_score")
    numeric_score = float(score) if isinstance(score, (int, float)) else None
    status = str(result.get("status") or ("passed" if result.get("passed") else "failed"))
    if status not in ACCEPTANCE_STATUSES:
        status = "failed"
    findings = [
        str(item)
        for item in [
            *_as_list(result.get("findings")),
            *_as_list(result.get("concerns")),
        ]
        if str(item).strip()
    ][:10]
    return _dimension_result(
        key="llm_judge",
        score=numeric_score,
        threshold=(
            float(result["threshold"])
            if isinstance(result.get("threshold"), (int, float))
            else None
        ),
        passed=bool(result.get("passed")) and status == "passed",
        status=status,
        findings=findings,
    )


def _runtime_budget_dimension(
    quality_summary: dict[str, Any],
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    runtime_quality = _as_dict(quality_summary.get("runtime_quality"))
    budget_gate = _as_dict(runtime_quality.get("budget_gate"))
    passed = bool(budget_gate.get("passed")) or not thresholds.require_runtime_budget_pass
    findings = [
        str(item)
        for item in [
            *_as_list(budget_gate.get("violations")),
            *_as_list(budget_gate.get("warnings")),
        ]
        if str(item).strip()
    ]
    if thresholds.require_runtime_budget_pass and not budget_gate:
        findings.insert(0, "runtime_quality.budget_gate is missing")
    status = "passed"
    if not passed:
        status = "failed"
    elif findings:
        status = "degraded"
    return _dimension_result(
        key="runtime_budget",
        score=100.0 if passed else 0.0,
        threshold=100.0 if thresholds.require_runtime_budget_pass else None,
        passed=passed,
        status=status,
        findings=findings[:10],
    )


def _runtime_observability_dimension(
    quality_summary: dict[str, Any],
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    if not thresholds.require_turn_observability:
        return _dimension_result(
            key="runtime_observability",
            score=100.0,
            threshold=None,
            passed=True,
            findings=[],
        )

    runtime_metrics = _as_dict(quality_summary.get("runtime_metrics"))
    event_count = runtime_metrics.get("turn_observability_event_count")
    count = int(event_count) if isinstance(event_count, int) else 0
    findings = []
    if count < 1:
        findings.append("runtime_metrics.turn_observability_event_count is missing or zero")
    return _dimension_result(
        key="runtime_observability",
        score=100.0 if count >= 1 else 0.0,
        threshold=100.0,
        passed=count >= 1,
        findings=findings,
    )


def _agent_quality_dimension(
    scenario: EvaluationScenario,
    quality_summary: dict[str, Any],
    thresholds: AcceptanceThresholds,
) -> dict[str, Any]:
    aggregate = _as_dict(quality_summary.get("aggregate"))
    score = aggregate.get("normalized_score")
    numeric_score = float(score) if isinstance(score, (int, float)) else None
    threshold = max(thresholds.min_agent_score, scenario.min_score)
    findings: list[str] = []
    if numeric_score is None:
        findings.append("aggregate.normalized_score is missing")
    elif numeric_score < threshold:
        findings.append(f"Aggregate score {numeric_score} is below threshold {threshold}")
    if not bool(aggregate.get("passed")):
        findings.append("aggregate.passed is false")
    return _dimension_result(
        key="agent_quality",
        score=numeric_score,
        threshold=threshold,
        passed=not findings,
        findings=findings,
    )


def _failure_records(
    *,
    scenario: EvaluationScenario,
    dimensions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    failures = []
    for key, dimension in dimensions.items():
        if dimension["passed"]:
            continue
        failures.append(
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "dimension": key,
                "dimension_label": dimension["label"],
                "status": dimension.get("status", "failed"),
                "score": dimension["score"],
                "threshold": dimension["threshold"],
                "findings": dimension["findings"] or [f"{dimension['label']} failed"],
                "suggestion": dimension["suggestion"],
            }
        )
    return failures


def _degradation_records(
    *,
    scenario: EvaluationScenario,
    dimensions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    degradations = []
    for key, dimension in dimensions.items():
        if dimension.get("status") != "degraded":
            continue
        degradations.append(
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "dimension": key,
                "dimension_label": dimension["label"],
                "status": "degraded",
                "score": dimension["score"],
                "threshold": dimension["threshold"],
                "findings": dimension["findings"] or [f"{dimension['label']} degraded"],
                "suggestion": dimension["suggestion"],
            }
        )
    return degradations


def build_acceptance_gate_result(
    *,
    scenario: EvaluationScenario,
    quality_summary: dict[str, Any],
    report_data: dict[str, Any] | None,
    snapshot_path: str | None = None,
    thresholds: AcceptanceThresholds | None = None,
    llm_judge_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one auditable acceptance gate result for a completed scenario."""

    gate_thresholds = thresholds or DEFAULT_ACCEPTANCE_THRESHOLDS
    if not isinstance(quality_summary, dict):
        raise TypeError("quality_summary must be a dictionary")

    dimensions = {
        "agent_quality": _agent_quality_dimension(scenario, quality_summary, gate_thresholds),
        "report_quality": _scored_quality_dimension(
            "report_quality",
            _as_dict(quality_summary.get("report_quality")),
            gate_thresholds.min_report_score,
        ),
        "rag_quality": _scored_quality_dimension(
            "rag_quality",
            _as_dict(quality_summary.get("rag_quality")),
            gate_thresholds.min_rag_score,
        ),
        "tool_quality": _scored_quality_dimension(
            "tool_quality",
            _as_dict(quality_summary.get("tool_quality")),
            gate_thresholds.min_tool_score,
        ),
        "runtime_quality": _scored_quality_dimension(
            "runtime_quality",
            _as_dict(quality_summary.get("runtime_quality")),
            gate_thresholds.min_runtime_score,
        ),
        "runtime_budget": _runtime_budget_dimension(quality_summary, gate_thresholds),
        "runtime_observability": _runtime_observability_dimension(
            quality_summary,
            gate_thresholds,
        ),
        "budget_confidence": _budget_confidence_dimension(report_data, gate_thresholds),
        "internal_evidence": _internal_evidence_dimension(scenario, report_data, gate_thresholds),
        "tool_audit": _tool_audit_dimension(report_data, gate_thresholds),
    }
    failures = _failure_records(scenario=scenario, dimensions=dimensions)
    degradations = _degradation_records(scenario=scenario, dimensions=dimensions)
    status = "failed" if failures else "degraded" if degradations else "passed"
    supplemental_dimensions = {
        "llm_judge": _llm_judge_supplement_dimension(llm_judge_evaluation),
    }
    return {
        "version": ACCEPTANCE_GATE_VERSION,
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "scenario_category": scenario.category,
        "expected_mode": scenario.expected_mode,
        "status": status,
        "passed": status == "passed",
        "snapshot_path": snapshot_path,
        "thresholds": gate_thresholds.to_dict(),
        "dimensions": dimensions,
        "supplemental_dimensions": supplemental_dimensions,
        "failures": failures,
        "degradations": degradations,
    }


def build_error_acceptance_gate_result(
    *,
    scenario: EvaluationScenario,
    error: str,
    snapshot_path: str | None = None,
    thresholds: AcceptanceThresholds | None = None,
    status: str = "failed",
    llm_judge_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an acceptance result for a scenario that failed before scoring."""

    if status not in {"failed", "blocked", "skipped"}:
        raise ValueError("Error acceptance gate status must be failed, blocked, or skipped")
    gate_thresholds = thresholds or DEFAULT_ACCEPTANCE_THRESHOLDS
    dimension = _dimension_result(
        key="live_run",
        score=0.0,
        threshold=100.0,
        passed=False,
        status=status,
        findings=[error],
    )
    dimensions = {"live_run": dimension}
    return {
        "version": ACCEPTANCE_GATE_VERSION,
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "scenario_category": scenario.category,
        "expected_mode": scenario.expected_mode,
        "status": status,
        "passed": False,
        "snapshot_path": snapshot_path,
        "thresholds": gate_thresholds.to_dict(),
        "dimensions": dimensions,
        "supplemental_dimensions": {
            "llm_judge": _llm_judge_supplement_dimension(llm_judge_evaluation),
        },
        "failures": _failure_records(scenario=scenario, dimensions=dimensions),
        "degradations": [],
    }


def build_skipped_acceptance_gate_result(
    *,
    scenario: EvaluationScenario,
    reason: str,
    thresholds: AcceptanceThresholds | None = None,
) -> dict[str, Any]:
    """Build an acceptance result for a scenario skipped by preflight."""

    return build_error_acceptance_gate_result(
        scenario=scenario,
        error=reason,
        snapshot_path=None,
        thresholds=thresholds,
        status="skipped",
    )


def _preflight_records(
    preflight: dict[str, Any] | None,
    *,
    statuses: set[str],
) -> list[dict[str, Any]]:
    records = []
    for check in _as_list(_as_dict(preflight).get("checks")):
        if not isinstance(check, dict) or check.get("status") not in statuses:
            continue
        status = str(check.get("status") or "failed")
        records.append(
            {
                "scenario_id": "__preflight__",
                "scenario_name": "Preflight environment",
                "dimension": "environment_dependencies",
                "dimension_label": DIMENSION_LABELS["environment_dependencies"],
                "status": status,
                "score": 0.0 if status in {"blocked", "skipped"} else None,
                "threshold": 100.0 if status in {"blocked", "skipped"} else None,
                "findings": [
                    f"{check.get('label') or check.get('key')}: {finding}"
                    for finding in _as_list(check.get("findings"))
                ]
                or [f"{check.get('label') or check.get('key')} is {status}"],
                "suggestion": check.get("suggestion")
                or DIMENSION_SUGGESTIONS["environment_dependencies"],
                "env_vars": _as_list(check.get("env_vars")),
            }
        )
    return records


def _safe_tool_counts(value: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tool, count in _as_dict(value).items():
        if not isinstance(tool, str) or not tool.strip():
            continue
        numeric_count = _as_int(count)
        if numeric_count is None or numeric_count < 0:
            continue
        counts[tool.strip()] = numeric_count
    return counts


def _result_runtime_metrics(result: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(result.get("runtime_metrics"))


def _acceptance_runtime_totals(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_elapsed = 0.0
    elapsed_count = 0
    total_tool_calls = 0
    total_tool_failures = 0
    total_fallbacks = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    token_count = 0
    tool_counts: dict[str, int] = {}

    for result in results:
        if not isinstance(result, dict):
            continue
        metrics = _result_runtime_metrics(result)
        elapsed = _as_number(metrics.get("total_elapsed_seconds"))
        if elapsed is None:
            elapsed = _as_number(result.get("elapsed_seconds"))
        if elapsed is not None:
            total_elapsed += elapsed
            elapsed_count += 1

        tool_call_count = _as_int(metrics.get("tool_call_count"))
        if tool_call_count is not None:
            total_tool_calls += tool_call_count
        else:
            total_tool_calls += sum(_safe_tool_counts(result.get("tool_counts")).values())

        total_tool_failures += _as_int(metrics.get("tool_failure_count")) or 0
        total_fallbacks += _as_int(metrics.get("fallback_count")) or 0

        input_tokens = _as_int(metrics.get("estimated_input_tokens"))
        output_tokens = _as_int(metrics.get("estimated_output_tokens"))
        estimated_tokens = _as_int(metrics.get("estimated_total_tokens"))
        if input_tokens is not None:
            total_input_tokens += input_tokens
        if output_tokens is not None:
            total_output_tokens += output_tokens
        if estimated_tokens is not None:
            total_tokens += estimated_tokens
            token_count += 1

        for tool, count in _safe_tool_counts(result.get("tool_counts")).items():
            tool_counts[tool] = tool_counts.get(tool, 0) + count

    return {
        "elapsed_seconds": round(total_elapsed, 3),
        "average_elapsed_seconds": round(total_elapsed / elapsed_count, 3) if elapsed_count else None,
        "tool_call_count": total_tool_calls,
        "tool_failure_count": total_tool_failures,
        "fallback_count": total_fallbacks,
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_total_tokens": total_tokens,
        "average_estimated_total_tokens": round(total_tokens / token_count, 2) if token_count else None,
        "tool_counts": dict(sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def build_acceptance_run_summary(
    *,
    results: list[dict[str, Any]],
    scenarios: list[EvaluationScenario],
    base_url: str,
    output_dir: Path,
    thresholds: AcceptanceThresholds | None = None,
    preflight: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the JSON-serializable run-level acceptance summary."""

    gate_thresholds = thresholds or DEFAULT_ACCEPTANCE_THRESHOLDS
    created = created_at or datetime.now(timezone.utc)
    scenario_ids = [scenario.id for scenario in scenarios]
    completed_ids = [str(result.get("scenario_id")) for result in results]
    missing_ids = [scenario_id for scenario_id in scenario_ids if scenario_id not in set(completed_ids)]
    gates = [_as_dict(result.get("acceptance_gate")) for result in results]
    failures = [
        failure
        for gate in gates
        for failure in _as_list(gate.get("failures"))
        if isinstance(failure, dict)
    ]
    degradations = [
        degradation
        for gate in gates
        for degradation in _as_list(gate.get("degradations"))
        if isinstance(degradation, dict)
    ]
    failures.extend(
        _preflight_records(preflight, statuses={"blocked", "skipped"})
    )
    degradations.extend(
        _preflight_records(preflight, statuses={"degraded"})
    )
    if missing_ids:
        failures.append(
            {
                "scenario_id": "__run__",
                "scenario_name": "Incomplete run",
                "dimension": "live_run",
                "dimension_label": DIMENSION_LABELS["live_run"],
                "score": 0.0,
                "threshold": 100.0,
                "findings": [
                    "The run stopped before these selected scenarios completed: "
                    + ", ".join(missing_ids)
                ],
                "suggestion": DIMENSION_SUGGESTIONS["live_run"],
            }
        )

    status_counts = {
        status: sum(1 for gate in gates if gate.get("status") == status)
        for status in sorted(ACCEPTANCE_STATUSES)
    }
    llm_judge_status_counts = {
        status: sum(
            1
            for gate in gates
            if _as_dict(_as_dict(gate.get("supplemental_dimensions")).get("llm_judge")).get("status") == status
        )
        for status in sorted(ACCEPTANCE_STATUSES)
    }
    passed_count = status_counts.get("passed", 0)
    scores = [
        float(_as_dict(gate.get("dimensions")).get("agent_quality", {}).get("score"))
        for gate in gates
        if isinstance(_as_dict(gate.get("dimensions")).get("agent_quality", {}).get("score"), (int, float))
    ]
    runtime_totals = _acceptance_runtime_totals(results)
    preflight_status = _as_dict(preflight).get("status")
    if preflight_status == "blocked":
        run_status = "blocked"
    elif any(gate.get("status") == "blocked" for gate in gates):
        run_status = "blocked"
    elif preflight_status == "degraded" and gates and all(gate.get("status") == "skipped" for gate in gates):
        run_status = "degraded"
    elif gates and all(gate.get("status") == "skipped" for gate in gates):
        run_status = "skipped"
    elif preflight_status == "skipped" or (not scenarios and not results):
        run_status = "skipped"
    elif failures or len(results) != len(scenarios) or not results:
        run_status = "failed"
    elif preflight_status == "degraded" or any(gate.get("status") == "degraded" for gate in gates):
        run_status = "degraded"
    else:
        run_status = "passed"

    return {
        "version": ACCEPTANCE_SUMMARY_VERSION,
        "created_at": created.isoformat(),
        "base_url": base_url,
        "output_dir": str(output_dir),
        "core_tag": ACCEPTANCE_CORE_TAG,
        "status": run_status,
        "thresholds": gate_thresholds.to_dict(),
        "preflight": preflight,
        "selected_scenarios": [scenario.to_dict() for scenario in scenarios],
        "result_count": len(results),
        "selected_count": len(scenarios),
        "status_counts": status_counts,
        "llm_judge_status_counts": llm_judge_status_counts,
        "passed_count": passed_count,
        "failed_count": status_counts.get("failed", 0) + len(missing_ids),
        "blocked_count": status_counts.get("blocked", 0),
        "degraded_count": status_counts.get("degraded", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "passed": run_status == "passed",
        "average_agent_score": round(sum(scores) / len(scores), 2) if scores else None,
        "runtime_totals": runtime_totals,
        "tool_counts": runtime_totals["tool_counts"],
        "results": results,
        "failures": failures,
        "degradations": degradations,
    }


def render_acceptance_markdown(summary: dict[str, Any]) -> str:
    """Render a human-readable Markdown acceptance summary."""

    status = str(summary.get("status") or ("passed" if summary.get("passed") else "failed"))
    status_label = {
        "passed": "passed（通过）",
        "failed": "failed（失败）",
        "degraded": "degraded（降级）",
        "blocked": "blocked（环境阻塞）",
        "skipped": "skipped（跳过）",
    }.get(status, status)
    lines = [
        "# 第一阶段验收质量门禁",
        "",
        f"- 结论: {status_label}",
        f"- 场景: {summary.get('passed_count')} / {summary.get('selected_count')} 通过",
        f"- 状态统计: {summary.get('status_counts')}",
        f"- LLM-as-Judge（大模型评审）补充统计: {summary.get('llm_judge_status_counts')}",
        f"- 平均 Agent（智能体）综合分: {summary.get('average_agent_score')}",
        f"- 总耗时: {_as_dict(summary.get('runtime_totals')).get('elapsed_seconds')} 秒",
        f"- 工具调用: {_as_dict(summary.get('runtime_totals')).get('tool_call_count')} 次",
        f"- 估算 token（文本令牌）: {_as_dict(summary.get('runtime_totals')).get('estimated_total_tokens')}",
        f"- 生成时间: {summary.get('created_at')}",
        f"- 后端地址: {summary.get('base_url')}",
        "",
        "## 门禁阈值",
    ]
    thresholds = _as_dict(summary.get("thresholds"))
    lines.extend(
        [
            f"- 报告质量: >= {thresholds.get('min_report_score')}",
            f"- RAG（检索增强生成）质量: >= {thresholds.get('min_rag_score')}",
            f"- 工具治理质量: >= {thresholds.get('min_tool_score')}",
            f"- 运行时质量: >= {thresholds.get('min_runtime_score')}",
            f"- 生产观测摘要: {'required（必需）' if thresholds.get('require_turn_observability') else 'optional（可选）'}",
            f"- 预算置信度契约: >= {thresholds.get('min_budget_confidence_score')}",
            f"- 旅行社内部证据类别: >= {thresholds.get('min_internal_evidence_categories')}",
        ]
    )
    preflight = _as_dict(summary.get("preflight"))
    if preflight:
        lines.extend(["", "## Preflight（预检）"])
        lines.append(f"- 状态: {preflight.get('status')}")
        lines.append(f"- `.env` 存在: {preflight.get('dotenv_present')}")
        skipped_metrics = _as_list(preflight.get("skipped_metrics"))
        if skipped_metrics:
            lines.append("- 指标不可判定: " + ", ".join(str(item) for item in skipped_metrics))
        lines.extend(["", "| 检查项 | 状态 | 环境变量 | 发现 |", "|---|---:|---|---|"])
        for check in _as_list(preflight.get("checks")):
            if not isinstance(check, dict):
                continue
            lines.append(
                "| "
                f"{check.get('label')} | {check.get('status')} | "
                f"{', '.join(str(item) for item in _as_list(check.get('env_vars'))) or '-'} | "
                f"{'; '.join(str(item) for item in _as_list(check.get('findings'))) or '-'} |"
            )
    lines.extend(
        [
            "",
            "## 场景结果",
            "",
            "| 场景 | 状态 | Agent 分 | 报告 | RAG | 工具 | 运行时 | LLM 评审 | 快照 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for result in _as_list(summary.get("results")):
        if not isinstance(result, dict):
            continue
        gate = _as_dict(result.get("acceptance_gate"))
        dimensions = _as_dict(gate.get("dimensions"))
        supplements = _as_dict(gate.get("supplemental_dimensions"))

        def score(key: str) -> Any:
            return _as_dict(dimensions.get(key)).get("score", "-")

        result_status = gate.get("status") or ("passed" if gate.get("passed") else "failed")
        snapshot = result.get("snapshot_path") or gate.get("snapshot_path") or "-"
        llm_judge = _as_dict(supplements.get("llm_judge"))
        llm_judge_text = llm_judge.get("score", "-")
        if llm_judge.get("status"):
            llm_judge_text = f"{llm_judge_text} ({llm_judge.get('status')})"
        lines.append(
            "| "
            f"{result.get('scenario_id')} | {result_status} | {score('agent_quality')} | "
            f"{score('report_quality')} | {score('rag_quality')} | {score('tool_quality')} | "
            f"{score('runtime_quality')} | {llm_judge_text} | {snapshot} |"
        )

    llm_judge_rows: list[str] = []
    for result in _as_list(summary.get("results")):
        if not isinstance(result, dict):
            continue
        gate = _as_dict(result.get("acceptance_gate"))
        llm_judge = _as_dict(_as_dict(gate.get("supplemental_dimensions")).get("llm_judge"))
        if not llm_judge:
            continue
        findings = "; ".join(str(item) for item in _as_list(llm_judge.get("findings"))[:3]) or "-"
        llm_judge_rows.append(
            f"- {result.get('scenario_id')}: {llm_judge.get('status')} "
            f"score={llm_judge.get('score')} findings={findings}"
        )
    if llm_judge_rows:
        lines.extend(["", "## LLM-as-Judge（大模型评审）补充"])
        lines.extend(llm_judge_rows)

    lines.extend(["", "## 失败排查"])
    failures = _as_list(summary.get("failures"))
    if not failures:
        lines.append("- 未发现失败维度。")
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        findings = "; ".join(str(item) for item in _as_list(failure.get("findings"))[:3])
        lines.append(
            "- "
            f"{failure.get('scenario_id')} / {failure.get('dimension_label')}: {findings} "
            f"建议: {failure.get('suggestion')}"
        )
    degradations = _as_list(summary.get("degradations"))
    if degradations:
        lines.extend(["", "## 降级提示"])
    for degradation in degradations:
        if not isinstance(degradation, dict):
            continue
        findings = "; ".join(str(item) for item in _as_list(degradation.get("findings"))[:3])
        lines.append(
            "- "
            f"{degradation.get('scenario_id')} / {degradation.get('dimension_label')}: {findings} "
            f"建议: {degradation.get('suggestion')}"
        )
    lines.append("")
    return "\n".join(lines)


def write_acceptance_summary_files(
    summary: dict[str, Any],
    output_dir: Path,
    *,
    prefix: str = "acceptance-summary",
    created_at: datetime | None = None,
) -> dict[str, str]:
    """Write JSON and Markdown summary artifacts and return their paths."""

    output_dir.mkdir(parents=True, exist_ok=True)
    created = created_at or datetime.now(timezone.utc)
    timestamp = created.strftime("%Y%m%d-%H%M%S")
    safe_prefix = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in prefix)
    json_path = output_dir / f"{timestamp}-{safe_prefix}.json"
    markdown_path = output_dir / f"{timestamp}-{safe_prefix}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_acceptance_markdown(summary), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}
