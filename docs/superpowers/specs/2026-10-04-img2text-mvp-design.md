# img2text MVP — Design Spec

**Date:** 2026-10-04
**Status:** draft for review
**Repo:** single codebase, env-driven. OSS release and self-deployed release differ only by configuration, never by fork.

## 1. Goal

Convert structured images of English exams (scans/photos, JPG/PNG/WebP, and PDF) into editable formats: Markdown, HTML, DOCX, PDF. OCR runs on PaddleOCR-VL on Google Colab free tier. The product is non-commercial for now: registration is open but OCR is disabled until an admin grants access. This prevents spam and lets an admin attribute GPU cost to usage.

## 2. Scope

### In (MVP)

- Register / login / logout; JWT (httpOnly) + refresh rotation; password reset via SMTP.
- Admin role: grant OCR access, view daily stats, view system/request logs.
- Upload images or PDF (≤ 50 MB, ≤ 50 pages).
- Job queue with lease + heartbeat; Colab notebook worker pulls jobs.
- Per-page pipeline on Colab: quality pre-check → PaddleOCR-VL inference → region parse → verdicts.
- Canonical intermediate: per-page Markdown + `regions[]` + `issues[]`, stored in Postgres JSONB.
- User UI: job list, upload, status polling, preview (Markdown pane + issues panel with crops), export buttons (md/html/docx/pdf).
- Export server-side via pandoc (md/html/docx) and pandoc→HTML→weasyprint (pdf); cached in R2.
- Storage on Cloudflare R2 only; presigned URLs; content-addressed uploads; lifecycle rules.
- Admin stats on-the-fly (no rollup tables): registered users, jobs submitted/done/failed, page views, GPU seconds per day.
- `request_logs` table + rotating JSON app log; admin log viewer (filter status/IP/time, recent 5xx, auth-failure spikes per IP).
- Health endpoint, structured JSON logs.

### Out (deferred, with upgrade path noted)

| Item | Upgrade path |
|---|---|
| Traditional OCR layer (PP-OCRv5 verifier) | `verdict.py` `sources` map + `resolve()` already dual-source shaped; bind later by adding `ocr` source |
| Fallback runners (Kaggle, HF Spaces) | `GET /jobs/next` is runner-agnostic; add notebook, same endpoint |
| Email verification on register | add token flow beside reset flow |
| OAuth | standard provider flow |
| Multi-file jobs (batch images) | one job = one file today; batch = loop client-side |
| Async export jobs | exports are sync today with cache; move to queue when slow |
| Per-page resume checkpoint on retry | retry redoes whole job (idempotent overwrite); checkpoint when GPU cost of retry hurts |
| Per-user quota UI | `users.ocr_enabled` boolean today; evolve to quota column |
| Direct-to-R2 presigned PUT upload | bypasses weak server CPU; same storage layer |
| Public CDN domain for crops/exports | `R2_PUBLIC_BASE` env already reserved |

## 3. Architecture

```
Browser (Vite React SPA)
   │  JWT httpOnly cookie
   ▼
Nginx ── reverse proxy, serves built SPA only (no file streaming)
   ▼
FastAPI (uvicorn, i5 host = I/O tier only)
   │  ├── Postgres 16 (auth, jobs, logs, result JSONB)
   │  ├── Cloudflare R2 via boto3 presigned URLs
   │  └── APScheduler: lease reaper, log/token pruning
   ▲
   │  pull: GET /jobs/next (Bearer RUNNER_KEY)
Colab notebook worker (GPU runtime)
   ├── pdftoppm (PDF → page PNGs, CPU)
   ├── quality pre-check (OpenCV Laplacian + resolution, CPU)
   ├── PaddleOCR-VL inference (GPU)  ← exact model tag pinned at implementation start
   └── POST result (Bearer per-job worker_token)
```

Principles:

- The server never rasterizes PDFs, never runs OCR, never serves binary files. CPU on the i5 stays trivial.
- Colab is an unreliable batch runner. The queue survives its death: lease expiry re-queues jobs; nothing else in the system knows Colab exists.
- One codebase. `RUNNER_MODE=colab` now; more runners later without server changes.

## 4. Data model (Postgres)

```sql
CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  email         CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,                -- bcrypt
  role          TEXT NOT NULL DEFAULT 'user', -- 'user' | 'admin'
  ocr_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  jti        UUID NOT NULL UNIQUE,            -- reuse detection
  token_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ
);

CREATE TABLE jobs (
  id               BIGSERIAL PRIMARY KEY,
  user_id          BIGINT NOT NULL REFERENCES users(id),
  status           TEXT NOT NULL DEFAULT 'queued', -- queued|running|done|failed
  storage_key      TEXT NOT NULL,                  -- uploads/{sha256}.{ext}
  file_type        TEXT NOT NULL,                  -- image|pdf
  page_count       INT NOT NULL,
  result           JSONB,
  error            TEXT,
  worker_token     TEXT,                           -- capability token, per run
  lease_expires_at TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at       TIMESTAMPTZ,
  finished_at      TIMESTAMPTZ
);
CREATE INDEX jobs_status_idx ON jobs (status, created_at) WHERE status = 'queued';

CREATE TABLE page_views (
  id         BIGSERIAL PRIMARY KEY,
  path       TEXT NOT NULL,
  user_id    BIGINT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE request_logs (
  id         BIGSERIAL PRIMARY KEY,
  ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  method     TEXT NOT NULL,
  path       TEXT NOT NULL,
  status     INT NOT NULL,
  user_id    BIGINT,
  ip         TEXT NOT NULL,
  ua         TEXT
);
CREATE INDEX request_logs_ip_idx ON request_logs (ip, ts);

CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);  -- seeds: usd_per_gpu_hour = '0.0'
```

`jobs.result` JSONB:

```json
{
  "model_version": "paddleocr-vl-<pinned-tag>",
  "gpu_seconds": 340.5,
  "warnings": ["page 3: blurry"],
  "markdown": "full document markdown",
  "edited_markdown": null,
  "pages": [
    {
      "index": 1,
      "width": 1654, "height": 2339,
      "page_flag": "ok | low_confidence | unreadable",
      "markdown": "page markdown",
      "regions": [
        {
          "id": "p1r3",
          "bbox": [x1, y1, x2, y2],
          "text": "extracted text or empty",
          "verdict": "ok | image_unextractable | unreadable | low_confidence",
          "placeholder": false
        }
      ]
    }
  ]
}
```

Verdict values `ocr_preferred` and `vlm_lowconf` are reserved for the future OCR binding; the enum accepts them but the MVP never emits them.

## 5. Storage (Cloudflare R2)

Single S3-compatible driver (boto3). No local disk driver, no custom HMAC signing: presigned URLs from boto3 replace all of it. Any S3 endpoint (MinIO, B2) works via env change.

```
uploads/{sha256}.{ext}          content-addressed, immutable, dedup by hash
crops/{job_id}/{region_id}.jpg  generated on demand, cached forever
exports/{job_id}/{fmt}          generated on demand, cached
```

- Upload: browser → backend multipart → backend streams to R2 while computing sha256. Existing hash = skip write, still create job row.
- Presigned GET TTLs: worker download 1 h, original preview 1 h, crops 24 h, exports 24 h.
- Crops: generated lazily on first preview request — PIL crop + resize (max 800 px wide) + JPEG q70, then PUT to R2. Trivial CPU on the i5; worker needs no R2 credentials.
- R2 lifecycle rules (dashboard, no code): `uploads/` delete after 30 days, `exports/` after 7 days. `crops/` kept (small, preview depends on them). Result JSONB lives in Postgres, so file deletion loses nothing essential.
- R2 free tier (10 GB storage, 10 M Class A/B ops/month) is comfortable for MVP scale.

Env:

```
R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=img2text
R2_REGION=auto
R2_PUBLIC_BASE=            # optional; reserved for public CDN domain later
```

## 6. Job queue & lease

- Status flow: `queued → running → done | failed`.
- `GET /jobs/next` (worker, `Authorization: Bearer $RUNNER_KEY`): `SELECT … FOR UPDATE SKIP LOCKED` on the oldest queued job; sets `running`, mints `worker_token` (random 32 bytes), sets `lease_expires_at = now() + 45 min`. Response includes presigned download URL.

  ```json
  {"job_id": "123", "worker_token": "...", "file_url": "<presigned>",
   "file_type": "pdf", "page_count": 14}
  ```

- `POST /jobs/{id}/heartbeat` (Bearer `worker_token`, worker sends every 10 min): extends lease to now + 45 min.
- `POST /jobs/{id}/result` (Bearer `worker_token`): accepted only when `status = running` and lease valid; else `409`. Sets `done`, stores result JSONB, `finished_at`, clears `worker_token`.
- `POST /jobs/{id}/fail` (Bearer `worker_token`): unrecoverable (corrupt file, model crash). Sets `failed`, stores sanitized `error` (message + error class only; full trace goes to app log).
- Lease reaper (APScheduler, every 1 min): `status = running AND lease_expires_at < now()` → back to `queued`, `worker_token = NULL`.
- Retry semantics (MVP): a retried job redoes all pages and overwrites the result. Idempotent, correct, occasionally wasteful of GPU — acceptable; per-page checkpoints are the documented upgrade.
- Upload validation failures never create a job row: synchronous `422` with a user-facing message (bad type, > 50 MB, > 50 pages via `pypdf`).

## 7. Worker (Colab notebook)

Config cell reads Colab Secrets: `RUNNER_KEY`, `BASE_URL`. Loop with 5–30 s backoff; auth failure stops the loop and raises (quota/key issue — visible, not silent).

Pipeline per job:

1. Download file via presigned URL.
2. If PDF: `pdftoppm -r 200` → page PNGs (≤ 50 pages guaranteed by upload check).
3. Per page:
   - **Pre-check (CPU):** `cv2.Laplacian(gray).var()`. `< 100` → blurry. Width `< 1000 px` or estimated glyph height `< ~20 px` → too small.
     - Both failed → skip VLM for the page, `page_flag = unreadable`, warning added; job continues.
     - One failed → run VLM but `page_flag = low_confidence` on the page.
   - **VLM inference (GPU):** PaddleOCR-VL. Exact model tag pinned in the notebook config cell at implementation start (design assumes the PaddleOCR 3.x Python API; no server code depends on the tag).
   - **Parse:** layout markdown + available bboxes → `regions[]`. Regions with no recoverable bbox get `bbox: null` (UI falls back to text-only issue rows).
   - **GPU seconds:** measured around inference, stored in result.
4. Build `markdown` per page and full document; embed warning markers at region positions where detectable:

   ```
   **[Hình ảnh chưa trích xuất: vùng p3r2]**
   ```

5. `POST result`.
6. Any exception: `POST fail` with error class; notebook continues polling next job.

Worker never talks to R2 or Postgres directly — only the two endpoints above. Retries reuse the presigned URL while valid.

### Verdict system (`worker/verdict.py`)

Pure Python module, unit-tested in the server test suite (imported, not re-implemented). The notebook is a thin wrapper.

```python
@dataclass
class SourceResult:
    text: str
    confidence: float | None      # None = source has no calibrated confidence

@dataclass
class Region:
    id: str
    bbox: tuple[int, int, int, int] | None
    sources: dict[str, SourceResult]   # MVP: {"vlm": ...}; later + "ocr": ...

def resolve(region: Region, page_flag: str) -> str:
    ...
```

MVP verdicts (VLM-only):

| Condition | Verdict | UI meaning |
|---|---|---|
| VLM returned text, page pre-check ok | `ok` | extracted; show text |
| Layout region is an image / VLM returned placeholder | `image_unextractable` | user must handle the image content |
| VLM returned empty text on a low-quality page | `unreadable` | "không trích xuất được văn bản" + page warning |
| Page pre-check mild fail | `low_confidence` | flagged on all page regions, review advised |

Because a single VLM source cannot cross-check itself, all `ok` regions are labeled in the UI as VLM-only confidence. The dual-source `resolve()` branch (compare normalized texts with `rapidfuzz.fuzz.ratio`, thresholds 0.7 confidence / 0.85 similarity, verdicts `ocr_preferred` / `vlm_lowconf`) is designed now and tested with synthetic data so the future OCR binding is configuration, not redesign.

## 8. API surface

```
POST /api/auth/register            {email, password}        → 201, sets cookies
POST /api/auth/login               {email, password}        → sets access+refresh
POST /api/auth/logout                                  → clears cookies, revokes refresh
POST /api/auth/password/forgot     {email}                  → 202 always (no user enumeration)
POST /api/auth/password/reset      {token, password}
GET  /api/auth/me

POST /api/jobs                     multipart file           → {id, status}
GET  /api/jobs                                             → my jobs
GET  /api/jobs/{id}                                      → status + result (if done)
GET  /api/jobs/next               Bearer RUNNER_KEY        → job payload or 204
POST /api/jobs/{id}/heartbeat     Bearer worker_token
POST /api/jobs/{id}/result        Bearer worker_token      → result JSONB
POST /api/jobs/{id}/fail          Bearer worker_token      → {error}
POST /api/jobs/{id}/export        {fmt: md|html|docx|pdf}  → presigned GET (cached)
GET  /api/jobs/{id}/regions/{rid}/crop                     → presigned GET (lazy-cached)
GET  /api/jobs/{id}/file                                    → presigned GET (original)
PATCH /api/jobs/{id}/content    {markdown}                → save result.edited_markdown (done only)

GET  /api/admin/users             ?page=                   → list + ocr_enabled
PATCH /api/admin/users/{id}       {ocr_enabled: bool}
GET  /api/admin/stats             ?from=&to=               → daily aggregates
GET  /api/admin/logs              ?status_class=&ip=&limit=
GET  /api/admin/logs/tail         ?lines=200               → app.log tail (fixed path)

GET  /healthz
```

Auth cookies: `access` JWT 15 min, `refresh` JWT 30 d — both httpOnly, SameSite=Lax, Secure. Refresh rotation on every use; a presented `jti` already marked used → token theft signal → revoke all refresh tokens for that user.

## 9. Backend

- FastAPI + SQLAlchemy (async) + asyncpg + Alembic; uvicorn behind Nginx.
- Nginx: reverse proxy `/api/` + serves built SPA. No `X-Accel-Redirect` (presigned URLs removed file streaming from the server entirely).
- APScheduler (in-process; single uvicorn worker assumption — documented ceiling): lease reaper 1 min, `request_logs` prune daily (keep 7 d), `refresh_tokens` prune daily, stale `used` tokens cleanup.
- SMTP: `smtplib` via threadpool (2 uses only: password reset, job-done email). Config via env; Gmail app password acceptable.
- Admin bootstrap: on startup, if `ADMIN_EMAIL`/`ADMIN_PASSWORD` env set and that email absent → create admin user. No CLI.
- Runner auth: static shared secret `RUNNER_KEY` in env / Colab Secret. Per-runner keys deferred with the fallback runners.
- `page_views` middleware: counts non-API GET paths with nullable `user_id`.
- `request_logs` middleware: every request, after response. IP taken from `X-Forwarded-For` (Nginx sets it; server must not trust client-supplied values).
- Export generation: pandoc with `deploy/reference.docx` as `--reference-doc` (styles: Normal, Heading 1–3, Table). `md/html/docx` direct; `pdf` via pandoc→standalone HTML→weasyprint. For `image_unextractable` regions with a bbox: download crop from R2 → temp dir → rewrite markdown image refs → all formats carry real images (md/html render them natively, pandoc embeds them in docx/pdf); bbox-less issues keep the bold warning marker. Exports prefer `result.edited_markdown` when present; `PATCH /jobs/{id}/content` deletes `exports/{job_id}/*` in R2 (cache invalidation). Sync request, 60 s timeout, result cached to `exports/{job_id}/{fmt}`.
- Health: `/healthz` checks DB connectivity only.

### Limits & abuse (MVP ceilings)

| Control | Value | Where |
|---|---|---|
| File size | 50 MB | upload validation |
| Pages | 50 | `pypdf` count at upload |
| File types | jpg/jpeg/png/webp/pdf | upload validation |
| Auth endpoints | 10 req/hour/IP | in-process sliding window |
| Uploads | 20 jobs/day/user (when `ocr_enabled`) | in-process counter |

In-process rate limiting assumes one process. Multi-worker deployment moves these to Postgres later; acceptable while the deploy is a single uvicorn on the i5.

## 10. Frontend

Vite + React + TypeScript + TanStack Query + Tailwind. Preview Markdown via `marked` + `DOMPurify` rendered inside a sandboxed iframe (`srcdoc`, no `allow-same-origin`) — VLM output is untrusted.

Pages:

| Route | Content |
|---|---|
| `/login` `/register` `/forgot` `/reset` | auth forms |
| `/` | job list + upload dropzone; if `ocr_enabled=false`: upload disabled + banner "Chờ admin cấp quyền" |
| `/jobs/{id}` | polling (TanStack Query, 3 s while `running`); when done: Markdown pane + issues panel + export buttons |
| `/admin` | tabs: Users (toggle `ocr_enabled`), Stats (date-range table incl. GPU seconds + estimated cost from `usd_per_gpu_hour`), Logs (filter + tail) |

Issues panel: grouped by verdict; each row = crop thumbnail (presigned, lazy) + region id + VLM text + verdict label. `image_unextractable` rows note that the image content needs manual handling. The two-candidate comparison layout is reserved for the OCR binding and does not ship in MVP.

**Editing & DOCX fidelity.** Users edit before export: the issues panel fixes region text inline; a toggle exposes the full markdown textarea. Edits save to `result.edited_markdown` (`PATCH /api/jobs/{id}/content`); exports prefer the edited version. Editing changes text only — styles never come from user content, so preview edits cannot drift Word styles.

Markdown is lossy (no merged cells, no per-region fonts, no absolute positioning): exports will not pixel-match the original scan — by design, the deliverable is editable, not a facsimile. Cross-export style consistency comes from `deploy/reference.docx` via `pandoc --reference-doc`; every docx/pdf inherits Normal/Heading/Table styles from that one template. Known ceiling: merged table cells + region-specific fonts need the python-docx upgrade path (build DOCX directly from `regions[]`); weasyprint+CSS PDF stays closest to the original look.

Status flow UX: queued → "Đang chờ worker Colab"; running → "Đang xử lý (trang x/total)" when result partials exist, else spinner; done → preview; failed → error message + retry button (re-queues same job).

## 11. Config (env)

```
DATABASE_URL=postgresql+asyncpg://...
APP_SECRET=<jwt signing key>
BASE_URL=https://app.example.com
RUNNER_KEY=<shared secret for Colab worker>
ADMIN_EMAIL=... ADMIN_PASSWORD=...
R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET / R2_REGION / R2_PUBLIC_BASE
SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM
LOG_PATH=/var/log/img2text/app.log
```

`usd_per_gpu_hour` lives in `settings` table (admin-editable later), not env — cost assumptions change without redeploy.

## 12. Repo layout

```
img2text/
  server/          # FastAPI app, Alembic, tests (pytest)
    app/  migrations/  tests/
  web/             # Vite React SPA
  worker/          # colab_notebook.ipynb + verdict.py (imported by server tests)
  deploy/          # docker-compose.yml (postgres + server), nginx.conf, .env.example, reference.docx
  docs/            # spec, Colab setup guide, R2 setup guide
```

## 13. Testing

- pytest + httpx ASGI client against a real Postgres (docker compose service). JSONB/`SKIP LOCKED` semantics need the real engine; no sqlite stand-in.
- Unit (pure logic, no I/O): `verdict.resolve()` — single-source matrix + synthetic dual-source branch; pre-check thresholds on synthetic PIL images; upload validation (type/size/page count); refresh rotation + reuse detection.
- Integration: auth flows, job lifecycle (queue → next → heartbeat → result → done), lease expiry re-queue, result-after-lease → 409, export cache (pandoc/weasyprint real in CI), rate limits.
- Worker: notebook logic lives in `verdict.py` and is covered by the server suite; the notebook itself is smoke-tested manually on Colab per release.

## 14. Deployment

**OSS release:** public repo with `deploy/` compose (postgres + server), nginx sample, `.env.example`, docs: R2 bucket setup, Colab secrets + notebook run guide, SMTP setup. Storage defaults to R2; MinIO alternative documented via the same env block.

**Self-deployed release:** same artifacts + branding env + later `runners/` directory (Kaggle, HF) calling the same `GET /jobs/next`. No code fork at any point.

## 15. Open items for implementation

1. Pin exact PaddleOCR-VL model tag in the notebook config cell (design is tag-agnostic).
2. Confirm `paddleocr` Python API output shape for layout+bbox mapping on Colab; regions without bboxes degrade gracefully (spec §7).
3. `pdftoppm` availability: install in notebook setup cell (`apt-get install poppler-utils`).
