"""Plan H Task 2: PATCH /api/jobs/{id}/regions/{rid} — per-region edit."""

import copy
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, User

# r0 text appears TWICE in markdown → replace-once asserted below
_MD_WITH_TEXT = "# tài liệu\n\nXin chào thế giới\n\n## Phần 2\n\nXin chào thế giới"
_MD_ABSENT = "# tài liệu\n\n## Phần 2"

def _result(markdown: str) -> dict:
    return {
        "model_version": "test-model",
        "gpu_seconds": 1.0,
        "warnings": [],
        "markdown": markdown,
        "pages": [
            {
                "index": 0,
                "width": 800,
                "height": 600,
                "page_flag": "ok",
                "markdown": markdown,
                "regions": [
                    {
                        "id": "r0",
                        "bbox": [1, 2, 30, 40],
                        "text": "Xin chào thế giới",
                        "verdict": "ok",
                        "placeholder": False,
                    },
                    {
                        "id": "r1",
                        "bbox": [5, 6, 70, 80],
                        "text": "Noi dung khac",
                        "verdict": "ok",
                        "placeholder": False,
                    },
                ],
            }
        ],
    }

async def _seed_done(db_session: AsyncSession, result: dict) -> int:
    """Done job owned by first user (auth_client registers first)."""
    user = (
        await db_session.execute(select(User).order_by(User.id))
    ).scalars().first()
    job = Job(
        user_id=user.id,
        status="done",
        result=copy.deepcopy(result),
        storage_key="uploads/test.jpg",
        file_type="image",
        page_count=1,
    )
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job.id

@pytest_asyncio.fixture
async def other_client(app, db_session):
    """Second registered+logged-in user; own httpx client (own cookies)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        email = f"other-{uuid4().hex}@test.io"
        r = await c.post(
            "/api/auth/register", json={"email": email, "password": "secret123"}
        )
        assert r.status_code == 201, r.text
        r = await c.post(
            "/api/auth/login", json={"email": email, "password": "secret123"}
        )
        assert r.status_code == 200, r.text
        yield c

async def test_region_edit_happy_path(auth_client, db_session):
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": "r0", "text": "Tạm biệt", "markdown_replaced": True
    }
    detail = (await auth_client.get(f"/api/jobs/{job_id}")).json()["result"]
    # edited_markdown: old replaced ONCE (2nd occurrence untouched)
    assert detail["edited_markdown"] == (
        "# tài liệu\n\nTạm biệt\n\n## Phần 2\n\nXin chào thế giới"
    )
    assert detail["markdown"] == _MD_WITH_TEXT  # original markdown intact
    regions = detail["pages"][0]["regions"]
    assert regions[0]["text"] == "Tạm biệt"
    assert regions[1]["text"] == "Noi dung khac"  # other region untouched

async def test_region_edit_old_text_absent(auth_client, db_session):
    job_id = await _seed_done(db_session, _result(_MD_ABSENT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": "r0", "text": "Tạm biệt", "markdown_replaced": False
    }
    detail = (await auth_client.get(f"/api/jobs/{job_id}")).json()["result"]
    assert "edited_markdown" not in detail  # no replace → key not created
    assert detail["pages"][0]["regions"][0]["text"] == "Tạm biệt"

async def test_region_edit_unknown_region_404(auth_client, db_session):
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/nope", json={"text": "x"}
    )
    assert r.status_code == 404, r.text

async def test_region_edit_other_user_403(auth_client, db_session, other_client):
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await other_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "x"}
    )
    assert r.status_code == 403, r.text

async def test_region_edit_invalidates_export_cache(auth_client, db_session, storage_spy):
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.post(f"/api/jobs/{job_id}/export", json={"fmt": "md"})
    assert r.status_code == 200, r.text
    await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    storage_spy.delete_prefix.assert_any_call(f"exports/{job_id}/")

async def test_region_edit_queued_job_409(auth_client, seed_job):
    r = await auth_client.patch(
        f"/api/jobs/{seed_job}/regions/r0", json={"text": "x"}
    )
    assert r.status_code == 409, r.text

async def test_region_edit_empty_text_422(auth_client, db_session):
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": ""}
    )
    assert r.status_code == 422, r.text
