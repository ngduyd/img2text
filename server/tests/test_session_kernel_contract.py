"""Spec kaggle session worker T7: kernel contract (deploy/kaggle/kernel/
img2text_session.py). Import module — KHÔNG bootstrap (kb rule: importing
phải cheap). Fake backend monkeypatch urllib seams (AC2/AC10)."""

import json
import sys
import types
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

KERNEL_DIR = Path(__file__).parents[2] / "deploy" / "kaggle" / "kernel"
sys.path.insert(0, str(KERNEL_DIR))

import img2text_batch as kb  # noqa: E402
import img2text_session as sess  # noqa: E402

sys.path.remove(str(KERNEL_DIR))

DOC_FIXTURE = {
    "source_pdf": "/tmp/x.pdf",
    "dpi": 200,
    "pages": [
        {
            "page": 1,
            "image": "/tmp/pre/page_0001.png",
            "width": 800,
            "height": 600,
            "preprocess": {},
            "blocks": [
                {"id": "p1_b0", "order": 0, "type": "doc_title",
                 "bbox": [10, 10, 400, 60], "text": "Báo cáo", "empty": False},
                {"id": "p1_b1", "order": 1, "type": "paragraph_title",
                 "bbox": [10, 70, 400, 100], "text": "Mục 1", "empty": False},
                {"id": "p1_b2", "order": 2, "type": "table",
                 "bbox": [10, 110, 400, 300],
                 "text": "1",
                 "html": "<table><tr><td>1</td></tr></table>",
                 "cells": [[{"text": "1", "rowspan": 1, "colspan": 1,
                             "header": False}]],
                 "empty": False},
                {"id": "p1_b3", "order": 3, "type": "image",
                 "bbox": [10, 310, 400, 500], "text": "hình minh họa",
                 "empty": False},
                {"id": "p1_b4", "order": 4, "type": "text",
                 "bbox": [10, 510, 400, 550], "text": "   ", "empty": True},
            ],
        }
    ],
    "problems": ["page_0002.png: precheck unreadable — không OCR"],
}

def test_session_kernel_import_parity():
    from app.core.schemas import IMAGE_MARKER
    from app.services.kaggle_orchestrator import BATCH_MODEL_VERSION

    assert sess.IMAGE_MARKER == IMAGE_MARKER
    assert sess.VL_MODEL_VERSION == BATCH_MODEL_VERSION
    assert kb.VL_MODEL == sess.VL_MODEL_VERSION
    assert sess.EXIT_GRACEFUL == 0
    assert sess.EXIT_FATAL == 1
    assert sess.EXIT_SESSION_LEVEL == 90
    # bootstrap tách thành hàm tái sử dụng (KHÔNG copy-paste vào session)
    assert callable(kb.bootstrap_venv)

def test_adapt_document_parity_with_server():
    """kernel adapt_document == orchestrator adapt_batch_document (cùng doc)."""
    from app.services.kaggle_orchestrator import adapt_batch_document

    assert sess.adapt_document(DOC_FIXTURE) == adapt_batch_document(DOC_FIXTURE)

def _claim(job_id: int) -> dict:
    return {
        "job_id": job_id,
        "session_key": "k",
        "session_id": 1,
        "file_url": f"http://r2/uploads/img{job_id}.png?sig=abc",
        "sha256": None,
        "file_type": "image",
        "page_count": 1,
        "preprocess": None,
        "result_upload_url": f"http://r2/jobs/{job_id}/_result.json?sig=x",
        "crop_upload_urls": {f"r{job_id}0": f"http://r2/jobs/{job_id}/crops/r{job_id}0.png?sig=y"},
        "server_flags": {"quota_low": False},
    }

async def test_session_kernel_loop_contract(monkeypatch):
    """AC2: claim → job → claim → job → empty → exit 0; model ctor 1 lần
    (singleton giữa các claim); PUT result.json mỗi job; done mỗi job."""
    claims = [_claim(11), _claim(12)]
    calls: list[tuple] = []
    done_bodies: list[dict] = []
    pipeline_ctors = {"n": 0}

    def fake_http(method, url, key, payload=None, timeout=60):
        calls.append((method, url, payload))
        if url.endswith("/api/jobs/next"):
            return claims.pop(0) if claims else {"empty": True}
        if url.endswith("/status"):
            return {"status": "extracting", "error": None}
        if url.endswith("/done") or url.endswith("/result"):
            done_bodies.append(payload)
            return {}
        if url.endswith("/fail"):
            raise AssertionError("không được fail")
        return {}  # heartbeat

    def fake_pipeline_ctor():
        pipeline_ctors["n"] += 1
        return object()

    def fake_process(job_id, input_path, preprocess_spec, cancel_check):
        sess.get_pipeline()  # model qua singleton — ctor phải = 1 tổng
        doc = json.loads(json.dumps(DOC_FIXTURE))
        return doc, {f"r{job_id}0": b"\x89PNG-fake"}

    puts: list[tuple] = []

    def fake_put(url, data, timeout=300):
        puts.append((url, data))

    fetched: list[str] = []

    def fake_fetch(url, dest, sha256=None, timeout=120.0):
        fetched.append(url)

    monkeypatch.setattr(sess, "_http_json", fake_http)
    monkeypatch.setattr(sess, "_put_bytes", fake_put)
    monkeypatch.setattr(sess, "_make_pipeline", fake_pipeline_ctor)
    monkeypatch.setattr(sess, "process_job_session", fake_process)
    monkeypatch.setattr(sess.kb, "fetch_input", fake_fetch)
    monkeypatch.setattr(sess, "HEARTBEAT_INTERVAL_S", 10**9)  # không heartbeat

    rc = sess.run_loop("http://base", "k")

    assert rc == sess.EXIT_GRACEFUL  # empty → exit 0 (AC5)
    assert pipeline_ctors["n"] == 1  # model load 1×/session (AC2)
    result_puts = [u for u, _ in puts if "_result.json" in u]
    crop_puts = [u for u, _ in puts if "/crops/" in u]
    assert len(result_puts) == 2 and len(crop_puts) == 2
    payload = json.loads(
        next(d for u, d in puts if "jobs/11/_result.json" in u)
    )
    assert payload["model_version"] == sess.VL_MODEL_VERSION
    assert payload["gpu_seconds"] >= 0
    assert len(done_bodies) == 2
    assert fetched == [
        "http://r2/uploads/img11.png?sig=abc",
        "http://r2/uploads/img12.png?sig=abc",
    ]

def test_exit_code_90_session_level(monkeypatch):
    """AC10: venv bootstrap fail (subprocess returncode != 0, venv không
    ra) → main() = exit 90 (session-level, server respawn)."""
    monkeypatch.setenv("BASE_URL", "http://base")
    monkeypatch.delenv("_IMG2TEXT_SESSION_VENV", raising=False)
    monkeypatch.setattr(sess.kb, "VENV_PY", "/nonexistent/paddle-venv/bin/python")
    monkeypatch.setattr(
        sess.kb.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(returncode=1),
    )
    assert sess.main() == sess.EXIT_SESSION_LEVEL

def test_main_missing_base_url_is_fatal(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("_IMG2TEXT_SESSION_VENV", raising=False)
    assert sess.main() == sess.EXIT_FATAL

def test_quota_low_exits_graceful(monkeypatch):
    """AC5: server_flags.quota_low → exit 0."""
    def fake_http(method, url, key, payload=None, timeout=60):
        if url.endswith("/api/jobs/next"):
            return {"job_id": 1, "server_flags": {"quota_low": True}}
        return {}
    monkeypatch.setattr(sess, "_http_json", fake_http)
    monkeypatch.setattr(sess, "HEARTBEAT_INTERVAL_S", 10**9)
    assert sess.run_loop("http://base", "k") == sess.EXIT_GRACEFUL

def test_cancel_check_429_treated_not_cancelled(monkeypatch):
    """Limiter 429 lúc poll status (transient) → coi như chưa cancel, KHÔNG raise
    (tránh fail SAI job khi limiter nghẽn tạm thời)."""
    def fake_status_429(base, key, job_id):
        raise urllib.error.HTTPError(
            "http://base", 429, "Too Many Requests", {}, None
        )
    monkeypatch.setattr(sess, "_status", fake_status_429)
    assert sess._cancel_check("http://base", "k", 7) is True

def test_cancel_check_timeout_treated_not_cancelled(monkeypatch):
    """Timeout lúc poll status → coi như chưa cancel, KHÔNG raise."""
    def fake_status_timeout(base, key, job_id):
        raise TimeoutError("timed out")
    monkeypatch.setattr(sess, "_status", fake_status_timeout)
    assert sess._cancel_check("http://base", "k", 7) is True

def test_claim_429_backoff_then_success(monkeypatch):
    """Claim 429 MỘT lần rồi OK → backoff rồi claim lại, loop TIẾP (empty →
    exit 0), KHÔNG exit fatal."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_http(method, url, key, payload=None, timeout=60):
        if url.endswith("/api/jobs/next"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    url, 429, "Too Many Requests", {}, None
                )
            return {"empty": True}
        return {}

    monkeypatch.setattr(sess, "_http_json", fake_http)
    monkeypatch.setattr(sess, "HEARTBEAT_INTERVAL_S", 10**9)
    monkeypatch.setattr(sess, "CLAIM_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(sess.time, "sleep", lambda s: sleeps.append(s))

    assert sess.run_loop("http://base", "k") == sess.EXIT_GRACEFUL
    assert calls["n"] == 2  # 1× 429 → retry → empty
    assert len(sleeps) == 1  # đã backoff đúng 1 lần

def test_claim_429_capped_then_fatal(monkeypatch):
    """429 LIÊN TỤC → retry CÓ CAP (số lần + sleep tối đa) rồi EXIT_FATAL —
    KHÔNG treo kernel vĩnh viễn."""
    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_http(method, url, key, payload=None, timeout=60):
        if url.endswith("/api/jobs/next"):
            calls["n"] += 1
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(sess, "_http_json", fake_http)
    monkeypatch.setattr(sess, "HEARTBEAT_INTERVAL_S", 10**9)
    monkeypatch.setattr(sess, "CLAIM_BACKOFF_BASE_S", 1.0)
    monkeypatch.setattr(sess, "CLAIM_MAX_RETRIES", 3)
    monkeypatch.setattr(sess.time, "sleep", lambda s: sleeps.append(s))

    assert sess.run_loop("http://base", "k") == sess.EXIT_FATAL
    assert calls["n"] == 4  # 1 lần gốc + 3 retry
    assert len(sleeps) == 3
    assert all(s <= sess.CLAIM_BACKOFF_MAX_S for s in sleeps)  # cap sleep
