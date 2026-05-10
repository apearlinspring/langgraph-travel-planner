import pytest

from app.evaluation.runtime_metrics import (
    collect_runtime_metrics,
    estimate_token_count,
    evaluate_runtime_metrics,
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
    assert metrics.report_event_count == 1
    assert metrics.estimated_total_tokens > 0
    assert metrics.tool_turn_elapsed_seconds == 1.8


def test_evaluate_runtime_metrics_passes_observable_snapshot():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "token", "content": "hello", "elapsed_since_scenario_start": 0.5},
            {"type": "report_data", "elapsed_since_scenario_start": 1.0},
        ],
        turns=[{"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 1.0}],
        assistant_text="hello",
        elapsed_seconds=1.0,
    )

    result = evaluate_runtime_metrics(metrics)

    assert result.passed is True
    assert result.normalized_score == 100


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


def test_collect_runtime_metrics_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        collect_runtime_metrics(
            events=None,  # type: ignore[arg-type]
            turns=[],
            assistant_text="",
            elapsed_seconds=0,
        )
