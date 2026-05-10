"""Helpers for building and carrying tool audit events through state."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.tools.contracts import ToolAuditEvent, ToolAuditStatus, ToolEvidenceType


SENSITIVE_INPUT_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
SENSITIVE_INPUT_KEY_PARTS = tuple(SENSITIVE_INPUT_KEYS)

TOOL_LABELS = {
    "query_hotel_options": "住宿",
    "query_transport_options": "交通",
    "getHotelDetail": "住宿详情",
    "getHotelSearchTags": "酒店标签",
    "maps_geo": "地图地理编码",
    "maps_direction_driving": "自驾路线",
    "get_weather_forecast": "天气",
    "search_travel_info": "搜索",
}


@dataclass(frozen=True)
class ToolAuditContext:
    name: str
    started_at: float
    perf_counter_started_at: float


def start_tool_audit(name: str) -> ToolAuditContext:
    return ToolAuditContext(
        name=name,
        started_at=time.time(),
        perf_counter_started_at=time.perf_counter(),
    )


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key or "").lower()
    return any(part in normalized for part in SENSITIVE_INPUT_KEY_PARTS)


def _summarize_value(value: Any, *, max_list_items: int = 5, max_text_length: int = 160) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _summarize_value(item)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        summarized = [_summarize_value(item) for item in value[:max_list_items]]
        if len(value) > max_list_items:
            summarized.append(f"...(+{len(value) - max_list_items})")
        return summarized
    if isinstance(value, str):
        compact = " ".join(value.split())
        return compact[:max_text_length] + ("..." if len(compact) > max_text_length else "")
    return value


def summarize_tool_input(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {"input": _summarize_value(args)}
    return {
        str(key): _summarize_value(value)
        for key, value in (args or {}).items()
        if not _is_sensitive_key(key) and str(key) != "runtime"
    }


def summarize_tool_output(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        summary = _summarize_value(output)
        if isinstance(summary, dict):
            return summary
    if isinstance(output, str):
        compact = " ".join(output.split())
        return {
            "content_chars": len(output),
            "preview": compact[:180] + ("..." if len(compact) > 180 else ""),
        }
    if output is None:
        return {"empty": True}
    return {"type": output.__class__.__name__, "preview": _summarize_value(str(output))}


def build_tool_audit_event(
    context: ToolAuditContext,
    *,
    status: ToolAuditStatus,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any] | None = None,
    error_type: str | None = None,
    retry_count: int = 0,
    evidence_type: ToolEvidenceType = "unknown",
) -> ToolAuditEvent:
    return {
        "name": context.name,
        "started_at": context.started_at,
        "elapsed_seconds": round(time.perf_counter() - context.perf_counter_started_at, 3),
        "status": status,
        "input_summary": input_summary,
        "output_summary": output_summary or {},
        "error_type": error_type,
        "retry_count": max(int(retry_count or 0), 0),
        "evidence_type": evidence_type,
    }


def append_tool_audit_event(
    state: dict[str, Any] | None,
    update: dict[str, Any],
    event: ToolAuditEvent,
) -> dict[str, Any]:
    events = list((state or {}).get("tool_audit_events") or [])
    events.append(event)
    update["tool_audit_events"] = events
    return update


def _audit_event_message(event: dict[str, Any]) -> str:
    label = TOOL_LABELS.get(str(event.get("name") or ""), str(event.get("name") or "工具"))
    status = event.get("status") or "failed"
    error_type = event.get("error_type") or "unknown_error"
    if status == "timeout":
        return f"{label}：真实查询超时（{error_type}），出发前需要重新查询并二次核验。"
    if status == "skipped":
        return f"{label}：本轮查询因参数不完整被跳过（{error_type}），需要补齐信息后再核验。"
    return f"{label}：真实查询未得到可靠结果（{error_type}），当前只能按兜底估算处理。"


def pending_checks_from_audit_events(events: list[dict[str, Any]] | None) -> list[str]:
    checks: list[str] = []
    for event in events or []:
        status = event.get("status")
        if status not in {"failed", "timeout", "degraded", "skipped"}:
            continue
        message = _audit_event_message(event)
        if message not in checks:
            checks.append(message)
    return checks


def summarize_audit_events_for_report(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for event in events or []:
        summaries.append(
            {
                "name": event.get("name"),
                "status": event.get("status"),
                "elapsed_seconds": event.get("elapsed_seconds"),
                "error_type": event.get("error_type"),
                "retry_count": event.get("retry_count", 0),
                "evidence_type": event.get("evidence_type") or "unknown",
            }
        )
    return summaries
