import pytest

from app.evaluation.rag_quality import evaluate_rag_quality, evidence_category_coverage
from tests.test_report_quality_evaluation import _valid_report_data


def test_evaluate_rag_quality_passes_structured_agency_evidence():
    result = evaluate_rag_quality(
        _valid_report_data(),
        expected_mode="agency_plan",
    )

    assert result.passed is True
    assert result.normalized_score == 100
    assert result.category_coverage["pricing"] >= 1


def test_evaluate_rag_quality_checks_required_categories():
    report_data = _valid_report_data()
    report_data["agency_context"]["evidence"] = [
        item
        for item in report_data["agency_context"]["evidence"]
        if item["category"] == "products"
    ]
    report_data["agency_context"]["categories"] = {"products": ["product route template"]}
    report_data["evidence_bundle"]["agency_categories"] = {"products": 1}

    result = evaluate_rag_quality(
        report_data,
        expected_mode="agency_plan",
        required_categories={"products", "sop", "pricing", "risk"},
    )

    assert result.passed is False
    assert any("Missing required evidence categories" in item for item in result.summary)


def test_evaluate_rag_quality_checks_applicable_mode():
    report_data = _valid_report_data(mode="free_planning")
    for item in report_data["agency_context"]["evidence"]:
        item["applicable_modes"] = ["agency_plan"]

    result = evaluate_rag_quality(report_data, expected_mode="free_planning")

    assert result.passed is False
    assert any("applicable_modes" in item for item in result.summary)


def test_evidence_category_coverage_uses_context_and_bundle_counts():
    report_data = _valid_report_data()
    report_data["agency_context"]["evidence"] = []

    coverage = evidence_category_coverage(report_data)

    assert coverage["products"] >= 1
    assert coverage["report"] >= 1


def test_evaluate_rag_quality_rejects_non_dict_report_data():
    with pytest.raises(TypeError):
        evaluate_rag_quality(None)  # type: ignore[arg-type]
