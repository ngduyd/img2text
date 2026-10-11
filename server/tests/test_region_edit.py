"""Plan H Task 2: PATCH /api/jobs/{id}/regions/{rid} — per-region edit."""

import copy
import json
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Job, User

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
    # P2-3: response mang text_version MỚI (bump) — client/API thô biết tv
    assert r.json() == {
        "id": "r0", "text": "Tạm biệt", "markdown_replaced": True,
        "text_version": 1,
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
        "id": "r0", "text": "Tạm biệt", "markdown_replaced": False,
        "text_version": 1,
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

async def test_region_edit_bumps_text_version(auth_client, db_session):
    """P1-2: region edit → bump jobs.text_version (stale badge) + snapshot
    kind "md" = job.result (content region edit sửa thật sự)."""
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    assert r.status_code == 200, r.text
    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.text_version == 1
    items = (await auth_client.get(
        f"/api/jobs/{job_id}/versions", params={"kind": "md"}
    )).json()["items"]
    assert items and items[0]["based_on_text_version"] == 1

async def test_region_edit_v1_keeps_pre_edit_text(auth_client, db_session, storage):
    """P1-R1: seed v1 TRƯỚC mutate → version 1 = result TRƯỚC edit,
    version 2 = result sau edit (bản gốc không biến mất khỏi history)."""
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    assert r.status_code == 200, r.text
    v1 = json.loads(await storage.get(f"versions/{job_id}/md/1"))
    assert v1["pages"][0]["regions"][0]["text"] == "Xin chào thế giới"
    assert "Tạm biệt" not in json.dumps(v1, ensure_ascii=False)
    v2 = json.loads(await storage.get(f"versions/{job_id}/md/2"))
    assert v2["pages"][0]["regions"][0]["text"] == "Tạm biệt"  # snapshot sau edit

async def test_region_edit_snapshot_md_not_extraction_text(
    auth_client, db_session, storage
):
    """P1-1 round 2: fixture CÓ extraction_text (lỗ che round 1) →
    region edit KHÔNG seed kind-text; version mới kind "md" = job.result
    TRƯỚC edit, KHÔNG phải extraction_text."""
    result = _result(_MD_WITH_TEXT)
    result["extraction_text"] = "EXTRACTION GOC KHONG DOI"
    job_id = await _seed_done(db_session, result)
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    assert r.status_code == 200, r.text
    # kind-text history không tăng v (text gốc vẫn là extraction_text)
    text_items = (await auth_client.get(
        f"/api/jobs/{job_id}/versions", params={"kind": "text"}
    )).json()["items"]
    assert text_items == []
    md_items = (await auth_client.get(
        f"/api/jobs/{job_id}/versions", params={"kind": "md"}
    )).json()["items"]
    assert [m["version"] for m in md_items] == [2, 1]  # newest first
    raw_v1 = await storage.get(f"versions/{job_id}/md/1")
    # RED: bytes từng là extraction_text thô (== bản copy y hệt v1/v2)
    assert raw_v1 != "EXTRACTION GOC KHONG DOI".encode("utf-8")
    v1 = json.loads(raw_v1)  # bytes = job.result JSON, không phải text gốc
    assert v1["pages"][0]["regions"][0]["text"] == "Xin chào thế giới"
    v2 = json.loads(await storage.get(f"versions/{job_id}/md/2"))
    assert v2["pages"][0]["regions"][0]["text"] == "Tạm biệt"

async def test_region_edit_restore_md_roundtrip(auth_client, db_session, storage):
    """P1-1 r2: snapshot/restore nhất quán — restore kind "md" trả
    job.result về bản chụp TRƯỚC edit + append version mới."""
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))
    r = await auth_client.patch(
        f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
    )
    assert r.status_code == 200, r.text
    v1 = next(
        v for v in (await auth_client.get(
            f"/api/jobs/{job_id}/versions", params={"kind": "md"}
        )).json()["items"]
        if v["version"] == 1
    )
    r = await auth_client.post(f"/api/jobs/{job_id}/versions/{v1['id']}/restore")
    assert r.status_code == 204, r.text
    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.result["pages"][0]["regions"][0]["text"] == "Xin chào thế giới"
    assert job.text_version == 2
    md_items = (await auth_client.get(
        f"/api/jobs/{job_id}/versions", params={"kind": "md"}
    )).json()["items"]
    assert [m["version"] for m in md_items] == [3, 2, 1]  # restore append-only

async def test_region_edit_save_version_fail_keeps_db(
    auth_client, db_session, monkeypatch
):
    """P1-2: save_version nổ → MỘT commit chưa tới: job.result + 
    text_version đều giữ nguyên trong DB."""
    job_id = await _seed_done(db_session, _result(_MD_WITH_TEXT))

    async def _boom(*args, **kwargs):
        raise RuntimeError("save_version exploded")

    monkeypatch.setattr("app.routers.jobs.save_version", _boom)
    try:
        await auth_client.patch(
            f"/api/jobs/{job_id}/regions/r0", json={"text": "Tạm biệt"}
        )
    except Exception:
        pass  # 500 hoặc exception lội lên — cả hai đều OK
    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.text_version == 0
    # RED: seed_current đã commit job.result mutated trước khi save_version nổ
    assert job.result["pages"][0]["regions"][0]["text"] == "Xin chào thế giới"
