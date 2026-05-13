from langchain.tools import ToolRuntime

from app.agency.product_rules import infer_report_planning_mode
from app.core.intent import detect_travel_intent, resolve_planning_mode
from app.core.state import create_initial_state
from app.reports import validate_report_data
from app.tools.state_transition import generate_order_tool, record_requirement_tool


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="tool-call-1",
        store=None,
    )


def test_free_city_three_days_stays_free_across_intent_and_report_mode():
    prompt = "我第一次去南京，3天2晚，自由行，想要文化加美食，不想太赶。"

    intent = detect_travel_intent(
        prompt,
        current_step="requirement_collection",
        state={},
    )
    decision = resolve_planning_mode(prompt, state={}, intent=intent)
    report_mode = infer_report_planning_mode(
        {
            "destination": "南京",
            "travel_styles": ["culture", "food"],
            "special_needs": prompt,
        },
        {},
    )

    assert intent.name == "free_planning_query"
    assert decision.mode == "free_planning"
    assert report_mode == "free_planning"


def test_family_or_low_stress_preferences_do_not_imply_agency_plan():
    prompt = "亲子游，2大1小，从上海去杭州3天2晚，希望少走路、酒店干净、行程轻松。"
    state = create_initial_state(user_id="user-1", session_id="session-1")

    decision = resolve_planning_mode(prompt, state=state)
    command = record_requirement_tool.invoke(
        {
            "departure_city": "上海",
            "destination": "杭州",
            "departure_date": "2026-06-01",
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 1,
            "budget_min": 2500.0,
            "budget_max": 5000.0,
            "travel_styles": ["culture", "food"],
            "special_needs": "亲子游，希望少走路、酒店干净、行程轻松。",
            "runtime": _build_runtime(state),
        }
    )

    assert decision.mode is None
    assert command.update["planning_mode"] == "free_planning"
    assert command.update["user_requirement"]["planning_mode"] == "free_planning"


def test_explicit_free_signal_overrides_overeager_agency_tool_argument():
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = record_requirement_tool.invoke(
        {
            "departure_city": "北京",
            "destination": "南京",
            "departure_date": "2026-06-01",
            "travel_days": 3,
            "adult_count": 2,
            "children_count": 0,
            "budget_min": 2000.0,
            "budget_max": 5000.0,
            "travel_styles": ["culture", "food"],
            "special_needs": "自由行，自己订酒店机票，不需要旅行社产品。",
            "planning_mode": "agency_plan",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["planning_mode"] == "free_planning"
    assert command.update["user_requirement"]["planning_mode"] == "free_planning"
    assert "自由规划" in command.update["messages"][0].content


def test_explicit_agency_quote_signal_still_records_agency_plan():
    prompt = "想要省心方案，请按旅行社顾问方案安排，并说明报价、费用包含和不含。"
    state = create_initial_state(user_id="user-1", session_id="session-1")

    intent = detect_travel_intent(
        prompt,
        current_step="requirement_collection",
        state=state,
    )
    decision = resolve_planning_mode(prompt, state=state, intent=intent)
    command = record_requirement_tool.invoke(
        {
            "departure_city": "成都",
            "destination": "重庆",
            "departure_date": "2026-06-20",
            "travel_days": 3,
            "adult_count": 4,
            "children_count": 0,
            "budget_min": 1500.0,
            "budget_max": 3500.0,
            "travel_styles": ["relaxation"],
            "special_needs": prompt,
            "runtime": _build_runtime(state),
        }
    )

    assert intent.name in {"agency_plan_query", "pricing_query"}
    assert decision.mode == "agency_plan"
    assert command.update["planning_mode"] == "agency_plan"
    assert command.update["user_requirement"]["planning_mode"] == "agency_plan"


def test_generate_order_report_data_keeps_free_mode_stable():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "order_generation",
            "planning_mode": "free_planning",
            "planning_mode_reason": "用户明确自由行，自己决策和预订",
            "planning_mode_confirmed": True,
            "user_requirement": {
                "departure_city": "北京",
                "destination": "南京",
                "departure_date": "2026-06-01",
                "travel_days": 3,
                "adult_count": 2,
                "children_count": 0,
                "budget_min": 2000.0,
                "budget_max": 5000.0,
                "budget_level": "comfort",
                "travel_styles": ["culture", "food"],
                "special_needs": "第一次去南京，自由行，想要文化加美食，不想太赶。",
                "planning_mode": "free_planning",
                "planning_mode_reason": "用户明确自由行，自己决策和预订",
                "planning_mode_confirmed": True,
            },
            "selected_destination": "南京",
            "selected_transport": "train",
            "selected_transport_option": {
                "transport_type": "train",
                "details": "高铁候选待二次核验",
                "price": 500.0,
                "source": "测试估算",
            },
            "selected_food_types": ["local", "specialty"],
        }
    )

    command = generate_order_tool.invoke({"runtime": _build_runtime(state)})
    report_data = command.update["report_data"]
    validation = validate_report_data(report_data)

    assert validation.ok
    assert report_data["agency_context"]["mode"] == "free_planning"
    assert report_data["agency_product"]["mode"] == "free_planning"
    assert report_data["agency_product"]["code"] == "free_planning_optimizer"
    assert "旅行社顾问方案" not in report_data["agency_context"]["summary"]
