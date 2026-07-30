"""旅行社业务 API 共用的幂等 Header 与错误映射。"""
from __future__ import annotations

from typing import Annotated, Awaitable, TypeVar

from fastapi import Header, status
from sqlalchemy.exc import SQLAlchemyError

from app.agency.errors import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionError,
    AgencyTransactionNotFound,
    AgencyTransactionPersistenceError,
    AgencyTransactionValidationError,
)
from app.api.dependencies import api_error


IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        description="客户端生成的幂等键；相同业务请求重试时必须复用",
    ),
]
T = TypeVar("T")


def agency_error_to_http(error: Exception):
    if isinstance(error, AgencyTransactionNotFound):
        return api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code=error.code,
            message=error.message,
        )
    if isinstance(error, AgencyTransactionAccessDenied):
        return api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code=error.code,
            message=error.message,
        )
    if isinstance(error, AgencyTransactionConflict):
        return api_error(
            status_code=status.HTTP_409_CONFLICT,
            code=error.code,
            message=error.message,
        )
    if isinstance(error, AgencyTransactionValidationError):
        return api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=error.code,
            message=error.message,
        )
    if isinstance(error, (AgencyTransactionPersistenceError, SQLAlchemyError)):
        return api_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=(
                error.code
                if isinstance(error, AgencyTransactionPersistenceError)
                else "transaction_persistence_unavailable"
            ),
            message=(
                error.message
                if isinstance(error, AgencyTransactionPersistenceError)
                else "交易数据服务暂时不可用，请稍后重试"
            ),
        )
    if isinstance(error, AgencyTransactionError):
        return api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=error.code,
            message=error.message,
        )
    raise error


async def agency_service_call(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except (AgencyTransactionError, SQLAlchemyError) as error:
        raise agency_error_to_http(error) from error
