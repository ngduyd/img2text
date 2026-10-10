# Spec: Chuyển storage sang Cloudflare R2 + presigned upload + pipeline fetch URL

Date: 2026-10-10
Status: design đã duyệt (presigned POST, backend metadata-only, pipeline manifest dual-mode, 3-lớp test)
Path: architectural → spec → writing-plans

## Problem

- Storage hiện localstack (docker) — file + artifacts nằm local.
- Upload: UI → backend multipart → backend **đọc file** (page_count/preprocess) → storage.put. File chạm backend (attack surface mã độc).
- Pipeline: backend **copy file vào dataset** `img2text-input` → upload Kaggle → kernel đọc mount ("gửi file thủ công", tốn staging + upload mỗi run).

## Intent

- **Storage → R2** (S3-compatible). Dev giữ localstack (endpoint split sẵn).
- **UI upload thẳng R2** qua **presigned POST** (content-length-range cap) — backend **chỉ metadata**, không chạm bytes (tránh mã độc).
- **Pipeline tải file từ URL** (presigned GET) thay vì copy vào dataset. Kernel **dual-mode**: có URL → tải; không → mount fallback (dev).
- Đếm trang **client-side** (pdf.js) → gửi metadata.

## Non-goals

- Đổi format/OCR pipeline. Đổi job.state machine. Đổi version/sync subsystem.
- Public bucket (R2 giữ private; URL presigned).

---

## Sub-system F1: Storage presign POST + R2 config

- `S3Driver.presign_post(key, expires, max_bytes, content_type)` → dict `{url, fields}` (policy: `content-length-range [0, max_bytes]`, `key`, `content-type`, expiry). Dùng `generate_presigned_post`.
- Config `.env`: `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` (build endpoint `https://{account_id}.r2.cloudflarestorage.com` nếu R2_ENDPOINT trống), `STORAGE_PUBLIC_ENDPOINT` (presign cho browser). Dev: localstack `:4566`.
- Driver đã S3-compatible; thêm `presign_post` (chỉ có `presign_get`).

## Sub-system F2: Upload flow (backend metadata-only)

- `POST /api/jobs/presign` `{filename, content_type, size_bytes, page_count, output_format, mode}` → sanity-check bounds (size ≤ max, page_count ≤ 100, format/mode enum) → sinh `storage_key` (content-addressed: sha256 prefix) → `presign_post` → trả `{storage_key, url, fields, max_bytes}`.
- **UI**: POST form (fields) thẳng tới R2 (không qua backend). Đếm trang client-side (pdf.js) → `page_count`.
- `POST /api/jobs` `{storage_key, page_count, output_format, mode}` → backend `head(storage_key)` xác minh tồn tại (KHÔNG đọc bytes) → tạo Job. Bỏ multipart `UploadFile` path (hoặc giữ làm legacy fallback — chốt trong plan).
- **Không còn**: backend đọc file cho page_count/preprocess.

## Sub-system F3: Pipeline manifest + dual-mode fetch

- Khi spawn batch: backend sinh **presigned GET** (`expires 3600s`) cho file → stage **`manifest.json`** `{job_id, input_url, filename, sha256?}` vào dataset input (vài byte; KHÔNG copy file lớn).
- Kernel `img2text_batch.py`: đọc `manifest.json` từ mount → có `input_url` → **tải về** (`urllib`/`httpx`) + verify sha256/size → xử lý. Không có manifest/URL → **fallback glob mount** (giữ dev staging).
- `enable_internet=true` đã có.

## Sub-system F4: Artifacts → R2

- `exports/{id}/{fmt}`, `versions/...` → cùng R2 driver (config). Không đổi code (driver abstracts). Dev localstack.

## Testing (3-lớp — không cần R2 thật ở dev)

1. **Unit (offline)**: `presign_post` policy đúng (content-length-range, key, expiry); kernel `fetch_input(url, dest)` với local `http.server` → download + sha256/size verify.
2. **Integration Kaggle leg**: manifest với **public URL** thật → run kernel trên Kaggle → verify tải về (độc lập R2).
3. **Dev E2E**: không URL → mount fallback → chạy như hiện tại (localstack).

Prod: điền R2 creds `.env` → presigned GET/POST thật → kernel tải từ R2.

## Error handling

- presign_post fail → 500. head(key) fail khi tạo job → 404 "File chưa tải lên".
- Kernel download fail (URL hết hạn/network) → log + retry job (đã có batch retry); manifest fallback mount.
- sha256 mismatch → kernel fail job đó (partial-fail đã có).

## Migration / deploy

- `.env` mới: R2_* + STORAGE_PUBLIC_ENDPOINT. Không migration DB (storage abstracts).
- Dev: giữ localstack, không cần R2.

## Phasing

- **F1** (presign_post + config) → **F2** (upload flow) → **F3** (pipeline manifest/kernel) → **F4** (artifacts, verify).
- F1+F2 (server+web upload) song song được với F3 (kernel) — tách file. F3 cần F1 (presign_get đã có) nhưng tách kernel.

## Quyết định mở (đã chốt)

- Bỏ hẳn multipart `UploadFile` — chuyển hết sang presigned POST.
- `max_bytes` cap = **50MB**.
