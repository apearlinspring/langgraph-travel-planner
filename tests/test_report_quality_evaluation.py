import pytest

from app.evaluation.report_quality import evaluate_report_quality


def _agency_evidence(category: str):
    return {
        "source": f"internal/{category}/sample.md",
        "source_type": "agency_internal",
        "category": category,
        "visibility": "internal",
        "title": f"{category} evidence",
        "snippet": f"{category} structured travel agency evidence",
        "relevance_score": 0.9,
        "evidence_level": "rule",
        "applicable_modes": ["agency_plan", "free_planning"],
        "constraints": ["do not promise inventory", "mark live data for verification"],
    }


def _valid_report_data(mode="agency_plan"):
    route = {
        "day_number": 1,
        "route_points": ["Beijing", "Shanghai", "People Square", "The Bund"],
        "summary": "Beijing -> Shanghai -> People Square -> The Bund",
        "map_label": "Day 1: Beijing -> Shanghai -> People Square -> The Bund",
    }
    day = {
        "day_number": 1,
        "title": "Arrival and light city walk",
        "route": route,
        "time_blocks": [
            "Morning: high-speed rail arrival",
            "Afternoon: hotel check-in",
            "Evening: Bund night walk",
        ],
        "activities": ["Arrive in Shanghai", "Check in", "Bund night view"],
        "meals": ["Breakfast: self-arranged", "Lunch: local snack"],
        "plan_b": "Switch to indoor museums if it rains.",
        "risk_notes": ["Verify booking and ticket price before departure."],
    }
    return {
        "version": "travel_report.v1",
        "title": "Personalized travel planning report",
        "subtitle": "Final itinerary plan",
        "overview": {
            "route_label": "Beijing -> Shanghai",
            "duration": "1 day",
            "people": "2 adults",
            "travel_styles": ["culture"],
            "special_needs": "low-stress agency plan",
        },
        "transport": {"summary": "High-speed rail first", "option": {}},
        "accommodation": {"summary": "Stay near People Square", "option": {}},
        "food_preferences": {"summary": "Local snacks"},
        "itinerary": [day],
        "map_routes": [route],
        "agency_context": {
            "source_type": "agency_internal",
            "mode": mode,
            "summary": "Built from internal agency consultant playbooks.",
            "highlights": ["mature route", "budget basis", "risk fallback"],
            "categories": {
                "products": ["product route template"],
                "sop": ["consultant workflow"],
                "pricing": ["budget rule"],
                "risk": ["risk reminder"],
                "report": ["delivery standard"],
            },
            "evidence": [
                _agency_evidence("products"),
                _agency_evidence("sop"),
                _agency_evidence("pricing"),
                _agency_evidence("risk"),
                _agency_evidence("report"),
            ],
        },
        "budget": {
            "currency": "CNY",
            "total": 3480,
            "per_person": 1740,
            "items": [
                {"key": "transport", "label": "Transport", "amount": 1000, "basis": "Rail estimate"},
                {"key": "accommodation", "label": "Hotel", "amount": 600, "basis": "Hotel estimate"},
                {"key": "food", "label": "Food", "amount": 1200, "basis": "Dining estimate"},
                {"key": "attractions", "label": "Attractions", "amount": 80, "basis": "Ticket estimate"},
                {"key": "misc", "label": "Buffer", "amount": 600, "basis": "Flexible buffer"},
            ],
        },
        "budget_confidence": {
            "level": "low",
            "confirmed_items": [],
            "estimated_items": ["transport and hotel are estimates"],
            "verification_items": ["verify ticket price, hotel, booking, and weather"],
        },
        "risks": [
            "Verify weather 24-48 hours before departure.",
            "Confirm transport ticket price before purchase.",
            "Check hotel booking and check-in policy again.",
            "Use Plan B if it rains.",
        ],
        "adjustment_options": ["Upgrade hotel", "Reduce food budget"],
        "evidence_bundle": {
            "source_type": "structured_state",
            "agency_categories": {
                "products": 1,
                "sop": 1,
                "pricing": 1,
                "risk": 1,
                "report": 1,
            },
            "price_evidence": {
                "confirmed": [],
                "estimated": ["transport and hotel are estimates"],
                "verification": ["verify ticket price, hotel, booking, and weather"],
            },
            "tool_sources": {"transport": "fixture", "accommodation": "fixture"},
            "route_evidence": [route],
        },
        "tool_audit_summary": {
            "readiness": "ready for client review",
            "used_sources": ["fixture report_data"],
            "pending_checks": ["verify ticket price, hotel, booking, and weather"],
            "unsupported_actions": ["no real payment link"],
        },
        "sections": [
            {"id": "overview", "title": "Overview"},
            {"id": "transport_accommodation", "title": "Transport and accommodation"},
            {"id": "itinerary", "title": "Daily itinerary"},
            {"id": "map_routes", "title": "Map routes"},
            {"id": "agency_context", "title": "Agency basis"},
            {"id": "budget", "title": "Budget details"},
            {"id": "budget_confidence", "title": "Budget confidence"},
            {"id": "risk", "title": "Risks"},
            {"id": "adjustments", "title": "Adjustments"},
            {"id": "tool_audit_summary", "title": "Consultant handoff"},
        ],
    }


def test_evaluate_report_quality_passes_valid_agency_report():
    result = evaluate_report_quality(
        _valid_report_data(),
        expected_mode="agency_plan",
    )

    assert result.passed is True
    assert result.normalized_score == 100
    assert result.grade == "A"


def test_evaluate_report_quality_flags_missing_budget_and_map_contracts():
    report_data = _valid_report_data()
    report_data["budget"]["items"] = []
    report_data["map_routes"] = []

    result = evaluate_report_quality(report_data, expected_mode="agency_plan")

    assert result.passed is False
    assert result.normalized_score < 90
    assert any("Missing budget groups" in item for item in result.summary)
    assert any("map_routes" in item for item in result.summary)


def test_evaluate_report_quality_checks_expected_planning_mode():
    result = evaluate_report_quality(
        _valid_report_data(mode="free_planning"),
        expected_mode="agency_plan",
    )

    assert result.passed is False
    assert any("agency_context.mode" in item for item in result.summary)


def test_evaluate_report_quality_checks_agency_evidence_contract():
    report_data = _valid_report_data()
    report_data["agency_context"]["evidence"] = [
        {
            "source": "internal/products/sample.md",
            "category": "products",
        }
    ]

    result = evaluate_report_quality(report_data, expected_mode="agency_plan")

    assert result.passed is False
    assert any("agency_context.evidence" in item for item in result.summary)


def test_evaluate_report_quality_rejects_non_dict_report_data():
    with pytest.raises(TypeError):
        evaluate_report_quality(None)  # type: ignore[arg-type]
