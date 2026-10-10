# R2 Storage + Presigned Upload + Pipeline Fetch URL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** Storage → R2 (prod), UI upload thẳng R2 qua presigned POST (backend metadata-only, bỏ multipart), pipeline tải file từ presigned GET URL (kernel dual-mode, mount fallback dev).

**Architecture:** `S3Driver.presign_post` (content-length-range 50MB). Upload: `POST /jobs/presign` → UI POST form→R2 → pdf.js đếm trang → `POST /jobs` (head-verify, metadata). Pipeline: manifest.json {input_url presigned GET 1h} stage vài byte → kernel dual-mode (URL/sha256 verify / mount fallback). Dev localstack + mount; prod R2 creds.

**Tech Stack:** boto3 (presign_post), FastAPI, React (pdf.js), kernel Python. `jobs.mode` đã migrate.

**Spec:** `docs/superpowers/specs/2026-10-10-r2-presigned-upload-design.md`. Đã chốt: bỏ multipart, cap 50MB. Phase 1-5 merged.

## Global Constraints

- `max_bytes = 50MB`. `presign_post(key, expires, max_bytes, content_type)` → `{url, fields}` policy content-length-range [0, max_bytes].
- Bỏ multipart `UploadFile` path — chuyển hết presigned POST.
- `POST /jobs/presign` sanity-check (size ≤ 50MB, page_count ≤ 100, format/mode enum). `POST /jobs` `head(storage_key)` verify (không đọc bytes), 404 nếu thiếu.
- PDF page_count client-side (pdf.js). image = 1.
- Kernel manifest: `manifest.json {job_id, input_url, filename, sha256}`; dual-mode (URL→download+verify sha256/size; else mount fallback). enable_internet=true.
- `.env`: R2_ENDPOINT/R2_BUCKET/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_ACCOUNT_ID + STORAGE_PUBLIC_ENDPOINT. Dev localstack.
- Test DB server: `...img2text_test`. Web: `cd web && npm test && npx tsc -b --force && npm run build`.
- GIỮ OUTPUT NHỎ.

## Review Focus

- presign_post policy đúng (content-length-range, key, expiry, content-type).
- Upload flow: UI POST form→R2 (không qua backend); head-verify 404; page_count từ pdf.js.
- Kernel manifest dual-mode: URL download + sha256 verify; mount fallback dev; download fail → retry.
- Backward: dev localstack + mount vẫn chạy; prod đổi .env.

---

### Task F1: storage `presign_post` + config
**Files:** `app/services/storage.py`, `app/core/config.py`, `.env.example`. Test: `tests/test_storage_presign.py`.
- [ ] Red: presign_post policy (content-length-range, key, expiry). Green. Commit.

### Task F2: upload flow (server + web)
**Files:** `app/routers/jobs.py` (presign + metadata create, bỏ multipart), `web/src/api/client.ts` (+presignUpload), `web/src/components/Dropzone.tsx` (POST form→R2 + pdf.js count). Test: `tests/test_presign_upload.py` + web.
- [ ] Red: presign endpoint, head-verify 404, create metadata. Web: POST form→R2, page count. Green. Commit.

### Task F3: pipeline manifest + kernel dual-mode
**Files:** `app/services/kaggle_orchestrator.py` (manifest + presign GET), `deploy/kaggle/kernel/img2text_batch.py` (fetch_input dual-mode). Test: kernel unit (local http.server).
- [ ] Red: manifest stage, kernel URL download + sha256 verify, mount fallback. Green. Commit.

### Task F4: gate + verify
- [ ] Server subset + web gate + kernel import. Commit.
