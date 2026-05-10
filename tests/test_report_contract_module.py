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


def test_report_validator_requires_food_preferences_contract():
    report_data = _valid_report_data()
    report_data.pop("food_preferences")

    validation = validate_report_data(report_data)

    assert validation.ok is False
    assert "food_preferences" in validation.missing_fields


def test_report_validator_rejects_empty_itinerary_and_map_routes():
    report_data = _valid_report_data()
    report_data["itinerary"] = []
    report_data["map_routes"] = []

    validation = validate_report_data(report_data)

    assert validation.ok is False
    assert "每日行程不能为空。" in validation.route_mismatches
    assert "地图路线不能为空。" in validation.route_mismatches
