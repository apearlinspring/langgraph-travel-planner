"""旅行社报价与订单 API 的 Pydantic 契约。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


QuoteStatus = Literal["draft", "offered", "accepted", "expired", "cancelled"]
OrderStatus = Literal[
    "draft",
    "pending_review",
    "approved",
    "review_rejected",
    "processing",
    "manual_intervention",
    "completed",
    "failed",
    "cancellation_pending",
    "cancelled",
]
PaymentStatus = Literal[
    "not_started",
    "pending",
    "paid",
    "failed",
    "partially_refunded",
    "refunded",
]
FulfillmentStatus = Literal[
    "not_started",
    "pending",
    "confirmed",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
]
OrderReviewStatus = Literal["pending", "approved", "rejected"]
OrderReviewDecision = Literal["approve", "reject"]
Money = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=2),
]
MAX_QUOTE_SNAPSHOT_BYTES = 256 * 1024


class AgencyQuoteCreateRequest(BaseModel):
    agency_id: uuid.UUID
    customer_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    total_amount: Money
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    snapshot_version: str = Field(
        default="agency_quote.v1",
        min_length=1,
        max_length=32,
    )
    quote_snapshot: dict[str, Any] = Field(default_factory=dict)
    valid_until: datetime

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if (
            len(normalized) != 3
            or not normalized.isascii()
            or not normalized.isalpha()
        ):
            raise ValueError("currency 必须是 3 位 ASCII 字母货币代码")
        return normalized

    @field_validator("quote_snapshot")
    @classmethod
    def limit_quote_snapshot(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("quote_snapshot 必须是有效 JSON 对象") from error
        if len(encoded) > MAX_QUOTE_SNAPSHOT_BYTES:
            raise ValueError("quote_snapshot 不能超过 256 KiB")
        return value

    @field_validator("valid_until")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valid_until 必须包含时区")
        return value


class ExpectedRevisionRequest(BaseModel):
    expected_revision: int = Field(..., ge=1)


class AgencyOrderCreateRequest(BaseModel):
    agency_id: uuid.UUID
    quote_id: uuid.UUID
    expected_quote_revision: int = Field(..., ge=1)


class AgencyOrderReviewDecisionRequest(BaseModel):
    decision: OrderReviewDecision
    expected_revision: int = Field(..., ge=1)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def require_rejection_reason(self):
        if self.decision == "reject" and self.reason is None:
            raise ValueError("拒绝订单审核时必须填写 reason")
        return self


class AgencyQuoteResponse(BaseModel):
    id: uuid.UUID
    quote_no: str
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    status: QuoteStatus
    revision: int
    payload_hash: str
    total_amount: Decimal
    currency: str
    snapshot_version: str
    quote_snapshot: dict[str, Any]
    valid_until: datetime
    issued_at: datetime | None = None
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyQuoteListResponse(BaseModel):
    quotes: list[AgencyQuoteResponse]
    total: int
    offset: int
    limit: int


class AgencyOrderResponse(BaseModel):
    id: uuid.UUID
    order_no: str
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    quote_id: uuid.UUID
    status: OrderStatus
    revision: int
    payload_hash: str
    payment_status: PaymentStatus
    fulfillment_status: FulfillmentStatus
    total_amount: Decimal
    currency: str
    quote_snapshot: dict[str, Any]
    external_action_enabled: bool
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyOrderListResponse(BaseModel):
    orders: list[AgencyOrderResponse]
    total: int
    offset: int
    limit: int


class AgencyOrderReviewResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID
    status: OrderReviewStatus
    order_revision: int
    decision_order_revision: int | None = None
    payload_hash: str
    total_amount: Decimal
    currency: str
    requested_by_user_id: uuid.UUID
    decided_by_user_id: uuid.UUID | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyOrderReviewListResponse(BaseModel):
    reviews: list[AgencyOrderReviewResponse]
    total: int
    offset: int
    limit: int


class AgencyOrderEventResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID
    event_sequence: int
    order_revision: int
    event_type: str
    from_status: OrderStatus | None = None
    to_status: OrderStatus | None = None
    payload_hash: str
    event_metadata: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyOrderEventListResponse(BaseModel):
    events: list[AgencyOrderEventResponse]
    total: int
    offset: int
    limit: int
