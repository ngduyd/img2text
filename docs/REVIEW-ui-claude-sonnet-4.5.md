# UI review — job view + văn bản/layout + editor

**Ngày:** 2026-11-06 · **Review-only**, không sửa code.

## Phương pháp

| Thành phần | Chi tiết |
|---|---|
| Model review | `KG/claude-sonnet-4.5` (vision) qua 9router `:20128` — prompt_tokens 40 078, completion 473 |
| Model yêu cầu ban đầu | `ocg/kimi-k3.1-pro` → **không dùng được**: 502 fetch connect timeout ×8, rồi `GoUsageLimitError` (hết quota opencode-go, cả `ocg/kimi-k3` cùng lỗi). Đã thử 12 lần, bỏ |
| Ảnh | Playwright/Chrome thật, job **#84 `e2e-de-thi.pdf`** (done, 1 trang, OCR thật Việt+Trung), 1440×900 và 390×900, fullPage — `/tmp/ui-review/*.png` |
| Code đưa vào prompt | `JobDetail.tsx`, `UnifiedEditor.tsx`, `WordEditor.tsx`, `WordToolbar.tsx`, `DocStyleTools.tsx`, `LayoutPreview.tsx`, `editor-surface.css` |
| Đo bổ sung | `getBoundingClientRect` + `scrollHeight` trên DOM thật (bảng dưới) |

**Số đo DOM thật @1440 (viewport 1440, `main` = 1200px):**

| Vùng | Rộng | Cao khung | Cao nội dung | Overflow |
|---|---|---|---|---|
| `/jobs/84/layout` → `[data-testid=preview-md]` | **595** | 675 | **2969** | auto |
| `/jobs/84/edit/word` → `.wp-paper` | 794 | — | 2788 | visible |
| `/jobs/84/edit/word` → `.wp-paper-scroll` | 1152 | **666** | 2864 | auto |
| `/jobs/84/edit/word` → `.ProseMirror` | 605 | 2647 | 2647 | visible |
| `/jobs/84/edit` (md) → `.w-md-editor` | 960 | **2184** | 2182 | hidden |

**Dữ liệu đã sửa để chụp:** job #82 (markdown rỗng) revert nguyên trạng; user `ui-demo@example.com` được set lại `password_hash` = của user audit để login xem job #84. Không sửa `result` của #84.

## Findings (đã kiểm chứng bằng ảnh + code/số đo)

| # | Sev | file:line | Issue → Fix |
|---|---|---|---|
| 1 | P0 | `components/JobRow.tsx:133` | Danh sách job **không hiển thị `job.filename`** — chỉ `#id · PDF · 1 page` (ảnh `jd-jobs__1440`: hàng duy nhất không có tên file). Nhiều file cùng loại → không phân biệt được → thêm `<span class="truncate">{job.filename}</span>` sau `#id` |
| 2 | P1 | `lib/docStyle.ts:75` | `max-width: 65ch` áp cho `.layout-preview` khiến tab Layout chỉ rộng **595px** giữa `main` 1200px, nội dung dài **2969px** phải cuộn lồng 4.4 màn (ảnh `jd-layout__1440`, chữ CJK wrap 2–3 chữ/dòng) → bỏ `max-width` khỏi pane container, chỉ giữ measure cho `p`/`li` |
| 3 | P1 | `styles/editor-surface.css:181-195` | `.wp-paper-scroll { max-height: var(--ed-h, min(74vh,780px)) }` nhốt tờ A4 **2788px** vào khung **666px** → mở trang Word chỉ thấy ~1/4 tờ giấy, phải cuộn trong khung (ảnh `jd-edit-word__1440`, `@390`) → cho `.wp-paper-scroll` cao theo nội dung, cuộn ở cấp trang; hoặc tách trang A4 thật thành nhiều trang |
| 4 | P1 | `pages/JobDetail.tsx:751` + `components/UnifiedEditor.tsx:258-270` + `components/editor/WordEditor.tsx:59` | **3 nút lưu cùng lúc** ở Word mode: `Save layout style` (header), badge `Layout saved`, `Save` (dưới details A4). Người dùng không biết nút nào ghi cái gì → gộp 1 nút Save, badge thành trạng thái dirty/saved |
| 5 | P1 | `components/UnifiedEditor.tsx:336` + `pages/JobDetail.tsx:742` | Mode Markdown: `.w-md-editor` cao **2184px**, không scroll nội bộ → trang dài 2321px; `Save`/`Layout saved` nằm ở đầu trang, cuộn xuống là mất (ảnh `jd-edit__1440`, `@390`) → đặt `height` cố định cho editor + sticky action bar |
| 6 | P1 | `components/editor/WordToolbar.tsx:292` | Ở 390px toolbar cắt sau `⋯` — chỉ còn undo/redo/Font/Size, toàn bộ B/I/U/list màu sắc ẩn trong menu (ảnh `jd-edit-word__390`) → cho toolbar 2 hàng trên mobile hoặc nhóm cố định 5 nút chính |
| 7 | P2 | `WordEditor.tsx:54` / `LayoutPreview.tsx:150` / `UnifiedEditor.tsx:254` | 3 nhãn cho cùng khái niệm xem trước: `Show A4 pages`, `Show layout view (DOCX)`, `Show preview` → thống nhất 1 thuật ngữ (i18n key dùng chung) |
| 8 | P2 | `pages/JobDetail.tsx:566` | Overview: `lg:grid-cols-[minmax(0,1fr)_22rem]` — card Result cao ~270px còn cột phải dồn Text+Info+Original, chênh lệch lớn khoảng trống dưới card Result (ảnh `jd-detail__1440`) → `items-start` + cho Result dùng hết chiều cao cột trái |
| 9 | P2 | `pages/JobDetail.tsx:657-670` + `:236` | Cùng panel ảnh gốc có 2 điều khiển khác nhãn: `Original file ⌄` (Overview) và `Original` (header) → một nguồn state, một nhãn |
| 10 | P2 | `pages/JobDetail.tsx:608` (`Problems (n)`) + ảnh `jd-text__1440` | Trang Text: dòng cuối khung bị cắt sát đáy (không có padding-safe), và `Problems (1)` thu gọn không cho biết lỗi gì → thêm `pb` cho pane, badge số lỗi + tooltip/expand mặc định khi >0 |
| 11 | P3 | `components/DocStyleTools.tsx` (form dưới `Save`) | `Number headings`, `Left/Right margin`, `Table borders`, `Line spacing` là form 2 cột không nhãn nhóm, `Line spacing` tách xuống cuối trang, cách `Save` vài trăm px (ảnh `jd-edit-word__1440`) → gom thành fieldset "Trang & kiểu chữ" có heading |

### Finding của model đã **loại** (không đúng với code)

| Model nói | Thực tế |
|---|---|
| P1 "menu ▾ không đóng khi click ra ngoài mobile" | `WordToolbar.tsx:260-276` có `document.addEventListener("mousedown", close)` + Escape → **sai** |
| P1 "`Show preview` lệch state với dragbar MDEditor" | `UnifiedEditor.tsx:337` đặt `visibleDragbar={false}` → không có toggle thứ hai → **sai** |
| P2 "`originalOpen` mặc định `false` trái spec U4" | `JobDetail.tsx:109` đúng là `false`, nhưng không có spec nào trong repo xác nhận "mặc định mở" → **không kiểm chứng được, bỏ** |
| P1 "link Show layout view không đổi màu sau click" | Nút là `Button variant="secondary"`, không có trạng thái active nào được thiết kế; ảnh không chứng minh được → **không kiểm chứng được, bỏ** |

## VERDICT (theo model, sau khi lọc)

**CHANGES-REQUIRED** — 1 P0 (tên file không hiển thị trong danh sách job) + 5 P1 (measure tab Layout 595px, giấy A4 nhốt trong khung 666px, 3 nút lưu trùng nghĩa, editor md dài 2184px làm mất Save, toolbar mobile mất nút định dạng).

## Chưa làm

- Chưa chạy `npm run audit:a11y` cho các route này (gate yêu cầu khi **sửa** UI; review này không sửa).
- Chưa chụp job nhiều trang → chưa kiểm chứng hành vi phân trang A4 của `paged.js`.
- 2 request `500` từ `/api/jobs/84/preview-layout-html` xuất hiện khi chụp: `PIL.UnidentifiedImageError` trong `server/app/routers/exports.py:192` (crop ảnh gốc trên dữ liệu job e2e) — **lỗi backend, không phải finding UI**, cần issue riêng.
