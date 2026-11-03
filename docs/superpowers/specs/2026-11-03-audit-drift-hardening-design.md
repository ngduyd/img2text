# Spec: Audit drift + hardening (after 76 compaction summaries, Oct 4 → Oct 23)

Date: 2026-11-03
Status: draft — awaiting approval (5 code lanes already in flight, see plan)
Path: bounded — fixes measurable drift only, no new features

## Problem

Audit on 2026-11-03 (git state + 76 compaction summaries + `docs/superpowers/**` + two parallel
code scans) found four classes of issues. Every claim below has file:line evidence, none are
guesses.

1. **Schema is not reproducible from the repo.** `server/app/core/models.py` declares 8 tables and
   4 columns that `docs/migrations/` never creates or alters. There is no `.sql` for
   `users.ocr_enabled` (:38), `jobs.preprocess` (:237), `jobs.output_format` (:241),
   `jobs.layout_style` (:255). `worker_heartbeats` (:400) exists only as a `.md` file
   (`2026-10-14-worker-heartbeats.md:6`), but CI applies `docs/migrations/*.sql` only
   (`.github/workflows/ci.yml:57`). Consequence: a DB created by hand-SQL (not `create_all`)
   lacks the columns. The app survives via NULL fallbacks (`limit_of(NULL → default)`), so the
   failure is silent: per-user overrides simply stop working.
2. **CI lies about the README.** `README.md:67` claims `cd worker && pytest` runs in CI;
   `README.md:68` claims lint is `oxlint`. `ci.yml` only has a `server` job and a `web` job
   (`tsc + vitest + build`) — no worker job, no lint step.
3. **Doc drift.** `docs/e2e-checklist.md` is the project's only end-to-end gate, but 0/69 boxes
   are ticked and 4 items contradict the code: section J (:91) says "retired" yet keeps its box;
   I5 (:88) and K2 (:100) describe the `/edit` route that was removed (`App.tsx` keeps only a
   redirect); M3-web (:116) describes the iframe that Tiptap replaced. `docs/SPEC-ui-redesign.md:254-259`
   leaves P0–P5 unticked although all shipped.
4. **Exactly one route is untested.** 69 of 70 routes have coverage;
   `GET /api/jobs/{id}/preview/layout.html` (`exports.py:729`) has none
   (`rg preview server/tests/` → empty). It is also the endpoint that guarantees
   "preview matches the downloaded file", i.e. the most likely place to break silently.

Out of scope here (each needs separate user approval, see plan §Approval-gated): dropping the
`pw_watch` debug trigger in `img2text_dev`, deleting Kaggle datasets/kernels, deleting 24
already-merged branches, deleting 2 orphan worktree directories, applying migrations to a real DB.

## Intent

1. **Schema reproducible from the repo**: one idempotent `.sql` covering every missing column and
   table, so `create_all` (fresh DB) and hand-SQL (legacy DB) converge.
2. **CI checks what the README claims.** Add to CI rather than weaken the README — the README
   states the intent, CI is what is missing.
3. **The manual gate must be true**: the checklist describes current code, not deleted code.
4. **No new features, no refactors.** One finding ↔ one change; do not touch files outside scope.

## Acceptance criteria

| # | AC | Verify |
|---|---|---|
| AC1 | `docs/migrations/2026-11-03-missing-columns.sql` covers every model column/table that has no `.sql` counterpart — scoped 2026-11-03 to: `users.ocr_enabled`, `jobs.preprocess/output_format/layout_style/filename/mode/text_version/rerender_requested/kaggle_ref/failed_step/ir_json`, `worker_heartbeats`; every statement idempotent | `rg -c "IF NOT EXISTS"` = 13 (12 statements + 1 header line); `rg -c "^ALTER TABLE\|^CREATE TABLE"` = 12; applying twice must not error (CI `server` job runs this exact path) |
| AC2 | CI has a `worker` job running `pytest -q` and the `web` job has an `npx oxlint` step | YAML parses; `npx oxlint` exits 0 at the time it is added |
| AC3 | `docs/e2e-checklist.md` has no section J; I5/K2/M3-web match current code | `rg -n "/edit" docs/e2e-checklist.md` → only the "route was removed" sentence remains |
| AC4 | `docs/SPEC-ui-redesign.md` P0–P5 ticked + one verify line | read that section |
| AC5 | `deploy/.env.example` and `.env.dev.example` say `KAGGLE_MODE=session` matching `config.py:112`; migration pointer points at a real file | `rg -n KAGGLE_MODE deploy/` |
| AC6 | `server/pyproject.toml` no longer lists `alembic` | `rg -n alembic --glob '!*.lock' .` → 0 hits |
| AC7 | `server/tests/test_preview_layout_html.py` covers happy path + 403/404 + non-`done` job | `pytest tests/test_preview_layout_html.py` (needs Postgres :5433) |
| AC8 | `document.documentElement.lang` follows the selected i18n language | `npx tsc -b --force` + `npx vitest run` in `web` |

## Constraints

- `pytest` **cannot run** while this work happens: Postgres `:5433` is down. AC7 can only reach
  "compiles + imports"; it must be reported as UNVERIFIED until the test container is started.
- Do not modify production code. If the new test exposes a bug in the endpoint, report it; do not
  fix it inside this scope.
- No `git commit`, no new branch: 24/24 existing branches are already merged into `master`
  (`git branch --no-merged master` → empty), so a branch would only add clutter.
