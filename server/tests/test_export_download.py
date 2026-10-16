"""Task 5 (Plan W): GET /api/jobs/{id}/export/{fmt}/download.

Owner-or-admin via jobs._job_or_403; done-only; fmt Literal (422 on other);
storage miss → 404 "Chưa xuất file."; success → raw bytes + exact Content-Type.
"""

from tests.test_jobs_read import other_client  # noqa: F401

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

async def test_download_docx_returns_bytes_and_content_type(
    auth_client, done_job_with_result, storage
):
    await storage.put(f"exports/{done_job_with_result}/docx", b"PK\x03\x04test")
    r = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/docx/download"
    )
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04test"
    assert r.headers["content-type"] == DOCX_CONTENT_TYPE

async def test_download_md_content_type(auth_client, done_job_with_result, storage):
    await storage.put(f"exports/{done_job_with_result}/md", b"# tai lieu")
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}/export/md/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"

async def test_download_absent_export_404(auth_client, done_job_with_result):
    r = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/docx/download"
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Chưa xuất file."

async def test_download_other_user_403(auth_client, other_client, done_job_with_result):
    # auth_client FIRST: done_job_with_result seeds to the first-registered user.
    r = await other_client.get(
        f"/api/jobs/{done_job_with_result}/export/docx/download"
    )
    assert r.status_code == 403

async def test_download_queued_job_409(auth_client, seed_job):
    r = await auth_client.get(f"/api/jobs/{seed_job}/export/md/download")
    assert r.status_code == 409

async def test_download_invalid_fmt_422(auth_client, done_job_with_result):
    r = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/xls/download"
    )
    assert r.status_code == 422

# --- #10 (spec 2026-10-15): Range header ---

async def test_download_export_range_header_returns_206(
    auth_client, done_job_with_result, storage
):
    await storage.put(f"exports/{done_job_with_result}/pdf", b"a" * 1000)
    resp = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/pdf/download",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 0-99/1000"
    assert len(resp.content) == 100

async def test_download_export_invalid_range_returns_416(
    auth_client, done_job_with_result, storage
):
    await storage.put(f"exports/{done_job_with_result}/pdf", b"a" * 1000)
    resp = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/pdf/download",
        headers={"Range": "bytes=2000-3000"},
    )
    assert resp.status_code == 416
    assert resp.headers["Content-Range"] == "bytes */1000"
    assert resp.json() == {"code": "invalid_range"}

async def test_download_export_unsupported_range_forms_416(
    auth_client, done_job_with_result, storage
):
    """Single bytes=start-end ONLY: suffix / multi / malformed → 416."""
    await storage.put(f"exports/{done_job_with_result}/pdf", b"a" * 1000)
    for bad in ("bytes=-500", "bytes=0-1,5-6", "bytes=abc", "bytes=0-"):
        resp = await auth_client.get(
            f"/api/jobs/{done_job_with_result}/export/pdf/download",
            headers={"Range": bad},
        )
        assert resp.status_code == 416, (bad, resp.status_code)

async def test_download_export_without_range_stays_200(
    auth_client, done_job_with_result, storage
):
    await storage.put(f"exports/{done_job_with_result}/pdf", b"a" * 1000)
    resp = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/pdf/download"
    )
    assert resp.status_code == 200
    assert len(resp.content) == 1000

# --- QA-1: get_range KeyError (purge race) → 404, không 500 ---

async def test_download_export_range_deleted_midway_404(
    auth_client, done_job_with_result, storage, monkeypatch
):
    await storage.put(f"exports/{done_job_with_result}/pdf", b"a" * 1000)

    async def gone(key, start, end):
        raise KeyError(key)

    # object còn lúc size() (test put), mất lúc get_range — như purge race
    monkeypatch.setattr(storage, "get_range", gone)
    resp = await auth_client.get(
        f"/api/jobs/{done_job_with_result}/export/pdf/download",
        headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 404
