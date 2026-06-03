"""
用户管理 API
"""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, status
from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import uuid4

from app.config import settings
from app.models.base import get_db
from app.models.user import User
from app.schemas.user import UserRegister, UserLogin, UserResponse, TokenResponse
from app.utils.security import hash_password, verify_password, create_access_token
from app.api.dependencies import get_current_user
from app.api.dependencies import api_error
from app.core.permissions import get_user_role

router = APIRouter(prefix="/users", tags=["用户管理"])
_login_attempt_buckets: dict[str, list[float]] = defaultdict(list)


def _set_auth_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.auth_cookie_secure_resolved,
        samesite=settings.auth_cookie_samesite_resolved,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
    )


def _login_rate_limit_key(username: str, request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    normalized_username = (username or "").strip().lower() or "anonymous"
    return f"{client_host}:{normalized_username}"


def _prune_login_attempts(now: float) -> None:
    window_seconds = settings.auth_rate_limit_window_seconds
    stale_before = now - window_seconds
    empty_keys: list[str] = []
    for key, attempts in _login_attempt_buckets.items():
        attempts[:] = [value for value in attempts if value > stale_before]
        if not attempts:
            empty_keys.append(key)
    for key in empty_keys:
        _login_attempt_buckets.pop(key, None)


def _enforce_login_rate_limit(username: str, request: Request) -> tuple[str, int]:
    now = time.time()
    _prune_login_attempts(now)
    key = _login_rate_limit_key(username, request)
    attempts = _login_attempt_buckets[key]
    if len(attempts) >= settings.auth_rate_limit_max_attempts:
        retry_after = max(
            1,
            int(settings.auth_rate_limit_window_seconds - (now - attempts[0])),
        )
        raise api_error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="too_many_login_attempts",
            message="登录失败次数过多，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
    return key, int(now)


def _record_failed_login(key: str, now: int) -> None:
    _login_attempt_buckets[key].append(float(now))


def _clear_failed_login(key: str) -> None:
    _login_attempt_buckets.pop(key, None)


@router.post("/register", response_model=TokenResponse)
async def register(
        user_data: UserRegister,
        response: Response,
        db: AsyncSession = Depends(get_db)
):
    """用户注册"""

    # 检查用户名是否存在
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="username_exists",
            message="用户名已存在",
        )

    # 检查邮箱是否存在
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="email_exists",
            message="邮箱已被注册",
        )

    # 创建用户
    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        preferences={"role": "user"}
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 生成 JWT
    access_token = create_access_token(
        data={"sub": str(user.id), "role": get_user_role(user)}
    )
    _set_auth_cookie(response, access_token)

    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
async def login(
        credentials: UserLogin,
        request: Request,
        response: Response,
        db: AsyncSession = Depends(get_db)
):
    """用户登录"""
    rate_limit_key, now = _enforce_login_rate_limit(credentials.username, request)

    # 查询用户
    result = await db.execute(select(User).where(User.username == credentials.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.password_hash):
        _record_failed_login(rate_limit_key, now)
        raise api_error(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_credentials",
            message="用户名或密码错误",
        )

    # 生成 JWT
    access_token = create_access_token(
        data={"sub": str(user.id), "role": get_user_role(user)}
    )
    _clear_failed_login(rate_limit_key)
    _set_auth_cookie(response, access_token)

    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
        user: User = Depends(get_current_user)
):
    """获取当前用户信息"""
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(response: Response):
    """清理当前登录态 Cookie。"""

    _clear_auth_cookie(response)
    return {"message": "已退出登录", "request_id": str(uuid4())}
