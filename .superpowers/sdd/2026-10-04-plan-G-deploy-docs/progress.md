# SDD ledger — plan: docs/superpowers/plans/2026-10-04-plan-G-deploy-docs.md

Worktree: .worktrees/plan-g-deploy (branch plan-g-deploy)
BASE: 544c387 (master: Plans A–F ALL merged — server 82+ tests, web 35 tests, worker 25 tests)

## Preflight scan (plan G)

| Pair/Task | Shared surface | Finding | Ruling |
|---|---|---|---|
| T1 | Dockerfile pandoc | server/.tools gitignored — binary not in repo | R39: Dockerfile downloads pandoc static during build (curl github releases); apt-get install libpango-1.0-0 libharfbuzz0b libfontconfig1 + poppler-utils + curl (weasyprint+pandoc runtime needs, root inside image OK) |
| T1 | env parity test | Settings fields across A+B merged | parity test asserts exact set both directions |
| T2 | reference.docx rebuild guard | committed artifact | test: fresh build styles == committed styles |
| T3 | docs | README/R2/Colab/e2e | content tasks, manual verification gates |
| T4 | full-suite gate | R33 prefixes obsolete post-merge | R40: T4 gate runs ALL suites on master WITHOUT DATABASE_URL prefix (:5433 default); docker compose down -v fresh-volume gate required |
| Lanes | plan-d/plan-e postgres containers | still running on host | R41: T4 gate first `docker rm -f plan-d-postgres-test-1 plan-e-postgres-test-1` (merge done, lane DBs obsolete) |

Scan clean after rulings R39/R40/R41.

## Progress

Task 1: dispatched (worker) — Dockerfile + compose + nginx + env parity
Task 1: complete (commits 544c387..3002df6, review clean — Approved; R39 satisfied, r2_public_base spec-correct, pangoft2/libamd64 deviations justified)
Task 1: Ruling R42 — G-T2 rider: append fonts-dejavu-core to Dockerfile apt (Important #1 — PDF export breaks without fonts; must land before release, not checklist)
Task 1: minor (deferred): nginx zero security headers (nosniff/X-Frame/CSP — cheap edge hardening)
Task 1: minor (deferred): curl stays in final image; no requirements layer caching
Task 1: minor (deferred): parity test comment parsing (indented # misparse — current file unaffected)
Task 1: minor (deferred): no server healthcheck in compose (502 window)
Task 1: note: host pytest boto3→pyOpenSSL breakage pre-existing — T4 gate fresh venv (R40)
Task 2: complete (commits 3002df6..8a15e48, review clean after fix round 1 — Critical backslash fixed + build-verified; rebuild guard + R42 fonts landed)
Task 2: minor (deferred): make_reference_docx.py CLI arg ignored (hardcoded path — pre-existing Plan D, rides docs note)
Task 3: complete (commits 8a15e48..c01db70, review clean — Approved; all commands traced to repo, checklist 1:1 spec §2)
Task 3: Ruling R43 — G-T4 rider: docs heartbeat wording "every 10 min" → "per page (lease 45 min)" in colab-setup (×2) + e2e-checklist A4 (spec-contract vs per-page impl drift)
Task 4: dispatched (worker) — full-suite gate (R40 no-prefix + R41 cleanup) + R43 rider
Task 4: complete — R43 rider 993c8d9; all gates green (server 108 / worker 25 / web 35+build / compose config-0 / docker build img2text-g4 SUCCESS / parity 1). Env fixes: host pandoc 3.10.2 at server/.tools/pandoc (R25 path, export tests red without it); .dockerignore added 842a42f (no .dockerignore → COPY pulled host server/.venv → chown -R hung build >30 min twice). No assertions weakened, no app code touched.
