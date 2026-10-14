"""Lane B2 (wave-5 S6): POST /api/feedback + GET /api/admin/feedbacks."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.models import Feedback, User


async def test_post_feedback_requires_auth(client):
    r = await client.post("/api/feedback", json={"content": "hi"})
    assert r.status_code == 401


async def test_post_feedback_saves_row(auth_client, db_session):
    r = await auth_client.post(
        "/api/feedback", json={"content": "trang này hay", "page_path": "/jobs"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content"] == "trang này hay"
    assert body["page_path"] == "/jobs"
    user = (await db_session.execute(select(User).order_by(User.id))).scalars().first()
    row = await db_session.get(Feedback, body["id"])
    assert row is not None
    assert row.user_id == user.id


async def test_post_feedback_page_path_optional(auth_client):
    r = await auth_client.post("/api/feedback", json={"content": "ok"})
    assert r.status_code == 201, r.text
    assert r.json()["page_path"] is None


async def test_post_feedback_content_over_2000_422(auth_client):
    r = await auth_client.post("/api/feedback", json={"content": "x" * 2001})
    assert r.status_code == 422


async def test_post_feedback_content_empty_422(auth_client):
    r = await auth_client.post("/api/feedback", json={"content": ""})
    assert r.status_code == 422


async def test_admin_feedbacks_non_admin_403(auth_client):
    r = await auth_client.get("/api/admin/feedbacks")
    assert r.status_code == 403


async def test_admin_feedbacks_newest_first_with_email(admin_client, db_session):
    user = (await db_session.execute(select(User).order_by(User.id))).scalars().first()
    for i, content in enumerate(["cũ", "mới"]):
        fb = Feedback(user_id=user.id, content=content, page_path="/")
        fb.created_at = datetime.now(timezone.utc).replace(microsecond=i)
        db_session.add(fb)
    await db_session.commit()
    r = await admin_client.get("/api/admin/feedbacks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert [x["content"] for x in body["items"]] == ["mới", "cũ"]
    assert body["items"][0]["email"] == user.email


async def test_admin_feedbacks_pagination(admin_client, db_session):
    user = (await db_session.execute(select(User).order_by(User.id))).scalars().first()
    for i in range(3):
        fb = Feedback(user_id=user.id, content=f"fb{i}")
        fb.created_at = datetime.now(timezone.utc).replace(microsecond=i)
        db_session.add(fb)
    await db_session.commit()
    r = await admin_client.get("/api/admin/feedbacks?page=2&page_size=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["items"][0]["content"] == "fb0"


async def test_admin_feedbacks_anonymous_401(client):
    r = await client.get("/api/admin/feedbacks")
    assert r.status_code == 401
