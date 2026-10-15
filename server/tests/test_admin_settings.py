"""Plan S: admin runtime settings — GET/PUT, floors, live reschedule, audit.

Runtime override store = Setting rows (key/value String). Sources: "db" when a
row exists, "env" (pydantic Settings) otherwise. Audit trail = the
RequestLogsMiddleware row for the PUT (every-request audit, Plan X R6).
"""

from datetime import timedelta

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.models import Job, RequestLog, Setting, User
from app.core.db import SessionLocal
from app.services import kaggle_orchestrator as orch
from app.services.runtime_settings import get_runtime_setting
from app.services.scheduler import init_scheduler

KEYS = (
    "scheduler_interval_seconds",
    "purge_interval_seconds",
    "purge_retention_days",
    "kaggle_min_queue",
    "kaggle_min_gap_seconds",
    "kaggle_mode",
    "llm_base_url",
    "llm_model",
    "proofread_llm_model",
    "llm_api_key",
    "llm_timeout",
    "ir_llm_model",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_pass",
    "smtp_from",
    "max_pages",
    "daily_page_limit",
    "weekly_page_limit",
    "upload_byte_limit",
)

# Write-only keys (WS-ADMIN): masked in every response, empty PUT = keep.
WRITE_ONLY = {"llm_api_key", "smtp_pass"}

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
        # no rows (db_truncate) → env default, source "env"; write-only keys
        # are masked (None when the env default is empty). Quota keys have no
        # pydantic twin — defaults mirror quota.py constants (Lane CFG decision
        # A: rows persist, quota redesign wires them later).
        from app.services.runtime_settings import _QUOTA_DEFAULTS
        default = getattr(settings, key, _QUOTA_DEFAULTS.get(key))
        want = _masked(default) if key in WRITE_ONLY else default
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
    # spec §User-facing #7: admin input 120–600s
    for bad in (29, 119, 601):
        r = await admin_client.put("/api/admin/settings", json={"llm_timeout": bad})
        assert r.status_code == 422
        assert r.json()["detail"] == "llm_timeout phải trong khoảng 120–600 giây."
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

async def test_put_llm_api_key_empty_keeps_existing(admin_client, db_session):
    """Lane C: PATCH để trống = giữ nguyên (write-only form không echo key)."""
    r = await admin_client.put(
        "/api/admin/settings", json={"llm_api_key": "sk-secret-abcdef1234"}
    )
    assert r.status_code == 200
    r = await admin_client.put("/api/admin/settings", json={"llm_api_key": ""})
    assert r.status_code == 200
    assert r.json()["llm_api_key"]["value"] == "sk-…1234"  # mask giữ nguyên
    row = await db_session.get(Setting, "llm_api_key")
    assert row.value == "sk-secret-abcdef1234"  # full key không bị xóa

# --- Lane CFG: smtp/max_pages/quota keys + floors + write-only smtp_pass ---

async def test_put_smtp_port_bounds_422(admin_client):
    for bad in (0, 65536):
        r = await admin_client.put("/api/admin/settings", json={"smtp_port": bad})
        assert r.status_code == 422
        assert r.json()["detail"] == "smtp_port phải trong khoảng 1–65535."
    r = await admin_client.put("/api/admin/settings", json={"smtp_port": 587})
    assert r.status_code == 200
    assert r.json()["smtp_port"] == {"value": 587, "source": "db"}

async def test_put_max_pages_and_upload_byte_limit_floors(admin_client):
    r = await admin_client.put("/api/admin/settings", json={"max_pages": 0})
    assert r.status_code == 422
    assert r.json()["detail"] == "max_pages phải từ 1 trở lên."
    r = await admin_client.put("/api/admin/settings", json={"max_pages": 50})
    assert r.json()["max_pages"] == {"value": 50, "source": "db"}
    r = await admin_client.put(
        "/api/admin/settings", json={"upload_byte_limit": 1_048_575}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "upload_byte_limit phải từ 1MB trở lên."
    r = await admin_client.put(
        "/api/admin/settings", json={"upload_byte_limit": 1_048_576}
    )
    assert r.json()["upload_byte_limit"] == {"value": 1048576, "source": "db"}

async def test_put_smtp_pass_write_only_mask(admin_client, db_session):
    r = await admin_client.put(
        "/api/admin/settings", json={"smtp_pass": "secret-pass-123"}
    )
    assert r.status_code == 200
    assert r.json()["smtp_pass"] == {"value": "sec…-123", "source": "db"}
    r = await admin_client.get("/api/admin/settings")
    assert r.json()["smtp_pass"]["value"] == "sec…-123"
    assert "secret-pass-123" not in r.text  # full secret never in a response
    row = await db_session.get(Setting, "smtp_pass")
    assert row is not None and row.value == "secret-pass-123"
    # empty PUT = keep (write-only form can't express "clear")
    r = await admin_client.put("/api/admin/settings", json={"smtp_pass": ""})
    assert r.json()["smtp_pass"]["value"] == "sec…-123"

async def test_put_quota_limit_floors_422(admin_client):
    """P2b: daily/weekly_page_limit floor ≥0 server-side (khớp list floor)."""
    for key in ("daily_page_limit", "weekly_page_limit"):
        r = await admin_client.put("/api/admin/settings", json={key: -5})
        assert r.status_code == 422
        assert r.json()["detail"] == f"{key} phải từ 0 trở lên."
    # 0 hợp lệ (vượt floor)
    r = await admin_client.put(
        "/api/admin/settings", json={"daily_page_limit": 0}
    )
    assert r.status_code == 200
    assert r.json()["daily_page_limit"] == {"value": 0, "source": "db"}

async def test_put_quota_and_ir_and_smtp_string_keys(admin_client):
    r = await admin_client.put(
        "/api/admin/settings",
        json={
            "daily_page_limit": 10,
            "weekly_page_limit": 50,
            "ir_llm_model": "oc/new-ir-model",
            "smtp_host": "smtp.example",
            "smtp_from": "noreply@example.com",
            "smtp_user": "bot",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["daily_page_limit"] == {"value": 10, "source": "db"}
    assert body["weekly_page_limit"] == {"value": 50, "source": "db"}
    assert body["ir_llm_model"] == {"value": "oc/new-ir-model", "source": "db"}
    assert body["smtp_host"] == {"value": "smtp.example", "source": "db"}
    assert body["smtp_from"] == {"value": "noreply@example.com", "source": "db"}
    assert body["smtp_user"] == {"value": "bot", "source": "db"}

async def test_llm_test_model_ok_500_timeout(admin_client, monkeypatch):
    """POST /api/admin/llm/test-model: probe 1 prompt \"ping\" (max_tokens 5),
    timeout 15s, KHÔNG persist → {ok, latency_ms, model, error}."""
    from app.routers import admin

    calls: list = []

    class Stub:
        def __init__(self, status=200, text="", exc=None):
            self.status_code, self.text, self._exc = status, text, exc

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            calls.append((url, kw))
            if self._exc:
                raise self._exc
            return self

    # 200 → ok
    monkeypatch.setattr(admin, "AsyncClient", lambda **kw: Stub(200))
    r = await admin_client.post(
        "/api/admin/llm/test-model",
        json={"model": "m1", "base_url": "http://llm.test/v1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["error"] is None
    assert body["model"] == "m1" and isinstance(body["latency_ms"], int)
    url, kw = calls[-1]
    assert url == "http://llm.test/v1/chat/completions"
    assert kw["json"]["max_tokens"] == 5
    assert kw["json"]["messages"] == [{"role": "user", "content": "ping"}]
    # timeout param fixed 15s (no persist: Setting rows unchanged)
    assert kw["timeout"] == 15

    # 500 → not ok + error carries status
    monkeypatch.setattr(admin, "AsyncClient", lambda **kw: Stub(500, "boom"))
    r = await admin_client.post(
        "/api/admin/llm/test-model", json={"model": "m1"}
    )
    body = r.json()
    assert body["ok"] is False and "HTTP 500" in body["error"]

    # timeout → not ok + error
    monkeypatch.setattr(
        admin,
        "AsyncClient",
        lambda **kw: Stub(exc=httpx.TimeoutException("timed out")),
    )
    r = await admin_client.post(
        "/api/admin/llm/test-model", json={"model": "m1"}
    )
    body = r.json()
    assert body["ok"] is False and "timeout" in body["error"].lower()

async def test_llm_test_model_bad_stored_base_url_200_not_ok(admin_client):
    """P1: stored base_url không parse được (port "abc") → contract 200 với
    ok=false (fallback except Exception), không 500."""
    r = await admin_client.put(
        "/api/admin/settings", json={"llm_base_url": "http://localhost:abc"}
    )
    assert r.status_code == 200
    r = await admin_client.post(
        "/api/admin/llm/test-model", json={"model": "m1"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["model"] == "m1"
    assert body["error"]  # có lý do, không im lặng

async def test_llm_test_model_no_persist_setting_count(admin_client, db_session, monkeypatch):
    """P2e: probe KHÔNG persist — số row Setting không đổi trước/sau."""
    from sqlalchemy import func

    from app.routers import admin

    class Stub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(admin, "AsyncClient", lambda **kw: Stub())
    await admin_client.put("/api/admin/settings", json={"llm_model": "m1"})

    async def _count():
        return (
            await db_session.execute(select(func.count()).select_from(Setting))
        ).scalar_one()

    before = await _count()
    r = await admin_client.post(
        "/api/admin/llm/test-model", json={"model": "m1"}
    )
    assert r.status_code == 200 and r.json()["ok"] is False
    assert await _count() == before

async def test_llm_test_model_anon_401(client):
    r = await client.post("/api/admin/llm/test-model", json={"model": "m"})
    assert r.status_code == 401

async def test_llm_test_model_non_admin_403(auth_client):
    r = await auth_client.post("/api/admin/llm/test-model", json={"model": "m"})
    assert r.status_code == 403

async def test_delete_setting_resets_to_env(admin_client, db_session):
    """Reset = xóa Setting row → GET trả về env default (source \"env\")."""
    r = await admin_client.put("/api/admin/settings", json={"max_pages": 42})
    assert r.json()["max_pages"]["source"] == "db"
    r = await admin_client.delete("/api/admin/settings/max_pages")
    assert r.status_code == 200
    assert r.json()["max_pages"] == {
        "value": settings.max_pages,
        "source": "env",
    }
    assert await db_session.get(Setting, "max_pages") is None
    # unknown / not-a-runtime-key → 404 (no silent no-op)
    r = await admin_client.delete("/api/admin/settings/kaggle_kernel_ref")
    assert r.status_code == 404

async def test_delete_setting_anon_401(client):
    r = await client.delete("/api/admin/settings/max_pages")
    assert r.status_code == 401

async def test_delete_setting_non_admin_403(auth_client):
    r = await auth_client.delete("/api/admin/settings/max_pages")
    assert r.status_code == 403

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
