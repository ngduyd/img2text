# Kaggle Batch One-Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Kaggle kernel run processes ALL queued jobs (N files staged, per-job outputs), instead of 1 run per job.

**Architecture:** `_batch_runs` keyed by ref (run-level, `job_ids` list); staging prefixes files `{job_id}__{name}`; kernel loops inputs writing `{job_id}_result.{json,md}`; ingest reads per-job file; partial-fail per job. Config `kaggle_batch_max_jobs` (default 20).

**Tech Stack:** FastAPI + SQLAlchemy async, pytest; Python kernel script (stdlib+existing deps). No DB migration.

**Spec:** `docs/superpowers/specs/2026-10-09-kaggle-batch-one-run-design.md` (in worktree; read it first)

## Global Constraints

- File naming: staged input `{job_id}__{orig_name}`; kernel outputs `{job_id}_result.json` + `{job_id}_result.md` in `/kaggle/working`.
- Verify-before-push: ALL staged filenames present in `dataset_list_files` before `kernels_push`; missing → no spawn, retry next tick.
- Partial-fail: job missing/unparsable output → that job `failed` + `failed_step=extracting` + specific `error`; other jobs ingest normally.
- Run-level fail (`failed`/`error`/`cancelled`/`timeout`): ALL jobs in run → `failed` + `failed_step=extracting` + `error=f"Kaggle kernel {status}"`. `kaggle_timeout`/ingest-giveup → ALL jobs revert `queued`.
- Single-active-run guard + min_gap + poison-guard semantics preserved.
- Adopt: group extracting jobs by `kaggle_ref` → one run entry per ref.
- Kernel: per-input exception → log + continue; exit 0 if ≥1 output written, else exit 1.
- Test DB: `DATABASE_URL="postgresql+asyncpg://img2text:img2text@localhost:5436/img2text_test"`, `cd server && PYTHONPATH="$PWD" .venv/bin/python -m pytest ...`
- TDD red→green; never weaken assertions (spec changes documented in commit body).
- Vietnamese log strings consistent with existing style.

## Review Focus

- **Ref-drop ordering**: ingest per job must not drop the whole run ref while some jobs still pending retry-next-tick (transient kernels_output failure).
- **Poison job in batch**: one job's validation error must not burn the whole batch (partial-fail isolation vs `_INGEST_MAX_FAILURES` interplay).
- **Spawn transaction**: crash between UPDATE extracting and `_batch_runs` insert → adopt must recover the whole group (all jobs same ref).
- **Kernel continue-on-error**: exception in job 2's OCR must still write job 1/3 outputs; exit code semantics honored.
- **Adopt grouping edge**: jobs from an OLD finished ref (stale kaggle_ref on done/failed) must not be adopted (status gate `extracting` only).

---

### Task 1: Config + `_batch_runs` shape refactor

**Files:**
- Modify: `server/app/core/config.py` (+`kaggle_batch_max_jobs: int = 20`, env `KAGGLE_BATCH_MAX_JOBS`)
- Modify: `server/app/services/kaggle_orchestrator.py` (`_batch_runs: dict[str, dict]` keyed by ref)
- Test: `server/tests/test_kaggle_batch_orchestrator.py`

**Interfaces:**
- Produces: `_batch_runs: dict[str, dict]` where value = `{"ref": str, "pushed_at": float, "job_ids": list[int], "ingest_failures": int}`.

- [ ] **Step 1:** Red test: tracked run keyed by ref; poll iterates refs (existing happy-flow test adapted).
- [ ] **Step 2:** Refactor all `_batch_runs` access sites (spawn/adopt/poll/timeout/fail paths) to ref-keyed shape. Update existing tests to new shape WITHOUT weakening behavior asserts.
- [ ] **Step 3:** Subset green: `pytest tests/test_kaggle_batch_orchestrator.py -q`.
- [ ] **Step 4:** Commit.

### Task 2: Multi-job spawn (staging + verify + mark)

**Files:**
- Modify: `server/app/services/kaggle_orchestrator.py` (`_ensure_batch_runs` select ALL queued up to cap; `_spawn_batch_run(jobs: list[Job])`)
- Modify: `deploy/.env.example` / `.env.dev` (+`KAGGLE_BATCH_MAX_JOBS`, parity test in `tests/test_env_parity.py` if it checks config fields)
- Test: `server/tests/test_kaggle_batch_orchestrator.py`

**Interfaces:**
- Produces: `_spawn_batch_run(api, session_factory, jobs: list[Job]) -> bool` — stage `{job.id}__{name}` for each; `dataset_list_files` must contain ALL; push; single transaction UPDATE all jobs → `extracting` + same `kaggle_ref`; insert one `_batch_runs[ref]` entry with `job_ids`.

- [ ] **Step 1:** Red tests: (a) 3 queued → staged names contain `1__a.jpg,2__b.png,3__c.pdf` + all marked extracting with SAME ref + one map entry; (b) verify missing 1 file → no push, no status change; (c) queue > cap → only cap staged, rest stay queued.
- [ ] **Step 2:** Implement staging prefix + all-or-nothing verify + batch UPDATE.
- [ ] **Step 3:** Subset green.
- [ ] **Step 4:** Commit.

### Task 3: Poll + per-job ingest + partial-fail

**Files:**
- Modify: `server/app/services/kaggle_orchestrator.py` (`_poll_batch_run` iterates `run["job_ids"]`; `_ingest_batch_result(api, session_factory, job_id, ref)` reads `{job_id}_result.json`)
- Modify: `deploy/kaggle/kernel/img2text_batch.py` (`find_inputs() -> list[tuple[job_id, path]]`; loop; `{job_id}_result.{json,md}`; continue-on-error; exit code)
- Test: `server/tests/test_kaggle_batch_orchestrator.py`; kernel unit test for `find_inputs` parse (import module, tmp paths)

**Interfaces:**
- Produces: kernel `find_inputs()` sorted, job_id from `{id}__` prefix, non-prefixed/unknown-ext skipped. `_ingest_batch_result` pulls output once per run (cache out_dir per ref across jobs? YAGNI: pull per job — Kaggle API download per job acceptable; choose pull-once-per-ref in run dict if trivial).

- [ ] **Step 1:** Red tests: (a) success + 3 outputs → 3 jobs leave extracting (→ rendering via store); (b) missing job 2 output → job2 failed+extracting+error, jobs 1/3 fine; (c) cancelled → all failed+extracting+error; (d) kernel test: `find_inputs` parses prefix/sorted/skips dirs; non-prefixed input → skipped (log).
- [ ] **Step 2:** Implement kernel loop + ingest per-job read.
- [ ] **Step 3:** Subset green.
- [ ] **Step 4:** Commit.

### Task 4: Adopt grouping + timeout/giveup batch revert

**Files:**
- Modify: `server/app/services/kaggle_orchestrator.py` (adopt group-by-ref; timeout + ingest-giveup revert ALL `job_ids`)
- Test: `server/tests/test_kaggle_batch_orchestrator.py`

- [ ] **Step 1:** Red tests: (a) 2 extracting jobs same ref, empty map → one entry with both ids, no new spawn while live; (b) kaggle_timeout → all job_ids queued; (c) ingest give-up (fail N times) → all job_ids queued (drop ref); (d) jobs with done/failed status + stale ref NOT adopted.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Subset green.
- [ ] **Step 4:** Commit.

### Task 5: Full suite gate

- [ ] **Step 1:** Full server suite `pytest -q` (~31 min). Expected pre-existing fails ONLY: `test_env_parity` (unless Task 2 changed env parity — then fix test in same task), `test_kaggle_orchestrator.py::test_stage_kernel_substitutes_owner_ref_accelerator`.
- [ ] **Step 2:** Fix regressions without weakening; commit if needed.

### Task 6: Kernel push + smoke (manual/integration)

- [ ] **Step 1:** Push kernel: `api.kernels_push('deploy/kaggle/kernel')` from container → new version.
- [ ] **Step 2:** Integration smoke (dev): reset 2 jobs to queued → tick spawns ONE run staging both → report kernel link + run state for user to Run on Kaggle web (or auto-run if available). Document outcome in task report.
