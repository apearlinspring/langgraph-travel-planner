"""旅行社交易负载的规范化与确定性摘要。"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from app.schemas.agency_transaction import AgencyQuoteCreateRequest


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_payload_hash(payload: Any) -> str:
    """对 JSON 语义负载生成稳定的 SHA-256 摘要。"""

    serialized = json.dumps(
        _canonical_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonical_money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def build_quote_payload(data: AgencyQuoteCreateRequest) -> dict[str, Any]:
    return {
        "agency_id": data.agency_id,
        "customer_user_id": data.customer_user_id,
        "conversation_id": data.conversation_id,
        "product_id": data.product_id,
        "total_amount": canonical_money_text(data.total_amount),
        "currency": data.currency,
        "snapshot_version": data.snapshot_version,
        "quote_snapshot": data.quote_snapshot,
        "valid_until": data.valid_until,
    }
