# Lane P1 Prod-Hardening — Worker Plan

Spec (QA, contract): `docs/superpowers/specs/2026-10-15-p1-prod-hardening.md` (7 tasks, AC1–AC7).
Rules: TDD red→green per task, commit per task, no weakened assertions. Spec file:line
references validated against actual code — deviations recorded inline.

Test command (worktree):

```
cd .worktrees/lane-p1-hardening/server && \
  env DATABASE_URL="postgresql+asyncpg://img2text:img2text@localhost:5436/img2text_test" \
  PYTHONPATH="$PWD" .venv/bin/python -m pytest tests/<file> -q
```

## T1 — #9 / AC1: SMTP failures surface; gate 503 on DB error

- `server/app/services/mailer.py`: `send_email` → `tuple[bool, str | None]`
  ((True, None) ok; (False, err) logged failure — never raises).
- `server/app/core/middleware.py::EmailVerifyGateMiddleware`: DB lookup exception
  → 503 `{"code": "service_unavailable"}` (no passthrough).
- `server/app/routers/auth.py`: register (welcome+verify), verify/resend, forgot
  AWAIT send inline; send failure → 503 `{"code":"email_unavailable","retry_after_seconds":300}`
  (flat body, mirrors EmailLimitExceeded handler pattern). Unknown-email forgot
  keeps 202 (no send attempted).
- Update existing tests encoding the swallow bug (spec = authority, strengthen not weaken):
  `test_register_smtp_down_still_201` → expects 503; `test_forgot_smtp_failure_still_202`
  → expects 503. `_capture`/fake `send_email` stubs updated to return `(True, None)`
  (contract change, assertions unchanged).
- New tests (spec-named): `tests/test_mailer.py::test_send_email_returns_failure_on_smtp_down`,
  `tests/test_middleware.py::test_email_gate_returns_503_on_db_error`,
  `tests/test_auth.py::test_verify_resend_returns_503_on_smtp_failure`.
- Known trade-off (matches existing 429 "leak tồn tại chấp nhận" precedent in forgot):
  forgot on a KNOWN email during an SMTP outage → 503 vs unknown → 202 = conditional
  existence signal, same class as the already-accepted 429 leak.

## T2 — #10 / AC2: storage `get_range`; export download Range → 206

- `server/app/services/storage.py`: Protocol + `S3Driver.get_range(key, start, end)`
  (S3 `Range: bytes=start-end`; `InvalidRange` ClientError → `ValueError("range…")`;
  end beyond object size clamps, S3 semantics).
- `server/app/routers/exports.py::download_export`: parse `Range` header —
  single `bytes=start-end` only; suffix/multi/malformed/out-of-bounds → 416
  `{"code":"invalid_range"}` (+ `Content-Range: bytes */size` when size known).
  Hit → `storage.get_range` → 206 + `Content-Range` + `Content-Length`.
  `md-layout` exception: bytes are re-encoded at serve-time (crop URL embed) →
  full fetch + transform + slice, range computed on final representation.
- Tests: `tests/test_storage.py::test_get_range_returns_exact_slice`,
  `::test_get_range_out_of_bounds_raises`; `tests/test_export_download.py::…_range_206`,
  `…_invalid_range_416` (+ suffix/multi/malformed → 416).

## T3 — #11 / AC3: password ≤72 bytes

- `server/app/core/security.py::hash_password`: `len(p.encode()) > 72` →
  `ValueError("…72…")`.
- API boundary (400 flat `{"code":"password_too_long","max_bytes":72}`), check BEFORE
  any other route logic: register (`auth.py`), password reset (`auth.py`),
  change password (`profile.py` — spec text lists "change password", files list
  omitted it; same finding surface, in scope).
- Tests: `tests/test_security.py` (reject 73B / accept 72B round-trip),
  `tests/test_auth.py` (register 400, reset 400 — length check precedes code claim),
  `tests/test_profile.py` (change-password 400).

## T4 — #12 / AC4: backup cron + script + docs

- `server/app/core/config.py`: `backup_cron: str = "0 4 * * *"`,
  `backup_retention_days: int = 14`.
- `server/app/core/db.py::backup_database(output_dir, retention_days)`: pg_dump
  (connstring: strip `+asyncpg` for libpq) piped through Python `gzip` →
  `/backups/img2text-YYYYMMDD-HHMMSS.sql.gz`; prune by mtime > retention days;
  non-zero pg_dump → RuntimeError.
- `server/app/services/scheduler.py`: job id `backup-db`, cron trigger from
  `backup_cron` (runtime override via Setting row, reschedule pattern like
  reap-leases); run in `asyncio.to_thread`; failure logged, tick survives.
- `deploy/backup.sh` (executable, `set -euo pipefail`, `--retention` `--output-dir`,
  logging) + `docs/backup-restore.md` (schedule, retention, restore
  `gunzip -c … | psql $DATABASE_URL`, test-restore checklist).
- `deploy/Dockerfile`: add `postgresql-client` (pg_dump in image).
- Tests (mock scheduler, no real pg_dump): job registered + cron 04:00 default;
  `backup_database` with fake `pg_dump` on PATH → `.sql.gz` payload; retention prune.
- Skipped (spec marks optional / YAGNI): compose sidecar; admin-settings API
  exposure of backup keys (Setting rows still override at runtime).

## T5 — #14 / AC5: Noto CJK fonts

- Spec deviation (validated): `_render_pdf`/`render_docx.py` PDF path does not
  exist — PDF font CSS lives in `server/app/routers/exports.py:295`. Hoist to
  module const `PDF_FONT_CSS`, Noto first:
  `'Noto Sans CJK', 'DejaVu Sans', serif`. `render_md.py` has no PDF path — no change.
- `deploy/Dockerfile`: + `fonts-noto-cjk fonts-noto-serif-cjk`.
- Tests (source-named, moved from spec path `test_render_docx.py`):
  `tests/test_export_pdf_font.py::test_pdf_font_css_uses_noto_first` +
  extend Dockerfile font test with Noto assertions.
- Skipped: docker build verification (manual/CI, per spec note).

## T6 — #15 / AC6: log rotation

- `server/app/core/config.py`: `log_max_bytes: int = 10_000_000`,
  `log_backup_count: int = 7`.
- `server/app/main.py::create_app`: root logger → `RotatingFileHandler`
  (settings-driven), handler tagged `_img2text_rotating` and replaced on every
  `create_app` (no handler pile-up), `logs/` dir auto-created. Formatter: plain
  timestamped text (`ponytail:` no JSON formatter exists in repo — add when a
  log shipper needs it); root level lowered to INFO when it would drop records.
- `deploy/logrotate.d/img2text`: daily, compress, delaycompress, missingok,
  notifempty, maxage 30, create 0640 appuser appuser (host/VM deploys; container
  logs go stdout).
- Test: `tests/test_logging.py::test_log_rotation_config_applied` (monkeypatched
  tmp path, maxBytes=100, backupCount=3; multi-record writes → rotate + backups ≤3).

## T7 — #16 / AC7: admin bootstrap idempotency

- `server/app/services/admin_bootstrap.py::bootstrap_admin`:
  - existing + prod + `role != "admin"` → `RuntimeError("…exists but is not superuser")`
    (privilege-escalation guard; model has no `is_superuser` column — `role` is the flag).
  - existing + prod + password mismatch (`verify_password`) → update hash.
  - audit: `RequestLog(method="BOOTSTRAP", path="/internal/admin-bootstrap", status=200,
    ip="internal", user_id=…)` on create AND on prod password update (spec allows reuse).
  - non-prod existing → unchanged no-op.
- Tests: `tests/test_admin_bootstrap.py` + spec's two prod tests (user lookup by
  email instead of hard-coded id 1 — assumption fix, same assertion).

## Commit map

1. `feat(email): SMTP failures surface to caller; gate returns 503 on DB error`
2. `feat(storage): add get_range; export download supports Range header`
3. `feat(security): validate password length ≤72 bytes for bcrypt`
4. `chore(backup): add daily pg_dump cron + restore docs`
5. `chore(fonts): add Noto CJK for Vietnamese PDF render`
6. `feat(logging): add RotatingFileHandler + logrotate config`
7. `feat(admin): bootstrap updates password on env change; audit log + prod guard`
