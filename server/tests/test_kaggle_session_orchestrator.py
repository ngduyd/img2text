"""Spec kaggle session worker T6: orchestrator mode "session"
(AC1/3/5/6/9/10). Fake api inject — pattern test_kaggle_batch_orchestrator."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, update

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.models import Job, User, WorkerSession
from app.core.security import hash_worker_token
from app.services import kaggle_orchestrator as orch

SESSION_REF = "testuser/img2text-session"

class FakeApi:
    """Live-shaped: kernels_push trả ref, kernels_status control được,
    quota_view trả GPU quota."""

    def __init__(self) -> None:
        self.pushes: list[dict[str, str]] = []  # staged files per push
        self.status = "running"
        self.gpu_used_s = 3600.0
        self.gpu_total_s = 21600.0

    def kernels_push(self, folder: str) -> str:
        from pathlib import Path

        self.pushes.append({
            p.name: p.read_text(encoding="utf-8")
            for p in Path(folder).iterdir()
            if p.is_file()
        })
        return SESSION_REF

    def kernels_status(self, ref: str):
        return SimpleNamespace(status=self.status)

    def quota_view(self):
        return SimpleNamespace(
            gpuQuota=SimpleNamespace(
                timeUsed=f"{self.gpu_used_s}s",
                totalTimeAllowed=f"{self.gpu_total_s}s",
            ),
        )

@pytest.fixture(autouse=True)
def _kaggle_env(monkeypatch):
    monkeypatch.setattr(settings, "kaggle_username", "testuser")
    monkeypatch.setattr(settings, "kaggle_key", "k")
    monkeypatch.setattr(
        settings, "kaggle_kernel_ref", "testuser/img2text-kernel"
    )
    monkeypatch.setattr(settings, "kaggle_mode", "session")
    monkeypatch.setattr(settings, "kaggle_min_gap_seconds", 0)
    monkeypatch.setattr(orch, "_last_spawn", 0.0)
    monkeypatch.setattr(orch, "_quota_low", False)
    monkeypatch.setattr(orch, "_sessions", {})

async def _seed_user(db_session) -> int:
    user = (
        await db_session.execute(select(User).order_by(User.id).limit(1))
    ).scalars().first()
    if user is None:
        user = User(email="ws-orch@x.io", password_hash="x")
        db_session.add(user)
        await db_session.commit()
    return user.id

async def _seed_job(db_session, status="queued", session_id=None) -> int:
    job = Job(
        user_id=await _seed_user(db_session),
        status=status,
        storage_key="uploads/ws-orch.jpg",
        file_type="image",
        page_count=1,
        session_id=session_id,
        lease_expires_at=(
            datetime.now(timezone.utc) + timedelta(hours=9)
            if status == "extracting"
            else None
        ),
        started_at=datetime.now(timezone.utc) if status == "extracting" else None,
    )
    db_session.add(job)
    await db_session.commit()
    return job.id

async def _live_session_id(db_session):
    return await db_session.scalar(
        select(WorkerSession.id).where(WorkerSession.closed_at.is_(None))
    )

async def test_spawn_session_bakes_base_url(db_session, monkeypatch):
    """E2: base_url bake vào script lúc push (__BASE_URL__ substitute), KHÔNG
    còn placeholder nào — kernel session không cần Secrets."""
    monkeypatch.setattr(settings, "base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "worker_base_url", "")
    api = FakeApi()
    assert await orch._spawn_session(api, SessionLocal, key="k-url") is True
    script = api.pushes[0]["img2text_session.py"]
    assert "https://api.example.com" in script
    assert "__BASE_URL__" not in script
    assert "__SESSION_KEY__" not in script

async def test_spawn_session_bakes_worker_base_url(db_session, monkeypatch):
    """W1: worker_base_url set → bake nó, KHÔNG bake base_url (browser-facing)."""
    monkeypatch.setattr(settings, "base_url", "http://localhost:5173")
    monkeypatch.setattr(settings, "worker_base_url", "https://worker.example.com")
    api = FakeApi()
    assert await orch._spawn_session(api, SessionLocal, key="k-worker") is True
    script = api.pushes[0]["img2text_session.py"]
    assert "https://worker.example.com" in script
    assert "http://localhost:5173" not in script
    assert "__BASE_URL__" not in script

async def test_spawn_session_falls_back_to_base_url(db_session, monkeypatch):
    """W1: worker_base_url rỗng → fallback base_url (backward-compat)."""
    monkeypatch.setattr(settings, "base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "worker_base_url", "")
    api = FakeApi()
    assert await orch._spawn_session(api, SessionLocal, key="k-fallback") is True
    script = api.pushes[0]["img2text_session.py"]
    assert "https://api.example.com" in script
    assert "__BASE_URL__" not in script

async def test_spawn_session_whitespace_worker_base_url_falls_back(
    db_session, monkeypatch
):
    """F1: worker_base_url whitespace-only → strip → fallback base_url,
    KHÔNG bake chuỗi "  " vào script."""
    monkeypatch.setattr(settings, "base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "worker_base_url", "  ")
    api = FakeApi()
    assert await orch._spawn_session(api, SessionLocal, key="k-ws") is True
    script = api.pushes[0]["img2text_session.py"]
    assert "https://api.example.com" in script
    assert "__BASE_URL__" not in script

async def test_spawn_session_warns_unreachable_base_url(
    db_session, monkeypatch, caplog
):
    """base_url rỗng/localhost → kernel Kaggle không reach được → warning."""
    # F3: pin settings để không phụ thuộc env shell (pydantic case-insensitive).
    monkeypatch.setattr(settings, "base_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "worker_base_url", "")
    api = FakeApi()
    with caplog.at_level(logging.WARNING, logger=orch.__name__):
        assert await orch._spawn_session(api, SessionLocal, key="k-warn") is True
    assert any(
        "api_base" in r.message and "reach" in r.message
        for r in caplog.records
    )

async def test_spawn_session_warns_worker_base_url_localhost(
    db_session, monkeypatch, caplog
):
    """W1: api_base localhost (qua worker_base_url) → warn, dù base_url public."""
    monkeypatch.setattr(settings, "base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "worker_base_url", "http://127.0.0.1:8000")
    api = FakeApi()
    with caplog.at_level(logging.WARNING, logger=orch.__name__):
        assert await orch._spawn_session(api, SessionLocal, key="k-warn2") is True
    assert any(
        "api_base" in r.message and "reach" in r.message
        for r in caplog.records
    )

async def test_spawn_session_stores_hash_not_plaintext(db_session):
    api = FakeApi()
    key = "spawn-plaintext-key-42"
    assert await orch._spawn_session(api, SessionLocal, key=key) is True
    assert len(api.pushes) == 1
    staged = api.pushes[0]
    assert {"img2text_session.py", "img2text_batch.py",
            "kernel-metadata.json"} <= set(staged)
    script = staged["img2text_session.py"]
    assert key in script  # key được chèn vào script lúc staged push
    assert "__SESSION_KEY__" not in script
    assert key not in staged["kernel-metadata.json"]  # key KHÔNG trong metadata
    meta = json.loads(staged["kernel-metadata.json"])
    assert meta["id"] == "testuser/img2text-session"
    assert meta["code_file"] == "img2text_session.py"
    # DB chỉ có hash-at-rest; plaintext không nằm trong row
    sid = await _live_session_id(db_session)
    row = await db_session.get(WorkerSession, sid)
    assert row.key_hash == hashlib.sha256(key.encode()).hexdigest()
    assert row.kernel_ref == SESSION_REF
    assert row.closed_at is None
    from sqlalchemy import text

    row_text = await db_session.scalar(
        text("SELECT ws::text FROM worker_sessions ws WHERE ws.id = :i"),
        {"i": sid},
    )
    assert key not in row_text

async def test_single_active_session_guard(db_session, monkeypatch):
    api = FakeApi()
    assert await orch._spawn_session(api, SessionLocal, key="k1") is True
    await _seed_job(db_session, "queued")
    monkeypatch.setattr(orch, "_api", lambda: api)
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is False
    assert len(api.pushes) == 1  # không push session thứ 2 (AC1)

async def test_quota_gate_blocks_spawn(db_session, monkeypatch):
    """AC6: quota API dưới ngưỡng → skip spawn + quota_low flag; đủ → push."""
    api = FakeApi()
    api.gpu_used_s = api.gpu_total_s  # hết quota
    monkeypatch.setattr(orch, "_api", lambda: api)
    await _seed_job(db_session, "queued")
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is False
    assert api.pushes == []
    assert orch.session_quota_low() is True
    # claim response sẽ thấy quota_low=true → worker exit 0 (AC5)
    api.gpu_used_s = 100.0  # đủ quota → spawn
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is True
    assert len(api.pushes) == 1
    assert orch.session_quota_low() is False

async def test_dead_kernel_reverts_claimed_clears_session_id_and_respawns(
    db_session, monkeypatch
):
    """AC9/AC10: kernel failed → fail job extracting của session, session row
    xóa, session_id NULL, respawn khi queue còn."""
    api = FakeApi()
    assert await orch._spawn_session(api, SessionLocal, key="k-dead") is True
    sid = await _live_session_id(db_session)
    jid = await _seed_job(db_session, "extracting", session_id=sid)
    await _seed_job(db_session, "queued")  # respawn trigger
    api.status = "failed"
    monkeypatch.setattr(orch, "_api", lambda: api)
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is True
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "failed"  # AC10: per-job fail (partial-fail kept)
    assert job.session_id is None  # AC3b: không treo trỏ session đã xóa
    assert job.lease_expires_at is None
    assert await db_session.get(WorkerSession, sid) is None  # hash xóa ngay
    assert len(api.pushes) == 2  # respawn

async def test_dead_kernel_reverts_queued_when_claim_lost(db_session, monkeypatch):
    """AC3b: revert path — job extracting (token NULL) → queued + lease NULL
    + session_id NULL khi kernel died + timeout (không fail)."""
    api = FakeApi()
    await orch._spawn_session(api, SessionLocal, key="k-timeout")
    sid = await _live_session_id(db_session)
    jid = await _seed_job(db_session, "extracting", session_id=sid)
    await db_session.execute(
        update(WorkerSession)
        .where(WorkerSession.id == sid)
        .values(spawned_at=datetime.now(timezone.utc) - timedelta(hours=10))
    )
    await db_session.commit()
    orch._sessions.clear()  # map entry mới → adopt từ DB row đã backdate
    monkeypatch.setattr(orch, "_api", lambda: api)
    pushed = await orch.ensure_worker(SessionLocal)
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "queued"
    assert job.lease_expires_at is None
    assert job.session_id is None
    assert await db_session.get(WorkerSession, sid) is None

async def test_close_session_with_live_job_sets_null(db_session):
    """AC3a: close session khi job còn trỏ → job còn tồn tại, session_id NULL
    (FK ON DELETE SET NULL)."""
    api = FakeApi()
    await orch._spawn_session(api, SessionLocal, key="k-close")
    sid = await _live_session_id(db_session)
    jid = await _seed_job(db_session, "extracting", session_id=sid)
    await orch._close_session(SessionLocal, sid)
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job is not None
    assert job.session_id is None
    assert await db_session.get(WorkerSession, sid) is None

async def test_close_session_emits_explicit_session_id_null(db_session):
    """F1: _close_session null jobs.session_id bằng UPDATE TƯỜNG MINH — không
    phụ thuộc FK ON DELETE SET NULL (FK tắt → job treo session_id cũ).
    Kiểm bằng SQL emit (không mutate DDL chung)."""
    api = FakeApi()
    await orch._spawn_session(api, SessionLocal, key="k-explicit")
    sid = await _live_session_id(db_session)
    job_id = await _seed_job(db_session, "extracting", session_id=sid)
    stmts: list[str] = []

    def _capture(conn, cursor, statement, params, context, executemany):
        stmts.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        await orch._close_session(SessionLocal, sid)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)
    upd = next(
        (i for i, s in enumerate(stmts)
         if s.lstrip().upper().startswith("UPDATE JOBS")
         and "session_id" in s.lower()),
        None,
    )
    dele = next(
        (i for i, s in enumerate(stmts)
         if s.lstrip().upper().startswith("DELETE FROM WORKER_SESSIONS")),
        None,
    )
    assert upd is not None, stmts
    assert dele is not None, stmts
    # session_id null PHẢI chạy TRƯỚC DELETE (FK tắt → job không bị treo).
    assert upd < dele, stmts

    db_session.expire_all()
    assert (await db_session.get(Job, job_id)).session_id is None

async def test_restart_adopts_live_session(db_session, monkeypatch):
    """AC9: restart — extracting job + session row + kernel active → adopt,
    KHÔNG push mới."""
    api = FakeApi()
    api.status = "running"
    sid = await orch._spawn_session(api, SessionLocal, key="k-adopt")
    jid = await _seed_job(db_session, "extracting", session_id=sid)
    await _seed_job(db_session, "queued")
    orch._sessions.clear()  # restart: map rỗng, DB còn
    monkeypatch.setattr(orch, "_api", lambda: api)
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is False
    assert len(api.pushes) == 1  # không push mới
    assert sid in orch._sessions
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "extracting"  # adopt, không revert

async def test_restart_dead_kernel_cleanup_and_respawn(db_session, monkeypatch):
    """AC9: restart — session row còn nhưng kernel dead → dọn (fail jobs +
    close) + respawn."""
    api = FakeApi()
    await orch._spawn_session(api, SessionLocal, key="k-dead2")
    sid = await _live_session_id(db_session)
    jid = await _seed_job(db_session, "extracting", session_id=sid)
    await _seed_job(db_session, "queued")
    orch._sessions.clear()
    api.status = "failed"
    monkeypatch.setattr(orch, "_api", lambda: api)
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is True
    db_session.expire_all()
    job = await db_session.get(Job, jid)
    assert job.status == "failed"  # AC10: kernel failed → fail job extracting
    assert job.session_id is None
    assert await db_session.get(WorkerSession, sid) is None
    assert len(api.pushes) == 2

async def test_session_exit_graceful_on_empty_queue(db_session, monkeypatch):
    """AC5: poll complete + queue rỗng → session đóng, KHÔNG respawn."""
    api = FakeApi()
    await orch._spawn_session(api, SessionLocal, key="k-grace")
    sid = await _live_session_id(db_session)
    api.status = "complete"
    monkeypatch.setattr(orch, "_api", lambda: api)
    pushed = await orch.ensure_worker(SessionLocal)
    assert pushed is False
    assert len(api.pushes) == 1  # không respawn
    assert await db_session.get(WorkerSession, sid) is None
    assert orch._sessions == {}
