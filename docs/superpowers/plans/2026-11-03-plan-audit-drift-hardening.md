# Plan — Audit drift + hardening (2026-11-03)

Spec: `docs/superpowers/specs/2026-11-03-audit-drift-hardening-design.md` (AC1–AC8).
Branch: none — work lands on `master`; all 24 existing branches are already merged
(`git branch --no-merged master` → empty).
Full test command once Postgres is up:

```
docker compose -f deploy/docker-compose.test.yml up -d --wait
cd server && DATABASE_URL="postgresql+asyncpg://img2text:img2text@localhost:5433/img2text_test" .venv/bin/pytest -q
cd web && npx tsc -b --force && npx vitest run
```

`:5433` is down right now, so AC7 only reaches "compiles + imports" and is reported UNVERIFIED.
Do not start Docker in a lane: the dev container publishes :5433 as well, they collide.

## Accepted deviations

- Full TDD red→green is **not** applicable to AC1–AC6: they are config/doc/schema files with no
  unit-test observer. Each lane's row states the concrete verification instead.
- AC7 is written test-first (correct TDD order) but cannot be executed, so the red state cannot be
  confirmed. Report that explicitly instead of implying a pass.
- The 5 lanes run **in parallel via subagents**, partitioned by disjoint file sets (no contention):
  A `docs/migrations/`, B `.github/workflows/`, C `docs/` + `deploy/`, D `server/`, E `web/`.

## Lane A — missing migration (AC1)

1. Read `docs/migrations/2026-10-16_worker_sessions.sql` for the comment/header format.
2. Create `docs/migrations/2026-11-03-missing-columns.sql` with:
   - `ALTER TABLE users ADD COLUMN IF NOT EXISTS ocr_enabled BOOLEAN NOT NULL DEFAULT false;`
   - `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS preprocess TEXT;`
   - `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS output_format TEXT DEFAULT 'md';`
   - `ALTER TABLE jobs ADD COLUMN IF NOT EXISTS layout_style TEXT;`
   - `CREATE TABLE IF NOT EXISTS worker_heartbeats (...)` — columns copied from `models.py:400-419`.
3. Verify: `rg -c "IF NOT EXISTS"` = 13 and `rg -c "^ALTER TABLE\|^CREATE TABLE"` = 12.
4. Scope widened by the parent after lane A reported back: `jobs.mode`, `jobs.text_version`,
   `jobs.rerender_requested`, `jobs.kaggle_ref`, `jobs.failed_step`, `jobs.ir_json`,
   `jobs.filename` have **no** `.sql` either (only comments in `models.py` or a `.md`), so they
   belong in the same idempotent file. Columns already covered by an existing `.sql`
   (`daily/weekly_page_limit`, `upload_byte_limit`, `auto_purge`, `purge_notice_seen`,
   `upload_bytes`, `storage_purged_at`, `session_id`, `worker_token_hash`, `is_verified`,
   `password_reset_code`) must **not** be repeated.
5. Do **not** delete `2026-10-14-worker-heartbeats.md`; keep it as a note. The `.sql` is what CI runs.

## Lane B — CI (AC2)

1. `web` job: add `npx oxlint` after `npx tsc -b --force`. Run it first; if it exits non-zero,
   report and do **not** touch app code.
2. New `worker` job: setup-python 3.11 + `cache-dependency-path: worker/pyproject.toml`,
   `pip install -e "./worker[test]"`, `working-directory: worker`, `pytest -q`,
   `timeout-minutes: 20`.
3. Verify: YAML parses via `python3 -c "import yaml, ..."`.

## Lane C — doc drift (AC3, AC4, AC5)

1. `docs/e2e-checklist.md`: delete section J; rewrite I5 (inline edit through `md-editor`, `/edit`
   gone), K2 (match actual `btn-edit-doc` behaviour), mark M3-web obsolete pointing at M4-tiptap.
2. `docs/SPEC-ui-redesign.md:254-259`: tick P0–P5 + add
   `> Shipped (verified 2026-11-03: route + page in web/src/App.tsx).`
3. `deploy/.env.example:70` + `deploy/.env.dev.example:33`: `KAGGLE_MODE=session` (config.py:112;
   batch = deprecated). `deploy/.env.example:107`: replace the dead `ADD COLUMN layout_style`
   pointer with `docs/migrations/2026-11-03-missing-columns.sql`.
4. Verify: `git diff --stat` shows exactly those 4 files.

## Lane D — drop alembic + test the untested endpoint (AC6, AC7)

1. `rg -n alembic --glob '!*.lock' .` → only pyproject → remove that line.
2. Read `conftest.py` (`client` fixture ~:281), `test_output_format.py`, `test_export_md_layout.py`,
   endpoint `exports.py:729`, `render_html_spec.py`.
3. Write `server/tests/test_preview_layout_html.py`:
   (a) `done` job with a 1-column result → 200 + `text/html` + page text present;
   (b) another user's job → 403, unknown id → 404 (copy the style of `test_jobs_read.py:120`);
   (c) `queued` job → whatever status the endpoint actually returns (read the code, do not guess).
4. Verify: `.venv/bin/python -m py_compile tests/test_preview_layout_html.py` +
   `.venv/bin/python -c "import app.main"`.

## Lane E — lang attribute (AC8)

1. `web/src/i18n/index.tsx`: set `document.documentElement.lang = lang` from state/`setLang`
   (smallest change; no new provider).
2. `web/index.html`: keep `lang="en"` (equals the `readLang()` default); do not switch it to `vi`.
3. Test: extend the existing i18n test, or add `web/tests/i18n.test.tsx` asserting
   `document.documentElement.lang === "vi"` after switching.
4. Verify: `npx tsc -b --force` + `npx vitest run <file>`.

## Round-1 review findings (2026-11-03)

### Accepted
1. **NOT NULL divergence — `jobs.rerender_requested`**
   - Migration had `BOOLEAN DEFAULT false` (nullable). Model: `Mapped[bool]` with `server_default=text("false")` → NOT NULL. Fixed in `docs/migrations/2026-11-03-missing-columns.sql:33` to `BOOLEAN NOT NULL DEFAULT false`.

2. **False completion tick — `SPEC-ui-redesign.md` P1**
   - Spec §3.1 defines 3 components (`JobOverview`/`JobText`/`JobLayout`). Reality: 3 routes exist in `web/src/App.tsx` but ALL render single `JobDetail` with `section` prop. Unchecked P1 at line 255; added caveat note. This supersedes Lane C step 2 ("tick P0–P5") for P1 only — P0/P2–P5 stay ticked.

### Rejected (false positives)
1. **Claimed `tests.test_jobs_read` import error**
   - Reviewer alleged `from tests.test_jobs_read import other_client` fails. Evidence: `tests/__init__.py` exists; `other_client` defined at `server/tests/test_jobs_read.py:14`; imported successfully by 5+ test files (e.g. `server/tests/test_layout_editor.py:22`). Import works.

2. **Claimed `jobs.filename` duplicate coverage**
   - Reviewer claimed a `.sql` migration already covers `jobs.filename`. Evidence: only `docs/migrations/2026-10-14-jobs-filename.md` (markdown note) exists; CI runs `docs/migrations/*.sql` only. Plan Lane A step 4 correctly notes “no `.sql`”. No duplicate.

---

## Approval-gated — do NOT execute (each needs explicit user approval)

| # | Action | Why it needs approval |
|---|---|---|
| G1 | `DROP TRIGGER pw_watch_trg ON users; DROP FUNCTION pw_watch_fn(); DROP TABLE pw_watch;` in `img2text_dev` | deletes DB objects; leftover debug artefact from the Oct 23 session |
| G2 | Delete Kaggle dataset `jhandf/img2text-wheelbuild-env` (4.35 GB) + kernels `img2text-wheelbuild`, `img2text-mounttest` | irreversible |
| G3 | Delete the 24 branches already merged into `master` | removes refs (commits stay in master) |
| G4 | Delete `.worktrees/plan-auth/`, `.worktrees/plan-pr/` (orphans; absent from `git worktree list`) | deletes directories |
| G5 | Apply `2026-11-03-missing-columns.sql` to `img2text_dev` / prod | mutates a real schema |
| G6 | Start Postgres test :5433 to run AC7 and confirm the newline fix (`layout_spec.py:~370`) | needs Docker; collides with the dev container on the same port |

## Still-open questions (carried over from earlier sessions)

1. Split `/jobs/:id/layout/md` and `/layout/word` into separate routes (~8 tests would change)?
2. Add an original-image panel to the Text page (`/text`)?
3. Narrow the right column on Overview?
4. Rename/split branch `bench/ir-structure` → `feat/layout-spec-no-llm`?

## Execution order

Lanes A, B, C, D, E in parallel → parent reviews each diff → run the shared verification
(`py_compile` + `tsc` + `vitest`) → update `MEMORY.md` → report G1–G6 awaiting approval.
