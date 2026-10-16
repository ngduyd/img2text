# P2 Prod Hardening — Implementation Plan

Spec: `docs/superpowers/specs/2026-10-16-p2-prod-hardening.md` (5 tasks).
Branch: `lane-p2-hardening`. Commit per task, TDD red→green, assertions không weaken.
Test cmd (worktree root):

```
env DATABASE_URL="postgresql+asyncpg://img2text:img2text@localhost:5436/img2text_test" \
    PYTHONPATH="$PWD/server" server/.venv/bin/python -m pytest server/tests/test_X.py -q
```

Spec deviations đã phê duyệt / giải thích:
- Spec ghi `_issue_worker_token` (không tồn tại) → hash INLINE trong `next_job` (parent steering: ít diff nhất, behavior giữ nguyên).
- Migration pattern file (`docs/checklist-migrations-prod.md`, `test_migration_checksums.py`) KHÔNG tồn tại → supervisor chọn (A): idempotent hand-SQL + test MỚI `server/tests/test_migration_p2_worker_token.py` (sha256(SQL)==constant tamper-detection + apply vào DB test + assert column).
- Spec TDD tên file `test_auth.py`/`test_admin.py`/`test_security.py` không khớp cấu trúc repo → đặt test theo source: revoke→`test_auth_refresh.py`, admin revoke→`test_admin_users.py`, hash→`test_security.py` (mới), gating→`test_prod_gating.py` (mới).
- #19 TDD `manifest["expires_in"]` không tồn tại (manifest chỉ có `jobs[].input_url`) → assert `settings.input_url_expires == 900` (cùng intent: cửa sổ 900s).
- #20 `test_rate_limit_upload_exceeded` phải monkeypatch `UPLOAD_DAILY_LIMIT`↑ (daily=20 chặn trước, nếu không test đo sai limiter).

## #16 Worker token hash-at-rest — AC1

TDD:
1. RED `tests/test_security.py::test_worker_token_hash_matches` — `hash_worker_token("test-token-123") == hashlib.sha256(...).hexdigest()`; fail: hàm chưa có.
2. RED `tests/test_worker_protocol.py::test_worker_auth_accepts_valid_token` (heartbeat 200 w/ claimed token), `test_worker_auth_rejects_invalid_token` (401 wrong token).
3. GREEN:
   - `app/core/security.py` +`hash_worker_token()` (sha256 hex).
   - `app/core/models.py:256` `worker_token` → `worker_token_hash: Mapped[str | None]` (Text, nullable); sửa comment ponytail/Alembic-để-sau.
   - `app/routers/jobs.py`: `next_job` ~546 `job.worker_token_hash = hash_worker_token(token)` (plaintext trả về worker 1 lần, không lưu); 3 gate (`_worker_job_or_401`, heartbeat, result) → `hmac.compare_digest(hash_worker_token(token), job.worker_token_hash)`; heartbeat UPDATE `Job.worker_token == token` → `Job.worker_token_hash == hash_worker_token(token)`; ctor ~770 rename.
   - `app/services/job_results.py`: `_store` values + `store_worker_result` cond + batch guards `.is_(None)` → `worker_token_hash` (hash compare cho claim cond).
   - `app/services/jobs_requeue.py:36`, `app/services/kaggle_orchestrator.py:675,786,894` rename (IS NULL semantics giữ nguyên).
   - Test cũ: attribute `job.worker_token` → `worker_token_hash` (test_kaggle_batch_orchestrator, test_worker_protocol:58, test_reaper_wiring:36, test_job_retry:72).
4. Migration MỚI `docs/migrations/2026-10-16_worker_token_hash.sql`: `CREATE EXTENSION IF NOT EXISTS pgcrypto;` + `ADD COLUMN IF NOT EXISTS worker_token_hash TEXT;` + DO-block backfill `encode(digest(worker_token,'sha256'),'hex')` (chỉ khi cột cũ còn tồn tại → re-runnable) + `DROP COLUMN IF EXISTS worker_token;`.
5. Test MỚI `server/tests/test_migration_p2_worker_token.py`: (a) sha256(file)==constant (tamper-detection); (b) simulate legacy (ADD worker_token, insert row qua register client + raw INSERT) → apply SQL → assert hash khớp sha256(token), cột cũ gone; (c) apply lại lần 2 → idempotent không lỗi.

Commit: `feat(security): hash worker_token at rest; migrate plaintext column`

## #17 Session revoke — AC2

TDD:
1. RED `tests/test_auth_refresh.py::test_revoke_sessions_deletes_refresh_tokens` — login → refresh 200 → `POST /api/auth/session/revoke` 204 → refresh 401.
2. RED `tests/test_admin_users.py::test_admin_revoke_sessions` — target user (client riêng, pattern test_admin_users pin) login+refresh → `POST /api/admin/users/{id}/revoke-sessions` (admin_client) 204 → target refresh 401.
3. GREEN:
   - `app/routers/auth.py` +`POST /session/revoke` status 204: `Depends(get_current_user)` + `revoke_all_refresh(session, user.id)`.
   - `app/routers/admin.py` +`POST /users/{user_id}/revoke-sessions` status 204: `_admin_user` (require_admin — codebase không có is_superuser; same intent), 404 unknown user, `revoke_all_refresh` + `logger.info` audit line (admin id + target id; RequestLog middleware đã ghi row audit tự động).

Commit: `feat(auth): add session revoke endpoint + admin revoke`

## #18 Request logs batch insert — AC3

TDD:
1. RED `tests/test_logging_middleware.py::test_request_logs_buffered_not_written_immediately` — GET /healthz → count(RequestLog) không đổi.
2. RED `tests/test_logging_middleware.py::test_flush_job_writes_buffered_logs` — 2 request → `flush_request_logs(app)` → count ≥ 2.
3. GREEN:
   - `app/core/middleware.py`: buffer list `app.state.request_log_buffer` (lazy getattr-init, pattern limiter); `_write` append + flush ngay khi ≥100; +`async def flush_request_logs(app) -> int` (snapshot→clear→`session.add_all`→commit; fail → re-buffer, raise — không mất audit row).
   - `app/services/scheduler.py`: job `flush-request-logs` interval 30s (try/except pattern).
   - `app/main.py` lifespan shutdown: flush buffer trước khi dispose.
   - `prune_request_logs` không đổi.
4. Test cũ đọc middleware-written row → thêm `await flush_request_logs(app)` trước assert (assertion giữ nguyên): `test_request_logged`, `test_request_log_resolves_authenticated_user`, `test_audit_ip_ua`, `test_admin_settings:433`.

Commit: `perf(logging): batch request_logs insert; flush every 30s`

## #19 Presigned URL expiry — AC4

TDD:
1. RED `tests/test_render_md.py::test_crop_presign_expiry_reduced` — `settings.crop_presign_expires == 3600`.
2. RED `tests/test_kaggle_orchestrator.py::test_input_url_expiry_reduced` — `settings.input_url_expires == 900`.
3. GREEN:
   - `app/core/config.py`: +`crop_presign_expires: int = 3600`, +`input_url_expires: int = 900` (env-overridable qua pydantic-settings).
   - `app/services/render_md.py:584` xoá `CROP_PRESIGN_EXPIRES = 86400`; call site `embed_crop_urls` dùng `settings.crop_presign_expires`; comment "24h" → 1h.
   - `app/services/kaggle_orchestrator.py:59` xoá `INPUT_URL_EXPIRES_SECONDS`; call site :562 dùng `settings.input_url_expires`; comment 15min.

Commit: `chore(security): reduce presigned URL expiry windows`

## #20 Test gating + limiter coverage — AC5

TDD:
1. RED `tests/test_limiter.py` (mới): `test_rate_limit_feedback_exceeded` (11× POST /api/feedback `{"content":"test"}` → 429), `test_rate_limit_upload_exceeded` (monkeypatch `UPLOAD_DAILY_LIMIT`=999 → 31× POST /api/jobs valid body → 429), `test_rate_limit_passes_under_limit` (1× each → không 429).
2. RED `tests/test_prod_gating.py` (mới): `prod_only` marker + non-prod env → skip marker; env=prod → không skip (gọi hook trực tiếp với stub item — collection-time nên self-test gọi hook).
3. GREEN:
   - `app/core/limiter.py`: `rate_limit_feedback` (10/60s per user — key `sub` từ access cookie, fallback IP) + `rate_limit_upload` (30/3600s per user), lazy `app.state` instance (pattern `rate_limit_auth`).
   - Wire: `feedback.py` create_feedback `Depends(rate_limit_feedback)`; `jobs.py` create_job `Depends(rate_limit_upload)`.
   - `pytest.ini`: register marker `prod_only`; `tests/conftest.py`: +`env` fixture (monkeypatch settings.env) + `pytest_collection_modifyitems` skip `prod_only` khi `settings.env != "prod"`.

Commit: `feat(limiter): add feedback + upload rate limits; test gating`

## Verification cuối

- Full suite `server/tests` (đảmua không regression, nhất là buffering + token rename).
- `git status` sạch (không staged file thừa), 5 commits trên `lane-p2-hardening`.
- AC map đối chiếu từng dòng spec → file thật.
