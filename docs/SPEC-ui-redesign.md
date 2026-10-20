# SPEC — Thiết kế lại UI (toàn hệ thống)

Trạng thái: DRAFT → chờ implement theo phase.
Căn cứ: review 48 ảnh chụp thật (12 route × 320/768/1024/1440) trên stack dev.
Design system hiện có: `web/DESIGN.md` (binding) + `tokens.css` / `index.css` `@theme`.
Ràng buộc R51: giữ `data-testid`, behavior, route public, i18n keys. Ngoại lệ phải ghi rõ trong phase.

---

## 0. Vấn đề gốc đo được

| Trang | Cao @1440 | Cao @320 | Nút | Lỗi chính |
|---|---|---|---|---|
| Landing | 3.961px (4,4 màn) | 4.756px (15 màn) | 5 | 6/6 ảnh preview rỗng; hero 40/60 |
| Jobs | 900 | 1.192 | 13 | container 768px trong 1440; 2 CTA upload; 5 action/dòng |
| JobDetail | 932 | 932 | 16 | cột trái 100% rỗng; heading trùng; card lồng card |
| Admin | 900 | 900 | 12 | 5 stat dọc @320; nav trùng (rail + 4 nút) |
| Profile | 1.060 | 1.152 | 9 | 2 form cùng "Current password"; label lệch cột |
| Storage | 900 | 900 | 6 | 3 stat trải 1.100px; cột Uploaded quá rộng |

Nguyên nhân chung: **không có luật bố cục / mật độ / thứ bậc nút**; nav gánh 9 phần tử; editor bị nhồi vào cột 700px.

---

## 1. Quyết định thiết kế (đã chốt)

| # | Quyết định |
|---|---|
| D1 | **1 shell**: container `1200px` (data pages) · `720px` (form/auth) · `1200px` (editor, full-width mode) |
| D2 | **Nav 4 phần tử**: brand · Jobs · Storage · avatar menu. Quota / theme / VI-EN / OCR / logout → vào avatar menu. `/features` bỏ khỏi nav |
| D3 | **JobDetail → 3 route**: `/jobs/:id` (overview) · `/jobs/:id/text` · `/jobs/:id/layout` |
| D4 | **Action hierarchy**: tối đa 1 primary + 2 secondary trên màn; còn lại vào `⋯` |
| D5 | **Upload 1 chỗ**: dropzone là primary; bỏ nút "Upload" trùng |
| D6 | **Editor tier B**: TipTap + extension nhóm 1 + custom nhóm 2 + `paged.js` cho preview A4 |
| D7 | **Pagination**: preview A4 song song, debounce 500ms (paged.js không thể chạy trên contenteditable sống) |
| D8 | **SplitPane** 3 trạng thái (Ảnh / Chia đôi / Văn bản), kéo được trên desktop, xếp dọc trên mobile |
| D9 | **Toolbar editor**: 1 hàng + `▾` (nhóm hiếm gom vào overflow), scroll ngang trên mobile |
| D10 | **Admin**: 5 stat → 1 hàng compact; bỏ 4 nút trùng; rail nhóm 3 cụm |

---

## 2. Phase 0 — Shell + Nav (nền, ảnh hưởng mọi trang)

### 2.1 Container
```
src/components/PageShell.tsx   (đã có — mở rộng)
width: "form"  → max-w-[720px]
       "data"  → max-w-[1200px]   ← thay cho content(3xl)/wide(6xl)
       "editor"→ max-w-[1200px] px-0 (editor tự quản padding)
padding: px-4 py-6 sm:px-6
```
Map lại: Jobs/Storage/Admin/JobDetail/Extraction → `data`; Profile/Feedback/Forgot/Reset → `form`; Landing giữ custom root.

### 2.2 AppNav
```
[img2text]  Jobs  Storage                        [22/25]  [☾]  [AU ▾]
                                                  ↑chip    ↑avatar menu
```
- Bỏ khỏi nav bar: `VI | EN`, `OCR enabled`, quota text dài, link **Features** → chuyển vào avatar menu / Landing.
- `/features` giữ route nhưng redirect về `/#roadmap` (link cũ không chết); component `Features.tsx` xóa sau khi nội dung roadmap đã nằm trong Landing.
- Quota giữ dạng chip gọn `22/25` (chỉ hiện khi đăng nhập, `title` có giải thích đầy đủ).
- Avatar menu (dùng `useDialogA11y` đã có): email · quota tuần · Ngôn ngữ (VI/EN) · Giao diện (theme) · OCR trạng thái · Profile · Admin (nếu role admin) · Đăng xuất.
- testid giữ: `nav-brand`, `nav-link-*`, `nav-avatar`, `nav-user-menu`, `nav-menu-toggle`, `mobile-menu`, `quota-remaining`, `lang-switch*` (move vào menu, giữ testid).
- Mobile: hamburger giữ nguyên; quota chip ẩn dưới 640px (vào menu).

### 2.3 SiteFooter
Giữ 1 hàng, thêm link `Features`. Không đổi logic.

---

## 3. Phase 1 — JobDetail tách 3 route

### 3.1 Routes (`App.tsx`)
```tsx
<Route path="/jobs/:id" element={<JobOverview />} />
<Route path="/jobs/:id/text" element={<JobText />} />
<Route path="/jobs/:id/layout" element={<JobLayout />} />
<Route path="/jobs/:id/extraction" element={<ExtractionPage />} />  // giữ
```
- `/jobs/:id/text` thay cho editor inline cũ.
- `/jobs/:id/layout` thay cho `UnifiedEditor` inline cũ.
- State `editing` chuyển từ `JobDetail` xuống từng page (hoặc URL query `?edit=1`).

### 3.2 `/jobs/:id` — Overview
```
┌──────────────────────────────────────────────────────────┐
│ ← Jobs   hoadon.pdf  [Done]                    [⋯]        │
├──────────────────────────────────────────────────────────┤
│ 1 trang · PDF · 192 B · 20/10 20:37                      │  1 hàng compact (không card)
├────────────────────────┬─────────────────────────────────┤
│ [thumbnail]            │ Lịch sử  (details, gập)          │
│ Xem file gốc ↗         │ Xuất: MD HTML DOCX PDF           │
└────────────────────────┴─────────────────────────────────┘
```
- Primary duy nhất theo trạng thái: `Queued` → "Hủy" (secondary) + chờ; `Done` → "Mở văn bản"; `Failed` → "Thử lại".
- `⋯` chứa: Tải file gốc, Lịch sử, Xóa job.
- **Không** render editor/TextSection ở đây.
- Giữ testid: `job-header`, `btn-download`, `btn-delete`, `panel-export`, `panel-info`, `panel-original`, `history-*`.

### 3.3 `/jobs/:id/text` — Văn bản
```
┌──────────────────────────────────────────────────────────┐
│ ← Job   Văn bản      [Ảnh│Chia đôi│Văn bản]   [Dựng layout →] │
├───────────────────────────┬──────────────────────────────┤
│  ẢNH GỐC (zoom, page nav) │  Lỗi phát hiện (3)           │
│                           │  ┌──────────────────────────┐│
│  ← click lỗi: highlight   │  │ "Nguyễn Văn A" → Nguyễn  ││
│    cả 2 phía              │  │ [Áp dụng] [Bỏ] [Sửa]     ││
│                           │  └──────────────────────────┘│
├───────────────────────────┴──────────────────────────────┤
│  VĂN BẢN ĐÃ TRÍCH XUẤT                    [Lưu] [↻ Dựng] │
└──────────────────────────────────────────────────────────┘
```
- `SplitPane` component mới:
  - 3 trạng thái qua segmented control (persist `localStorage: split-mode`)
  - Drag divider, `role="separator"`, `aria-orientation="vertical"`, `aria-valuenow`, focusable, ←/→ ±1%, double-click reset 55/45
  - Mobile (<768px): bỏ drag, xếp dọc
- **Lỗi gom 1 panel phải**: N lỗi = N block (thay vì 3N nút rải trong văn bản).
  - Giữ testid `btn-apply-{sid}`, `btn-reject-{sid}`, `btn-save-custom-{sid}` (chỉ đổi vị trí render).
- Save: 1 nút + autosave debounce. Bỏ toggle `btn-edit-text` (luôn editable).
- Giữ: `extraction-text`, `extraction-loading`, `extraction-error`, `btn-save-text`, `rerender-modal`, `btn-rerender-confirm/cancel`, `link-back-job`.

### 3.4 `/jobs/:id/layout` — Dựng layout (editor)
```
┌──────────────────────────────────────────────────────────┐
│ ← Job   Layout   [cached ✓]              [Lưu]  [⋯]      │
├──────────────────────────────────────────────────────────┤
│ Toolbar 1 hàng + ▾  (xem §4.2)                           │
├───────────────────────────────┬──────────────────────────┤
│  EDITOR (TipTap, liên tục)    │  PREVIEW A4 (paged.js)   │
│                               │  ┌──────────┐            │
│                               │  │  trang 1 │            │
│                               │  └──────────┘            │
│                               │  ┌──────────┐            │
│                               │  │  trang 2 │            │
└───────────────────────────────┴──────────────────────────┘
```
- **Bỏ tab MD/Word**. Markdown chuyển vào `⋯` → "Xem Markdown" (read-only drawer).
- **1 nút Lưu** (nội dung + style cùng lúc). Bỏ `btn-save-layout` / `btn-save-style` tách rời → gộp thành `btn-save-layout`, xóa `btn-save-style` khỏi UI (giữ i18n key).
- Giữ: `panel-editor`, `md-editor`, `layout-loading`, `layout-error`, `btn-retry-layout-error`, `layout-badge`, `word-tb-*` (đủ).

---

## 4. Phase 2 — Editor tier B

### 4.1 Extension thêm vào `src/lib/wordEditor.ts`
```ts
Highlight, Color, Subscript, Superscript, Link,
TaskList, TaskItem, Image, CharacterCount,
CodeBlockLowlight, Placeholder
// + config: Heading levels 1-6, Table resizable
```
Custom (attribute/command tự viết):
- `lineHeight` (attribute), `letterSpacing` (attribute)
- `indent` / `outdent` (Tab, Shift-Tab)
- `pageBreak` (node)
- Find & replace (`prosemirror-search` + UI panel)
- Zoom 50–200% (CSS scale + state)

### 4.2 Toolbar — 1 hàng + ▾
```
[↶ ↷] │ [B I U S] │ [màu ▾][highlight ▾] │ [≡ ⬅ ⬛ ➡] │ [• 1. ☑] │ [↩ ↪] │ [🔗 🖼 ⊞ ⤓] │ [Font ▾][Size ▾][Giãn dòng ▾] │ [▾ thêm]
```
- Nhóm cuối `▾ thêm`: Sub/Sup, Letter-spacing, Page break, Find, Zoom, Heading, In.
- Mobile: `flex-nowrap overflow-x-auto`, không wrap.
- Toolbar cao 40px; divider dọc giữa nhóm.

### 4.3 Preview A4 (`paged.js`)
- Component `LayoutPagePreview`: nhận HTML từ editor, render vào iframe/div, chạy `paged.js`, debounce 500ms.
- CSS A4: 210×297mm, margin 20mm, `--paper` token.
- Click trang → scroll editor tới vị trí tương ứng (anchor theo block id).
- Toggle ẩn/hiện preview (`localStorage: layout-preview`), mặc định hiện ở ≥1024px.

---

## 5. Phase 3 — Jobs list

```
┌──────────────────────────────────────────────────────────┐
│ Jobs                                    [Tải file lên]   │  ← primary DUY NHẤT
│ Theo dõi tiến trình OCR                                  │
├──────────────────────────────────────────────────────────┤
│ [3 Tổng] [3 Chờ] [0 Xong]  ← 1 hàng compact, inline      │
├──────────────────────────────────────────────────────────┤
│ [🔎 Tìm theo tên file…]                    [Sắp xếp ▾]   │
│ [Tất cả 3] [Chờ 3] [Đang trích 0] [Đang dựng 0] [Xong 0] [Lỗi 0]  ← 1 hàng, scroll ngang
├──────────────────────────────────────────────────────────┤
│ ┌ dropzone (chỉ hiện khi danh sách rỗng hoặc bấm CTA) ┐  │
│ └─────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│ ☐  #12  hoadon.png    Image · 1 trang   [Chờ]       ⋯    │  ← row = 1 link
│ ☐  #11  hopdong.pdf   PDF · 1 trang     [Chờ]       ⋯    │
```
- Row: click = mở Overview. `⋯` = Xem / Hủy / Xóa. Bỏ 3 nút rời.
- "Select all" chuyển thành header checkbox của list.
- Stats: 1 hàng `Tổng · Chờ · Xong` inline (không phải 3 khối).
- Sửa copy: "1 pages" → "1 trang" (`jobs.pageCount` interpolation).
- Giữ testid: `empty-state`, `empty-filter`, `job-row-*`, `btn-page-*`, `pagination`, `stats-total/pending/done`, `filter-*`.

---

## 6. Phase 4 — Admin
- 5 stat → 1 hàng compact (số + label cùng dòng, cao 56px, gap 8).
- Số format: GPU `0 s`, cost `$0.00`.
- **Bỏ** hàng 4 nút `Users/API/Logs/Stats` trùng rail.
- Rail nhóm 3 cụm có label nhỏ:
  - *Tổng quan*: Overview · Stats
  - *Vận hành*: Users · API · Logs · Storage
  - *Hệ thống*: System · Feedback
- Giữ testid `admin-rail`, `tab-*`, `stat-*`.

---

## 7. Phase 5 — Profile / Storage / Landing
- **Profile**: 2 form (password/email) → tab hoặc accordion; chỉ 1 form mở cùng lúc. Info card: label cột trái cố định 96px. Bỏ VI/EN trùng (đã vào avatar menu).
- **Storage**: 3 stat 1 hàng compact; "Delete N file(s)" xuống toolbar phải; cột Uploaded co lại (`w-40`), filename `flex-1 truncate`.
- **Landing**:
  - Gộp nội dung `/features` thành section **"Sắp có" (roadmap)** cuối trang: Organizations · custom worker pools · org-level storage · shared quotas & members.
  - Xóa section Preview rỗng → thay **1 mock tĩnh** (`landing-shot`) dùng ảnh/mock HTML thật, không để khung rỗng.
  - Hero cân lại 60/40 có visual; rút còn ~2,5 màn; bỏ câu "The whole page on a dark background."
- **Features**: xóa khỏi nav + xóa component sau khi merge; route redirect `/#roadmap`.

---

## 8. Component mới

| File | Props | Dùng ở |
|---|---|---|
| `components/SplitPane.tsx` | `mode: "image"\|"split"\|"text"`, `onModeChange`, `ratio`, `onRatioChange`, `left`, `right` | JobText |
| `components/PagePreview.tsx` | `html`, `css`, `zoom` | JobLayout |
| `components/EditorToolbar.tsx` | `editor`, `overflowItems` | JobLayout |
| `components/StatBar.tsx` | `items: {label, value, tone?}[]` | Jobs, Storage, Admin |
| `components/RowActionMenu.tsx` | `items: {label, onClick, tone?}[]` | JobRow, JobOverview |

---

## 9. Gate mỗi phase
```
cd web
npm test            # baseline 61 files / 441 tests — redirect route test phải update
npx tsc --noEmit    # exit 0
npm run build       # success
npx oxlint          # exit 0
```
Ảnh hưởng test dự kiến:
- `tests/pages/JobDetail.test.tsx` — route tách 3 → phải chia test theo page mới.
- `tests/App.test.tsx` — nav bớt phần tử (lang-switch move) → assert phải theo.
- `tests/pages/Jobs.test.tsx` — row action đổi (View/Cancel/Delete → ⋯ menu).

---

## 10. Thứ tự thực thi
- [ ] P0 Shell + Nav
- [ ] P1 JobDetail → 3 route (Overview trước, Text, Layout)
- [ ] P2 Editor extension + toolbar + PagePreview
- [ ] P3 Jobs list
- [ ] P4 Admin
- [ ] P5 Profile / Storage / Landing

## 11. Câu hỏi chưa chốt
(không còn — đã chốt: Features gộp vào Landing dạng section "Sắp có"; Landing thay Preview bằng 1 mock tĩnh)
