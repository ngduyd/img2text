# Kaggle Session Loop Worker — Redesign Spec

**Date:** 2026-10-16 (rev 2 — NEEDS-EDIT fixes applied)
**Goal:** Thay Kaggle batch-orchestrator spawn mỗi-lô (Plan K5, `kaggle_mode=batch`) bằng **session loop**: 1 kernel session active duy nhất, tự claim → OCR → upload → done lặp vô hạn trong giới hạn session Kaggle (~9h), model load **1 lần/session**. Auth **per-session Bearer key** (mỗi session 1 key random, hash-at-rest, hết hiệu lực khi session đóng). Server giữ watchdog/respawn/gap-guard; loop ổn → bỏ batch orchestrator path.

**Inputs đã đọc (rev 2, line grep-verified):** `kaggle_orchestrator.py` (K5 batch: `_batch_runs`/`_spawn_batch_run` L522/`_poll_batch_run` L807/`_ensure_batch_runs` L871, restart-adopt L888-902, `_revert_job_queued` L662, `_fail_job_extracting` L775 — cả 3 nằm ở **kaggle_orchestrator.py**, KHÔNG phải jobs.py), `jobs.py` (next_job L523, upload_limiter L306-308, worker gates L1331-1473: `_worker_job_or_401` L1331/`submit_result` L1399/`fail_job` L1442, cancel L1544), `models.py` (Job L175, `worker_token_hash` L258), `storage.py` (protocol L22 / `presign_put` L88), `admin.py` (`_kaggle_quota_payload` L364, kaggle_mode read-only pin L614-617), `config.py` (`kaggle_mode` L102 default "batch", validator L148-152 chỉ nhận batch|loop), `img2text_batch.py` (`_predict_pages_one_by_one` L99, todo-filter trong `_ocr_phase` ~L178-183, `normalize` L1019, `run_batch` L1125, venv/wheelhouse bootstrap ~L620-700, `VENV_DIR` L217), `test_migration_p2_worker_token.py` (checksum pattern), `2026-10-16-p2-prod-hardening.md`.

## Non-Goals

- KHÔNG đổi UI/client upload flow (presign PUT đã production).
- KHÔNG đổi per-job `worker_token_hash` (HTTP worker Colab-loop path giữ nguyên — tương thích cả 2 auth theo `kaggle_mode`).
- KHÔNG đổi spec §4 result schema; `adapt_batch_document` (orchestrator L297) tái sử dụng nguyên vẹn.
- KHÔNG thêm GPU-type mới, KHÔNG async kaggle package (giữ `asyncio.to_thread` wrappers).
- KHÔNG xóa batch path trong release này — coi như deprecated, bỏ khi loop ổn (AC11).

## Architecture

```
                    ┌──────────────────────────── server (uvicorn, 1 worker) ──┐
   queue queued ──▶ │ scheduler tick ─▶ ensure_worker ─▶ _ensure_sessions      │
                    │   guard: quota API OK + session rỗng + gap ≥ min_gap     │
                    │                                                          │
                    │ _spawn_session (mode="session"):                        │
                    │   key = secrets.token_urlsafe(32)                        │
                    │   stage kernel dir: img2text_session.py (KEY chèn       │
                    │     lúc push — pattern _sub_owner orchestrator L173,     │
                    │     placeholder __SESSION_KEY__) + kernel metadata       │
                    │   claim response (next_job, 200 JSON): session_id,       │
                    │     session_key, result_upload_url (presign PUT),       │
                    │     crop_upload_urls (presign PUT từng rid)             │
                    │   kernels_push ─▶ upsert worker_sessions(key_hash=      │
                    │     sha256(key), kernel_ref, closed_at NULL)            │
                    │                                                          │
                    │ _ensure_sessions tick:                                   │
                    │   poll kernels_status(kernel_ref)                        │
                    │     active   ─▶ nothing                                  │
                    │     complete ─▶ close_session (DELETE hash row NOW;     │
                    │                    jobs.session_id → NULL tự động qua    │
                    │                    FK ON DELETE SET NULL)               │
                    │     failed/  ─▶ revert claimed jobs (lease clear +      │
                    │     error/   ─▶  session_id NULL thủ công) +             │
                    │     died        fail extracting (partial-fail kept) +   │
                    │                  close + respawn nếu queue còn          │
                    │   age > 9h budget ─▶ close + respawn                     │
                    │   restart: extracting job.session_id còn sống + kernel  │
                    │     active ─▶ adopt (L888-902 pattern); kernel dead ─▶   │
                    │     dọn + revert + respawn                              │
                    └──────────────────────────────┬───────────────────────────┘
                                                   │  (1 kernel session, GPU)
                    ┌──────────────────────────────▼───────────────────────────┐
                    │ Kaggle kernel: img2text_session.py (kernel_type script)  │
                    │  bootstrap 1×/session (reuse img2text_batch.py venv       │
                    │  recipe ~L620-700) ─ FAIL → exit 90 (session-level,      │
                    │  server respawns)                                         │
                    │  loop:                                                      │
                    │   1. GET /api/jobs/next  (Bearer session_key) ─▶ 200     │
                    │      JSON {session_key, session_id, result_upload_url,   │
                    │      crop_upload_urls, server_flags:{quota_low}}         │
                    │      ─▶ queue rỗng: 200 {"empty": true} → exit 0          │
                    │      ─▶ quota_low=true → exit 0, server tự dừng spawn     │
                    │   2. download input (manifest/presign GET) + sha256      │
                    │   3. rasterize → precheck → preprocess (per-page resume:  │
                    │      ocr_raw json cache L1019, giữ nguyên)                │
                    │   4. OCR predict từng trang, SIGALRM watchdog giữ        │
                    │      (_predict_pages_one_by_one L99); model load 1×/session│
                    │   5. PUT result.json + crops → R2 (presigned PUT từ      │
                    │      claim) → POST /api/jobs/{id}/done (Bearer) → lặp     │
                    │   6. giữa các trang: GET /api/jobs/{id}/status ─▶ 200     │
                    │      JSON {status, error} — cancelled → abort, giữ        │
                    │      partial, sang job sau                               │
                    │   7. per-job OCR error (run_batch L1125 catch pattern) →  │
                    │      POST /api/jobs/{id}/fail (Bearer, gpu_seconds) → lặp│
                    │   8. session budget < ~30min còn lại → exit 0 trước 9h     │
                    └───────────────────────────────────────────────────────────┘
```

## Tasks

Mọi task: **TDD red→green** (viết test fail trước → code → green), chạy `pytest server/tests/...` trên test DB share (conftest fixtures sẵn có — mỗi file test mới chia fixture chung, ≤3 file test, không weaken assertion nào).

### T1. `docs/migrations/2026-10-16_worker_sessions.sql` — bảng + cột mới (checksum pattern)

File mới. Idempotent (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / DO block):

```sql
CREATE TABLE IF NOT EXISTS worker_sessions (
  id BIGSERIAL PRIMARY KEY,
  kernel_ref TEXT NOT NULL,
  key_hash TEXT NOT NULL,             -- sha256(session_key) — hash-at-rest (P2 #16 pattern)
  spawned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ NULL,
  exit_code INT NULL,                 -- 0=graceful, 90=session-level fail
  gpu_seconds_reported DOUBLE PRECISION NOT NULL DEFAULT 0  -- writer: T4 (done/failed payload)
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS session_id BIGINT
  REFERENCES worker_sessions(id) ON DELETE SET NULL;  -- close session khi job còn trỏ → session_id tự NULL, KHÔNG FK vi phạm
CREATE INDEX IF NOT EXISTS ix_jobs_session ON jobs (session_id) WHERE session_id IS NOT NULL;
```

**Test mới** `server/tests/test_migration_worker_sessions.py` (pattern `test_migration_p2_worker_token.py`):
- `test_migration_checksum_unchanged` — sha256(file) pin `CHECKSUM` (giá trị thật lấy sau khi viết SQL).
- `test_migration_idempotent_and_link` — apply 2 lần không lỗi; `jobs.session_id` insert được trỏ hàng `worker_sessions`; **xóa session row khi job còn trỏ → job.session_id tự NULL, job KHÔNG mất** (ON DELETE SET NULL assert).

### T2. `server/app/core/models.py` — `WorkerSession` model

Sau `Job` (L175), cạnh `WorkerHeartbeat` (cuối file). Mirror SQL T1 (`__tablename__ = "worker_sessions"`, fields: id, kernel_ref, key_hash, spawned_at, closed_at, exit_code, gpu_seconds_reported). `Job.session_id: Mapped[int | None]` nullable (BigInteger), FK `worker_sessions(id)` **ON DELETE SET NULL** (không cascade — job thuộc owner). Ghi chú ALTER-only như các cột wave-5.

### T3. `server/app/core/deps.py` — `get_session_key`

Sau `get_runner_key` (L58). Bearer = plaintext session key; lookup `WorkerSession` WHERE `key_hash = hash_worker_token(key)` (security.py L45) AND `closed_at IS NULL`; **mọi lỗi (thiếu header/sai scheme/key lạ/session đóng) → cùng 1 detail rỗng**: `401 "bad session key"` (anti-oracle — không phân biệt nguyên nhân). Non-ascii key → 401 (tránh compare_digest TypeError 500, pattern deps.py L63). Rate-limit per-IP: in-process `DailyCounter` (pattern jobs.py upload_limiter L306-308, single-worker assumption ghi chú) — key `session-auth:{ip}`, e.g. 60/min → vượt → 429; floor sống trong constant, không runtime setting (không cần admin toggle).

**Test mới** `server/tests/test_session_auth.py`:
- `test_session_key_accepts_live` — Bearer session_key hợp lệ → 200 trên worker route.
- `test_session_key_rejects_unknown_and_closed` — key random → 401 detail đúng chuẩn; session đóng (closed_at set) → 401 cùng detail.
- `test_session_key_rate_limit_per_ip` — >60 req/min/cùng IP → 429; IP khác vẫn 200.
- `test_runner_key_still_works` — `get_runner_key` path cũ không regress.

### T4. `server/app/routers/jobs.py` — session claim + upload + status + gpu_seconds writer

- `next_job` (L523): khi `kaggle_mode == "session"` → claim job cũ (FOR UPDATE SKIP LOCKED), nhưng worker token = session scope: kiểm tra live session (spawned, `closed_at IS NULL`, kernel còn active); gán `job.session_id = session.id`. Claim response = **200 JSON** (KHÔNG dùng 204 — worker cần body):
  ```json
  {"job_id": N, "session_key": "<plaintext, 1 lần>", "session_id": S,
   "result_upload_url": "<presign PUT jobs/{N}/_result.json>",
   "crop_upload_urls": {"<rid>": "<presign PUT jobs/{N}/crops/<rid>.png>", ...},
   "server_flags": {"quota_low": false}}
  ```
  Crop URLs: 1 presign PUT **theo rid** (chốt — không wildcard); worker request rid list theo pages có image block, server presign từng URL trả về. Queue rỗng → `200 {"empty": true}` (exit 0). `quota_low=true` → exit 0, server dừng spawn. (HTTP worker Colab-loop cũ vẫn nhận 204 tương thích.)
  - Session-level giữ `worker_token_hash = NULL` (rider guards orchestrator L662/L775 hoạt động: batch path không clobber session claims — và ngược lại; thêm `Job.session_id.is_(None)` vào mọi batch rider guard).
- Route mới `GET /api/jobs/{id}/status` (auth `get_session_key` — KHÔNG dùng cookie owner): **200 JSON `{status, error}`** — worker poll giữa các trang (cancel check, AC7). Job không thuộc session đang auth → 401 rỗng (anti-oracle giữ).
- `submit_result` (L1399) / `fail_job` (L1442): khi job có `session_id` → xác thực bằng **session key** (lookup qua session) thay per-job token hash; guard 409-first giữ (R14); atomic conditional UPDATE thêm `Job.session_id` re-check. Body thêm optional `gpu_seconds` (float) — backend ghi vào `worker_sessions.gpu_seconds_reported` (UPSERT +`=` — last-writer-wins, job cuối báo cập nhật session) **trước khi job done**; thiếu field → 0.0 (writer bắt buộc có trong schema). Job không session_id → đường per-job token cũ nguyên vẹn.
- Idempotency (AC8): done/failed gửi lại → conditional UPDATE `status=='extracting'` trả rowcount 0 → **200 no-op** (không 409) khi job ở terminal `done`/`failed` cùng session; 409 chỉ khi lease hết/claim khác.

**Test mới** `server/tests/test_session_protocol.py` (share client/db_session fixtures):
- `test_claim_returns_200_session_key_and_upload_urls` — Bearer runner key, job queued → **200** (không 204) có `session_key`, `result_upload_url` jobs/{id}/_result.json, `crop_upload_urls` dict; DB chỉ có `worker_sessions.key_hash = sha256(session_key)` (assert plaintext KHÔNG nằm trong row text).
- `test_empty_queue_returns_200_empty_flag` — không job → `200 {"empty": true}`.
- `test_done_upload_then_result_writes_gpu_seconds` — worker PUT bytes lên presign URL (moto) → POST /result (Bearer session_key, `gpu_seconds: 42.5`) → job done, `store_worker_result` gọi (giữ service path), `worker_sessions.gpu_seconds_reported == 42.5`.
- `test_done_idempotent_replay` — POST /result lần 2 (cùng body) → 200, không thay đổi result, không 409.
- `test_cancel_between_pages_via_status` — owner POST /cancel; worker GET /status (session key) → 200 `{"status": "cancelled"}`; worker dừng; job terminal cancelled.
- `test_status_route_rejects_other_session` — Bearer key session B đọc job của session A → 401 rỗng.

### T5. `server/app/services/storage.py` — giữ nguyên

`presign_put` (L88, protocol L22) đủ dùng: claim cấp presigned PUT `{job_id}_result.json` + từng crop theo rid (T4). KHÔNG sửa driver. (P2 #19 presign expiry 3600 đã green.)

### T6. `server/app/services/kaggle_orchestrator.py` — mode "session"

- `ensure_worker` (L991): nhánh `mode == "session"` → `_ensure_sessions` (thay `_ensure_batch_runs` L871). Guard dispatch (AC1): `kaggle_enabled` + quota API còn (AC6) + không session active (`_sessions` map + DB live check) + gap `_last_spawn` + queue ≥ min_queue. **1 session active** tuyệt đối (shared input slug rationale giữ).
- Quota check trước dispatch (AC6): helper `_kaggle_quota_remaining()` — tách từ `admin._kaggle_quota_payload` (admin.py L364, import helper chung, không duplicate field-mapping): `api.quota_view()` → `gpuQuota.timeUsed/totalTimeAllowed` → `remaining_s`. `remaining_s < settings.kaggle_session_min_quota_s` (default e.g. 7200) → skip spawn + log + claim response `quota_low=true`. (Admin card giữ nguyên.)
- `_spawn_session` (thay `_spawn_batch_run` L522 cho mode session):
  1. `key = secrets.token_urlsafe(32)`; hash `hash_worker_token(key)` (security.py L45).
  2. stage kernel dir (pattern `_stage_kernel` L187): copy `kernel/img2text_session.py` + `kernel/kernel-session-metadata.json`; `_sub_owner(meta, owner)` (L173) **+ sub `__SESSION_KEY__` → key** (placeholder trong script; kernel-metadata không chứa key — push = upload folder nên key chỉ vào code file).
  3. `kernels_push`; upsert `worker_sessions(key_hash, kernel_ref, closed_at NULL)`; jobs claim lần đầu sẽ trỏ `session_id` qua next_job (T4) — KHÔNG cần UPDATE extracting ở spawn (khác batch path).
  4. `_last_spawn = now` (gap guard), heartbeat marker `kaggle-session` (pattern `_touch_batch_heartbeat` L251).
- `_poll_session` (thay `_poll_batch_run` L807): `kernels_status(kernel_ref)`:
  - active → return.
  - complete/failed/error/cancelled → `_close_session`: DELETE `worker_sessions` row (xóa hash NGAY — AC3/AC9; FK ON DELETE SET NULL tự null jobs.session_id, **job không mất**); extracting jobs còn trỏ → `_revert_job_queued` (L662, rider guard thêm `session_id` check) hoặc `_fail_job_extracting` (L775, partial-fail) — **cả 2 đều set `session_id = NULL`** (thủ công + tự động qua FK — không được để job treo trỏ session đã xóa); respawn nếu queue còn.
  - age > `kaggle_session_max_age_s` (default 9h trừ margin 30min → exit trước limit Kaggle ~12h) → close + respawn.
- Restart recovery (AC9): extracting job `session_id NOT NULL`, session row `closed_at IS NULL`, kernel `kernels_status` active → adopt (merge vào `_sessions`, pattern adopt L888-902); kernel dead → `_close_session` + revert claimed (lease clear + session_id NULL) + respawn nếu queue còn.
- Failure taxonomy (AC10): kernel `failed`/`error` → **fail từng job đang extracting của session** (`_fail_job_extracting` L775, rider `session_id`) + close session + respawn; venv/import fail do kernel tự exit 90 (T7) → complete không có result → cùng nhánh per-job fail; exit code 90 best-effort ghi qua `kernels_output` log marker `[session] exit 90` → `worker_sessions.exit_code` (telemetry).

**Test mới** `server/tests/test_kaggle_session_orchestrator.py` (fake api object inject — pattern test K5 hiện có):
- `test_spawn_session_stores_hash_not_plaintext` — `_spawn_session` với fake `api` → `worker_sessions.key_hash == sha256(key)`, file text không chứa key; kernel-metadata không chứa key; script chứa key (đọc staged file).
- `test_single_active_session_guard` — session live + queue ≥ min → không push thứ 2 (fake api đếm push calls).
- `test_quota_gate_blocks_spawn` — `quota_view` trả `timeUsed ≈ totalTimeAllowed` → ensure_worker False, không push; đủ quota → push.
- `test_dead_kernel_reverts_claimed_clears_session_id_and_respawns` — poll `kernels_status` → `failed` → job extracting (session_id set) → queued, lease NULL, **session_id NULL**, `worker_sessions` row xóa (hash mất).
- `test_close_session_with_live_job_sets_null` — close session khi job vẫn trỏ → job còn tồn tại, `session_id` NULL (ON DELETE SET NULL assert).
- `test_restart_adopts_live_session` — extracting job + session row còn + kernel active → `_ensure_sessions` adopt, không push mới.
- `test_session_exit_graceful_on_empty_queue` — poll complete + queue rỗng → session đóng, không respawn (AC5).

### T7. `deploy/kaggle/kernel/img2text_session.py` — loop kernel mới (thay notebook)

Script kernel (`kernel_type: script`), tái dùng toàn khối từ `img2text_batch.py` (chọn: stage cả 2 file, script import trực tiếp — giảm trùng code):

- `__SESSION_KEY__`/`__BASE_URL__` placeholder → giá trị thật lúc staged push (T6): session mode nhận `BASE_URL` qua orchestrator bake lúc push (KHÔNG cần Kaggle Secrets); Secrets chỉ còn cho path manual/push.py.
- Bootstrap 1×/session (reuse venv/wheelhouse ~L620-700) → fail → `sys.exit(90)` (session-level).
- Loop (AC2/AC5/AC7/AC10):
  1. `GET {BASE_URL}/api/jobs/next` Bearer key → **200 JSON** (T4 shape) — `{"empty": true}` hoặc `quota_low` → exit 0.
  2. download input (reuse `fetch_input` + sha256) → `preprocess_spec` từ claim.
  3. rasterize → precheck gate → preprocess → **per-page resume**: `ocr_raw` cache json (reuse `normalize` L1019 + todo-filter L178-183).
  4. OCR: model load **1×/session** (global singleton, lặp claim giữ pipeline) + SIGALRM watchdog per trang (`_predict_pages_one_by_one` L99).
  5. Build result JSON (doc shape {pages, blocks}) → PUT `result_upload_url` → từng crop PUT `crop_upload_urls[rid]` → `POST /api/jobs/{id}/done` (Bearer) → lặp.
  6. Giữa các trang: `GET /api/jobs/{id}/status` → **200 JSON {status, error}** — `cancelled` → dừng ngay, giữ partial, sang job sau.
  7. Per-job OCR error (reuse `run_batch` L1125 catch) → `POST /api/jobs/{id}/fail` (Bearer, gpu_seconds) → lặp.
  8. Session budget: monotonic clock — còn < 30min → exit 0 trước 9h; heartbeat `POST /api/worker/heartbeat {kind: "kaggle-session"}` mỗi 5 phút.
- Exit codes: 0 = graceful (queue rỗng/budget/quota_low), 1 = lỗi không phục hồi được, 90 = session-level bootstrap fail (venv/import) → server respawn.

**Test mới** `server/tests/test_session_kernel_contract.py` — import module (không bootstrap, pattern img2text_batch.py docstring "importing this module must stay cheap"):
- `test_session_kernel_import_parity` — `IMAGE_MARKER` parity với `app.core.schemas.IMAGE_MARKER`; `VL_MODEL` parity với orchestrator `BATCH_MODEL_VERSION`; exit code constants tồn tại.
- `test_session_kernel_loop_contract` (AC2, kernel harness): fake backend (monkeypatch HTTP) trả claim 1 job → worker xong job → fake next trả `{"empty": true}` → exit 0; **assert OCR pipeline/model constructor được gọi đúng 1 lần** (singleton giữa các claim), assert PUT result.json được gọi.
- `test_exit_code_90_session_level` (AC10): fake venv bootstrap fail (monkeypatch subprocess.run trả returncode≠0 giả lập lỗi import) → `SystemExit` code 90.

### T8. `server/app/routers/admin.py` + `server/app/services/kaggle_quota.py` — quota gate đọc chung

Tách `app/services/kaggle_quota.py`: `quota_remaining_seconds()` + `kaggle_quota_payload()`; admin.py `_kaggle_quota_payload` (L364) refactor gọi helper (giữ response shape/503/502 pins + kaggle_mode read-only pin L614-617 nguyên vẹn), orchestrator T6 dùng chung (AC6). Test parity: test admin quota cũ giữ green (response shape không đổi).

### T9. `server/app/core/config.py` — validator nhận "session" + batch path deprecated

- **T9a (BLOCKER fix):** `config.py` L148-152 `_kaggle_mode_values` chỉ nhận `("batch", "loop")` → flip default "session" = **startup fail** (pydantic ValidationError khi import settings). Sửa validator: `("batch", "loop", "session")`; cập nhật message. Default `kaggle_mode` (L102) → `"session"` (batch giữ code, rollback = flip env).
- **Test parity** `server/tests/test_config_kaggle_mode.py`: `kaggle_mode="session"` parse OK; `"bogus"` vẫn ValueError với message mới; default == "session".
- T9b: `deploy/kaggle/run_one.py` giữ làm **tool test tay** (README §6 cập nhật: loop mode production, run_one để smoke).
- T9c: Migration plan (ghi trong README/spec): khi session mode ổn ≥2 tuần production → task sau xóa `_ensure_batch_runs`/`_spawn_batch_run`/`_poll_batch_run` + `kaggle_batch_max_jobs`/`INPUT_SLUG` path + test tương ứng. **Không test cho T9b/T9c — checklist docs** (không thể assert code tồn tại bằng unit test mà không giả lập toàn K5 path).

## Acceptance Criteria (AC) Map — 11 yêu cầu đã chốt

| AC | Yêu cầu | Task | Evidence |
|----|---------|------|----------|
| AC1 | Dispatch: queued ≥1 + không session active + quota còn → spawn; guard 1 session | T6 | `test_single_active_session_guard`, `test_quota_gate_blocks_spawn` |
| AC2 | Loop kernel: claim→OCR→upload→done lặp; model load 1×/session; per-page resume + SIGALRM giữ; exit trước 9h | T7 | `test_session_kernel_loop_contract` (fake backend: 1 job rồi empty → exit 0, model ctor 1 lần), `test_session_kernel_import_parity`, orchestrator `kaggle_session_max_age_s` |
| AC3 | Per-session key: random lúc spawn, chèn lúc staged push (`_sub_owner` pattern), Bearer mọi request, sha256 vào `worker_sessions` (migration idempotent + checksum), key lạ/đóng → 401 rỗng + rate limit per-IP, đóng session xóa hash ngay | T1-T4, T6 | `test_migration_worker_sessions*`, `test_session_auth*`, `test_dead_kernel_reverts_claimed_clears_session_id_and_respawns` |
| AC3a | Close session thành công khi job còn trỏ (FK ON DELETE SET NULL) | T1, T6 | `test_close_session_with_live_job_sets_null`, `test_migration_worker_sessions` (re-run + link) |
| AC3b | Revert path clear `session_id` (không để job treo trỏ session đã xóa) | T6 | `test_dead_kernel_reverts_claimed_clears_session_id_and_respawns` (assert session_id NULL + row xóa) |
| AC4 | Claim cấp presign PUT `{job_id}_result.json` + từng crop URL; worker upload trực tiếp R2 → done → `store_worker_result` | T4-T5 | `test_claim_returns_200_session_key_and_upload_urls`, `test_done_upload_then_result_writes_gpu_seconds` |
| AC4a | `gpu_seconds` writer: done/failed payload → `worker_sessions.gpu_seconds_reported` | T4 | `test_done_upload_then_result_writes_gpu_seconds` (assert 42.5) |
| AC5 | Exit: queue rỗng (200 `{"empty": true}`) hoặc quota thấp → exit graceful → server dọn session + respawn nếu queue còn (gap-guard giữ) | T6-T7 | `test_session_exit_graceful_on_empty_queue`, kernel loop contract (empty → exit 0) |
| AC6 | Quota: worker báo gpu_seconds/job; backend đếm tuần; check quota API trước dispatch; dưới ngưỡng → dừng spawn | T6-T8 | `test_quota_gate_blocks_spawn` (admin card parity test cũ giữ) |
| AC7 | Cancel: worker hỏi status giữa các trang → cancelled → abort job, tiếp job sau | T4 | `test_cancel_between_pages_via_status` |
| AC8 | Idempotency: done/failed gửi lại → no-op (job_id + status check) | T4 | `test_done_idempotent_replay` |
| AC9 | Watchdog: `kernels_status` poll giữ (complete/failed → dọn; died → revert claimed qua lease — D1 pattern); restart: hash DB → adopt session sống / dọn + respawn | T6 | `test_dead_kernel_reverts_claimed_clears_session_id_and_respawns`, `test_restart_adopts_live_session` |
| AC10 | Failure taxonomy: per-job OCR error → failed + worker tiếp; session-level (venv/import) → exit code 90 → server respawn | T6-T7 | `test_exit_code_90_session_level`, kernel failed-poll test |
| AC11 | Batch mode: `run_one.py` giữ làm tool test tay; bỏ batch orchestrator path khi loop ổn — spec quyết + migration plan. **Không test — checklist docs** | T9 | `test_config_kaggle_mode` (T9a parity); T9b/T9c checklist trong README |

## Rollout / Migration

1. Apply T1 SQL lên dev/test/prod (idempotent — an toàn chạy 2 lần).
2. Deploy code với `KAGGLE_MODE=batch` (hiện tại) → flip `session` sau khi test green + smoke 1 job tay (`run_one.py` cũ vẫn độc lập).
3. Smoke: 1 job → verify session spawn, claim (200 JSON), upload, done, session card trong `/api/admin/workers` (`kaggle-session` marker), quota card đọc đúng.
4. Rollback = flip `KAGGLE_MODE=batch` (code batch còn nguyên). Forward-clean = T9c migration plan.

## Residual Risks

- Single uvicorn worker assumption (in-process `_last_spawn`, rate-limit counter) — multi-worker deploy cần DB-backed state (đã ghi chú sẵn trong code hiện tại; không đổi trong spec này).
- SIGALRM không interrupt native/CUDA hang (ponytail `_predict_pages_one_by_one` L99) — giữ nguyên, upgrade path subprocess watchdog.
- Session claim khi kernel đang boot (~1-2 phút venv): next_job không cấp job cho tới khi session đăng ký (spawn → session row → kernel sống mới claim được; job queued lại nếu kernel chết giữa chừng).
- `__SESSION_KEY__` nằm trong staged folder (push = upload) — exposure window = vòng đời session (đã giảm từ per-run presign pattern; hash-at-rest + xóa ngay khi đóng giảm rủi ro đáng kể).
- `gpu_seconds` last-writer-wires trên nhiều job cùng session — job cuối báo chiếm session-level metric (per-job vẫn nằm trong result JSON; session metric là aggregate best-effort).
