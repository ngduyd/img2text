# Plan Z — Backend cleanup (server/ only) — task report

Branch: `plan-backend-clean` · base: `59ba16a` · scope: `server/` only · zero behavior change · gate: 152 server tests green.

---

## 1. ARCHITECTURE MAP (primary deliverable)

File → responsibility → rulings embedded → importers.
("importers" = modules inside `server/` that import it; test importers abbreviated.)

### app/ root

| File | Responsibility | Rulings embedded | Imported by |
|---|---|---|---|
| `admin_bootstrap.py` (was `admin.py`) | First-run admin user creation from settings; no-op when credentials empty or user exists | R28 (per-test bootstrap); trusted identity → `ocr_enabled=True` unconditional | `main.py` (lifespan), `tests/conftest.py`, `tests/test_admin_bootstrap.py` |
| `config.py` | pydantic-settings `Settings`; single source of env config (DB, JWT, SMTP, R2, CORS, scheduler) | R58 CORS regex origins incl. VSCode port-forward hosts; R58a `scheduler_interval_seconds` floor 5s | `deps, db, security, storage, scheduler, mailer, routers/{admin,auth}`; tests: conftest, test_env_parity, test_cors_kick, test_storage_public, test_admin_logs |
| `convert.py` | Pandoc invocation constants only | R25 static binary in `server/.tools/` (gitignored), env override; reference styles at `deploy/reference.docx` | `routers/exports.py` |
| `db.py` | Async engine, `SessionLocal`, `get_session` DI, declarative `Base` | R1: schema bootstrap lives in `main.lifespan` (ASGITransport skips lifespan; tests create schema from same `Base`) | `deps, models, routers/*, tests/conftest` |
| `deps.py` | Auth DI: `get_current_user`, `require_admin`, `require_ocr`, `get_runner_key`; `ACCESS/REFRESH_COOKIE` names | R11 bearer runner key (`compare_digest` + `isascii` guard → non-ascii 401 not 500); 401/403 detail strings test-pinned contract | `security` (cookie names), `middleware` (ACCESS_COOKIE), all 6 authed routers |
| `jobs_requeue.py` | `reap_leases` — requeue `running` jobs whose lease expired | Started-at reset deliberate: reclaimed job's clock must be honest; error/result fields untouched | `scheduler` (lazy), `tests/test_reaper_wiring.py` |
| `limiter.py` | Sliding-window limiter (auth) + daily counter (uploads); `rate_limit_auth` dependency | Task 6; ponytail: single-process in-memory → Postgres/Redis before multi-worker deploy | `routers/{auth,profile,jobs}.py` |
| `mailer.py` | SMTP send via `anyio.to_thread`; failures logged + swallowed | Down SMTP must not turn forgot-password into 500; `timeout=10` prevents known-email timing oracle | `routers/auth.py` |
| `main.py` | FastAPI factory + lifespan (create_all → admin bootstrap → scheduler; shutdown closes scheduler + engine) | R6 `app.state.session_factory` for pure-ASGI middlewares; router mount order auth→profile→admin→jobs→exports→region_edit (profile shares `/api/auth` prefix); CORS last-added = outermost | `tests/conftest.py` |
| `middleware.py` | Pure-ASGI `RequestLogs` + `PageViews` middlewares; retention prune helpers (called by scheduler) | R6: no `Depends` — own session from `app.state.session_factory`; write failures logged, never break responses; R60 UA capped 200 chars | `main.py`, `scheduler` (lazy `prune_*`), `tests/test_logging_middleware.py` |
| `models.py` | ORM: User, RefreshToken, PasswordResetToken, PageView, RequestLog, Setting, Job | Spec §4 Job shape; R11 `worker_token` plaintext (hash-at-rest rides Alembic); R2 reset tokens sha256-only in DB; Job user_id FK plain, no cascade | `deps, admin_bootstrap, scheduler, jobs_requeue, routers/*`; tests (13 files) |
| `net.py` | `client_ip(request)` | R5 rightmost X-Forwarded-For entry (nearest trusted proxy appends real client; leftmost is forgeable) | `limiter.py`, `middleware.py`, `tests/test_net.py` |
| `scheduler.py` | APScheduler wiring: interval job `reap-leases` + cron job `daily-prune` (3am) | R58a: upload kick deleted (reaper ≠ claim) — workers claim via `GET /api/jobs/next`; R58 interval floor; `start()` skipped under pytest | `main.py` |
| `schemas.py` | Worker result validation models: PreprocessIn, RegionOut, ResultPage, ResultBody | Spec §4 result JSONB incl. `edited_markdown` (Plan D seam); bbox must be `[x1,y1,x2,y2]` len 4 | `routers/jobs.py` |
| `security.py` | bcrypt hash/verify, access-JWT mint/decode, cookie helpers, reset-token generator | R2 raw reset token only in email body, sha256 in DB; R6 `decode_access_sub` never raises (middleware logs anonymously); bcrypt direct (passlib 1.7.4 AttributeError pollution) | `admin_bootstrap, middleware, routers/{auth,profile}`; tests |
| `storage.py` | S3/R2 driver (`put/presign_get/exists/get/delete_prefix`) + `get_storage` DI + `build_storage` | R24 missing key → `KeyError` so callers map 404; R2 S3 API, `r2_region="auto"`; dev/prod endpoint split (ops client = internal, presign client = public, empty = single client prod-unchanged); content-addressed dedupe put no-op; path-style addressing (MinIO dev + R2 prod); `to_thread` (boto3 sync) | `main.py`, `routers/{jobs,exports,region_edit}`, tests: conftest, test_storage, test_storage_public |

### app/routers/

| File | Responsibility | Rulings embedded | Imported by |
|---|---|---|---|
| `health.py` | `GET /healthz` — SELECT 1 probe | DB failure → 503, never 500 | `main.py` |
| `auth.py` | Register / login / me / refresh / logout + password forgot/reset | R8 forgot always 202 identical body (no user enumeration), SMTP enqueued via BackgroundTasks AFTER token commit; refresh-token reuse → revoke whole family; atomic rotation claim (conditional UPDATE, rowcount race → family revoke); R50 `revoke_all_refresh` exported for profile.py | `main.py`; `profile.py` (UserOut, `_EmailIn`, `_user_out`, `revoke_all_refresh`) |
| `profile.py` | `PATCH /api/auth/profile` — self-service email/password change | R50 shares `revoke_all_refresh` with auth.py; bcrypt verify per request behind `rate_limit_auth` | `main.py` |
| `admin.py` | `/api/admin` router: users list + OCR toggle, request-log filter + safe tail, per-day stats + GPU cost | R28 admin gate; StrictBool OCR patch ("yes" must 422); log tail path from Settings ONLY (traversal impossible by construction); paging clamped | `main.py` |
| `jobs.py` | Job lifecycle router: upload → owner reads → worker claim → owner retry → worker protocol | Spec §6 corrupt PDF = sync 422, no job row/storage write; R11 capability token; R16/R17 atomic conditional-UPDATE transitions (TOCTOU closed); Plan D retry deletes `exports/{id}/` + `crops/{id}/` BEFORE commit (stale artifacts forbidden); `/api/jobs/next` route defined BEFORE `/{id}`; 50MB / 20-per-day / 50-page limits; `storage_key` never leaked to users | `main.py`; `exports.py` + `region_edit.py` (`_job_or_403`); `tests/test_upload.py` (monkeypatches `MAX_UPLOAD_BYTES`) |
| `exports.py` | Content edit (`PATCH /content`) + export generation md/html/docx/pdf + same-origin download + lazy region crops | R27 pandoc failures sanitized 500 (stdout/stderr to log only); R34 `data:` URIs applied post-bleach only — never in global allowlist (click-XSS on R2 origin); R26 crops = image jobs only (PDFs not PIL-decodable); R24 missing original → 404; content edit invalidates `exports/{id}/` cache; crops embedded in ALL md-family exports; no `exif_transpose` (crop must match VLM pixel frame) | `main.py`; `region_edit.py` (`current_markdown`, `find_region`); `tests/test_export_pdf_rewrite.py` (monkeypatches `"app.routers.exports.PANDOC_BIN"`) |
| `__init__.py` ×2 | Empty package markers | — | — |

### tests/ layout (34 files)

`conftest.py` = all fixtures: session-scoped `db_schema` (R1: ASGITransport skips lifespan → tests own schema), autouse `db_truncate`, `auth_client`/`admin_client`/`worker_client` (R10), `seed_job`, `done_job_with_result` (R24), `storage_spy` (R10 wraps real driver). Test files map 1:1 to surface: auth×4, admin×4, jobs/upload×8 (incl. `cors_kick` R58/R58a, `rate_limit`, `reaper_wiring` R17), exports/crops×8, infra×6 (health, net R5, models, logging_middleware R6, env_parity, audit_ip_ua R60).

### Import graph (acyclic — verified)

`config` ← everything · `db` ← deps/models/routers · `models` ← almost all · `deps` ← routers + middleware + security(cookie names) · `security` ← admin_bootstrap/middleware/routers · `net` ← limiter/middleware · `convert` ← exports · `storage` ← main/routers · `routers.jobs` ← exports/region_edit (`_job_or_403`) · `routers.exports` ← region_edit (`current_markdown`, `find_region`) · `routers.auth` ← profile. No cycle introduced or broken; `create_app()` imports clean.

---

## 2. Before / after tree

**Before** (flat, 24 files, 2 532 lines; `app/admin.py` duplicated the name "admin" with `app/routers/admin.py` — one was a bootstrap helper, the other the router; nothing said so):

```
server/app/
  admin.py(27) config.py(47) convert.py(11) db.py(25) deps.py(63) __init__.py(0)
  jobs_requeue.py(34) limiter.py(72) mailer.py(54) main.py(71) middleware.py(128)
  models.py(143) net.py(16) scheduler.py(83) schemas.py(45) security.py(90) storage.py(140)
  routers/{admin(206) auth(304) exports(368) health(18) jobs(469) profile(54) region_edit(64)}.py
```

**After** (24 files, 2 587 lines — +55 net from docstrings/banners; no new modules; no splits):

```
server/app/
  admin_bootstrap.py(32)   ← renamed from admin.py (+3-line ruling docstring)
  config.py(51) convert.py(15) db.py(29) deps.py(67) __init__.py(0)
  jobs_requeue.py(33) limiter.py(72) mailer.py(54) main.py(77) middleware.py(128)
  models.py(147) net.py(16) scheduler.py(80) schemas.py(45) security.py(89) storage.py(142)
  routers/{admin(206) auth(304) exports(377) health(21) jobs(479) profile(54) region_edit(69)}.py
```

Same layout, one rename, lock gone, every module now opens with a responsibility+rulings header, both long routers carry `# --- Section ---` banners.

---

## 3. Decisions (with reasons)

1. **`_claim_lock` removed.** Grep-verified single-caller (`reap_all` → `_run_jobs_once`, one call site inside `init_scheduler`); zero test references (`test_reaper_wiring.py` pins job id `reap-leases` + reap behavior, not the lock). The stale comment itself admitted the lock was "a cheap guard if a second caller appears" — vestigial post-R58a. `asyncio` import dropped with it.
2. **`admin.py` → `admin_bootstrap.py` (not `admin_utils.py`).** Binding allowed "or better name after reading": the module contains exactly one function, `bootstrap_admin`; `admin_bootstrap` names the thing, matches Task 8 and the existing `tests/test_admin_bootstrap.py`. `admin_utils` would be vaguer — the exact confusion this cleanup targets. `app/routers/admin.py` keeps its name (it *is* the router). Imports updated mechanically in `main.py`, `tests/conftest.py`, `tests/test_admin_bootstrap.py`. Repo-wide grep: no other references (worker/web/docs untouched).
3. **No split of `jobs.py` / `exports.py`.** Seams examined: render helpers (sanitize/pandoc/crops/pdf) → `app/export_render.py`. Rejected — three reasons: (a) `tests/test_export_pdf_rewrite.py:140` monkeypatches `"app.routers.exports.PANDOC_BIN"` — a split forces test edits beyond the binding's "mechanical import fixes only"; (b) `routers/exports.py` is already a de-facto shared lib (`region_edit` imports `current_markdown`/`find_region` from it) — moving symbols widens the rename surface past "no renames beyond the admin move"; (c) payoff marginal: 377/479 lines with section banners + docstrings is navigable. Lazy default per binding: banners + docstrings suffice.
4. **Dead-import sweep via pyflakes.** Removed: `security.py` `UUID/uuid4`; `jobs_requeue.py` `AsyncSession`; `region_edit.py` `Job`; `tests/test_admin_users.py` `select`; `tests/test_admin_stats.py` `date`. **Deliberately NOT removed:** `tests/test_crop.py:10` / `tests/test_export_download.py:7` "unused" `other_client` imports — pytest fixture imports (`# noqa: F401` re-export pattern); pyflakes can't see fixture resolution, deleting them breaks tests.
5. **Stale comments fixed:** scheduler header now states R58a accurately (kick deleted, reaper ≠ claim) instead of advertising a deleted lock; `jobs.py`/`exports.py` old task-numbered banners normalized to `# --- Section ---` with ruling references. `test_cors_kick.py` SyntaxWarning (`\.` in docstring) escaped — docstring only.
6. **Env notes (no code impact):** worktree lacked gitignored `server/.tools/pandoc` — provisioned symlink to main checkout's binary (tree stays clean; `server/.tools/` is gitignored). The first baseline run (pre-symlink) showed 8 export-test failures — missing-pandoc env gap, same tests pass with `.tools` present. Test DB: host `:5433` is occupied by the parallel plan-H lane's test Postgres; started isolated `plan-z-postgres-test` container on `:5436`. No dev-stack container was restarted or recreated; test suite runs use `DATABASE_URL=...@localhost:5436/img2text_test`.

---

## 4. Commits

```
a0dfdd1 refactor(server): remove dead code + vestigial claim lock
8fe89d9 refactor(server): rename app/admin.py -> app/admin_bootstrap.py
0393a8e docs(server): module docstrings + section banners
```

Diff vs base: `20 files changed, 93 insertions(+), 39 deletions(-)`. Test-file changes are import/docstring-only — zero assertion changes (R51). Tree clean at end.

## 5. Suite output (pasted)

Baseline (HEAD 59ba16a, before edits, `.tools` missing): `8 failed, 144 passed, 2 warnings in 613.17s` — all 8 failures in `test_export_docx.py`/`test_export_pdf_rewrite.py` from the missing pandoc binary (env gap; re-ran those 2 files with `.tools` provisioned: `10 passed in 54.00s`).

Final (post-cleanup, `/tmp/z-clean-server.log`):

```
........................................................................ [ 47%]
........................................................................ [ 94%]
....................................................................     [100%]
152 passed, 1 warning in 608.93s (0:10:08)
```

The 1 warning = pre-existing httpx `DeprecationWarning` (per-request `cookies=`) from test code — unrelated to this cleanup.

Commands run: `.venv/bin/python -m pyflakes app/ tests/` → clean on `app/`; `py_compile` all `app/`+`tests/` files → OK; `create_app()` import smoke → 7 routers wired; full pytest → 152 passed.
