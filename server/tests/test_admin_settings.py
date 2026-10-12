"""Plan S: admin runtime settings — GET/PUT, floors, live reschedule, audit.

Runtime override store = Setting rows (key/value String). Sources: "db" when a
row exists, "env" (pydantic Settings) otherwise. Audit trail = the
RequestLogsMiddleware row for the PUT (every-request audit, Plan X R6).
"""

from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, RequestLog, Setting, User
from app.core.db import SessionLocal
from app.services import kaggle_orchestrator as orch
from app.services.runtime_settings import get_runtime_setting
from app.services.scheduler import init_scheduler

KEYS = (
    "scheduler_interval_seconds",
    "kaggle_min_queue",
    "kaggle_min_gap_seconds",
    "kaggle_mode",
    "llm_base_url",
    "llm_model",
    "proofread_llm_model",
    "llm_api_key",
    "llm_timeout",
)

# Write-only key masking (WS-ADMIN): "sk-…last4", empty → null.
def _masked(value) -> str | None:
    if not value:
        return None
    return f"{value[:3]}…{value[-4:]}" if len(value) >= 8 else "***"

# --- GET ---

async def test_get_settings_shape_default_source_env(admin_client):
    r = await admin_client.get("/api/admin/settings")
    assert r.status_code == 200
    data = r.json()
    assert set(data) == set(KEYS)
    for key in KEYS:
        # no rows (db_truncate) → env default, source "env"; api key is
        # write-only → masked (None when the env default is empty)
        want = _masked(getattr(settings, key)) if key == "llm_api_key" else getattr(settings, key)
        assert data[key] == {"value": want, "source": "env"}

async def test_get_settings_non_admin_403(auth_client):
    assert (await auth_client.get("/api/admin/settings")).status_code == 403

async def test_get_settings_anon_401(client):
    assert (await client.get("/api/admin/settings")).status_code == 401

# --- PUT validation ---

async def test_put_interval_floor_422(admin_client):
    r = await admin_client.put(
        "/api/admin/settings", json={"scheduler_interval_seconds": 4}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "scheduler_interval_seconds phải từ 5 giây trở lên."

async def test_put_other_floors_and_mode_readonly(admin_client):
    r = await admin_client.put("/api/admin/settings", json={"kaggle_min_queue": 0})
    assert r.status_code == 422
    assert r.json()["detail"] == "kaggle_min_queue phải từ 1 trở lên."
    r = await admin_client.put("/api/admin/settings", json={"kaggle_min_gap_seconds": 59})
    assert r.status_code == 422
    assert r.json()["detail"] == "kaggle_min_gap_seconds phải từ 60 giây trở lên."
    # kaggle_mode: read-only in the API (mode flip needs a restart)
    r = await admin_client.put("/api/admin/settings", json={"kaggle_mode": "loop"})
    assert r.status_code == 422
    assert "read-only" in r.json()["detail"]

async def test_put_unknown_key_422(admin_client):
    """Rider: extra=forbid — a typo'd key must 422, not silently no-op."""
    r = await admin_client.put(
        "/api/admin/settings", json={"kaggle_min_gape": 60}
    )
    assert r.status_code == 422

async def test_put_llm_string_keys(admin_client):
    """LLM keys are strings — upsert + effective value returned."""
    r = await admin_client.put(
        "/api/admin/settings",
        json={
            "llm_base_url": "http://llm.example/v1",
            "llm_model": "custom-layout-model",
            "proofread_llm_model": "custom-proofread-model",
            "llm_api_key": "sk-test-key",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["llm_base_url"] == {"value": "http://llm.example/v1", "source": "db"}
    assert body["llm_model"] == {"value": "custom-layout-model", "source": "db"}
    assert body["proofread_llm_model"] == {"value": "custom-proofread-model", "source": "db"}
    # write-only: PUT echoes the MASK, full key never leaves the server
    assert body["llm_api_key"] == {"value": "sk-…-key", "source": "db"}
    # upsert: second PUT rewrites
    r = await admin_client.put(
        "/api/admin/settings", json={"llm_model": "another-model"}
    )
    assert r.status_code == 200
    assert r.json()["llm_model"] == {"value": "another-model", "source": "db"}
    # untouched keys stay env
    assert r.json()["llm_base_url"]["source"] == "db"
    assert r.json()["proofread_llm_model"]["source"] == "db"

# --- WS-ADMIN: llm_timeout bounds + llm_api_key write-only mask ---

async def test_put_llm_timeout_bounds_422(admin_client):
    for bad in (29, 601):
        r = await admin_client.put("/api/admin/settings", json={"llm_timeout": bad})
        assert r.status_code == 422
        assert r.json()["detail"] == "llm_timeout phải trong khoảng 30–600 giây."
    r = await admin_client.put("/api/admin/settings", json={"llm_timeout": 300})
    assert r.status_code == 200
    assert r.json()["llm_timeout"] == {"value": 300, "source": "db"}

async def test_llm_api_key_write_only_mask(admin_client, db_session):
    r = await admin_client.put(
        "/api/admin/settings", json={"llm_api_key": "sk-secret-abcdef1234"}
    )
    assert r.status_code == 200
    assert r.json()["llm_api_key"]["value"] == "sk-…1234"  # PUT echo masked
    r = await admin_client.get("/api/admin/settings")
    assert r.status_code == 200
    assert r.json()["llm_api_key"]["value"] == "sk-…1234"
    assert "sk-secret-abcdef1234" not in r.text  # full value never in a response
    # write-only ≠ not stored: consumers (render/proofread) read the full row
    row = await db_session.get(Setting, "llm_api_key")
    assert row is not None and row.value == "sk-secret-abcdef1234"

async def test_put_anon_401(client):
    r = await client.put("/api/admin/settings", json={"kaggle_min_queue": 2})
    assert r.status_code == 401

async def test_put_non_admin_403(auth_client):
    r = await auth_client.put(
        "/api/admin/settings", json={"kaggle_min_queue": 2}
    )
    assert r.status_code == 403

# --- PUT upsert + live reschedule ---

async def test_put_upserts_setting_rows_and_reschedules(admin_client, app):
    init_scheduler(app)  # registers reap-leases (start skipped under pytest)
    r = await admin_client.put(
        "/api/admin/settings",
        json={"scheduler_interval_seconds": 30, "kaggle_min_queue": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scheduler_interval_seconds"] == {"value": 30, "source": "db"}
    assert body["kaggle_min_queue"] == {"value": 3, "source": "db"}
    assert body["kaggle_min_gap_seconds"]["source"] == "env"  # untouched
    # live apply: reap-leases trigger retargeted without a restart
    job = app.state.scheduler.get_job("reap-leases")
    assert job.trigger.interval == timedelta(seconds=30)
    # upsert: second PUT rewrites the row (no duplicates), trigger follows
    r = await admin_client.put(
        "/api/admin/settings", json={"scheduler_interval_seconds": 45}
    )
    assert r.status_code == 200
    assert r.json()["scheduler_interval_seconds"] == {"value": 45, "source": "db"}
    job = app.state.scheduler.get_job("reap-leases")
    assert job.trigger.interval == timedelta(seconds=45)

async def test_put_without_scheduler_registered_still_succeeds(app, admin_client):
    # no lifespan under ASGITransport → app.state.scheduler missing: no live
    # apply, but the DB write must stand (next boot picks it up)
    r = await admin_client.put(
        "/api/admin/settings", json={"scheduler_interval_seconds": 30}
    )
    assert r.status_code == 200
    assert r.json()["scheduler_interval_seconds"] == {"value": 30, "source": "db"}

async def test_put_writes_audit_request_log(admin_client, db_session):
    r = await admin_client.put("/api/admin/settings", json={"kaggle_min_queue": 2})
    assert r.status_code == 200
    row = (
        await db_session.execute(
            select(RequestLog).where(RequestLog.path == "/api/admin/settings")
        )
    ).scalars().one()
    assert row.method == "PUT"
    assert row.status == 200
    assert row.user_id is not None  # attributed to the admin actor (R60a)

# --- runtime override in the orchestrator ---

async def test_runtime_setting_db_row_wins_else_env(db_session, monkeypatch):
    monkeypatch.setattr(settings, "kaggle_min_queue", 7)
    assert await get_runtime_setting(SessionLocal, "kaggle_min_queue") == 7
    db_session.add(Setting(key="kaggle_min_queue", value="5"))
    await db_session.commit()
    assert await get_runtime_setting(SessionLocal, "kaggle_min_queue") == 5
    # unparseable row → env default (never crash a tick)
    monkeypatch.setattr(settings, "scheduler_interval_seconds", 50)
    db_session.add(Setting(key="scheduler_interval_seconds", value="abc"))
    await db_session.commit()
    assert await get_runtime_setting(SessionLocal, "scheduler_interval_seconds") == 50

class _LoopStubApi:
    """Loop-branch stub: status complete; records pushes (skip = none)."""

    def __init__(self) -> None:
        self.status_calls: list = []
        self.pushed: list = []

    def kernels_status(self, ref):
        self.status_calls.append(ref)
        return {"status": "complete"}

    def kernels_push(self, path, **kwargs):
        self.pushed.append(path)
        return {"ref": path}

async def test_ensure_worker_reads_db_min_queue_override(db_session, monkeypatch):
    """DB min_queue=5 with 2 queued → skip, even though env says 1 (spawn)."""
    monkeypatch.setattr(settings, "kaggle_mode", "loop")
    monkeypatch.setattr(settings, "kaggle_username", "testuser")
    monkeypatch.setattr(settings, "kaggle_key", "testkey")
    monkeypatch.setattr(settings, "kaggle_kernel_ref", "testuser/img2text-worker")
    monkeypatch.setattr(settings, "kaggle_min_queue", 1)  # env floor: would spawn
    monkeypatch.setattr(orch, "_last_spawn", 0.0)
    stub = _LoopStubApi()
    monkeypatch.setattr(orch, "_api", lambda: stub)
    user = User(email="seed@test.io", password_hash="x", role="user")
    db_session.add(user)
    await db_session.flush()  # id BEFORE the jobs (FK)
    for i in range(2):
        db_session.add(
            Job(user_id=user.id, storage_key=f"{i}.png", file_type="png", page_count=1)
        )
    db_session.add(Setting(key="kaggle_min_queue", value="5"))
    await db_session.commit()
    assert await orch.ensure_worker(SessionLocal) is False
    # reached the queue gate (status probed) but never pushed
    assert len(stub.status_calls) == 1
    assert stub.pushed == []
