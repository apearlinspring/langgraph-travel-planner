import math

import pytest
from langchain.tools import ToolRuntime

from app.core.state import create_initial_state
from app.tools.state_transition import (
    record_requirement_tool,
    select_accommodation_tool,
    select_transport_tool,
)


def _build_runtime(state):
    return ToolRuntime(
        state=state,
        context=None,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="input-validation-test",
        store=None,
    )


def _record_requirement(**overrides):
    state = create_initial_state(user_id="user-1", session_id="session-1")
    arguments = {
        "departure_city": "上海",
        "destination": "杭州",
        "departure_date": "2026-08-01",
        "travel_days": 3,
        "adult_count": 2,
        "children_count": 0,
        "budget_min": 1500,
        "budget_max": 3500,
        "travel_styles": ["轻松舒适"],
        "runtime": _build_runtime(state),
    }
    arguments.update(overrides)
    return record_requirement_tool.invoke(arguments)


def test_requirement_numeric_coercion_preserves_negative_signs():
    command = _record_requirement(
        travel_days="-3 天",
        adult_count="-3 位成人",
        children_count="-2 名儿童",
        budget_min="-500 元",
        budget_max="-900 元",
    )

    requirement = command.update["user_requirement"]
    assert requirement["travel_days"] == 1
    assert requirement["adult_count"] == 1
    assert requirement["children_count"] == 0
    assert requirement["budget_min"] == 1500
    assert requirement["budget_max"] == 3500


@pytest.mark.parametrize(
    "invalid_budget",
    [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"],
)
def test_requirement_rejects_non_finite_budgets(invalid_budget):
    command = _record_requirement(
        budget_min=invalid_budget,
        budget_max=invalid_budget,
    )

    requirement = command.update["user_requirement"]
    assert requirement["budget_min"] == 1500
    assert requirement["budget_max"] == 3500
    assert math.isfinite(requirement["budget_min"])
    assert math.isfinite(requirement["budget_max"])


@pytest.mark.parametrize("unknown_confirmation", ["maybe", "later", {"confirmed": True}, []])
def test_requirement_unknown_confirmation_values_are_not_truthy(unknown_confirmation):
    command = _record_requirement(planning_mode_confirmed=unknown_confirmation)

    assert command.update["planning_mode_confirmed"] is False
    assert command.update["user_requirement"]["planning_mode_confirmed"] is False


@pytest.mark.parametrize(
    ("confirmation", "expected"),
    [("yes", True), ("确认", True), (1, True), ("no", False), ("未确认", False), (0, False)],
)
def test_requirement_accepts_explicit_confirmation_values(confirmation, expected):
    command = _record_requirement(planning_mode_confirmed=confirmation)

    assert command.update["planning_mode_confirmed"] is expected


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"price_per_night": "-320 元/晚"},
        {"price_per_night": float("nan")},
        {"price_per_night": float("inf")},
        {"rating": "-0.1"},
        {"rating": "5.1"},
        {"rating": float("nan")},
        {"rating": float("inf")},
    ],
)
def test_accommodation_rejects_invalid_price_or_rating_without_advancing(invalid_fields):
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["current_step"] = "accommodation_planning"

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["star_hotel"],
            "hotel_name": "边界测试酒店",
            **invalid_fields,
            "runtime": _build_runtime(state),
        }
    )

    assert "current_step" not in command.update
    assert "selected_accommodation_types" not in command.update
    assert "selected_accommodation_option" not in command.update
    assert "无效" in command.update["messages"][0].content
    assert command.update["messages"][0].artifact["status"] == "not_applied"
    assert command.update["messages"][0].artifact["reason"] == "invalid_input"


def test_accommodation_accepts_zero_price_and_boundary_rating():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["current_step"] = "accommodation_planning"

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["star_hotel"],
            "hotel_name": "待核价酒店",
            "price_per_night": 0,
            "rating": 5,
            "runtime": _build_runtime(state),
        }
    )

    option = command.update["selected_accommodation_option"]
    assert command.update["current_step"] == "food_planning"
    assert option["price_per_night"] == 0
    assert option["rating"] == 5


def test_accommodation_treats_pending_numeric_markers_as_unconfirmed():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["current_step"] = "accommodation_planning"

    command = select_accommodation_tool.invoke(
        {
            "accommodation_types": ["star_hotel"],
            "location": "核心文化景点周边",
            "price_per_night": "待核验",
            "rating": "未知",
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "food_planning"
    assert command.update["selected_accommodation_types"] == ["star_hotel"]
    assert command.update["messages"][0].artifact["status"] == "applied"


@pytest.mark.parametrize(
    "candidate_fields",
    [
        {"price_per_night": -1, "rating": 4.5},
        {"price_per_night": 320, "rating": 5.5},
    ],
)
def test_accommodation_rejects_invalid_values_from_existing_candidates(candidate_fields):
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state.update(
        {
            "current_step": "accommodation_planning",
            "accommodation_options": [
                {
                    "hotel_id": 1001,
                    "name": "异常候选酒店",
                    "type": "star_hotel",
                    **candidate_fields,
                }
            ],
        }
    )

    command = select_accommodation_tool.invoke(
        {"hotel_id": 1001, "runtime": _build_runtime(state)}
    )

    assert "current_step" not in command.update
    assert "selected_accommodation_option" not in command.update
    assert "候选住宿" in command.update["messages"][0].content
    assert command.update["messages"][0].artifact["status"] == "not_applied"
    assert command.update["messages"][0].artifact["reason"] == "invalid_input"


@pytest.mark.parametrize("invalid_price", [{"amount": "￥-73/人"}, float("inf")])
def test_transport_does_not_turn_invalid_price_into_a_positive_price(invalid_price):
    state = create_initial_state(user_id="user-1", session_id="session-1")

    command = select_transport_tool.invoke(
        {
            "transport_type": "train",
            "details": "车次待核验",
            "price": invalid_price,
            "runtime": _build_runtime(state),
        }
    )

    assert command.update["current_step"] == "accommodation_planning"
    assert "price" not in command.update["selected_transport_option"]


def test_transport_invalid_choice_emits_not_applied_outcome():
    state = create_initial_state(user_id="user-1", session_id="session-1")
    state["current_step"] = "transport_planning"

    command = select_transport_tool.invoke(
        {
            "transport_type": "teleport",
            "runtime": _build_runtime(state),
        }
    )

    assert "selected_transport" not in command.update
    assert command.update["messages"][0].artifact["status"] == "not_applied"
    assert command.update["messages"][0].artifact["reason"] == "invalid_input"
