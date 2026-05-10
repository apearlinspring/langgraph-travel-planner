"""Render structured travel report data into user-visible Markdown."""
from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_money(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f} 元"
    return "待确认"


def _clean_line(value: Any) -> str:
    return str(value or "").strip().lstrip("-").strip()


def _format_report_highlights(itinerary: list[dict[str, Any]], max_days: int = 5) -> list[str]:
    highlights = []
    for day in itinerary[:max_days]:
        day_number = day.get("day_number", len(highlights) + 1)
        theme = day.get("title") or day.get("theme") or "当日安排"
        activities = [str(item) for item in _as_list(day.get("activities"))[:2]]
        activity_text = "；".join(activities) if activities else "具体活动待确认"
        highlights.append(f"- Day {day_number}｜{theme}：{activity_text}")
    if len(itinerary) > max_days:
        highlights.append(f"- 其余 {len(itinerary) - max_days} 天按已生成行程继续执行。")
    return highlights or ["- 行程明细待确认。"]


def _format_daily_itinerary(itinerary: list[dict[str, Any]], max_days: int = 8) -> list[str]:
    if not itinerary:
        return ["- 行程明细待确认。"]

    lines = []
    for day in itinerary[:max_days]:
        day_number = day.get("day_number", len(lines) + 1)
        title = day.get("title") or day.get("theme") or "当天安排"
        route = _as_dict(day.get("route"))
        lines.append(f"Day {day_number}：{title}")
        if route.get("summary"):
            lines.append(f"- 地图路线：{route['summary']}")

        time_blocks = _as_list(day.get("time_blocks"))
        if time_blocks:
            lines.extend(f"- {block}" for block in time_blocks)
        else:
            activities = _as_list(day.get("activities"))
            lines.extend(f"- {activity}" for activity in activities[:3])

        route_note = day.get("route_note") or day.get("transport_note")
        if route_note:
            lines.append(f"- 动线/交通：{route_note}")
        meals = _as_list(day.get("meals"))
        if meals:
            lines.append(f"- 餐饮：{'；'.join(str(item) for item in meals[:3])}")
        accommodation = day.get("accommodation")
        if accommodation:
            lines.append(f"- 住宿/落脚：{accommodation}")
        plan_b = day.get("plan_b")
        if plan_b:
            lines.append(f"- Plan B：{plan_b}")
        risk_notes = _as_list(day.get("risk_notes"))
        if risk_notes:
            risk_text = "；".join(str(item).strip() for item in risk_notes[:2] if str(item).strip())
            if risk_text:
                lines.append(f"- 当天风险：{risk_text}。")

    if len(itinerary) > max_days:
        lines.append(f"- 其余 {len(itinerary) - max_days} 天按已生成行程继续执行。")
    return lines


def _format_budget_items(budget: dict[str, Any]) -> list[str]:
    items = _as_list(budget.get("items"))
    if items:
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- {label}：{amount}（人均 {per_person}）｜{confidence}｜依据：{basis}".format(
                    label=item.get("label", "费用"),
                    amount=_format_money(item.get("amount")),
                    per_person=_format_money(item.get("per_person")),
                    confidence=item.get("confidence", "估算"),
                    basis=item.get("basis", "依据待补充"),
                )
            )
        lines.append(
            f"- 合计：{_format_money(budget.get('total'))}，人均：{_format_money(budget.get('per_person'))}"
        )
        return lines

    return [
        f"- 总计：{_format_money(budget.get('total'))}，人均：{_format_money(budget.get('per_person'))}",
    ]


def _format_budget_confidence(budget_confidence: dict[str, Any]) -> list[str]:
    lines = [f"- 预算置信度：{budget_confidence.get('level') or '待评估'}"]
    confirmed_items = _as_list(budget_confidence.get("confirmed_items"))
    estimated_items = _as_list(budget_confidence.get("estimated_items"))
    verification_items = _as_list(budget_confidence.get("verification_items"))

    lines.append("- 已确认/可追溯价格：")
    lines.extend(f"  - {item}" for item in confirmed_items) if confirmed_items else lines.append(
        "  - 暂无已确认锁价；当前价格均需以正式预订页为准。"
    )
    lines.append("- 估算项：")
    lines.extend(f"  - {item}" for item in estimated_items) if estimated_items else lines.append(
        "  - 暂无估算项。"
    )
    lines.append("- 待核验项：")
    lines.extend(f"  - {item}" for item in verification_items) if verification_items else lines.append(
        "  - 正式预订或出发前复核票价、酒店、景点开放和天气。"
    )
    return lines


def _format_tool_audit(tool_audit: dict[str, Any]) -> list[str]:
    if not tool_audit:
        return ["- 交付状态：待补充。"]

    lines = [f"- 交付状态：{tool_audit.get('readiness') or '可交付，预订前需核验'}"]
    used_sources = _as_list(tool_audit.get("used_sources"))
    pending_checks = _as_list(tool_audit.get("pending_checks"))
    unsupported_actions = _as_list(tool_audit.get("unsupported_actions"))

    if used_sources:
        lines.append("- 已用来源：")
        lines.extend(f"  - {item}" for item in used_sources)
    if pending_checks:
        lines.append("- 顾问核验清单：")
        lines.extend(f"  - {item}" for item in pending_checks)
    if unsupported_actions:
        lines.append("- 不支持承诺：")
        lines.extend(f"  - {item}" for item in unsupported_actions)
    return lines


def render_report_markdown(report_data: dict[str, Any]) -> str:
    """Render a structured travel report into Markdown."""

    overview = _as_dict(report_data.get("overview"))
    transport = _as_dict(report_data.get("transport"))
    accommodation = _as_dict(report_data.get("accommodation"))
    food_preferences = _as_dict(report_data.get("food_preferences"))
    itinerary = [_as_dict(day) for day in _as_list(report_data.get("itinerary"))]
    map_routes = [_as_dict(route) for route in _as_list(report_data.get("map_routes"))]
    agency_context = _as_dict(report_data.get("agency_context"))
    budget = _as_dict(report_data.get("budget"))
    budget_confidence = _as_dict(report_data.get("budget_confidence"))
    tool_audit = _as_dict(report_data.get("tool_audit_summary"))

    travel_styles = "、".join(str(item) for item in _as_list(overview.get("travel_styles"))) or "待确认"
    map_lines = [
        str(route.get("map_label") or route.get("summary"))
        for route in map_routes
        if route.get("map_label") or route.get("summary")
    ] or ["总览：路线节点待补充"]
    assumption_lines = [
        f"- {item}" for item in _as_list(budget.get("assumptions"))
    ] or ["- 费用依据待补充，建议以正式预订页面为准。"]
    risk_lines = [
        f"- {_clean_line(item)}"
        for item in _as_list(report_data.get("risks"))
        if _clean_line(item)
    ] or ["- 出发前需复核天气、交通、酒店和预约状态。"]
    adjustment_lines = [
        f"- {_clean_line(item)}"
        for item in _as_list(report_data.get("adjustment_options"))
        if _clean_line(item)
    ] or ["- 可继续调整交通、住宿、景点顺序或预算。"]
    lines = [
        f"# {report_data.get('title') or '个性化旅游规划报告'}",
        str(report_data.get("subtitle") or "最终旅行方案报告"),
        "",
        (
            "行程概览："
            f"{overview.get('route_label') or '路线待确认'}，"
            f"{overview.get('duration') or '天数待确认'}，"
            f"{overview.get('people') or '人数待确认'}，"
            f"主题偏好：{travel_styles}。"
            f"整体节奏以顺路、留白和可执行为主，特殊需求：{overview.get('special_needs') or '无特别备注'}。"
        ),
        "",
        "交通与住宿：",
        f"- 交通：{transport.get('label') or transport.get('type') or '未确认'}；{transport.get('summary') or '具体班次/路线待确认'}",
        f"- 住宿：{accommodation.get('summary') or '住宿待结合偏好确认'}",
        f"- 餐饮偏好：{food_preferences.get('summary') or '待确认'}",
        "",
        "行程亮点：",
        *_format_report_highlights(itinerary),
        "",
        "每日行程：",
        *_format_daily_itinerary(itinerary),
        "",
        "景点地图：",
        *map_lines,
        "",
        "方案依据：",
        f"- {agency_context.get('summary') or '方案依据待补充。'}",
        *[
            f"- 方案标准：{item}"
            for item in _as_list(agency_context.get("highlights"))
        ],
        "",
        "预算明细：",
        *_format_budget_items(budget),
        f"- {budget.get('fit') or '预算匹配：待人工复核。'}",
        "",
        "费用依据：",
        *assumption_lines,
        "",
        "预算置信度与待核验项：",
        *_format_budget_confidence(budget_confidence),
        "",
        "天气与风险提醒：",
        *risk_lines,
        "",
        "后续可调整：",
        *adjustment_lines,
        "",
        "顾问交付清单：",
        *_format_tool_audit(tool_audit),
    ]
    return "\n".join(lines)
