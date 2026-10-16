"""#11 (spec 2026-10-15): bcrypt cap 72 byte — hash_password ValueError.

Bcrypt truncate im lặng → hai password khác nhau cùng tiền tố 72B mở khoá
được nhau; cap phải chặn ở nguồn (unit) + API boundary (test_auth/test_profile).
"""

import pytest

from app.core.security import BCRYPT_MAX_BYTES, hash_password, password_too_long, verify_password


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
