"""Wave-5 S1 (spec 2026-10-15): migration quota_purge — model columns đọc được.

Red-green: ALTER-only migration áp tay lên test2; create_all không ALTER —
test xác nhận ORM map đúng 5 cột mới + default server-side.
"""

from sqlalchemy import text

from app.core.models import Job, User

EXPECTED_USER = {"upload_byte_limit", "auto_purge", "purge_notice_seen"}
EXPECTED_JOB = {"upload_bytes", "storage_purged_at"}

def test_user_quota_purge_columns_mapped():
    cols = {c.name for c in User.__table__.columns}
    assert EXPECTED_USER <= cols

def test_job_purge_columns_mapped():
    cols = {c.name for c in Job.__table__.columns}
    assert EXPECTED_JOB <= cols

async def test_db_columns_exist_and_defaults(db_session):
    """Migration đã chạy trên test2: 5 cột có thật, default đúng spec."""
    uc = (
        await db_session.execute(
            text(
                "SELECT column_name, column_default, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name='users' AND column_name IN "
                "('upload_byte_limit','auto_purge','purge_notice_seen')"
            )
        )
    ).all()
    assert {r[0] for r in uc} == EXPECTED_USER
    d = {r[0]: (r[1], r[2]) for r in uc}
    assert d["upload_byte_limit"][0] == "211812352"
    assert d["auto_purge"][0] == "true"
    assert d["purge_notice_seen"][0] == "false"
    jc = (
        await db_session.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name='jobs' AND column_name IN "
                "('upload_bytes','storage_purged_at')"
            )
        )
    ).all()
    jd = {r[0]: (r[1], r[2]) for r in jc}
    assert set(jd) == EXPECTED_JOB
    assert jd["upload_bytes"] == ("NO", "0")
    assert jd["storage_purged_at"][0] == "YES"
