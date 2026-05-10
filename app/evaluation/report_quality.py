"""Deterministic quality checks for structured travel reports."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.reports.contracts import (
    REPORT_VERSION,
    REQUIRED_REPORT_SECTION_IDS,
    REQUIRED_REPORT_TOP_LEVEL_KEYS,
)

REQUIRED_TOP_LEVEL_KEYS = REQUIRED_REPORT_TOP_LEVEL_KEYS
REQUIRED_SECTION_IDS = REQUIRED_REPORT_SECTION_IDS

REQUIRED_BUDGET_GROUPS = {
    "transport",
    "accommodation",
    "food",
    "attractions",
    "other",
}

REQUIRED_AGENCY_CATEGORIES = {"products", "sop", "pricing", "risk", "report"}

VERIFY_KEYWORDS = (
    "verify",
    "confirm",
    "\u590d\u6838",
    "\u6838\u5b9e",
    "\u786e\u8ba4",
)
WEATHER_KEYWORDS = (
    "weather",
    "Plan B",
    "\u5929\u6c14",
    "\u4e0b\u96e8",
    "\u96e8",
)
BOOKING_KEYWORDS = (
    "ticket",
    "hotel",
    "booking",
    "\u4ea4\u901a",
    "\u9152\u5e97",
    "\u9884\u7ea6",
    "\u7968\u4ef7",
)


@dataclass
class CriterionResult:
    """Single rubric item in the report quality score."""

    name: str
    score: float
    max_score: float
    findings: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return round(self.score / self.max_score, 4)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ratio"] = self.ratio
        return payload


@dataclass
class ReportEvaluationResult:
    """Full deterministic evaluation result for one structured report."""

    total_score: float
    max_score: float
    normalized_score: float
    grade: str
    passed: bool
    criteria: list[CriterionResult]
    summary: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "grade": self.grade,
            "passed": self.passed,
            "summary": self.summary,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
        }


def _score(condition: bool, points: float, findings: list[str], message: str) -> float:
    if condition:
        return points
    findings.append(message)
    return 0.0


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower_text = text.lower()
    return any(keyword.lower() in lower_text for keyword in keywords)


def _expected_days(report_data: dict[str, Any]) -> int | None:
    overview = _as_dict(report_data.get("overview"))
    duration = str(overview.get("duration") or "")
    match = re.search("(\\d+)\\s*(?:\u5929|\u65e5|days?|d)", duration, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _section_ids(report_data: dict[str, Any]) -> set[str]:
    return {
        str(section.get("id"))
        for section in _as_list(report_data.get("sections"))
        if isinstance(section, dict) and section.get("id")
    }


def _route_point_label(point: Any) -> str:
    if isinstance(point, dict):
        for key in ("label", "name", "title", "address"):
            value = point.get(key)
            if _has_text(value):
                return value.strip()
        return ""
    return str(point).strip()


def _route_points(route: dict[str, Any]) -> list[str]:
    raw_points = route.get("route_points") or route.get("points") or []
    return [label for point in raw_points if (label := _route_point_label(point))]


def _budget_group(key: str) -> str:
    normalized = key.lower().strip()
    if normalized in {"misc", "other", "contingency", "buffer"}:
        return "other"
    if normalized in {"scenic", "sights", "experience", "attraction", "attractions"}:
        return "attractions"
    if normalized in {"hotel", "lodging", "accommodation"}:
        return "accommodation"
    if normalized in {"meal", "meals", "food", "dining"}:
        return "food"
    if normalized in {"traffic", "transport", "transportation"}:
        return "transport"
    return normalized


def _criterion_structure(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    missing_keys = sorted(REQUIRED_TOP_LEVEL_KEYS - set(report_data))
    score += _score(
        not missing_keys,
        7,
        findings,
        f"Missing top-level fields: {', '.join(missing_keys)}",
    )
    score += _score(
        report_data.get("version") == REPORT_VERSION,
        4,
        findings,
        f"Report version must be {REPORT_VERSION}",
    )

    overview = _as_dict(report_data.get("overview"))
    overview_ready = all(
        _has_text(overview.get(key))
        for key in ("route_label", "duration", "people")
    )
    score += _score(
        overview_ready,
        5,
        findings,
        "Overview must include route_label, duration, and people",
    )

    missing_sections = sorted(REQUIRED_SECTION_IDS - _section_ids(report_data))
    score += _score(
        not missing_sections,
        4,
        findings,
        f"Missing export sections: {', '.join(missing_sections)}",
    )
    return CriterionResult("structure_contract", score, 20, findings)


def _criterion_itinerary_and_map(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    itinerary = _as_list(report_data.get("itinerary"))
    map_routes = _as_list(report_data.get("map_routes"))
    expected_days = _expected_days(report_data)

    score += _score(bool(itinerary), 3, findings, "Missing itinerary list")
    if expected_days:
        score += _score(
            len(itinerary) == expected_days,
            4,
            findings,
            f"Itinerary day count {len(itinerary)} does not match duration {expected_days}",
        )
    else:
        score += _score(
            len(itinerary) >= 1,
            4,
            findings,
            "Could not parse expected day count from overview.duration",
        )

    rich_days = 0
    routed_days = 0
    for day in itinerary:
        if not isinstance(day, dict):
            continue
        has_daily_content = (
            _has_text(day.get("title"))
            and (
                len(_as_list(day.get("time_blocks"))) >= 2
                or len(_as_list(day.get("activities"))) >= 2
            )
        )
        rich_days += 1 if has_daily_content else 0
        route = _as_dict(day.get("route"))
        routed_days += 1 if len(_route_points(route)) >= 2 and _has_text(route.get("summary")) else 0

    score += _score(
        rich_days == len(itinerary) and bool(itinerary),
        5,
        findings,
        "Some itinerary days lack title and detailed activities/time blocks",
    )
    score += _score(
        routed_days == len(itinerary) and bool(itinerary),
        4,
        findings,
        "Some itinerary days lack visual route nodes",
    )
    score += _score(
        len(map_routes) == len(itinerary) and bool(map_routes),
        4,
        findings,
        "map_routes count must match itinerary day count",
    )
    return CriterionResult("itinerary_map_readiness", score, 20, findings)


def _criterion_budget(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    budget = _as_dict(report_data.get("budget"))
    budget_items = _as_list(budget.get("items"))
    item_groups = {
        _budget_group(str(item.get("key") or item.get("category") or ""))
        for item in budget_items
        if isinstance(item, dict)
    }
    budget_confidence = _as_dict(report_data.get("budget_confidence"))

    score += _score(
        isinstance(budget.get("total"), (int, float)) and budget.get("total") > 0,
        4,
        findings,
        "Budget total must be a positive number",
    )
    score += _score(
        isinstance(budget.get("per_person"), (int, float)) and budget.get("per_person") > 0,
        2,
        findings,
        "Budget per_person must be a positive number",
    )
    score += _score(
        REQUIRED_BUDGET_GROUPS.issubset(item_groups),
        5,
        findings,
        f"Missing budget groups: {', '.join(sorted(REQUIRED_BUDGET_GROUPS - item_groups))}",
    )
    score += _score(
        bool(budget_items)
        and all(
            isinstance(item, dict)
            and _has_text(item.get("label"))
            and isinstance(item.get("amount"), (int, float))
            and _has_text(item.get("basis"))
            for item in budget_items
        ),
        4,
        findings,
        "Some budget items lack label, amount, or basis",
    )
    score += _score(
        _has_text(budget_confidence.get("level"))
        and (
            _as_list(budget_confidence.get("estimated_items"))
            or _as_list(budget_confidence.get("confirmed_items"))
        )
        and _as_list(budget_confidence.get("verification_items")),
        5,
        findings,
        "Budget confidence must include level, item status, and verification items",
    )
    return CriterionResult("budget_explainability", score, 20, findings)


def _criterion_risk(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    risks = [str(item) for item in _as_list(report_data.get("risks"))]
    adjustments = [str(item) for item in _as_list(report_data.get("adjustment_options"))]
    risk_text = "\n".join(risks)

    score += _score(len(risks) >= 4, 5, findings, "Risk reminders should contain at least 4 items")
    score += _score(
        _text_contains_any(risk_text, VERIFY_KEYWORDS)
        and _text_contains_any(risk_text, WEATHER_KEYWORDS)
        and _text_contains_any(risk_text, BOOKING_KEYWORDS),
        5,
        findings,
        "Risk reminders should cover verification, weather/Plan B, and booking/transport/hotel risks",
    )
    score += _score(
        len(adjustments) >= 2,
        5,
        findings,
        "Adjustment options should contain at least 2 items",
    )
    return CriterionResult("risk_and_adjustment", score, 15, findings)


def _criterion_agency_alignment(
    report_data: dict[str, Any],
    expected_mode: str | None,
) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    agency_context = _as_dict(report_data.get("agency_context"))
    categories = _as_dict(agency_context.get("categories"))
    category_keys = set(categories)
    highlights = _as_list(agency_context.get("highlights"))
    mode = agency_context.get("mode")

    score += _score(
        agency_context.get("source_type") == "agency_internal",
        3,
        findings,
        "agency_context.source_type must be agency_internal",
    )
    score += _score(
        mode in {"agency_plan", "free_planning"},
        3,
        findings,
        "agency_context.mode must be agency_plan or free_planning",
    )
    if expected_mode:
        score += _score(
            mode == expected_mode,
            4,
            findings,
            f"agency_context.mode={mode!r} does not match expected {expected_mode!r}",
        )
    else:
        score += 4 if mode else 0
    score += _score(
        len(highlights) >= 3,
        2,
        findings,
        "agency_context.highlights should contain at least 3 items",
    )
    score += _score(
        REQUIRED_AGENCY_CATEGORIES.issubset(category_keys),
        3,
        findings,
        f"Missing agency categories: {', '.join(sorted(REQUIRED_AGENCY_CATEGORIES - category_keys))}",
    )
    return CriterionResult("agency_business_alignment", score, 15, findings)


def _criterion_frontend_export(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    map_routes = [_as_dict(route) for route in _as_list(report_data.get("map_routes"))]
    itinerary = [_as_dict(day) for day in _as_list(report_data.get("itinerary"))]
    section_ids = _section_ids(report_data)

    score += _score(
        all(route.get("map_label") and len(_route_points(route)) >= 2 for route in map_routes)
        and bool(map_routes),
        4,
        findings,
        "Map routes must include map_label and at least 2 route points",
    )
    score += _score(
        [(_as_dict(day.get("route")).get("summary")) for day in itinerary]
        == [route.get("summary") for route in map_routes]
        and bool(itinerary),
        3,
        findings,
        "Daily route summaries must align with map_routes summaries",
    )
    score += _score(
        {"map_routes", "budget", "risk"}.issubset(section_ids),
        3,
        findings,
        "Export sections must include map_routes, budget, and risk",
    )
    return CriterionResult("frontend_export_readiness", score, 10, findings)


def _grade(normalized_score: float) -> str:
    if normalized_score >= 90:
        return "A"
    if normalized_score >= 80:
        return "B"
    if normalized_score >= 70:
        return "C"
    if normalized_score >= 60:
        return "D"
    return "F"


def evaluate_report_quality(
    report_data: dict[str, Any],
    *,
    expected_mode: str | None = None,
    pass_threshold: float = 80.0,
) -> ReportEvaluationResult:
    """Evaluate a structured travel report on a 100-point deterministic rubric."""

    if not isinstance(report_data, dict):
        raise TypeError("report_data must be a dictionary")

    criteria = [
        _criterion_structure(report_data),
        _criterion_itinerary_and_map(report_data),
        _criterion_budget(report_data),
        _criterion_risk(report_data),
        _criterion_agency_alignment(report_data, expected_mode),
        _criterion_frontend_export(report_data),
    ]
    total_score = round(sum(criterion.score for criterion in criteria), 2)
    max_score = round(sum(criterion.max_score for criterion in criteria), 2)
    normalized_score = round((total_score / max_score) * 100, 2) if max_score else 0.0
    failed_findings = [
        f"{criterion.name}: {finding}"
        for criterion in criteria
        for finding in criterion.findings
    ]
    summary = (
        ["Structured report satisfies the current quality gate."]
        if normalized_score >= pass_threshold and not failed_findings
        else failed_findings[:10]
    )
    return ReportEvaluationResult(
        total_score=total_score,
        max_score=max_score,
        normalized_score=normalized_score,
        grade=_grade(normalized_score),
        passed=normalized_score >= pass_threshold and not failed_findings,
        criteria=criteria,
        summary=summary,
    )
