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
from app.core.observability import TurnObservation, build_observability_context
from app.utils.security import redact_sensitive_data


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


def test_recovered_transient_error_does_not_fail_runtime_budget():
    metrics = collect_runtime_metrics(
        events=[
            {
                "type": "error",
                "error_type": "APIConnectionError",
                "recovered": True,
                "recovery_category": "transient_llm_api_connection",
            },
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
        turns=[
            {"turn_index": 1, "user_message": "Plan", "elapsed_seconds": 0.4, "error": "APIConnectionError"},
            {"turn_index": 2, "user_message": "Continue", "elapsed_seconds": 0.6, "produced_report_data": True},
        ],
        assistant_text="hello",
        elapsed_seconds=1.0,
    )

    result = evaluate_runtime_metrics(metrics)

    assert metrics.error_event_count == 0
    assert metrics.recoverable_error_event_count == 1
    assert result.passed is True
    assert result.budget_gate.passed is True


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
            "max_tool_failure_count": 2,
            "max_tool_failure_ratio": 0.5,
            "max_fallback_count": 2,
        }
    )

    assert budget.max_total_elapsed_seconds == 120
    assert budget.max_first_token_seconds is None
    assert budget.max_tool_call_count == 3
    assert budget.max_estimated_total_tokens == 5000
    assert budget.max_error_event_count == 1
    assert budget.max_tool_failure_count == 2
    assert budget.max_tool_failure_ratio == 0.5
    assert budget.max_fallback_count == 2


def test_runtime_budget_blocks_failure_heavy_run_unless_scenario_explicitly_allows_it():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "token", "content": "hello", "elapsed_since_scenario_start": 0.5},
            {"type": "report_data", "elapsed_since_scenario_start": 1.0},
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 21,
                    "tool_failure_count": 13,
                    "fallback_count": 13,
                    "degradation_status": "degraded",
                    "estimated_input_tokens": 10,
                    "estimated_output_tokens": 20,
                    "estimated_total_tokens": 30,
                },
            },
        ],
        turns=[
            {
                "turn_index": 1,
                "user_message": "Plan with tool evidence",
                "elapsed_seconds": 1.0,
                "tool_call_count": 21,
            }
        ],
        assistant_text="hello",
        elapsed_seconds=1.0,
    )

    strict_gate = evaluate_runtime_budget(metrics)
    strict_result = evaluate_runtime_metrics(metrics)

    assert strict_gate.passed is False
    assert strict_result.passed is False
    assert strict_result.governance_summary["status"] == "fail"
    assert any("Tool failure count 13" in item for item in strict_gate.violations)
    assert any("Tool failure ratio 61.9%" in item for item in strict_gate.violations)
    assert any("Fallback count 13" in item for item in strict_gate.violations)

    fallback_scenario_budget = runtime_budget_from_dict(
        {
            "max_tool_failure_count": 16,
            "max_tool_failure_ratio": 1.0,
            "max_fallback_count": 16,
        }
    )

    assert evaluate_runtime_budget(metrics, fallback_scenario_budget).passed is True
    assert evaluate_runtime_metrics(metrics, budget=fallback_scenario_budget).passed is True


def test_runtime_budget_rejects_invalid_tool_failure_ratio():
    with pytest.raises(ValueError, match="max_tool_failure_ratio"):
        runtime_budget_from_dict({"max_tool_failure_ratio": 1.01})


@pytest.mark.parametrize(
    "field_name",
    [
        "max_total_elapsed_seconds",
        "max_first_token_seconds",
        "max_tool_turn_elapsed_seconds",
        "max_tool_failure_ratio",
        "warning_total_elapsed_ratio",
        "warning_first_token_ratio",
        "warning_tool_call_ratio",
        "warning_token_ratio",
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_runtime_budget_rejects_non_finite_float_thresholds(field_name, value):
    with pytest.raises(ValueError, match=field_name):
        runtime_budget_from_dict({field_name: value})


def test_runtime_budget_constructor_rejects_non_finite_thresholds():
    with pytest.raises(ValueError, match="max_tool_failure_ratio"):
        RuntimeBudget(max_tool_failure_ratio=float("nan"))


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
                    "tool_failure_count": 0,
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

    assert metrics.tool_failure_count == 0
    assert metrics.error_event_count == 0
    assert metrics.degraded_event_count == 1


def test_needs_verification_is_degraded_but_not_a_tool_failure_or_fallback():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "tool_call", "tool": "summarize_budget_tool"},
            {
                "type": "tool_audit",
                "tool": "summarize_budget_tool",
                "status": "degraded",
                "semantic_status": "needs_verification",
                "error_type": "mcp_result_requires_verification",
            },
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 1,
                    "tool_failure_count": 0,
                    "fallback_count": 0,
                    "degradation_status": "degraded",
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "汇总预算", "elapsed_seconds": 1.0}],
        assistant_text="预算结果待二次核验。",
        elapsed_seconds=1.0,
    )

    assert metrics.tool_failure_count == 0
    assert metrics.fallback_count == 0
    assert metrics.degraded_event_count == 1


def test_empty_result_semantics_override_raw_failed_status_as_fallback_only():
    events = [
        {"type": "tool_call", "tool": f"tool_{index}"}
        for index in range(4)
    ]
    events.extend(
        [
            {
                "type": "tool_audit",
                "status": "failed",
                "error_type": "empty_rag_result",
            },
            {
                "type": "tool_audit",
                "status": "failed",
                "error_type": "empty_mcp_result",
            },
            {
                "type": "tool_audit",
                "status": "failed",
                "error_type": "empty_transport_result",
            },
            {
                "type": "tool_audit",
                "status": "failed",
                "semantic_status": "not_found",
            },
        ]
    )

    metrics = collect_runtime_metrics(
        events=events,
        turns=[{"turn_index": 1, "user_message": "查询候选", "elapsed_seconds": 1.0}],
        assistant_text="暂未查到候选。",
        elapsed_seconds=1.0,
    )

    assert metrics.tool_failure_count == 0
    assert metrics.fallback_count == 4


def test_tool_audit_semantics_override_stale_turn_summary_counts():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "tool_call", "tool": "query_transport_options"},
            {
                "type": "tool_audit",
                "tool": "query_transport_options",
                "status": "failed",
                "error_type": "empty_transport_result",
                "semantic_status": "not_found",
            },
            {
                "type": "turn_observability",
                "observability": {
                    "tool_call_count": 1,
                    "tool_failure_count": 1,
                    "fallback_count": 1,
                    "degradation_status": "degraded",
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "查交通", "elapsed_seconds": 1.0}],
        assistant_text="暂未查到候选。",
        elapsed_seconds=1.0,
    )

    assert metrics.tool_failure_count == 0
    assert metrics.fallback_count == 1


def test_observability_error_count_fails_budget_without_sse_error_event():
    metrics = collect_runtime_metrics(
        events=[
            {"type": "token", "content": "ok", "elapsed_since_scenario_start": 0.1},
            {"type": "report_data"},
            {
                "type": "turn_observability",
                "observability": {
                    "error_event_count": 1,
                    "degradation_status": "failed",
                },
            },
        ],
        turns=[{"turn_index": 1, "user_message": "生成方案", "elapsed_seconds": 1.0}],
        assistant_text="ok",
        elapsed_seconds=1.0,
    )

    gate = evaluate_runtime_budget(metrics)

    assert metrics.error_event_count == 1
    assert gate.passed is False
    assert any("Error event count 1" in violation for violation in gate.violations)


def test_collect_runtime_metrics_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        collect_runtime_metrics(
            events=None,  # type: ignore[arg-type]
            turns=[],
            assistant_text="",
            elapsed_seconds=0,
        )


def test_redaction_keeps_runtime_token_metrics_readable():
    payload = redact_sensitive_data(
        {
            "estimated_total_tokens": 128,
            "average_estimated_total_tokens": 64,
            "access_token": "eyJabcdefgh.ijklmnopqr.stuvwxyz12",
            "message": "联系 test@example.com，api_key=sk-testvalue123456789",
        }
    )

    assert payload["estimated_total_tokens"] == 128
    assert payload["average_estimated_total_tokens"] == 64
    assert payload["access_token"] == "[REDACTED]"
    assert "test@example.com" not in str(payload)
    assert "sk-testvalue123456789" not in str(payload)


def test_turn_observability_internal_snapshot_redacts_identifiers():
    observation = TurnObservation(
        conversation_id="conversation-for-test@example.com",
        user_id="test@example.com",
        user_message="手机号 13800138000",
    )
    snapshot = observation.finish("completed")
    serialized = str(snapshot)

    assert snapshot["metadata"]["user_message_chars"] == len("手机号 13800138000")
    assert "test@example.com" not in serialized
    assert "13800138000" not in serialized


def test_turn_observability_defaults_to_named_step_and_mode():
    observation = TurnObservation(
        conversation_id="conversation-1",
        user_id="user-1",
        user_message="先帮我规划一下",
    )
    summary = observation.to_public_summary()
    context = build_observability_context(
        turn_id=observation.turn_id,
        current_step=None,
        planning_mode=None,
    )

    assert summary["step"] == "requirement_collection"
    assert summary["planning_mode"] == "pending_confirmation"
    assert context["current_step"] == "requirement_collection"
    assert context["planning_mode"] == "pending_confirmation"


def test_turn_observability_exposes_safe_error_count_without_error_type():
    observation = TurnObservation(
        conversation_id="conversation-1",
        user_id="user-1",
        user_message="生成方案",
    )
    observation.mark_error("ToolAuditPersistenceError")

    summary = observation.to_public_summary()

    assert summary["error_event_count"] == 1
    assert summary["degradation_status"] == "failed"
    assert "error_type" not in summary
