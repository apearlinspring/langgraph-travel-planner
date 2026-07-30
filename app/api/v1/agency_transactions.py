"""旅行社报价与订单的最小交易 API。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agency.order_review_service import AgencyOrderReviewService
from app.agency.transaction_service import AgencyTransactionService
from app.api.dependencies import get_current_user
from app.api.v1.agency_common import (
    IdempotencyKeyHeader,
    agency_service_call as _service_call,
    get_agency_db,
)
from app.models.user import User
from app.schemas.agency_transaction import (
    AgencyOrderCreateRequest,
    AgencyOrderEventListResponse,
    AgencyOrderEventResponse,
    AgencyOrderListResponse,
    AgencyOrderReviewDecisionRequest,
    AgencyOrderReviewListResponse,
    AgencyOrderReviewResponse,
    AgencyOrderResponse,
    AgencyQuoteCreateRequest,
    AgencyQuoteListResponse,
    AgencyQuoteResponse,
    ExpectedRevisionRequest,
    OrderReviewStatus,
    OrderStatus,
    QuoteStatus,
)


router = APIRouter(prefix="/agency", tags=["旅行社交易"])


async def get_agency_transaction_service(
    db: AsyncSession = Depends(get_agency_db, scope="function"),
) -> AgencyOrderReviewService:
    return AgencyOrderReviewService(db)


def _event_response(event) -> AgencyOrderEventResponse:
    response = AgencyOrderEventResponse.model_validate(event)
    allowed_metadata = {
        "quote_id",
        "review_id",
        "review_order_revision",
        "decision_order_revision",
        "external_actions_triggered",
    }
    safe_metadata = {
        key: value
        for key, value in response.event_metadata.items()
        if key in allowed_metadata
    }
    return response.model_copy(update={"event_metadata": safe_metadata})


@router.post(
    "/quotes",
    response_model=AgencyQuoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agency_quote(
    data: AgencyQuoteCreateRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """由旅行社租户内的报价管理角色创建客户报价草稿。"""

    return await _service_call(
        service.create_quote(
            actor_user_id=user.id,
            data=data,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/quotes", response_model=AgencyQuoteListResponse)
async def list_agency_quotes(
    agency_id: uuid.UUID,
    quote_status: QuoteStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """列出当前客户自己的报价，或有完整快照权限的租户报价。"""

    quotes, total = await _service_call(
        service.list_quotes(
            actor_user_id=user.id,
            agency_id=agency_id,
            status_filter=quote_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyQuoteListResponse(
        quotes=[AgencyQuoteResponse.model_validate(quote) for quote in quotes],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/quotes/{quote_id}", response_model=AgencyQuoteResponse)
async def get_agency_quote(
    quote_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """读取客户自己的报价，或有完整快照权限的租户报价。"""

    return await _service_call(
        service.get_quote(
            actor_user_id=user.id,
            quote_id=quote_id,
        )
    )


@router.post("/quotes/{quote_id}/issue", response_model=AgencyQuoteResponse)
async def issue_agency_quote(
    quote_id: uuid.UUID,
    data: ExpectedRevisionRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """将未过期的报价草稿发布给客户。"""

    return await _service_call(
        service.issue_quote(
            actor_user_id=user.id,
            quote_id=quote_id,
            expected_revision=data.expected_revision,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/quotes/{quote_id}/accept", response_model=AgencyQuoteResponse)
async def accept_agency_quote(
    quote_id: uuid.UUID,
    data: ExpectedRevisionRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """由报价所属客户接受仍在有效期内的已发布报价。"""

    return await _service_call(
        service.accept_quote(
            actor_user_id=user.id,
            quote_id=quote_id,
            expected_revision=data.expected_revision,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/orders",
    response_model=AgencyOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agency_order(
    data: AgencyOrderCreateRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """由客户从本人已接受、未过期的报价创建订单草稿。"""

    return await _service_call(
        service.create_order(
            actor_user_id=user.id,
            data=data,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/orders", response_model=AgencyOrderListResponse)
async def list_agency_orders(
    agency_id: uuid.UUID,
    order_status: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """列出当前客户自己的订单，或有完整快照权限的租户订单。"""

    orders, total = await _service_call(
        service.list_orders(
            actor_user_id=user.id,
            agency_id=agency_id,
            status_filter=order_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyOrderListResponse(
        orders=[AgencyOrderResponse.model_validate(order) for order in orders],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/order-reviews", response_model=AgencyOrderReviewListResponse)
async def list_agency_order_reviews(
    agency_id: uuid.UUID,
    review_status: OrderReviewStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """列出专职审批员所在旅行社的结构化订单审核工作队列。"""

    reviews, total = await _service_call(
        service.list_order_reviews(
            actor_user_id=user.id,
            agency_id=agency_id,
            status_filter=review_status,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyOrderReviewListResponse(
        reviews=[
            AgencyOrderReviewResponse.model_validate(review)
            for review in reviews
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/orders/{order_id}", response_model=AgencyOrderResponse)
async def get_agency_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """读取客户自己的订单，或有完整快照权限的租户订单。"""

    return await _service_call(
        service.get_order(
            actor_user_id=user.id,
            order_id=order_id,
        )
    )


@router.get(
    "/orders/{order_id}/review",
    response_model=AgencyOrderReviewResponse,
)
async def get_agency_order_review(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """由同一旅行社的专职审批员读取结构化审核记录。"""

    return await _service_call(
        service.get_order_review(
            actor_user_id=user.id,
            order_id=order_id,
        )
    )


@router.get(
    "/orders/{order_id}/events",
    response_model=AgencyOrderEventListResponse,
)
async def list_agency_order_events(
    order_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """读取订单的只追加状态事件。"""

    events, total = await _service_call(
        service.list_order_events(
            actor_user_id=user.id,
            order_id=order_id,
            limit=limit,
            offset=offset,
        )
    )
    return AgencyOrderEventListResponse(
        events=[_event_response(event) for event in events],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/orders/{order_id}/submit", response_model=AgencyOrderResponse)
async def submit_agency_order(
    order_id: uuid.UUID,
    data: ExpectedRevisionRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """由订单所属客户将草稿提交旅行社人工审核。"""

    return await _service_call(
        service.submit_order(
            actor_user_id=user.id,
            order_id=order_id,
            expected_revision=data.expected_revision,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/orders/{order_id}/review",
    response_model=AgencyOrderReviewResponse,
)
async def decide_agency_order_review(
    order_id: uuid.UUID,
    data: AgencyOrderReviewDecisionRequest,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(get_current_user),
    service: AgencyTransactionService = Depends(get_agency_transaction_service),
):
    """由同一旅行社的专职审批员批准或拒绝内部订单审核。"""

    return await _service_call(
        service.decide_order_review(
            actor_user_id=user.id,
            order_id=order_id,
            decision=data.decision,
            expected_revision=data.expected_revision,
            reason=data.reason,
            idempotency_key=idempotency_key,
        )
    )
