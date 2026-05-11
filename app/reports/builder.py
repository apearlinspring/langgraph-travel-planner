"""High-level structured report builder."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agency.evidence import build_rule_evidence
from app.agency.pricing_rules import (
    budget_confidence_payload,
    build_adjustment_options,
    build_quote_policy,
    format_budget_fit,
)
from app.agency.product_rules import build_agency_context, build_light_product
from app.agency.risk_rules import build_report_risk_lines
from app.reports.contracts import REPORT_VERSION, report_sections
from app.reports.render_markdown import render_report_markdown
from app.reports.route_builder import normalize_report_route_alignment
from app.reports.validators import ReportValidationResult, validate_report_data
from app.tools.audit import pending_checks_from_audit_events, summarize_audit_events_for_report


@dataclass(frozen=True)
class ReportBundle:
    """A validated structured report and its Markdown rendering."""

    report_data: dict[str, Any]
    markdown: str
    validation: ReportValidationResult


def build_report_bundle(report_data: dict[str, Any]) -> ReportBundle:
    """Validate report_data and render Markdown from the same source payload."""

    validation = validate_report_data(report_data)
    markdown = render_report_markdown(report_data) if validation.ok else ""
    return ReportBundle(
        report_data=report_data,
        markdown=markdown,
        validation=validation,
    )


def _clean_report_line(line: Any) -> str:
    return str(line or "").strip().lstrip("-").strip()


def _dedupe_report_points(points: list[str], max_items: int = 6) -> list[str]:
    picked = []
    for point in points:
        normalized = str(point or "").strip()
        if not normalized or normalized in picked:
            continue
        picked.append(normalized)
        if len(picked) >= max_items:
            break
    return picked


def format_report_people(requirement: dict[str, Any]) -> str:
    adult_count = requirement.get("adult_count") or 0
    children_count = requirement.get("children_count") or 0
    parts = []
    if adult_count:
        parts.append(f"{adult_count} 位成人")
    if children_count:
        parts.append(f"{children_count} 位儿童")
    return "、".join(parts) if parts else "人数待确认"


def format_report_duration(requirement: dict[str, Any]) -> str:
    travel_days = requirement.get("travel_days")
    if isinstance(travel_days, int) and travel_days > 0:
        nights = max(travel_days - 1, 0)
        return f"{travel_days}天{nights}晚"
    return "天数待确认"


def format_report_route_label(state: dict[str, Any], requirement: dict[str, Any]) -> str:
    departure_city = requirement.get("departure_city") or "出发地待确认"
    destination = state.get("selected_destination") or requirement.get("destination") or "目的地待确认"
    return f"{departure_city} → {destination}"


def build_report_evidence_bundle(
    agency_context: dict[str, Any],
    budget: dict[str, Any],
    route_summaries: list[dict[str, Any]],
    selected_transport_option: dict[str, Any],
    selected_accommodation: dict[str, Any],
    tool_audit_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    categories = agency_context.get("categories") or {}
    transport_source = selected_transport_option.get("source") or "user_or_rule"
    accommodation_source = selected_accommodation.get("source") or "user_or_rule"
    return {
        "source_type": "structured_state",
        "agency_categories": {
            category: len(lines) if isinstance(lines, list) else 0
            for category, lines in categories.items()
        },
        "price_evidence": {
            "confirmed": list(budget.get("confirmed_items") or []),
            "estimated": list(budget.get("estimated_items") or []),
            "verification": list(budget.get("verification_items") or []),
        },
        "tool_sources": {
            "transport": transport_source,
            "accommodation": accommodation_source,
        },
        "tool_audit_events": summarize_audit_events_for_report(tool_audit_events),
        "route_evidence": [
            {
                "day_number": route.get("day_number"),
                "route_points": list(route.get("route_points") or []),
                "summary": route.get("summary") or "",
            }
            for route in route_summaries
        ],
    }


def build_report_tool_audit_summary(
    budget: dict[str, Any],
    route_summaries: list[dict[str, Any]],
    selected_transport_option: dict[str, Any],
    selected_accommodation: dict[str, Any],
    tool_audit_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    audit_pending_checks = pending_checks_from_audit_events(tool_audit_events)
    pending_checks = _dedupe_report_points(
        [
            *[_clean_report_line(item) for item in budget.get("estimated_items") or []],
            *[_clean_report_line(item) for item in budget.get("verification_items") or []],
            *[_clean_report_line(item) for item in audit_pending_checks],
        ],
        max_items=6,
    )
    if not pending_checks:
        pending_checks = [
            "正式预订或出发前复核交通票价、酒店政策、景点开放和天气变化。"
        ]

    used_sources = [
        f"交通：{selected_transport_option.get('source') or '用户选择/规则估算'}",
        f"住宿：{selected_accommodation.get('source') or '用户选择/规则估算'}",
        f"地图路线：已生成 {len(route_summaries)} 条分日路线节点",
        "预算：已拆分为已确认、估算和待核验项目",
    ]
    return {
        "readiness": "可交付，预订前需核验",
        "used_sources": used_sources,
        "pending_checks": pending_checks,
        "events": summarize_audit_events_for_report(tool_audit_events),
        "unsupported_actions": [
            "当前项目未接入真实支付服务，不生成支付链接。",
            "不承诺真实库存、真实锁价或真实预订成功。",
        ],
    }


def _sections_with_product_quote() -> list[dict[str, str]]:
    sections = report_sections()
    if any(section.get("id") == "product_quote" for section in sections):
        return sections

    insert_at = next(
        (
            index + 1
            for index, section in enumerate(sections)
            if section.get("id") == "agency_context"
        ),
        len(sections),
    )
    sections.insert(insert_at, {"id": "product_quote", "title": "产品与报价规则"})
    return sections


def build_travel_report_data(
    *,
    state: dict[str, Any],
    requirement: dict[str, Any],
    budget: dict[str, Any],
    itinerary: list[dict[str, Any]],
    route_summaries: list[dict[str, Any]],
    selected_transport_option: dict[str, Any],
    selected_accommodation: dict[str, Any],
    selected_food_types: list[str],
    transport_label: str,
    transport_summary: str,
    accommodation_summary: str,
    food_preferences_summary: str,
    weather_info: Any = None,
) -> dict[str, Any]:
    """Assemble the stable report_data contract from normalized planning state."""

    route_alignment = normalize_report_route_alignment(itinerary, route_summaries)
    itinerary = route_alignment.itinerary
    route_summaries = route_alignment.route_summaries

    itinerary_data = []
    for index, day in enumerate(itinerary):
        route_summary = route_summaries[index]
        itinerary_data.append(
            {
                "day_number": day.get("day_number"),
                "title": day.get("theme") or "当天安排",
                "route": route_summary,
                "time_blocks": list(day.get("time_blocks") or []),
                "activities": list(day.get("activities") or []),
                "meals": list(day.get("meals") or []),
                "accommodation": day.get("accommodation"),
                "transport_note": day.get("transport_note"),
                "route_note": day.get("route_note"),
                "plan_b": day.get("plan_b"),
                "risk_notes": list(day.get("risk_notes") or []),
            }
        )

    budget_items = budget.get("line_items") or []
    budget_confidence = budget_confidence_payload(budget)
    risks = [
        _clean_report_line(line)
        for line in build_report_risk_lines(
            itinerary,
            budget,
            weather_info=weather_info,
        )
    ]
    adjustment_options = [
        _clean_report_line(line)
        for line in build_adjustment_options(requirement, budget)
    ]
    light_product = build_light_product(requirement, state)
    quote_policy = budget.get("quote_policy") or build_quote_policy(
        requirement,
        budget,
        product=light_product,
        state=state,
    )
    agency_context = build_agency_context(
        requirement,
        state,
        quote_policy=quote_policy,
    )
    agency_context["quote_policy"] = quote_policy
    agency_context["rule_evidence"] = build_rule_evidence(
        light_product,
        quote_policy,
        agency_context.get("categories") or {},
    )
    evidence_bundle = build_report_evidence_bundle(
        agency_context,
        budget,
        route_summaries,
        selected_transport_option,
        selected_accommodation,
        state.get("tool_audit_events"),
    )
    if route_alignment.findings:
        evidence_bundle["route_alignment_findings"] = list(route_alignment.findings)
    tool_audit_summary = build_report_tool_audit_summary(
        budget,
        route_summaries,
        selected_transport_option,
        selected_accommodation,
        state.get("tool_audit_events"),
    )

    return {
        "version": REPORT_VERSION,
        "title": "个性化旅游规划报告",
        "subtitle": "最终旅行方案报告",
        "overview": {
            "route_label": format_report_route_label(state, requirement),
            "duration": format_report_duration(requirement),
            "people": format_report_people(requirement),
            "travel_styles": list(requirement.get("travel_styles") or []),
            "special_needs": requirement.get("special_needs") or "无特别备注",
        },
        "transport": {
            "type": state.get("selected_transport"),
            "label": transport_label,
            "summary": transport_summary,
            "option": dict(selected_transport_option),
        },
        "accommodation": {
            "summary": accommodation_summary,
            "option": dict(selected_accommodation),
        },
        "food_preferences": {
            "types": list(selected_food_types),
            "summary": food_preferences_summary,
        },
        "itinerary": itinerary_data,
        "map_routes": route_summaries,
        "agency_context": agency_context,
        "agency_product": light_product,
        "budget": {
            "currency": budget.get("currency", "CNY"),
            "total": budget.get("total"),
            "per_person": budget.get("per_person"),
            "items": budget_items,
            "assumptions": list(budget.get("assumptions") or []),
            "confidence_level": budget.get("confidence_level") or "待评估",
            "confirmed_items": list(budget.get("confirmed_items") or []),
            "estimated_items": list(budget.get("estimated_items") or []),
            "verification_items": list(budget.get("verification_items") or []),
            "confidence": budget_confidence,
            "fit": format_budget_fit(requirement, budget),
            "quote_policy": quote_policy,
        },
        "budget_confidence": budget_confidence,
        "quote_policy": quote_policy,
        "risks": risks,
        "adjustment_options": adjustment_options,
        "evidence_bundle": evidence_bundle,
        "tool_audit_summary": tool_audit_summary,
        "sections": _sections_with_product_quote(),
    }
