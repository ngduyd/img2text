"""#11 + P2 #16 — bcrypt cap 72 byte; worker_token hashed at rest.

Bcrypt truncate im lặng → cap ở nguồn (unit) + API boundary; worker_token
lưu sha256 hex (claim comparison = hmac.compare_digest ở jobs gates).
"""

import hashlib

import pytest

from app.core.security import (
    BCRYPT_MAX_BYTES,
    hash_password,
    hash_worker_token,
    password_too_long,
    verify_password,
)

def test_worker_token_hash_matches():
    token = "test-token-123"
    assert hash_worker_token(token) == hashlib.sha256(token.encode()).hexdigest()

def test_hash_password_rejects_over_72_bytes():
    long_pw = "x" * 73
    with pytest.raises(ValueError, match="72"):
        hash_password(long_pw)

def test_hash_password_accepts_72_bytes():
    pw = "x" * BCRYPT_MAX_BYTES
    h = hash_password(pw)
    assert verify_password(pw, h)

def test_password_too_long_counts_utf8_bytes():
    # "ệ" = 3 byte UTF-8: 25 ký tự × 3 = 75 byte > 72 dù len() chỉ 25
    accented = "ệ" * 25
    assert len(accented) < BCRYPT_MAX_BYTES
    assert password_too_long(accented) is True
    with pytest.raises(ValueError, match="72"):
        hash_password(accented)
