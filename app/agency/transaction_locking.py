"""交易资源的客户优先锁序与不可变绑定复验。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agency.errors import (
    AgencyTransactionConflict,
    AgencyTransactionValidationError,
    hidden_not_found,
)
from app.models.agency_customer_lifecycle import AgencyBranch, AgencyCustomer
from app.models.agency_transaction import AgencyOrder, AgencyQuote


TransactionBinding = tuple[
    uuid.UUID,
    uuid.UUID,
    uuid.UUID,
    uuid.UUID | None,
]


class TransactionLockingMixin:
    """统一客户、门店、交易资源的并发锁定辅助方法。"""

    db: AsyncSession

    async def _get_transaction_customer(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID | None = None,
        customer_id: uuid.UUID,
        for_update: bool = False,
    ) -> AgencyCustomer:
        statement = (
            select(AgencyCustomer)
            .join(
                AgencyBranch,
                (AgencyBranch.agency_id == AgencyCustomer.agency_id)
                & (AgencyBranch.id == AgencyCustomer.branch_id),
            )
            .where(AgencyCustomer.agency_id == agency_id)
            .where(AgencyCustomer.id == customer_id)
            .where(AgencyBranch.status == "active")
        )
        if branch_id is not None:
            statement = statement.where(
                AgencyCustomer.branch_id == branch_id
            )
        if for_update:
            statement = statement.with_for_update(
                of=AgencyCustomer
            ).execution_options(populate_existing=True)
        result = await self.db.execute(statement)
        customer = result.scalar_one_or_none()
        if customer is None:
            raise AgencyTransactionValidationError(
                "quote_customer_not_active",
                "客户或所属门店当前不可执行交易",
            )
        if (
            customer.status != "active"
            or customer.consent_status != "granted"
            or customer.consent_evidence_hash is None
            or customer.user_id is None
        ):
            raise AgencyTransactionValidationError(
                "quote_customer_not_active",
                "客户尚未完成账号关联、同意确认和业务关系激活",
            )
        return customer

    async def _get_customer_binding(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        customer_id: uuid.UUID,
        for_update: bool = False,
    ) -> AgencyCustomer:
        """读取客户绑定；用于允许 inactive 客户的收口命令。"""

        statement = (
            select(AgencyCustomer)
            .where(AgencyCustomer.agency_id == agency_id)
            .where(AgencyCustomer.branch_id == branch_id)
            .where(AgencyCustomer.id == customer_id)
        )
        if for_update:
            statement = statement.with_for_update(
                of=AgencyCustomer
            ).execution_options(populate_existing=True)
        result = await self.db.execute(statement)
        customer = result.scalar_one_or_none()
        if customer is None:
            raise hidden_not_found()
        return customer

    async def _get_quote(
        self,
        quote_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyQuote:
        return await self._get_resource(
            AgencyQuote,
            quote_id,
            for_update=for_update,
        )

    async def _get_order(
        self,
        order_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> AgencyOrder:
        return await self._get_resource(
            AgencyOrder,
            order_id,
            for_update=for_update,
        )

    async def _get_resource(
        self,
        model: Any,
        resource_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Any:
        statement = select(model).where(model.id == resource_id)
        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        result = await self.db.execute(statement)
        resource = result.scalar_one_or_none()
        if resource is None:
            raise hidden_not_found()
        return resource

    @staticmethod
    def _transaction_binding(
        resource: AgencyQuote | AgencyOrder,
    ) -> TransactionBinding:
        return (
            resource.agency_id,
            resource.branch_id,
            resource.customer_id,
            resource.user_id,
        )

    @classmethod
    def _ensure_transaction_binding(
        cls,
        resource: AgencyQuote | AgencyOrder,
        expected: TransactionBinding,
    ) -> None:
        if cls._transaction_binding(resource) != expected:
            raise AgencyTransactionConflict(
                "transaction_binding_conflict",
                "交易资源的客户或门店绑定已变化，请刷新后重试",
            )

    @staticmethod
    def _ensure_customer_binding(
        customer: AgencyCustomer,
        expected: TransactionBinding,
    ) -> None:
        if (
            customer.agency_id,
            customer.branch_id,
            customer.id,
            customer.user_id,
        ) != expected:
            raise AgencyTransactionConflict(
                "transaction_customer_binding_conflict",
                "客户账号或门店绑定与交易资源不一致，请刷新后重试",
            )
