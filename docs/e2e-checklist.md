# E2E checklist — img2text MVP

**Manual gate — human ticks after real run.** No automated test covers this.
Run against a real stack (docker compose prod + Colab GPU + R2 + SMTP), tick
each box, and record notes. A miss is filed as an issue against the owning
plan's task.

Prereqs: `deploy/.env` filled (see [docs/r2-setup.md](docs/r2-setup.md)),
`cd web && npm run build`, `docker compose -f deploy/docker-compose.yml up -d --build`.

## A. Spec §2 "In (MVP)" — 1:1

- [ ] **Auth: register / login / logout; JWT httpOnly + refresh rotation; password reset via SMTP.** Expected: register returns 201 and sets httpOnly cookies; logout clears them; forgot→reset via SMTP link changes password and old refresh tokens are revoked; a reused refresh `jti` revokes all of that user's refresh tokens.
- [ ] **Admin: grant OCR access, daily stats, system/request logs.** Expected: `/admin` has Users/Stats/Logs tabs; toggling `ocr_enabled` enables upload for that user; Stats shows per-day aggregates; Logs shows `request_logs` rows + app.log tail.
- [ ] **Upload images or PDF (≤ 50 MB, ≤ 50 pages).** Expected: valid JPG/PNG/WebP/PDF accepted → job row `queued`; >50 MB, >50 pages, or wrong type → synchronous 422 with user-facing message and **no** job row created.
- [ ] **Job queue with lease + heartbeat; Colab notebook worker pulls jobs.** Expected: worker's `GET /api/jobs/next` (Bearer `RUNNER_KEY`) claims the oldest queued job (`running`, 45-min lease, `worker_token` minted); heartbeats every 10 min extend the lease; a second worker call gets the next job, not a duplicate.
- [ ] **Per-page pipeline on Colab: quality pre-check → PaddleOCR-VL → region parse → verdicts.** Expected: blurry/small pages come back with `page_flag` warnings and correct per-region `verdict` values (`ok` / `image_unextractable` / `unreadable` / `low_confidence`); `gpu_seconds` measured around inference.
- [ ] **Canonical intermediate stored in Postgres JSONB.** Expected: `jobs.result` contains `markdown`, `pages[]` (with `regions[]`), `warnings`, `gpu_seconds`, `model_version` (`paddleocr-vl-*`); editable via `PATCH /api/jobs/{id}/content` → `edited_markdown` on `done` jobs only.
- [ ] **User UI: job list, upload, status polling, preview (Markdown pane + issues panel with crops), export buttons (md/html/docx/pdf).** Expected: `/` lists my jobs with upload dropzone; `ocr_enabled=false` → upload disabled + banner "Chờ admin cấp quyền"; `/jobs/{id}` polls every 3 s while `running`, then shows rendered Markdown + verdict-grouped issues rows (lazy crop thumbnails); all 4 export buttons present.
- [ ] **Export server-side (pandoc md/html/docx; pandoc→weasyprint pdf), cached in R2.** Expected: each export returns a presigned URL that downloads; second export of same format hits cache (no regeneration delay); docx/pdf inherit styles from `deploy/reference.docx`; `image_unextractable` regions with bbox embed real crops; edited markdown is preferred after a content save (old cache invalidated).
- [ ] **Storage: R2 only; presigned URLs; content-addressed uploads; lifecycle rules.** Expected: `uploads/{sha256}.{ext}` keys in R2; re-uploading an identical file creates a job but skips the write; all downloads (worker, preview, crops, exports) are presigned GETs; dashboard lifecycle rules match the table in [docs/r2-setup.md](docs/r2-setup.md); server has no local-disk storage path.
- [ ] **Admin stats on-the-fly (no rollups): registered users, jobs submitted/done/failed, page views, GPU seconds per day.** Expected: Stats tab date-range table shows all five columns; GPU seconds for the test day > 0 and matches the job's `result.gpu_seconds`.
- [ ] **`request_logs` + rotating JSON app log; admin log viewer (filter status/IP/time, recent 5xx, auth-failure spikes per IP).** Expected: every request appears in the Logs tab with method/path/status/ip/time; filters narrow correctly; app.log is JSON lines at `LOG_PATH`; 5xx and auth-failure views surface test entries.
- [ ] **Health endpoint + structured JSON logs.** Expected: `GET /healthz` returns 200 when DB is up (5xx/retry when DB is down); app.log lines are structured JSON (not bare text).

## B. Security checks (2)

- [ ] **Preview XSS payload renders inert.** Expected: markdown containing `<script>alert(2)</script>` and `<img src=x onerror=alert(1)>` renders in the preview iframe **without executing** — no alert, no request fired; iframe is sandboxed `srcdoc` without `allow-same-origin` (unit-covered in `web/src/components/MarkdownPreview.test.tsx`, verified live here).
- [ ] **Other user's job → 403.** Expected: user B requesting `GET /api/jobs/{id}` (or export/crop/file/content/retry) for user A's job receives HTTP 403 (`forbidden`); unknown id → 404.

## C. Full-stack walkthrough (one real pass)

- [ ] **Stack up.** Expected: `docker compose -f deploy/docker-compose.yml up -d --build` → nginx :80 serves SPA, `/api/` proxied, `/healthz` 200.
- [ ] **Register.** Expected: new user lands on `/` with upload **disabled** + "Chờ admin cấp quyền" banner (`ocr_enabled=false` default).
- [ ] **Admin grants via admin tab.** Expected: admin (bootstrapped from `ADMIN_EMAIL`/`ADMIN_PASSWORD`) toggles the user's `ocr_enabled` in `/admin` → user's upload dropzone becomes enabled without redeploy.
- [ ] **Upload 3-page PDF.** Expected: job row appears `queued` with `page_count: 3`; R2 shows `uploads/{sha256}.pdf`.
- [ ] **Worker loop on Colab claims the job.** Expected: after secrets + cells 1–2/4–5 run, loop prints the claimed job; server shows `running`; heartbeat keeps lease alive.
- [ ] **Preview issues render.** Expected: job → `done`; `/jobs/{id}` shows Markdown pane + issues panel with crop thumbnails and verdict labels; structure headings (`##`/`###`, question numbers) survive into the preview.
- [ ] **Edit markdown.** Expected: inline region fix or full-text textarea edit saves (`PATCH /content`); re-preview shows the edit; `edited_markdown` set in DB.
- [ ] **Export docx/pdf.** Expected: docx opens with Heading 1–3 styles (pandoc `--reference-doc`); pdf renders via weasyprint; both reflect the edited markdown; R2 `exports/{job_id}/` caches them.
- [ ] **Admin stats row shows gpu_seconds.** Expected: Stats tab row for today includes the job in done count and `gpu_seconds` > 0.
- [ ] **Logs show requests.** Expected: `request_logs` / Logs tab contains the register/upload/export/preview requests from this pass with correct status codes and IPs.
- [ ] **Worker resilience (disconnect drill).** Expected: kill the Colab runtime mid-job → job stays `running` until lease expiry → lease reaper re-queues it (`queued`, `worker_token = NULL`) → re-running the loop cell claims and completes it (idempotent redo).
