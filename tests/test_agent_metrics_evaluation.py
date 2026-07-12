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
                "categories": ["price", "transport_schedule", "hotel_availability"],
            }
        }
    )

    result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text=(
            "酒店房间和688元/晚价格均为估算，需二次核验。\n"
            "- **大交通**：高铁班次余票及价格波动（建议提前 15-30 天核验）。\n"
            "- 高铁班次与余票：确认成都东⇌重庆北/西具体车次、时段与票价。\n"
            "- 酒店库存与房型：确认核心商圈舒适型酒店可订房型、含早权益与取消政策。"
        ),
    ).to_dict()

    assert result["passed"] is True
    assert result["unsupported_claims"]["unsupported_claim_count"] == 0


def test_agent_metrics_requires_successful_audit_evidence_for_dynamic_claims():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["price", "hotel_availability"],
            }
        }
    )
    events = [
        {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
        {
            "type": "tool_audit",
            "tool": "query_hotel_options",
            "status": "success",
            "semantic_status": "success",
            "evidence_type": "live_hotel_search",
            "turn_index": 1,
        },
    ]

    result = evaluate_agent_metrics(
        events,
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店房间已锁房，价格已确认为688元/晚。",
    ).to_dict()

    assert result["passed"] is True
    assert result["unsupported_claims"]["unsupported_claim_count"] == 0
    assert all(
        claim["support_reason"].startswith("supported_by_successful_tool_evidence:")
        for claim in result["unsupported_claims"]["claims"]
        if claim["source"] == "assistant_text"
    )


@pytest.mark.parametrize(
    ("status", "semantic_status"),
    [
        ("failed", "service_exception"),
        ("timeout", "service_exception"),
        ("degraded", "not_found"),
        ("degraded", "needs_verification"),
        ("success", "not_found"),
    ],
)
def test_agent_metrics_rejects_unsuccessful_or_empty_audit_evidence(
    status: str,
    semantic_status: str,
):
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["price", "hotel_availability"],
            }
        }
    )
    events = [
        {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
        {
            "type": "tool_audit",
            "tool": "query_hotel_options",
            "status": status,
            "semantic_status": semantic_status,
            "evidence_type": "live_hotel_search",
            "error_type": "empty_hotel_result" if semantic_status == "not_found" else None,
            "turn_index": 1,
        },
    ]

    result = evaluate_agent_metrics(
        events,
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店房间已锁房，价格已确认为688元/晚。",
    ).to_dict()

    assert result["passed"] is False
    assert result["unsupported_claims"]["unsupported_claim_count"] >= 1
    assert all(
        claim["support_reason"] == "missing_successful_compatible_tool_evidence"
        for claim in result["unsupported_claims"]["unsupported"]
        if claim["source"] == "assistant_text"
    )


def test_agent_metrics_rejects_called_tool_without_compatible_audit_type():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["hotel_availability"],
            }
        }
    )
    events = [
        {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
        {
            "type": "tool_audit",
            "tool": "query_hotel_options",
            "status": "success",
            "semantic_status": "success",
            "evidence_type": "live_transport_query",
            "turn_index": 1,
        },
    ]

    result = evaluate_agent_metrics(
        events,
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店房间已锁房。",
    ).to_dict()

    assert result["passed"] is False
    assert result["unsupported_claims"]["unsupported_claim_count"] >= 1


def test_agent_metrics_keeps_honest_verification_claim_with_failed_tool():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["price", "hotel_availability"],
            }
        }
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "query_hotel_options", "turn_index": 1},
            {
                "type": "tool_audit",
                "tool": "query_hotel_options",
                "status": "failed",
                "semantic_status": "service_exception",
                "evidence_type": "live_hotel_search",
                "turn_index": 1,
            },
        ],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店房间与688元/晚价格均待核验，当前没有锁房。",
    ).to_dict()

    assert result["passed"] is True
    assert result["unsupported_claims"]["unsupported_claim_count"] == 0


def test_agent_metrics_treats_approximate_number_as_estimate_not_booking_word():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["transport_schedule", "hotel_availability"],
            }
        }
    )

    approximate = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="高铁具体班次与余票价格，往返约300元/人。",
    ).to_dict()
    booking_word = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="酒店已锁房，后续需预约景点。",
    ).to_dict()

    assert approximate["unsupported_claims"]["unsupported_claim_count"] == 0
    assert booking_word["unsupported_claims"]["unsupported_claim_count"] == 1


def test_agent_metrics_inventory_includes_current_state_and_scenic_tools():
    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": "confirm_planning_mode_tool", "turn_index": 1},
            {"type": "tool_call", "tool": "record_evidence_bundle_tool", "turn_index": 1},
            {"type": "tool_call", "tool": "scenic_price_lookup_tool", "turn_index": 2},
        ],
        scenario=_scenario(),
        report_data=_valid_report_data(),
        assistant_text="景点票价为参考，出发前需二次核验。",
    ).to_dict()

    assert result["metric_values"]["tool_call_precision"] == 1.0
    assert result["observed"]["unexpected_tools"] == []


def test_agent_metrics_counts_real_fallback_tools_as_stage_not_precision_noise():
    fallback_tools = [
        "go_back_to_requirement",
        "go_back_to_destination",
        "go_back_to_transport",
        "go_back_to_accommodation",
        "go_back_to_food",
        "go_back_to_itinerary",
        "go_back_to_budget",
    ]
    scenario = _scenario(
        metric_expectations={
            "tools": {"strict": True},
            "stage": {
                "strict": True,
                "expected_transition_tools": fallback_tools,
            },
        }
    )

    result = evaluate_agent_metrics(
        [
            {"type": "tool_call", "tool": tool, "turn_index": index}
            for index, tool in enumerate(fallback_tools, start=1)
        ],
        scenario=scenario,
        report_data=_valid_report_data(),
    ).to_dict()

    assert result["passed"] is True
    assert result["metric_values"]["tool_call_precision"] == 1.0
    assert result["metric_values"]["stage_transition_accuracy"] == 1.0
    assert result["observed"]["unexpected_tools"] == []
    assert result["observed"]["transition_tools"] == fallback_tools


def test_agent_metrics_preserves_markdown_verification_section_context():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["transport_schedule", "inventory", "hotel_availability"],
            }
        }
    )

    verification_list = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text=(
            "### 二次核验项（出发前需确认）\n"
            "- 高铁班次与余票：具体车次、票价、是否需提前抢票\n"
            "- 酒店库存与价格：实际可订房型、含早权益、连住优惠"
        ),
    ).to_dict()
    confirmed_list = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text="### 已确认方案\n- 酒店库存充足，房型可订。",
    ).to_dict()
    bold_verification_list = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text=(
            "**出发前二次核验清单**\n"
            "- 高铁班次与票价：具体车次余票与实时票价\n"
            "- 酒店房态与权益：实际可订房型、是否含早及取消政策"
        ),
    ).to_dict()

    assert verification_list["unsupported_claims"]["unsupported_claim_count"] == 0
    assert bold_verification_list["unsupported_claims"]["unsupported_claim_count"] == 0
    assert confirmed_list["unsupported_claims"]["unsupported_claim_count"] >= 1


def test_agent_metrics_keeps_verification_context_across_paragraphs_and_table_rows():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["transport_schedule"],
            }
        }
    )

    result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text=(
            "### 二次核验项\n"
            "以下内容将在出发前复核。\n"
            "| 项目 | 当前记录 |\n"
            "| --- | --- |\n"
            "| 交通 | 返程高铁班次已确认有票。 |"
        ),
    ).to_dict()

    assert result["unsupported_claims"]["unsupported_claim_count"] == 0
    assert any(
        claim["support_reason"] == "qualified_by_verification_section"
        for claim in result["unsupported_claims"]["claims"]
    )


def test_agent_metrics_ends_verification_context_at_next_markdown_heading():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["transport_schedule"],
            }
        }
    )

    result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=_valid_report_data(),
        assistant_text=(
            "### 二次核验项\n"
            "返程交通将在出发前复核。\n"
            "### 已确认方案\n"
            "返程高铁班次已确认有票。"
        ),
    ).to_dict()

    assert result["unsupported_claims"]["unsupported_claim_count"] == 1
    assert result["unsupported_claims"]["unsupported"][0]["support_reason"] == (
        "missing_successful_compatible_tool_evidence"
    )


def test_agent_metrics_preserves_structured_verification_field_context():
    scenario = _scenario(
        metric_expectations={
            "unsupported_claims": {
                "strict": True,
                "categories": ["transport_schedule", "inventory", "hotel_availability"],
            }
        }
    )
    verification_report = _valid_report_data()
    verification_report["tool_audit_summary"] = {
        "pending_checks": ["返程班次真实余票和票价。"],
    }
    confirmed_report = _valid_report_data()
    confirmed_report["transport"] = {
        "summary": "返程高铁班次已确认有票。",
    }

    verification_result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=verification_report,
    ).to_dict()
    confirmed_result = evaluate_agent_metrics(
        [],
        scenario=scenario,
        report_data=confirmed_report,
    ).to_dict()

    assert verification_result["unsupported_claims"]["unsupported_claim_count"] == 0
    assert any(
        claim["support_reason"] == "qualified_by_structured_verification_field"
        for claim in verification_result["unsupported_claims"]["claims"]
    )
    assert confirmed_result["unsupported_claims"]["unsupported_claim_count"] >= 1


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
