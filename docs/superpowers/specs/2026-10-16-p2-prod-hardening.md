# P2 Prod Hardening Spec

**Date:** 2026-10-16
**Goal:** Remediate 5 P2 findings from deploy-readiness audit. Each finding maps to a concrete task with test criteria. P0 (8/8) + P1 (7/7) already done.

## Background

Deploy-readiness audit (20 findings): P0=8 done, P1=7 done, P2=5 open. This spec covers the 5 P2 items deferred from P1. All tasks are code changes except migration SQL (#16) and test gating (#20).

---

## Findings & Tasks

### #16. Worker Token Plaintext at Rest

**Files:**
- `server/app/core/models.py` — `Job.worker_token` (line 256)
- `server/app/routers/jobs.py` — `_issue_worker_token` (lines 542-554)
- `docs/migrations/2026-10-16_worker_token_hash.sql` — new migration

**Spec:**
- Migration: `ALTER TABLE jobs ADD COLUMN worker_token_hash TEXT;` + backfill `UPDATE jobs SET worker_token_hash = encode(digest(worker_token, 'sha256'), 'hex') WHERE worker_token IS NOT NULL;` + `ALTER TABLE jobs DROP COLUMN worker_token;`
- `Job.worker_token_hash: Mapped[str | None]` (Text, nullable).
- `_issue_worker_token`: generate token, store `sha256(token)` hash in DB, return plaintext token to caller (worker) once.
- Worker auth: hash incoming `worker_token` from `Authorization: Bearer`, compare hash. Plaintext token never stored.

**TDD Red→Green Steps:**
```python
# test_security.py
def test_worker_token_hash_matches():
    from app.core.security import hash_worker_token
    token = "test-token-123"
    assert hash_worker_token(token) == hashlib.sha256(token.encode()).hexdigest()

# test_worker_protocol.py
async def test_worker_auth_accepts_valid_token(client, job_with_token):
    resp = await client.post(
        f"/api/jobs/{job_with_token.id}/heartbeat",
        headers={"Authorization": f"Bearer {job_with_token.plaintext_token}"}
    )
    assert resp.status_code == 200

async def test_worker_auth_rejects_invalid_token(client, job_with_token):
    resp = await client.post(
        f"/api/jobs/{job_with_token.id}/heartbeat",
        headers={"Authorization": "Bearer wrong-token"}
    )
    assert resp.status_code == 401
```

**Expected New Tests:**
- `tests/test_security.py::test_worker_token_hash_matches`
- `tests/test_worker_protocol.py::test_worker_auth_accepts_valid_token`
- `tests/test_worker_protocol.py::test_worker_auth_rejects_invalid_token`

**Commit Message:** `feat(security): hash worker_token at rest; migrate plaintext column`

---

### #17. Session Revoke Endpoint

**Files:**
- `server/app/routers/auth.py` — add `POST /api/auth/session/revoke`
- `server/app/routers/admin.py` — add `POST /api/admin/users/{id}/revoke-sessions`

**Spec:**
- `POST /api/auth/session/revoke`: revoke all refresh tokens for current user (reuse `revoke_all_refresh`). Returns `204`.
- `POST /api/admin/users/{id}/revoke-sessions`: admin-only, revoke all refresh tokens for target user. Returns `204`. Audit log entry.
- Both endpoints require auth (access token). Admin endpoint requires `is_superuser`.

**TDD Red→Green Steps:**
```python
# test_auth.py
async def test_revoke_sessions_deletes_refresh_tokens(client, logged_in_user):
    # create refresh token
    await client.post("/api/auth/refresh", json={"refresh_token": valid_refresh})
    resp = await client.post("/api/auth/session/revoke", headers=auth_headers)
    assert resp.status_code == 204
    # verify refresh token no longer works
    resp2 = await client.post("/api/auth/refresh", json={"refresh_token": valid_refresh})
    assert resp2.status_code == 401

# test_admin.py
async def test_admin_revoke_sessions(client, admin_headers, target_user):
    resp = await client.post(f"/api/admin/users/{target_user.id}/revoke-sessions", headers=admin_headers)
    assert resp.status_code == 204
```

**Expected New Tests:**
- `tests/test_auth.py::test_revoke_sessions_deletes_refresh_tokens`
- `tests/test_admin.py::test_admin_revoke_sessions`

**Commit Message:** `feat(auth): add session revoke endpoint + admin revoke`

---

### #18. Request Logs Batch Insert

**Files:**
- `server/app/core/middleware.py` — `RequestLogsMiddleware` (lines 128-165)
- `server/app/services/scheduler.py` — add `flush_request_logs` job

**Spec:**
- Buffer `RequestLog` rows in-memory (list on `app.state`). Flush every 30s or when buffer reaches 100 rows.
- Scheduler job `flush-request-logs`: interval 30s, bulk insert buffered rows, clear buffer.
- On app shutdown: flush remaining buffer.
- Existing `prune_request_logs` unchanged (separate daily cleanup).

**TDD Red→Green Steps:**
```python
# test_logging_middleware.py
async def test_request_logs_buffered_not_written_immediately(client, db_session):
    initial = await db_session.scalar(select(func.count()).select_from(RequestLog))
    await client.get("/api/healthz")
    # not yet flushed (buffer only)
    after = await db_session.scalar(select(func.count()).select_from(RequestLog))
    assert after == initial  # still buffered

async def test_flush_job_writes_buffered_logs(client, db_session):
    await client.get("/api/healthz")
    await client.get("/api/healthz")
    await flush_request_logs(app)  # manual flush
    count = await db_session.scalar(select(func.count()).select_from(RequestLog))
    assert count >= 2
```

**Expected New Tests:**
- `tests/test_logging_middleware.py::test_request_logs_buffered_not_written_immediately`
- `tests/test_logging_middleware.py::test_flush_job_writes_buffered_logs`

**Commit Message:** `perf(logging): batch request_logs insert; flush every 30s`

---

### #19. Presigned URL Expiry / Artifact Link Rot

**Files:**
- `server/app/services/render_md.py` — `CROP_PRESIGN_EXPIRES` (line 584), `_serve_crops` (lines 635-640)
- `server/app/services/kaggle_orchestrator.py` — `INPUT_URL_EXPIRES_SECONDS` (line 59)

**Spec:**
- `CROP_PRESIGN_EXPIRES`: reduce 86400 (24h) → 3600 (1h). Markdown artifact embeds crop URLs; shorter window reduces stale-link window.
- `INPUT_URL_EXPIRES_SECONDS`: reduce 3600 → 900 (15min). Kernel fetches input quickly; shorter window reduces exposure.
- Both values configurable via settings (`crop_presign_expires`, `input_url_expires`).

**TDD Red→Green Steps:**
```python
# test_render_md.py
def test_crop_presign_expiry_reduced():
    assert settings.crop_presign_expires == 3600

# test_kaggle_orchestrator.py
async def test_input_url_expiry_reduced():
    # manifest input_url should expire in 900s
    manifest = await build_manifest(...)
    assert manifest["expires_in"] == 900
```

**Expected New Tests:**
- `tests/test_render_md.py::test_crop_presign_expiry_reduced`
- `tests/test_kaggle_orchestrator.py::test_input_url_expiry_reduced`

**Commit Message:** `chore(security): reduce presigned URL expiry windows`

---

### #20. Test Gating + Limiter Coverage

**Files:**
- `server/tests/conftest.py` — add `env` fixture, skip non-prod tests when `env != "prod"`
- `server/app/core/limiter.py` — add `rate_limit_feedback`, `rate_limit_upload`
- `server/tests/test_limiter.py` — new test file

**Spec:**
- `conftest.py`: add `prod_only` marker; skip tests marked `prod_only` when `settings.env != "prod"`.
- `limiter.py`: add `rate_limit_feedback` (10/min per user), `rate_limit_upload` (30/hour per user).
- `test_limiter.py`: test each limiter returns 429 when exceeded, passes when under limit.

**TDD Red→Green Steps:**
```python
# test_limiter.py
async def test_rate_limit_feedback_exceeded(client, logged_in_user):
    for _ in range(11):
        resp = await client.post("/api/feedback", json={"text": "test"})
    assert resp.status_code == 429

async def test_rate_limit_upload_exceeded(client, logged_in_user):
    for _ in range(31):
        resp = await client.post("/api/jobs", json={...})
    assert resp.status_code == 429

async def test_rate_limit_passes_under_limit(client, logged_in_user):
    resp = await client.post("/api/feedback", json={"text": "test"})
    assert resp.status_code != 429
```

**Expected New Tests:**
- `tests/test_limiter.py::test_rate_limit_feedback_exceeded`
- `tests/test_limiter.py::test_rate_limit_upload_exceeded`
- `tests/test_limiter.py::test_rate_limit_passes_under_limit`

**Commit Message:** `feat(limiter): add feedback + upload rate limits; test gating`

---

## Acceptance Criteria (AC) Map

| AC | Finding | Task | Files Changed |
|----|---------|------|---------------|
| AC1 | #16 | Worker token hashed at rest; migration SQL | `models.py`, `jobs.py`, `docs/migrations/2026-10-16_worker_token_hash.sql` |
| AC2 | #17 | Session revoke endpoint + admin revoke | `auth.py`, `admin.py` |
| AC3 | #18 | Request logs batch insert; 30s flush | `middleware.py`, `scheduler.py` |
| AC4 | #19 | Presigned URL expiry reduced (crop 1h, input 15min) | `render_md.py`, `kaggle_orchestrator.py` |
| AC5 | #20 | Feedback + upload rate limits; test gating | `limiter.py`, `conftest.py`, `test_limiter.py` |

---

## Architecture

- **Hash-at-rest**: Worker tokens stored as SHA-256 hashes; plaintext returned once to worker, never persisted.
- **Session lifecycle**: User-initiated + admin-initiated revoke; reuses `revoke_all_refresh` helper.
- **Log batching**: In-memory buffer + scheduler flush; reduces DB write pressure.
- **URL expiry**: Configurable windows; shorter = less exposure.
- **Rate limiting**: Per-user sliding windows for feedback + upload endpoints.

## Tech Stack

- FastAPI + SQLAlchemy async (hash, batch insert)
- Alembic (migration)
- APScheduler (flush job)
- pytest + monkeypatch (limiter tests)
