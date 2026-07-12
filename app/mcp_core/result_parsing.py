"""Small, dependency-free helpers for parsing MCP tool results."""

from __future__ import annotations

import json
from typing import Any


def extract_text_payload(result: Any) -> str:
    """Extract the first MCP text block, falling back to ``str``."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text", ""))
    if isinstance(result, dict) and result.get("type") == "text":
        return str(result.get("text", ""))
    return str(result)


def parse_json_text(result: Any) -> dict[str, Any]:
    """Parse an MCP text result as JSON or return an empty mapping when invalid."""
    try:
        return json.loads(extract_text_payload(result))
    except json.JSONDecodeError:
        return {}


def extract_text_blocks(result: Any) -> str:
    """Join every item in an MCP content-block list into text."""
    if isinstance(result, list):
        return "\n".join(
            item.get("text", "")
            if isinstance(item, dict) and item.get("type") == "text"
            else str(item)
            for item in result
        )
    return str(result)
