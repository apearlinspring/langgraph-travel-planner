"""旅行社订单人工取消、补偿记录与对账 API。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agency.cancellation_service import CancellationService
from app.api.dependencies import get_current_user
from app.api.v1.agency_common import (
    IdempotencyKeyHeader,
    get_agency_db,
)
from app.api.v1.agency_common import (
    agency_service_call as _service_call,
)
from app.models.user import User
from app.schemas.agency_cancellation import (
    AgencyCancellationCaseListResponse,
    AgencyCancellationCaseResponse,
    AgencyCancellationEventListResponse,
    AgencyCancellationEventResponse,
    AgencyCancellationRequest,
    AgencyCancellationResumeRequest,
    AgencyCancellationReviewRequest,
    AgencyManualCancellationResultListItem,
    AgencyManualCancellationResultListResponse,
    AgencyManualCancellationResultRequest,
    AgencyManualCancellationResultResponse,
    AgencyManualResultReconcileRequest,
    AgencyManualResultReconciliationResponse,
    CancellationCaseStatus,
)

router = APIRouter(prefix="/agency", tags=["旅行社订单取消与对账"])


async def get_cancellation_service(
    db: AsyncSession = Depends(get_agency_db, scope="function"),
) -> CancellationService:
    return CancellationService(db)


@router.post(
    "/orders/{order_id}/cancellation-requests",
    response_model=AgencyCancellationCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_agency_order_cancellation(
    order_id: uuid.UUID,
    data: AgencyCancellationRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """创建人工取消申请；补偿范围由服务端按锁定订单状态派生。"""

    return await _service_call(
        service.request_cancellation(
            actor_user_id=user.id,
            order_id=order_id,
            expected_revision=data.expected_order_revision,
            reason_code=data.reason_code,
            reason_detail=data.reason_detail,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/orders/{order_id}/cancellation-case",
    response_model=AgencyCancellationCaseResponse,
)
async def get_agency_order_cancellation_case(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """读取授权范围内订单的取消案件脱敏投影。"""

    return await _service_call(
        service.get_cancellation_case(
            actor_user_id=user.id,
            order_id=order_id,
        )
    )


@router.get(
    "/cancellation-cases",
    response_model=AgencyCancellationCaseListResponse,
)
async def list_agency_cancellation_cases(
    agency_id: uuid.UUID,
    case_status: CancellationCaseStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """按旅行社授权范围列出取消案件。"""

    cases, total = await _service_call(
        service.list_cancellation_cases(
            actor_user_id=user.id,
            agency_id=agency_id,
            status_filter=case_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyCancellationCaseListResponse(
        cases=[
            AgencyCancellationCaseResponse.model_validate(case)
            for case in cases
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/cancellation-cases/{case_id}/review",
    response_model=AgencyCancellationCaseResponse,
)
async def review_agency_cancellation_case(
    case_id: uuid.UUID,
    data: AgencyCancellationReviewRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """由同一门店的专职 approver 批准或拒绝；owner/admin 不可替代。"""

    return await _service_call(
        service.review_cancellation(
            actor_user_id=user.id,
            case_id=case_id,
            decision=data.decision,
            expected_revision=data.expected_revision,
            approved_refund_amount=data.approved_refund_amount,
            approved_refund_currency=data.approved_refund_currency,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/cancellation-cases/{case_id}/manual-results",
    response_model=AgencyManualCancellationResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_agency_manual_cancellation_result(
    case_id: uuid.UUID,
    data: AgencyManualCancellationResultRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """记录人工取得的供应商取消或退款结果，不触发外部动作。"""

    return await _service_call(
        service.record_manual_result(
            actor_user_id=user.id,
            case_id=case_id,
            expected_revision=data.expected_revision,
            action_type=data.action_type,
            outcome=data.outcome,
            external_reference_sha256=data.external_reference_sha256,
            evidence_sha256=data.evidence_sha256,
            amount=data.amount,
            currency=data.currency,
            occurred_at=data.occurred_at,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/cancellation-cases/{case_id}/manual-results",
    response_model=AgencyManualCancellationResultListResponse,
)
async def list_agency_manual_cancellation_results(
    case_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """列出脱敏人工结果及其对账状态，供独立审计岗位发现待办。"""

    results, total = await _service_call(
        service.list_manual_results(
            actor_user_id=user.id,
            case_id=case_id,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyManualCancellationResultListResponse(
        results=[
            AgencyManualCancellationResultListItem(
                **AgencyManualCancellationResultResponse.model_validate(
                    record
                ).model_dump(),
                reconciliation_outcome=reconciliation_outcome,
            )
            for record, reconciliation_outcome in results
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/manual-results/{record_id}/reconcile",
    response_model=AgencyManualResultReconciliationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reconcile_agency_manual_cancellation_result(
    record_id: uuid.UUID,
    data: AgencyManualResultReconcileRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """记录人工补偿结果的独立对账结论。"""

    return await _service_call(
        service.reconcile_manual_result(
            actor_user_id=user.id,
            record_id=record_id,
            expected_revision=data.expected_revision,
            outcome=data.outcome,
            observed_amount=data.observed_amount,
            observed_currency=data.observed_currency,
            evidence_sha256=data.evidence_sha256,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/cancellation-cases/{case_id}/resume",
    response_model=AgencyCancellationCaseResponse,
)
async def resume_agency_cancellation_case(
    case_id: uuid.UUID,
    data: AgencyCancellationResumeRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """从人工介入状态恢复取消案件，由服务端重新判断下一阶段。"""

    return await _service_call(
        service.resume_cancellation(
            actor_user_id=user.id,
            case_id=case_id,
            expected_revision=data.expected_revision,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/cancellation-cases/{case_id}/events",
    response_model=AgencyCancellationEventListResponse,
)
async def list_agency_cancellation_events(
    case_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CancellationService = Depends(get_cancellation_service),
):
    """读取取消案件事件，不返回负载摘要、原始备注或事件元数据。"""

    events, total = await _service_call(
        service.list_cancellation_events(
            actor_user_id=user.id,
            case_id=case_id,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyCancellationEventListResponse(
        events=[
            AgencyCancellationEventResponse.model_validate(event)
            for event in events
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
