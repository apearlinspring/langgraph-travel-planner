"""旅行社业务服务可安全映射到 API 的领域错误。"""
from __future__ import annotations


class AgencyTransactionError(Exception):
    """旅行社业务域错误基类。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgencyTransactionNotFound(AgencyTransactionError):
    """资源不存在，或调用方无权知道该资源是否存在。"""


class AgencyTransactionAccessDenied(AgencyTransactionError):
    """调用方没有租户或门店级操作权限。"""


class AgencyTransactionConflict(AgencyTransactionError):
    """幂等、版本或状态机冲突。"""


class AgencyTransactionValidationError(AgencyTransactionError):
    """请求字段可解析，但不满足业务域约束。"""


class AgencyTransactionPersistenceError(AgencyTransactionError):
    """数据库暂时无法可靠完成业务操作。"""


def hidden_not_found() -> AgencyTransactionNotFound:
    """隐藏跨租户、跨门店资源是否存在，避免对象枚举。"""

    return AgencyTransactionNotFound(
        "agency_transaction_not_found",
        "交易资源不存在",
    )
