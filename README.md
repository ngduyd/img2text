# img2text

Convert structured images of English exams (JPG/PNG/WebP scans/photos, PDF) into
editable formats: Markdown, HTML, DOCX, PDF. OCR runs on PaddleOCR-VL on Google
Colab free tier; the server is an I/O tier only. Spec:
[docs/superpowers/specs/2026-10-04-img2text-mvp-design.md](docs/superpowers/specs/2026-10-04-img2text-mvp-design.md).

## Stack

```
Browser (Vite React SPA)
   │  JWT httpOnly cookie
   ▼
Nginx ── serves built SPA + reverse proxy /api/  (deploy/nginx.conf)
   ▼
FastAPI (uvicorn)  ── APScheduler: lease reaper, log/token pruning
   ├── Postgres 16 (auth, jobs, result JSONB, request_logs)
   ├── Cloudflare R2 via boto3 presigned URLs (uploads/ exports/ crops/)
   └── pandoc + weasyprint (exports: md/html/docx/pdf, cached in R2)
   ▲
   │  pull: GET /api/jobs/next   (Bearer RUNNER_KEY)
Colab notebook worker (GPU runtime)   worker/colab_notebook.ipynb
   pdftoppm → quality pre-check → PaddleOCR-VL v1.5 → verdicts → POST result
```

Layout: `server/` (FastAPI + tests), `web/` (SPA; scoped notes in
[web/README.md](web/README.md)), `worker/` (notebook + verdict logic),
`deploy/` (compose, nginx, `.env.example`, `reference.docx`), `docs/`.

## Quickstart — development

```bash
docker compose -f deploy/docker-compose.test.yml up -d --wait   # Postgres 16 on :5433

cd server && python -m venv .venv
# Export tests need pandoc at the explicit path convert.py expects (R25, pinned 3.10.2):
mkdir -p .tools/pandoc && curl -fsSL https://github.com/jgm/pandoc/releases/download/3.10.2/pandoc-3.10.2-linux-amd64.tar.gz | tar -xz -C .tools/pandoc --strip-components=2
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest -v

cd ../worker && python -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest -v

cd ../web && npm install
npm test
```

Server tests default to `postgresql+asyncpg://img2text:img2text@localhost:5433/img2text_test`
(see `server/app/config.py`); worker tests import `verdict`/`pipeline` from `worker/`.

## Run the app in development

Run the full stack locally: MinIO for storage (no Cloudflare), Postgres, FastAPI,
Vite dev server. Vite proxies `/api` to `:8000` (`web/vite.config.ts`) — no CORS
middleware on the server; prod nginx covers this instead.

**Storage — MinIO (dev stand-in for R2):**

```bash
docker run -d --name img2text-minio -p 9000:9000 -p 9001:9001 -v img2text-minio-data:/data minio/minio server /data --console-address :9001

docker run --rm --network=host minio/mc --alias local http://localhost:9000 mb local/img2text
```

(or open the console at http://localhost:9001 — login `minioadmin`/`minioadmin` — and create bucket `img2text`).

**Dev env file:**

```bash
cp deploy/.env.example deploy/.env.dev   # then fill with DEV values:
# APP_SECRET=dev-secret-change-me
# BASE_URL=http://localhost:5173
# RUNNER_KEY=dev-runner-key
# ADMIN_EMAIL=<your email>            # bootstraps the admin on first server boot
# ADMIN_PASSWORD=<dev password>
# R2_ENDPOINT=http://localhost:9000
# R2_ACCESS_KEY_ID=minioadmin
# R2_SECRET_ACCESS_KEY=minioadmin
# R2_BUCKET=img2text
# R2_REGION=auto
# SMTP_* left empty — password-reset emails won't send in dev
#   (the mailer logs the failure and continues; reset flow no-ops)
# DATABASE_URL can stay unset — server defaults to Postgres on :5433 (see server/app/config.py)
```

**Terminal 1 — Postgres:**

```bash
docker compose -f deploy/docker-compose.test.yml up -d --wait   # Postgres 16 on :5433
```

Dev reuses the test DB (`img2text_test`) — fine for dev; wipe it freely.

**Terminal 2 — server:**

```bash
set -a && source deploy/.env.dev && set +a && cd server && .venv/bin/uvicorn app.main:app --reload --port 8000
```

`ADMIN_EMAIL`/`ADMIN_PASSWORD` bootstraps the admin user on first boot. Install
pandoc (see quickstart above) before testing exports.

**Terminal 3 — web:**

```bash
cd web && npm install && npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to `:8000`.

**Worker in dev:** uploads sit `queued` until the Colab notebook connects
([docs/colab-setup.md](docs/colab-setup.md)). For UI development WITHOUT Colab,
inject a canned result — **DEV STUB ONLY**, bypasses the VLM:

```bash
# 1. Claim a job (returns job_id, worker_token, page_count — stub below posts 1 page;
#    if page_count > 1 the result is rejected, use an image upload for multi-page)
curl -X GET localhost:8000/api/jobs/next -H "Authorization: Bearer dev-runner-key"

# 2. Post the stub result ({id} = job_id from step 1, {worker_token} likewise):
curl -X POST localhost:8000/api/jobs/{id}/result -H "Authorization: Bearer {worker_token}" -H "Content-Type: application/json" -d '{"model_version":"dev-stub","gpu_seconds":0.1,"warnings":["DEV STUB — bypasses VLM"],"markdown":"# Stub\n\n## Part 2","edited_markdown":null,"pages":[{"index":0,"width":800,"height":600,"page_flag":"ok","markdown":"# Stub\n\n## Part 2","regions":[{"id":"p1r0","bbox":[10,10,300,80],"text":"Part 2","verdict":"ok","placeholder":false}]}]}'
```

Job flips to `done` → UI preview/issues/edit/export flows become testable.

**What works without external services:**

| Postgres + MinIO up | SMTP empty | Colab absent |
|---|---|---|
| register/login/upload/preview/issues/edit/export all work — pandoc needed for docx/pdf/html export; md export needs nothing | password-reset email no-op (logged, flow continues) | jobs stay `queued` — use the dev stub above |

## Quickstart — production

```bash
cd web && npm run build                              # tsc -b && vite build → web/dist
test -f web/dist/index.html || echo "WARNING: web/dist missing — run npm run build in web/ first"

cd ..
cp deploy/.env.example deploy/.env                   # then fill (see below)

docker compose -f deploy/docker-compose.yml up -d --build
```

Nginx serves `web/dist` and proxies `/api/` on port 80. Fill `deploy/.env`:
`APP_SECRET`, `RUNNER_KEY`, `BASE_URL`, `ADMIN_EMAIL`/`ADMIN_PASSWORD` (bootstraps
the admin user on first start), R2 keys ([docs/r2-setup.md](docs/r2-setup.md)),
SMTP (password reset). Keys must match `Settings` fields —
`server/tests/test_env_parity.py` fails on drift.

> **Single uvicorn worker by design — in-process rate limits assume it.**
> Auth endpoints: 10 req/hour/IP; uploads: 20 jobs/day/user when `ocr_enabled`.
> Do not scale uvicorn workers without moving the limits to Postgres.

## Workers (Colab)

Run the notebook against a deployed server: [docs/colab-setup.md](docs/colab-setup.md).
Smoke-check the notebook before each release: [docs/colab-smoke-checklist.md](docs/colab-smoke-checklist.md).

## Docs

- [docs/r2-setup.md](docs/r2-setup.md) — R2 bucket, API token, lifecycle rules, `.env` fill
- [docs/colab-setup.md](docs/colab-setup.md) — GPU runtime, secrets, cell order
- [docs/e2e-checklist.md](docs/e2e-checklist.md) — manual end-to-end gate (human ticks after real run)
- [docs/superpowers/specs/2026-10-04-img2text-mvp-design.md](docs/superpowers/specs/2026-10-04-img2text-mvp-design.md) — design spec
