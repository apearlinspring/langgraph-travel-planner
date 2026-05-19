"""
Shared workflow definitions for the travel-planning state machine.
"""
from typing import Literal


PlanningStep = Literal[
    "requirement_collection",
    "destination_recommendation",
    "transport_planning",
    "accommodation_planning",
    "food_planning",
    "itinerary_generation",
    "budget_summarization",
    "order_generation",
]

AgencyStep = Literal[
    "agency_requirement",
    "agency_product_match",
    "agency_plan_draft",
    "agency_feedback",
    "agency_report",
]

RollbackTargetStep = Literal[
    "requirement_collection",
    "destination_recommendation",
    "transport_planning",
    "accommodation_planning",
    "food_planning",
    "itinerary_generation",
    "budget_summarization",
]

PLANNING_STEPS: tuple[PlanningStep, ...] = (
    "requirement_collection",
    "destination_recommendation",
    "transport_planning",
    "accommodation_planning",
    "food_planning",
    "itinerary_generation",
    "budget_summarization",
    "order_generation",
)

ROLLBACK_TARGET_STEPS: tuple[RollbackTargetStep, ...] = PLANNING_STEPS[:-1]
INITIAL_PLANNING_STEP: PlanningStep = PLANNING_STEPS[0]
FINAL_PLANNING_STEP: PlanningStep = PLANNING_STEPS[-1]

AGENCY_STEPS: tuple[AgencyStep, ...] = (
    "agency_requirement",
    "agency_product_match",
    "agency_plan_draft",
    "agency_feedback",
    "agency_report",
)

INITIAL_AGENCY_STEP: AgencyStep = AGENCY_STEPS[0]
FINAL_AGENCY_STEP: AgencyStep = AGENCY_STEPS[-1]

STEP_LABELS: dict[PlanningStep, str] = {
    "requirement_collection": "需求收集",
    "destination_recommendation": "目的地推荐",
    "transport_planning": "交通规划",
    "accommodation_planning": "住宿规划",
    "food_planning": "餐饮规划",
    "itinerary_generation": "行程生成",
    "budget_summarization": "预算汇总",
    "order_generation": "订单生成",
}

AGENCY_STEP_LABELS: dict[AgencyStep, str] = {
    "agency_requirement": "基础需求",
    "agency_product_match": "匹配方案",
    "agency_plan_draft": "方案草案",
    "agency_feedback": "方案确认",
    "agency_report": "报告生成",
}

STEP_STATE_FIELDS: dict[PlanningStep, list[str]] = {
    "requirement_collection": ["user_requirement"],
    "destination_recommendation": ["selected_destination", "destination_options"],
    "transport_planning": [
        "selected_transport",
        "selected_transport_option",
        "transport_options",
    ],
    "accommodation_planning": [
        "selected_accommodation_types",
        "selected_accommodation_option",
        "accommodation_options",
    ],
    "food_planning": ["selected_food_types", "food_options"],
    "itinerary_generation": ["itinerary"],
    "budget_summarization": ["budget"],
    "order_generation": ["order_id", "report", "report_data"],
}
