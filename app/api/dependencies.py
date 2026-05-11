"""API 依赖项。"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import UserRole, get_user_role
from app.models.base import get_db
from app.models.user import User
from app.utils.security import decode_access_token


security = HTTPBearer(auto_error=False)


def error_detail(
    code: str,
    message: str,
    *,
    required_roles: list[str] | None = None,
    current_role: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable, non-secret API error detail payload."""

    payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if required_roles is not None:
        payload["required_roles"] = required_roles
    if current_role is not None:
        payload["current_role"] = current_role
    if extra:
        payload.update(extra)
    return payload


def api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    required_roles: list[str] | None = None,
    current_role: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_detail(
            code,
            message,
            required_roles=required_roles,
            current_role=current_role,
        ),
        headers=headers,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """获取当前登录用户（依赖注入）。"""

    if credentials is None:
        raise api_error(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth_required",
            message="缺少认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)

    if payload is None:
        raise api_error(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_token",
            message="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if user_id is None:
        raise api_error(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_token_payload",
            message="令牌格式错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise api_error(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="user_not_found",
            message="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_user_role(*allowed_roles: UserRole):
    """FastAPI dependency factory for lightweight role checks."""

    allowed = list(allowed_roles)

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        current_role = get_user_role(user)
        if current_role not in allowed_roles:
            raise api_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="permission_denied",
                message="当前用户没有执行该操作的权限",
                required_roles=allowed,
                current_role=current_role,
            )
        return user

    return _dependency
