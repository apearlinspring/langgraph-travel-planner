from pathlib import Path

from langchain.tools import ToolRuntime

from app.agency.pricing_rules import build_quote_policy
from app.agency.product_rules import build_light_product
from app.core.intent import detect_travel_intent
from app.core.state import create_initial_state
from app.tools.state_transition import generate_order_tool, summarize_budget_tool


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )


def _family_agency_state():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "budget_summarization",
            "user_requirement": {
                "departure_city": "北京",
                "destination": "上海",
                "departure_date": "2026-06-19",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 1,
                "budget_min": 2500.0,
                "budget_max": 5000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture", "food"],
                "special_needs": "亲子省心，按旅行社方案安排，孩子需要午休。",
            },
            "selected_destination": "上海",
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "G1 北京南 -> 上海虹桥",
                "price": 626.0,
                "source": "测试票价",
            },
            "selected_accommodation_types": ["star_hotel"],
            "selected_accommodation_option": {
                "name": "上海亲子友好酒店",
                "type": "star_hotel",
                "location": "人民广场",
                "price_per_night": 900.0,
                "rating": 4.6,
                "amenities": ["亲子房", "近地铁"],
            },
            "selected_food_types": ["local", "specialty"],
            "itinerary": [
                {
                    "day_number": 1,
                    "theme": "抵达与轻松适应",
                    "activities": ["抵达上海", "人民广场周边散步"],
                    "time_blocks": ["下午/抵达：入住酒店", "晚上/轻松：周边散步"],
                    "meals": ["午餐：就近简餐", "晚餐：本地小吃"],
                    "accommodation": "上海亲子友好酒店",
                    "route_note": "抵达后围绕住宿周边轻量活动。",
                    "plan_b": "如遇阵雨，改为商场和室内亲子空间。",
                },
                {
                    "day_number": 2,
                    "theme": "城市文化与亲子留白",
                    "activities": ["上海博物馆", "南京路步行街"],
                    "time_blocks": ["上午/文化：上海博物馆", "下午/留白：午休后南京路"],
                    "meals": ["午餐：就近简餐", "晚餐：特色餐厅"],
                    "accommodation": "上海亲子友好酒店",
                    "route_note": "当天围绕人民广场和南京路活动。",
                    "plan_b": "如孩子疲惫，缩短步行街时间。",
                },
                {
                    "day_number": 3,
                    "theme": "返程缓冲",
                    "activities": ["酒店早餐", "返程"],
                    "time_blocks": ["上午/缓冲：退房与返程"],
                    "meals": ["早餐：酒店", "午餐：车站简餐"],
                    "accommodation": "返程日不住宿",
                    "route_note": "保留返程缓冲。",
                    "plan_b": "如交通变化，优先保留打车机动金。",
                },
            ],
        }
    )
    return state


def test_light_product_and_quote_policy_explain_agency_boundaries():
    requirement = {
        "travel_days": 4,
        "adult_count": 2,
        "children_count": 1,
        "budget_level": "comfort",
        "budget_max": 5000.0,
        "travel_styles": ["culture"],
        "special_needs": "亲子省心，旅行社方案。",
    }
    budget = {
        "currency": "CNY",
        "travel_days": 4,
        "nights": 3,
        "total_people": 3,
        "per_person": 3600.0,
        "confidence_level": "中",
        "line_items": [
            {
                "key": "transport",
                "label": "交通",
                "amount": 1800.0,
                "basis": "已选高铁参考价",
                "confidence": "已确认价格",
            }
        ],
        "verification_items": ["住宿：入住前复核房型、税费和取消政策。"],
    }

    product = build_light_product(requirement)
    quote_policy = build_quote_policy(requirement, budget, product=product)

    assert product["mode"] == "agency_plan"
    assert product["code"] == "family_light_custom"
    assert product["budget_level"] == "舒适"
    assert "交通酒店核验" in product["service_nodes"]
    assert quote_policy["pricing_status"] == "estimate_only"
    assert quote_policy["locked_price"] is False
    assert any("不承诺真实库存" in item for item in quote_policy["excluded"])
    assert "库存锁价" in quote_policy["disclaimer"]


def test_budget_and_final_report_export_agency_product_quote_policy():
    state = _family_agency_state()

    budget_command = summarize_budget_tool.invoke({"runtime": _build_runtime(state)})
    state.update(budget_command.update)

    budget = state["budget"]
    assert budget["quote_policy"]["product_name"] == "亲子省心轻定制"
    assert budget["quote_policy"]["locked_price"] is False
    budget_message = budget_command.update["messages"][0].content
    assert "轻量产品与报价规则" in budget_message
    assert "费用不含口径" in budget_message

    order_command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report = order_command.update["report"]
    report_data = order_command.update["report_data"]

    assert "产品与报价规则" in report
    assert "亲子省心轻定制" in report
    assert "不承诺真实库存" in report
    assert report_data["agency_product"]["code"] == "family_light_custom"
    assert report_data["quote_policy"]["product_name"] == "亲子省心轻定制"
    assert report_data["budget"]["quote_policy"] == report_data["quote_policy"]
    assert report_data["agency_context"]["rule_evidence"]["evidence_type"] == "agency_rules"
    assert any(
        section["title"] == "产品与报价规则"
        for section in report_data["sections"]
    )


def test_pricing_intent_covers_real_agency_quote_terms():
    intent = detect_travel_intent(
        "这份报价单儿童价怎么算，费用不含和单房差有哪些？",
        current_step="budget_summarization",
    )

    assert intent.name == "pricing_query"
    assert intent.preferred_tool == "search_agency_pricing_rules"


def test_quote_policy_ignores_malformed_line_items():
    requirement = {
        "travel_days": 2,
        "adult_count": 2,
        "children_count": 0,
        "budget_level": "economy",
        "special_needs": "旅行社省心方案。",
    }
    product = build_light_product(requirement)

    quote_policy = build_quote_policy(
        requirement,
        {
            "travel_days": 2,
            "line_items": [
                "上游模型误填的纯文本费用项",
                {"label": "交通", "basis": "高铁参考价", "confidence": "估算"},
            ],
        },
        product=product,
    )

    assert any("交通：高铁参考价" in item for item in quote_policy["quote_basis"])
    assert all("上游模型误填" not in item for item in quote_policy["quote_basis"])


def test_internal_docs_keep_light_product_and_quote_boundaries():
    product_doc = (
        PROJECT_ROOT / "data" / "documents" / "internal" / "products" / "route_templates.md"
    ).read_text(encoding="utf-8")
    pricing_doc = (
        PROJECT_ROOT / "data" / "documents" / "internal" / "pricing" / "pricing_rules.md"
    ).read_text(encoding="utf-8")

    assert "轻量产品线" in product_doc
    assert "亲子省心轻定制" in product_doc
    assert "自由行路线优化" in product_doc
    assert "产品边界" in product_doc
    assert "轻量产品报价口径" in pricing_doc
    assert "费用不含口径" in pricing_doc
    assert "不承诺锁价" in pricing_doc
