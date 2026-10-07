"""Plan M1: unified-editor server contracts.

Covers: GET job `layout_cache` flags (+storage-error → false), GET
`layout_style` parse (broken JSON → null + warning), PUT export/md-layout/
content (upsert bytes, 422 exact "Nội dung quá dài.", done-only 409 exact,
other-user 403), PUT layout-style (typed enum validation 422 exact, null
clears, docx-layout cache invalidated), docx-layout export renders
style_overrides (python-docx read-back incl. table cells).
"""

import io
import json

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from app.core.models import Job
from app.services.llm_docx import build_layout_docx

from tests.test_export_llm_docx import (  # noqa: F401  (fixtures/helpers)
    FAKE_PLAN,
    FakeResponse,
    fake_llm,
)
from tests.test_jobs_read import other_client  # noqa: F401

FULL_STYLE = {
    "fontFamily": "Arial",
    "fontSize": 18,
    "align": "center",
    "indent": 1,
    "spacing": 1.5,
    "underline": True,
}

async def _set_style(db_session: Job, job_id: int, raw: str | None) -> None:
    job = await db_session.get(Job, job_id)
    job.layout_style = raw
    await db_session.commit()

# --- GET /api/jobs/{id}: layout_cache ---

async def test_layout_cache_all_false(auth_client, done_job_with_result):
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.status_code == 200
    assert r.json()["layout_cache"] == {"md": False, "docx": False}

async def test_layout_cache_flags_after_seed(
    auth_client, done_job_with_result, storage
):
    await storage.put(f"exports/{done_job_with_result}/md-layout", b"# moi")
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.json()["layout_cache"] == {"md": True, "docx": False}
    await storage.put(f"exports/{done_job_with_result}/docx-layout", b"PK")
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.json()["layout_cache"] == {"md": True, "docx": True}

async def test_layout_cache_storage_error_false(
    auth_client, done_job_with_result, storage, monkeypatch, caplog
):
    """storage.exists lỗi → flags false + warning, GET vẫn 200."""
    caplog.set_level("WARNING", logger="app.routers.jobs")

    async def boom(key: str) -> bool:
        raise RuntimeError("s3 down")

    monkeypatch.setattr(storage, "exists", boom)
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.status_code == 200
    assert r.json()["layout_cache"] == {"md": False, "docx": False}
    assert any(
        rec.levelname == "WARNING" and "layout_cache" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]

# --- GET /api/jobs/{id}: layout_style ---

async def test_layout_style_parsed(
    auth_client, done_job_with_result, db_session
):
    await _set_style(db_session, done_job_with_result, json.dumps(FULL_STYLE))
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.status_code == 200
    assert r.json()["layout_style"] == FULL_STYLE

async def test_layout_style_broken_json_null(
    auth_client, done_job_with_result, db_session, caplog
):
    caplog.set_level("WARNING", logger="app.routers.jobs")
    await _set_style(db_session, done_job_with_result, "{oops")
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.status_code == 200
    assert r.json()["layout_style"] is None
    assert any("layout_style" in rec.getMessage() for rec in caplog.records)

async def test_layout_style_absent_null(auth_client, done_job_with_result):
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.json()["layout_style"] is None

# --- PUT /api/jobs/{id}/export/md-layout/content ---

async def test_put_md_layout_content_204_upsert_bytes(
    auth_client, done_job_with_result, storage
):
    key = f"exports/{done_job_with_result}/md-layout"
    await storage.put(key, b"# cu")  # driver put dedupe → route phải xóa trước
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/export/md-layout/content",
        json={"markdown": "# moi"},
    )
    assert r.status_code == 204, r.text
    assert await storage.get(key) == "# moi".encode()

async def test_put_md_layout_content_non_string_422(auth_client, done_job_with_result):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/export/md-layout/content",
        json={"markdown": 123},
    )
    assert r.status_code == 422

async def test_put_md_layout_content_empty_422(auth_client, done_job_with_result):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/export/md-layout/content",
        json={"markdown": "   "},
    )
    assert r.status_code == 422

async def test_put_md_layout_content_too_long_422(auth_client, done_job_with_result):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/export/md-layout/content",
        json={"markdown": "x" * 500_001},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Nội dung quá dài."

async def test_put_md_layout_content_queued_409(auth_client, seed_job):
    r = await auth_client.put(
        f"/api/jobs/{seed_job}/export/md-layout/content",
        json={"markdown": "# moi"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Chưa có kết quả OCR."

async def test_put_md_layout_content_other_user_403(
    auth_client, other_client, done_job_with_result
):
    r = await other_client.put(
        f"/api/jobs/{done_job_with_result}/export/md-layout/content",
        json={"markdown": "# moi"},
    )
    assert r.status_code == 403

# --- PUT /api/jobs/{id}/layout-style ---

async def test_put_layout_style_valid_roundtrip(
    auth_client, done_job_with_result, db_session
):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style",
        json={"style": FULL_STYLE},
    )
    assert r.status_code == 204, r.text
    job = await db_session.get(Job, done_job_with_result)
    assert json.loads(job.layout_style) == FULL_STYLE
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.json()["layout_style"] == FULL_STYLE

async def test_put_layout_style_partial_ok(
    auth_client, done_job_with_result
):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style",
        json={"style": {"fontSize": 20}},
    )
    assert r.status_code == 204
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.json()["layout_style"] == {"fontSize": 20}

@pytest.mark.parametrize(
    "good",
    [
        {"fontSize": "14"},        # web <select> gửi string → coerce int
        {"spacing": "1.5"},        # web gửi string → coerce float
        {"fontSize": 14, "spacing": 1.5},  # số nguyên thủy vẫn ok
    ],
)
async def test_put_layout_style_string_values_coerced(
    auth_client, done_job_with_result, db_session, good
):
    """BUGFIX 2: client web gửi fontSize/spacing dạng string → 204, lưu số."""
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style", json={"style": good}
    )
    assert r.status_code == 204, r.text
    job = await db_session.get(Job, done_job_with_result)
    stored = json.loads(job.layout_style)
    assert stored == {k: int(v) if k == "fontSize" else float(v)
                      for k, v in good.items()}
    assert all(type(stored[k]) is (int if k == "fontSize" else float)
               for k in good)

@pytest.mark.parametrize(
    "bad",
    [
        {"color": "red"},          # key ngoài enum
        {"fontSize": 100},         # int ngoài 8-72
        {"fontSize": "73"},        # string ngoài 8-72
        {"fontSize": "abc"},       # string không parse được
        {"fontSize": True},        # bool ≠ int
        {"align": "middle"},       # giá trị ngoài enum
        {"indent": 3},             # ngoài [0,1,2]
        {"spacing": 1.1},          # ngoài [1,1.25,1.5,2]
        {"spacing": 13},           # số ngoài enum
        {"spacing": "abc"},        # string không parse được
        {"underline": "yes"},      # không phải bool
        {"fontFamily": "x" * 41},  # > 40 ký tự
    ],
)
async def test_put_layout_style_invalid_422(
    auth_client, done_job_with_result, bad
):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style", json={"style": bad}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Kiểu định dạng không hợp lệ."

async def test_put_layout_style_null_clears(
    auth_client, done_job_with_result, db_session
):
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style",
        json={"style": FULL_STYLE},
    )
    assert r.status_code == 204
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style", json={"style": None}
    )
    assert r.status_code == 204
    job = await db_session.get(Job, done_job_with_result)
    assert job.layout_style is None
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}")
    assert r.json()["layout_style"] is None

async def test_put_layout_style_other_user_403(
    auth_client, other_client, done_job_with_result
):
    r = await other_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style",
        json={"style": FULL_STYLE},
    )
    assert r.status_code == 403

async def test_put_layout_style_invalidates_docx_layout_cache(
    auth_client, done_job_with_result, storage
):
    """Gates M3: style đổi → docx-layout cache cũ phải mất hiệu lực."""
    key = f"exports/{done_job_with_result}/docx-layout"
    await storage.put(key, b"PK-old")
    r = await auth_client.put(
        f"/api/jobs/{done_job_with_result}/layout-style",
        json={"style": FULL_STYLE},
    )
    assert r.status_code == 204
    assert not await storage.exists(key)

# --- docx-layout export với style_overrides ---

async def test_export_docx_layout_applies_style_overrides(
    auth_client, done_job_with_result, storage, db_session, monkeypatch
):
    await _set_style(db_session, done_job_with_result, json.dumps(FULL_STYLE))
    plan = {"columns": "single", "blocks": [{"id": "r0", "col": "full", "style": "h1"}]}
    fake_llm(monkeypatch, [FakeResponse(json.dumps(plan))])
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/export", json={"fmt": "docx-layout"}
    )
    assert r.status_code == 200, r.text
    data = await storage.get(f"exports/{done_job_with_result}/docx-layout")
    doc = Document(io.BytesIO(data))
    para = next(p for p in doc.paragraphs if p.text == "Xin chào")
    run = para.runs[0]
    assert run.font.name == "Arial"
    assert run.font.size == Pt(18)
    assert run.underline is True
    assert para.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert para.paragraph_format.line_spacing == 1.5
    assert para.paragraph_format.left_indent == Inches(0.5)

async def test_build_layout_docx_overrides_reach_table_cells(
    monkeypatch, VALID_RESULT_JSONB
):
    """Two-column plan: override áp cả paragraph trong cell (đọc lại)."""
    fake_llm(monkeypatch, [FakeResponse(json.dumps(FAKE_PLAN))])
    data = await build_layout_docx(
        VALID_RESULT_JSONB,
        [(800, 600)],
        style_overrides={"fontFamily": "Courier New", "align": "justify"},
    )
    doc = Document(io.BytesIO(data))
    table = doc.tables[0]
    merged = table.rows[0].cells[0]
    assert merged.paragraphs[0].runs[0].font.name == "Courier New"
    assert merged.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    left = table.rows[1].cells[0]
    assert left.paragraphs[0].runs[0].font.name == "Courier New"
    assert left.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
