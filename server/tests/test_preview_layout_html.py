"""GET /api/jobs/{id}/preview/layout.html — preview HTML dựng từ layout_spec.

Trước file này route không có test nào (`rg -n preview server/tests/` → 0 hit).
3 test (tối đa theo yêu cầu):
1. happy path: done job, result 1 cột → 200, text/html, body chứa text trang.
2. auth/ownership: job của user khác → 403 (mẫu test_jobs_read.py:120);
   id không tồn tại → 404.
3. job chưa done (queued) → 409 'job not done' (exports.py:746 — đọc code,
   không đoán).

Seeding: `_seed_done` (tests/test_region_edit.py) — cùng helper
test_export_md_layout.py dùng để tạo done job với result tuỳ ý.
"""

from sqlalchemy import select

from tests.test_jobs_read import other_client  # noqa: F401
from tests.test_region_edit import _seed_done

# 1 trang 1 cột, chỉ vùng TEXT: preview không đi qua crop/presign nên test
# không phụ thuộc storage (vùng ảnh sẽ gọi get_or_make_crop).
TEXT_RESULT = {
    "model_version": "paddleocr-vl-1.5-0.9B",
    "gpu_seconds": 0.0,
    "warnings": [],
    "markdown": "",
    "pages": [
        {
            "index": 0,
            "width": 800,
            "height": 600,
            "page_flag": "ok",
            "markdown": "",
            "regions": [
                {
                    "id": "r0",
                    "bbox": [40, 40, 700, 80],
                    "text": "Xin chào thế giới",
                    "verdict": "ok",
                    "placeholder": False,
                },
            ],
        }
    ],
}


async def test_preview_layout_html_happy(auth_client, db_session):
    """Done job 1 cột → 200 + text/html + text của trang trong body."""
    job_id = await _seed_done(db_session, TEXT_RESULT)
    r = await auth_client.get(f"/api/jobs/{job_id}/preview/layout.html")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    text = r.text
    assert "Xin chào thế giới" in text
    assert 'class="pg"' in text        # render_html_spec bọc từng trang
    assert "font-family" in text       # CSS inline của renderer có mặt


async def test_preview_layout_html_auth_ownership(
    auth_client, other_client, db_session
):
    """Job user khác → 403; id không tồn tại → 404 (_job_or_403 chạy TRƯỚC
    mọi xử lý crop, nên không cần storage)."""
    job_id = await _seed_done(db_session, TEXT_RESULT)
    r = await other_client.get(f"/api/jobs/{job_id}/preview/layout.html")
    assert r.status_code == 403
    r = await auth_client.get("/api/jobs/999999/preview/layout.html")
    assert r.status_code == 404


async def test_preview_layout_html_not_done_409(auth_client, seed_job):
    """seed_job tạo job status='queued' → 409 (preview chỉ dựng cho job done)."""
    r = await auth_client.get(f"/api/jobs/{seed_job}/preview/layout.html")
    assert r.status_code == 409
    assert r.json()["detail"] == "job not done"
