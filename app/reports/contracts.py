"""Stable contracts for structured travel reports."""
from __future__ import annotations


REPORT_VERSION = "travel_report.v1"
REPORT_PLANNING_MODES = ("free_planning", "agency_plan")

REPORT_SECTIONS: tuple[dict[str, str], ...] = (
    {"id": "overview", "title": "行程概览"},
    {"id": "transport_accommodation", "title": "交通与住宿"},
    {"id": "itinerary", "title": "每日行程"},
    {"id": "map_routes", "title": "景点地图"},
    {"id": "agency_context", "title": "方案依据"},
    {"id": "budget", "title": "预算明细"},
    {"id": "budget_confidence", "title": "预算置信度与待核验项"},
    {"id": "risk", "title": "天气与风险提醒"},
    {"id": "adjustments", "title": "后续可调整"},
    {"id": "tool_audit_summary", "title": "顾问交付清单"},
)

REPORT_SECTION_IDS = tuple(section["id"] for section in REPORT_SECTIONS)
REQUIRED_REPORT_SECTION_IDS = set(REPORT_SECTION_IDS)

REQUIRED_REPORT_TOP_LEVEL_KEYS = {
    "version",
    "overview",
    "transport",
    "accommodation",
    "food_preferences",
    "itinerary",
    "map_routes",
    "agency_context",
    "budget",
    "budget_confidence",
    "risks",
    "adjustment_options",
    "evidence_bundle",
    "tool_audit_summary",
    "sections",
}


def report_sections() -> list[dict[str, str]]:
    """Return a copy of the canonical report section list."""

    return [dict(section) for section in REPORT_SECTIONS]
