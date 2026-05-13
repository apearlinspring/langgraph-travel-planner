import pytest

from app.evaluation.runtime_metrics import (
    RuntimeBudget,
    build_runtime_governance_summary,
    collect_runtime_metrics,
    estimate_token_count,
    evaluate_runtime_budget,
    evaluate_runtime_metrics,
    runtime_budget_from_dict,
)


def test_estimate_token_count_handles_ascii_and_chinese():
    assert estimate_token_count("") == 0
    assert estimate_token_count("hello world") >= 3
    assert estimate_token_count("旅行规划") >= 2


def test_collect_runtime_metrics_counts_events_and_tokens():
    events = [
        {"type": "tool_call", "tool": "query_transport_options", "elapsed_since_scenario_start": 0.2},
        {"type": "token", "content": "hello", "elapsed_since_scenario_start": 0.8},
        {"type": "report_data", "elapsed_since_scenario_start": 1.8},
        {
            "type": "turn_observability",
            "observability": {
                "tool_call_count": 1,
                "tool_failure_count": 0,
                "fallback_count": 0,
                "degradation_status": "ok",
                "estimated_input_tokens": 3,
                "estimated_output_tokens": 2,
                "estimated_total_tokens": 5,
            },
        },
    ]
    turns = [
        {
            "turn_index": 1,
            "user_message": "Plan a trip",
            "elapsed_seconds": 1.8,
            "tool_call_count": 1,
        }
    ]

    metrics = collect_runtime_metrics(
        events=events,
        turns=turns,
        assistant_text="hello",
        elapsed_seconds=1.8,
    )

    assert metrics.first_token_seconds == 0.8
    assert metrics.tool_call_count == 1
    assert metrics.turn_observability_event_count == 1
    assert metrics.report_event_count == 1
    assert metrics.estimated_total_tokens > 0
    assert metrics.tool_turn_elapsed_seconds == 1.8


def test_evaluate_runtime_metrics_passes_observable_snapshot():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "token", "content": "hello", "elapsed_since_scenario_start": 0.5},
            {"type": "report_data", "elapsed_since_scenario_start": 1.0},
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 0,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "ok",
                    "estimated_input_tokens": 1,
                    "estimated_output_tokens": 2,
                    "estimated_total_tokens": 3,
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 1.0}],
        assistant_text="hello",
        elapsed_seconds=1.0,
    )

    result = evaluate_runtime_metrics(metrics)

    assert result.passed is True
    assert result.normalized_score == 100
    assert result.budget_gate.passed is True
    assert result.governance_summary["status"] == "pass"


def test_evaluate_runtime_metrics_flags_missing_report_event():
    metrics = collect_runtime_metrics(
        events=[{"type": "token", "content": "hello", "elapsed_since_scenario_start": 0.5}],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 1.0}],
        assistant_text="hello",
        elapsed_seconds=1.0,
    )

    result = evaluate_runtime_metrics(metrics)

    assert result.passed is False
    assert any("No report_data event" in item for item in result.summary)


def test_runtime_budget_from_dict_overrides_thresholds():
    budget = runtime_budget_from_dict(
        {
            "max_total_elapsed_seconds": 120,
            "max_first_token_seconds": None,
            "max_tool_call_count": 3,
            "max_estimated_total_tokens": 5000,
            "max_error_event_count": 1,
        }
    )

    assert budget.max_total_elapsed_seconds == 120
    assert budget.max_first_token_seconds is None
    assert budget.max_tool_call_count == 3
    assert budget.max_estimated_total_tokens == 5000
    assert budget.max_error_event_count == 1


def test_evaluate_runtime_budget_flags_threshold_violations():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "tool_call", "tool": "query_transport_options"},
            {"type": "tool_call", "tool": "query_hotel_options"},
            {"type": "tool_audit", "tool": "query_hotel_options", "status": "failed"},
            {"type": "error", "message": "timeout"},
            {"type": "report_data"},
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 2,
                    "tool_failure_count": 1,
                    "fallback_count": 1,
                    "degradation_status": "failed",
                    "estimated_input_tokens": 1,
                    "estimated_output_tokens": 100,
                    "estimated_total_tokens": 101,
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 10, "tool_call_count": 2}],
        assistant_text="x" * 200,
        elapsed_seconds=10,
    )
    budget = RuntimeBudget(
        max_total_elapsed_seconds=5,
        max_first_token_seconds=1,
        max_tool_call_count=1,
        max_estimated_total_tokens=20,
        max_error_event_count=0,
    )

    gate = evaluate_runtime_budget(metrics, budget)
    result = evaluate_runtime_metrics(metrics, budget=budget)

    assert gate.passed is False
    assert result.passed is False
    assert any("Total elapsed seconds" in item for item in gate.violations)
    assert any("Tool call count" in item for item in gate.violations)
    assert any("Estimated total tokens" in item for item in gate.violations)
    assert any("Error event count" in item for item in gate.violations)


def test_runtime_governance_summary_explains_latency_cost_and_tools():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "tool_call", "tool": "query_transport_options", "turn_index": 1},
            {"type": "tool_call", "tool": "query_transport_options", "turn_index": 1},
            {"type": "token", "content": "hello", "elapsed_since_scenario_start": 8},
            {"type": "report_data"},
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 2,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "ok",
                    "estimated_input_tokens": 6,
                    "estimated_output_tokens": 150,
                    "estimated_total_tokens": 156,
                },
            },
        ],
        turns=[
            {
                "turn_index": 1,
                "user_message": "Plan a detailed trip",
                "elapsed_seconds": 9,
                "tool_call_count": 2,
            }
        ],
        assistant_text="hello" * 120,
        elapsed_seconds=10,
    )
    budget = RuntimeBudget(
        max_total_elapsed_seconds=10,
        max_first_token_seconds=10,
        max_tool_call_count=2,
        max_estimated_total_tokens=180,
        max_error_event_count=0,
    )

    summary = build_runtime_governance_summary(
        metrics,
        budget=budget,
        tool_counts={"query_transport_options": 2},
        redundant_calls=["turn-1:query_transport_options called 2 times"],
    )

    assert summary["status"] == "pass"
    assert summary["slow_path"]["findings"]
    assert summary["cost_risk"]["findings"]
    assert summary["tool_usage"]["redundant_calls"] == [
        "turn-1:query_transport_options called 2 times"
    ]


def test_collect_runtime_metrics_uses_turn_observability_for_hidden_tool_pressure():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "tool_call", "tool": "query_hotel_options"},
            {
                "type": "tool_audit",
                "tool": "query_hotel_options",
                "status": "degraded",
                "degraded": True,
            },
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 3,
                    "tool_failure_count": 1,
                    "fallback_count": 1,
                    "degradation_status": "degraded",
                    "estimated_input_tokens": 10,
                    "estimated_output_tokens": 20,
                    "estimated_total_tokens": 30,
                },
            },
            {"type": "report_data"},
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 1.0}],
        assistant_text="ok",
        elapsed_seconds=1.0,
    )

    assert metrics.tool_call_count == 3
    assert metrics.tool_failure_count == 1
    assert metrics.fallback_count == 1
    assert metrics.degraded_event_count == 1


def test_duplicate_loop_guard_skip_is_recoverable_runtime_signal():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "tool_call", "tool": "query_transport_options", "turn_index": 1},
            {
                "type": "tool_audit",
                "tool": "query_transport_options",
                "status": "skipped",
                "error_type": "duplicate_tool_call_same_turn",
            },
            {"type": "report_data"},
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 1,
                    "tool_failure_count": 1,
                    "fallback_count": 0,
                    "degradation_status": "degraded",
                    "estimated_input_tokens": 4,
                    "estimated_output_tokens": 6,
                    "estimated_total_tokens": 10,
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "查交通", "elapsed_seconds": 2.0}],
        assistant_text="本轮已跳过重复交通查询。",
        elapsed_seconds=2.0,
    )

    assert metrics.tool_failure_count == 1
    assert metrics.error_event_count == 0
    assert metrics.degraded_event_count == 1


def test_collect_runtime_metrics_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        collect_runtime_metrics(
            events=None,  # type: ignore[arg-type]
            turns=[],
            assistant_text="",
            elapsed_seconds=0,
        )
