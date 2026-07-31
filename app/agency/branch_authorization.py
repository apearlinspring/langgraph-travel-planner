"""旅行社租户、门店与客户范围授权。

这里只实现应用层的门店范围行级授权，不宣称数据库已经启用 PostgreSQL
RLS（Row-Level Security，行级安全策略）。调用方仍须把返回的可见性条件
应用到列表查询，并在单资源查询后调用对应 ``require_*`` 方法。
"""
from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.agency.errors import (
    AgencyTransactionAccessDenied,
    hidden_not_found,
)
from app.models.agency_customer_lifecycle import (
    AgencyBranch,
    AgencyBranchRoleGrant,
    AgencyCustomer,
    AgencyCustomerAdvisorAssignment,
)
from app.models.agency_transaction import (
    Agency,
    AgencyMembership,
)


AGENCY_WIDE_ROLES = frozenset({"owner", "admin"})
CUSTOMER_MANAGER_ROLES = frozenset({"branch_manager"})
QUOTE_MANAGER_BRANCH_ROLES = frozenset(
    {"branch_manager", "travel_advisor"}
)
ALLOWED_BRANCH_GRANT_ROLES = frozenset(
    {
        "travel_advisor",
        "booking_operator",
        "approver",
        "finance",
        "auditor",
        "branch_manager",
    }
)
BRANCH_NEW_WORK_STATUSES = frozenset({"active"})
BRANCH_DRAIN_STATUSES = frozenset({"active", "inactive"})


@dataclass(frozen=True)
class BranchAccess:
    """一次已校验的门店授权结果。"""

    membership: AgencyMembership
    grant: AgencyBranchRoleGrant | None

    @property
    def is_agency_wide(self) -> bool:
        return self.membership.role in AGENCY_WIDE_ROLES


class BranchAuthorization:
    """集中执行 fail-closed（失败时默认拒绝）的门店授权。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_membership(
        self,
        *,
        agency_id: uuid.UUID,
        user_id: uuid.UUID,
        for_share: bool = False,
    ) -> AgencyMembership | None:
        statement = (
            select(AgencyMembership)
            .join(Agency, Agency.id == AgencyMembership.agency_id)
            .where(AgencyMembership.agency_id == agency_id)
            .where(AgencyMembership.user_id == user_id)
            .where(AgencyMembership.status == "active")
            .where(Agency.status == "active")
        )
        if for_share:
            statement = statement.with_for_update(read=True)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    def is_agency_wide(membership: AgencyMembership | None) -> bool:
        return (
            membership is not None
            and membership.role in AGENCY_WIDE_ROLES
        )

    async def require_agency_wide(
        self,
        *,
        agency_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        hide_resource: bool = False,
        lock_scope: bool = False,
    ) -> AgencyMembership:
        membership = await self.get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
            for_share=lock_scope,
        )
        if self.is_agency_wide(membership):
            return membership  # type: ignore[return-value]
        if hide_resource:
            raise hidden_not_found()
        raise AgencyTransactionAccessDenied(
            "agency_wide_permission_denied",
            "只有旅行社负责人或管理员可以执行该操作",
        )

    async def _active_branch_grant(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        membership: AgencyMembership,
        roles: Collection[str],
        allowed_branch_statuses: Collection[str] = (
            BRANCH_NEW_WORK_STATUSES
        ),
    ) -> AgencyBranchRoleGrant | None:
        if not roles or not allowed_branch_statuses:
            return None
        result = await self.db.execute(
            select(AgencyBranchRoleGrant)
            .join(
                AgencyBranch,
                and_(
                    AgencyBranch.agency_id
                    == AgencyBranchRoleGrant.agency_id,
                    AgencyBranch.id == AgencyBranchRoleGrant.branch_id,
                ),
            )
            .where(AgencyBranchRoleGrant.agency_id == agency_id)
            .where(AgencyBranchRoleGrant.branch_id == branch_id)
            .where(
                AgencyBranchRoleGrant.membership_id == membership.id
            )
            .where(AgencyBranchRoleGrant.status == "active")
            .where(AgencyBranchRoleGrant.role.in_(tuple(roles)))
            .where(AgencyBranchRoleGrant.role == membership.role)
            .where(
                AgencyBranch.status.in_(
                    tuple(allowed_branch_statuses)
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def require_branch_role(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        roles: Collection[str],
        hide_resource: bool = True,
        allow_agency_wide: bool = True,
        lock_scope: bool = False,
        allowed_branch_statuses: Collection[str] = (
            BRANCH_NEW_WORK_STATUSES
        ),
    ) -> BranchAccess:
        if not allowed_branch_statuses:
            if hide_resource:
                raise hidden_not_found()
            raise AgencyTransactionAccessDenied(
                "agency_branch_not_active",
                "门店不存在或当前不可用",
            )
        branch_statement = (
            select(AgencyBranch.id)
            .where(AgencyBranch.agency_id == agency_id)
            .where(AgencyBranch.id == branch_id)
            .where(
                AgencyBranch.status.in_(
                    tuple(allowed_branch_statuses)
                )
            )
        )
        if lock_scope:
            branch_statement = branch_statement.with_for_update(read=True)
        branch_result = await self.db.execute(branch_statement)
        if branch_result.scalar_one_or_none() is None:
            if hide_resource:
                raise hidden_not_found()
            raise AgencyTransactionAccessDenied(
                "agency_branch_not_active",
                "门店不存在或当前不可用",
            )
        membership = await self.get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
            for_share=lock_scope,
        )
        if allow_agency_wide and self.is_agency_wide(membership):
            return BranchAccess(
                membership=membership,  # type: ignore[arg-type]
                grant=None,
            )
        if membership is not None:
            grant = await self._active_branch_grant(
                agency_id=agency_id,
                branch_id=branch_id,
                membership=membership,
                roles=roles,
                allowed_branch_statuses=allowed_branch_statuses,
            )
            if grant is not None:
                return BranchAccess(membership=membership, grant=grant)
        if hide_resource:
            raise hidden_not_found()
        raise AgencyTransactionAccessDenied(
            "agency_branch_permission_denied",
            "当前用户没有该门店的有效角色授权",
        )

    async def lock_branch_scope(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        allowed_branch_statuses: Collection[str],
        hide_resource: bool = True,
    ) -> None:
        """以共享行锁固定命令所允许的门店状态。"""

        if allowed_branch_statuses:
            result = await self.db.execute(
                select(AgencyBranch.id)
                .where(AgencyBranch.agency_id == agency_id)
                .where(AgencyBranch.id == branch_id)
                .where(
                    AgencyBranch.status.in_(
                        tuple(allowed_branch_statuses)
                    )
                )
                .with_for_update(read=True)
            )
            if result.scalar_one_or_none() is not None:
                return
        if hide_resource:
            raise hidden_not_found()
        raise AgencyTransactionAccessDenied(
            "agency_branch_not_active",
            "门店不存在或当前不可用",
        )

    async def lock_active_branch_scope(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        hide_resource: bool = True,
    ) -> None:
        """以共享行锁固定新业务所依赖的 active 门店。"""

        await self.lock_branch_scope(
            agency_id=agency_id,
            branch_id=branch_id,
            allowed_branch_statuses=BRANCH_NEW_WORK_STATUSES,
            hide_resource=hide_resource,
        )

    async def _has_active_assignment(
        self,
        *,
        customer: AgencyCustomer,
        membership: AgencyMembership,
        allowed_branch_statuses: Collection[str] = (
            BRANCH_DRAIN_STATUSES
        ),
    ) -> bool:
        return await self._has_active_assignment_ids(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            customer_id=customer.id,
            membership=membership,
            allowed_branch_statuses=allowed_branch_statuses,
        )

    async def _has_active_assignment_ids(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        customer_id: uuid.UUID,
        membership: AgencyMembership,
        allowed_branch_statuses: Collection[str] = (
            BRANCH_DRAIN_STATUSES
        ),
    ) -> bool:
        if not allowed_branch_statuses:
            return False
        result = await self.db.execute(
            select(AgencyCustomerAdvisorAssignment.id)
            .join(
                AgencyBranchRoleGrant,
                and_(
                    AgencyBranchRoleGrant.agency_id
                    == AgencyCustomerAdvisorAssignment.agency_id,
                    AgencyBranchRoleGrant.branch_id
                    == AgencyCustomerAdvisorAssignment.branch_id,
                    AgencyBranchRoleGrant.id
                    == AgencyCustomerAdvisorAssignment.advisor_role_grant_id,
                    AgencyBranchRoleGrant.membership_id
                    == AgencyCustomerAdvisorAssignment.advisor_membership_id,
                ),
            )
            .join(
                AgencyBranch,
                and_(
                    AgencyBranch.agency_id
                    == AgencyCustomerAdvisorAssignment.agency_id,
                    AgencyBranch.id
                    == AgencyCustomerAdvisorAssignment.branch_id,
                ),
            )
            .where(
                AgencyCustomerAdvisorAssignment.agency_id == agency_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.branch_id == branch_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.customer_id == customer_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.advisor_membership_id
                == membership.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
            .where(AgencyBranchRoleGrant.status == "active")
            .where(AgencyBranchRoleGrant.role == "travel_advisor")
            .where(AgencyBranchRoleGrant.role == membership.role)
            .where(
                AgencyBranch.status.in_(
                    tuple(allowed_branch_statuses)
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def require_customer_view(
        self,
        *,
        customer: AgencyCustomer,
        actor_user_id: uuid.UUID,
    ) -> BranchAccess | None:
        if (
            customer.user_id == actor_user_id
            and customer.consent_status != "unknown"
        ):
            return None
        membership = await self.get_active_membership(
            agency_id=customer.agency_id,
            user_id=actor_user_id,
        )
        if self.is_agency_wide(membership):
            return BranchAccess(
                membership=membership,  # type: ignore[arg-type]
                grant=None,
            )
        if membership is not None:
            manager_grant = await self._active_branch_grant(
                agency_id=customer.agency_id,
                branch_id=customer.branch_id,
                membership=membership,
                roles=CUSTOMER_MANAGER_ROLES,
                allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
            )
            if manager_grant is not None:
                return BranchAccess(membership, manager_grant)
            if (
                membership.role == "travel_advisor"
                and await self._has_active_assignment(
                    customer=customer,
                    membership=membership,
                    allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
                )
            ):
                advisor_grant = await self._active_branch_grant(
                    agency_id=customer.agency_id,
                    branch_id=customer.branch_id,
                    membership=membership,
                    roles={"travel_advisor"},
                    allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
                )
                if advisor_grant is not None:
                    return BranchAccess(membership, advisor_grant)
        raise hidden_not_found()

    async def require_customer_manager(
        self,
        *,
        customer: AgencyCustomer,
        actor_user_id: uuid.UUID,
        hide_resource: bool = True,
        lock_scope: bool = False,
    ) -> BranchAccess:
        return await self.require_branch_role(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            actor_user_id=actor_user_id,
            roles=CUSTOMER_MANAGER_ROLES,
            hide_resource=hide_resource,
            lock_scope=lock_scope,
        )

    async def require_customer_cleanup_manager(
        self,
        *,
        customer: AgencyCustomer,
        actor_user_id: uuid.UUID,
    ) -> BranchAccess:
        """允许全域管理员清理已停用门店的客户与顾问绑定。"""

        branch_result = await self.db.execute(
            select(AgencyBranch.id)
            .where(AgencyBranch.agency_id == customer.agency_id)
            .where(AgencyBranch.id == customer.branch_id)
            .with_for_update(read=True)
        )
        if branch_result.scalar_one_or_none() is None:
            raise hidden_not_found()
        membership = await self.get_active_membership(
            agency_id=customer.agency_id,
            user_id=actor_user_id,
            for_share=True,
        )
        if self.is_agency_wide(membership):
            return BranchAccess(
                membership=membership,  # type: ignore[arg-type]
                grant=None,
            )
        return await self.require_branch_role(
            agency_id=customer.agency_id,
            branch_id=customer.branch_id,
            actor_user_id=actor_user_id,
            roles=CUSTOMER_MANAGER_ROLES,
            allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
        )

    async def require_quote_manager(
        self,
        *,
        customer: AgencyCustomer,
        actor_user_id: uuid.UUID,
        hide_resource: bool = True,
        lock_scope: bool = False,
        allowed_branch_statuses: Collection[str] = (
            BRANCH_NEW_WORK_STATUSES
        ),
    ) -> BranchAccess:
        if lock_scope:
            branch_result = await self.db.execute(
                select(AgencyBranch.id)
                .where(AgencyBranch.agency_id == customer.agency_id)
                .where(AgencyBranch.id == customer.branch_id)
                .where(
                    AgencyBranch.status.in_(
                        tuple(allowed_branch_statuses)
                    )
                )
                .with_for_update(read=True)
            )
            if branch_result.scalar_one_or_none() is None:
                if hide_resource:
                    raise hidden_not_found()
                raise AgencyTransactionAccessDenied(
                    "agency_branch_not_active",
                    "门店不存在或当前不可用",
                )
        membership = await self.get_active_membership(
            agency_id=customer.agency_id,
            user_id=actor_user_id,
            for_share=lock_scope,
        )
        if self.is_agency_wide(membership):
            return BranchAccess(
                membership=membership,  # type: ignore[arg-type]
                grant=None,
            )
        if membership is not None and membership.role == "branch_manager":
            grant = await self._active_branch_grant(
                agency_id=customer.agency_id,
                branch_id=customer.branch_id,
                membership=membership,
                roles={"branch_manager"},
                allowed_branch_statuses=allowed_branch_statuses,
            )
            if grant is not None:
                return BranchAccess(membership, grant)
        if (
            membership is not None
            and membership.role == "travel_advisor"
            and await self._has_active_assignment(
                customer=customer,
                membership=membership,
                allowed_branch_statuses=allowed_branch_statuses,
            )
        ):
            grant = await self._active_branch_grant(
                agency_id=customer.agency_id,
                branch_id=customer.branch_id,
                membership=membership,
                roles={"travel_advisor"},
                allowed_branch_statuses=allowed_branch_statuses,
            )
            if grant is not None:
                return BranchAccess(membership, grant)
        if hide_resource:
            raise hidden_not_found()
        raise AgencyTransactionAccessDenied(
            "agency_quote_permission_denied",
            "当前用户不能管理该客户的报价",
        )

    async def require_branch_approver(
        self,
        *,
        agency_id: uuid.UUID,
        branch_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        hide_resource: bool = True,
        lock_scope: bool = False,
        allowed_branch_statuses: Collection[str] = (
            BRANCH_NEW_WORK_STATUSES
        ),
    ) -> BranchAccess:
        return await self.require_branch_role(
            agency_id=agency_id,
            branch_id=branch_id,
            actor_user_id=actor_user_id,
            roles={"approver"},
            hide_resource=hide_resource,
            allow_agency_wide=False,
            lock_scope=lock_scope,
            allowed_branch_statuses=allowed_branch_statuses,
        )

    async def require_transaction_view(
        self,
        *,
        resource: object,
        actor_user_id: uuid.UUID,
        include_approver: bool = False,
    ) -> BranchAccess | None:
        """校验报价或订单的客户、门店与租户范围。

        ``include_approver`` 只证明调用方具备该门店的 approver 授权；
        订单审核记录是否存在仍由订单审核服务校验。
        """

        owner_user_id = getattr(resource, "user_id")
        if owner_user_id == actor_user_id:
            return None
        agency_id = getattr(resource, "agency_id")
        branch_id = getattr(resource, "branch_id")
        customer_id = getattr(resource, "customer_id")
        membership = await self.get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if self.is_agency_wide(membership):
            return BranchAccess(
                membership=membership,  # type: ignore[arg-type]
                grant=None,
            )
        if membership is not None:
            allowed_roles = {"branch_manager"}
            if include_approver:
                allowed_roles.add("approver")
            grant = await self._active_branch_grant(
                agency_id=agency_id,
                branch_id=branch_id,
                membership=membership,
                roles=allowed_roles,
                allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
            )
            if grant is not None:
                return BranchAccess(membership, grant)
            if (
                membership.role == "travel_advisor"
                and await self._has_active_assignment_ids(
                    agency_id=agency_id,
                    branch_id=branch_id,
                    customer_id=customer_id,
                    membership=membership,
                    allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
                )
            ):
                advisor_grant = await self._active_branch_grant(
                    agency_id=agency_id,
                    branch_id=branch_id,
                    membership=membership,
                    roles={"travel_advisor"},
                    allowed_branch_statuses=BRANCH_DRAIN_STATUSES,
                )
                if advisor_grant is not None:
                    return BranchAccess(membership, advisor_grant)
        raise hidden_not_found()

    async def branch_visibility_filter(
        self,
        *,
        agency_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        roles: Collection[str] | None = None,
        branch_column: object | None = None,
    ) -> ColumnElement[bool]:
        membership = await self.get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if self.is_agency_wide(membership):
            return true()
        if membership is None:
            return false()
        target_branch_column = (
            AgencyBranch.id if branch_column is None else branch_column
        )
        scoped_branch = aliased(AgencyBranch)
        role_filter: ColumnElement[bool] = (
            AgencyBranchRoleGrant.role == membership.role
        )
        if roles is not None:
            role_values = tuple(roles)
            if not role_values:
                return false()
            role_filter = and_(
                role_filter,
                AgencyBranchRoleGrant.role.in_(role_values),
            )
        return exists(
            select(1)
            .select_from(AgencyBranchRoleGrant)
            .join(
                scoped_branch,
                and_(
                    scoped_branch.agency_id
                    == AgencyBranchRoleGrant.agency_id,
                    scoped_branch.id == AgencyBranchRoleGrant.branch_id,
                ),
            )
            .where(
                AgencyBranchRoleGrant.agency_id
                == agency_id
            )
            .where(
                AgencyBranchRoleGrant.branch_id
                == target_branch_column
            )
            .where(
                AgencyBranchRoleGrant.membership_id == membership.id
            )
            .where(AgencyBranchRoleGrant.status == "active")
            .where(role_filter)
            .where(scoped_branch.status.in_(BRANCH_DRAIN_STATUSES))
        )

    async def transaction_visibility_filter(
        self,
        *,
        model: type,
        agency_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        include_approver: bool = False,
    ) -> ColumnElement[bool]:
        """返回可直接用于报价或订单列表的关联可见性条件。

        ``model`` 必须提供 ``agency_id``、``branch_id``、``customer_id`` 和
        ``user_id`` 列。若允许 approver，调用方还必须追加“订单已有审核记录”
        条件，不能让待审核权限扩散到普通报价或无审核订单。
        """

        membership = await self.get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if self.is_agency_wide(membership):
            return true()

        visible_as_customer = model.user_id == actor_user_id
        if membership is None:
            return visible_as_customer

        branch_roles = ["branch_manager"]
        if include_approver:
            branch_roles.append("approver")
        granted_branch = aliased(AgencyBranch)
        branch_grant = exists(
            select(1)
            .select_from(AgencyBranchRoleGrant)
            .join(
                granted_branch,
                and_(
                    granted_branch.agency_id
                    == AgencyBranchRoleGrant.agency_id,
                    granted_branch.id
                    == AgencyBranchRoleGrant.branch_id,
                ),
            )
            .where(AgencyBranchRoleGrant.agency_id == model.agency_id)
            .where(AgencyBranchRoleGrant.branch_id == model.branch_id)
            .where(
                AgencyBranchRoleGrant.membership_id == membership.id
            )
            .where(AgencyBranchRoleGrant.role.in_(branch_roles))
            .where(AgencyBranchRoleGrant.role == membership.role)
            .where(AgencyBranchRoleGrant.status == "active")
            .where(granted_branch.status.in_(BRANCH_DRAIN_STATUSES))
        )
        assigned_branch = aliased(AgencyBranch)
        assigned_advisor = exists(
            select(1)
            .select_from(AgencyCustomerAdvisorAssignment)
            .join(
                AgencyBranchRoleGrant,
                and_(
                    AgencyBranchRoleGrant.agency_id
                    == AgencyCustomerAdvisorAssignment.agency_id,
                    AgencyBranchRoleGrant.branch_id
                    == AgencyCustomerAdvisorAssignment.branch_id,
                    AgencyBranchRoleGrant.id
                    == AgencyCustomerAdvisorAssignment.advisor_role_grant_id,
                    AgencyBranchRoleGrant.membership_id
                    == AgencyCustomerAdvisorAssignment.advisor_membership_id,
                ),
            )
            .join(
                assigned_branch,
                and_(
                    assigned_branch.agency_id
                    == AgencyCustomerAdvisorAssignment.agency_id,
                    assigned_branch.id
                    == AgencyCustomerAdvisorAssignment.branch_id,
                ),
            )
            .where(
                AgencyCustomerAdvisorAssignment.agency_id == model.agency_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.branch_id == model.branch_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.customer_id
                == model.customer_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.advisor_membership_id
                == membership.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
            .where(AgencyBranchRoleGrant.status == "active")
            .where(AgencyBranchRoleGrant.role == "travel_advisor")
            .where(AgencyBranchRoleGrant.role == membership.role)
            .where(assigned_branch.status.in_(BRANCH_DRAIN_STATUSES))
        )
        return or_(visible_as_customer, branch_grant, assigned_advisor)

    async def customer_visibility_filter(
        self,
        *,
        agency_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> ColumnElement[bool]:
        membership = await self.get_active_membership(
            agency_id=agency_id,
            user_id=actor_user_id,
        )
        if self.is_agency_wide(membership):
            return true()

        visible_as_customer = and_(
            AgencyCustomer.user_id == actor_user_id,
            AgencyCustomer.consent_status != "unknown",
        )
        if membership is None:
            return visible_as_customer

        manager_branch = aliased(AgencyBranch)
        manager_grant = exists(
            select(1)
            .select_from(AgencyBranchRoleGrant)
            .join(
                manager_branch,
                and_(
                    manager_branch.agency_id
                    == AgencyBranchRoleGrant.agency_id,
                    manager_branch.id
                    == AgencyBranchRoleGrant.branch_id,
                ),
            )
            .where(
                AgencyBranchRoleGrant.agency_id
                == AgencyCustomer.agency_id
            )
            .where(
                AgencyBranchRoleGrant.branch_id
                == AgencyCustomer.branch_id
            )
            .where(
                AgencyBranchRoleGrant.membership_id == membership.id
            )
            .where(AgencyBranchRoleGrant.role == "branch_manager")
            .where(AgencyBranchRoleGrant.role == membership.role)
            .where(AgencyBranchRoleGrant.status == "active")
            .where(manager_branch.status.in_(BRANCH_DRAIN_STATUSES))
        )
        advisor_branch = aliased(AgencyBranch)
        assigned_advisor = exists(
            select(1)
            .select_from(AgencyCustomerAdvisorAssignment)
            .join(
                AgencyBranchRoleGrant,
                and_(
                    AgencyBranchRoleGrant.agency_id
                    == AgencyCustomerAdvisorAssignment.agency_id,
                    AgencyBranchRoleGrant.branch_id
                    == AgencyCustomerAdvisorAssignment.branch_id,
                    AgencyBranchRoleGrant.id
                    == AgencyCustomerAdvisorAssignment.advisor_role_grant_id,
                    AgencyBranchRoleGrant.membership_id
                    == AgencyCustomerAdvisorAssignment.advisor_membership_id,
                ),
            )
            .join(
                advisor_branch,
                and_(
                    advisor_branch.agency_id
                    == AgencyCustomerAdvisorAssignment.agency_id,
                    advisor_branch.id
                    == AgencyCustomerAdvisorAssignment.branch_id,
                ),
            )
            .where(
                AgencyCustomerAdvisorAssignment.agency_id
                == AgencyCustomer.agency_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.branch_id
                == AgencyCustomer.branch_id
            )
            .where(
                AgencyCustomerAdvisorAssignment.customer_id
                == AgencyCustomer.id
            )
            .where(
                AgencyCustomerAdvisorAssignment.advisor_membership_id
                == membership.id
            )
            .where(AgencyCustomerAdvisorAssignment.status == "active")
            .where(AgencyBranchRoleGrant.status == "active")
            .where(AgencyBranchRoleGrant.role == "travel_advisor")
            .where(AgencyBranchRoleGrant.role == membership.role)
            .where(advisor_branch.status.in_(BRANCH_DRAIN_STATUSES))
        )
        return or_(visible_as_customer, manager_grant, assigned_advisor)
