"""Scenario catalog helpers for evaluation regression checks."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluation.runtime_metrics import runtime_budget_from_dict


SCENARIO_CATALOG_VERSION = "evaluation_scenarios.v1"
RAG_SCENARIO_CATALOG_VERSION = "rag_quality_scenarios.v1"
TOOL_SCENARIO_CATALOG_VERSION = "tool_call_scenarios.v1"
VALID_PLANNING_MODES = {"agency_plan", "free_planning"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_FILE = PROJECT_ROOT / "data" / "evaluation" / "report_quality_scenarios.json"
DEFAULT_RAG_SCENARIO_FILE = PROJECT_ROOT / "data" / "evaluation" / "rag_quality_scenarios.json"
DEFAULT_TOOL_CALL_SCENARIO_FILE = PROJECT_ROOT / "data" / "evaluation" / "tool_call_scenarios.json"


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
    runtime_budget: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagQualityScenario:
    """One fixed scenario for RAG evidence quality checks."""

    id: str
    name: str
    prompt: str
    expected_mode: str
    min_score: float
    required_categories: list[str]
    focus: list[str]
    tags: list[str]
    required_evidence_count: int = 3
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCallScenario:
    """One fixed scenario for tool-call quality checks."""

    id: str
    name: str
    prompt: str
    expected_mode: str
    min_score: float
    expected_tools: list[str]
    forbidden_tools: list[str]
    focus: list[str]
    tags: list[str]
    max_duplicate_calls: int = 1
    requires_fallback: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_string_list(value: Any, *, field_name: str, scenario_id: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a non-empty string list")
    return value


def _as_optional_string_list(
    value: Any,
    *,
    field_name: str,
    scenario_id: str,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a string list")
    return value


def _as_optional_runtime_budget(
    value: Any,
    *,
    scenario_id: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Scenario {scenario_id!r} field 'runtime_budget' must be an object")
    runtime_budget_from_dict(value)
    return dict(value)


def _validate_scenario_id(payload: dict[str, Any]) -> str:
    scenario_id = payload.get("id")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("Scenario id must be a non-empty string")
    return scenario_id


def _validate_expected_mode(payload: dict[str, Any], scenario_id: str) -> str:
    expected_mode = payload.get("expected_mode")
    if expected_mode not in VALID_PLANNING_MODES:
        raise ValueError(f"Scenario {scenario_id!r} has invalid expected_mode: {expected_mode!r}")
    return expected_mode


def _validate_min_score(payload: dict[str, Any], scenario_id: str) -> float:
    min_score = payload.get("min_score")
    if not isinstance(min_score, (int, float)) or not 0 <= float(min_score) <= 100:
        raise ValueError(f"Scenario {scenario_id!r} min_score must be between 0 and 100")
    return float(min_score)


def _require_string_fields(payload: dict[str, Any], scenario_id: str, fields: tuple[str, ...]) -> None:
    for field_name in fields:
        if not isinstance(payload.get(field_name), str) or not payload[field_name].strip():
            raise ValueError(f"Scenario {scenario_id!r} field {field_name!r} must be a non-empty string")


def _load_catalog(path: Path, version: str) -> list[dict[str, Any]]:
    catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    if catalog.get("version") != version:
        raise ValueError(f"Scenario catalog version must be {version}")

    raw_scenarios = catalog.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("Scenario catalog must contain a non-empty scenarios list")
    if not all(isinstance(item, dict) for item in raw_scenarios):
        raise ValueError("Scenario catalog items must be objects")
    return raw_scenarios


def _validate_unique_ids(scenarios: list[Any]) -> None:
    ids = [scenario.id for scenario in scenarios]
    duplicate_ids = sorted({scenario_id for scenario_id in ids if ids.count(scenario_id) > 1})
    if duplicate_ids:
        raise ValueError(f"Duplicate scenario ids: {', '.join(duplicate_ids)}")


def _scenario_from_dict(payload: dict[str, Any]) -> EvaluationScenario:
    scenario_id = _validate_scenario_id(payload)
    expected_mode = _validate_expected_mode(payload, scenario_id)
    min_score = _validate_min_score(payload, scenario_id)
    _require_string_fields(payload, scenario_id, ("name", "category", "prompt"))

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
        runtime_budget=_as_optional_runtime_budget(
            payload.get("runtime_budget"),
            scenario_id=scenario_id,
        ),
        notes=str(payload.get("notes") or "").strip(),
    )


def _rag_scenario_from_dict(payload: dict[str, Any]) -> RagQualityScenario:
    scenario_id = _validate_scenario_id(payload)
    expected_mode = _validate_expected_mode(payload, scenario_id)
    min_score = _validate_min_score(payload, scenario_id)
    _require_string_fields(payload, scenario_id, ("name", "prompt"))

    required_count = payload.get("required_evidence_count", 3)
    if not isinstance(required_count, int) or required_count < 1:
        raise ValueError(f"Scenario {scenario_id!r} required_evidence_count must be a positive integer")

    return RagQualityScenario(
        id=scenario_id,
        name=payload["name"].strip(),
        prompt=payload["prompt"].strip(),
        expected_mode=expected_mode,
        min_score=min_score,
        required_categories=_as_string_list(
            payload.get("required_categories"),
            field_name="required_categories",
            scenario_id=scenario_id,
        ),
        focus=_as_string_list(payload.get("focus"), field_name="focus", scenario_id=scenario_id),
        tags=_as_string_list(payload.get("tags"), field_name="tags", scenario_id=scenario_id),
        required_evidence_count=required_count,
        notes=str(payload.get("notes") or "").strip(),
    )


def _tool_call_scenario_from_dict(payload: dict[str, Any]) -> ToolCallScenario:
    scenario_id = _validate_scenario_id(payload)
    expected_mode = _validate_expected_mode(payload, scenario_id)
    min_score = _validate_min_score(payload, scenario_id)
    _require_string_fields(payload, scenario_id, ("name", "prompt"))

    max_duplicate_calls = payload.get("max_duplicate_calls", 1)
    if not isinstance(max_duplicate_calls, int) or max_duplicate_calls < 0:
        raise ValueError(f"Scenario {scenario_id!r} max_duplicate_calls must be a non-negative integer")
    requires_fallback = payload.get("requires_fallback", False)
    if not isinstance(requires_fallback, bool):
        raise ValueError(f"Scenario {scenario_id!r} requires_fallback must be a boolean")

    return ToolCallScenario(
        id=scenario_id,
        name=payload["name"].strip(),
        prompt=payload["prompt"].strip(),
        expected_mode=expected_mode,
        min_score=min_score,
        expected_tools=_as_optional_string_list(
            payload.get("expected_tools"),
            field_name="expected_tools",
            scenario_id=scenario_id,
        ),
        forbidden_tools=_as_optional_string_list(
            payload.get("forbidden_tools"),
            field_name="forbidden_tools",
            scenario_id=scenario_id,
        ),
        focus=_as_string_list(payload.get("focus"), field_name="focus", scenario_id=scenario_id),
        tags=_as_string_list(payload.get("tags"), field_name="tags", scenario_id=scenario_id),
        max_duplicate_calls=max_duplicate_calls,
        requires_fallback=requires_fallback,
        notes=str(payload.get("notes") or "").strip(),
    )


def load_scenarios(path: Path | None = None) -> list[EvaluationScenario]:
    """Load and validate the evaluation scenario catalog."""

    scenario_path = path or DEFAULT_SCENARIO_FILE
    scenarios = [
        _scenario_from_dict(item)
        for item in _load_catalog(scenario_path, SCENARIO_CATALOG_VERSION)
    ]
    _validate_unique_ids(scenarios)
    return scenarios


def load_rag_quality_scenarios(path: Path | None = None) -> list[RagQualityScenario]:
    """Load and validate the RAG evidence quality scenario catalog."""

    scenario_path = path or DEFAULT_RAG_SCENARIO_FILE
    scenarios = [
        _rag_scenario_from_dict(item)
        for item in _load_catalog(scenario_path, RAG_SCENARIO_CATALOG_VERSION)
    ]
    _validate_unique_ids(scenarios)
    return scenarios


def load_tool_call_scenarios(path: Path | None = None) -> list[ToolCallScenario]:
    """Load and validate the tool-call quality scenario catalog."""

    scenario_path = path or DEFAULT_TOOL_CALL_SCENARIO_FILE
    scenarios = [
        _tool_call_scenario_from_dict(item)
        for item in _load_catalog(scenario_path, TOOL_SCENARIO_CATALOG_VERSION)
    ]
    _validate_unique_ids(scenarios)
    return scenarios


def get_scenario(scenario_id: str, path: Path | None = None) -> EvaluationScenario:
    """Return one scenario by id."""

    for scenario in load_scenarios(path):
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(f"Unknown evaluation scenario: {scenario_id}")


def get_rag_quality_scenario(scenario_id: str, path: Path | None = None) -> RagQualityScenario:
    """Return one RAG quality scenario by id."""

    for scenario in load_rag_quality_scenarios(path):
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(f"Unknown RAG quality scenario: {scenario_id}")


def get_tool_call_scenario(scenario_id: str, path: Path | None = None) -> ToolCallScenario:
    """Return one tool-call quality scenario by id."""

    for scenario in load_tool_call_scenarios(path):
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(f"Unknown tool-call quality scenario: {scenario_id}")
