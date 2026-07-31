"""旅行社业务 API 共用的幂等 Header 与错误映射。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Awaitable, TypeVar

from fastapi import Header, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agency.errors import (
    AgencyTransactionAccessDenied,
    AgencyTransactionConflict,
    AgencyTransactionError,
    AgencyTransactionNotFound,
    AgencyTransactionPersistenceError,
    AgencyTransactionValidationError,
    is_database_write_conflict,
)
from app.api.dependencies import api_error
from app.models.base import async_session_maker


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


async def get_agency_db() -> AsyncIterator[AsyncSession]:
    """在响应发送前提交旅行社领域事务并映射提交阶段错误。"""

    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception as error:
            await session.rollback()
            if is_database_write_conflict(error):
                conflict = AgencyTransactionConflict(
                    "transaction_write_conflict",
                    "交易数据已变化或违反数据库约束，请刷新后重试",
                )
                raise agency_error_to_http(conflict) from error
            if isinstance(error, (AgencyTransactionError, SQLAlchemyError)):
                raise agency_error_to_http(error) from error
            raise


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=error.code,
            message=error.message,
        )
    raise error


async def agency_service_call(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except (AgencyTransactionError, SQLAlchemyError) as error:
        raise agency_error_to_http(error) from error
