"""Security helpers for password hashing, JWT handling and redaction."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Optional

import bcrypt
import jwt

from app.config import settings


REDACTED_VALUE = "[REDACTED]"

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "email",
    "id_card",
    "identity",
    "mobile",
    "passport",
    "password",
    "phone",
    "secret",
    "token",
    "身份证",
    "手机号",
    "护照",
    "邮箱",
    "电话",
)

SAFE_TOKEN_METRIC_KEYS = {
    "estimated_input_tokens",
    "estimated_output_tokens",
    "estimated_total_tokens",
    "average_estimated_total_tokens",
    "max_estimated_total_tokens",
    "token_event_count",
    "token_count",
    "token_ratio",
    "warning_token_ratio",
}

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.+-])",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
ID_CARD_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])\d{6}(?:18|19|20)\d{2}"
    r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]"
    r"(?![0-9A-Za-z])"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
BEARER_PATTERN = re.compile(
    r"(?i)\b(?:bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}"
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"authorization|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"
)
API_KEY_PATTERN = re.compile(
    r"\b(?:sk|rk|pk|ak|dashscope|amap|tavily)[-_][A-Za-z0-9][A-Za-z0-9_-]{10,}\b",
    re.IGNORECASE,
)
URL_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|key|access[_-]?token|refresh[_-]?token|"
    r"token|secret|password|authorization)=)([^&#\s]+)"
)


def is_sensitive_key(key: object) -> bool:
    """Return True when a field name should never expose its raw value."""

    normalized = str(key or "").lower()
    if normalized in SAFE_TOKEN_METRIC_KEYS:
        return False
    if normalized.endswith("_tokens") or normalized.endswith("_token_count"):
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_sensitive_text(text: str) -> str:
    """Redact common PII and credential-shaped substrings from text."""

    if not text:
        return text
    redacted = str(text)
    redacted = URL_QUERY_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTED_VALUE}",
        redacted,
    )
    redacted = SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}={REDACTED_VALUE}",
        redacted,
    )
    for pattern in (
        BEARER_PATTERN,
        JWT_PATTERN,
        API_KEY_PATTERN,
        EMAIL_PATTERN,
        PHONE_PATTERN,
        ID_CARD_PATTERN,
    ):
        redacted = pattern.sub(REDACTED_VALUE, redacted)
    return redacted


def redact_sensitive_data(
    value,
    *,
    max_depth: int = 8,
):
    """Recursively redact sensitive values while preserving response shape."""

    if max_depth < 0:
        return REDACTED_VALUE
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            text_key = str(key)
            if is_sensitive_key(text_key):
                redacted[text_key] = REDACTED_VALUE
            else:
                redacted[text_key] = redact_sensitive_data(
                    item,
                    max_depth=max_depth - 1,
                )
        return redacted
    if isinstance(value, list):
        return [
            redact_sensitive_data(item, max_depth=max_depth - 1)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_data(item, max_depth=max_depth - 1)
            for item in value
        )
    if isinstance(value, set):
        return {
            redact_sensitive_data(item, max_depth=max_depth - 1)
            for item in value
        }
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def hash_password(password: str) -> str:
    """Hash a plaintext password."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against the stored hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode a JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
