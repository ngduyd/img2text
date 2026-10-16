# Kaggle Session Loop Worker — Redesign Spec

**Date:** 2026-10-16
**Goal:** Thay Kaggle batch-orchestrator spawn mỗi-lô (Plan K5, `kaggle_mode=batch`) bằng **session loop**: 1 kernel session active duy nhất, tự claim → OCR → upload → done lặp vô hạn trong giới hạn session Kaggle (~9h), model load **1 lần/session**. Auth **per-session Bearer key** (mỗi session 1 key random, hash-at-rest, hết hiệc lực khi session đóng). Server giữ watchdog/respawn/gap-guard; loop ổn → bỏ batch orchestrator path.

**Inputs đã đọc:** `kaggle_orchestrator.py` (K5 batch: `_batch_runs`/`_spawn_batch_run`/`_poll_batch_run`/`_ensure_batch_runs` L871/L522/L807), `jobs.py` (next_job L523, worker gates L1331-1473, cancel L1534), `models.py` (Job L121, worker_token_hash L181), `storage.py` (presign_put đã có), `admin.py` (`_kaggle_quota_payload`, `kaggle_quota` card), `img2text_batch.py` (venv bootstrap, per-page resume, SIGALRM), `test_migration_p2_worker_token.py` (checksum pattern), `2026-10-16-p2-prod-hardening.md`.

## Non-Goals

- KHÔNG đổi UI/client upload flow (presign PUT đã production).
- KHÔNG đổi per-job `worker_token_hash` (HTTP worker Colab-loop path giữ nguyên — tương thích cả 2 auth theo `kaggle_mode`).
- KHÔNG đổi spec §4 result schema; `adapt_batch_document` (L297) tái sử dụng nguyên vẹn.
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
                    │     lúc push — pattern _sub_owner L173, placeholder     │
                    │     __SESSION_KEY__) + kernel-session-metadata.json     │
                    │   presign PUT {job_id}_result.json + crops/{rid}.png     │
                    │   kernels_push ─▶ upsert worker_sessions(key_hash=      │
                    │     sha256(key), kernel_ref, closed_at NULL)            │
                    │   claim response (next_job) trả: session_id +           │
                    │     session_key + result_upload_url                     │
                    │                                                          │
                    │ _ensure_sessions tick:                                   │
                    │   poll kernels_status(session kernel_ref)                │
                    │     active   ─▶ nothing                                  │
                    │     complete ─▶ close_session (DELETE hash row NOW)     │
                    │     failed/  ─▶ revert claimed jobs (lease clear) +     │
                    │     error/   ─▶ fail extracting (partial-fail kept) +   │
                    │     died        close + respawn nếu queue còn          │
                    │   age > 9h budget ─▶ close + respawn                     │
                    │   restart: extracting job.session_id còn sống + kernel  │
                    │     active ─▶ adopt; else dọn + respawn                  │
                    └──────────────────────────────┬───────────────────────────┘
                                                   │  (1 kernel session, GPU)
                    ┌──────────────────────────────▼───────────────────────────┐
                    │ Kaggle kernel: img2text_session.py (kernel_type script)  │
                    │  bootstrap 1×/session: venv py3.12 + wheelhouse (reuse    │
                    │  img2text_batch.py recipe) ─ FAIL → exit 90 (session-    │
                    │  level, server respawns)                                  │
                    │  loop:                                                      │
                    │   1. GET /api/jobs/next  (Bearer session_key)            │
                    │      204 + budget OK → exit 0 (graceful)                  │
                    │      204 + quota low  → exit 0, server tự dừng spawn      │
                    │   2. download input (manifest/presign GET) + sha256      │
                    │   3. rasterize → precheck → preprocess (per-page resume:  │
                    │      ocr_raw json cache, giữ nguyên)                      │
                    │   4. OCR predict từng trang, SIGALRM watchdog giữ        │
                    │      (BATCH_PAGE_TIMEOUT); model load 1×/session         │
                    │   5. PUT {job_id}_result.json + crops → R2 (presigned     │
                    │      PUT từ claim) — pixels khỏi kernel                  │
                    │   6. POST /api/jobs/{id}/done ─▶ lặp                     │
                    │      per-page: GET /api/jobs/{id}/status (session key)   │
                    │        cancelled → abort, giữ partial, sang job sau      │
                    │   session budget < ~30min còn lại → exit 0 trước 9h       │
                    └───────────────────────────────────────────────────────────┘
```

## Tasks

Mọi task: **TDD red→green** (viết test fail trước → code → green), chạy `pytest server/tests/...` trên test DB share (conftest fixtures sẵn có — mỗi file test mới chia fixture chung, ≤2-3 file test, không weaken assertion nào).

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
  gpu_seconds_reported DOUBLE PRECISION NOT NULL DEFAULT 0
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS session_id BIGINT REFERENCES worker_sessions(id);
CREATE INDEX IF NOT EXISTS ix_jobs_session ON jobs (session_id) WHERE session_id IS NOT NULL;
```

**Test mới** `server/tests/test_migration_worker_sessions.py` (pattern `test_migration_p2_worker_token.py`):
- `test_migration_checksum_unchanged` — sha256(file) pin `CHECKSUM` (giá trị thật lấy sau khi viết SQL).
- `test_migration_idempotent_and_link` — apply 2 lần không lỗi; `jobs.session_id` insert được trỏ hàng `worker_sessions`; xóa session row không xóa job (không cascade — job thuộc owner).

### T2. `server/app/core/models.py` — `WorkerSession` model

Sau `Job` (L121) hoặc cuối file cạnh `WorkerHeartbeat`. Mirror SQL T1 (`__tablename__ = "worker_sessions"`, fields: id, kernel_ref, key_hash, spawned_at, closed_at, exit_code, gpu_seconds_reported). `Job.session_id: Mapped[int | None]` nullable (Text/BigInteger), FK `worker_sessions.id` (no cascade). Ghi chú ALTER-only như các cột wave-5.

### T3. `server/app/core/deps.py` — `get_session_key`

Sau `get_runner_key` (L52). Bearer = plaintext session key; lookup `WorkerSession` WHERE `key_hash = hash_worker_token(key) AND closed_at IS NULL`; **mọi lỗi (thiếu header/sai scheme/key lạ/session đóng) → cùng 1 detail rỗng**: `401 "bad session key"` (anti-oracle — không phân biệt nguyên nhân). Non-ascii key → 401 (tránh compare_digest TypeError 500, pattern L56). Rate-limit per-IP: in-process `DailyCounter` (pattern `jobs.py` L301 upload_limiter, single-worker assumption ghi chú) — key `session-auth:{ip}`, e.g. 60/min → vượt → 429; floor sống trong constant, không runtime setting (không cần admin toggle).

**Test mới** `server/tests/test_session_auth.py`:
- `test_session_key_accepts_live` — Bearer session_key hợp lệ → 200 trên worker route.
- `test_session_key_rejects_unknown_and_closed` — key random → 401 detail đúng chuẗ; session đóng (closed_at set) → 401 cùng detail.
- `test_session_key_rate_limit_per_ip` — >60 req/min/cùng IP → 429; IP khác vẫn 200.
- `test_runner_key_still_works` — `get_runner_key` path cũ không regress.

### T4. `server/app/routers/jobs.py` — session claim + upload + status

- `next_job` (L523): khi `kaggle_mode == "session"` → claim job cũ (FOR UPDATE SKIP LOCKED), nhưng worker token = session scope: lấy/kiểm tra live session (spawned, `closed_at IS NULL`, kernel còn active — poll `_norm_status`); gán `job.session_id = session.id`; response thêm `session_id`, `session_key` (plaintext — chỉ 1 lần, claim response), `result_upload_url` = `storage.presign_put(f"jobs/{job_id}/_result.json", PRESIGN_EXPIRES_SECONDS)` + `result_upload_prefix = f"jobs/{job_id}/crops/"` (crop keys `{rid}.png` — presign PUT lẻ mỗi crop claim-response kèm, hoặc wildcard `Content-Range`? — chọn: presign PUT từng crop ngay khi worker done 1 job, claim response cấp sẵn `crop_upload_url(rid)` pattern — worker gọi `PUT /api/jobs/{id}/upload-url` (session auth) trả presign; đơn giản hơn: wildcard PUT `jobs/{job_id}/crops/*` không presign được → route trả URL theo rid).
  - Session-level giữ `worker_token_hash = NULL` (rider guards L662/L775/L1432 vẫn hoạt động: batch/HTTP paths không clobber session claims — và ngược lại; thêm `Job.session_id.is_(None)` vào mọi batch rider guard).
- Route mới `GET /api/jobs/{id}/status` (auth `get_session_key` — KHÔNG dùng cookie owner): trả `{status, error}` — worker poll giữa các trang (cancel check, AC7). Trả về status thô; 404 nếu job không thuộc session đang auth (anti-oracle giữ).
- `submit_result`/`fail_job` (L1389/L1432): khi job có `session_id` → xác thực bằng **session key** (lookup qua session) thay per-job token hash; guard 409-first giữ (R14); atomic conditional UPDATE thêm `Job.session_id` re-check. Job không session_id → đường per-job token cũ nguyên vẹn.
- Idempotency (AC8): done/failed gửi lại → conditional UPDATE `status=='extracting'` trả rowcount 0 → **200 no-op** (không 409) khi job ở terminal `done`/`failed` cùng session; 409 chỉ khi lease hết/claim khác.

**Test mới** `server/tests/test_session_protocol.py` (share client/db_session fixtures):
- `test_claim_returns_session_key_and_upload_url` — Bearer runner key, job queued → 200 có `session_key`, `result_upload_url` jobs/{id}/_result.json; DB chỉ có `worker_sessions.key_hash = sha256(session_key)` (assert plaintext KHÔNG nằm trong row text).
- `test_done_upload_then_result` — worker PUT bytes lên presign URL (moto) → POST /result (Bearer session_key) → job done, store_worker_result gọi (giữ `store_worker_result` service path).
- `test_done_idempotent_replay` — POST /result lần 2 (cùng body) → 200, không thay đổi result, không 409.
- `test_cancel_between_pages_via_status` — owner POST /cancel; worker GET /status (session key) → `cancelled`; worker dừng; job terminal cancelled.
- `test_status_route_rejects_other_session` — Bearer key session B đọc job của session A → 401 rỗng.

### T5. `server/app/services/storage.py` — presign_put crop wildcard không cần; giữ nguyên

`presign_put` (L100) đủ dùng: claim cấp presigned PUT `{job_id}_result.json` + route trả presign PUT crop theo rid. KHÔNG sửa driver. (P2 #19 presign expiry 3600 đã green.)

### T6. `server/app/services/kaggle_orchestrator.py` — mode "session"

- `ensure_worker` (L991): nhánh `mode == "session"` → `_ensure_sessions` (thay `_ensure_batch_runs` L871). Guard dispatch (AC1): `kaggle_enabled` + quota API còn (AC6) + không session active (`_batch_runs` analog: `_sessions` map + DB live check) + gap `_last_spawn` + queue ≥ min_queue. **1 session active** tuyệt đối (shared input slug rationale giữ).
- Quota check trước dispatch (AC6): helper `_kaggle_quota_remaining()` — tách từ `admin._kaggle_quota_payload` (admin.py L262, import helper chung, không duplicate field-mapping): `api.quota_view()` → `gpuQuota.timeUsed/totalTimeAllowed` → `remaining_s`. `remaining_s < settings.kaggle_session_min_quota_s` (default e.g. 7200 — đủ ≥1 job dài) → skip spawn + log. (Admin card giữ nguyên.)
- `_spawn_session` (thay `_spawn_batch_run` L522 cho mode session):
  1. `key = secrets.token_urlsafe(32)`; hash `hash_worker_token(key)` (security.py L37).
  2. stage kernel dir (pattern `_stage_kernel` L187): copy `kernel/img2text_session.py` + `kernel/kernel-session-metadata.json`; `_sub_owner(meta, owner)` (L173) **+ sub `__SESSION_KEY__` → key** (placeholder trong script/metadata; kernel-metadata không chứa key — chỉ code file — vì push = upload folder).
  3. `kernels_push`; upsert `worker_sessions(key_hash, kernel_ref, closed_at NULL)`; jobs claim lần đầu sẽ trỏ `session_id` qua next_job (T4) — KHÔNG cần UPDATE extracting ở spawn (khác batch path).
  4. `_last_spawn = now` (gap guard), heartbeat marker `kaggle-session` (pattern `_touch_batch_heartbeat` L251).
- `_poll_session` (thay `_poll_batch_run` L807): `kernels_status(kernel_ref)`:
  - active → return.
  - complete/failed/error/cancelled → `_close_session`: DELETE `worker_sessions` row (xóa hash NGAY — AC3/AC9); extracting jobs của session → revert qua `_revert_job_queued` (L662, rider guard thêm `session_id` check: job có session_id KHÔNG bị revert bởi batch path); respawn nếu queue còn.
  - age > `kaggle_session_max_age_s` (default 9h trừ margin 30min → exit trước limit Kaggle ~12h) → close + respawn.
- Restart recovery (AC9): extracting job `session_id NOT NULL`, session row `closed_at IS NULL`, kernel `kernels_status` active → adopt (merge vào `_sessions`, pattern L925-945); kernel dead → `_close_session` + revert claimed (lease clear) + respawn nếu queue còn.
- Failure taxonomy (AC10): kernel `failed`/`error` → **fail từng job đang extracting của session** (`_fail_job_extracting` L775 pattern, rider `session_id`) + close session + respawn; venv/import fail do kernel tự exit 90 (worker-side T7) → complete không có result → cùng nhánh per-job fail; exit 90 được báo qua `kernels_output` log marker `[session] exit 90` → orchestrator ghi `exit_code` (best-effort, telemetry).

**Test mới** `server/tests/test_kaggle_session_orchestrator.py` (fake api object inject — pattern test K5 hiện có):
- `test_spawn_session_stores_hash_not_plaintext` — `_spawn_session` với fake `api` → `worker_sessions.key_hash == sha256(key)`, file text không chứa key; kernel-metadata không chứa key; script chứa key (đọc staged file).
- `test_single_active_session_guard` — session live + queue ≥ min → không push thứ 2 (fake api đếm push calls).
- `test_quota_gate_blocks_spawn` — `quota_view` trả `timeUsed ≈ totalTimeAllowed` → ensure_worker False, không push; đủ quota → push.
- `test_dead_kernel_reverts_claimed_and_respawns` — poll `kernels_status` → `failed` → job extracting (session_id set) → queued, lease NULL, `worker_sessions` row xóa (hash mất).
- `test_restart_adopts_live_session` — extracting job + session row còn + kernel active → `_ensure_sessions` adopt, không push mới.
- `test_close_session_deletes_hash_immediately` — poll complete → SELECT key_hash → không tồn tại (worker cũ Bearer → 401 — assert qua T3 test).

### T7. `deploy/kaggle/kernel/img2text_session.py` — loop kernel mới (thay notebook)

Script kernel (`kernel_type: script`), tái dùng toàn khối từ `img2text_batch.py` (import trực tiếp được — chung dir, hoặc copy-flattened giống hiện tại — chọn **import từ chính file đó** khi stage cả 2 file; giảm trùng code):

- `__SESSION_KEY__` placeholder → key thật lúc staged (T6); đọc env `BASE_URL` (Secrets, README §2 giữ).
- Bootstrap 1×/session (reuse toàn bộ block venv/wheelhouse L620-700) → fail → `sys.exit(90)` (session-level).
- Loop (AC2/AC5/AC7/AC10):
  1. `GET {BASE_URL}/api/jobs/next` Bearer key → 204 → `GET /api/quota/me`-like budget check? Không — budget do server biết: next_job 204 + `server_flags: {quota_low: true}` (response header hoặc body JSON khi mode session) → exit 0. Plain 204 (HTTP worker cũ) → exit 0.
  2. claim payload → download input (reuse `fetch_input` + sha256) → `preprocess_spec` từ claim.
  3. rasterize → precheck gate → preprocess → **per-page resume**: `ocr_raw` cache json (reuse `normalize` + todo-filter L226 — claim job mới hoặc resume đều chạy đúng).
  4. OCR: model load **1×/session** (global singleton, lặp claim giữ pipeline) + SIGALRM watchdog per trang (giữ `_predict_pages_one_by_one` L205).
  5. Build result JSON (reuse `adapt`-side doc shape: `document` {pages, blocks} — build từ `pages_out`/`_page_md`) → PUT presigned `result_upload_url` → từng crop PUT presign (route T4) → `POST /api/jobs/{id}/done` (Bearer).
  6. Giữa các trang: `GET /api/jobs/{id}/status` (session key) → `cancelled` → dừng ngay, giữ partial, sang job sau (AC7).
  7. Per-job OCR error (reuse `run_batch` catch pattern L1128) → `POST /api/jobs/{id}/fail` (Bearer, error text) → lặp (AC10).
  8. Session budget: monotonic clock — còn < 30min → exit 0 trước 9h (AC2); heartbeat `POST /api/worker/heartbeat {kind: "kaggle-session"}` mỗi 5 phút (giữ marker).
- Exit codes: 0 = graceful (queue rỗng/budget), 1 = lỗi không phục hồi được, 90 = session-level bootstrap fail (venv/import) → server respawn.

**Test mới** `server/tests/test_session_kernel_import.py` — import module (không bootstrap, pattern `img2text_batch.py` docstring "importing this module must stay cheap"): assert `IMAGE_MARKER` parity + `VL_MODEL` parity với `adapt_batch_document.BATCH_MODEL_VERSION` + exit code constants tồn tại.

### T8. `server/app/routers/admin.py` — quota gate đọc chung

Thêm import helper quota từ orchestrator (hoặc tách `kaggle_quota.py` service mới — chọn tách nhỏ: `app/services/kaggle_quota.py` with `quota_remaining_seconds()` + `kaggle_quota_payload()`; admin L262 `_kaggle_quota_payload` refactor gọi helper (giữ response shape/503/502 pins), orchestrator T6 dùng chung (AC6). Test parity: test admin quota cŉ giữ green (response shape không đổi).

### T9. Batch path → deprecated (AC11)

- Spec quyết: `kaggle_mode` mặc định đổi `batch → `session`` trong `config.py` (env `KAGGLE_MODE` giữ override); batch code giữ nguyên (không xóa — rollback = flip setting).
- `deploy/kaggle/run_one.py` giữ làm **tool test tay** (README §6 cập nhật: loop mode production, run_one để smoke).
- Migration plan (ghi trong README/spec): khi session mode ổn ≥2 tuần production → task sau xóa `_ensure_batch_runs`/`_spawn_batch_run`/`_poll_batch_run` + `kaggle_batch_max_jobs`/`INPUT_SLUG` path + test tương ứng. Không làm trong spec này.
- `RuntimeSettingsPut.kaggle_mode` vẫn read-only (admin.py 422 pin) — đổi mode = restart, ghi chú rõ half-state risk đã xử lý (session rỗng + adopt path).

## Acceptance Criteria (AC) Map — 11 yêu cầu đã chốt

| AC | Yêu cầu | Task | Evidence |
|----|---------|------|----------|
| AC1 | Dispatch: queued ≥1 + không session active + quota còn → spawn; guard 1 session | T6 | `test_single_active_session_guard`, `test_quota_gate_blocks_spawn` |
| AC2 | Loop kernel: claim→OCR→upload→done lặp; model load 1×/session; per-page resume + SIGALRM giữ; exit trước 9h | T7 | `test_session_kernel_import` + orchestrator `kaggle_session_max_age_s` |
| AC3 | Per-session key: random lúc spawn, chèn lúc staged push (pattern `_sub_owner`), Bearer mọi request, sha256 vào `worker_sessions` (migration idempotent + checksum), key lạ/đóng → 401 rỗng + rate limit per-IP, đóng session xóa hash ngay | T1-T4, T6 | `test_migration_worker_sessions*`, `test_session_auth*`, `test_close_session_deletes_hash_immediately` |
| AC4 | Claim cấp presign PUT `{job_id}_result.json` + crops; worker upload trực tiếp R2 → done → `store_worker_result` | T4-T5 | `test_done_upload_then_result` |
| AC5 | Exit: queue rỗng (404/204 + budget OK) hoặc quota thấp → exit graceful → server dọn session + respawn nếu queue còn (gap-guard giữ) | T6-T7 | `test_...exit_graceful` + dead-kernel test |
| AC6 | Quota: worker báo gpu_seconds/job; backend đếm tuần; check quota API trước dispatch; dưới ngưỡng → dừng spawn | T6-T8 | `test_quota_gate_blocks_spawn` (admin card parity test cũ giữ) |
| AC7 | Cancel: worker hỏi status giữa các trang → cancelled → abort job, tiếp job sau | T4 | `test_cancel_between_pages_via_status` |
| AC8 | Idempotency: done/failed gửi lại → no-op (job_id + status check) | T4 | `test_done_idempotent_replay` |
| AC9 | Watchdog: `kernels_status` poll giữ (complete/failed → dọn; died → revert claimed qua lease — D1 pattern); restart: hash DB → adopt session sống / dọn + respawn | T6 | `test_dead_kernel_reverts_claimed_and_respawns`, `test_restart_adopts_live_session` |
| AC10 | Failure taxonomy: per-job OCR error → failed + worker tiếp; session-level (venv/import) → exit code riêng (90) → server respawn | T6-T7 | kernel exit-90 test + orchestrator failed-poll test |
| AC11 | Batch mode: `run_one.py` giữ làm tool test tay; bỏ batch orchestrator path khi loop ổn — spec quyết + migration plan | T9 | README + config default flip; giữ nguyên code batch |

## Rollout / Migration

1. Apply T1 SQL lên dev/test/prod (idempotent — an toàn chạy 2 lần).
2. Deploy code với `KAGGLE_MODE=batch` (hiện tại) → flip `session` sau khi test green + smoke 1 job tay (`run_one.py` cũ vẫn độc lập).
3. Smoke: 1 job → verify session spawn, claim, upload, done, session card trong `/api/admin/workers` (`kaggle-session` marker), quota card đọc đúng.
4. Rollback = flip `KAGGLE_MODE=batch` (code batch còn nguyên). Forward-clean = T9 migration plan.

## Residual Risks

- Single uvicorn worker assumption (in-process `_last_spawn`, rate-limit counter) — multi-worker deploy cần DB-backed state (đã ghi chú sẵn trong code hiện tại; không đổi trong spec này).
- SIGALRM không interrupt native/CUDA hang (ponytail đã có trong `img2text_batch.py` L205) — giữ nguyên, upgrade path subprocess watchdog.
- Session claim khi kernel đang boot (~1-2 phút venv): next_job không cấp job cho tới khi session đăng ký (spawn → session row → kernel sống mới claim được; job queued lại nếu kernel chết giữa chừng).
- `__SESSION_KEY__` nằm trong staged folder (push = upload) — exposure window = vòng đời session (đã giảm từ per-run presign pattern; hash-at-rest + xóa ngay khi đóng giảm rủi ro đáng kể).
