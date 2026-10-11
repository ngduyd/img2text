"""Plan: LLM Proofread — detect & suggest OCR errors (auto after OCR).

No live LLM: proofread's module-local AsyncClient is patched to canned
responses (the conftest autouse stub fails fast by default; these tests
override the same seam). Covers: parse → fuzzy locate (exact / whitespace
/ diacritic fold) → store rows, unknown phrase → skip, replace-all on
re-run, LLM down/garbage → warning + 0 + job stays done, hook schedule
after store, API GET/accept/reject/proofread + 403/404.
"""

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, OcrSuggestion
from app.core.schemas import ResultBody
from app.services import proofread
from app.services.job_results import drain_auto_output, store_batch_result
from app.services.proofread import run_proofread

from tests.test_export_llm_docx import FakeResponse  # canned LLM responses
from tests.test_jobs_read import other_client  # noqa: F401
from tests.test_output_format import md_llm_down  # noqa: F401

def fake_llm(monkeypatch, responses: list) -> list:
    """Patch proofread's module-local AsyncClient; returns recorded calls.

    `responses` items: FakeResponse → returned, Exception → raised.
    """
    calls: list = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, dict(json or {}), dict(headers or {})))  # copy
            resp = responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp

    monkeypatch.setattr(proofread, "AsyncClient", Client)
    return calls

def _llm_response(items: list[dict]) -> FakeResponse:
    return FakeResponse(json.dumps({"items": items}))

async def _job(db_session, job_id: int) -> Job:
    job = await db_session.get(Job, job_id)
    assert job is not None
    return job

# --- run_proofread: parse → locate → store ---

async def test_run_proofread_stores_suggestions(
    monkeypatch, db_session, done_job_with_result, caplog
):
    caplog.set_level("INFO", logger="app.services.proofread")
    calls = fake_llm(
        monkeypatch,
        [_llm_response([{"phrase": "chào", "suggestion": "chao", "reason": "thiếu dấu"}])],
    )
    job = await _job(db_session, done_job_with_result)
    n = await run_proofread(db_session, job)
    assert n == 1
    # LLM call contract: model from settings, temperature 0, json_object, prompt
    url, payload, _ = calls[0]
    assert url.endswith("/chat/completions")
    assert payload["model"] == settings.proofread_llm_model
    assert payload["temperature"] == 0
    assert payload["response_format"] == {"type": "json_object"}
    prompt = payload["messages"][0]["content"]
    assert "Đề thi (ngữ cảnh)" in prompt
    assert "Xin chào" in prompt  # page text in input
    assert "phrase" in prompt and "suggestion" in prompt  # JSON schema hint
    # stored row: offsets point at the phrase INSIDE the page text
    rows = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == job.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    page_text = "\n".join(
        r.get("text") or "" for r in job.result["pages"][0]["regions"]
    )
    assert (row.page_index, row.status) == (0, "pending")
    assert row.original == "chào"
    assert row.suggestion == "chao"
    assert row.reason == "thiếu dấu"
    assert page_text[row.start : row.end] == "chào"
    # observability: plan-mandated summary line (never logs content)
    info = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert any(m.startswith("proofread: job=") for m in info), info
    assert not any("thiếu dấu" in m for m in info)

async def test_prompt_marks_non_ok_regions_with_verdict(
    monkeypatch, db_session, done_job_with_result
):
    """VLM signal: non-ok region prefixed [verdict=...] trong prompt; ok region
    giữ nguyên (prompt lấy đúng text trang gửi LLM)."""
    job = await _job(db_session, done_job_with_result)
    regions = job.result["pages"][0]["regions"]
    regions[1]["text"] = "hinh anh meo"  # verdict=image_unextractable, có text
    calls = fake_llm(monkeypatch, [_llm_response([])])
    assert await run_proofread(db_session, job) == 0
    prompt = calls[0][1]["messages"][0]["content"]
    assert "[verdict=image_unextractable] hinh anh meo" in prompt
    assert "[verdict=ok]" not in prompt
    # hint = text REGION ĐẦU (context tài liệu: trường/đề thi), không phải "3 dòng đầu"
    assert "Đề thi (ngữ cảnh): Xin chào" in prompt

def test_page_text_region_missing_verdict_key_not_prefixed():
    """P2: region thiếu key verdict → default ok → text không bị prefix [verdict=...]."""
    assert proofread._page_text({"regions": [{"text": "xin chao"}]}) == "xin chao"
    assert (
        proofread._page_text(
            {"regions": [{"text": "anh meo", "verdict": "image_unextractable"}]}
        )
        == "[verdict=image_unextractable] anh meo"
    )

def test_prompt_new_instructions_and_no_conservative_line():
    """Prompt mới: task VLM OCR + verdict legend + liệt kê mọi từ khả nghi;"
    "dòng bảo thủ 'Chỉ nghi ngờ thực sự' bị gỡ."""
    p = proofread.PROMPT.format(hint="H", text="T")
    assert "Đây là ảnh chụp đề thi tiếng Việt đã OCR" in p
    assert "bổ mẹ" in p
    assert "[verdict=...]" in p
    assert "Liệt kê mọi từ khả nghi" in p
    assert "Chỉ nghi ngờ thực sự" not in p
    assert "3 dòng đầu" not in p
    assert '{"items":[{"phrase"' in p.replace("{{", "{").replace("}}", "}")

async def test_timeout_retries_once_then_succeeds(
    monkeypatch, db_session, done_job_with_result, caplog
):
    """ReadTimeout lần 1 → retry 1 lần → response OK → suggestions lưu."""
    fake_llm(
        monkeypatch,
        [
            httpx.ReadTimeout("timed out"),
            _llm_response([{"phrase": "chào", "suggestion": "chao", "reason": "dấu"}]),
        ],
    )
    job = await _job(db_session, done_job_with_result)
    with caplog.at_level("WARNING", logger="app.services.proofread"):
        assert await run_proofread(db_session, job) == 1
    warns = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("timeout" in m for m in warns), warns

async def test_both_timeouts_raise_proofread_error_with_diagnostics(
    monkeypatch, db_session, done_job_with_result, caplog
):
    """Timeout ×2 → ProofreadError (str(ReadTimeout) rỗng → message phải tự
    chứa 'timeout' + số lần + elapsed) → warning + 0, job giữ done."""
    fake_llm(
        monkeypatch,
        [httpx.ReadTimeout(""), httpx.ReadTimeout("")],
    )
    job = await _job(db_session, done_job_with_result)
    with caplog.at_level("WARNING", logger="app.services.proofread"):
        assert await run_proofread(db_session, job) == 0
    warns = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("LLM timeout sau 2 lần" in m for m in warns), warns
    assert any(re.search(r"\(\d+s\)", m) for m in warns), warns
    assert job.status == "done"

async def test_run_proofread_skips_unknown_phrase(monkeypatch, db_session, done_job_with_result):
    fake_llm(
        monkeypatch,
        [_llm_response([{"phrase": "cụm không tồn tại", "suggestion": "x", "reason": "r"}])],
    )
    job = await _job(db_session, done_job_with_result)
    assert await run_proofread(db_session, job) == 0
    rows = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == job.id)
        )
    ).scalars().all()
    assert rows == []

async def test_run_proofread_fuzzy_whitespace_and_diacritics(
    monkeypatch, db_session, done_job_with_result
):
    """Whitespace runs + missing diacritics still locate (offsets map back)."""
    fake_llm(
        monkeypatch,
        [
            _llm_response(
                [
                    # double space vs single space in page text
                    {"phrase": "Xin  chao", "suggestion": "Xin chào", "reason": "sai"},
                ]
            ),
        ],
    )
    job = await _job(db_session, done_job_with_result)
    assert await run_proofread(db_session, job) == 1
    row = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == job.id)
        )
    ).scalars().one()
    page_text = "\n".join(r.get("text") or "" for r in job.result["pages"][0]["regions"])
    assert page_text[row.start : row.end] == "Xin chào"

async def test_run_proofread_rerun_keeps_accepted_rows(
    monkeypatch, db_session, done_job_with_result
):
    """P2-7: rerun giữ status accepted (quyết định người dùng không mất);
    pending/rejected cũ drop → kết quả mới thay thế."""
    job = await _job(db_session, done_job_with_result)
    db_session.add_all([
        OcrSuggestion(
            job_id=job.id, page_index=0, start=0, end=1,
            original="giu", suggestion="y", reason="ok", status="accepted",
        ),
        OcrSuggestion(
            job_id=job.id, page_index=0, start=2, end=3,
            original="stale", suggestion="x", reason="old", status="pending",
        ),
        OcrSuggestion(
            job_id=job.id, page_index=0, start=4, end=5,
            original="bo", suggestion="z", reason="no", status="rejected",
        ),
    ])
    await db_session.commit()
    fake_llm(
        monkeypatch,
        [_llm_response([{"phrase": "chào", "suggestion": "chao", "reason": "dấu"}])],
    )
    assert await run_proofread(db_session, job) == 1
    rows = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == job.id)
        )
    ).scalars().all()
    assert {r.original: r.status for r in rows} == {
        "giu": "accepted", "chào": "pending",
    }

async def test_run_proofread_rerun_dedupes_vs_accepted(
    monkeypatch, db_session, done_job_with_result
):
    """P2: rerun trả đúng (phrase, suggestion) đã accepted → KHÔNG tạo
    row thứ 2 (chỉ 1 row, giữ accepted)."""
    job = await _job(db_session, done_job_with_result)
    db_session.add(
        OcrSuggestion(
            job_id=job.id, page_index=0, start=0, end=1,
            original="chào", suggestion="chao", reason="dấu",
            status="accepted",
        )
    )
    await db_session.commit()
    fake_llm(
        monkeypatch,
        [_llm_response([{"phrase": "chào", "suggestion": "chao", "reason": "dấu"}])],
    )
    assert await run_proofread(db_session, job) == 0  # 0 row mới
    rows = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == job.id)
        )
    ).scalars().all()
    assert len(rows) == 1 and rows[0].status == "accepted"

async def test_run_proofread_llm_down_warns_and_keeps_job(
    monkeypatch, db_session, done_job_with_result, caplog
):
    fake_llm(monkeypatch, [httpx.ConnectError("LLM down (test)")])
    job = await _job(db_session, done_job_with_result)
    with caplog.at_level("WARNING", logger="app.services.proofread"):
        n = await run_proofread(db_session, job)
    assert n == 0  # best-effort: never raises
    assert any("proofread" in rec.getMessage() for rec in caplog.records)
    assert job.status == "done"
    rows = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == job.id)
        )
    ).scalars().all()
    assert rows == []

async def test_run_proofread_garbage_json_warns_and_returns_zero(
    monkeypatch, db_session, done_job_with_result, caplog
):
    fake_llm(monkeypatch, [FakeResponse("không phải JSON")])
    job = await _job(db_session, done_job_with_result)
    with caplog.at_level("WARNING", logger="app.services.proofread"):
        assert await run_proofread(db_session, job) == 0
    assert any("proofread" in rec.getMessage() for rec in caplog.records)

async def test_run_proofread_reads_db_model_override(
    monkeypatch, db_session, done_job_with_result
):
    """DB Setting row for proofread_llm_model wins over env default."""
    from app.core.models import Setting
    db_session.add(Setting(key="proofread_llm_model", value="db-proofread-model"))
    await db_session.commit()
    calls = fake_llm(
        monkeypatch,
        [_llm_response([{"phrase": "chào", "suggestion": "chao", "reason": "dấu"}])],
    )
    job = await _job(db_session, done_job_with_result)
    await run_proofread(db_session, job)
    assert calls[0][1]["model"] == "db-proofread-model"

async def test_run_proofread_no_result_returns_zero(db_session, done_job_with_result):
    job = await _job(db_session, done_job_with_result)
    job.result = None
    await db_session.commit()
    assert await run_proofread(db_session, job) == 0

# --- hook: schedule after store (job_results pattern) ---

async def test_store_schedules_proofread(
    db_session, seed_job, storage_spy, VALID_RESULT_JSONB, monkeypatch
):
    """_store schedules proofread fire-and-forget; drain awaits it."""
    calls: list = []

    async def _rec(session, job):
        calls.append(job.id)

    monkeypatch.setattr("app.services.proofread.run_proofread", _rec)
    # one layout OK → completion rule reaches done (proofread must not flip it)
    async def _md_ok(*args, **kwargs):
        return "# layout md"
    monkeypatch.setattr("app.routers.exports.build_md", _md_ok)
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
    assert calls == [seed_job]
    # completion task commit trong session RIÊNG (fire-and-forget) — expire cache
    # để đọc status done vừa commit (không stale rendering).
    db_session.expire_all()
    job = await db_session.get(Job, seed_job)
    assert job.status == "done"  # proofread never flips job status

# --- API ---

async def _seed_suggestion(db_session, job_id: int, **kw) -> int:
    row = OcrSuggestion(
        job_id=job_id,
        page_index=kw.get("page_index", 0),
        start=kw.get("start", 0),
        end=kw.get("end", 4),
        original=kw.get("original", "chào"),
        suggestion=kw.get("suggestion", "chao"),
        reason=kw.get("reason", "thiếu dấu"),
        status=kw.get("status", "pending"),
        created_at=kw.get("created_at"),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row.id

async def test_suggestions_list_pending_first_newest_first(
    auth_client, db_session, done_job_with_result
):
    now = datetime.now(timezone.utc)
    older = now - timedelta(minutes=2)
    newer = now - timedelta(minutes=1)
    accepted = await _seed_suggestion(
        db_session, done_job_with_result, original="a", status="accepted", created_at=older
    )
    pending_old = await _seed_suggestion(
        db_session, done_job_with_result, original="b", created_at=older
    )
    pending_new = await _seed_suggestion(
        db_session, done_job_with_result, original="c", created_at=newer
    )
    r = await auth_client.get(f"/api/jobs/{done_job_with_result}/suggestions")
    assert r.status_code == 200, r.text
    items = r.json()
    # pending trước (mới nhất trước), rồi các status khác
    assert [i["id"] for i in items] == [pending_new, pending_old, accepted]
    assert set(items[0]) == {
        "id", "page_index", "start", "end", "original", "suggestion", "reason", "status",
    }

async def test_accept_and_reject_change_status(
    auth_client, db_session, done_job_with_result
):
    sid = await _seed_suggestion(db_session, done_job_with_result)
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/suggestions/{sid}/accept"
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "accepted"}
    row = await db_session.get(OcrSuggestion, sid)
    assert row.status == "accepted"
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/suggestions/{sid}/reject"
    )
    assert r.status_code == 200, r.text
    await db_session.refresh(row)
    assert row.status == "rejected"

async def test_suggestions_other_user_403(auth_client, other_client, db_session, done_job_with_result):
    await _seed_suggestion(db_session, done_job_with_result)
    r = await other_client.get(f"/api/jobs/{done_job_with_result}/suggestions")
    assert r.status_code == 403

async def test_accept_unknown_suggestion_404(auth_client, done_job_with_result):
    r = await auth_client.post(
        f"/api/jobs/{done_job_with_result}/suggestions/999999/accept"
    )
    assert r.status_code == 404

async def test_manual_proofread_endpoint(
    monkeypatch, auth_client, db_session, done_job_with_result
):
    """POST /proofread = nút refresh: chạy run_proofread thật, trả count."""
    fake_llm(
        monkeypatch,
        [_llm_response([{"phrase": "chào", "suggestion": "chao", "reason": "dấu"}])],
    )
    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/proofread")
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 1}
    rows = (
        await db_session.execute(
            select(OcrSuggestion).where(OcrSuggestion.job_id == done_job_with_result)
        )
    ).scalars().all()
    assert len(rows) == 1

async def test_manual_proofread_llm_down_returns_zero(auth_client, done_job_with_result):
    # conftest autouse stub: proofread.AsyncClient raises ConnectError → count 0
    r = await auth_client.post(f"/api/jobs/{done_job_with_result}/proofread")
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 0}
