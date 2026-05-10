"""Validation helpers for structured travel reports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.reports.contracts import (
    REPORT_VERSION,
    REQUIRED_REPORT_SECTION_IDS,
    REQUIRED_REPORT_TOP_LEVEL_KEYS,
)


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
    route_mismatches: list[str] = []
    if len(itinerary) != len(map_routes):
        route_mismatches.append("每日行程数量必须和地图路线数量一致。")
    else:
        for day, route in zip(itinerary, map_routes):
            day_summary = _as_dict(day.get("route")).get("summary")
            route_summary = route.get("summary")
            if day_summary != route_summary:
                day_number = day.get("day_number") or route.get("day_number") or "?"
                route_mismatches.append(f"Day {day_number} 行程路线摘要与地图摘要不一致。")

    ok = not (missing_fields or missing_sections or route_mismatches or version_error)
    return ReportValidationResult(
        ok=ok,
        missing_fields=missing_fields,
        missing_sections=missing_sections,
        route_mismatches=route_mismatches,
        version_error=version_error,
    )
