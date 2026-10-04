# Plan B — R2 Storage + Upload + Job Queue API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** S3/R2 storage driver, multipart upload with validation (type/size/page count), job CRUD for owners, worker protocol (`next`/`heartbeat`/`result`/`fail`) with lease, requeue reaper, presigned file access, upload daily limit.

**Architecture:** boto3 S3Driver pointed at R2 via env (tests run against moto in-process S3). Jobs table + `FOR UPDATE SKIP LOCKED` claiming. Worker auth: static `RUNNER_KEY` for `next`; per-job `worker_token` for everything else. Lease 45 min, heartbeat +45 min, reaper re-queues expired leases.

**Tech Stack:** Plan A stack + `boto3`, `moto[server]` (tests), `pypdf`, `python-multipart`.

**Spec:** §4 (jobs table, result JSONB), §5 (R2 keys/presign TTLs), §6 (queue & lease), §8 (API), §9 (limits), §11 (R2 env).

**Depends on:** Plan A (create_app, deps, models, scheduler import hook).

## Global Constraints

- `storage_key` format: `uploads/{sha256_hex}.{ext}` — content-addressed, lowercase hex.
- Presign TTLs: worker download 1h, original preview 1h (crop/export TTLs in Plan D: 24h).
- Upload limits: 50 MB, types jpg/jpeg/png/webp/pdf, pdf pages ≤50 via `pypdf.PdfReader`, >50 → 422 with Vietnamese message `File PDF quá 50 trang.`; image pages=1.
- Upload requires `ocr_enabled=true` → else 403 `{detail:"Chưa được cấp quyền OCR."}`.
- Upload per-user limit: 20 jobs/day (in-process counter, same caveat as auth limiter) → 429.
- `GET /api/jobs/next`: 204 no body when empty; sets `status=running`, `lease_expires_at=now+45min`, `worker_token=secrets.token_urlsafe(32)`; returns `{"job_id","worker_token","file_url","file_type","page_count"}`.
- `result` accepted only when `status=running` AND lease valid → else `409`. Body validated against JSONB shape (§4 result schema; verdict enum: `ok|image_unextractable|unreadable|low_confidence`) → 422 on invalid.
- `fail` stores sanitized error (max 500 chars). `file`/`jobs`/`jobs/{id}` owner-or-admin only.
- Dedupe: same content uploaded twice → new job row referencing existing storage_key; storage.put skipped when exists.
- TDD: failing test → red → implement → green → commit. Test client factory from Plan A conftest extended with `auth_client` (registered+logged-in user) and `admin_client` fixtures.

## Review Focus

- Concurrent claim: two simultaneous `next` calls must not return the same job (test with two parallel ASGI clients + asyncio.gather).
- Lease expiry path: running job with expired lease must be re-queued by reaper and claimable again (test).
- Oversized/malformed PDF rejected before any storage write (test: storage.put never called — spy).
- `result` for non-running job (already done/failed) → 409, result not overwritten (test).
- Presigned URL for another user's job → 403 (test).

---

### Task 1: Job model + settings + S3Driver (moto)

**Files:**
- Create: `server/app/models.py` additions `Job`, `server/app/storage.py`, `server/tests/test_storage.py`
- Modify: `server/tests/test_models.py` (extend: create Job row)

**Interfaces:**
- Produces: `Job(id:int, user_id:FK, status:str default "queued", storage_key:str, file_type:str, page_count:int, result:JSONB|None, error:str|None, worker_token:str|None, lease_expires_at:datetime|None, created_at, started_at:datetime|None, finished_at:datetime|None)`; `StorageDriver` protocol: `put(key:str, data:bytes)->None`, `presign_get(key:str, expires:int)->str`, `exists(key:str)->bool`, `delete_prefix(prefix:str)->None`; `S3Driver(endpoint, key_id, secret, bucket, region)`; `get_storage()->StorageDriver` (app.state.storage, injectable in tests).

- [ ] **Step 1: Failing test** `server/tests/test_storage.py` (moto mock_s3 fixture creates bucket):

```python
async def test_put_exists_presign_delete(storage):   # storage fixture = S3Driver on moto
    await storage.put("uploads/abc.jpg", b"img")
    assert await storage.exists("uploads/abc.jpg")
    url = await storage.presign_get("uploads/abc.jpg", expires=3600)
    assert "uploads/abc.jpg" in url and "X-Amz-Expires=3600" in url
    await storage.delete_prefix("uploads/")
    assert not await storage.exists("uploads/abc.jpg")
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** Job model + storage.py: boto3 client `endpoint_url=settings.r2_endpoint`; `presign_get` = `generate_presigned_url("get_object", Params={"Bucket","Key"}, ExpiresIn)`; all methods `asyncio.to_thread`. `put` no-op if exists.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): jobs model + S3/R2 storage driver`

---

### Task 2: Upload endpoint (validation + sha256 + job create)

**Files:**
- Create: `server/app/routers/jobs.py`, `server/tests/test_upload.py`
- Modify: `server/app/main.py`, `server/app/limiter.py` (add `daily_counter`)

**Interfaces:**
- Produces: `POST /api/jobs` (multipart field `file`) → `201 {"id","status","page_count","file_type"}`. Order: auth → ocr_enabled → daily 20 → type ∈ {jpg,jpeg,png,webp,pdf} → size ≤50MB → pypdf page_count (pdf) → sha256 stream → storage.put (skip if exists) → Job row `queued`. Failures: `422` type `415`? No — keep spec: bad type/size/pages = 422 with `{"detail": "<vi message>"}`.

- [ ] **Step 1: Failing tests** `server/tests/test_upload.py` (jpeg bytes via PIL; pdf via `pypdf` writer 3 pages):

```python
async def test_upload_image_201(auth_client, storage_spy):
    r = await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    assert r.status_code == 201 and r.json()["page_count"] == 1 and r.json()["file_type"] == "image"

async def test_upload_pdf_3_pages(auth_client):
    r = await auth_client.post("/api/jobs", files={"file": ("a.pdf", TEST_PDF_3, "application/pdf")})
    assert r.json()["page_count"] == 3

async def test_upload_pdf_51_pages_422_no_storage(auth_client, storage_spy):
    r = await auth_client.post("/api/jobs", files={"file": ("big.pdf", TEST_PDF_51, "application/pdf")})
    assert r.status_code == 422 and "50 trang" in r.json()["detail"]
    assert storage_spy.put.call_count == 0

async def test_upload_bad_type_422(auth_client):
    r = await auth_client.post("/api/jobs", files={"file": ("a.gif", b"RIFF", "image/gif")})
    assert r.status_code == 422

async def test_upload_requires_ocr_enabled(client):
    await client.post("/api/auth/register", json={"email":"e@x.io","password":"secret123"})
    r = await client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    assert r.status_code == 403

async def test_upload_daily_limit_429(auth_client):
    for _ in range(20):
        await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    r = await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    assert r.status_code == 429

async def test_dedupe_same_content(auth_client, db_session):
    r1 = await auth_client.post("/api/jobs", files={"file": ("a.jpg", TEST_JPEG, "image/jpeg")})
    r2 = await auth_client.post("/api/jobs", files={"file": ("b.jpg", TEST_JPEG, "image/jpeg")})
    j1 = await db_session.get(Job, r1.json()["id"]); j2 = await db_session.get(Job, r2.json()["id"])
    assert j1.storage_key == j2.storage_key and j1.id != j2.id
```

(conftest adds: `auth_client` = register+login fixture; `ocr_enabled` toggled directly via db_session update; `storage_spy` wraps real driver with `AsyncMock(wraps)`.)

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** jobs.py router per Interfaces; limiter `DailyCounter(limit=20, key=f"upload:{user_id}")`; hash = sha256 while streaming `UploadFile.read(1MB)` chunks to temp file then storage.put.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): upload endpoint with validation and dedupe`

---

### Task 3: List / detail / file presign

**Files:**
- Create: `server/tests/test_jobs_read.py`
- Modify: `server/app/routers/jobs.py`

**Interfaces:**
- Produces: `GET /api/jobs` → my jobs desc: `{"items":[{"id","status","page_count","file_type","created_at","error"}], "total"}`; `GET /api/jobs/{id}` → detail incl. `result` when done, owner-or-admin, else 403/404; `GET /api/jobs/{id}/file` → `{"url"}` presigned 3600s, owner-or-admin.

- [ ] **Step 1: Failing tests**:

```python
async def test_list_only_mine(auth_client, other_client, seed_two_jobs):
    r = await auth_client.get("/api/jobs")
    assert all(j["id"] in seed_two_jobs["mine"] for j in r.json()["items"])

async def test_detail_owner_ok(auth_client, seed_job):
    r = await auth_client.get(f"/api/jobs/{seed_job}")
    assert r.status_code == 200 and r.json()["status"] == "queued"

async def test_detail_other_user_403(auth_client, other_client, seed_job):
    assert (await other_client.get(f"/api/jobs/{seed_job}")).status_code == 403

async def test_file_presign_owner(auth_client, seed_job):
    r = await auth_client.get(f"/api/jobs/{seed_job}/file")
    assert r.status_code == 200 and "uploads/" in r.json()["url"]
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces. Admin check: `user.role == "admin"` bypasses ownership.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): job list/detail/presigned file`

---

### Task 4: Worker protocol (next / heartbeat / result / fail)

**Files:**
- Create: `server/tests/test_worker_protocol.py`
- Modify: `server/app/routers/jobs.py`

**Interfaces:**
- Produces: `GET /api/jobs/next` (Bearer RUNNER_KEY) → `204` | `{"job_id","worker_token","file_url","file_type","page_count"}`; `POST /api/jobs/{id}/heartbeat` (Bearer worker_token) → `200 {"lease_expires_at"}`, `401` bad token; `POST /api/jobs/{id}/result` (Bearer worker_token, JSONB body) → `200 {}`, `409` if not running/lease expired, `422` invalid shape; `POST /api/jobs/{id}/fail` (Bearer worker_token, `{"error"}`) → `200`. Wrong runner key on `/next` → `401`.

- [ ] **Step 1: Failing tests** `server/tests/test_worker_protocol.py`:

```python
async def test_next_claims_and_returns_payload(worker_client, seed_job):
    r = await worker_client.get("/api/jobs/next")
    assert r.status_code == 200
    b = r.json()
    assert b["job_id"] == seed_job and b["worker_token"] and "uploads/" in b["file_url"]

async def test_next_empty_204(worker_client):
    assert (await worker_client.get("/api/jobs/next")).status_code == 204

async def test_next_wrong_key_401(client_no_runner_key):
    assert (await client_no_runner_key.get("/api/jobs/next")).status_code == 401

async def test_concurrent_next_single_claim(worker_client, worker_client2, seed_job):
    rs = await asyncio.gather(worker_client.get("/api/jobs/next"),
                              worker_client2.get("/api/jobs/next"))
    claimed = [r for r in rs if r.status_code == 200]
    assert len(claimed) == 1 and sum(r.status_code == 204 for r in rs) == 1

async def test_heartbeat_extends(worker_client, seed_job):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    r = await worker_client.post(f"/api/jobs/{seed_job}/heartbeat",
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and "lease_expires_at" in r.json()

async def test_result_done(worker_client, db_session, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=VALID_RESULT_JSONB,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    job = await db_session.get(Job, seed_job)
    assert job.status == "done" and job.result["model_version"] and job.worker_token is None

async def test_result_409_when_not_running(worker_client, db_session, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    await worker_client.post(f"/api/jobs/{seed_job}/fail", json={"error": "boom"},
                             headers={"Authorization": f"Bearer {tok}"})
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=VALID_RESULT_JSONB,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 409

async def test_result_422_bad_verdict_enum(worker_client, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    bad = deepcopy(VALID_RESULT_JSONB); bad["pages"][0]["regions"][0]["verdict"] = "madeup"
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=bad,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422

async def test_result_409_lease_expired(worker_client, db_session, seed_job, VALID_RESULT_JSONB):
    claim = await worker_client.get("/api/jobs/next"); tok = claim.json()["worker_token"]
    job = await db_session.get(Job, seed_job)
    job.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    r = await worker_client.post(f"/api/jobs/{seed_job}/result", json=VALID_RESULT_JSONB,
                                 headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 409                       # expired lease ≠ runnable
    # requeue + reclaimable path covered in Task 5 (reaper)
```

`VALID_RESULT_JSONB` = conftest factory matching spec §4 shape (1 page, 2 regions: verdicts `ok` + `image_unextractable`, bbox present, `model_version="paddleocr-vl-1.5-0.9B"`, `gpu_seconds=12.5`, `markdown` string).

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** per Interfaces. Claim: `SELECT * FROM jobs WHERE status='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1` via `with_for_update(skip_locked=True)`. Result validation: pydantic models `ResultPage`, `RegionOut` (verdict `Literal["ok","image_unextractable","unreadable","low_confidence"]`), `ResultBody` — shared file `server/app/schemas.py`.
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): worker protocol with lease and validated results`

---

### Task 5: Reaper wiring + auth/worker client fixtures finalization

**Files:**
- Create: `server/app/jobs_requeue.py`, `server/tests/test_reaper_wiring.py`
- Modify: `server/app/scheduler.py` (Plan A placeholder → real import), `server/tests/conftest.py` (promote `worker_client` = headers Bearer settings.RUNNER_KEY)

**Interfaces:**
- Produces: `reap_leases(session)->int` (running + expired → queued, token NULL, lease NULL); scheduler job every 1min calls it.

- [ ] **Step 1: Failing test**:

```python
async def test_scheduler_job_registered(app):
    jobs = [j for j in app.state.scheduler.get_jobs() if j.id == "reap-leases"]
    assert len(jobs) == 1
```

- [ ] **Step 2: Run → FAIL** → **Step 3: Implement** jobs_requeue.py + scheduler registration (import now unconditionally).
- [ ] **Step 4: Run → PASS** → **Step 5: Commit** `feat(server): lease reaper scheduled`

---

**Plan B done when:** `pytest tests/test_storage.py tests/test_upload.py tests/test_jobs_read.py tests/test_worker_protocol.py tests/test_reaper_wiring.py -v` green; moto bucket fixture isolated per test.
