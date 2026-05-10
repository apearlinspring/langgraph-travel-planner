"""
Core travel-planning state schema.
"""
from typing import Literal, Optional

from langchain.agents import AgentState
from typing_extensions import NotRequired, TypedDict

from app.core.workflow import INITIAL_PLANNING_STEP, PlanningStep

TravelStyle = Literal["relaxation", "culture", "adventure", "food"]
BudgetLevel = Literal["economy", "comfort", "luxury"]
TransportType = Literal["flight", "train", "driving"]
AccommodationType = Literal["star_hotel", "economy_hotel", "hostel", "youth_hostel"]
FoodType = Literal["specialty", "chain", "local"]
PlanningMode = Literal["free_planning", "agency_plan"]


class UserRequirement(TypedDict):
    departure_city: str
    destination: Optional[str]
    departure_date: str
    travel_days: int
    adult_count: int
    children_count: int
    budget_min: Optional[float]
    budget_max: Optional[float]
    budget_level: BudgetLevel
    travel_styles: list[TravelStyle]
    special_needs: Optional[str]
    planning_mode: NotRequired[PlanningMode]
    planning_mode_reason: NotRequired[str]
    planning_mode_confirmed: NotRequired[bool]


class DestinationInfo(TypedDict):
    name: str
    description: str
    weather_info: Optional[str]
    attractions: list[str]
    attraction_pois: NotRequired[list["POIInfo"]]
    estimated_cost: Optional[float]


class POIInfo(TypedDict):
    name: str
    area: NotRequired[str]
    best_time: NotRequired[str]
    duration_hours: NotRequired[float]
    reservation_required: NotRequired[bool]
    indoor: NotRequired[bool]
    estimated_cost: NotRequired[float]
    tags: NotRequired[list[str]]


class TransportInfo(TypedDict):
    transport_type: TransportType
    details: str
    departure_time: NotRequired[str]
    arrival_time: NotRequired[str]
    duration: NotRequired[str]
    price: NotRequired[float]
    source: NotRequired[str]


class AccommodationInfo(TypedDict):
    hotel_id: NotRequired[int]
    name: str
    type: AccommodationType
    location: str
    price_per_night: float
    rating: Optional[float]
    amenities: list[str]
    booking_url: NotRequired[str]
    source: NotRequired[str]


class FoodInfo(TypedDict):
    type: FoodType
    recommendations: list[str]
    estimated_daily_cost: float
    food_pois: NotRequired[list["FoodPOIInfo"]]


class FoodPOIInfo(TypedDict):
    name: str
    type: FoodType
    area: NotRequired[str]
    meal_time: NotRequired[str]
    average_cost: NotRequired[float]
    reservation_required: NotRequired[bool]
    queue_risk: NotRequired[str]
    suitable_for: NotRequired[list[str]]
    tags: NotRequired[list[str]]


class ItineraryDay(TypedDict):
    day_number: int
    theme: NotRequired[str]
    activities: list[str]
    time_blocks: NotRequired[list[str]]
    meals: list[str]
    accommodation: str
    transport_note: NotRequired[str]
    plan_b: NotRequired[str]
    route_note: NotRequired[str]
    route_points: NotRequired[list[str]]
    route_summary: NotRequired[str]
    map_route: NotRequired[str]
    risk_notes: NotRequired[list[str]]


class BudgetLineItem(TypedDict):
    key: str
    label: str
    amount: float
    per_person: float
    basis: str
    confidence: str


class BudgetBreakdown(TypedDict):
    transport: float
    accommodation: float
    food: float
    attractions: float
    misc: float
    total: float
    per_person: NotRequired[float]
    currency: NotRequired[str]
    total_people: NotRequired[int]
    travel_days: NotRequired[int]
    nights: NotRequired[int]
    line_items: NotRequired[list[BudgetLineItem]]
    assumptions: NotRequired[list[str]]
    confidence_level: NotRequired[str]
    confirmed_items: NotRequired[list[str]]
    estimated_items: NotRequired[list[str]]
    verification_items: NotRequired[list[str]]
    budget_confidence: NotRequired["BudgetConfidenceData"]


class BudgetConfidenceData(TypedDict):
    level: str
    confirmed_items: list[str]
    estimated_items: list[str]
    verification_items: list[str]


class ReportData(TypedDict, total=False):
    version: str
    title: str
    subtitle: str
    overview: dict
    transport: dict
    accommodation: dict
    itinerary: list[dict]
    map_routes: list[dict]
    budget: dict
    budget_confidence: BudgetConfidenceData
    risks: list[str]
    adjustment_options: list[str]
    sections: list[dict]


class TravelState(AgentState):
    current_step: NotRequired[PlanningStep]
    planning_mode: NotRequired[PlanningMode]
    planning_mode_reason: NotRequired[str]
    planning_mode_confirmed: NotRequired[bool]
    evidence_bundle: NotRequired[dict]
    tool_audit_events: NotRequired[list[dict]]

    user_requirement: NotRequired[UserRequirement]

    selected_destination: NotRequired[str]
    selected_transport: NotRequired[TransportType]
    selected_transport_option: NotRequired[TransportInfo]
    selected_accommodation_types: NotRequired[list[AccommodationType]]
    selected_accommodation_option: NotRequired[AccommodationInfo]
    selected_food_types: NotRequired[list[FoodType]]
    selected_food_pois: NotRequired[list[FoodPOIInfo]]

    destination_options: NotRequired[list[DestinationInfo]]
    transport_options: NotRequired[list[TransportInfo]]
    accommodation_options: NotRequired[list[AccommodationInfo]]
    food_options: NotRequired[list[FoodInfo]]

    itinerary: NotRequired[list[ItineraryDay]]
    budget: NotRequired[BudgetBreakdown]
    report: NotRequired[str]
    report_data: NotRequired[ReportData]
    order_id: NotRequired[str]

    approval_pending: NotRequired[bool]
    approval_reason: NotRequired[str]

    user_id: NotRequired[str]
    session_id: NotRequired[str]
    created_at: NotRequired[float]
    updated_at: NotRequired[float]


def create_initial_state(user_id: str, session_id: str) -> TravelState:
    import time

    return TravelState(
        messages=[],
        current_step=INITIAL_PLANNING_STEP,
        destination_options=[],
        transport_options=[],
        accommodation_options=[],
        food_options=[],
        approval_pending=False,
        planning_mode_confirmed=False,
        tool_audit_events=[],
        user_id=user_id,
        session_id=session_id,
        created_at=time.time(),
        updated_at=time.time(),
    )
