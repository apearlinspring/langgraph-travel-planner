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
        "last_reviewed": "2026-05-11",
        "freshness_status": "current",
        "requires_verification": False,
        "prohibited_commitments": [],
    }


def _valid_report_data(mode="agency_plan"):
    route = {
        "day_number": 1,
        "route_points": ["Beijing", "Shanghai", "People Square", "The Bund"],
        "summary": "Beijing -> Shanghai -> People Square -> The Bund",
        "map_label": "Day 1: Beijing -> Shanghai -> People Square -> The Bund",
    }
    route_map_day = {
        "day_number": 1,
        "title": "Arrival and light city walk",
        "summary": route["summary"],
        "route_points": route["route_points"],
        "points": [
            {
                "name": "Beijing",
                "type": "transport",
                "type_label": "交通节点",
                "description": "Departure city.",
            },
            {
                "name": "Shanghai",
                "type": "city",
                "type_label": "城市节点",
                "description": "Arrival city.",
            },
            {
                "name": "People Square",
                "type": "business_district",
                "type_label": "商业街区",
                "description": "City center area.",
            },
            {
                "name": "The Bund",
                "type": "attraction",
                "type_label": "景点/体验",
                "description": "Core sightseeing node.",
            },
        ],
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
        "route_map": {
            "version": "route_map.v1",
            "style": "cartoon_daily_route",
            "days": [route_map_day],
        },
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
        "agency_product": {
            "mode": mode,
            "segment": "standard",
            "code": "comfort_light_custom",
            "name": "Light custom planning",
            "product_type": "Consultant planning",
            "positioning": "Route, budget, and risk-control deliverable.",
            "deliverables": ["route structure", "budget breakdown", "risk checklist"],
            "non_commitments": ["do not promise inventory", "do not lock prices"],
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
                {"key": "service_reserve", "label": "Service reserve", "amount": 500, "basis": "Flexible buffer"},
                {"key": "other", "label": "Other", "amount": 100, "basis": "Personal extras"},
            ],
        },
        "quote_policy": {
            "pricing_status": "estimate_only",
            "locked_price": False,
            "currency": "CNY",
            "product_code": "comfort_light_custom",
            "product_name": "Light custom planning",
            "quote_basis": ["2 people / 1 day estimate", "Transport: Rail estimate"],
            "included": ["planning service", "budget explanation", "risk checklist"],
            "excluded": ["no actual ticket payment", "no hotel payment", "no inventory lock"],
            "price_variables": ["date", "hotel room", "ticket availability"],
            "verification_required": ["verify ticket price, hotel, booking, and weather"],
            "disclaimer": "Estimate only; not a formal contract quote or inventory lock.",
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


def test_evaluate_report_quality_flags_itinerary_route_count_mismatch():
    report_data = _valid_report_data()
    extra_day = dict(report_data["itinerary"][0])
    extra_day["day_number"] = 2
    extra_day["route"] = dict(extra_day["route"])
    extra_day["route"]["day_number"] = 2
    report_data["itinerary"].append(extra_day)

    result = evaluate_report_quality(report_data, expected_mode="agency_plan")

    assert result.passed is False
    assert any("map_routes count must match itinerary day count" in item for item in result.summary)


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


def test_evaluate_report_quality_checks_quote_policy_boundaries():
    report_data = _valid_report_data()
    report_data["quote_policy"] = {"pricing_status": "locked", "locked_price": True}

    result = evaluate_report_quality(report_data, expected_mode="agency_plan")

    assert result.passed is False
    assert any("quote_policy" in item for item in result.summary)


def test_evaluate_report_quality_rejects_non_dict_report_data():
    with pytest.raises(TypeError):
        evaluate_report_quality(None)  # type: ignore[arg-type]
