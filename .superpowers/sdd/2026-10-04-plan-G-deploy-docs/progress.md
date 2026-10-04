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
