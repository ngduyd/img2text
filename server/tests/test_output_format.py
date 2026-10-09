"""Plan D4: output_format chosen at upload → auto-generated export after OCR.

Covers: upload default "md" / "docx" accepted / invalid → 422 exact VN,
GET /api/jobs/{id} returns the field, worker-protocol store schedules
exports/{id}/md (storage spy), LLM down on docx → warning + job stays
done, store_batch_result (Kaggle ingest path) schedules the same export.
"""

from datetime import datetime, timezone

import pytest

from app.core.models import Job
from app.services.job_results import drain_auto_output, store_batch_result
from app.core.schemas import ResultBody

from tests.test_upload import TEST_JPEG  # noqa: F401 (reuses fixtures via conftest)

def _put_keys(storage_spy) -> list[str]:
    return [c.args[0] for c in storage_spy.put.await_args_list]

@pytest.fixture
def md_llm_down(monkeypatch):
    """IR rewrite: build_md raises → auto-gen md takes the plain-md fallback path."""
    def _down(*args, **kwargs):
        from app.services.render_md import LLMError
        raise LLMError("LLM down (test)")
    monkeypatch.setattr("app.routers.exports.build_md", _down)

@pytest.fixture
def docx_llm_down(monkeypatch):
    """build_docx raises → auto-gen docx-layout skipped (warning)."""
    def _down(*args, **kwargs):
        from app.services.render_docx import LLMError
        raise LLMError("LLM down (test)")
    monkeypatch.setattr("app.routers.exports.build_docx", _down)

async def test_upload_defaults_to_md(auth_client, db_session):
    r = await auth_client.post(
        "/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/png")}
    )
    assert r.status_code == 201
    assert r.json()["output_format"] == "md"
    job = await db_session.get(Job, r.json()["id"])
    assert job.output_format == "md"

async def test_upload_docx_accepted(auth_client, db_session):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.jpg", TEST_JPEG, "image/png")},
        data={"output_format": "docx"},
    )
    assert r.status_code == 201
    assert r.json()["output_format"] == "docx"
    job = await db_session.get(Job, r.json()["id"])
    assert job.output_format == "docx"

async def test_upload_invalid_output_format_422(auth_client):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.jpg", TEST_JPEG, "image/png")},
        data={"output_format": "pdf"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "Đầu ra không hợp lệ."

async def test_get_job_returns_output_format(auth_client, db_session):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.jpg", TEST_JPEG, "image/png")},
        data={"output_format": "docx"},
    )
    jid = r.json()["id"]
    r = await auth_client.get(f"/api/jobs/{jid}")
    assert r.status_code == 200
    assert r.json()["output_format"] == "docx"
    # legacy row (NULL column) reads as "md"
    job = await db_session.get(Job, jid)
    job.output_format = None
    await db_session.commit()
    r = await auth_client.get(f"/api/jobs/{jid}")
    assert r.json()["output_format"] == "md"

async def test_worker_result_auto_generates_md(
    worker_client, seed_job, storage_spy, db_session, VALID_RESULT_JSONB, md_llm_down, docx_llm_down
):
    """POST /result (worker protocol) → exports/{id}/md written in background."""
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{seed_job}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    await drain_auto_output()
    key = f"exports/{seed_job}/md"
    assert key in _put_keys(storage_spy)
    data = await storage_spy.get(key)
    assert data.decode("utf-8") == VALID_RESULT_JSONB["markdown"]
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"

async def test_auto_docx_llm_down_warns_and_job_stays_done(
    auth_client,
    worker_client,
    storage_spy,
    db_session,
    VALID_RESULT_JSONB,
    monkeypatch,
    caplog,
):
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.jpg", TEST_JPEG, "image/png")},
        data={"output_format": "docx"},
    )
    jid = r.json()["id"]

    def _llm_down(*args, **kwargs):
        from app.services.render_docx import LLMError
        raise LLMError("LLM down")

    monkeypatch.setattr("app.routers.exports.build_docx", _llm_down)
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    with caplog.at_level("WARNING", logger="app.services.job_results"):
        r = await worker_client.post(
            f"/api/jobs/{jid}/result",
            json=VALID_RESULT_JSONB,
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        await drain_auto_output()
    assert any("docx-layout auto-gen failed" in rec.getMessage() for rec in caplog.records)
    assert f"exports/{jid}/docx" not in _put_keys(storage_spy)
    assert f"exports/{jid}/docx-layout" not in _put_keys(storage_spy)
    job = await db_session.get(Job, jid)
    assert job.status == "done"

async def test_auto_docx_success_stores_docx_layout_key(
    auth_client,
    worker_client,
    storage_spy,
    VALID_RESULT_JSONB,
    monkeypatch,
    md_llm_down,
):
    """IR rewrite: LLM bytes go to exports/{id}/docx-layout."""
    import json

    from tests.test_export_llm_docx import FakeResponse, fake_llm

    ir_response = json.dumps({
        "document_id": "doc_001",
        "schema_version": "1.0",
        "pages": [{
            "page_id": "page_001",
            "page_number": 1,
            "header": [],
            "content": [
                {
                    "id": "node_001",
                    "type": "heading",
                    "role": "section_heading",
                    "text": "Xin chào",
                    "align": "left",
                    "indent": 0,
                    "source_block_ids": ["r0"],
                    "children": [],
                }
            ],
            "footer": [],
        }],
    })
    fake_llm(monkeypatch, [FakeResponse(ir_response)])
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.jpg", TEST_JPEG, "image/png")},
        data={"output_format": "docx"},
    )
    jid = r.json()["id"]
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{jid}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    await drain_auto_output()
    keys = _put_keys(storage_spy)
    assert f"exports/{jid}/docx-layout" in keys
    assert f"exports/{jid}/docx" not in keys
    data = await storage_spy.get(f"exports/{jid}/docx-layout")
    assert data[:2] == b"PK"

async def test_auto_generates_both_formats(
    auth_client,
    worker_client,
    storage_spy,
    VALID_RESULT_JSONB,
    monkeypatch,
):
    """User request: auto-gen writes BOTH md-layout AND docx-layout regardless
    of output_format — viewing never waits for LLM."""
    import json

    from tests.test_export_llm_docx import FakeResponse, fake_llm

    async def _md_ok(*args, **kwargs):
        return "# layout md"

    ir_response = json.dumps({
        "document_id": "doc_001",
        "schema_version": "1.0",
        "pages": [{
            "page_id": "page_001",
            "page_number": 1,
            "header": [],
            "content": [
                {
                    "id": "node_001",
                    "type": "heading",
                    "role": "section_heading",
                    "text": "Xin chào",
                    "align": "left",
                    "indent": 0,
                    "source_block_ids": ["r0"],
                    "children": [],
                }
            ],
            "footer": [],
        }],
    })
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
    fake_llm(monkeypatch, [FakeResponse(ir_response)])
    r = await auth_client.post(
        "/api/jobs",
        files={"file": ("a.jpg", TEST_JPEG, "image/png")},
        data={"output_format": "md"},
    )
    jid = r.json()["id"]
    claim = await worker_client.get("/api/jobs/next")
    tok = claim.json()["worker_token"]
    r = await worker_client.post(
        f"/api/jobs/{jid}/result",
        json=VALID_RESULT_JSONB,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    await drain_auto_output()
    keys = _put_keys(storage_spy)
    assert f"exports/{jid}/md-layout" in keys
    assert f"exports/{jid}/docx-layout" in keys
    md_data = await storage_spy.get(f"exports/{jid}/md-layout")
    assert md_data.decode("utf-8") == "# layout md"
    docx_data = await storage_spy.get(f"exports/{jid}/docx-layout")
    assert docx_data[:2] == b"PK"

async def test_store_batch_result_schedules_md_export(
    db_session, seed_job, storage_spy, VALID_RESULT_JSONB, md_llm_down, docx_llm_down
):
    """Kaggle ingest path (store_batch_result) schedules the same export."""
    body = ResultBody.model_validate(VALID_RESULT_JSONB)
    stored = await store_batch_result(
        db_session,
        seed_job,
        body,
        now=datetime.now(timezone.utc),
        storage=storage_spy,
    )
    assert stored is True
    await drain_auto_output()
    assert f"exports/{seed_job}/md" in _put_keys(storage_spy)

async def test_store_without_storage_skips_scheduling(
    db_session, seed_job, VALID_RESULT_JSONB
):
    """storage=None (legacy callers/tests) → store succeeds, no task scheduled."""
    body = ResultBody.model_validate(VALID_RESULT_JSONB)
    assert (
        await store_batch_result(
            db_session, seed_job, body, now=datetime.now(timezone.utc)
        )
        is True
    )
    await drain_auto_output()
