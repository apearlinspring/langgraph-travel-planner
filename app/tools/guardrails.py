"""Pre-call validation for high-value travel planning tools."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.tools.contracts import ToolValidationResult


PLACEHOLDER_VALUES = {
    "",
    "unknown",
    "none",
    "null",
    "未确认",
    "待确认",
    "目的地",
    "城市",
    "出发地",
    "日期",
    "入住日期",
    "departure_date",
    "check_in_date",
    "destination",
    "origin",
}

VALID_BUDGET_LEVELS = {"economy", "comfort", "luxury"}
VALID_PLACE_TYPES = {"城市", "机场", "景点", "火车站", "地铁站", "酒店", "区/县", "详细地址"}
VALID_TRANSPORT_TYPES = {"flight", "train", "driving", None, ""}


def _is_placeholder(value: Any) -> bool:
    return str(value or "").strip().lower() in PLACEHOLDER_VALUES


def _validate_iso_date(value: Any, field_name: str) -> str | None:
    if _is_placeholder(value):
        return f"{field_name}缺失"
    text = str(value).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return f"{field_name}必须是 YYYY-MM-DD 格式"
    return None


def _int_in_range(value: Any, field_name: str, minimum: int, maximum: int) -> str | None:
    if not isinstance(value, int):
        return f"{field_name}必须是整数"
    if value < minimum or value > maximum:
        return f"{field_name}必须在 {minimum}-{maximum} 之间"
    return None


def _float_positive_or_none(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or value <= 0:
        return f"{field_name}必须是正数"
    return None


def _invalid_result(error_type: str, messages: list[str], args: dict[str, Any]) -> ToolValidationResult:
    return ToolValidationResult(
        ok=False,
        error_type=error_type,
        message="；".join(messages),
        normalized_args=args,
    )


def validate_hotel_query_args(args: dict[str, Any]) -> ToolValidationResult:
    messages: list[str] = []
    if _is_placeholder(args.get("destination")):
        messages.append("目的地缺失")
    if error := _validate_iso_date(args.get("check_in_date"), "入住日期"):
        messages.append(error)
    for field_name, minimum, maximum in [
        ("stay_nights", 1, 30),
        ("adult_count", 1, 20),
        ("children_count", 0, 20),
        ("size", 1, 10),
    ]:
        if error := _int_in_range(args.get(field_name), field_name, minimum, maximum):
            messages.append(error)
    if args.get("budget_level") not in VALID_BUDGET_LEVELS:
        messages.append("预算等级只能是 economy、comfort 或 luxury")
    if args.get("place_type") not in VALID_PLACE_TYPES:
        messages.append("地点类型不在支持范围内")
    if error := _float_positive_or_none(args.get("max_price_per_night"), "每晚最高预算"):
        messages.append(error)
    if messages:
        return _invalid_result("invalid_hotel_query_args", messages, args)
    return ToolValidationResult(ok=True, normalized_args=args)


def validate_transport_query_args(args: dict[str, Any]) -> ToolValidationResult:
    messages: list[str] = []
    if _is_placeholder(args.get("origin_city")):
        messages.append("出发城市缺失")
    if _is_placeholder(args.get("destination_city")):
        messages.append("目的地城市缺失")
    if error := _validate_iso_date(args.get("departure_date"), "出发日期"):
        messages.append(error)
    if args.get("transport_type") not in VALID_TRANSPORT_TYPES:
        messages.append("交通方式只能是 flight、train、driving 或留空")
    if messages:
        return _invalid_result("invalid_transport_query_args", messages, args)
    return ToolValidationResult(ok=True, normalized_args=args)


def validate_driving_query_args(args: dict[str, Any]) -> ToolValidationResult:
    messages: list[str] = []
    if _is_placeholder(args.get("origin")):
        messages.append("自驾出发地缺失")
    if _is_placeholder(args.get("destination")):
        messages.append("自驾目的地缺失")
    if messages:
        return _invalid_result("invalid_driving_query_args", messages, args)
    return ToolValidationResult(ok=True, normalized_args=args)


def validate_destination_query_args(args: dict[str, Any]) -> ToolValidationResult:
    destination = str((args or {}).get("destination") or "").strip()
    query = str((args or {}).get("query") or "").strip()
    if _is_placeholder(destination):
        return _invalid_result(
            "invalid_destination_query_args",
            ["目的地缺失"],
            {**(args or {}), "destination": destination, "query": query},
        )
    if len(query) > 500:
        return _invalid_result(
            "invalid_destination_query_args",
            ["目的地查询问题过长，请压缩到 500 字以内"],
            {**(args or {}), "destination": destination, "query": query[:500]},
        )
    return ToolValidationResult(
        ok=True,
        normalized_args={**(args or {}), "destination": destination, "query": query},
    )


def validate_rag_query_args(args: dict[str, Any]) -> ToolValidationResult:
    query = str((args or {}).get("query") or "").strip()
    if _is_placeholder(query):
        return _invalid_result(
            "invalid_rag_query_args",
            ["检索问题缺失"],
            {**(args or {}), "query": query},
        )
    if len(query) > 500:
        return _invalid_result(
            "invalid_rag_query_args",
            ["检索问题过长，请压缩到 500 字以内"],
            {**(args or {}), "query": query[:500]},
        )
    return ToolValidationResult(ok=True, normalized_args={**(args or {}), "query": query})


def validate_mcp_tool_args(args: dict[str, Any]) -> ToolValidationResult:
    if not isinstance(args, dict):
        return _invalid_result("invalid_mcp_tool_args", ["工具参数必须是对象"], {})
    if any(_is_placeholder(value) for value in args.values() if isinstance(value, str)):
        return _invalid_result(
            "invalid_mcp_tool_args",
            ["工具参数包含未确认占位符"],
            args,
        )
    return ToolValidationResult(ok=True, normalized_args=args)
