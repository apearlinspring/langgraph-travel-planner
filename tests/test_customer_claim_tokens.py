from __future__ import annotations

import base64
import hashlib
import re

from app.agency.customer_claim_tokens import (
    generate_claim_token,
    hash_claim_token,
    verify_claim_token,
)


def test_generate_claim_token_is_urlsafe_with_32_bytes_of_entropy():
    token = generate_claim_token()
    padding = "=" * (-len(token) % 4)
    decoded = base64.b64decode(
        token + padding,
        altchars=b"-_",
        validate=True,
    )

    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert len(decoded) == 32


def test_hash_claim_token_is_lowercase_sha256_of_utf8_token():
    token = "customer-claim-token_测试"
    expected = hashlib.sha256(token.encode("utf-8")).hexdigest()

    digest = hash_claim_token(token)

    assert digest == expected
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_verify_claim_token_matches_only_the_original_secret():
    token = generate_claim_token()
    digest = hash_claim_token(token)

    assert verify_claim_token(token, digest) is True
    assert verify_claim_token(f"{token}x", digest) is False
