"""P2 #16 (spec 2026-10-16): migration 2026-10-16_worker_token_hash.sql.

Pattern A (supervisor 2026-10-16 — checklist/test mẫu không tồn tại):
1. checksum tamper-detection — sha256(SQL) pin, file sửa sau apply → fail;
2. apply vào DB test — legacy plaintext row được backfill thành sha256 hex,
   cột cũ biến mất;
3. re-run → idempotent (không lỗi, kết quả giữ nguyên).
"""

import hashlib
import os
from pathlib import Path

import asyncpg
from sqlalchemy import text


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "migrations"
    / "2026-10-16_worker_token_hash.sql"
)
# Tamper-detection: migration đã apply prod KHÔNG được sửa lặng — mọi đổi
# chữ phải bump constant này (kèm migration mới/rolled-back có chủ đích).
CHECKSUM = "d30862d1ea16ac466e6d24437c44ef6d21f1f5b4127bf88e9a2c1cd6118a8416"

PLAINTEXT = "legacy-claim-token-abc"

async def _apply_migration() -> None:
    """asyncpg simple query (no args) — psql-equivalent: multi-statement
    script + DO block không chạy được qua prepared statement (extended
    query protocol). DSN tách khỏi SQLAlchemy URL postgresql+asyncpg://."""
    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(MIGRATION.read_text())
    finally:
        await conn.close()

def test_migration_checksum_unchanged():
    assert hashlib.sha256(MIGRATION.read_bytes()).hexdigest() == CHECKSUM

async def _job_columns(db_session) -> dict[str, bool]:
    rows = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'jobs'"
        )
    )
    names = {r[0] for r in rows}
    return {
        "worker_token_hash": "worker_token_hash" in names,
        "worker_token": "worker_token" in names,
    }

async def test_migration_backfills_and_drops_plaintext_column(client, db_session):
    # Legacy state: cột plaintext tồn tại trước migration.
    await db_session.execute(
        text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS worker_token TEXT")
    )
    r = await client.post(
        "/api/auth/register", json={"email": "mig-hash@x.io", "password": "secret123"}
    )
    assert r.status_code == 201, r.text
    user_id = await db_session.scalar(
        text("SELECT id FROM users WHERE email = :e"), {"e": "mig-hash@x.io"}
    )
    await db_session.execute(
        text(
            "INSERT INTO jobs (user_id, status, storage_key, file_type, "
            "page_count, worker_token) "
            "VALUES (:u, 'extracting', 'uploads/a.jpg', 'image', 1, :tok)"
        ),
        {"u": user_id, "tok": PLAINTEXT},
    )
    await db_session.commit()

    await _apply_migration()

    cols = await _job_columns(db_session)
    assert cols["worker_token_hash"] and not cols["worker_token"]
    hashed = await db_session.scalar(
        text(
            "SELECT worker_token_hash FROM jobs WHERE user_id = :u"
        ),
        {"u": user_id},
    )
    assert hashed == hashlib.sha256(PLAINTEXT.encode()).hexdigest()
    # plaintext không còn ở bất kỳ cột nào của row (cột cũ đã DROP)
    row_text = await db_session.scalar(
        text("SELECT t::text FROM jobs t WHERE user_id = :u"), {"u": user_id}
    )
    assert PLAINTEXT not in row_text

    # Idempotent: re-run lần 2 không lỗi, hash giữ nguyên.
    await _apply_migration()
    hashed2 = await db_session.scalar(
        text("SELECT worker_token_hash FROM jobs WHERE user_id = :u"),
        {"u": user_id},
    )
    assert hashed2 == hashed
