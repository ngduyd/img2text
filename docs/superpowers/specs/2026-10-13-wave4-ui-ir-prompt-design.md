# Spec: Wave-4 — UI JobDetail + IR prompt (2026-10-13)

Base: master `cef9529`. Tiếp nối wave-3. 8 điểm user báo (trả lời #6/#7/#8 ở session).

## Bối cảnh

UI test thật:2 nút "Chỉnh sửa" chồng chéo (btn-edit-doc thay luôn LayoutPreview →
btn-edit-layout chết); file gốc sticky vẫn khó chịu; download rải dưới; đổi định
đạng layout rối; không rõ khi nào layout vẽ lại. IR prompt không có rule multi-column
→ không nhận2 khối2 cột; COVERAGE fail → fallback stub 0 blocks ("xóa đầu ra").

## Users

Giáo viên thao tác trên tài liệu dài (20 trang), cần: sửa text thuần, xem file gốc
khi cần, đổi định dạng + vẽ lại layout rõ ràng, bản văn không mất.

## Đúng/sai/MVP

Đúng: soạn thảo Văn bản = textarea thuần text (paste strip — giáo viên dán Word
full formatting rác); Layout = TÁI DÙNG UnifiedEditor (Tiptap word + @uiw MDEditor
md — đã cài) cho cả md VÀ word pane; XÓA nút "Kiểm tra lỗi" (proofread) + refresh
trong UnifiedEditor; File gốc/Thông tin = collapsible; 1 nút "Chỉnh sửa" duy nhất;
download gộp1 nút dời header; đổi định dạng = switch md-layout ↔ docx-layout kèm
transition; "Vẽ lại layout" nút riêng. IR: geometry-first (bbox columns trước, type
sau) + map type vocabulary OCR→IR + coverage-fallback-keep-heuristic-render. Crop:
embed dùng on-demand /regions/{rid}/crop (đang chạy OK) thay vì S3 batch (rỗng).
Sai: sticky panel;2 nút Chỉnh sửa chồng chéo; textarea mới cho Layout (re-use lib).

MVP = mục 1-9.

## Assumption (verify lúc implement)

1. Paste strip: `onPaste` → `e.preventDefault(); insertText(clipboard plain)` —
   Firefox/Chrome khác API, verify cả2 (hoặc test jsdom + comment).
2. Collapsible: `<details>/<summary>` pattern (native, a11y free) hoặc Button +
   `aria-expanded` + height transition — chọn pattern có sẵn trong repo.
3. Đổi định dạng layout: gọi `POST /api/jobs/{id}/export` fmt mới → poll → toast;
   transition = CSS crossfade 200ms (không setTimeout giả).
4. "Vẽ lại layout" = `POST /api/jobs/{id}/retry-layout` (đã có) — chỉ cần nút +
   confirm + loading state.
5. IR multi-column: thêm rule "blocks with overlapping y-range and disjoint x-range
   on the same page = parallel columns; read left→right per row band" + test fixture
   b15/b17 →2 figure nodes không merge. Coverage fail → keep previous ir_json
   (không overwrite stub) + warning.

## User-facing behavior

1. **Section Văn bản**: GIỮ click-fix + suggestion (cho phép sửa các từ khác —
   hệ thống chỉ ra từ sai, user sửa hoặc sửa từ khác); SONG SONG thêm soạn thảo
   thuần text (UnifiedEditor word mode / Tiptap) cho sửa tay; paste → strip mọi
   formatting, chỉ giữ text + xuống dòng.
2. **File gốc + Thông tin** = collapsible sections (click mở/đóng), bỏ sticky panel.
3. Bỏ nút "Mở trang trích xuất đầy đủ".
4. **Layout**: tái dùng UnifiedEditor (Tiptap + @uiw MDEditor) cho md VÀ word pane
   đều sửa được; XÓA nút "Kiểm tra lỗi" (proofread Sparkles) + refresh (RefreshCw)
   trong UnifiedEditor (proofread LLM timeout 180s, vô dụng); gộp btn-edit-doc +
   btn-edit-layout còn1 nút.
5. **Download**:1 nút gộp dropdown, dời lên cạnh "Chỉnh sửa" (header actions).
6. Gộp2 nút "Chỉnh sửa" chồng chéo còn1.
7. **Đổi định dạng layout**: switch md-layout ↔ docx-layout ở header (transition
   crossfade 200ms) + nút "Vẽ lại layout" (retry-layout) + toast. Lịch sử giữ 4 kind.
8. **IR — cấu trúc theo TỌA ĐO (geometry-primary), không theo type**:
   Mục tiêu: IR quyết được KHI NÀO là bảng / list / heading mức N / cột song song
   — để layout render ĐỒNG BỘ (cùng input → cùng output).
   - **Group theo bbox TRƯỚC**: blocks overlapping-y + disjoint-x = cột song song
     (đọc trái→phải mỗi hàng); blocks x-align thành grid (nhiều hàng × cột đều)
     = bảng; blocks tuần tự có indent treo/bullet = list; block đứng đầu band =
     heading.
   - **type chỉ để ĐẶT LOẠI node SAU** khi đã group xong theo geometry.
   - Map type vocabulary OCR (header/seal/doc_title/text/figure) → IR enum tường
     minh (không đoán mò).
   - Coverage fail → fallback GIỮ heuristic render (`_cluster_columns` đang group
     đúng theo geometry) thay vì stub 0 blocks ("xóa đầu ra").
   - Test fixture b0/b2 trái + b3/b4 phải (header 2 cột) →2 cột song song, không
     gộp theo type; bảng grid → node table.
9. **Crop embed**: `embed_crop_keys` gọi on-demand `/regions/{rid}/crop` (200 OK)
   → nhét ảnh vào layout; batch `extract_crops` = cache (có dùng, không on-demand).

## Non-goals

Rich-text editor; rename định dạng file; dual-truth sync; IR zones cho bảng.

## Risks

- Paste strip mất undo history (textarea native undo vẫn OK — verify).
- Collapsible section height animation có thể gây layout shift mobile.
- IR multi-column rule tăng token prompt (~50) — chấp nhận.
- Coverage fallback giữ bản cũ → user thấy data cũ nếu LLM down — cần toast warn.

## Open questions

Không.
