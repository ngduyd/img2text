# Plan: JobDetail 2 section + pipeline crop/quota/landing (2026-10-13)

Base: master `b4dae41`. Spec: `docs/superpowers/specs/2026-10-13-jobdetail-redesign-pipeline-quota-landing-design.md`.

## Lane C (server: quota + admin LLM) — độc lập, ship trước

- Migration `docs/migrations/2026-10-13_quota_admin_llm.sql`: `ALTER TABLE users
  ADD COLUMN daily_page_limit int DEFAULT 25`, `weekly_page_limit int DEFAULT 150`.
- Config `settings.llm_timeout` (int, default 180), `llm_api_key` (str|None) +
  parity `.env.example`.
- Quota module `server/app/services/quota.py`: `check_quota(session, user_id,
  page_count) -> None | HTTPException(429)` (Asia/Ho_Chi_Minh; week Mon→Sun);
  `get_quota(session, user_id) -> dict`; refund trên failed/cancelled (hook vào
  jobs fail + delete).
- `POST /api/jobs` (create): đếm quota pre-create → 429 nếu vượt.
- AdminUsers: quota inline edit (daily/weekly limit); AdminSettings: llm_timeout
  input + llm_api_key masked write-only (không echo; PATCH để trống = giữ).
- Tests TDD: quota check, refund, parity, masked key.

## Lane A (server: fix blocker + magic sniff)

- `img2text_batch.py`: rename `process_job(preprocess=...)` → `preprocess_spec`
  (param shadow module fn `preprocess`). Test red→green (import module, callable).
- `POST /api/jobs` create: sau head-verify, GET object (≤50MB) → sniff 16 byte
  đầu: `%PDF`→pdf, `\xff\xd8\xff`→jpg/jpeg, `\x89PNG\r\n\x1a\n`→png, `RIFF..WEBP`→webp.
  Mismatch ext → 422 "File không khớp đuôi (.X)" + `storage.delete(key)`.
- HEIC/HEIF/AVIF: add `ALLOWED_EXTENSIONS` + `CONTENT_TYPE_BY_EXT` +
  `pillow-heif`/`pillow-avif` deps + `register_heif_opener()` (server boot).
  Verify = fixture ảnh thật. JPEG-XL: docs note defer.
- EXIF-rotate: `ImageOps.exif_transpose` trước OCR (kernel `_apply_preprocess`
  hoặc rasterize step).
- Tests TDD: rename shadow, magic sniff (pdf-as-jpg→422), heic/avif open,
  exif_transpose.

## Lane B (web: JobDetail 2 section + preview styled + quota badge)

- JobDetail: bỏ tab Extraction/Layout; 2 section dọc (cuộn dọc):
  1. **Văn bản**: IssuesPanel + Markdown render + click-to-highlight.
  2. **Layout**: styled preview (iframe sandbox + docStyle) + 7/5 ảnh gốc
     (grid: preview 7, ảnh 5, responsive stack mobile).
- Preview styled: default = styled HTML (font Inter, radius 6/8, spacing
  4/8/16/24/32/48, accent); toggle xem Markdown/HTML/Styled.
- ExportBar: 2 nhóm label ("Văn bản" / "Layout"); md/html/docx/pdf vs
  md-layout/docx-layout.
- QuotaBadge: header + Jobs (còn X/Y trang hôm nay; fetch `/api/quota/me`).
- Upload: accept + heic/heif/avif extensions (types.ts + MultiFileUpload).
- Tests TDD: 2 section, styled preview, quota badge, accept extensions.

## Lane D (landing mới + capture script)

- `web/src/pages/Landing.tsx`: hero + gallery 6 slot screenshot + copy Việt
  (đã có; mở rộng slot).
- `web/scripts/capture.mjs`: Playwright Chromium; seed account (register API);
  navigate → upload fixture jpg → job → 2 section → layout preview → export →
  admin; capture PNG đúng kích thước hero/gallery.
- README: hướng dẫn chạy tay capture (sandbox chặn Chrome).
- Tests: landing render; capture script = manual (user chạy tay).

## Thứ tự

1. Lane C + A (server) song song (independent files) → review loop → merge.
2. Lane B (web) sau C+A (cần quota endpoint + magic error response).
3. Lane D (landing) cuối (cần B 2 section + styled preview để capture).

## Risks / notes

- HEIC/AVIF plugin có thể thiếu native lib → fallback `pillow-heif`/`pillow-avif`
  (server deps +5MB); JPEG-XL defer.
- Magic sniff = 1 GET thêm mỗi create (chấp nhận ≤50MB).
- Quota migration cần prod checklist (dev đã ALTER tay).
- Landing capture CHẠY TAY trên máy bình thường (sandbox chặn Chrome network).
- Refcount/magic/delete race = P2 backlog (đã ghi nhận).
