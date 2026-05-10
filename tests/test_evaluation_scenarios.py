import json
from pathlib import Path

import pytest

from app.evaluation.scenarios import get_scenario, load_scenarios


def test_load_default_scenarios_has_expected_coverage():
    scenarios = load_scenarios()
    scenario_ids = {scenario.id for scenario in scenarios}
    modes = {scenario.expected_mode for scenario in scenarios}
    tags = {tag for scenario in scenarios for tag in scenario.tags}

    assert len(scenarios) >= 8
    assert len(scenario_ids) == len(scenarios)
    assert {"free_planning", "agency_plan"}.issubset(modes)
    assert {"free", "agency", "edge", "hotel", "budget"}.issubset(tags)


def test_get_scenario_returns_catalog_entry():
    scenario = get_scenario("agency_couple_relaxed")

    assert scenario.expected_mode == "agency_plan"
    assert scenario.min_score >= 80
    assert "agency" in scenario.tags
    assert scenario.prompt


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
