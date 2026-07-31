"""旅行社订单人工取消、补偿记录与对账 API 契约。"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

CancellationCaseStatus = Literal[
    "approval_pending",
    "rejected",
    "action_pending",
    "reconciliation_pending",
    "manual_intervention",
    "completed",
]
CancellationReasonCode = Literal[
    "customer_request",
    "customer_consent_withdrawn",
    "agency_unable_to_fulfill",
    "supplier_unavailable",
    "duplicate_order",
    "pricing_or_booking_error",
    "force_majeure",
    "compliance_or_risk",
]
CancellationReviewRequestDecision = Literal["approve", "reject"]
CancellationReviewDecision = Literal["approved", "rejected"]
CancellationActionType = Literal["supplier_cancel", "refund"]
ManualActionOutcome = Literal["succeeded", "failed", "unknown"]
ReconciliationOutcome = Literal["matched", "mismatched", "unverifiable"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgencyCancellationRequest(StrictRequest):
    expected_order_revision: int = Field(..., ge=1)
    reason_code: CancellationReasonCode
    reason_detail: str | None = Field(default=None, max_length=500)

    @field_validator("reason_detail")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        return value or None


class AgencyCancellationReviewRequest(StrictRequest):
    expected_revision: int = Field(..., ge=1)
    decision: CancellationReviewRequestDecision
    approved_refund_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    approved_refund_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("approved_refund_currency")
    @classmethod
    def normalize_optional_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if not normalized.isascii() or not normalized.isalpha():
            raise ValueError("approved_refund_currency 必须是 3 位 ASCII 字母")
        return normalized

    @field_validator("reason")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def validate_decision_fields(self):
        amount = self.approved_refund_amount
        currency = self.approved_refund_currency
        if (amount is None) != (currency is None):
            raise ValueError(
                "approved_refund_amount 与 approved_refund_currency "
                "必须同时提供"
            )
        if self.decision == "reject":
            if self.reason is None:
                raise ValueError("拒绝取消申请时必须填写 reason")
            if amount is not None:
                raise ValueError("拒绝取消申请时不能批准退款金额")
        return self


class AgencyManualCancellationResultRequest(StrictRequest):
    expected_revision: int = Field(..., ge=1)
    action_type: CancellationActionType
    outcome: ManualActionOutcome
    external_reference_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        repr=False,
    )
    evidence_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        repr=False,
    )
    amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    occurred_at: datetime

    @field_validator("external_reference_sha256", "evidence_sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        return value.lower()

    @field_validator("currency")
    @classmethod
    def normalize_optional_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if not normalized.isascii() or not normalized.isalpha():
            raise ValueError("currency 必须是 3 位 ASCII 字母")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action_type == "refund":
            if self.amount is None or self.currency is None:
                raise ValueError("退款结果必须同时提供 amount 与 currency")
        elif self.amount is not None or self.currency is not None:
            raise ValueError("供应商取消结果不能提供 amount 或 currency")
        return self


class AgencyManualResultReconcileRequest(StrictRequest):
    expected_revision: int = Field(..., ge=1)
    outcome: ReconciliationOutcome
    observed_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    observed_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )
    evidence_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        repr=False,
    )

    @field_validator("evidence_sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        return value.lower()

    @field_validator("observed_currency")
    @classmethod
    def normalize_observed_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if not normalized.isascii() or not normalized.isalpha():
            raise ValueError("observed_currency 必须是 3 位 ASCII 字母")
        return normalized

    @model_validator(mode="after")
    def validate_observation_pair(self):
        if (self.observed_amount is None) != (
            self.observed_currency is None
        ):
            raise ValueError(
                "observed_amount 与 observed_currency 必须同时提供"
            )
        return self


class AgencyCancellationResumeRequest(StrictRequest):
    expected_revision: int = Field(..., ge=1)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        return value or None


class AgencyCancellationCaseResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID
    customer_id: uuid.UUID
    revision: int
    status: CancellationCaseStatus
    order_revision_at_request: int
    reason_code: str
    supplier_cancel_required: bool
    refund_required: bool
    approved_refund_amount: Decimal | None = None
    currency: str
    requested_at: datetime
    review_decision: CancellationReviewDecision | None = None
    reviewed_at: datetime | None = None
    external_action_triggered: Literal[False]
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCancellationCaseListResponse(BaseModel):
    cases: list[AgencyCancellationCaseResponse]
    total: int
    offset: int
    limit: int


class AgencyManualCancellationResultResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID
    case_id: uuid.UUID = Field(
        validation_alias=AliasChoices("case_id", "cancellation_case_id")
    )
    sequence: int = Field(
        validation_alias=AliasChoices("sequence", "record_sequence")
    )
    case_revision: int
    action_type: CancellationActionType
    outcome: ManualActionOutcome
    amount: Decimal | None = None
    currency: str | None = None
    occurred_at: datetime
    system_external_action_triggered: Literal[False]
    recorded_at: datetime = Field(
        validation_alias=AliasChoices("recorded_at", "created_at")
    )

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def hide_supplier_amount_placeholder(self):
        if self.action_type == "supplier_cancel":
            self.amount = None
            self.currency = None
        return self


class AgencyManualCancellationResultListItem(
    AgencyManualCancellationResultResponse
):
    reconciliation_outcome: ReconciliationOutcome | None = None


class AgencyManualCancellationResultListResponse(BaseModel):
    results: list[AgencyManualCancellationResultListItem]
    total: int
    offset: int
    limit: int


class AgencyManualResultReconciliationResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID
    case_id: uuid.UUID = Field(
        validation_alias=AliasChoices("case_id", "cancellation_case_id")
    )
    compensation_record_id: uuid.UUID
    case_revision: int
    outcome: ReconciliationOutcome
    observed_amount: Decimal | None = None
    observed_currency: str | None = Field(
        default=None,
        validation_alias=AliasChoices("observed_currency", "currency"),
    )
    reconciled_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCancellationEventResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID
    case_id: uuid.UUID = Field(
        validation_alias=AliasChoices("case_id", "cancellation_case_id")
    )
    sequence: int = Field(
        validation_alias=AliasChoices("sequence", "event_sequence")
    )
    case_revision: int
    event_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCancellationEventListResponse(BaseModel):
    events: list[AgencyCancellationEventResponse]
    total: int
    offset: int
    limit: int
