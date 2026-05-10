"""Scenario catalog helpers for report quality regression checks."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCENARIO_CATALOG_VERSION = "evaluation_scenarios.v1"
VALID_PLANNING_MODES = {"agency_plan", "free_planning"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_FILE = PROJECT_ROOT / "data" / "evaluation" / "report_quality_scenarios.json"


@dataclass(frozen=True)
class EvaluationScenario:
    """One fixed regression scenario for end-to-end report evaluation."""

    id: str
    name: str
    category: str
    prompt: str
    expected_mode: str
    min_score: float
    focus: list[str]
    tags: list[str]
    followups: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_string_list(value: Any, *, field_name: str, scenario_id: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a non-empty string list")
    return value


def _scenario_from_dict(payload: dict[str, Any]) -> EvaluationScenario:
    scenario_id = payload.get("id")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("Scenario id must be a non-empty string")

    expected_mode = payload.get("expected_mode")
    if expected_mode not in VALID_PLANNING_MODES:
        raise ValueError(f"Scenario {scenario_id!r} has invalid expected_mode: {expected_mode!r}")

    min_score = payload.get("min_score")
    if not isinstance(min_score, (int, float)) or not 0 <= float(min_score) <= 100:
        raise ValueError(f"Scenario {scenario_id!r} min_score must be between 0 and 100")

    required_string_fields = ("name", "category", "prompt")
    for field_name in required_string_fields:
        if not isinstance(payload.get(field_name), str) or not payload[field_name].strip():
            raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a non-empty string")

    return EvaluationScenario(
        id=scenario_id,
        name=payload["name"].strip(),
        category=payload["category"].strip(),
        prompt=payload["prompt"].strip(),
        expected_mode=expected_mode,
        min_score=float(min_score),
        focus=_as_string_list(payload.get("focus"), field_name="focus", scenario_id=scenario_id),
        tags=_as_string_list(payload.get("tags"), field_name="tags", scenario_id=scenario_id),
        followups=(
            _as_string_list(payload.get("followups"), field_name="followups", scenario_id=scenario_id)
            if payload.get("followups") is not None
            else []
        ),
        notes=str(payload.get("notes") or "").strip(),
    )


def load_scenarios(path: Path | None = None) -> list[EvaluationScenario]:
    """Load and validate the evaluation scenario catalog."""

    scenario_path = path or DEFAULT_SCENARIO_FILE
    catalog = json.loads(scenario_path.read_text(encoding="utf-8"))
    if catalog.get("version") != SCENARIO_CATALOG_VERSION:
        raise ValueError(f"Scenario catalog version must be {SCENARIO_CATALOG_VERSION}")

    raw_scenarios = catalog.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("Scenario catalog must contain a non-empty scenarios list")

    scenarios = [_scenario_from_dict(item) for item in raw_scenarios]
    ids = [scenario.id for scenario in scenarios]
    duplicate_ids = sorted({scenario_id for scenario_id in ids if ids.count(scenario_id) > 1})
    if duplicate_ids:
        raise ValueError(f"Duplicate scenario ids: {', '.join(duplicate_ids)}")
    return scenarios


def get_scenario(scenario_id: str, path: Path | None = None) -> EvaluationScenario:
    """Return one scenario by id."""

    for scenario in load_scenarios(path):
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(f"Unknown evaluation scenario: {scenario_id}")
