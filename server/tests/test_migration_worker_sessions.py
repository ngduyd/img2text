"""Spec 2026-10-16 kaggle session worker (T1): migration
2026-10-16_worker_sessions.sql — worker_sessions table + jobs.session_id.

Pattern test_migration_p2_worker_token.py:
1. checksum tamper-detection — sha256(SQL) pin;
2. apply 2 lần không lỗi (idempotent);
3. FK ON DELETE SET NULL (AC3a): xóa session row khi job còn trỏ →
   job.session_id tự NULL, job KHÔNG mất.
"""

import hashlib
import os

from app.core.config import settings
from pathlib import Path

import asyncpg
from sqlalchemy import text

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "migrations"
    / "2026-10-16_worker_sessions.sql"
)
# Tamper-detection: migration đã apply prod KHÔNG được sửa lặng — mọi đổi
# chữ phải bump constant này.
CHECKSUM = "fce4a4a3711fc4e5065b921a6623108c99d1ae263ce9a953f2bb7ca586b8700c"

async def _apply_migration() -> None:
    """asyncpg simple query (no args) — psql-equivalent multi-statement."""
    dsn = os.environ.get("DATABASE_URL", str(settings.database_url)).replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(MIGRATION.read_text())
    finally:
        await conn.close()

def test_migration_checksum_unchanged():
    assert hashlib.sha256(MIGRATION.read_bytes()).hexdigest() == CHECKSUM

async def test_migration_idempotent_and_link(client, db_session):
    await _apply_migration()
    await _apply_migration()
    # jobs.session_id link được hàng worker_sessions.
    await db_session.execute(
        text(
            "INSERT INTO worker_sessions (kernel_ref, key_hash) "
            "VALUES ('testuser/img2text-session', 'deadbeef')"
        )
    )
    r = await client.post(
        "/api/auth/register",
        json={"email": "ws-mig@x.io", "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    user_id = await db_session.scalar(
        text("SELECT id FROM users WHERE email = :e"), {"e": "ws-mig@x.io"}
    )
    await db_session.execute(
        text(
            "INSERT INTO jobs (user_id, status, storage_key, file_type, "
            "page_count, session_id) "
            "VALUES (:u, 'extracting', 'uploads/a.jpg', 'image', 1, "
            "(SELECT id FROM worker_sessions WHERE key_hash = 'deadbeef'))"
        ),
        {"u": user_id},
    )
    await db_session.commit()
    linked = await db_session.scalar(
        text(
            "SELECT s.kernel_ref FROM jobs j JOIN worker_sessions s "
            "ON s.id = j.session_id WHERE j.user_id = :u"
        ),
        {"u": user_id},
    )
    assert linked == "testuser/img2text-session"
    # AC3a: xóa session row khi job còn trỏ → job.session_id tự NULL, job giữ.
    await db_session.execute(
        text("DELETE FROM worker_sessions WHERE key_hash = 'deadbeef'")
    )
    await db_session.commit()
    row = await db_session.execute(
        text(
            "SELECT j.session_id, j.status FROM jobs j WHERE j.user_id = :u"
        ),
        {"u": user_id},
    )
    session_id, status = row.one()
    assert session_id is None
    assert status == "extracting"
    # Đóng read txn NGAY — txn còn mở giữ S lock trên jobs → DDL re-run
    # (ACCESS EXCLUSIVE) chờ vô hạn → hang (pattern p2 migration test).
    await db_session.commit()
    # Re-run lần 3 sau khi data thay đổi — vẫn idempotent.
    await _apply_migration()
