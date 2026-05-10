from app.reports import (
    REPORT_SECTION_IDS,
    build_report_bundle,
    report_sections,
    validate_report_data,
)
from tests.test_report_quality_evaluation import _valid_report_data


def test_report_contract_sections_are_canonical_and_copied():
    sections = report_sections()

    assert [section["id"] for section in sections] == list(REPORT_SECTION_IDS)
    sections[0]["id"] = "mutated"
    assert report_sections()[0]["id"] == "overview"


def test_report_bundle_renders_markdown_from_valid_report_data():
    report_data = _valid_report_data()
    bundle = build_report_bundle(report_data)

    assert bundle.validation.ok is True
    assert "# Personalized travel planning report" in bundle.markdown
    assert "顾问交付清单" in bundle.markdown
    assert "verify ticket price" in bundle.markdown


def test_report_validator_blocks_pseudo_report_without_required_contract():
    report_data = {"version": "travel_report.v1", "overview": {}}
    validation = validate_report_data(report_data)

    assert validation.ok is False
    assert "itinerary" in validation.missing_fields
    assert "tool_audit_summary" in validation.missing_fields
    assert "缺少必要结构" in validation.to_user_message()
