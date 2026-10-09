# Phase 1: Version storage + incremental sync + conflict — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended). Steps use checkbox (`- [ ]`).

**Goal:** Foundation subsystem — document version history, incremental layout sync (0 LLM) when raw text is edited, staleness/conflict detection, restore/undo API.

**Architecture:** `document_versions` table stores per-(job,kind) snapshots (S3 object + metadata). `jobs.text_version` tracks text edits. Save-text endpoint persists text + incrementally patches md-layout + docx.html (text-node replace), returns only after persist (atomic per-layout). Conflict when layout `detached` (edited directly) — UI confirms overwrite. Restore = write old snapshot as new version.

**Tech Stack:** FastAPI + SQLAlchemy async, PostgreSQL, S3 storage (existing StorageDriver put/get/exists), pytest.

**Spec:** `docs/superpowers/specs/2026-10-10-redesign-editor-versioning-design.md` (Sub-system A). Read it first.

## Global Constraints

- Kinds: `text` | `md-layout` | `docx-layout` (+ treat `docx.html` as the docx-layout editable artifact).
- Artifacts live at `exports/{job_id}/{fmt}` via existing `storage.put/get/exists`.
- N = 20 versions per (job, kind), auto-prune oldest.
- Incremental sync: md-layout = plain-text replace; docx.html = replace within HTML text nodes (preserve tags). No LLM call.
- Endpoint returns ONLY after text + successful layouts persisted (atomic per-layout; failed layout → not updated, flagged `needs_render`, no partial).
- Conflict: layout `detached=True` → sync does NOT overwrite; return conflict for UI confirm.
- Optimistic lock: save uses expected `text_version`; mismatch → 409.
- Vietnamese log/error strings; R-style: no weakened assertions.
- Test DB: `DATABASE_URL="postgresql+asyncpg://img2text:img2text@localhost:5436/img2text_test"`, `cd server && PYTHONPATH="$PWD" .venv/bin/python -m pytest ...`

## Review Focus

- **Atomicity**: text saved but layout replace half-applied → must not leave md synced + docx stale silently (per-layout flag, no cross-artifact false success).
- **Text-node replace correctness**: docx.html replace must not corrupt HTML (only text nodes, not attribute/tag content); nested tags handled.
- **Version prune**: keep exactly N; race between concurrent saves.
- **Restore**: restoring creates NEW version (history append-only), doesn't delete.
- **First version**: existing jobs have no `document_versions` — lazy-seed current text/layout as version 1 on first access.

---

### Task 1: Model + migration

**Files:** `server/app/core/models.py` (+`DocumentVersion`), migration SQL note. Test DB ALTER.

**Interfaces:** `DocumentVersion(id, job_id, kind, storage_key, version, based_on_text_version, detached, created_at)`; `jobs.text_version int DEFAULT 0`.

- [ ] Apply migration (dev + test DB): `document_versions` table + `jobs.text_version`.
- [ ] Red test: DocumentVersion row CRUD + unique (job_id, kind, version).
- [ ] Implement model. Green. Commit.

### Task 2: Version storage service

**Files:** `server/app/services/doc_versions.py` (new).

**Interfaces:** `save_version(storage, job_id, kind, data: bytes, based_on_text_version, detached) -> DocumentVersion` (writes S3 object `versions/{job_id}/{kind}/{n}`, inserts row, prunes >N); `latest_version(session, job_id, kind) -> DocumentVersion | None`; `read_version(storage, job) -> bytes`; `seed_current(...)` lazy-seed.

- [ ] Red tests: save bumps version, writes S3, prunes to N (delete old rows + S3), latest returns newest.
- [ ] Implement. Green. Commit.

### Task 3: Incremental sync (replace in artifacts)

**Files:** `server/app/services/layout_sync.py` (new).

**Interfaces:** `sync_md_layout(md_text, old, new, count) -> str | None` (None = not found); `sync_docx_html(html, old, new) -> str | None` (HTMLParser text-node replace); `sync_job_layouts(storage, job_id, old, new) -> dict` returns per-kind `synced: bool`.

- [ ] Red tests: md replace count; docx.html replace inside `<span>text</span>` preserves tags; not-found → synced=False (needs_render); nested tags.
- [ ] Implement (use `html.parser` or regex-safe text-node walk). Green. Commit.

### Task 4: Extraction API (save-text + sync + conflict + versions + restore)

**Files:** `server/app/routers/jobs.py` (+ endpoints), `server/app/services/layout_sync.py` orchestration.

**Interfaces:**
- `GET /api/jobs/{id}/extraction` → text (seeded from result regions), text_version.
- `POST /api/jobs/{id}/extraction` body `{text, old_phrase, new_phrase, expected_text_version}` → 200 `{synced:{md,docx}, needs_render:[...]}` | 409 conflict (version mismatch or detached). Persist text (result + S3 snapshot + text_version++), then per-layout sync + snapshot.
- `GET /api/jobs/{id}/versions?kind=` → list.
- `POST /api/jobs/{id}/versions/{vid}/restore` → 204 (new version from old snapshot).

- [ ] Red tests: save+sync 200; detached conflict 409; version mismatch 409; needs_render on not-found; restore appends version; lazy-seed on first GET.
- [ ] Implement. Green. Commit.

### Task 5: Full suite gate

- [ ] Full server suite `pytest -q`. Pre-existing fails ONLY: `test_env_parity`, `test_kaggle_orchestrator::test_stage_kernel_substitutes_owner_ref_accelerator`. Fix regressions. Commit if needed.

### Task 6: Detach hook (layout edited directly)

**Files:** mark `detached=True` + snapshot when `PUT md-layout/content` / `PUT docx-layout/html` (existing endpoints in jobs.py/exports.py) fire.

- [ ] Red test: PUT md-layout content → latest md-layout version detached=True.
- [ ] Implement. Green. Commit.
