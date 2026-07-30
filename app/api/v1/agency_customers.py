"""旅行社门店、客户生命周期与顾问分配 API。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agency.customer_lifecycle_service import CustomerLifecycleService
from app.api.dependencies import get_current_user
from app.api.v1.agency_common import (
    IdempotencyKeyHeader,
    agency_service_call as _service_call,
)
from app.models.base import get_db
from app.models.user import User
from app.schemas.agency_customer_lifecycle import (
    AdvisorAssignmentStatus,
    AgencyBranchCreateRequest,
    AgencyBranchListResponse,
    AgencyBranchResponse,
    AgencyBranchRoleGrantCreateRequest,
    AgencyBranchRoleGrantListResponse,
    AgencyBranchRoleGrantResponse,
    AgencyBranchRoleGrantRevokeRequest,
    AgencyCustomerAdvisorAssignRequest,
    AgencyCustomerAdvisorEndRequest,
    AgencyCustomerAdvisorAssignmentListResponse,
    AgencyCustomerAdvisorAssignmentResponse,
    AgencyCustomerConsentRequest,
    AgencyCustomerCreateRequest,
    AgencyCustomerDeactivateRequest,
    AgencyCustomerEventListResponse,
    AgencyCustomerEventResponse,
    AgencyCustomerLinkUserRequest,
    AgencyCustomerListResponse,
    AgencyCustomerResponse,
    BranchRoleGrantStatus,
    BranchStatus,
    CustomerStatus,
    ExpectedRevisionRequest,
)


router = APIRouter(prefix="/agency", tags=["旅行社客户与门店"])


async def get_customer_lifecycle_service(
    db: AsyncSession = Depends(get_db),
) -> CustomerLifecycleService:
    return CustomerLifecycleService(db)


@router.post(
    "/branches",
    response_model=AgencyBranchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agency_branch(
    data: AgencyBranchCreateRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """由旅行社全域管理员创建门店。"""

    return await _service_call(
        service.create_branch(
            actor_user_id=user.id,
            data=data,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/branches", response_model=AgencyBranchListResponse)
async def list_agency_branches(
    agency_id: uuid.UUID,
    branch_status: BranchStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """按当前成员的旅行社与门店授权范围列出门店。"""

    branches, total = await _service_call(
        service.list_branches(
            actor_user_id=user.id,
            agency_id=agency_id,
            status_filter=branch_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyBranchListResponse(
        branches=[
            AgencyBranchResponse.model_validate(branch)
            for branch in branches
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/branches/{branch_id}/role-grants",
    response_model=AgencyBranchRoleGrantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agency_branch_role_grant(
    branch_id: uuid.UUID,
    data: AgencyBranchRoleGrantCreateRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """由旅行社全域管理员授予成员指定门店角色。"""

    return await _service_call(
        service.create_branch_role_grant(
            actor_user_id=user.id,
            branch_id=branch_id,
            data=data,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/branches/{branch_id}/role-grants",
    response_model=AgencyBranchRoleGrantListResponse,
)
async def list_agency_branch_role_grants(
    branch_id: uuid.UUID,
    grant_status: BranchRoleGrantStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """列出当前用户有权管理或查看的门店角色授权。"""

    grants, total = await _service_call(
        service.list_branch_role_grants(
            actor_user_id=user.id,
            branch_id=branch_id,
            status_filter=grant_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyBranchRoleGrantListResponse(
        grants=[
            AgencyBranchRoleGrantResponse.model_validate(grant)
            for grant in grants
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/branches/{branch_id}/role-grants/{grant_id}/revoke",
    response_model=AgencyBranchRoleGrantResponse,
)
async def revoke_agency_branch_role_grant(
    branch_id: uuid.UUID,
    grant_id: uuid.UUID,
    data: AgencyBranchRoleGrantRevokeRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """撤销门店角色授权；仍绑定有效客户的顾问授权会被拒绝。"""

    return await _service_call(
        service.revoke_branch_role_grant(
            actor_user_id=user.id,
            branch_id=branch_id,
            grant_id=grant_id,
            expected_revision=data.expected_revision,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/customers",
    response_model=AgencyCustomerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agency_customer(
    data: AgencyCustomerCreateRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """登记旅行社客户关系；此操作不代表已通知客户或已取得同意。"""

    return await _service_call(
        service.create_customer(
            actor_user_id=user.id,
            data=data,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/customers", response_model=AgencyCustomerListResponse)
async def list_agency_customers(
    agency_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    customer_status: CustomerStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """按门店权限和顾问分配范围列出客户关系。"""

    customers, total = await _service_call(
        service.list_customers(
            actor_user_id=user.id,
            agency_id=agency_id,
            branch_id=branch_id,
            status_filter=customer_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyCustomerListResponse(
        customers=[
            AgencyCustomerResponse.model_validate(customer)
            for customer in customers
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/customers/{customer_id}",
    response_model=AgencyCustomerResponse,
)
async def get_agency_customer(
    customer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """读取授权范围内的单个客户关系。"""

    return await _service_call(
        service.get_customer(
            actor_user_id=user.id,
            customer_id=customer_id,
        )
    )


@router.post(
    "/customers/{customer_id}/link-user",
    response_model=AgencyCustomerResponse,
)
async def link_agency_customer_user(
    customer_id: uuid.UUID,
    data: AgencyCustomerLinkUserRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """将线下客户关系关联到已注册用户，不在响应中暴露用户标识。"""

    return await _service_call(
        service.link_customer_user(
            actor_user_id=user.id,
            customer_id=customer_id,
            expected_revision=data.expected_revision,
            user_id=data.user_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/customers/{customer_id}/consent",
    response_model=AgencyCustomerResponse,
)
async def record_agency_customer_consent(
    customer_id: uuid.UUID,
    data: AgencyCustomerConsentRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """由已关联的平台客户记录本人授权决定及证据摘要。"""

    return await _service_call(
        service.record_customer_consent(
            actor_user_id=user.id,
            customer_id=customer_id,
            expected_revision=data.expected_revision,
            decision=data.decision,
            consent_version=data.consent_version,
            consent_evidence_hash=data.consent_evidence_hash,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/customers/{customer_id}/activate",
    response_model=AgencyCustomerResponse,
)
async def activate_agency_customer(
    customer_id: uuid.UUID,
    data: ExpectedRevisionRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """在关联用户且客户授权有效后激活客户关系。"""

    return await _service_call(
        service.activate_customer(
            actor_user_id=user.id,
            customer_id=customer_id,
            expected_revision=data.expected_revision,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/customers/{customer_id}/deactivate",
    response_model=AgencyCustomerResponse,
)
async def deactivate_agency_customer(
    customer_id: uuid.UUID,
    data: AgencyCustomerDeactivateRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """停用客户关系；客户本人停用时同时撤回同意。"""

    return await _service_call(
        service.deactivate_customer(
            actor_user_id=user.id,
            customer_id=customer_id,
            expected_revision=data.expected_revision,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/customers/{customer_id}/advisor-assignments",
    response_model=AgencyCustomerAdvisorAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_agency_customer_advisor(
    customer_id: uuid.UUID,
    data: AgencyCustomerAdvisorAssignRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """原子创建或更换客户的当前主顾问。"""

    return await _service_call(
        service.assign_customer_advisor(
            actor_user_id=user.id,
            customer_id=customer_id,
            expected_revision=data.expected_revision,
            advisor_role_grant_id=data.advisor_role_grant_id,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/customers/{customer_id}/advisor-assignments/end",
    response_model=AgencyCustomerAdvisorAssignmentResponse,
)
async def end_agency_customer_advisor_assignment(
    customer_id: uuid.UUID,
    data: AgencyCustomerAdvisorEndRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """结束客户当前主顾问分配，不自动停用客户。"""

    return await _service_call(
        service.end_customer_advisor_assignment(
            actor_user_id=user.id,
            customer_id=customer_id,
            expected_revision=data.expected_revision,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/customers/{customer_id}/advisor-assignments",
    response_model=AgencyCustomerAdvisorAssignmentListResponse,
)
async def list_agency_customer_advisor_assignments(
    customer_id: uuid.UUID,
    assignment_status: AdvisorAssignmentStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """列出授权范围内客户的顾问分配历史。"""

    assignments, total = await _service_call(
        service.list_customer_advisor_assignments(
            actor_user_id=user.id,
            customer_id=customer_id,
            status_filter=assignment_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyCustomerAdvisorAssignmentListResponse(
        assignments=[
            AgencyCustomerAdvisorAssignmentResponse.model_validate(assignment)
            for assignment in assignments
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/customers/{customer_id}/events",
    response_model=AgencyCustomerEventListResponse,
)
async def list_agency_customer_events(
    customer_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CustomerLifecycleService = Depends(
        get_customer_lifecycle_service
    ),
):
    """读取客户生命周期的只追加事件，不返回原始元数据。"""

    events, total = await _service_call(
        service.list_customer_events(
            actor_user_id=user.id,
            customer_id=customer_id,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyCustomerEventListResponse(
        events=[
            AgencyCustomerEventResponse.model_validate(event)
            for event in events
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
