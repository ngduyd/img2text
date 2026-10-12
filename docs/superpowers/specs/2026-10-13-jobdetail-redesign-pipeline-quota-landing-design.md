# Spec: JobDetail 2-section redesign + pipeline ảnh + quota + landing mới

Ngày: 2026-10-13. Nguồn: user yêu cầu trực tiếp (21 mục liệt kê + 4 chỗ chốt).
Chốt: nút tải = 2 nhóm (Văn bản | Layout); remove background = `rembg` (u2net);
landing = viết mới toàn bộ + self-capture playwright; quota = page_count, refund khi
fail/hủy, tuần T2→CN Asia/Ho_Chi_Minh, chặn lúc upload, LLM không tính.

## WS-UI — JobDetail 2 section (items 1-9, 13, 14)

### Cấu trúc trang (cuộn dọc, 2 section)
```
[Header job: tên + status + Chạy lại/Hủy + Lịch sử] [badge "Cần đồng bộ"]

SECTION 1 "Văn bản"  — grid lg:[7fr_5fr]
  trái 7: text render HTML thuần (GET /extraction), KHÔNG free editor.
          từ proofread (suggestions) → <mark> bg-warning/20 + underline dotted.
          click → popover: "Đề xuất: X" [Áp dụng] [Bỏ qua] | ô nhập "Sửa khác…" [Lưu].
          Áp dụng/Sửa khác → POST /extraction (old/new phrase) → save+sync → invalidate.
          KHÔNG còn IssuesPanel ở layout — panel "Kiểm tra lỗi" (issues accordion
          + inline region edit) chuyển vào đây (dưới text).
          Hiện kể cả status == "rendering" (OCR xong).
          Nút "Lưu văn bản": nếu response requires_rerender hoặc status rendering →
          modal confirm (useDialogA11y):
          "Lưu văn bản sẽ cần vẽ lại layout. Thêm vào hàng đợi vẽ layout?"
          [Hủy] [Lưu & xếp hàng] → toast + invalidate.
          Link "Mở trang trích xuất đầy đủ".
  phải 5: ẢNH GỐC — auto-fetch blob khi mount (bỏ toggle "Hiện file"),
          sticky lg:top-16, cùng padding/align-start với cột trái.
          PDF nhiều trang → container cuộn (h-[75vh]) + nút zoom −/+ và slider
          (pdf.js render trang → canvas; deps pdfjs-dist đã có).
          Ảnh đơn → zoom container (buttons + wheel).
          1 fetch blob chung cho cả 2 section (module-level cache theo jobId).

SECTION 2 "Layout"  — grid lg:[7fr_5fr]
  trái 7: XEM TRƯỚC mặc định, read-only, styled:
    • word (docx.html): iframe sandbox srcDoc = docx.html + <style>{docStyle}</style>
    • md (md-layout): md → HTML (renderer markdown tối giản/đã có deps) + docStyle,
      sanitize (DOMPurify hoặc escape nghiêm ngặt).
    ảnh figure node (crop artifact, xem WS-PIPE) render <img> presigned 24h thay marker.
    Toggle "Chỉnh sửa" → WordEditor (Tiptap docx.html) / MDEditor (md) như hiện tại
    (set detached=true). Stats line dưới preview.
  phải 5: ẢNH GỐC (cùng component, dùng lại blob cache — không fetch đôi).
  Cột rail còn lại (ExportBar 2 nhóm + InfoPanel) — ExportBar đặt DƯỚI preview
  cột trái (không còn trong rail chen chung), InfoPanel gọn cột phải dưới ảnh.

### Nút tải định dạng (item 13 = B)
2 nhóm trong ExportBar:
  • "Văn bản": md | docx | pdf (thuần text, các export hiện có)
  • "Layout": md-layout | docx-layout (bản dựng layout)
UI: 2 dropdown button nhóm; giữ testids cũ R51 (điều chỉnh).

### Fix kèm theo
- crop404 spam: IssuesPanel/Crop chỉ fetch crop khi job.file_type=="image",
  query retry:false. PDF → hiện text region.
- log LLM: render_md.py:323 + render_docx.py:275 → repr(exc) + attempt;
  fallback log loud "HEURISTIC FALLBACK render — layout tạm".

## WS-SERVER — hàng đợi render (item 4)

- Migration: `ALTER TABLE jobs ADD COLUMN rerender_requested boolean DEFAULT false;`
- `POST /api/jobs/{id}/extraction`: cho phép khi status=="rendering"; save set
  `rerender_requested=true` KHI (status=="rendering") hoặc (layout artifact tồn tại
  && sync targeted-fail); KHÔNG set khi mode=="extract_only".
  Response thêm `requires_rerender: bool`.
- Render/completion finalize: trước khi done → nếu rerender_requested → clear flag +
  render lại tối đa 1 lần (loop guard 2; quá 2 → done + giữ flag + log warning).
- Đặt reaper/sweep hiện có làm tương tự khi job stuck rendering + flag.

## WS-PIPE — pipeline trích xuất ảnh + remove background (items 15, 16)

- Kernel (`deploy/kaggle/kernel/img2text_batch.py`):
  với mọi region verdict=="image_unextractable" (và placeholder): PyMuPDF
  `page.get_pixmap(clip=bbox)` → PNG crop.
  rembg (u2net) remove background → `img2text-crops/{job_id}__{rid}.png`.
  Model u2net.onnx (~170MB) đưa vào dataset wheelbuild-env (cache, tránh tải mỗi run).
  Upload crops qua manifest/Kaggle output → orchestrator ingest về S3
  `exports/{job_id}/crops/{rid}.png` (S3Driver).
- Server render:
  docx-layout: embed bytes crop (html_to_docx img src = bytes) — không phụ thuộc URL.
  md-layout: `![vùng {rid}]({presigned 24h})`.
  LayoutPreview (web): figure node → <img> presigned (invalidate khi hết giờ).
- Timing: kernel +~10-30s/ảnh (rembg GPU), budget trong batch run.

## WS-WEB — Landing page mới (item 17)

- VIẾT MỚI toàn bộ copy (Vietnamese) + design theo skill design-taste-frontend +
  DESIGN.md (dark, một accent, radius 6/8, không em-dash).
- Cấu trúc đề xuất: Hero (giá trị + CTA) → Cách hoạt động (OCR→IR→Layout pipeline,
  3 bước) → Tính năng (2 section, version/undo, proofread click-fix, export 5 định
  dạng) → Gallery screenshot → Giới hạn/quota → CTA cuối + Footer.
- Screenshot: cài playwright (devDep web hoặc scripts/ riêng) — capture từ dev stack
  thật (cần login; seed dev user hoặc reuse token): Jobs list, JobDetail section
  Văn bản, Section Layout preview, Extraction page. Ảnh PNG vào web/public/screenshots/.
- Landing route hiện có (pages/Landing.tsx) → thay nội dung; giữ auth flow.

## WS-ADMIN — settings + quota (items 18-21)

- Admin runtime settings mở rộng: `llm_timeout` (số, 30-600), `llm_api_key`
  (write-only: hiện masked "sk-…last4", submit mới ghi đè; không log).
- Quota:
  Migration: `ALTER TABLE users ADD COLUMN daily_page_limit int DEFAULT 25;`
             `ALTER TABLE users ADD COLUMN weekly_page_limit int DEFAULT 150;`
  Usage = SUM(jobs.page_count) WHERE created_at trong cửa sổ
  (ngày: local Asia/Ho_Chi_Minh; tuần: T2→CN) AND status NOT IN ('failed','cancelled').
  Check tại POST /jobs/presign + POST /jobs (pre-create) → 429
  "Hôm nay bạn đã hết quota (25 trang). Quay lại sau." / tuần.
  GET /api/quota/me → {daily_limit, daily_used, weekly_limit, weekly_used,
  daily_remaining, weekly_remaining}.
  UI: Jobs header "Còn X trang hôm nay · Y tuần này" (query invalidate sau tạo job).
  Admin: bảng user → cột quota (đã dùng/còn) + inline edit limit (2 ô) + audit.

## Migration/Deploy checklist (thêm)
- ALTER TABLE jobs ADD COLUMN rerender_requested boolean DEFAULT false;
- ALTER TABLE users ADD COLUMN daily_page_limit int DEFAULT 25;
- ALTER TABLE users ADD COLUMN weekly_page_limit int DEFAULT 150;
- Wheelhouse-env dataset: thêm u2net.onnx (rembg model) — rebuild wheelbuild kernel.

## Phasing (lane)
- **A**: WS-UI + WS-SERVER (JobDetail 2 section + queue + fixes) — đau nhất, làm trước
- **B**: WS-PIPE (kernel ảnh + rembg + ingest crops + render embed)
- **C**: WS-ADMIN (settings + quota + widget)
- **D**: WS-LANDING (sau A — cần screenshot từ UI mới)
A/B/C song song được (file disjoint: web+server routers/jobs vs kernel/deploy vs admin).
Review loop mỗi lane (round 1 → fix → re-check, cap 3).

## Testing
- Server: extraction save khi rendering (flag+429/200), finalize rerender guard,
  quota check (day/week boundary, refund), crop ingest.
- Web: section render khi rendering, confirm modal queue, popover "Sửa khác",
  preview styled (iframe srcDoc chứa docStyle), zoom/pdf scroll, ExportBar 2 nhóm.
- Kernel: crop extract unit (PyMuPDF clip) + rembg stub (mock model).
- Landing: build pass, screenshot files exist.
