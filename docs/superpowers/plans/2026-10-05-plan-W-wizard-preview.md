# Plan W — Upload Wizard (B + image crop) & Export Preview Tabs

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** (1) Upload wizard: PDF → client-side page selection + per-page rotate, original file uploaded untouched + `preprocess` metadata honored by server/worker; Image → client-side crop/rotate, cropped blob uploaded as the file. (2) Job-detail "Tài liệu" preview tabs: Markdown / PDF / DOCX (mammoth → sanitized sandbox iframe).

**Architecture:** Sequential single worktree `plan-wizard-preview` (web/ shared by W3-W5; server/worker only in W1-W2). Server: new nullable TEXT column `jobs.preprocess` (JSON string) + optional field on POST /api/jobs + included in GET /jobs/next payload + validation. Worker: after pdftoppm, filter selected pages + apply rotation (PIL transpose) before pre-check/VLM; page index in result = ORIGINAL PDF page number (1-based) even when filtered. Web: pdfjs-dist wizard (PDF), canvas crop wizard (image, no server change — cropped blob IS the upload), PreviewTabs (mammoth for DOCX bytes via NEW server download endpoint to dodge CORS; PDF via presigned iframe; MD via existing sandboxed preview).

**Tech Stack:** existing + `pdfjs-dist`, `mammoth` (web deps), pypdf already server-side, PIL already worker-side.

**Spec:** docs/superpowers/specs/2026-10-04-img2text-mvp-design.md §4/§7/§8/§10 + approved in-chat design 2026-10-05 (B + image crop + preview docs/pdf/md).

## Global Constraints

- Preprocess JSON shape (binding): `{"pages": [int,...] | null, "rotate": {"<page>": 0|90|180|270}}`. `null`/absent pages = all pages. Validation on POST /api/jobs (422 Vietnamese messages): pages non-empty when present, ints within 1..page_count (pdf only; image jobs reject non-null preprocess), rotate keys ⊆ selected pages, values ∈ {0,90,180,270}. Store as TEXT column `preprocess` on jobs (JSON string, nullable). GET /jobs/next payload adds `"preprocess": <parsed dict|null>`.
- Worker rotation mapping (clockwise): 90→`Image.ROTATE_270`, 180→`Image.ROTATE_180`, 270→`Image.ROTATE_90`; applied AFTER rasterize BEFORE precheck; width/height swap for 90/270 (affects bbox frame + dims in result). Filtered pages keep ORIGINAL 1-based page numbers as `page` index in result JSONB (region ids p{N}r{M} use original numbers). Absent preprocess = behavior identical to today (regression tests must stay green).
- Image crop wizard: canvas crop + rotate client-side → `api.uploadJob(croppedBlob, filename?)` — uploadJob signature gains optional filename; server unchanged (cropped blob is the file). Cropped output JPEG q0.92 (or PNG when transparency? pin: always JPEG quality 0.92, extension .jpg — simplest, matches upload types).
- DOCX preview CORS: NEW tiny server endpoint `GET /api/jobs/{id}/export/{fmt}/download` (owner-or-admin, done-only, fmt md|html|docx|pdf) → server fetches export bytes from R2 (storage.get on exports/{id}/{fmt}; 404 → generate? NO — 404 "Chưa xuất file." if absent; client calls exportJob POST first then download GET) → stream bytes with Content-Type (docx vnd.openxmlformats, pdf application/pdf, html text/html, md text/markdown). Presigned window.open flow REMAINS for the Tải buttons (no behavior change).
- Preview tabs (JobDetail ResultPanel, new Card "Tài liệu" testid panel-docs): tabs preview-md|preview-pdf|preview-docx. MD = existing MarkdownPreview of current_markdown. PDF = lazy: first activation → api.exportJob(id,"pdf") → iframe src=url (sandbox NOT needed for pdf viewer; title attr). DOCX = lazy: api.exportJob(id,"docx") → api.downloadExport(id,"docx") → arrayBuffer → mammoth.convertToHtml → DOMPurify → sandboxed iframe (testid preview-docx-frame) + note line "Xem trước DOCX: giữ nội dung, mất định dạng font." (testid docx-note).
- Deps: pdfjs-dist + mammoth via npm in web/. pdfjs worker configured for vite (`?url` import pattern). Tests vi.mock pdfjs-dist/mammoth modules (R30).
- TDD red→green per task; R33-style lane isolation if any parallel (this plan runs sequential single lane, default DB :5433 — dev stack postgres hosts img2text_test, no prefix needed); single commit per task; never weaken assertions; preserve existing testids (R51).

## Review Focus

- Preprocess roundtrip: POST validation (bad pages/rotate → 422 exact) → stored → /jobs/next payload → worker filter+rotate; result page numbers original; bbox dims swapped for 90/270.
- Backward compat: no preprocess → worker identical behavior (existing worker tests untouched+green).
- Wizard tests mock pdfjs — assert uploadJob called with ORIGINAL file + preprocess payload; crop wizard asserts uploadJob called with cropped BLOB.
- PreviewTabs: lazy fetch (exportJob only on tab activation), docx sanitize (script stripped), 404 flow (export first, then download).
- Security: download endpoint owner-or-admin + content-type mapping (no path injection — fmt Literal).

---

### Task 1: Server — preprocess column + validation + payload

**Files:** Create server/tests/test_preprocess.py; Modify server/app/models.py (Job.preprocess TEXT nullable), server/app/routers/jobs.py (POST /api/jobs optional field + validation + store; GET /jobs/next payload += parsed preprocess), server/app/schemas.py (PreprocessIn model).

- [ ] Step 1 failing tests: upload pdf with preprocess {"pages":[1,3],"rotate":{"3":90}} → job.preprocess stored + /jobs/next returns parsed dict; invalid: empty pages list → 422 "Chưa chọn trang nào."; page 99 > page_count → 422 "Trang chọn vượt quá số trang của file."; rotate key not in pages → 422 "Xoay áp dụng cho trang đã chọn."; rotate value 45 → 422 "Góc xoay không hợp lệ."; image job + preprocess → 422 "Chỉ file PDF hỗ trợ chọn trang."; absent preprocess → null roundtrip (existing behavior).
- [ ] Steps 2-4 TDD cycle.
- [ ] Step 5 commit `feat(server): job preprocess (page selection + rotation) metadata`.

### Task 2: Worker — page filter + rotate

**Files:** Create worker/tests/test_preprocess_filter.py; Modify worker/pipeline.py (run_job: parse job payload preprocess; after pdftoppm: filter + rotate; pass original page numbers), worker/pipeline build_page index semantics documented.

- [ ] Step 1 failing tests (fake rasterize list of 4 numbered PIL images, distinct colors/quadrants): preprocess pages [2,4] → only 2 pages processed, result pages indices [2,4]; rotate {"2":90} → page 2 dims swapped (w/h exchanged) + quadrant colors rotated clockwise (assert pixel at corner); absent preprocess → 4 pages, identical indices [1,2,3,4] (regression); rotate 0 → no-op.
- [ ] Steps 2-4 TDD.
- [ ] Step 5 commit `feat(worker): honor preprocess page filter + rotation`.

### Task 3: Web — PDF upload wizard

**Files:** Create web/src/components/wizard/PdfWizard.tsx (+ test), web/src/lib/pdfjs.ts (loader wrapper, vi.mock-able); Modify web/src/components/Dropzone.tsx (file selected + type=pdf → render PdfWizard instead of immediate upload), web/src/api/client.ts (uploadJob(file, opts?: {preprocess?: object})), tests.

- [ ] Step 1 failing tests: select pdf → wizard renders (testid wizard-pdf) with page list (mock pdfjs: 3 pages, thumbnails rendered to canvases — assert page checkboxes testid wizard-page-{n}); default all checked; uncheck page 2; rotate page 3 → 90 (btn wizard-rotate-3 cycles or select — pin: select element testid wizard-rotate-3 options 0/90/180/270); submit testid wizard-submit "Gửi lên" → api.uploadJob called with ORIGINAL File + {preprocess:{pages:[1,3],rotate:{"3":90}}}; cancel testid wizard-cancel → back to dropzone empty. Image type → wizard NOT rendered (Task 4 owns).
- [ ] Steps 2-4 TDD.
- [ ] Step 5 commit `feat(web): pdf upload wizard (page select + rotate)`.

### Task 4: Web — image crop wizard

**Files:** Create web/src/components/wizard/ImageCropWizard.tsx (+ test); Modify Dropzone.tsx (type=image → ImageCropWizard), client uploadJob filename param.

- [ ] Step 1 failing tests: select image → wizard renders (testid wizard-image) with canvas + buttons btn-crop-rotate (90° cw), btn-crop-reset, wizard-submit — RULING R57 (2026-10-05): btn-crop-apply REMOVED from binding — live-rect (rect applies as dragged) supersedes manual apply click; ImageCropWizard ships without it; draw rect via fireEvent on canvas (mock canvas getContext + dimensions) → submit → api.uploadJob called with a Blob (instanceof, size>0, type image/jpeg) NOT the original File; rotate twice → canvas transform state (assert via mocked ctx calls or re-rendered img); cancel returns to dropzone. Gated like dropzone (banner unchanged).
- [ ] Steps 2-4 TDD.
- [ ] Step 5 commit `feat(web): image crop/rotate wizard before upload`.

### Task 5: Web+server — export preview tabs (docs/pdf/md) + download endpoint

**Files:** Create server/tests/test_export_download.py; Modify server/app/routers/exports.py (GET /{id}/export/{fmt}/download — owner-or-admin via _job_or_403, done, fmt Literal, storage.get(exports/{id}/{fmt}) KeyError→404 "Chưa xuất file.", stream bytes + Content-Type map); web/src/api/client.ts (downloadExport(id, fmt) → blob via fetch same-origin); Create web/src/components/PreviewTabs.tsx (+ test); Modify JobDetail ResultPanel (new Card "Tài liệu" panel-docs after ExportBar).

- [ ] Step 1 failing tests: server — download returns bytes + content-type (docx) when export exists (seed storage); absent → 404 "Chưa xuất file."; other user → 403. web — PreviewTabs renders 3 tabs (preview-md|pdf|docx); MD tab shows MarkdownPreview (existing behavior); PDF lazy: activation → exportJob(id,"pdf") + iframe src=url (assert one call, no eager); DOCX lazy: activation → exportJob(id,"docx") + downloadExport → mammoth.convertToHtml mocked → sanitized iframe (script stripped) + docx-note text present; activation again → no duplicate exportJob call (cache in state).
- [ ] Steps 2-4 TDD.
- [ ] Step 5 commit `feat: export preview tabs (md/pdf/docx) + download endpoint`.

### Task 6: Gate + docs

- [ ] Full suites: server pytest -q (expect 124 + new), worker pytest -v (25 + new), web npm test + tsc + build — paste outputs.
- [ ] README: dev section note (wizard flow) + docs/e2e-checklist.md: add checkboxes (wizard pdf select+rotate → worker only processes selected pages w/ original numbering; image crop upload; preview tabs md/pdf/docx render).
- [ ] Commit `chore: wizard+preview gate, docs checkboxes`.

**Plan W done when:** all 6 tasks green; branch ready for final review + merge.
