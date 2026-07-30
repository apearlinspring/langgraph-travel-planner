"""旅行社门店、客户生命周期与顾问分配 API 契约。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


BranchStatus = Literal["active", "inactive", "closed"]
BranchRole = Literal[
    "travel_advisor",
    "booking_operator",
    "approver",
    "finance",
    "auditor",
    "branch_manager",
]
BranchRoleGrantStatus = Literal["active", "revoked"]
CustomerStatus = Literal[
    "invited",
    "prospect",
    "active",
    "inactive",
    "blocked",
]
CustomerConsentStatus = Literal[
    "unknown",
    "pending",
    "granted",
    "denied",
    "revoked",
]
CustomerConsentDecision = Literal["grant", "deny", "revoke"]
CustomerBindingProvenance = Literal[
    "unbound",
    "legacy_direct",
    "secure_claim",
]
CustomerConsentEvidenceOrigin = Literal[
    "none",
    "legacy_client_hash",
    "server_canonical",
]
CustomerClaimInvitationStatus = Literal["pending", "claimed", "revoked"]
CustomerSourceType = Literal[
    "manual",
    "staff_import",
    "referral",
    "registered_user",
]
AdvisorAssignmentStatus = Literal["active", "ended"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpectedRevisionRequest(StrictRequest):
    expected_revision: int = Field(..., ge=1)


class AgencyBranchCreateRequest(StrictRequest):
    agency_id: uuid.UUID
    branch_code: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=160)

    @field_validator("branch_code")
    @classmethod
    def normalize_branch_code(cls, value: str) -> str:
        normalized = value.upper()
        if len(normalized) > 40 or not normalized[0].isalnum() or not all(
            character.isascii()
            and (character.isalnum() or character in {"_", "-"})
            for character in normalized
        ):
            raise ValueError(
                "branch_code 只能包含 ASCII 字母、数字、下划线或连字符，"
                "且必须以字母或数字开头"
            )
        return normalized


class AgencyBranchRoleGrantCreateRequest(StrictRequest):
    membership_id: uuid.UUID
    role: BranchRole


class AgencyBranchRoleGrantRevokeRequest(ExpectedRevisionRequest):
    reason: str = Field(..., min_length=1, max_length=500)


class AgencyCustomerCreateRequest(StrictRequest):
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    source_type: CustomerSourceType = "manual"
    source_reference: str | None = Field(default=None, max_length=160)

    @field_validator("source_reference")
    @classmethod
    def normalize_optional_reference(cls, value: str | None) -> str | None:
        return value or None


class AgencyCustomerConsentRequest(ExpectedRevisionRequest):
    decision: CustomerConsentDecision
    expected_notice_version: str = Field(..., min_length=1, max_length=40)
    expected_notice_document_sha256: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )

    @field_validator("expected_notice_document_sha256")
    @classmethod
    def normalize_notice_hash(cls, value: str) -> str:
        return value.lower()


class AgencyCustomerClaimInvitationIssueRequest(ExpectedRevisionRequest):
    target_user_id: uuid.UUID


class AgencyCustomerClaimInvitationRevokeRequest(ExpectedRevisionRequest):
    expected_invitation_revision: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=500)


class AgencyCustomerClaimRequest(StrictRequest):
    claim_token: str = Field(
        ...,
        min_length=32,
        max_length=512,
        repr=False,
    )


class AgencyCustomerDeactivateRequest(ExpectedRevisionRequest):
    reason: str = Field(..., min_length=1, max_length=500)


class AgencyCustomerAdvisorAssignRequest(ExpectedRevisionRequest):
    advisor_role_grant_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_optional_reason(cls, value: str | None) -> str | None:
        return value or None


class AgencyCustomerAdvisorEndRequest(ExpectedRevisionRequest):
    reason: str = Field(..., min_length=1, max_length=500)


class AgencyBranchResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_code: str
    name: str
    status: BranchStatus
    revision: int
    deactivated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyBranchListResponse(BaseModel):
    branches: list[AgencyBranchResponse]
    total: int
    offset: int
    limit: int


class AgencyBranchRoleGrantResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    membership_id: uuid.UUID
    role: BranchRole
    status: BranchRoleGrantStatus
    revision: int
    granted_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyBranchRoleGrantListResponse(BaseModel):
    grants: list[AgencyBranchRoleGrantResponse]
    total: int
    offset: int
    limit: int


class AgencyCustomerResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    customer_no: str
    source_type: str
    status: CustomerStatus
    binding_provenance: CustomerBindingProvenance
    claimed_at: datetime | None = None
    consent_status: CustomerConsentStatus
    consent_evidence_origin: CustomerConsentEvidenceOrigin
    consent_version: str | None = None
    consent_updated_at: datetime | None = None
    lifecycle_revision: int
    invited_at: datetime
    activated_at: datetime | None = None
    deactivated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCustomerListResponse(BaseModel):
    customers: list[AgencyCustomerResponse]
    total: int
    offset: int
    limit: int


class AgencyCustomerConsentNoticeResponse(BaseModel):
    consent_version: str
    consent_document_sha256: str
    evidence_schema_version: str
    channel: str
    notice_markdown: str


class AgencyCustomerClaimInvitationResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    status: CustomerClaimInvitationStatus
    revision: int
    issued_at: datetime
    expires_at: datetime
    claimed_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCustomerClaimInvitationIssuedResponse(
    AgencyCustomerClaimInvitationResponse
):
    # 只在首次创建成功时返回；幂等重放、查询和事件都不会再次暴露原 token。
    claim_token: str | None = Field(default=None, repr=False)


class AgencyCustomerClaimInvitationListResponse(BaseModel):
    invitations: list[AgencyCustomerClaimInvitationResponse]
    total: int
    offset: int
    limit: int


class AgencyCustomerAdvisorAssignmentResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    advisor_role_grant_id: uuid.UUID
    advisor_membership_id: uuid.UUID
    status: AdvisorAssignmentStatus
    revision: int
    assigned_at: datetime
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCustomerAdvisorAssignmentListResponse(BaseModel):
    assignments: list[AgencyCustomerAdvisorAssignmentResponse]
    total: int
    offset: int
    limit: int


class AgencyCustomerEventResponse(BaseModel):
    id: uuid.UUID
    agency_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID
    event_sequence: int
    customer_revision: int
    event_type: str
    from_status: CustomerStatus | None = None
    to_status: CustomerStatus | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgencyCustomerEventListResponse(BaseModel):
    events: list[AgencyCustomerEventResponse]
    total: int
    offset: int
    limit: int
