"""Deterministic quality checks for report evidence and RAG alignment."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.evaluation.report_quality import CriterionResult, REQUIRED_AGENCY_CATEGORIES
from app.rag.contracts import LOW_CONFIDENCE_EVIDENCE_LEVELS, PROHIBITED_DYNAMIC_COMMITMENTS


REQUIRED_EVIDENCE_FIELDS = {
    "source",
    "source_type",
    "category",
    "visibility",
    "title",
    "snippet",
    "relevance_score",
    "evidence_level",
    "applicable_modes",
    "constraints",
    "last_reviewed",
    "freshness_status",
    "requires_verification",
    "prohibited_commitments",
}


@dataclass
class RagQualityResult:
    """Full deterministic evaluation result for report evidence quality."""

    total_score: float
    max_score: float
    normalized_score: float
    grade: str
    passed: bool
    criteria: list[CriterionResult]
    summary: list[str]
    category_coverage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "normalized_score": self.normalized_score,
            "grade": self.grade,
            "passed": self.passed,
            "summary": self.summary,
            "category_coverage": self.category_coverage,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
        }


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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _score(condition: bool, points: float, findings: list[str], message: str) -> float:
    if condition:
        return points
    findings.append(message)
    return 0.0


def _agency_context(report_data: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(report_data.get("agency_context"))


def _evidence_items(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    context = _agency_context(report_data)
    return [_as_dict(item) for item in _as_list(context.get("evidence"))]


def _needs_verification(item: dict[str, Any]) -> bool:
    evidence_level = str(item.get("evidence_level") or "").strip().lower()
    return (
        item.get("requires_verification") is True
        or str(item.get("freshness_status") or "").strip() != "current"
        or evidence_level in LOW_CONFIDENCE_EVIDENCE_LEVELS
    )


def evidence_category_coverage(report_data: dict[str, Any]) -> dict[str, int]:
    """Return a stable count of evidence categories visible in report_data."""

    coverage: dict[str, int] = {}
    for item in _evidence_items(report_data):
        category = item.get("category")
        if _has_text(category):
            normalized = str(category).strip()
            coverage[normalized] = coverage.get(normalized, 0) + 1

    agency_categories = _as_dict(_agency_context(report_data).get("categories"))
    for category, value in agency_categories.items():
        if not _has_text(category):
            continue
        if isinstance(value, list) and value:
            coverage.setdefault(str(category), len(value))
        elif value:
            coverage.setdefault(str(category), 1)

    bundle_categories = _as_dict(_as_dict(report_data.get("evidence_bundle")).get("agency_categories"))
    for category, value in bundle_categories.items():
        if _has_text(category) and isinstance(value, (int, float)) and value > 0:
            coverage.setdefault(str(category), int(value))
    return coverage


def _criterion_evidence_contract(
    report_data: dict[str, Any],
    required_evidence_count: int,
) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    evidence = _evidence_items(report_data)

    score += _score(
        len(evidence) >= required_evidence_count,
        8,
        findings,
        f"Need at least {required_evidence_count} structured evidence items",
    )
    missing_field_items = []
    for index, item in enumerate(evidence, start=1):
        missing_fields = sorted(REQUIRED_EVIDENCE_FIELDS - set(item))
        if missing_fields:
            missing_field_items.append(f"#{index}: {', '.join(missing_fields)}")
    score += _score(
        not missing_field_items and bool(evidence),
        8,
        findings,
        "Evidence items are missing required fields: " + "; ".join(missing_field_items[:3]),
    )
    score += _score(
        all(
            isinstance(item.get("relevance_score"), (int, float))
            and 0 <= float(item.get("relevance_score")) <= 1
            and _as_list(item.get("applicable_modes"))
            and _as_list(item.get("constraints"))
            and _has_text(item.get("last_reviewed"))
            and item.get("freshness_status") in {"current", "expired", "unknown", "future"}
            and isinstance(item.get("requires_verification"), bool)
            and isinstance(item.get("prohibited_commitments"), list)
            for item in evidence
        )
        and bool(evidence),
        4,
        findings,
        "Evidence items need bounded scores, mode metadata, freshness, and verification flags",
    )
    return CriterionResult("rag_evidence_contract", score, 20, findings)


def _criterion_category_coverage(
    report_data: dict[str, Any],
    required_categories: set[str],
    expected_mode: str | None,
) -> CriterionResult:
    findings: list[str] = []
    coverage = evidence_category_coverage(report_data)
    covered_categories = set(coverage)
    score = 0.0

    score += _score(
        required_categories.issubset(covered_categories),
        18,
        findings,
        f"Missing required evidence categories: {', '.join(sorted(required_categories - covered_categories))}",
    )
    if expected_mode == "agency_plan":
        score += _score(
            len(covered_categories & REQUIRED_AGENCY_CATEGORIES) >= min(3, len(REQUIRED_AGENCY_CATEGORIES)),
            7,
            findings,
            "Agency-plan evidence should cover at least 3 agency categories",
        )
    else:
        score += 7
    return CriterionResult("rag_category_coverage", score, 25, findings)


def _criterion_mode_alignment(
    report_data: dict[str, Any],
    expected_mode: str | None,
) -> CriterionResult:
    findings: list[str] = []
    context = _agency_context(report_data)
    evidence = _evidence_items(report_data)
    mode = expected_mode or context.get("mode")
    score = 0.0

    score += _score(
        context.get("mode") in {"agency_plan", "free_planning"},
        6,
        findings,
        "agency_context.mode must be agency_plan or free_planning",
    )
    if expected_mode:
        score += _score(
            context.get("mode") == expected_mode,
            6,
            findings,
            f"agency_context.mode={context.get('mode')!r} does not match expected {expected_mode!r}",
        )
    else:
        score += 6 if context.get("mode") else 0

    score += _score(
        all(
            not mode
            or mode in {str(item) for item in _as_list(evidence_item.get("applicable_modes"))}
            or "all" in {str(item).lower() for item in _as_list(evidence_item.get("applicable_modes"))}
            for evidence_item in evidence
        )
        and bool(evidence),
        5,
        findings,
        "Evidence applicable_modes must include the expected planning mode",
    )
    if mode == "agency_plan":
        score += _score(
            any(item.get("source_type") == "agency_internal" for item in evidence),
            3,
            findings,
            "agency_plan evidence should include agency_internal sources",
        )
    else:
        summary_text = str(context.get("summary") or "")
        score += _score(
            "硬推" not in summary_text and "强制" not in summary_text,
            3,
            findings,
            "free_planning evidence should avoid hard-sell wording",
        )
    return CriterionResult("rag_mode_alignment", score, 20, findings)


def _criterion_traceability(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    evidence_bundle = _as_dict(report_data.get("evidence_bundle"))
    price_evidence = _as_dict(evidence_bundle.get("price_evidence"))
    budget_confidence = _as_dict(report_data.get("budget_confidence"))

    score += _score(
        _has_text(evidence_bundle.get("source_type")),
        5,
        findings,
        "evidence_bundle.source_type is required",
    )
    score += _score(
        bool(_as_dict(evidence_bundle.get("agency_categories"))) or bool(_as_list(evidence_bundle.get("route_evidence"))),
        5,
        findings,
        "evidence_bundle should expose agency category counts or route evidence",
    )
    score += _score(
        any(_as_list(price_evidence.get(key)) for key in ("confirmed", "estimated", "verification")),
        5,
        findings,
        "price_evidence should distinguish confirmed, estimated, or verification items",
    )
    score += _score(
        _as_list(budget_confidence.get("verification_items")),
        5,
        findings,
        "budget_confidence must include verification_items",
    )
    return CriterionResult("rag_traceability", score, 20, findings)


def _criterion_evidence_governance(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    evidence = _evidence_items(report_data)
    quote_policy = _as_dict(report_data.get("quote_policy"))

    score += _score(
        all(
            item.get("visibility") == "internal"
            for item in evidence
            if item.get("source_type") == "agency_internal"
        )
        and bool(evidence),
        3,
        findings,
        "agency_internal evidence must keep visibility=internal",
    )
    score += _score(
        all(
            item.get("source_type") in {"agency_internal", "destination_guide"}
            for item in evidence
        )
        and bool(evidence),
        3,
        findings,
        "Evidence source_type must stay within known RAG contracts",
    )

    verification_items = [item for item in evidence if _needs_verification(item)]
    prohibited_terms = set(PROHIBITED_DYNAMIC_COMMITMENTS)
    score += _score(
        all(
            prohibited_terms.intersection(set(_as_list(item.get("prohibited_commitments"))))
            for item in verification_items
        )
        and not quote_policy.get("locked_price")
        and str(quote_policy.get("pricing_status") or "") != "locked",
        4,
        findings,
        "Expired or low-confidence evidence must prohibit dynamic commitments and cannot support locked pricing",
    )
    return CriterionResult("rag_evidence_governance", score, 10, findings)


def _criterion_user_safe_delivery(report_data: dict[str, Any]) -> CriterionResult:
    findings: list[str] = []
    score = 0.0
    tool_audit = _as_dict(report_data.get("tool_audit_summary"))
    risks = "\n".join(str(item) for item in _as_list(report_data.get("risks")))

    score += _score(
        _as_list(tool_audit.get("pending_checks")),
        5,
        findings,
        "tool_audit_summary.pending_checks should be visible",
    )
    score += _score(
        _as_list(tool_audit.get("unsupported_actions")),
        5,
        findings,
        "tool_audit_summary.unsupported_actions should state unsupported promises",
    )
    score += _score(
        any(keyword in risks.lower() for keyword in ("verify", "confirm", "\u6838\u9a8c", "\u590d\u6838", "\u786e\u8ba4")),
        5,
        findings,
        "Risk text should remind users to verify live booking or weather details",
    )
    return CriterionResult("rag_user_safe_delivery", score, 15, findings)


def evaluate_rag_quality(
    report_data: dict[str, Any],
    *,
    expected_mode: str | None = None,
    required_categories: set[str] | None = None,
    required_evidence_count: int = 3,
    pass_threshold: float = 80.0,
) -> RagQualityResult:
    """Evaluate evidence coverage and precision for a structured report."""

    if not isinstance(report_data, dict):
        raise TypeError("report_data must be a dictionary")

    mode = expected_mode or _agency_context(report_data).get("mode")
    if required_categories is None:
        required_categories = (
            {"products", "sop", "pricing", "risk"}
            if mode == "agency_plan"
            else {"risk", "report"}
        )

    criteria = [
        _criterion_evidence_contract(report_data, required_evidence_count),
        _criterion_category_coverage(report_data, required_categories, mode if isinstance(mode, str) else None),
        _criterion_mode_alignment(report_data, expected_mode),
        _criterion_traceability(report_data),
        _criterion_evidence_governance(report_data),
        _criterion_user_safe_delivery(report_data),
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
        ["RAG evidence satisfies the current quality gate."]
        if normalized_score >= pass_threshold and not failed_findings
        else failed_findings[:10]
    )
    return RagQualityResult(
        total_score=total_score,
        max_score=max_score,
        normalized_score=normalized_score,
        grade=_grade(normalized_score),
        passed=normalized_score >= pass_threshold and not failed_findings,
        criteria=criteria,
        summary=summary,
        category_coverage=evidence_category_coverage(report_data),
    )
