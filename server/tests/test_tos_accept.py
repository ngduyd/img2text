"""Spec 2026-11-04 (A3/A4): ToS bắt buộc ở register + ghi nhận đã đồng ý."""

from sqlalchemy import select

from app.core.config import settings
from app.core.models import User

async def test_register_without_accept_tos_422(client, db_session):
    r = await client.post(
        "/api/auth/register", json={"email": "tos1@x.io", "password": "secret123"}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "tos_required"
    # không tạo user (không có side effect trước khi validate)
    assert await db_session.scalar(select(User).where(User.email == "tos1@x.io")) is None

async def test_register_accept_tos_false_422(client):
    r = await client.post(
        "/api/auth/register",
        json={"email": "tos2@x.io", "password": "secret123", "accept_tos": False},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "tos_required"

async def test_register_accept_tos_true_writes_columns(client, db_session):
    r = await client.post(
        "/api/auth/register",
        json={"email": "tos3@x.io", "password": "secret123", "accept_tos": True},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"status": "ok"}
    user = (
        await db_session.execute(select(User).where(User.email == "tos3@x.io"))
    ).scalar_one()
    assert user.tos_accepted_at is not None
    assert user.tos_version == settings.tos_version

async def test_register_422_precedes_email_lookup(client, db_session):
    """Anti-oracle: email đã tồn tại vẫn 422 (không 201) khi thiếu accept_tos —
    thứ tự check giống hệt email mới, không lộ email tồn tại."""
    first = await client.post(
        "/api/auth/register",
        json={"email": "tos4@x.io", "password": "secret123", "accept_tos": True},
    )
    assert first.status_code == 201
    again = await client.post(
        "/api/auth/register", json={"email": "tos4@x.io", "password": "secret123"}
    )
    assert again.status_code == 422
