"""Scenario catalog helpers for evaluation regression checks."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.evaluation.runtime_metrics import runtime_budget_from_dict


SCENARIO_CATALOG_VERSION = "evaluation_scenarios.v1"
RAG_SCENARIO_CATALOG_VERSION = "rag_quality_scenarios.v1"
TOOL_SCENARIO_CATALOG_VERSION = "tool_call_scenarios.v1"
VALID_PLANNING_MODES = {"agency_plan", "free_planning"}
ACCEPTANCE_CORE_TAG = "acceptance-core"
ACCEPTANCE_SMOKE_TAG = "acceptance-smoke"
MIN_ACCEPTANCE_CORE_SCENARIOS = 8
MIN_ACCEPTANCE_SMOKE_SCENARIOS = 1
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
    requirements: dict[str, Any] = field(default_factory=dict)
    metric_expectations: dict[str, Any] = field(default_factory=dict)
    manual_review: dict[str, Any] = field(default_factory=dict)
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


def _as_optional_requirements(
    value: Any,
    *,
    scenario_id: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Scenario {scenario_id!r} field 'requirements' must be an object")

    requirements = dict(value)
    for field_name in ("real_llm", "real_mcp"):
        if field_name in requirements and not isinstance(requirements[field_name], bool):
            raise ValueError(f"Scenario {scenario_id!r} requirements.{field_name} must be a boolean")
    for field_name in ("mcp_servers", "external_apis"):
        if field_name in requirements:
            _as_optional_string_list(
                requirements[field_name],
                field_name=f"requirements.{field_name}",
                scenario_id=scenario_id,
            )
    if "notes" in requirements and not isinstance(requirements["notes"], str):
        raise ValueError(f"Scenario {scenario_id!r} requirements.notes must be a string")
    return requirements


def _as_optional_manual_review(
    value: Any,
    *,
    scenario_id: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Scenario {scenario_id!r} field 'manual_review' must be an object")

    manual_review = dict(value)
    for field_name in ("status", "reviewer_id", "reviewed_at", "decision", "notes"):
        if field_name in manual_review and not isinstance(manual_review[field_name], str):
            raise ValueError(f"Scenario {scenario_id!r} manual_review.{field_name} must be a string")
    for field_name in ("labels", "corrections"):
        if field_name in manual_review:
            _as_optional_string_list(
                manual_review[field_name],
                field_name=f"manual_review.{field_name}",
                scenario_id=scenario_id,
            )
    if "dataset_candidate" in manual_review and not isinstance(manual_review["dataset_candidate"], bool):
        raise ValueError(f"Scenario {scenario_id!r} manual_review.dataset_candidate must be a boolean")
    if "overall_score" in manual_review:
        score = manual_review["overall_score"]
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            raise ValueError(f"Scenario {scenario_id!r} manual_review.overall_score must be between 0 and 100")
    return manual_review


def _as_optional_metric_expectations(
    value: Any,
    *,
    scenario_id: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Scenario {scenario_id!r} field 'metric_expectations' must be an object")

    expectations = dict(value)
    intent = expectations.get("intent")
    if intent is not None:
        if not isinstance(intent, dict):
            raise ValueError(f"Scenario {scenario_id!r} metric_expectations.intent must be an object")
        if "expected" in intent and not isinstance(intent["expected"], str):
            raise ValueError(f"Scenario {scenario_id!r} metric_expectations.intent.expected must be a string")
        if "accepted" in intent:
            _as_optional_string_list(
                intent["accepted"],
                field_name="metric_expectations.intent.accepted",
                scenario_id=scenario_id,
            )

    tools = expectations.get("tools")
    if tools is not None:
        if not isinstance(tools, dict):
            raise ValueError(f"Scenario {scenario_id!r} metric_expectations.tools must be an object")
        for field_name in ("required", "optional", "allowed", "forbidden"):
            if field_name in tools:
                _as_optional_string_list(
                    tools[field_name],
                    field_name=f"metric_expectations.tools.{field_name}",
                    scenario_id=scenario_id,
                )
        if "strict" in tools and not isinstance(tools["strict"], bool):
            raise ValueError(f"Scenario {scenario_id!r} metric_expectations.tools.strict must be a boolean")

    stage = expectations.get("stage")
    if stage is not None:
        if not isinstance(stage, dict):
            raise ValueError(f"Scenario {scenario_id!r} metric_expectations.stage must be an object")
        if "expected_transition_tools" in stage:
            _as_optional_string_list(
                stage["expected_transition_tools"],
                field_name="metric_expectations.stage.expected_transition_tools",
                scenario_id=scenario_id,
            )
        if "strict" in stage and not isinstance(stage["strict"], bool):
            raise ValueError(f"Scenario {scenario_id!r} metric_expectations.stage.strict must be a boolean")

    unsupported_claims = expectations.get("unsupported_claims")
    if unsupported_claims is not None:
        if not isinstance(unsupported_claims, dict):
            raise ValueError(
                f"Scenario {scenario_id!r} metric_expectations.unsupported_claims must be an object"
            )
        if "strict" in unsupported_claims and not isinstance(unsupported_claims["strict"], bool):
            raise ValueError(
                f"Scenario {scenario_id!r} metric_expectations.unsupported_claims.strict must be a boolean"
            )
        if "categories" in unsupported_claims:
            _as_optional_string_list(
                unsupported_claims["categories"],
                field_name="metric_expectations.unsupported_claims.categories",
                scenario_id=scenario_id,
            )
    return expectations


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
        requirements=_as_optional_requirements(
            payload.get("requirements"),
            scenario_id=scenario_id,
        ),
        metric_expectations=_as_optional_metric_expectations(
            payload.get("metric_expectations"),
            scenario_id=scenario_id,
        ),
        manual_review=_as_optional_manual_review(
            payload.get("manual_review"),
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


def acceptance_core_scenarios(
    scenarios: Iterable[EvaluationScenario] | None = None,
    *,
    min_count: int = MIN_ACCEPTANCE_CORE_SCENARIOS,
) -> list[EvaluationScenario]:
    """Return the first-stage core acceptance scenarios in catalog order."""

    selected = [
        scenario
        for scenario in (list(scenarios) if scenarios is not None else load_scenarios())
        if ACCEPTANCE_CORE_TAG in scenario.tags
    ]
    if len(selected) < min_count:
        raise ValueError(
            "Acceptance core scenario set must contain at least "
            f"{min_count} scenarios tagged {ACCEPTANCE_CORE_TAG!r}; found {len(selected)}"
        )
    return selected


def _has_smoke_quote_coverage(scenario: EvaluationScenario) -> bool:
    tags = set(scenario.tags)
    searchable_text = " ".join(
        [
            scenario.name,
            scenario.prompt,
            scenario.notes,
            *scenario.focus,
            *scenario.tags,
        ]
    ).lower()
    has_agency_mode = scenario.expected_mode == "agency_plan" and "agency" in tags
    has_carefree_plan = "省心" in searchable_text or "agency" in searchable_text
    has_quote_signal = (
        "pricing" in tags
        or "budget" in tags
        or "报价" in searchable_text
        or "费用" in searchable_text
        or "quote" in searchable_text
    )
    return has_agency_mode and has_carefree_plan and has_quote_signal


def acceptance_smoke_scenarios(
    scenarios: Iterable[EvaluationScenario] | None = None,
    *,
    min_count: int = MIN_ACCEPTANCE_SMOKE_SCENARIOS,
) -> list[EvaluationScenario]:
    """Return the minimal live acceptance smoke scenarios in catalog order."""

    selected = [
        scenario
        for scenario in (list(scenarios) if scenarios is not None else load_scenarios())
        if ACCEPTANCE_SMOKE_TAG in scenario.tags
    ]
    if len(selected) < min_count:
        raise ValueError(
            "Acceptance smoke scenario set must contain at least "
            f"{min_count} scenarios tagged {ACCEPTANCE_SMOKE_TAG!r}; found {len(selected)}"
        )
    if not any(_has_smoke_quote_coverage(scenario) for scenario in selected):
        raise ValueError(
            "Acceptance smoke scenario set must include at least one agency-plan "
            "scenario covering a carefree plan and quote or budget explanation."
        )
    return selected


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
