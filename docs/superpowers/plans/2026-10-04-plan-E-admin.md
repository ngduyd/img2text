# Plan E — Admin: Users, Stats, Logs, Job Retry

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Admin surface — user list + OCR grant toggle, daily stats with GPU-cost estimate, request-log filtering + app-log tail, job retry endpoint (failed → queued).

**Architecture:** All queries on-the-fly `date_trunc` aggregates (no rollup tables — spec ceiling). `usd_per_gpu_hour` from `settings` table (default `"0.0"`). Log tail reads fixed `LOG_PATH` from settings — no user-controlled path (traversal impossible by construction).

**Tech Stack:** Plan A/B stack; SQLAlchemy `func.date_trunc`, JSONB casts.

**Spec:** §8 admin API + `usd_per_gpu_hour`, §4 settings/page_views, §9 stats, §10 admin UI backend data, §11.

**Depends on:** Plan B (Job model, worker protocol — retry reuses queue semantics), Plan A (`require_admin`, `request_logs`, `bootstrap_admin`).

## Global Constraints

- All `/api/admin/*` require `role="admin"` → else 403 `{"detail":"Forbidden."}`.
- `GET /api/admin/users?page=1&size=20` → `{"items":[{"id","email","role","ocr_enabled","created_at"}], "total"}`; `size` ≤100.
- `PATCH /api/admin/users/{id} {"ocr_enabled": bool}` → `200` full user JSON; non-bool → 422; unknown id → 404.
- `GET /api/admin/stats?from=YYYY-MM-DD&to=YYYY-MM-DD` → `{"days":[{"date","users_registered","jobs_submitted","jobs_done","jobs_failed","page_views","gpu_seconds","estimated_cost_usd"}]}`; dates inclusive; default window last 7 days; missing days zero-filled; `gpu_seconds = sum((result->>'gpu_seconds')::float)` over done jobs; `estimated_cost_usd = round(gpu_seconds/3600 * usd_per_gpu_hour, 4)`.
- `GET /api/admin/logs?status_class=&ip=&limit=` → `{"items":[request_logs rows newest first]}`; `status_class` ∈ `2xx|4xx|5xx`; `limit` ≤500 default 100.
- `GET /api/admin/logs/tail?lines=200` → `{"lines":[...str]}`; reads `settings.LOG_PATH` only; `lines` ≤500; missing file → `{"lines":[]}`.
- `POST /api/jobs/{id}/retry` (OWNER, not admin-only): `status=failed` → `queued` (error/worker_token/lease cleared, `started_at`/`finished_at` NULL) → `200 {"id","status"}`; else 409.
- TDD per task; commit per task.

## Review Focus

- Stats must not count other users' jobs (test seeds two users' data, admin sees totals — totals are global BY DESIGN; assert documented: stats are global, not per-user).
- Zero-fill: gap days between from/to must appear with zeros (test).
- Log tail: request with `lines=-5` or `lines=99999` clamped, never errors (test).
- Retry on `done` job → 409 (test: idempotent-ish guard, no re-queue).
- PATCH ocr_enabled=false on user with queued job: queued jobs remain (documented; test pins current behavior — job stays queued, worker can still claim; ponytail: revoke-on-disable upgrade).

---

### Task 1: Admin users list + PATCH toggle

**Files:**
- Create: `server/app/routers/admin.py`, `server/tests/test_admin_users.py`
- Modify: `server/app/main.py` (replace `__probe` route with real router; keep probe removed)

**Interfaces:**
- Consumes: `require_admin` (Plan A).
- Produces: router per Global Constraints; remove `GET /api/admin/__probe`.

- [ ] **Step 1: Failing tests** `server/tests/test_admin_users.py`:

```python
async def test_list_users(admin_client, seeded_users_5):
    r = await admin_client.get("/api/admin/users?page=1&size=2")
    assert r.status_code == 200 and len(r.json()["items"]) == 2 and r.json()["total"] == 6  # 5+admin

async def test_patch_ocr_enabled(admin_client, db_session):
    r = await admin_client.patch("/api/admin/users/2", json={"ocr_enabled": True})
    assert r.status_code == 200 and r.json()["ocr_enabled"] is True
    u = await db_session.get(User, 2); assert u.ocr_enabled is True

async def test_patch_422_non_bool(admin_client):
    r = await admin_client.patch("/api/admin/users/2", json={"ocr_enabled": "yes"})
    assert r.status_code == 422

async def test_patch_404_unknown(admin_client):
    assert (await admin_client.patch("/api/admin/users/9999", json={"ocr_enabled": True})).status_code == 404

async def test_admin_required_403(auth_client):
    assert (await auth_client.get("/api/admin/users")).status_code == 403
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces; `__probe` route deleted.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): admin user list + ocr grant`

---

### Task 2: Stats aggregates + settings-backed cost

**Files:**
- Create: `server/tests/test_admin_stats.py`
- Modify: `server/app/routers/admin.py`

**Interfaces:**
- Consumes: `Job`, `User`, `PageView`, `Setting`.
- Produces: `GET /api/admin/stats` per Global Constraints; helper `get_usd_per_gpu_hour(session) -> float`.

- [ ] **Step 1: Failing tests** (seed: 2 done jobs gpu 3600s + 7200s, 1 failed, 3 users today, 4 page_views today, setting `usd_per_gpu_hour="2.5"`):

```python
async def test_stats_aggregates(admin_client, seeded_stats):
    r = await admin_client.get(f"/api/admin/stats?from={today()}&to={today()}")
    d = r.json()["days"][0]
    assert d["users_registered"] == 3
    assert d["jobs_submitted"] == 3 and d["jobs_done"] == 2 and d["jobs_failed"] == 1
    assert d["page_views"] == 4
    assert d["gpu_seconds"] == 10800.0
    assert d["estimated_cost_usd"] == 7.5      # 10800/3600 * 2.5

async def test_stats_zero_fill_gap(admin_client):
    r = await admin_client.get(f"/api/admin/stats?from={d(-2)}&to={d(0)}")
    days = r.json()["days"]
    assert len(days) == 3 and days[0]["jobs_submitted"] == 0 and days[0]["users_registered"] == 0

async def test_stats_default_window_7d(admin_client):
    r = await admin_client.get("/api/admin/stats")
    assert len(r.json()["days"]) == 7

async def test_stats_admin_only(auth_client):
    assert (await auth_client.get("/api/admin/stats")).status_code == 403
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces: three grouped queries + python zero-fill + cost multiply; `get_usd_per_gpu_hour` parses `Setting.value` float, default 0.0 on missing/bad.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): admin stats with gpu cost estimate`

---

### Task 3: Logs filter + tail

**Files:**
- Create: `server/tests/test_admin_logs.py`
- Modify: `server/app/routers/admin.py`

**Interfaces:**
- Produces: `GET /api/admin/logs` filter per Global Constraints; `GET /api/admin/logs/tail` reads `Path(settings.log_path)` — file path comes from Settings ONLY, request has no path input.

- [ ] **Step 1: Failing tests**:

```python
async def test_logs_filter_by_status_class_and_ip(admin_client, seeded_logs):  # 2x 200, 1x 401, 1x 500; ip variants
    r = await admin_client.get("/api/admin/logs?status_class=5xx")
    assert [x["status"] for x in r.json()["items"]] == [500]
    r = await admin_client.get(f"/api/admin/logs?ip=10.0.0.1")
    assert all(x["ip"] == "10.0.0.1" for x in r.json()["items"]) and r.json()["items"]

async def test_logs_limit_clamped(admin_client, seeded_logs):
    r = await admin_client.get("/api/admin/logs?limit=99999")
    assert len(r.json()["items"]) <= 500

async def test_tail_returns_last_lines(admin_client, tmp_settings_log):
    # conftest writes tmp LOG_PATH with 3 lines
    r = await admin_client.get("/api/admin/logs/tail?lines=2")
    assert len(r.json()["lines"]) == 2 and r.json()["lines"][-1] == "line3"

async def test_tail_missing_file_empty(admin_client, settings_log_missing):
    r = await admin_client.get("/api/admin/logs/tail")
    assert r.status_code == 200 and r.json()["lines"] == []

async def test_tail_no_path_param_ignores_traversal(admin_client, tmp_settings_log):
    r = await admin_client.get("/api/admin/logs/tail?lines=2&path=../../../etc/passwd")
    assert all("root:" not in ln for ln in r.json()["lines"])
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces (path param deliberately absent from signature).
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): admin log filter and safe tail`

---

### Task 4: Job retry endpoint

**Files:**
- Create: `server/tests/test_job_retry.py`
- Modify: `server/app/routers/jobs.py`

**Interfaces:**
- Produces: `POST /api/jobs/{id}/retry` (OWNER) → `200 {"id","status":"queued"}` iff `status=="failed"`; clears `error`, `worker_token`, `lease_expires_at`, `started_at`, `finished_at`; else 409; unknown → 404; other user → 403.

- [ ] **Step 1: Failing tests**:

```python
async def test_retry_failed_requeues(auth_client, failed_job, db_session):
    r = await auth_client.post(f"/api/jobs/{failed_job}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    job = await db_session.get(Job, failed_job)
    assert job.error is None and job.worker_token is None and job.started_at is None

async def test_retry_done_409(auth_client, done_job_with_result):
    assert (await auth_client.post(f"/api/jobs/{done_job_with_result}/retry")).status_code == 409

async def test_retry_other_user_403(other_client, failed_job):
    assert (await other_client.post(f"/api/jobs/{failed_job}/retry")).status_code == 403

async def test_retried_job_claimable(worker_client, failed_job):
    await auth_client.post(f"/api/jobs/{failed_job}/retry")   # auth_client = owner fixture
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200 and r.json()["job_id"] == failed_job
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): retry failed jobs`

---

**Plan E done when:** `pytest tests/test_admin_users.py tests/test_admin_stats.py tests/test_admin_logs.py tests/test_job_retry.py -v` green; full suite still green.
