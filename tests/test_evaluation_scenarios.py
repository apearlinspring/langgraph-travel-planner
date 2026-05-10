import json
from pathlib import Path

import pytest

from app.evaluation.scenarios import (
    get_rag_quality_scenario,
    get_scenario,
    get_tool_call_scenario,
    load_rag_quality_scenarios,
    load_scenarios,
    load_tool_call_scenarios,
)


def test_load_default_scenarios_has_expected_coverage():
    scenarios = load_scenarios()
    scenario_ids = {scenario.id for scenario in scenarios}
    modes = {scenario.expected_mode for scenario in scenarios}
    tags = {tag for scenario in scenarios for tag in scenario.tags}

    assert len(scenarios) >= 10
    assert len(scenario_ids) == len(scenarios)
    assert {"free_planning", "agency_plan"}.issubset(modes)
    assert {"free", "agency", "edge", "hotel", "budget", "transport", "risk"}.issubset(tags)


def test_get_scenario_returns_catalog_entry():
    scenario = get_scenario("agency_couple_relaxed")

    assert scenario.expected_mode == "agency_plan"
    assert scenario.min_score >= 80
    assert "agency" in scenario.tags
    assert scenario.prompt


def test_load_scenarios_accepts_runtime_budget_contract():
    scenario = get_scenario("long_context_revision")

    assert scenario.runtime_budget["max_total_elapsed_seconds"] == 1200
    assert scenario.runtime_budget["max_estimated_total_tokens"] == 180000


def test_load_rag_quality_scenarios_has_business_coverage():
    scenarios = load_rag_quality_scenarios()
    scenario_ids = {scenario.id for scenario in scenarios}
    required_categories = {
        category
        for scenario in scenarios
        for category in scenario.required_categories
    }
    modes = {scenario.expected_mode for scenario in scenarios}

    assert len(scenarios) >= 6
    assert len(scenario_ids) == len(scenarios)
    assert {"agency_plan", "free_planning"}.issubset(modes)
    assert {"products", "sop", "pricing", "risk", "report"}.issubset(required_categories)


def test_load_tool_call_scenarios_has_tool_governance_coverage():
    scenarios = load_tool_call_scenarios()
    scenario_ids = {scenario.id for scenario in scenarios}
    expected_tools = {tool for scenario in scenarios for tool in scenario.expected_tools}
    tags = {tag for scenario in scenarios for tag in scenario.tags}

    assert len(scenarios) >= 6
    assert len(scenario_ids) == len(scenarios)
    assert {"query_transport_options", "query_hotel_options", "query_destination_info"}.issubset(expected_tools)
    assert {"fallback", "redundancy", "budget"}.issubset(tags)


def test_get_specialized_scenarios_return_catalog_entries():
    rag_scenario = get_rag_quality_scenario("rag_agency_quote_policy")
    tool_scenario = get_tool_call_scenario("tool_transport_train_lookup")

    assert rag_scenario.expected_mode == "agency_plan"
    assert "pricing" in rag_scenario.required_categories
    assert tool_scenario.expected_tools == ["query_transport_options"]
    assert "query_hotel_options" in tool_scenario.forbidden_tools


def test_load_scenarios_rejects_duplicate_ids(tmp_path: Path):
    catalog = {
        "version": "evaluation_scenarios.v1",
        "scenarios": [
            {
                "id": "duplicate",
                "name": "One",
                "category": "free_planning",
                "prompt": "Plan a trip",
                "expected_mode": "free_planning",
                "min_score": 80,
                "focus": ["contract"],
                "tags": ["free"],
            },
            {
                "id": "duplicate",
                "name": "Two",
                "category": "agency_plan",
                "prompt": "Plan another trip",
                "expected_mode": "agency_plan",
                "min_score": 80,
                "focus": ["contract"],
                "tags": ["agency"],
            },
        ],
    }
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate scenario ids"):
        load_scenarios(path)


def test_load_scenarios_rejects_invalid_mode(tmp_path: Path):
    catalog = {
        "version": "evaluation_scenarios.v1",
        "scenarios": [
            {
                "id": "bad_mode",
                "name": "Bad mode",
                "category": "edge_case",
                "prompt": "Plan a trip",
                "expected_mode": "supplier_mode",
                "min_score": 80,
                "focus": ["contract"],
                "tags": ["edge"],
            }
        ],
    }
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid expected_mode"):
        load_scenarios(path)
