# Job Status Phases + Per-Step Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `running` into `extracting`/`rendering` phases, persist kernel ref so restart never orphans a job, and add a unified per-step retry + retry buttons everywhere.

**Architecture:** `jobs.status` (TEXT) gains two values between `queued` and `done`; two new TEXT columns `kaggle_ref` (restart recovery: orchestrator adopts `extracting` jobs each tick) and `failed_step` (retry target). Server transitions + one unified `POST /jobs/{id}/retry`; web maps 5 labels/chips and renders retry buttons on every failed position.

**Tech Stack:** FastAPI + SQLAlchemy (async), PostgreSQL, pytest; Vite + React + vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-09-job-phases-retry-design.md`

## Global Constraints

- Statuses: exactly `queued` | `extracting` | `rendering` | `done` | `failed` (`running` value is eliminated).
- Labels (Vietnamese, exact): `queued`="Đang lập lịch", `extracting`="Đang trích xuất văn bản", `rendering`="Đang dựng layout", done/failed unchanged.
- Retry rule: only `failed` jobs (else 409). `failed_step=extracting` → reset to `queued`. `failed_step=rendering` → re-run `auto_generate_output`, success → `done`.
- Auto-gen result rule: BOTH formats fail → `failed` + `failed_step=rendering`; at least one OK → `done`.
- Proofread stays fire-and-forget; never flips status.
- Migration: `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kaggle_ref TEXT;` + `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_step TEXT;` on dev DB (`img2text_dev` @ :5433) and test DB (`img2text_test` @ :5436) before running tests.
- Test DB isolation (R33): server tests run with `DATABASE_URL="postgresql+asyncpg://img2text:img2text@localhost:5436/img2text_test" PYTHONPATH="$PWD" server/.venv/bin/python -m pytest ...` — never the dev DB.
- R59: every UI mutation → toast. R51: existing testids adjust-only, never delete.
- Copy: zero visible em-dash; radius 6/8px only; tokens from `web/DESIGN.md`.
- TDD: red → green per task; never weaken an existing assertion (adjust only when spec changes behavior — note in commit).
- Scratch cleanup: delete untracked `server/_show_ir.py`, `server/_ir_sample.md`, `server/_ir1.json` (approved).

## Review Focus

- **Restart mid-kernel**: server restarts while a kernel runs → job must resume ingest, not hang (test: adopt path).
- **Reaper scope**: reaper/revert currently targets `running` → must target `extracting`; missed spot = job stuck forever (test: revert WHERE).
- **Retry abuse**: retry on non-failed job must 409 (test: 409 on queued/done).
- **Auto-gen partial failure**: one format OK, other down → must still `done`, not `failed` (test: partial OK → done).
- **Web union exhaustiveness**: adding 2 statuses to `JobStatus` breaks every switch/map → tsc must stay green and all 5 labels resolve (test: label map 5 keys).

---

### Task 1: Server — columns + status transitions

**Files:**
- Modify: `server/app/core/models.py` (Job model: `kaggle_ref`, `failed_step`)
- Modify: `server/app/services/kaggle_orchestrator.py:447` (spawn mark), `_FAILED_STATUSES` handling, revert sites (:488)
- Modify: `server/app/services/jobs_requeue.py:24`
- Modify: `server/app/services/job_results.py` (ingest → `rendering`; auto-gen completion → `done`/`failed`+`failed_step`)
- Modify: any other `status="running"` writes (grep `running` under `server/app`)
- Test: `server/tests/test_kaggle_batch_orchestrator.py`, `server/tests/test_output_format.py` (update transitions)

**Interfaces:**
- Consumes: existing `_batch_runs`, `_spawn_batch_run`, `auto_generate_output(job, storage)`.
- Produces: `Job.kaggle_ref: str | None`, `Job.failed_step: str | None`; `auto_generate_output` returns `bool` (True = ≥1 format OK).

- [ ] **Step 1: Migration** — run both ALTERs on dev + test DB; verify `\d jobs` shows columns.
- [ ] **Step 2: Red tests** — write failing tests: (a) spawn marks `extracting` + stores `kaggle_ref`; (b) ingest success → `rendering`, auto-gen OK → `done`; (c) kernel `cancelled`/`failed` → `failed` + `failed_step=extracting`; (d) auto-gen both-fail → `failed` + `failed_step=rendering`; (e) auto-gen partial OK → `done`.
- [ ] **Step 3: Run red** — expect failures (columns/status values unknown).
- [ ] **Step 4: Implement** — model columns; replace every `running` write with `extracting`; `_FAILED_STATUSES` path sets `failed`+`failed_step="extracting"` (supersedes revert-and-respawn from `2263d24`); `_store` sets `rendering`; task in `_schedule_auto_output` sets `done` or `failed` per return bool of `auto_generate_output`.
- [ ] **Step 5: Sweep** — `grep -rn "running" server/app` → zero status uses remain; update fixtures asserting `running`.
- [ ] **Step 6: Run green** — orchestrator + output_format + jobs_requeue subsets pass.
- [ ] **Step 7: Delete scratch files** (`server/_show_ir.py`, `server/_ir_sample.md`, `server/_ir1.json`) + commit.

### Task 2: Server — restart recovery (adopt) + reaper scope

**Files:**
- Modify: `server/app/services/kaggle_orchestrator.py` (`_ensure_batch_runs`, revert WHERE)
- Modify: `server/app/services/jobs_requeue.py` (WHERE includes `extracting`)
- Test: `server/tests/test_kaggle_batch_orchestrator.py`

**Interfaces:**
- Produces: `_ensure_batch_runs(api, session_factory) -> bool` also adopts: SELECT `extracting` jobs with `kaggle_ref IS NOT NULL` AND id not in `_batch_runs` → `_batch_runs[id] = {"ref": ..., "pushed_at": ...}`.

- [ ] **Step 1: Red test** — simulate restart: `_batch_runs` empty, job row `status="extracting"`, `kaggle_ref="jhandf/img2text-batch-v2:123"`; run `_ensure_batch_runs`; assert job now in `_batch_runs` with that ref → poll resumes (and eventually ingest).
- [ ] **Step 2: Red test** — `extracting` job WITHOUT `kaggle_ref` → reaper reverts to `queued`.
- [ ] **Step 3: Implement** adopt query + reaper WHERE (`status IN ('queued', 'extracting')` revert rules: lease-expired queued unchanged; extracting-without-ref → queued).
- [ ] **Step 4: Green** — orchestrator + reaper subsets pass.
- [ ] **Step 5: Commit.**

### Task 3: Server — unified retry endpoint

**Files:**
- Modify: `server/app/routers/jobs.py` (add `POST /api/jobs/{id}/retry`)
- Test: `server/tests/test_jobs_retry.py` (new)

**Interfaces:**
- Produces: `POST /api/jobs/{id}/retry` → 204. 404 unknown job; 409 if `status != "failed"`; branch on `failed_step`:
  - `extracting` (or NULL → default) → UPDATE `status='queued'`, `failed_step=NULL`, `lease_expires_at=NULL`, `error=NULL`; spawn happens on next orchestrator tick (batch mode).
  - `rendering` → keep `failed` while running, re-run `auto_generate_output` fire-and-forget → set `done`/`failed` same rule as Task 1.
- Existing `POST /jobs/{id}/retry-layout` and `POST /jobs/{id}/requeue` unchanged.

- [ ] **Step 1: Red tests** — retry on failed+extracting → 204, status `queued`; failed+rendering → 204 → (await task) status `done`; queued → 409; done → 409; unknown → 404; authz matches other job endpoints.
- [ ] **Step 2: Implement endpoint.**
- [ ] **Step 3: Green** — new file + full jobs router tests pass.
- [ ] **Step 4: Commit.**

### Task 4: Server — full suite gate

- [ ] **Step 1: Full suite** — `DATABASE_URL=...img2text_test PYTHONPATH="$PWD" server/.venv/bin/python -m pytest -q` (~19 min).
- [ ] **Step 2: Fix regressions** (label/status assertions in old tests) without weakening assertions beyond spec changes; document each in commit body.
- [ ] **Step 3: Commit** if fixes needed.

### Task 5: Web — status labels, types, filters, stats

**Files:**
- Modify: `web/src/lib/status.ts` (5-label map + status→chip color/class map)
- Modify: `web/src/api/types.ts:47` `JobStatus = "queued" | "extracting" | "rendering" | "done" | "failed"`
- Modify: `web/src/components/StatusFilterTabs.tsx` (options + counts)
- Modify: `web/src/pages/Jobs.tsx` (stats: pending bucket = queued+extracting+rendering)
- Test: `web/tests/...` status + Jobs tests

**Interfaces:**
- Produces: `STATUS_LABELS: Record<JobStatus, string>` (exact Vietnamese strings from Global Constraints); chip class per status using DESIGN.md tokens (extracting and rendering get distinct hues).

- [ ] **Step 1: Red tests** — label map has exactly the 5 exact strings; filter tabs render 5; stats bucket sums.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Green** — `cd web && npm test`.
- [ ] **Step 4: `npx tsc --noEmit`** — exhaustive switch/map errors fixed (all 5 statuses handled everywhere `running` was).
- [ ] **Step 5: Commit.**

### Task 6: Web — retry buttons

**Files:**
- Modify: `web/src/api/client.ts` (add `retryJob(id)` → `POST /api/jobs/{id}/retry`)
- Modify: `web/src/components/JobRow.tsx` (failed → `btn-retry-job` button)
- Modify: `web/src/pages/JobDetail.tsx` (failed status area → same button)
- Test: `web/tests/components/JobRow.test.tsx` (or file where JobRow tests live), JobDetail tests

**Interfaces:**
- Consumes: `retryJob(id: string): Promise<void>`; toast via existing toast util (R59).
- Behavior: click → `retryJob` → success toast "Đã lên lịch chạy lại" → refetch jobs list/detail. `btn-retry-layout` in UnifiedEditor unchanged.

- [ ] **Step 1: Red tests** — failed JobRow shows `btn-retry-job`; click → POST called + toast + refetch; non-failed rows have no button.
- [ ] **Step 2: Implement client + buttons.**
- [ ] **Step 3: Green** — `cd web && npm test && npx tsc --noEmit && npm run build`.
- [ ] **Step 4: Commit.**

### Task 7: Integration gate

- [ ] **Step 1:** Server full suite + web full suite both green on final state.
- [ ] **Step 2:** Manual smoke: dev stack up, existing job 3 → after deploy set `kaggle_ref=NULL, status='queued'` (one-off requeue) OR observe Task-2 reaper path; Jobs page shows 5 chips + retry on failed.
- [ ] **Step 3:** Commit any fixes; report.

## Deploy notes (prod)

```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kaggle_ref TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS failed_step TEXT;
```
