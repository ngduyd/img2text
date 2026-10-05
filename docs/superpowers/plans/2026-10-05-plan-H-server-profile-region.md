# Plan H — Server: Profile + Region Edit

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Two small auth/jobs endpoints backing the new UI: profile self-service (change email/password) and per-region content edit.

**Architecture:** Additive routes on existing FastAPI app. No schema changes (region text lives in jobs.result JSONB; password rehash + refresh revoke reuse existing paths). R33 lesson: this lane gets isolated test DB (compose project `plan-h`, port 5435, db img2text_test_h, DATABASE_URL prefix on every pytest run).

**Tech Stack:** Plan A–G stack (FastAPI/SQLAlchemy/PyJWT/bcrypt). Tests: pytest + httpx ASGI, real Postgres.

**Spec:** docs/superpowers/specs/2026-10-04-img2text-mvp-design.md §4 (result JSONB), §8 (auth/jobs API), §10 (editing).

## Global Constraints

- R33 MANDATORY: `DATABASE_URL=postgresql+asyncpg://img2text:img2text@localhost:5435/img2text_test_h` on every pytest run; postgres `plan-h-postgres-test-1` via `docker compose -p plan-h -f deploy/docker-compose.test.yml up -d --wait` with local uncommitted override (port 5435, POSTGRES_DB img2text_test_h — lane-local, NOT committed).
- Email normalize `strip().lower()` + uniqueness (reuse `_EmailIn` validator pattern from auth.py register/login/forgot).
- Password change revokes ALL user refresh tokens (same helper password-reset uses).
- `current_password` required for BOTH email and password changes (401 wrong — same message as login wrong password).
- JSONB region edit: update `result.pages[*].regions[*].text` by region id (p{N}r{M}) AND attempt string-replace of old text in `result.edited_markdown or result.markdown` (count=1; if absent, region updates only + response flags `markdown_replaced: false`). done-only jobs; owner-only.
- TDD red→green per task; single commit per task; never weaken assertions.

## Review Focus

- Password change → old refresh dead (test via /api/auth/refresh 401).
- Email change → login works with NEW email, old fails; duplicate → 409.
- Region edit 404 unknown region / 403 other user / 409 not-done; JSONB write survives concurrent structure (pages array shape intact).
- current_password wrong → 401 for BOTH operations (no enumeration).

---

### Task 1: PATCH /api/auth/profile

**Files:**
- Create: `server/app/routers/profile.py`, `server/tests/test_profile.py`
- Modify: `server/app/main.py` (mount router), `server/app/routers/auth.py` (export revoke-all helper if private)

**Interfaces:**
- Produces: `PATCH /api/auth/profile` body `{current_password: str, email?: str, new_password?: str}` — at least one of email/new_password required (422 otherwise); auth via get_current_user; verify current_password (401 `"Sai mật khẩu."`); email path: normalize + unique (409 `"Email đã tồn tại."`) → update; new_password path: min 8 (422) → rehash + revoke all refresh tokens; respond `{id, email, role, ocr_enabled}` (same shape as /me).

- [ ] **Step 1: Failing tests** `server/tests/test_profile.py`:
  - change password: old refresh dead (capture refresh cookie → change → /api/auth/refresh → 401), login with new password 200, old password 401.
  - change email: login works with new email, old 401; duplicate other user's email → 409 `"Email đã tồn tại."`.
  - wrong current_password → 401 (both paths parametrized).
  - neither field → 422.
  - response shape equals /me shape.
- [ ] **Step 2: Run → FAIL** (R33 prefix)
- [ ] **Step 3: Implement** per Interfaces (bcrypt via existing hash_password; revoke helper from auth.py)
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(server): profile self-service (email/password change)`

---

### Task 2: PATCH /api/jobs/{id}/regions/{rid}

**Files:**
- Create: `server/app/routers/region_edit.py`, `server/tests/test_region_edit.py`
- Modify: `server/app/main.py` (mount)

**Interfaces:**
- Produces: `PATCH /api/jobs/{id}/regions/{rid}` body `{text: str}` (non-empty ≤10k chars else 422); owner-only (`_job_or_403` from jobs.py); job done else 409; find region across result pages (unknown → 404); old = region.text; update region.text; markdown target = result.edited_markdown or result.markdown; if old non-empty and old in target: replace count=1 into edited_markdown (create key if missing) → `markdown_replaced: true`; else `markdown_replaced: false`; persist full result dict (copy-set-reassign JSONB pattern from patch_content); 200 `{"id": rid, "text": new, "markdown_replaced": bool}`.

- [ ] **Step 1: Failing tests** `server/tests/test_region_edit.py`:
  - happy path: seed done job with result (2 regions, markdown contains region text) → PATCH text → region.text updated + edited_markdown replaced once + response flags true.
  - old text absent from markdown → markdown_replaced false, region still updated.
  - unknown region → 404; other user → 403; queued job → 409; empty text → 422.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** per Interfaces
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** `feat(server): per-region content edit`

**Plan H done when:** both suites green R33-prefix; full suite green; commits on branch `plan-h-server`.
