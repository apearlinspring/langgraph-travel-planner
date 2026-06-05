"""Validation helpers for structured travel reports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.reports.contracts import (
    REPORT_PLANNING_MODES,
    REPORT_VERSION,
    REQUIRED_REPORT_SECTION_IDS,
    REQUIRED_REPORT_TOP_LEVEL_KEYS,
)

ROUTE_SEGMENT_VERIFICATION_STATUSES = {
    "verified",
    "estimated",
    "needs_live_route",
}


@dataclass(frozen=True)
class ReportValidationResult:
    """Validation result for a structured report payload."""

    ok: bool
    missing_fields: list[str]
    missing_sections: list[str]
    route_mismatches: list[str]
    version_error: str | None = None

    @property
    def issues(self) -> list[str]:
        issues = []
        if self.version_error:
            issues.append(self.version_error)
        if self.missing_fields:
            issues.append(f"缺少顶层字段：{'、'.join(self.missing_fields)}")
        if self.missing_sections:
            issues.append(f"缺少报告章节：{'、'.join(self.missing_sections)}")
        issues.extend(self.route_mismatches)
        return issues

    def to_user_message(self) -> str:
        if self.ok:
            return "结构化报告校验通过。"
        return "最终报告生成失败，缺少必要结构：" + "；".join(self.issues)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _section_ids(report_data: dict[str, Any]) -> set[str]:
    return {
        str(section.get("id"))
        for section in _as_list(report_data.get("sections"))
        if isinstance(section, dict) and section.get("id")
    }


def _route_point_label(point: Any) -> str:
    if isinstance(point, dict):
        for key in ("label", "name", "title", "address"):
            value = point.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
    return str(point or "").strip()


def _route_points(route: dict[str, Any]) -> list[str]:
    raw_points = route.get("route_points") or route.get("points") or []
    return [label for point in _as_list(raw_points) if (label := _route_point_label(point))]


def _validate_route_segment_contract(
    route: dict[str, Any],
    *,
    day_number: Any,
    route_mismatches: list[str],
) -> None:
    points = _route_points(route)
    if len(points) < 2:
        return

    segments = [item for item in _as_list(route.get("segments")) if isinstance(item, dict)]
    expected_count = len(points) - 1
    if len(segments) != expected_count:
        route_mismatches.append(
            f"Day {day_number} 路段数量必须等于路线点之间的连接数。"
        )
        return

    for index, segment in enumerate(segments, start=1):
        selected_mode = str(segment.get("selected_mode") or segment.get("mode") or "").strip()
        alternatives = [
            item for item in _as_list(segment.get("alternatives")) if isinstance(item, dict)
        ]
        verification_status = str(segment.get("verification_status") or "").strip()
        if not selected_mode:
            route_mismatches.append(f"Day {day_number} 第 {index} 段缺少 selected_mode。")
        if "locked_by_user" not in segment or not isinstance(segment.get("locked_by_user"), bool):
            route_mismatches.append(f"Day {day_number} 第 {index} 段缺少 locked_by_user 布尔值。")
        if verification_status not in ROUTE_SEGMENT_VERIFICATION_STATUSES:
            route_mismatches.append(f"Day {day_number} 第 {index} 段 verification_status 无效。")
        if not alternatives:
            route_mismatches.append(f"Day {day_number} 第 {index} 段缺少交通候选 alternatives。")
        elif not any(str(option.get("mode") or "").strip() == selected_mode for option in alternatives):
            route_mismatches.append(f"Day {day_number} 第 {index} 段候选中缺少当前 selected_mode。")


def validate_report_data(report_data: dict[str, Any]) -> ReportValidationResult:
    """Validate the minimum report contract required for delivery and export."""

    if not isinstance(report_data, dict):
        return ReportValidationResult(
            ok=False,
            missing_fields=sorted(REQUIRED_REPORT_TOP_LEVEL_KEYS),
            missing_sections=sorted(REQUIRED_REPORT_SECTION_IDS),
            route_mismatches=["report_data 必须是字典。"],
            version_error=f"报告版本必须是 {REPORT_VERSION}。",
        )

    missing_fields = sorted(REQUIRED_REPORT_TOP_LEVEL_KEYS - set(report_data))
    missing_sections = sorted(REQUIRED_REPORT_SECTION_IDS - _section_ids(report_data))
    version_error = (
        None
        if report_data.get("version") == REPORT_VERSION
        else f"报告版本必须是 {REPORT_VERSION}。"
    )

    itinerary = [_as_dict(day) for day in _as_list(report_data.get("itinerary"))]
    map_routes = [_as_dict(route) for route in _as_list(report_data.get("map_routes"))]
    route_map = _as_dict(report_data.get("route_map"))
    route_map_days = [_as_dict(day) for day in _as_list(route_map.get("days"))]
    route_mismatches: list[str] = []
    if not itinerary:
        route_mismatches.append("每日行程不能为空。")
    if not map_routes:
        route_mismatches.append("地图路线不能为空。")
    if itinerary and map_routes and len(itinerary) != len(map_routes):
        route_mismatches.append("每日行程数量必须和地图路线数量一致。")
        if len(itinerary) > len(map_routes):
            for day in itinerary[len(map_routes):]:
                day_number = day.get("day_number") or "?"
                route_mismatches.append(f"Day {day_number} 缺少地图路线摘要。")
        else:
            for route in map_routes[len(itinerary):]:
                day_number = route.get("day_number") or "?"
                route_mismatches.append(f"地图路线 Day {day_number} 缺少对应每日行程。")
    if itinerary and map_routes:
        for index in range(min(len(itinerary), len(map_routes))):
            day = itinerary[index]
            route = map_routes[index]
            day_number = day.get("day_number") or route.get("day_number") or "?"
            day_summary = _as_dict(day.get("route")).get("summary")
            route_summary = route.get("summary")
            if day_summary != route_summary:
                route_mismatches.append(f"Day {day_number} 行程路线摘要与地图摘要不一致。")
            _validate_route_segment_contract(
                _as_dict(day.get("route")),
                day_number=day_number,
                route_mismatches=route_mismatches,
            )
            _validate_route_segment_contract(
                route,
                day_number=day_number,
                route_mismatches=route_mismatches,
            )

    if route_map:
        if not route_map_days:
            route_mismatches.append("route_map.days 不能为空。")
        if itinerary and route_map_days and len(route_map_days) != len(itinerary):
            route_mismatches.append("route_map.days 数量必须和每日行程数量一致。")
        for index, route_day in enumerate(route_map_days):
            day_number = route_day.get("day_number") or index + 1
            points = _as_list(route_day.get("points"))
            if len(points) < 2:
                route_mismatches.append(f"route_map Day {day_number} 至少需要 2 个路线点。")
            _validate_route_segment_contract(
                route_day,
                day_number=day_number,
                route_mismatches=route_mismatches,
            )

    agency_context = _as_dict(report_data.get("agency_context"))
    if "agency_context" not in missing_fields and agency_context.get("mode") not in REPORT_PLANNING_MODES:
        route_mismatches.append(
            "agency_context.mode 必须是 free_planning 或 agency_plan。"
        )

    ok = not (missing_fields or missing_sections or route_mismatches or version_error)
    return ReportValidationResult(
        ok=ok,
        missing_fields=missing_fields,
        missing_sections=missing_sections,
        route_mismatches=route_mismatches,
        version_error=version_error,
    )
