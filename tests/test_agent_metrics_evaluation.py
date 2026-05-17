import json
from pathlib import Path

import pytest

from app.evaluation.agent_metrics import evaluate_agent_metrics
from app.evaluation.scenarios import EvaluationScenario, load_scenarios
from tests.test_report_quality_evaluation import _valid_report_data


def _scenario(
    scenario_id: str = "metric_case",
    *,
    mode: str = "agency_plan",
    tags: list[str] | None = None,
    metric_expectations: dict | None = None,
) -> EvaluationScenario:
    return EvaluationScenario(
        id=scenario_id,
        name=f"Scenario {scenario_id}",
        category=mode,
        prompt="Plan a trip",
        expected_mode=mode,
        min_score=80,
        focus=["metrics"],
        tags=tags or ["agency"],
        metric_expectations=metric_expectations or {},
    )


def test_agent_metrics_scores_required_tool_precision_and_recall():
    scenario = _scenario(
        mode="free_planning",
        tags=["edge", "hotel", "fallback"],
        metric_expectations={
            "intent": {"expected": "hotel_query", "accepted": ["free_planning", "hotel_query"]},
            "tools": {
                "required": ["query_hotel_options"],
                "optional": ["query_destination_info"],
            },
        },
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "query_destination_info", "turn_index": 1},
            {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
        ],
        scenario=scenario,
        report_data=_valid_report_data(mode="free_planning"),
        assistant_text="酒店价格为估算，需二次核验。",
    ).to_dict()

    assert result["passed"] is True
    assert result["metric_values"]["tool_call_precision"] == 1.0
    assert result["metric_values"]["tool_call_recall"] == 1.0
    assert "hotel_query" in result["observed"]["intents"]


def test_agent_metrics_fails_missing_required_tool_recall():
    scenario = _scenario(
        mode="free_planning",
        tags=["edge", "transport", "fallback"],
        metric_expectations={
            "tools": {"required": ["query_transport_options"]},
        },
    )

    result = evaluate_agent_metrics(
        [{"type": "tool_call", "tool": "query_destination_info", "turn_index": 1}],
        scenario=scenario,
        report_data=_valid_report_data(mode="free_planning"),
    ).to_dict()

    assert result["passed"] is False
    assert result["metric_values"]["tool_call_recall"] == 0.0
    assert any("Missing required tool calls" in item for item in result["summary"])


def test_agent_metrics_flags_forbidden_state_tool_even_when_ignored_for_precision():
    scenario = _scenario(
        mode="free_planning",
        tags=["edge", "hotel", "fallback"],
        metric_expectations={
            "tools": {
                "required": ["query_hotel_options"],
                "forbidden": ["select_accommodation_tool"],
            },
        },
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "select_accommodation_tool", "turn_index": 1},
            {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
        ],
        scenario=scenario,
        report_data=_valid_report_data(mode="free_planning"),
    ).to_dict()

    assert result["passed"] is False
    assert "select_accommodation_tool" in result["observed"]["called_forbidden_tools"]
    assert any("Forbidden tool calls" in item for item in result["summary"])


def test_agent_metrics_scores_stage_transition_order():
    scenario = _scenario(
        metric_expectations={
            "stage": {
                "expected_transition_tools": [
                    "record_requirement_tool",
                    "select_destination_tool",
                    "generate_order_tool",
                ]
            }
        }
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "record_requirement_tool", "turn_index": 1},
            {"type": "tool_call", "tool": "query_destination_info", "turn_index": 2},
            {"type": "tool_call", "tool": "select_destination_tool", "turn_index": 3},
            {"type": "tool_call", "tool": "generate_order_tool", "turn_index": 4},
        ],
        scenario=scenario,
        report_data=_valid_report_data(),
    ).to_dict()

    assert result["passed"] is True
    assert result["metric_values"]["stage_transition_accuracy"] == 1.0


def test_agent_metrics_keeps_non_strict_stage_mismatch_as_finding_only():
    scenario = _scenario(
        metric_expectations={
            "stage": {
                "strict": False,
                "expected_transition_tools": [
                    "record_requirement_tool",
                    "select_destination_tool",
                    "select_food_tool",
                    "generate_order_tool",
                ],
            }
        }
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "record_requirement_tool", "turn_index": 1},
            {"type": "tool_call", "tool": "select_destination_tool", "turn_index": 2},
            {"type": "tool_call", "tool": "generate_order_tool", "turn_index": 3},
        ],
        scenario=scenario,
        report_data=_valid_report_data(),
    ).to_dict()

    assert result["passed"] is True
    assert result["metric_values"]["stage_transition_accuracy"] == 0.5
    assert any(
        criterion["name"] == "stage_transition_accuracy" and criterion["findings"]
        for criterion in result["criteria"]
    )


def test_agent_metrics_fails_strict_stage_mismatch():
    scenario = _scenario(
        metric_expectations={
            "stage": {
                "strict": True,
                "expected_transition_tools": [
                    "record_requirement_tool",
                    "select_destination_tool",
                    "select_food_tool",
                    "generate_order_tool",
                ],
            }
        }
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "record_requirement_tool", "turn_index": 1},
            {"type": "tool_call", "tool": "select_destination_tool", "turn_index": 2},
            {"type": "tool_call", "tool": "generate_order_tool", "turn_index": 3},
        ],
        scenario=scenario,
        report_data=_valid_report_data(),
    ).to_dict()

    assert result["passed"] is False
    assert any("Stage transition tool sequence" in item for item in result["summary"])


def test_agent_metrics_flags_unsupported_dynamic_claims():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["price", "hotel_availability"],
            }
        }
    )

    result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店房间已锁房，价格已确认为688元/晚。",
    ).to_dict()

    assert result["passed"] is False
    assert result["unsupported_claims"]["unsupported_claim_count"] >= 1
    assert result["metric_values"]["unsupported_claim_rate"] > 0


def test_agent_metrics_allows_qualified_dynamic_claims():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["price", "hotel_availability"],
            }
        }
    )

    result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店房间和688元/晚价格均为估算，需二次核验。",
    ).to_dict()

    assert result["passed"] is True
    assert result["unsupported_claims"]["unsupported_claim_count"] == 0


def test_scenario_catalog_accepts_metric_expectations(tmp_path: Path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            {
                "version": "evaluation_scenarios.v1",
                "scenarios": [
                    {
                        "id": "metric_catalog",
                        "name": "Metric catalog",
                        "category": "agency_plan",
                        "prompt": "Plan",
                        "expected_mode": "agency_plan",
                        "min_score": 80,
                        "focus": ["metrics"],
                        "tags": ["agency"],
                        "metric_expectations": {
                            "intent": {"expected": "agency_plan"},
                            "tools": {"required": ["query_destination_info"]},
                            "stage": {"expected_transition_tools": ["generate_order_tool"]},
                            "unsupported_claims": {"strict": True, "categories": ["price"]},
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scenario = load_scenarios(path)[0]

    assert scenario.metric_expectations["intent"]["expected"] == "agency_plan"


def test_scenario_catalog_rejects_invalid_metric_expectations(tmp_path: Path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            {
                "version": "evaluation_scenarios.v1",
                "scenarios": [
                    {
                        "id": "bad_metric_catalog",
                        "name": "Bad metric catalog",
                        "category": "agency_plan",
                        "prompt": "Plan",
                        "expected_mode": "agency_plan",
                        "min_score": 80,
                        "focus": ["metrics"],
                        "tags": ["agency"],
                        "metric_expectations": {"tools": {"required": "query_destination_info"}},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="metric_expectations.tools.required"):
        load_scenarios(path)
