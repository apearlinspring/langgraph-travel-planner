"""Offline Shadow / A-B experiment definitions and acceptance-run comparison."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.utils.security import REDACTED_VALUE, is_sensitive_key, redact_sensitive_text


EXPERIMENT_DEFINITION_VERSION = "shadow_ab_experiment.v1"
ACCEPTANCE_COMPARISON_VERSION = "shadow_ab_acceptance_comparison.v1"
EXPERIMENT_MODES = frozenset({"shadow-only", "offline-ab"})
MODE_DESCRIPTIONS = {
    "shadow-only": (
        "Candidate artifacts are observed next to the baseline for offline review only; "
        "no user-facing response or chat routing is affected."
    ),
    "offline-ab": (
        "Baseline and candidate are compared on fixed offline scenario sets or cohorts; "
        "the live chat router is not changed and no real user traffic is split."
    ),
}
SAFE_NUMERIC_METRIC_KEYS = frozenset(
    {
        "estimated_input_tokens",
        "estimated_output_tokens",
        "estimated_total_tokens",
        "average_estimated_total_tokens",
    }
)


def _redact_experiment_payload(value: Any, *, max_depth: int = 8) -> Any:
    if max_depth < 0:
        return REDACTED_VALUE
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if is_sensitive_key(text_key) and text_key not in SAFE_NUMERIC_METRIC_KEYS:
                redacted[text_key] = REDACTED_VALUE
            else:
                redacted[text_key] = _redact_experiment_payload(
                    item,
                    max_depth=max_depth - 1,
                )
        return redacted
    if isinstance(value, list):
        return [
            _redact_experiment_payload(item, max_depth=max_depth - 1)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _redact_experiment_payload(item, max_depth=max_depth - 1)
            for item in value
        )
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


@dataclass(frozen=True)
class ScenarioSet:
    """Scenario catalog slice used by one offline experiment."""

    scenario_set_id: str
    scenario_ids: tuple[str, ...] = ()
    source: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_set_id": self.scenario_set_id,
            "scenario_ids": list(self.scenario_ids),
            "source": self.source,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class ExperimentVariant:
    """One prompt, model profile, or tool-policy variant under comparison."""

    variant_id: str
    label: str | None = None
    model_profile: str | None = None
    prompt_ref: str | None = None
    tool_strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _redact_experiment_payload(asdict(self))


@dataclass(frozen=True)
class ExperimentDefinition:
    """Auditable offline experiment definition.

    The definition intentionally describes evaluation artifacts only. It does not
    configure runtime traffic routing.
    """

    experiment_id: str
    mode: str
    scenario_set: ScenarioSet
    baseline: ExperimentVariant
    candidate: ExperimentVariant
    description: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in EXPERIMENT_MODES:
            raise ValueError(
                "Experiment mode must be one of: " + ", ".join(sorted(EXPERIMENT_MODES))
            )
        if not self.experiment_id.strip():
            raise ValueError("experiment_id is required")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version": EXPERIMENT_DEFINITION_VERSION,
            "experiment_id": self.experiment_id,
            "mode": self.mode,
            "mode_description": MODE_DESCRIPTIONS[self.mode],
            "scenario_set": self.scenario_set.to_dict(),
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "description": self.description,
            "created_at": self.created_at,
            "online_traffic_split": False,
        }
        return _redact_experiment_payload(payload)


@dataclass(frozen=True)
class AcceptanceRunMetrics:
    """Compact, safe metrics extracted from one acceptance summary."""

    variant_id: str
    status: str
    passed: bool
    selected_count: int
    passed_count: int
    pass_rate: float
    average_agent_score: float | None
    status_counts: dict[str, int]
    failure_dimensions: dict[str, int]
    degradation_dimensions: dict[str, int]
    runtime_totals: dict[str, Any]
    tool_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return _redact_experiment_payload(asdict(self))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return int(value) if isinstance(value, int) else None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise TypeError("Expected a string or list of strings")
    return tuple(str(item) for item in value if str(item).strip())


def _counter_delta(
    baseline: dict[str, int],
    candidate: dict[str, int],
) -> dict[str, dict[str, int]]:
    keys = sorted(set(baseline) | set(candidate))
    return {
        key: {
            "baseline": baseline.get(key, 0),
            "candidate": candidate.get(key, 0),
            "delta": candidate.get(key, 0) - baseline.get(key, 0),
        }
        for key in keys
    }


def _safe_int_dict(value: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, raw_count in _as_dict(value).items():
        if not isinstance(key, str) or not key.strip():
            continue
        count = _as_int(raw_count)
        if count is None or count < 0:
            continue
        counts[key.strip()] = count
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _scenario_set_from_dict(payload: Any) -> ScenarioSet:
    if isinstance(payload, str):
        return ScenarioSet(scenario_set_id=payload)
    data = _as_dict(payload)
    scenario_set_id = str(data.get("scenario_set_id") or data.get("id") or "").strip()
    if not scenario_set_id:
        raise ValueError("scenario_set.scenario_set_id is required")
    return ScenarioSet(
        scenario_set_id=scenario_set_id,
        scenario_ids=_string_tuple(data.get("scenario_ids")),
        source=str(data["source"]) if data.get("source") is not None else None,
        tags=_string_tuple(data.get("tags")),
    )


def _variant_from_dict(payload: Any, *, default_id: str) -> ExperimentVariant:
    data = _as_dict(payload)
    variant_id = str(data.get("variant_id") or data.get("id") or default_id).strip()
    if not variant_id:
        raise ValueError("variant_id is required")
    return ExperimentVariant(
        variant_id=variant_id,
        label=str(data["label"]) if data.get("label") is not None else None,
        model_profile=(
            str(data["model_profile"]) if data.get("model_profile") is not None else None
        ),
        prompt_ref=str(data["prompt_ref"]) if data.get("prompt_ref") is not None else None,
        tool_strategy=(
            str(data["tool_strategy"]) if data.get("tool_strategy") is not None else None
        ),
        metadata=_redact_experiment_payload(_as_dict(data.get("metadata"))),
    )


def experiment_definition_from_dict(payload: dict[str, Any]) -> ExperimentDefinition:
    """Parse and validate a JSON experiment definition."""

    if not isinstance(payload, dict):
        raise TypeError("experiment definition payload must be a dictionary")
    return ExperimentDefinition(
        experiment_id=str(payload.get("experiment_id") or "").strip(),
        mode=str(payload.get("mode") or "shadow-only"),
        scenario_set=_scenario_set_from_dict(payload.get("scenario_set")),
        baseline=_variant_from_dict(payload.get("baseline"), default_id="baseline"),
        candidate=_variant_from_dict(payload.get("candidate"), default_id="candidate"),
        description=(
            str(payload["description"]) if payload.get("description") is not None else None
        ),
        created_at=str(payload["created_at"]) if payload.get("created_at") is not None else None,
    )


def build_experiment_definition(
    *,
    experiment_id: str,
    mode: str = "shadow-only",
    scenario_set_id: str = "acceptance-core",
    scenario_ids: list[str] | tuple[str, ...] | None = None,
    baseline_variant_id: str = "baseline",
    candidate_variant_id: str = "candidate",
    description: str | None = None,
) -> ExperimentDefinition:
    """Build a minimal experiment definition for local comparison scripts."""

    return ExperimentDefinition(
        experiment_id=experiment_id,
        mode=mode,
        scenario_set=ScenarioSet(
            scenario_set_id=scenario_set_id,
            scenario_ids=tuple(scenario_ids or ()),
        ),
        baseline=ExperimentVariant(variant_id=baseline_variant_id),
        candidate=ExperimentVariant(variant_id=candidate_variant_id),
        description=description,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _dimension_counts(records: Any) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in _as_list(records):
        dimension = _as_dict(record).get("dimension")
        if isinstance(dimension, str) and dimension.strip():
            counter[dimension.strip()] += 1
    return dict(sorted(counter.items()))


def _scenario_records(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for result in _as_list(summary.get("results")):
        if not isinstance(result, dict):
            continue
        scenario_id = str(result.get("scenario_id") or "").strip()
        if not scenario_id:
            continue
        gate = _as_dict(result.get("acceptance_gate"))
        dimensions = _as_dict(gate.get("dimensions"))
        agent_score = _as_float(result.get("agent_score"))
        if agent_score is None:
            agent_score = _as_float(_as_dict(dimensions.get("agent_quality")).get("score"))
        runtime_metrics = _as_dict(result.get("runtime_metrics"))
        tool_counts = _safe_int_dict(result.get("tool_counts"))
        tool_call_count = _as_int(runtime_metrics.get("tool_call_count"))
        if tool_call_count is None:
            tool_call_count = sum(tool_counts.values())
        elapsed = _as_float(runtime_metrics.get("total_elapsed_seconds"))
        if elapsed is None:
            elapsed = _as_float(result.get("elapsed_seconds"))
        records[scenario_id] = {
            "scenario_id": scenario_id,
            "status": str(gate.get("status") or result.get("status") or "unknown"),
            "passed": bool(gate.get("passed", result.get("passed", False))),
            "agent_score": agent_score,
            "elapsed_seconds": elapsed,
            "tool_call_count": tool_call_count,
            "estimated_total_tokens": _as_int(runtime_metrics.get("estimated_total_tokens")),
            "failure_dimensions": sorted(_dimension_counts(gate.get("failures"))),
            "degradation_dimensions": sorted(_dimension_counts(gate.get("degradations"))),
        }
    return records


def _runtime_totals_from_results(results: list[Any]) -> dict[str, Any]:
    totals = {
        "elapsed_seconds": 0.0,
        "tool_call_count": 0,
        "tool_failure_count": 0,
        "fallback_count": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_total_tokens": 0,
    }
    elapsed_count = 0
    token_count = 0
    tool_counts: dict[str, int] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        metrics = _as_dict(result.get("runtime_metrics"))
        result_tool_counts = _safe_int_dict(result.get("tool_counts"))
        elapsed = _as_float(metrics.get("total_elapsed_seconds"))
        if elapsed is None:
            elapsed = _as_float(result.get("elapsed_seconds"))
        if elapsed is not None:
            totals["elapsed_seconds"] += elapsed
            elapsed_count += 1
        if _as_int(metrics.get("tool_call_count")) is None:
            totals["tool_call_count"] += sum(result_tool_counts.values())
        for key in (
            "tool_call_count",
            "tool_failure_count",
            "fallback_count",
            "estimated_input_tokens",
            "estimated_output_tokens",
            "estimated_total_tokens",
        ):
            value = _as_int(metrics.get(key))
            if value is not None:
                totals[key] += value
                if key == "estimated_total_tokens":
                    token_count += 1
        for tool, count in result_tool_counts.items():
            tool_counts[tool] = tool_counts.get(tool, 0) + count
    totals["elapsed_seconds"] = round(float(totals["elapsed_seconds"]), 3)
    totals["average_elapsed_seconds"] = (
        round(float(totals["elapsed_seconds"]) / elapsed_count, 3) if elapsed_count else None
    )
    totals["average_estimated_total_tokens"] = (
        round(float(totals["estimated_total_tokens"]) / token_count, 2) if token_count else None
    )
    totals["tool_counts"] = dict(sorted(tool_counts.items(), key=lambda item: (-item[1], item[0])))
    return totals


def _runtime_totals(summary: dict[str, Any]) -> dict[str, Any]:
    totals = _as_dict(summary.get("runtime_totals"))
    if not totals:
        totals = _runtime_totals_from_results(_as_list(summary.get("results")))
    safe_totals = {
        "elapsed_seconds": _as_float(totals.get("elapsed_seconds")) or 0.0,
        "average_elapsed_seconds": _as_float(totals.get("average_elapsed_seconds")),
        "tool_call_count": _as_int(totals.get("tool_call_count")) or 0,
        "tool_failure_count": _as_int(totals.get("tool_failure_count")) or 0,
        "fallback_count": _as_int(totals.get("fallback_count")) or 0,
        "estimated_input_tokens": _as_int(totals.get("estimated_input_tokens")) or 0,
        "estimated_output_tokens": _as_int(totals.get("estimated_output_tokens")) or 0,
        "estimated_total_tokens": _as_int(totals.get("estimated_total_tokens")) or 0,
        "average_estimated_total_tokens": _as_float(
            totals.get("average_estimated_total_tokens")
        ),
        "tool_counts": _safe_int_dict(totals.get("tool_counts") or summary.get("tool_counts")),
    }
    return safe_totals


def summarize_acceptance_run(
    summary: dict[str, Any],
    *,
    variant_id: str,
) -> AcceptanceRunMetrics:
    """Extract compact comparison metrics from one acceptance run summary."""

    if not isinstance(summary, dict):
        raise TypeError("acceptance summary must be a dictionary")
    results = _as_list(summary.get("results"))
    selected_count = _as_int(summary.get("selected_count")) or len(results)
    passed_count = _as_int(summary.get("passed_count"))
    if passed_count is None:
        passed_count = sum(1 for result in results if _as_dict(result).get("passed") is True)
    pass_rate = round(passed_count / selected_count, 4) if selected_count else 0.0
    average_score = _as_float(summary.get("average_agent_score"))
    if average_score is None:
        scores = [
            record["agent_score"]
            for record in _scenario_records(summary).values()
            if isinstance(record.get("agent_score"), (int, float))
        ]
        average_score = round(sum(scores) / len(scores), 2) if scores else None
    runtime_totals = _runtime_totals(summary)
    return AcceptanceRunMetrics(
        variant_id=variant_id,
        status=str(summary.get("status") or "unknown"),
        passed=bool(summary.get("passed")),
        selected_count=selected_count,
        passed_count=passed_count,
        pass_rate=pass_rate,
        average_agent_score=average_score,
        status_counts=_safe_int_dict(summary.get("status_counts")),
        failure_dimensions=_dimension_counts(summary.get("failures")),
        degradation_dimensions=_dimension_counts(summary.get("degradations")),
        runtime_totals=runtime_totals,
        tool_counts=_safe_int_dict(runtime_totals.get("tool_counts") or summary.get("tool_counts")),
    )


def _numeric_delta(candidate: Any, baseline: Any, *, digits: int = 3) -> float | None:
    candidate_number = _as_float(candidate)
    baseline_number = _as_float(baseline)
    if candidate_number is None or baseline_number is None:
        return None
    return round(candidate_number - baseline_number, digits)


def _scenario_comparisons(
    baseline_summary: dict[str, Any],
    candidate_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_records = _scenario_records(baseline_summary)
    candidate_records = _scenario_records(candidate_summary)
    ordered_ids = list(baseline_records)
    ordered_ids.extend(scenario_id for scenario_id in candidate_records if scenario_id not in baseline_records)
    comparisons = []
    for scenario_id in ordered_ids:
        baseline = baseline_records.get(scenario_id)
        candidate = candidate_records.get(scenario_id)
        regressions: list[str] = []
        improvements: list[str] = []
        if baseline and candidate:
            if baseline["passed"] and not candidate["passed"]:
                regressions.append("passed_to_failed")
            if not baseline["passed"] and candidate["passed"]:
                improvements.append("failed_to_passed")
            score_delta = _numeric_delta(candidate.get("agent_score"), baseline.get("agent_score"), digits=2)
            if score_delta is not None and score_delta <= -5:
                regressions.append("score_drop_ge_5")
            elif score_delta is not None and score_delta >= 5:
                improvements.append("score_gain_ge_5")
        else:
            score_delta = None
            if baseline and not candidate:
                regressions.append("missing_candidate_result")
            if candidate and not baseline:
                improvements.append("new_candidate_result")
        comparisons.append(
            {
                "scenario_id": scenario_id,
                "baseline": baseline,
                "candidate": candidate,
                "deltas": {
                    "agent_score": score_delta,
                    "elapsed_seconds": _numeric_delta(
                        _as_dict(candidate).get("elapsed_seconds"),
                        _as_dict(baseline).get("elapsed_seconds"),
                    ),
                    "tool_call_count": _numeric_delta(
                        _as_dict(candidate).get("tool_call_count"),
                        _as_dict(baseline).get("tool_call_count"),
                    ),
                    "estimated_total_tokens": _numeric_delta(
                        _as_dict(candidate).get("estimated_total_tokens"),
                        _as_dict(baseline).get("estimated_total_tokens"),
                    ),
                },
                "regressions": regressions,
                "improvements": improvements,
            }
        )
    return comparisons


def _verdict(
    *,
    baseline: AcceptanceRunMetrics,
    candidate: AcceptanceRunMetrics,
    scenario_comparisons: list[dict[str, Any]],
) -> str:
    if candidate.status in {"blocked", "skipped"}:
        return "blocked"
    has_scenario_regression = any(record["regressions"] for record in scenario_comparisons)
    increased_failures = any(
        item["delta"] > 0
        for item in _counter_delta(
            baseline.failure_dimensions,
            candidate.failure_dimensions,
        ).values()
    )
    if candidate.pass_rate < baseline.pass_rate or has_scenario_regression or increased_failures:
        return "regressed"
    score_delta = _numeric_delta(candidate.average_agent_score, baseline.average_agent_score, digits=2)
    if candidate.pass_rate > baseline.pass_rate or (score_delta is not None and score_delta > 0):
        return "improved"
    return "neutral"


def compare_acceptance_summaries(
    baseline_summary: dict[str, Any],
    candidate_summary: dict[str, Any],
    *,
    experiment: ExperimentDefinition | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare two acceptance run summaries without storing raw tool payloads."""

    if experiment is None:
        experiment = build_experiment_definition(experiment_id="ad-hoc-shadow-ab")
    baseline = summarize_acceptance_run(
        baseline_summary,
        variant_id=experiment.baseline.variant_id,
    )
    candidate = summarize_acceptance_run(
        candidate_summary,
        variant_id=experiment.candidate.variant_id,
    )
    scenario_comparisons = _scenario_comparisons(baseline_summary, candidate_summary)
    verdict = _verdict(
        baseline=baseline,
        candidate=candidate,
        scenario_comparisons=scenario_comparisons,
    )
    runtime_deltas = {
        "pass_rate_points": round((candidate.pass_rate - baseline.pass_rate) * 100, 2),
        "average_agent_score": _numeric_delta(
            candidate.average_agent_score,
            baseline.average_agent_score,
            digits=2,
        ),
        "elapsed_seconds": _numeric_delta(
            candidate.runtime_totals.get("elapsed_seconds"),
            baseline.runtime_totals.get("elapsed_seconds"),
        ),
        "tool_call_count": _numeric_delta(
            candidate.runtime_totals.get("tool_call_count"),
            baseline.runtime_totals.get("tool_call_count"),
        ),
        "estimated_total_tokens": _numeric_delta(
            candidate.runtime_totals.get("estimated_total_tokens"),
            baseline.runtime_totals.get("estimated_total_tokens"),
        ),
    }
    comparison = {
        "version": ACCEPTANCE_COMPARISON_VERSION,
        "created_at": (created_at or datetime.now(timezone.utc)).isoformat(),
        "experiment": experiment.to_dict(),
        "mode": experiment.mode,
        "mode_description": MODE_DESCRIPTIONS[experiment.mode],
        "online_traffic_split": False,
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
        "deltas": runtime_deltas,
        "failure_dimension_delta": _counter_delta(
            baseline.failure_dimensions,
            candidate.failure_dimensions,
        ),
        "degradation_dimension_delta": _counter_delta(
            baseline.degradation_dimensions,
            candidate.degradation_dimensions,
        ),
        "tool_call_delta": _counter_delta(baseline.tool_counts, candidate.tool_counts),
        "scenario_comparisons": scenario_comparisons,
        "verdict": verdict,
        "passed": verdict in {"neutral", "improved"} and candidate.status == "passed",
        "safety": {
            "stores_raw_tool_payloads": False,
            "stores_user_traffic_assignments": False,
            "redaction": "credentials_and_common_pii",
        },
    }
    return _redact_experiment_payload(comparison)


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    """Render a concise Markdown summary for human review."""

    experiment = _as_dict(comparison.get("experiment"))
    baseline = _as_dict(comparison.get("baseline"))
    candidate = _as_dict(comparison.get("candidate"))
    deltas = _as_dict(comparison.get("deltas"))
    lines = [
        "# Shadow / A-B 验收比较",
        "",
        f"- experiment_id: {experiment.get('experiment_id')}",
        f"- mode: {comparison.get('mode')}",
        f"- verdict: {comparison.get('verdict')}",
        f"- online_traffic_split: {comparison.get('online_traffic_split')}",
        f"- baseline: {baseline.get('variant_id')} ({baseline.get('status')})",
        f"- candidate: {candidate.get('variant_id')} ({candidate.get('status')})",
        "",
        "## 汇总",
        "",
        "| 指标 | baseline | candidate | delta |",
        "|---|---:|---:|---:|",
        (
            f"| 通过率 | {round(float(baseline.get('pass_rate') or 0) * 100, 2)}% | "
            f"{round(float(candidate.get('pass_rate') or 0) * 100, 2)}% | "
            f"{deltas.get('pass_rate_points')} pp |"
        ),
        (
            f"| 平均 Agent 分 | {baseline.get('average_agent_score')} | "
            f"{candidate.get('average_agent_score')} | {deltas.get('average_agent_score')} |"
        ),
        (
            "| 总耗时（秒） | "
            f"{_as_dict(baseline.get('runtime_totals')).get('elapsed_seconds')} | "
            f"{_as_dict(candidate.get('runtime_totals')).get('elapsed_seconds')} | "
            f"{deltas.get('elapsed_seconds')} |"
        ),
        (
            "| 工具调用 | "
            f"{_as_dict(baseline.get('runtime_totals')).get('tool_call_count')} | "
            f"{_as_dict(candidate.get('runtime_totals')).get('tool_call_count')} | "
            f"{deltas.get('tool_call_count')} |"
        ),
        (
            "| 估算 token（文本令牌） | "
            f"{_as_dict(baseline.get('runtime_totals')).get('estimated_total_tokens')} | "
            f"{_as_dict(candidate.get('runtime_totals')).get('estimated_total_tokens')} | "
            f"{deltas.get('estimated_total_tokens')} |"
        ),
        "",
        "## 失败维度变化",
    ]
    failure_delta = _as_dict(comparison.get("failure_dimension_delta"))
    if not failure_delta:
        lines.append("- 无失败维度。")
    else:
        for dimension, record in failure_delta.items():
            data = _as_dict(record)
            lines.append(
                f"- {dimension}: {data.get('baseline')} -> {data.get('candidate')} "
                f"(delta {data.get('delta')})"
            )

    lines.extend(["", "## 工具调用变化"])
    tool_delta = _as_dict(comparison.get("tool_call_delta"))
    if not tool_delta:
        lines.append("- 无工具调用计数。")
    else:
        for tool, record in tool_delta.items():
            data = _as_dict(record)
            lines.append(
                f"- {tool}: {data.get('baseline')} -> {data.get('candidate')} "
                f"(delta {data.get('delta')})"
            )

    scenario_changes = [
        record
        for record in _as_list(comparison.get("scenario_comparisons"))
        if _as_list(_as_dict(record).get("regressions"))
        or _as_list(_as_dict(record).get("improvements"))
    ]
    lines.extend(["", "## 场景变化"])
    if not scenario_changes:
        lines.append("- 无显著场景级变化。")
    else:
        for record in scenario_changes:
            item = _as_dict(record)
            lines.append(
                f"- {item.get('scenario_id')}: "
                f"regressions={item.get('regressions') or []}, "
                f"improvements={item.get('improvements') or []}"
            )
    lines.append("")
    return "\n".join(lines)
