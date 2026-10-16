"""P2 #16 (spec 2026-10-16): worker_token hashed at rest."""

import hashlib

from app.core.security import hash_worker_token

def test_worker_token_hash_matches():
    token = "test-token-123"
    assert hash_worker_token(token) == hashlib.sha256(token.encode()).hexdigest()
