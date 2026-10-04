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

## Quickstart — production

```bash
cd web && npm run build                              # tsc -b && vite build → web/dist

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
