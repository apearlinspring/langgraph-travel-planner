"""Scenic ticket reference provider backed by public references and search."""
from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.rag.contracts import parse_markdown_metadata
from app.utils.logger import app_logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENIC_TICKET_CATALOG_PATH = (
    PROJECT_ROOT
    / "data"
    / "documents"
    / "internal"
    / "scenic_tickets"
    / "scenic_ticket_reference.md"
)
SCENIC_TICKET_COLLECTION_DATE = "2026-05-19"
PUBLIC_SEARCH_PROVIDER = "public_web_search"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _split_scenic_names(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = [str(item) for item in _as_list(value) if item is not None]
    names: list[str] = []
    for raw in raw_values:
        for part in raw.replace("，", ",").replace("、", ",").split(","):
            name = part.strip()
            if name and name not in names:
                names.append(name)
    return names


def _normalize_ticket_item(raw: dict[str, Any]) -> dict[str, Any]:
    item = dict(raw)
    if "adult_price" in item:
        try:
            item["adult_price"] = float(item["adult_price"])
        except (TypeError, ValueError):
            item["adult_price"] = None
    item.setdefault("collected_at", SCENIC_TICKET_COLLECTION_DATE)
    item.setdefault("provider", "curated_rag_ticket_catalog")
    item.setdefault("requires_verification", True)
    item.setdefault(
        "disclaimer",
        "公开参考价，不代表实时库存、预约成功或锁价；正式预订前需以官方购票页或公开票务页二次核验。",
    )
    return item


def build_public_ticket_search_query(destination: Any, scenic_names: Any = None) -> str:
    """Build a public-web query for scenic ticket references."""

    destination_text = _as_text(destination)
    names = _split_scenic_names(scenic_names)
    subject = " ".join([destination_text, *names]).strip() or "景点"
    return f"{subject} 门票 票价 预约 开放时间 官方"


def _extract_json_payload(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, tuple) and raw_result:
        raw_result = raw_result[0]
    if isinstance(raw_result, dict):
        return raw_result
    text = str(raw_result or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def _extract_price_label(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    patterns = [
        r"(?:成人票|门票|票价|价格|参考价)[^。；\n]{0,35}?(?:¥|￥)?\s*\d+(?:\.\d+)?\s*元(?:起|/人|左右)?",
        r"(?:¥|￥)\s*\d+(?:\.\d+)?\s*(?:元)?(?:起|/人|左右)?",
        r"\d+(?:\.\d+)?\s*元(?:起|/人|左右)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(0).strip()
    return "公开搜索结果未稳定识别具体票价，请打开来源页核验"


def _match_result_name(
    destination: str,
    scenic_names: list[str],
    title: str,
    content: str,
) -> str:
    text = f"{title} {content}"
    for name in scenic_names:
        if name and name in text:
            return name
    if scenic_names:
        return scenic_names[0]
    return f"{destination or '目的地'}景点门票公开搜索结果"


def _normalize_public_search_payload(
    *,
    destination: str,
    scenic_names: Any,
    query: str,
    raw_result: Any,
) -> dict[str, Any]:
    payload = _extract_json_payload(raw_result)
    queried_at = datetime.now().isoformat(timespec="seconds")
    base = {
        "provider": PUBLIC_SEARCH_PROVIDER,
        "provider_status": "public_search",
        "destination": destination or "目的地待确认",
        "query": query,
        "queried_at": queried_at,
        "collected_at": date.today().isoformat(),
        "items": [],
        "raw_answer": payload.get("answer"),
        "error": payload.get("error"),
        "disclaimer": (
            "公网搜索结果仅用于生成参考票价和核验入口，不代表实时库存、预约成功或锁价；"
            "正式预订前必须打开来源页二次核验。"
        ),
    }
    if payload.get("error"):
        base["provider_status"] = "public_search_unavailable"
        return base

    names = _split_scenic_names(scenic_names)
    results = [item for item in _as_list(payload.get("results")) if isinstance(item, dict)]
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for result in results[:5]:
        title = _as_text(result.get("title"))
        url = _as_text(result.get("url"))
        content = _as_text(result.get("content"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        name = _match_result_name(destination, names, title, content)
        items.append(
            {
                "destination": destination or "目的地待确认",
                "name": name,
                "price_label": _extract_price_label(f"{title} {content}"),
                "reservation_note": "按来源页的预约入口、实名规则和优惠政策二次核验",
                "open_note": "开放时间、停止入园和临时闭园以来源页/景区公告为准",
                "source": title or "公网搜索结果",
                "source_url": url,
                "collected_at": base["collected_at"],
                "queried_at": queried_at,
                "provider": PUBLIC_SEARCH_PROVIDER,
                "provider_status": "public_search",
                "requires_verification": True,
                "disclaimer": base["disclaimer"],
            }
        )
    base["items"] = items
    if not items:
        base["provider_status"] = "public_search_empty"
    return base


async def search_public_scenic_ticket_references(
    destination: Any,
    scenic_names: Any = None,
    *,
    max_results: int = 5,
) -> dict[str, Any]:
    """Search public web pages for scenic ticket references via the search MCP."""

    destination_text = _as_text(destination)
    query = build_public_ticket_search_query(destination_text, scenic_names)
    try:
        from app.tools.mcp_tools import get_search_tools

        search_tools = await get_search_tools()
    except Exception as exc:  # pragma: no cover - defensive around MCP startup
        app_logger.warning(f"Failed to load public scenic ticket search tool: {exc}")
        return {
            "provider": PUBLIC_SEARCH_PROVIDER,
            "provider_status": "public_search_unavailable",
            "destination": destination_text or "目的地待确认",
            "query": query,
            "queried_at": datetime.now().isoformat(timespec="seconds"),
            "collected_at": date.today().isoformat(),
            "items": [],
            "error": str(exc) or exc.__class__.__name__,
            "disclaimer": "公网搜索工具暂不可用；景点票价需人工打开官方/公开票务页面核验，不锁价。",
        }

    search_tool = next(
        (tool for tool in search_tools if getattr(tool, "name", "") == "search_travel_info"),
        search_tools[0] if search_tools else None,
    )
    if search_tool is None:
        return {
            "provider": PUBLIC_SEARCH_PROVIDER,
            "provider_status": "public_search_unavailable",
            "destination": destination_text or "目的地待确认",
            "query": query,
            "queried_at": datetime.now().isoformat(timespec="seconds"),
            "collected_at": date.today().isoformat(),
            "items": [],
            "error": "search_travel_info unavailable",
            "disclaimer": "公网搜索工具未就绪；景点票价需人工打开官方/公开票务页面核验，不锁价。",
        }

    try:
        raw_result = await search_tool.ainvoke(
            {"query": query, "max_results": min(max_results, 10)}
        )
    except Exception as exc:  # pragma: no cover - defensive around external search
        app_logger.warning(f"Public scenic ticket search failed: {exc}")
        raw_result = {"error": str(exc) or exc.__class__.__name__}
    return _normalize_public_search_payload(
        destination=destination_text,
        scenic_names=scenic_names,
        query=query,
        raw_result=raw_result,
    )


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive thread bridge
            error = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=20)
    if thread.is_alive():
        return {
            "provider": PUBLIC_SEARCH_PROVIDER,
            "provider_status": "public_search_timeout",
            "items": [],
            "error": "public search timed out",
        }
    if error is not None:
        raise error
    return result


def search_public_scenic_ticket_references_sync(
    destination: Any,
    scenic_names: Any = None,
    *,
    max_results: int = 5,
) -> dict[str, Any]:
    """Synchronous bridge for the state-transition tool."""

    return _run_coro_sync(
        search_public_scenic_ticket_references(
            destination,
            scenic_names,
            max_results=max_results,
        )
    )


@lru_cache(maxsize=4)
def load_scenic_ticket_catalog(path: str | None = None) -> dict[str, Any]:
    """Load scenic ticket references from the internal knowledge document."""

    catalog_path = Path(path) if path else SCENIC_TICKET_CATALOG_PATH
    parsed = parse_markdown_metadata(catalog_path.read_text(encoding="utf-8"))
    metadata = parsed.metadata
    ticket_items = [
        _normalize_ticket_item(item)
        for item in _as_list(metadata.get("ticket_items"))
        if isinstance(item, dict)
    ]
    return {
        "source": str(catalog_path),
        "provider": metadata.get("provider") or "curated_rag_ticket_catalog",
        "provider_status": metadata.get("provider_status") or "public_reference_only",
        "collected_at": metadata.get("price_collected_at") or SCENIC_TICKET_COLLECTION_DATE,
        "supplier_candidates": _as_list(metadata.get("supplier_candidates")),
        "ticket_items": ticket_items,
        "body": parsed.body,
    }


def _name_matches(item: dict[str, Any], names: list[str]) -> bool:
    item_name = _as_text(item.get("name"))
    aliases = [_as_text(alias) for alias in _as_list(item.get("aliases"))]
    return any(
        name
        and (
            name in item_name
            or item_name in name
            or any(name in alias or alias in name for alias in aliases if alias)
        )
        for name in names
    )


def _destination_matches(item: dict[str, Any], destination: str) -> bool:
    if not destination:
        return True
    item_destination = _as_text(item.get("destination"))
    region = _as_text(item.get("region"))
    city = _as_text(item.get("city"))
    return any(
        value and (value in destination or destination in value)
        for value in (item_destination, region, city)
    )


def find_scenic_ticket_candidates(
    destination: Any,
    scenic_names: Any = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Find scenic ticket candidates from the curated document-backed catalog."""

    destination_text = _as_text(destination)
    names = [
        part
        for part in _split_scenic_names(scenic_names)
    ]
    catalog = load_scenic_ticket_catalog()
    candidates = [
        dict(item)
        for item in catalog["ticket_items"]
        if _destination_matches(item, destination_text)
    ]
    if names:
        name_filtered = [
            item
            for item in (candidates or catalog["ticket_items"])
            if _name_matches(item, names)
        ]
        if name_filtered:
            candidates = [dict(item) for item in name_filtered]

    matched_destination = destination_text
    if not matched_destination and candidates:
        matched_destination = _as_text(candidates[0].get("destination"))
    return matched_destination or "目的地待确认", candidates, catalog
