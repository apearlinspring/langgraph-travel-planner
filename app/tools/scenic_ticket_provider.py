"""Scenic ticket reference provider backed by internal RAG documents."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.rag.contracts import parse_markdown_metadata


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


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_text(value: Any) -> str:
    return str(value or "").strip()


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
        "公开参考价，不代表实时库存、预约成功或锁价；正式预订前需以官方购票页/供应商接口二次核验。",
    )
    return item


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
        "provider_status": metadata.get("provider_status") or "reference_only",
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
        part.strip()
        for item in _as_list(scenic_names)
        for part in str(item).replace("，", ",").split(",")
        if part.strip()
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
