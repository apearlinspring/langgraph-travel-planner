"""
Train query tools that wrap 12306 MCP APIs with planner-friendly inputs.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from langchain.tools import tool

from app.mcp_core.client import get_mcp_client
from app.utils.logger import app_logger


DEFAULT_TRAIN_FILTER_FLAGS = "GD"
MAX_TEXT_CHARS = 3500


@dataclass
class StationResolution:
    name: str
    code: str
    source: str


def _extract_text_blocks(result: Any) -> str:
    if isinstance(result, list):
        text_blocks = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                text_blocks.append(item.get("text", ""))
            else:
                text_blocks.append(str(item))
        return "\n".join(text_blocks)
    return str(result)


def _parse_loose_payload(text: str) -> Any:
    payload_text = text.strip()
    if ":" in payload_text and not payload_text.startswith(("{", "[")):
        _, possible_payload = payload_text.split(":", 1)
        if possible_payload.strip().startswith(("{", "[")):
            payload_text = possible_payload.strip()

    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(payload_text)
    except (SyntaxError, ValueError):
        return text


def _find_station_code(payload: Any, preferred_name: str = "") -> str | None:
    preferred = preferred_name.strip().rstrip("市")
    code_keys = {
        "station_code",
        "stationcode",
        "telecode",
        "station_telecode",
        "code",
    }

    def pick_code(value: Any) -> str | None:
        if isinstance(value, str) and re.fullmatch(r"[A-Z]{3,4}", value.strip()):
            return value.strip()
        return None

    def walk(value: Any) -> str | None:
        if isinstance(value, dict):
            if preferred:
                for key, item in value.items():
                    if preferred in str(key):
                        found = walk(item)
                        if found:
                            return found

            for key, item in value.items():
                normalized_key = str(key).replace("-", "_").lower()
                if normalized_key in code_keys:
                    found = pick_code(item)
                    if found:
                        return found

            for item in value.values():
                found = walk(item)
                if found:
                    return found

        if isinstance(value, list):
            preferred_items = []
            other_items = []
            for item in value:
                item_text = str(item)
                if preferred and preferred in item_text:
                    preferred_items.append(item)
                else:
                    other_items.append(item)
            for item in preferred_items + other_items:
                found = walk(item)
                if found:
                    return found

        if isinstance(value, str):
            patterns = [
                r"(?:station[_ ]?code|telecode|code)['\"]?\s*[:=]\s*['\"]?([A-Z]{3,4})",
                r"车站代码[:：\s]+([A-Z]{3,4})",
                r"\b([A-Z]{3,4})\b",
            ]
            for pattern in patterns:
                match = re.search(pattern, value)
                if match:
                    return match.group(1)

        return None

    return walk(payload)


def _compact_text(text: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n...（结果较长，已截断展示）"


def _looks_empty_or_no_direct_ticket(text: str) -> bool:
    normalized = text.strip().lower()
    empty_markers = [
        "未查询到",
        "暂无",
        "没有符合",
        "无直达",
        "no data",
        "not found",
        "[]",
        "'data': []",
        '"data": []',
    ]
    return not normalized or any(marker in normalized for marker in empty_markers)


def _is_railway_empty_result_error(error: Exception) -> bool:
    message = str(error)
    empty_error_markers = [
        "Cannot read properties of undefined",
        "reading 'result'",
        "reading \"result\"",
    ]
    return any(marker in message for marker in empty_error_markers)


async def _get_railway_tool(tool_name: str) -> Any | None:
    manager = await get_mcp_client(servers=["12306-mcp"])
    tools = await manager.get_tools(servers=["12306-mcp"])
    for tool_instance in tools:
        if tool_instance.name == tool_name:
            return tool_instance
    return None


async def _invoke_with_fallbacks(tool_instance: Any, payloads: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    last_error: Exception | None = None
    for payload in payloads:
        try:
            result = await tool_instance.ainvoke(payload)
            return result, payload
        except Exception as exc:  # pragma: no cover - depends on remote MCP validation messages
            last_error = exc
            app_logger.warning(
                f"12306 tool payload failed: {tool_instance.name}, payload={payload}, error={exc}"
            )
    if last_error:
        raise last_error
    raise ValueError("No payload candidates provided")


async def _resolve_station(name: str) -> StationResolution:
    city_tool = await _get_railway_tool("get-station-code-of-citys")
    station_tool = await _get_railway_tool("get-station-code-by-names")
    if city_tool is None and station_tool is None:
        raise RuntimeError("12306 站点编码工具当前不可用")

    stripped = name.strip()
    attempts: list[tuple[str, Any, list[dict[str, Any]]]] = []
    if city_tool is not None:
        attempts.append(
            (
                "city",
                city_tool,
                [
                    {"citys": stripped},
                    {"cities": stripped, "format": "json"},
                    {"cities": stripped},
                    {"city": stripped, "format": "json"},
                    {"city": stripped},
                ],
            )
        )
    if station_tool is not None:
        attempts.append(
            (
                "station",
                station_tool,
                [
                    {"stationNames": stripped},
                    {"stationName": stripped, "format": "json"},
                    {"stationName": stripped},
                    {"name": stripped, "format": "json"},
                    {"name": stripped},
                ],
            )
        )

    errors = []
    for source, tool_instance, payloads in attempts:
        try:
            result, _ = await _invoke_with_fallbacks(tool_instance, payloads)
        except Exception as exc:  # pragma: no cover - remote MCP dependent
            errors.append(str(exc))
            continue
        text = _extract_text_blocks(result)
        code = _find_station_code(_parse_loose_payload(text), stripped)
        if code:
            return StationResolution(name=stripped, code=code, source=source)

    error_suffix = f"；最近错误：{errors[-1]}" if errors else ""
    raise RuntimeError(f"无法解析车站代码：{stripped}{error_suffix}")


def _ticket_payloads(
    origin_code: str,
    destination_code: str,
    departure_date: str,
    train_filter_flags: str,
    max_results: int,
) -> list[dict[str, Any]]:
    normalized_limit = min(max(max_results, 3), 10)
    return [
        {
            "date": departure_date,
            "fromStation": origin_code,
            "toStation": destination_code,
            "trainFilterFlags": train_filter_flags,
            "sortFlag": "startTime",
            "sortReverse": False,
            "limitedNum": normalized_limit,
            "format": "text",
        },
        {
            "date": departure_date,
            "fromStation": origin_code,
            "toStation": destination_code,
            "trainFilterFlags": train_filter_flags,
            "sortFlag": "startTime",
            "sortReverse": False,
            "limitedNum": normalized_limit,
        },
        {
            "date": departure_date,
            "fromStation": origin_code,
            "toStation": destination_code,
            "trainFilterFlags": train_filter_flags,
            "sortFlag": "duration",
            "sortReverse": False,
            "limitedNum": normalized_limit,
            "format": "text",
        },
    ]


@tool
async def query_train_options(
    origin_city: str,
    destination_city: str,
    departure_date: str,
    train_filter_flags: str = DEFAULT_TRAIN_FILTER_FLAGS,
    allow_transfer: bool = True,
    max_results: int = 5,
) -> str:
    """
    查询真实 12306 火车/高铁方案，自动解析站点编码，优先直达，无直达时查询中转。
    """

    tickets_tool = await _get_railway_tool("get-tickets")
    if tickets_tool is None:
        return "12306 余票查询服务当前不可用，请稍后再试，或先给出非实时交通建议。"

    try:
        origin_station = await _resolve_station(origin_city)
        destination_station = await _resolve_station(destination_city)
    except Exception as exc:
        return f"12306 站点编码失败：{exc}"

    normalized_flags = (train_filter_flags or DEFAULT_TRAIN_FILTER_FLAGS).upper()
    sections = [
        (
            f"火车查询条件：{origin_city}({origin_station.code}) -> "
            f"{destination_city}({destination_station.code})，{departure_date}，"
            f"车型筛选 {normalized_flags}"
        ),
        f"站点编码来源：出发地={origin_station.source}，目的地={destination_station.source}",
    ]

    app_logger.info(
        "调用 query_train_options: "
        f"{origin_city}({origin_station.code}) -> "
        f"{destination_city}({destination_station.code}), date={departure_date}"
    )

    try:
        direct_result, direct_payload = await _invoke_with_fallbacks(
            tickets_tool,
            _ticket_payloads(
                origin_station.code,
                destination_station.code,
                departure_date,
                normalized_flags,
                max_results,
            ),
        )
    except Exception as exc:
        if _is_railway_empty_result_error(exc):
            return (
                "12306 当前没有返回可用余票数据，可能是查询日期超出当前预售范围，"
                "或该日期车票数据尚未放出。建议改查更近日期，或稍后再次查询。"
            )
        return f"12306 直达余票查询失败：{exc}"

    direct_text = _compact_text(_extract_text_blocks(direct_result))
    sections.extend(["", "直达车次候选：", direct_text or "未返回可展示的直达车次。"])

    should_query_transfer = allow_transfer and _looks_empty_or_no_direct_ticket(direct_text)
    if should_query_transfer:
        transfer_tool = await _get_railway_tool("get-interline-tickets")
        if transfer_tool is not None:
            try:
                transfer_result, _ = await _invoke_with_fallbacks(
                    transfer_tool,
                    _ticket_payloads(
                        origin_station.code,
                        destination_station.code,
                        departure_date,
                        normalized_flags,
                        max_results,
                    ),
                )
                sections.extend(
                    [
                        "",
                        "中转/接续候选：",
                        _compact_text(_extract_text_blocks(transfer_result))
                        or "未返回可展示的中转方案。",
                    ]
                )
            except Exception as exc:  # pragma: no cover - remote MCP dependent
                if _is_railway_empty_result_error(exc):
                    sections.extend(
                        [
                            "",
                            "中转查询未返回可用数据，可能是日期超出预售范围或暂无接续方案。",
                        ]
                    )
                else:
                    sections.extend(["", f"中转查询未成功：{exc}"])
        else:
            sections.extend(["", "中转查询工具当前不可用。"])

    sections.extend(
        [
            "",
            f"实际调用参数：{direct_payload}",
            "提示：12306 余票、票价和停靠站会实时变化，正式购票前需要再次核实。",
        ]
    )
    return "\n".join(sections)
