# Spec: Redesign UI upload (nhiều file, crop/page-select, submit modal, ghép ảnh→PDF)

Date: 2026-10-10
Status: design đã duyệt (user mô tả; (a) follow-up sau R2; job = 1 PDF gộp client-side)
Path: architectural → spec → writing-plans

## Problem

- Upload hiện theo Phase 5: mode radios trong Dropzone + format picker; mỗi wizard (Pdf/ImageCrop) xử lý 1 file riêng.
- Chưa đúng design đã chốt: chưa có empty-state rõ ("Tải file lên" + "Kéo thả file vào"), nhiều ảnh chưa ghép, crop/page-select trải rộng, mode/format chưa phải modal lúc Gửi.

## Intent

- **Empty**: nút "Tải file lên" + hint "Kéo thả file vào".
- **Nhiều file** (ảnh + PDF, tổng **≤25 trang**):
  - **Ảnh**: thumbnail → **Xóa** + **chọn vùng (crop)** mỗi ảnh. Nhiều ảnh → **ghép thành 1 PDF** (client-side pdf-lib).
  - **PDF**: **chọn số trang** (≤25) + **Hủy**.
  - Nút **"Gửi"** giữ vị trí cũ.
- **Bấm "Gửi" → modal**: "Lấy văn bản" (extract_only) | "Lấy cả layout" → **md|word** → tạo job.
- Job = **1 PDF** (ảnh ghép hoặc PDF đã chọn trang) → **presign POST** (R2) → tạo job.
- **Backend metadata-only** (giữ nguyên R2 design) — merge ảnh→PDF **client-side**, không file qua backend.

## Non-goals

- Đổi job model (vẫn 1 job = 1 file/PDF). Đổi OCR pipeline. Đổi version/sync.
- Server multipart (đã bỏ ở R2).

## Sub-system U1: Multi-file upload state

- Dropzone nhận N files (ảnh + PDF). State: `files: {id, kind: image|pdf, blob, crop?, pages?, name}[]`.
- Empty state: "Tải file lên" button + "Kéo thả file vào" hint.
- Mỗi file card: thumbnail (ảnh) hoặc badge (PDF) + Xóa. Ảnh thêm nút "Chọn vùng" (crop). PDF thêm "Chọn số trang" (page-select).
- Tổng trang (ảnh gộp + trang PDF đã chọn) ≤ 25 → chặn + báo.
- Nút "Gửi" vị trí cũ (không đổi layout khung).

## Sub-system U2: Client-side image→PDF merge

- Khi Gửi: ảnh đã crop → **pdf-lib** ghép thành 1 PDF (theo thứ tự). PDF đã chọn trang → extract trang (pdf-lib). Nếu mixed ảnh + PDF → append (ảnh trước, PDF sau) → **1 PDF gộp**.
- Output: single PDF blob ≤25 trang. → presign POST (R2).

## Sub-system U3: Submit modal (mode + format)

- Click "Gửi" → modal: "Lấy văn bản" (extract_only) | "Lấy cả layout" → radio md|word (chỉ hiện khi layout).
- Confirm → upload PDF (presign POST, progress bar) → pdf.js đếm trang → tạo job (mode + output_format).
- **Thay thế** Phase 5 mode radios + format picker trong Dropzone.

## Sub-system U4: Sequencing + integration

- **Dispatch SAU khi R2 merge** (dùng presign POST + progress đã có). Replaces Phase 5 ModeSelector.
- Wizard hiện tại (PdfWizard/ImageCropWizard) → hợp nhất vào multi-file flow (crop/page-select per file card).

## Error handling

- >25 trang → chặn trước khi gửi, toast.
- Merge pdf-lib fail → toast, giữ files.
- presign/upload fail → toast (R2 flow).

## Testing

- Multi-file state: thêm N ảnh → N cards; Xóa/crop per image.
- Merge: 2 ảnh → 1 PDF (pdf-lib, mock) — page count đúng.
- PDF page-select: extract trang (mock pdf-lib).
- Modal: extract_only | layout+md/word → tạo job đúng mode/format.
- >25 trang → chặn.

## Open

- Crop UI: tái dùng ImageCropWizard logic per-image hay crop đơn giản hơn (drag-rect trên thumbnail)?
- PDF page-select: range input hay thumbnail grid chọn trang?
