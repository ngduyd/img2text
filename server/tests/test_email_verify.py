"""Wave-5 S5 (Lane E): email verify, reset code, per-kind email limits,
gating. DB: img2text_test@5436 — migration docs/migrations/2026-10-15_email_verify.sql."""

from datetime import datetime

async def test_user_defaults_unverified_no_codes(db_session):
    from app.core.models import User

    u = User(email="fresh@x.io", password_hash="x")
    db_session.add(u)
    await db_session.commit()
    assert u.is_verified is False
    assert u.email_verify_code_hash is None
    assert u.email_verify_expires_at is None
    assert u.password_reset_code is None
    assert u.password_reset_expires_at is None

async def test_email_sends_audit_row(db_session):
    from app.core.models import EmailSend, User

    u = User(email="audit@x.io", password_hash="x")
    db_session.add(u)
    await db_session.commit()
    row = EmailSend(user_id=u.id, kind="welcome")
    db_session.add(row)
    await db_session.commit()
    assert row.id is not None
    assert row.kind == "welcome"
    assert isinstance(row.created_at, datetime)
