"""客户认领所用的一次性不透明 token。

数据库只持久化 SHA-256 摘要。原始 token 仅在邀请首次创建成功时返回，
不得写入日志、事件、幂等负载或后续查询响应。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets


CLAIM_TOKEN_ENTROPY_BYTES = 32


def generate_claim_token() -> str:
    """生成包含 32 bytes 随机熵的 URL-safe 不透明 token。"""

    return secrets.token_urlsafe(CLAIM_TOKEN_ENTROPY_BYTES)


def hash_claim_token(token: str) -> str:
    """生成用于持久化和查找的 SHA-256 小写十六进制摘要。"""

    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def verify_claim_token(token: str, expected_digest: str) -> bool:
    """以常量时间比较 token 摘要，避免直接比较原始秘密。"""

    actual_digest = hash_claim_token(token)
    return hmac.compare_digest(actual_digest, str(expected_digest).lower())


__all__ = [
    "CLAIM_TOKEN_ENTROPY_BYTES",
    "generate_claim_token",
    "hash_claim_token",
    "verify_claim_token",
]
