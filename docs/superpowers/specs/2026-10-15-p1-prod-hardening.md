# P1 Prod Hardening Spec

**Date:** 2026-10-15
**Goal:** Remediate 7 P1 findings from deploy-readiness audit. Each finding maps to a concrete task with test criteria. P0 (8/8) already done.

## Background

Deploy-readiness audit (20 findings): P0=8 done, P1=7 open, P2=5 deferred. This spec covers the 7 P1 items that block production hardening. All tasks are code changes except backup cron/docs (infra) and log rotation (infra+code).

---

## Findings & Tasks

### #9. SMTP Swallow + email_unverified Gate Stuck

**Files:**
- `server/app/services/mailer.py` — `_send_sync`, `send_email` (lines 18-48)
- `server/app/core/middleware.py` — `EmailVerifyGateMiddleware` (lines 73-115)
- `server/app/routers/auth.py` — verify/resend/forgot/reset endpoints (lines 140-420)

**Spec:**
- `mailer.py` `send_email`: **do not swallow** SMTP exceptions. Return `(success: bool, error: str | None)` tuple. Callers (auth routes) decide HTTP response.
- `EmailVerifyGateMiddleware`: on DB lookup failure, **return 503** (not passthrough). Gate must not let unverified users through on DB error.
- Auth routes: on SMTP failure, return `503 {"code":"email_unavailable", "retry_after_seconds": 300}` (not 202/201). Distinguish "send failed" from "limit exceeded".

**TDD Red→Green Steps:**
```python
# test_mailer.py
async def test_send_email_returns_failure_on_smtp_down(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "unreachable-host")
    monkeypatch.setattr(settings, "smtp_port", 25)
    ok, err = await send_email("test@example.com", "subj", "body")
    assert ok is False
    assert err is not None

# test_middleware.py
async def test_email_gate_returns_503_on_db_error(app, monkeypatch):
    async def failing_session_factory():
        raise RuntimeError("db down")
    app.state.session_factory = failing_session_factory
    # request with verified user cookie
    response = await client.get("/api/jobs", cookies={"access": valid_token})
    assert response.status_code == 503

# test_auth.py
async def test_verify_resend_returns_503_on_smtp_failure(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "bad")
    resp = await client.post("/api/auth/verify/resend", json={"email": "a@b.c"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "email_unavailable"
```

**Expected New Tests:**
- `tests/test_mailer.py::test_send_email_returns_failure_on_smtp_down`
- `tests/test_middleware.py::test_email_gate_returns_503_on_db_error`
- `tests/test_auth.py::test_verify_resend_returns_503_on_smtp_failure`

**Commit Message:** `feat(email): SMTP failures surface to caller; gate returns 503 on DB error`

---

### #10. Storage Range-GET 12B

**Files:**
- `server/app/services/storage.py` — `S3Driver.get` (lines 85-98), add `get_range(key, start, end)`
- `server/app/routers/exports.py` — `download_export` (lines 560-585), add Range header support

**Spec:**
- `S3Driver.get_range(key: str, start: int, end: int) -> bytes`: uses `Range` param in `get_object`. Returns exact byte slice.
- `download_export`: parse `Range` header (bytes=start-end). If present, call `storage.get_range` and return `206 Partial Content` with `Content-Range` and `Content-Length`. If absent, current behavior (full content).
- Support single-range only (suffix-range, multi-range → 416).

**TDD Red→Green Steps:**
```python
# test_storage.py
async def test_get_range_returns_exact_slice(storage, sample_file):
    # sample_file = 100 bytes
    chunk = await storage.get_range(sample_file.key, 10, 19)  # 10 bytes
    assert len(chunk) == 10
    assert chunk == sample_file.content[10:20]

async def test_get_range_out_of_bounds_raises(storage, sample_file):
    with pytest.raises(ValueError, match="range"):
        await storage.get_range(sample_file.key, 100, 200)

# test_exports.py
async def test_download_export_range_header_returns_206(client, job_with_export):
    resp = await client.get(
        f"/api/jobs/{job_with_export.id}/export/pdf/download",
        headers={"Range": "bytes=0-99"}
    )
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 0-99/1000"
    assert len(resp.content) == 100

async def test_download_export_invalid_range_returns_416(client, job_with_export):
    resp = await client.get(
        f"/api/jobs/{job_with_export.id}/export/pdf/download",
        headers={"Range": "bytes=2000-3000"}
    )
    assert resp.status_code == 416
```

**Expected New Tests:**
- `tests/test_storage.py::test_get_range_returns_exact_slice`
- `tests/test_storage.py::test_get_range_out_of_bounds_raises`
- `tests/test_exports.py::test_download_export_range_header_returns_206`
- `tests/test_exports.py::test_download_export_invalid_range_returns_416`

**Commit Message:** `feat(storage): add get_range; export download supports Range header`

---

### #11. Bcrypt Cap 72B

**Files:**
- `server/app/core/security.py` — `hash_password`, `verify_password` (lines 26-33)
- `server/app/routers/auth.py` — register/password reset (lines 120-180, 400-420)

**Spec:**
- Bcrypt truncates input at 72 bytes. Add validation: reject passwords > 72 bytes with `400 {"code":"password_too_long", "max_bytes":72}`.
- Validation in `hash_password` (raise `ValueError`) and at API boundary (register, reset, change password).
- Use `len(p.encode())` for byte count (UTF-8).

**TDD Red→Green Steps:**
```python
# test_security.py
def test_hash_password_rejects_over_72_bytes():
    long_pw = "x" * 73
    with pytest.raises(ValueError, match="72"):
        hash_password(long_pw)

def test_hash_password_accepts_72_bytes():
    pw = "x" * 72
    h = hash_password(pw)
    assert verify_password(pw, h)

# test_auth.py
async def test_register_rejects_password_over_72_bytes(client):
    resp = await client.post("/api/auth/register", json={
        "email": "a@b.c", "password": "x" * 73
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == "password_too_long"

async def test_password_reset_rejects_over_72_bytes(client, unverified_user):
    code = "123456"  # mock
    resp = await client.post("/api/auth/password/reset", json={
        "email": unverified_user.email, "code": code, "password": "x" * 73
    })
    assert resp.status_code == 400
```

**Expected New Tests:**
- `tests/test_security.py::test_hash_password_rejects_over_72_bytes`
- `tests/test_security.py::test_hash_password_accepts_72_bytes`
- `tests/test_auth.py::test_register_rejects_password_over_72_bytes`
- `tests/test_auth.py::test_password_reset_rejects_over_72_bytes`

**Commit Message:** `feat(security): validate password length ≤72 bytes for bcrypt`

---

### #12. Backup Cron + Docs

**Files:**
- `server/app/services/scheduler.py` — add `backup_db` job (new function)
- `server/app/core/db.py` — add `backup_database()` helper (new)
- `deploy/backup.sh` — new executable script (deliverable)
- `docs/backup-restore.md` — new documentation (deliverable)
- `deploy/docker-compose.yml` — optional: pg_dump sidecar or volume mount

**Spec:**
- New scheduler job `backup-db`: daily at 04:00 (configurable via `backup_cron` runtime setting, default `0 4 * * *`).
- `backup_database()`: uses `pg_dump` (requires `postgresql-client` in image) → writes to `/backups/img2text-YYYYMMDD-HHMMSS.sql.gz`. Retains last 14 days (configurable `backup_retention_days` default 14).
- `deploy/backup.sh`: standalone script for manual/off-schedule runs. Usage: `backup.sh [--retention 14] [--output-dir /backups]`.
- `docs/backup-restore.md`: documents schedule, retention, restore procedure (`gunzip -c backup.sql.gz | psql $DATABASE_URL`), verification steps.

**Deliverables (no code tests):**
- `deploy/backup.sh` executable, shebang `#!/bin/bash`, error handling, logging.
- `docs/backup-restore.md` with: schedule, retention, restore command, test-restore checklist.
- Scheduler job visible in `scheduler.get_job("backup-db")` after app start.

**Commit Message:** `chore(backup): add daily pg_dump cron + restore docs`

---

### #14. Font Noto for Render (Vietnamese)

**Files:**
- `deploy/Dockerfile` — add `fonts-noto-cjk` + `fonts-noto-serif-cjk` packages
- `server/app/services/render_docx.py` — `_render_pdf` (lines 680-695) font-family
- `server/app/services/render_md.py` — if any PDF path, same font

**Spec:**
- Dockerfile: `apt-get install -y fonts-noto-cjk fonts-noto-serif-cjk` (Noto Sans CJK + Noto Serif CJK cover Vietnamese).
- `_render_pdf` in `render_docx.py`: change `font-family: 'DejaVu Sans', serif` → `'Noto Sans CJK', 'DejaVu Sans', serif` (Noto first for CJK glyphs, DejaVu fallback).
- `render_md.py` if it has PDF path (check: it uses same `_render_pdf` via exports) — same CSS.

**TDD Red→Green Steps:**
```python
# test_render_docx.py
def test_pdf_font_css_uses_noto_first():
    from app.services.render_docx import _render_pdf
    # inspect the CSS string passed to weasyprint
    # CSS must contain 'Noto Sans CJK' before 'DejaVu Sans'
    css_str = _extract_font_css(_render_pdf)
    assert css_str.index("Noto Sans CJK") < css_str.index("DejaVu Sans")

# Docker build test (manual/CI):
# docker build -f deploy/Dockerfile .. && docker run --rm <image> fc-list | grep -i "noto.*cjk"
```

**Expected New Tests:**
- `tests/test_render_docx.py::test_pdf_font_css_uses_noto_first`

**Commit Message:** `chore(fonts): add Noto CJK for Vietnamese PDF render`

---

### #15. Log Rotation

**Files:**
- `server/app/core/config.py` — `log_path` setting (line 25), add `log_max_bytes`, `log_backup_count`
- `server/app/main.py` — `create_app` logging config (replace basicConfig with rotating handler)
- `deploy/logrotate.d/img2text` — new logrotate config (deliverable)

**Spec:**
- Config: `log_max_bytes: int = 10_000_000` (10MB), `log_backup_count: int = 7`.
- `create_app()`: configure root logger with `RotatingFileHandler(settings.log_path, maxBytes=..., backupCount=...)`. JSON format (already structured via middleware). Ensure `logs/` dir exists.
- `deploy/logrotate.d/img2text`: daily rotate, compress, delaycompress, missingok, notifempty, maxage 30, create 0640 appuser appuser. For container: stdout/stderr handled by Docker; this is for host/VM deploys.

**TDD Red→Green Steps:**
```python
# test_logging.py
def test_log_rotation_config_applied(monkeypatch, tmp_path):
    log_file = tmp_path / "test.log"
    monkeypatch.setattr(settings, "log_path", str(log_file))
    monkeypatch.setattr(settings, "log_max_bytes", 100)
    monkeypatch.setattr(settings, "log_backup_count", 3)
    app = create_app()
    # write >100 bytes via logger
    logger = logging.getLogger()
    logger.info("x" * 200)
    # rotation should have occurred
    assert log_file.exists()
    # backup files exist
    backups = list(tmp_path.glob("test.log.*"))
    assert len(backups) <= 3
```

**Expected New Tests:**
- `tests/test_logging.py::test_log_rotation_config_applied`

**Deliverable:**
- `deploy/logrotate.d/img2text` (for non-container deploys)

**Commit Message:** `feat(logging): add RotatingFileHandler + logrotate config`

---

### #16. [7th P1] Admin Bootstrap Idempotency on Prod Restart

**Files:**
- `server/app/services/admin_bootstrap.py` — `bootstrap_admin` (lines 1-50)
- `server/app/main.py` — lifespan calls `bootstrap_admin`

**Spec:**
- Current: on prod restart, if admin user exists but password changed externally, bootstrap does nothing (idempotent). But if admin user deleted, it recreates with env credentials (by design).
- **P1 gap**: no audit log entry when bootstrap creates/updates admin. Add `AuditLog` entry (new model or reuse `RequestLog` with `path="/internal/admin-bootstrap"`).
- On prod, if `ADMIN_PASSWORD` env changed, **update** the admin user's password hash (currently only creates if missing).
- Fail-fast: if `settings.env == "prod"` and admin user exists but `is_superuser` false → raise `RuntimeError` (privilege escalation guard).

**TDD Red→Green Steps:**
```python
# test_admin_bootstrap.py
async def test_prod_updates_admin_password_on_env_change(db_session, monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    monkeypatch.setattr(settings, "admin_email", "admin@test.com")
    monkeypatch.setattr(settings, "admin_password", "old-pass")
    await bootstrap_admin(db_session, "admin@test.com", "old-pass")
    # change env
    monkeypatch.setattr(settings, "admin_password", "new-pass")
    await bootstrap_admin(db_session, "admin@test.com", "new-pass")
    user = await db_session.get(User, 1)
    assert verify_password("new-pass", user.password_hash)

async def test_prod_raises_on_existing_non_superuser_admin(db_session, monkeypatch):
    monkeypatch.setattr(settings, "env", "prod")
    # create non-superuser with admin@ email
    db_session.add(User(email="admin@test.com", password_hash=hash_password("x"), role="user"))
    await db_session.commit()
    with pytest.raises(RuntimeError, match="admin.*not superuser"):
        await bootstrap_admin(db_session, "admin@test.com", "pass")
```

**Expected New Tests:**
- `tests/test_admin_bootstrap.py::test_prod_updates_admin_password_on_env_change`
- `tests/test_admin_bootstrap.py::test_prod_raises_on_existing_non_superuser_admin`

**Commit Message:** `feat(admin): bootstrap updates password on env change; audit log + prod guard`

---

## Acceptance Criteria (AC) Map

| AC | Finding | Task | Files Changed |
|----|---------|------|---------------|
| AC1 | #9 | SMTP failures surface; gate 503 on DB error | `mailer.py`, `middleware.py`, `auth.py` |
| AC2 | #10 | Storage `get_range`; export download `Range` → 206 | `storage.py`, `exports.py` |
| AC3 | #11 | Password >72 bytes rejected at hash + API | `security.py`, `auth.py` |
| AC4 | #12 | Daily pg_dump cron; backup.sh; restore docs | `scheduler.py`, `db.py`, `deploy/backup.sh`, `docs/backup-restore.md` |
| AC5 | #14 | Noto CJK fonts in Dockerfile; PDF CSS uses Noto first | `Dockerfile`, `render_docx.py` |
| AC6 | #15 | RotatingFileHandler (10MB/7); logrotate config | `config.py`, `main.py`, `deploy/logrotate.d/img2text` |
| AC7 | #16 | Admin bootstrap updates password; audit log; prod guard | `admin_bootstrap.py`, `main.py` |

---

## Architecture

- **Validation layer**: API-boundary checks (bcrypt, Range, SMTP) — fail fast, clear error codes.
- **Config-driven**: All intervals, retention, limits via settings (runtime overrideable).
- **Observability**: Audit log for admin bootstrap; structured logs already in place.
- **Infra as code**: backup.sh, logrotate.d, Dockerfile packages — versioned, reviewable.

## Tech Stack

- FastAPI + pydantic-settings (config)
- APScheduler 3.x (cron jobs)
- boto3 (S3 Range GET)
- bcrypt (password hashing)
- weasyprint + fontconfig (PDF render)
- Python logging.handlers.RotatingFileHandler

---

## Implementation Plan Reference

See `docs/superpowers/plans/2026-10-15-p1-prod-hardening.md` for task-by-task execution plan with checkboxes.
