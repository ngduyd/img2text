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
   ├── LLM (localhost:20128) — layout exports: docx-layout, md-layout (geometry-aware markdown)
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

PRIMARY — one compose command: Postgres + LocalStack S3 (+ bucket init) +
hot-reload server (prod image reused: pandoc/fonts/weasyprint baked → exports
work in dev):

```bash
cp deploy/.env.dev.example deploy/.env.dev   # dev defaults work as-is
docker compose -f deploy/docker-compose.dev.yml up -d --build

curl -s localhost:8010/healthz               # → {"status":"ok","db":true}

cd web && npm install && npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to `:8010` (`web/vite.config.ts`; server CORS
origin-regex (`ALLOWED_ORIGINS`, comma-separated) default covers `http://localhost:*`,
`http://127.0.0.1:*` and `https://<subdomain>.vscode.dev` — VSCode port-forwarding works out of the box;
other origins (LAN access from another host) → set `ALLOWED_ORIGINS` env regex;
host port defaults to 8010 via `DEV_PORT` in the compose file — keep the proxy in
sync when overridden).
Port 8000 is commonly taken on dev boxes (e.g. portainer) — the old manual guide's
`uvicorn --port 8000` was equally broken there; 8010 fixes both paths.

- `ADMIN_EMAIL`/`ADMIN_PASSWORD` bootstraps the admin user on first server boot.
- `ALLOWED_ORIGINS` — comma-separated origin regexes for CORS; default
  `http://localhost:.*|http://127\.0\.0\.1:.*|https://[a-z0-9-]+\.vscode\.dev`
  (VSCode port-forward; subdomain-anchored — `evilvscode.dev` does NOT match);
  set for LAN access from other origins.
- `SCHEDULER_INTERVAL_SECONDS` — server sweep interval (lease reaper),
  default 60, floor 5; admin-set env.
  Plan S: `SCHEDULER_INTERVAL_SECONDS`/`KAGGLE_MIN_QUEUE`/`KAGGLE_MIN_GAP_SECONDS` override runtime qua admin UI (tab Hệ thống, bảng `Setting`); env = mặc định khi DB trống (`kaggle_mode` read-only — đổi mode cần restart).
- Bucket `img2text` auto-created by `s3-init` (official `amazon/aws-cli`
  image against LocalStack — MinIO's public images are gone, ruling R47).
- LocalStack S3 API on http://localhost:4566
  (health: `/_localstack/health`).
- Postgres publishes host `:5433` (`img2text_dev`) — **don't run
  `deploy/docker-compose.test.yml` at the same time** (same host port).
- Server code hot-reloads (`../server` mounted over `/app/server`, `uvicorn --reload`).
- Storage endpoints are split (dev upload 500 fix): server-container ops
  calls use the in-network `R2_ENDPOINT=http://localstack:4566`
  (container→host-published :4566 times out on some hosts); browser-fetched
  presigned object URLs (preview / export download) use
  `STORAGE_PUBLIC_ENDPOINT=http://localhost:4566` — forward port **4566** in
  VSCode too when viewing images/preview from another machine. Prod keeps the
  single `R2_ENDPOINT` (public falls back to it); `R2_PUBLIC_BASE` stays
  spec-reserved for a future CDN.

**Upload wizard:** PDF uploads open a wizard — pick which pages to OCR and
rotate individual pages 90°; image uploads open a crop/rotate step first.
After a job is `done`, the job detail shows preview tabs (Markdown / PDF /
DOCX render on demand).

**Upload flow:** sau khi gửi, job vào hàng đợi — Colab worker poll `/api/jobs/next`
(5–30s) tự xử lý khi đang bật (plan X).

**Worker in dev:** if Colab is off, uploads sit `queued` until the Colab notebook connects
([docs/colab-setup.md](docs/colab-setup.md)). For UI development WITHOUT Colab,
inject a canned result — **DEV STUB ONLY**, bypasses the VLM:

```bash
# 1. Claim a job (returns job_id, worker_token, page_count — stub below posts 1 page;
#    NOTE: the server does not validate pages against page_count — a 1-page stub result
#    marks even a multi-page job done (dev convenience, no guard))
curl -X GET localhost:8010/api/jobs/next -H "Authorization: Bearer dev-runner-key"

# 2. Post the stub result ({id} = job_id from step 1, {worker_token} likewise):
curl -X POST localhost:8010/api/jobs/{id}/result -H "Authorization: Bearer {worker_token}" -H "Content-Type: application/json" -d '{"model_version":"dev-stub","gpu_seconds":0.1,"warnings":["DEV STUB — bypasses VLM"],"markdown":"# Stub\n\n## Part 2","edited_markdown":null,"pages":[{"index":0,"width":800,"height":600,"page_flag":"ok","markdown":"# Stub\n\n## Part 2","regions":[{"id":"p1r0","bbox":[10,10,300,80],"text":"Part 2","verdict":"ok","placeholder":false}]}]}'
```

Job flips to `done` → UI preview/issues/edit/export flows become testable.

**What works without external services:**

| One compose command up (Postgres + LocalStack + server) | SMTP empty | Colab absent |
|---|---|---|
| register/login/upload/preview/issues/edit/export all work — pandoc in the image for docx/pdf/html export; md export needs nothing | password-reset email no-op (logged, flow continues) | jobs stay `queued` — use the dev stub above |

<details>
<summary>Alternative: server on host (editor / pytest workflows)</summary>

Run infra manually and uvicorn on the host. Takes host `:5433`, `:4566` and
`:8010` — stop the dev compose stack first.

**Storage — LocalStack S3 (dev stand-in for R2):**

```bash
docker run -d --name img2text-localstack -p 4566:4566 -v img2text-localstack-data:/var/lib/localstack localstack/localstack:4.13.0

docker run --rm --network=host amazon/aws-cli:2.17.0 --endpoint-url http://localhost:4566 s3 mb s3://img2text --region us-east-1
```

(Any non-empty AWS creds work against LocalStack — the dev env file uses
`test`/`test`.)

**Dev env file:**

```bash
cp deploy/.env.dev.example deploy/.env.dev   # then set HOST-side values:
# APP_SECRET=dev-secret-change-me
# BASE_URL=http://localhost:5173
# RUNNER_KEY=dev-runner-key
# ADMIN_EMAIL=<your email>            # bootstraps the admin on first server boot
# ADMIN_PASSWORD=<dev password>
# R2_ENDPOINT=http://localhost:4566   # host server + host browser both reach it
# R2_ACCESS_KEY_ID=test
# R2_SECRET_ACCESS_KEY=test
# R2_BUCKET=img2text
# R2_REGION=us-east-1
# SMTP_* left empty — password-reset emails won't send in dev
#   (the mailer logs the failure and continues; reset flow no-ops)
# DATABASE_URL can stay UNSET (delete the compose override) — server defaults
#   to Postgres on :5433/img2text_test (see server/app/config.py)
```

**Terminal 1 — Postgres:**

```bash
docker compose -f deploy/docker-compose.test.yml up -d --wait   # Postgres 16 on :5433
```

Dev reuses the test DB (`img2text_test`) — fine for dev; wipe it freely.

**Terminal 2 — server:**

```bash
set -a && source deploy/.env.dev && set +a && cd server && .venv/bin/uvicorn app.main:app --reload --port 8010
```

`ADMIN_EMAIL`/`ADMIN_PASSWORD` bootstraps the admin user on first boot. Install
pandoc (see quickstart above) before testing exports.

**Terminal 3 — web:**

```bash
cd web && npm install && npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to `:8010` (same target as the
compose path; if you port elsewhere, update `web/vite.config.ts` to match).

</details>

## Quickstart — production

```bash
cd web && npm run build                              # tsc -b && vite build → web/dist
test -f web/dist/index.html || echo "WARNING: web/dist missing — run npm run build in web/ first"

cd ..
cp deploy/.env.example deploy/.env                   # then fill (see below)

docker compose -f deploy/docker-compose.yml up -d --build
```

> **Migration 1 lần cho DB đã tồn tại (Plan D4/Plan M — `create_all` không ALTER):**
>
> ```bash
> docker compose -f deploy/docker-compose.yml exec postgres \
>   psql -U img2text -d img2text -c "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS output_format TEXT;" \
>   -c "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS layout_style TEXT;"
> ```

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

## Kaggle orchestration (worker tự động)

Server tự điều phối Kaggle worker (Plan K2 + K5), chọn bằng `KAGGLE_MODE`
(mặc định `batch`):

- **`batch` (mặc định, Plan K5)**: scheduler thấy `queued` job → backend tự
  stage file upload vào dataset `img2text-input` (delete + create — luôn
  chạy trên file mới nhất), push script kernel `img2text_batch.py` (từ
  `deploy/kaggle`), poll status → `kernels_output` → `result.json` → ingest
  vào job (`done` + payload spec §4). **Không cần public URL, không cần
  Secrets.** Ceiling: single-active-run (1 run tại một thời điểm — slug
  input `img2text-input` dùng chung, chống overlap) + gap
  `KAGGLE_MIN_GAP_SECONDS`; block `image` bị bỏ khỏi regions/markdown
  (batch không có regions ảnh — chỉ worker `loop` mới có placeholder);
  `preprocess` bị bỏ qua (log warning — dùng `loop` khi cần chọn trang/xoay);
  map run giữ trong RAM (restart = kernel mồ côi). Output script ghi vào
  `/kaggle/working` (capture của `kernel_type: script`) + copy
  `/kaggle/outputs` (compat notebook — chỉ notebook kernel mới capture).
- **`loop` (Plan K2)**: bump dataset `img2text-worker-files` + push kernel
  worker (`img2text_worker.ipynb`); kernel xử lý theo session rồi poll backend
  qua `/api/jobs/next` — production mode khi có URL public + Secrets.

Kernel xử lý theo session rồi thoát (platform cap ~12h); server tái kích
khi queue còn job.

**Bật env** (deploy/.env hoặc shell — compose dev pass-through, xem
`deploy/.env.dev.example`):

```bash
KAGGLE_USERNAME=<kaggle username>        # OWNER id trong metadata (bắt buộc)
KAGGLE_API_TOKEN=<token>                 # khuyên — kaggle 2.x primary (kaggle.com/settings/api)
KAGGLE_KEY=<api key>                     # legacy fallback khi không có token
KAGGLE_KERNEL_REF=<user>/img2text-worker # ref kernel đã tạo 1 lần (bắt buộc mọi mode — feature gate; loop dùng ref này)
KAGGLE_MODE=batch                        # batch (mặc định) | loop (Plan K2)
```

Không set đủ `KAGGLE_USERNAME` + (`KAGGLE_KEY` **hoặc** `KAGGLE_API_TOKEN`) + `KAGGLE_KERNEL_REF` = feature tự tắt, server **không import** `kaggle`
(thiếu package cũng không crash — orchestrator disabled + warning).

**Secrets 1 lần** (chỉ mode `loop` — batch không gọi lại backend): kaggle.com → Add-ons → Secrets:
`BASE_URL` (URL **public** của API worker — không localhost) + `RUNNER_KEY`.
Chi tiết: [deploy/kaggle/README.md](deploy/kaggle/README.md).

**Khởi tạo 1 lần** (chỉ mode `loop`): dataset `OWNER/img2text-worker-files` +
kernel ref phải tồn tại trên Kaggle — chạy `python deploy/kaggle/push.py`
(Plan K manual push) trước khi bật orchestration. Mode `batch` tự push kernel
`img2text-batch` + tự tạo dataset `img2text-input` khi spawn.

Quota GPU free ~**30h/tuần** — `KAGGLE_MIN_GAP_SECONDS` (mặc định 600s)
chống spam spawn ở cả 2 mode; `KAGGLE_MIN_QUEUE` (mặc định 1) chỉ tính ở mode
`loop`. `KAGGLE_TIMEOUT` ở mode `batch` là trần poll thật (ref quá hạn bị xóa,
job vẫn `queued` → spawn lại sau gap); ở mode `loop` chỉ là ceiling note
(kernels_push timeout kw không đáng tin; session cap do platform).

**Production note**: server cần egress internet + package `kaggle`
(Dockerfile đã `pip install "/app/server[kaggle]"`; server thường thì
`pip install -e 'server[kaggle]'`). `kaggle>=1.6` — kaggle 2.2.x đổi tên
dataset API: deploy đi qua `deploy/kaggle/kcompat.py`, server orchestrator
dùng hasattr dispatch inline (`_bump_dataset_version`), cả 2 thế hệ API
đều chạy. Kernel Secrets đã set 1 lần như trên.
Sync Kaggle↔cloud-storage cho production là follow-up riêng.

## Docs

- [docs/r2-setup.md](docs/r2-setup.md) — R2 bucket, API token, lifecycle rules, `.env` fill
- [docs/colab-setup.md](docs/colab-setup.md) — GPU runtime, secrets, cell order
- [docs/e2e-checklist.md](docs/e2e-checklist.md) — manual end-to-end gate (human ticks after real run)
- [docs/superpowers/specs/2026-10-04-img2text-mvp-design.md](docs/superpowers/specs/2026-10-04-img2text-mvp-design.md) — design spec
