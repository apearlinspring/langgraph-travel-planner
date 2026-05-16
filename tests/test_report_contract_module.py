from app.reports import (
    REPORT_SECTION_IDS,
    build_report_bundle,
    build_travel_report_data,
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
    assert "产品与报价规则" in bundle.markdown
    assert "| 类别 | 金额 | 置信度 | 依据 |" in bundle.markdown
    assert "人均：" not in bundle.markdown


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


def test_report_validator_reports_route_length_mismatch_without_truncating():
    report_data = _valid_report_data()
    extra_day = dict(report_data["itinerary"][0])
    extra_day["day_number"] = 2
    extra_day["route"] = dict(extra_day["route"])
    extra_day["route"]["day_number"] = 2
    report_data["itinerary"].append(extra_day)

    validation = validate_report_data(report_data)

    assert validation.ok is False
    assert "每日行程数量必须和地图路线数量一致。" in validation.route_mismatches
    assert "Day 2 缺少地图路线摘要。" in validation.route_mismatches


def test_report_builder_assembles_report_data_from_domain_inputs():
    route = {
        "day_number": 1,
        "route_points": ["北京", "上海", "人民广场", "外滩"],
        "summary": "北京 → 上海 → 人民广场 → 外滩",
        "map_label": "Day 1：北京 → 上海 → 人民广场 → 外滩",
    }
    day = {
        "day_number": 1,
        "theme": "抵达与城市夜景",
        "time_blocks": ["上午/出发：高铁抵达。", "晚上/游览：外滩夜景。"],
        "activities": ["抵达上海", "外滩夜景"],
        "risk_notes": ["出发前复核票价和天气。"],
    }
    budget = {
        "currency": "CNY",
        "total": 1000,
        "per_person": 500,
        "line_items": [
            {"key": "transport", "label": "交通", "amount": 600, "basis": "高铁估算"},
            {"key": "accommodation", "label": "住宿", "amount": 0, "basis": "当日往返"},
            {"key": "food", "label": "餐饮", "amount": 200, "basis": "本地小吃"},
            {"key": "attractions", "label": "景点/体验", "amount": 0, "basis": "免费街区"},
            {"key": "misc", "label": "其他机动", "amount": 200, "basis": "市内交通"},
        ],
        "confidence_level": "中",
        "estimated_items": ["交通：按高铁参考价估算。"],
        "verification_items": ["交通：正式购票前复核实时票价。"],
    }

    report_data = build_travel_report_data(
        state={"selected_destination": "上海", "selected_transport": "train"},
        requirement={
            "departure_city": "北京",
            "destination": "上海",
            "travel_days": 1,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 400,
            "budget_max": 800,
            "travel_styles": ["城市漫步"],
        },
        budget=budget,
        itinerary=[day],
        route_summaries=[route],
        selected_transport_option={"source": "fixture", "price": 300},
        selected_accommodation={"source": "fixture"},
        selected_food_types=["local"],
        transport_label="高铁",
        transport_summary="高铁参考价 300 元/人",
        accommodation_summary="当日往返或住宿待确认",
        food_preferences_summary="本地小吃",
    )

    assert report_data["version"] == "travel_report.v1"
    assert report_data["quote_policy"]["locked_price"] is False
    assert report_data["agency_product"]["non_commitments"]
    assert report_data["route_map"]["days"][0]["points"][0]["type_label"]
    assert [item["key"] for item in report_data["budget"]["items"]] == [
        "transport",
        "accommodation",
        "food",
        "attractions",
        "service_reserve",
        "other",
    ]
    assert any(section["id"] == "product_quote" for section in report_data["sections"])
    assert validate_report_data(report_data).ok is True


def test_report_builder_pads_missing_routes_instead_of_zip_truncating():
    route = {
        "day_number": 1,
        "route_points": ["北京", "上海", "人民广场", "外滩"],
        "summary": "北京 → 上海 → 人民广场 → 外滩",
        "map_label": "Day 1：北京 → 上海 → 人民广场 → 外滩",
    }
    days = [
        {
            "day_number": 1,
            "theme": "抵达与城市夜景",
            "time_blocks": ["上午/出发：高铁抵达。", "晚上/游览：外滩夜景。"],
            "activities": ["抵达上海", "外滩夜景"],
        },
        {
            "day_number": 2,
            "theme": "博物馆与返程",
            "route_points": ["人民广场", "上海博物馆", "返程交通"],
            "time_blocks": ["上午/参观：上海博物馆。", "下午/返程：预留交通缓冲。"],
            "activities": ["上海博物馆", "返程交通"],
        },
    ]
    budget = {
        "currency": "CNY",
        "total": 1200,
        "per_person": 600,
        "line_items": [
            {"key": "transport", "label": "交通", "amount": 600, "basis": "高铁估算"},
            {"key": "accommodation", "label": "住宿", "amount": 0, "basis": "当日往返"},
            {"key": "food", "label": "餐饮", "amount": 300, "basis": "本地小吃"},
            {"key": "attractions", "label": "景点/体验", "amount": 0, "basis": "免费场馆"},
            {"key": "misc", "label": "其他机动", "amount": 300, "basis": "市内交通"},
        ],
        "confidence_level": "中",
        "estimated_items": ["交通：按高铁参考价估算。"],
        "verification_items": ["交通：正式购票前复核实时票价。"],
    }

    report_data = build_travel_report_data(
        state={"selected_destination": "上海", "selected_transport": "train"},
        requirement={
            "departure_city": "北京",
            "destination": "上海",
            "travel_days": 2,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 400,
            "budget_max": 800,
            "travel_styles": ["城市漫步"],
        },
        budget=budget,
        itinerary=days,
        route_summaries=[route],
        selected_transport_option={"source": "fixture", "price": 300},
        selected_accommodation={"source": "fixture"},
        selected_food_types=["local"],
        transport_label="高铁",
        transport_summary="高铁参考价 300 元/人",
        accommodation_summary="当日往返或住宿待确认",
        food_preferences_summary="本地小吃",
    )

    assert len(report_data["itinerary"]) == 2
    assert len(report_data["map_routes"]) == 2
    assert len(report_data["route_map"]["days"]) == 2
    assert report_data["itinerary"][1]["route"]["summary"] == report_data["map_routes"][1]["summary"]
    assert report_data["evidence_bundle"]["route_alignment_findings"] == [
        "Day 2 缺少地图路线，已按行程内容补齐。"
    ]
    assert validate_report_data(report_data).ok is True
