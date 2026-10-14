# Spec: Lane U — JobDetail UI rework + P0 state reset (2026-10-15) — rev2

Base: master `cb70a8f`. Web-only. TDD. i18n keys mới → en+vi parity.
Rev2: fix theo spec-review (2 P0 + 4 P1).

## U1 — P0: state trộn content giữa các job

**Bug**: React Router đổi `:id` KHÔNG remount → state cache giữ html job cũ;
"Lưu layout" PUT `exports/1/docx.html` với html job2 (evidence có sẵn).

**Fix — 2 lớp**:
1. `key={job.id}` tại mount-level đủ cao (grid/section wrap trong JobDetail,
   mounts ~469-500; `key` dùng `id` từ params — undefined-safe với early-return
   `!job`).
2. Null-reset effect trong `LayoutPreview`: deps `[mode, job.id]` →
   `setMdHtml(null); setWordHtml(null)` TRƯỚC khi `load()` (thêm job.id vào
   deps KHÔNG đủ vì `load()` early-return khi state !== null).

**Full reset table** (component giữ state theo job):
| Component | States reset khi job.id đổi |
|---|---|
| LayoutPreview | mdHtml, wordHtml, loading |
| JobDetail | editing, downloadOpen, layoutFmtOverride, showHistory, originalOpen, infoOpen, anchorEls |
| TextSection | editingText, open, customText |
| UnifiedEditor | mode, mdText, docxHtml, loaded, error, baseCss, wordCss, styleMap |

Áp dụng: `key={job.id}` cover 90% (unmount/remount). State nào nằm TRONG
component được key → khỏi xử lý riêng. State nằm ở JobDetail (không remount)
→ reset effect deps `[id]`. Test đỏ→xanh: navigate A→B, mock đếm call id=2,
không còn html A.

## U2 — Nút "Edit text" vào heading section Text

- Lift `editingText` state lên JobDetail (prop `editingText` +
  `onEditingTextChange` vào TextSection) — button render ở JobDetail header row.
- Thứ tự header row Text: **heading trái → edit button phải**.
- **Text section KHÔNG collapsible** (chỉ scroll — U9). Không chevron ở Text.

## U3 — Section Layout = collapsible

- Header row: **heading trái → nút Edit (U8) → chevron phải**.
- `useState(true)` mặc định mở, chevron `rotate-180`, `aria-expanded` +
  `aria-controls="layout-panel-wrap"`, testid `btn-toggle-layout`.
- Scroll region của Layout GIỮ NGUYÊN (đã đúng).
- Đầu row đây cũng là chỗ đặt nút Edit (U8) — gộp Task.

## U4+U5 — Original + Info: text trái, chevron phải, mặc định mở

- `justify-between`: label trái, chevron phải. `useState(true)` ×2.
- Testid giữ; header row có `aria-expanded` (đã có pattern).

## U6 — Original + Info sticky (offset 2 layer)

- Sidebar wrap `lg:sticky lg:top-32` (AppNav h-16 4rem + job-header sticky
  ~4rem — TRÁNH chồng overlap khi cả 2 sticky cùng top-16).
- <lg không sticky. Chấp nhận: job-header wrap cao hơn → top-32 vẫn an toàn.

## U7 — XÓA toàn bộ switch MD/Word (2 chỗ, option a)

- **Xóa**: header switch `fmt-md-layout`/`fmt-docx-layout` (JobDetail ~282-292)
  + preview toggle `preview-mode-md`/`preview-mode-word` (LayoutPreview ~111-126).
- `LayoutPreview({job, fmt})` — `fmt` fixed từ parent init
  `job.output_format` (`md-layout`↔`docx-layout`); bỏ `onFmtChange`,
  `layoutFmtOverride`/`switchLayoutFmt` (JobDetail ~59-61, 121), `key={layoutFmt}`
  crossfade.
- **GIỮ**: UnifiedEditor `switch-mode-md/word` (editor mode switch độc lập
  trong editor — không phải layout fmt switch).
- Dead cleanup: i18n `jd.layoutFmtChanged`/`jd.layoutFmtAria`,
  `layout-crossfade` CSS, tests assert `fmt-*`.

## U8 — Nút Edit panel chung → heading section Layout

- Nút Edit (panel trên, `btn-edit-doc`-style hiện tại) dời vào header row
  Layout: **heading → edit → chevron** (U3).
- State wiring giữ nguyên (chỉ đổi vị trí render).

## U9 — Section Text cuộn được

- Scroll region = **vùng text editor** (`max-h-[75vh] overflow-y-auto`,
  match Layout preview pattern).
- **IssuesPanel/suggestion popover**: KHÔNG nằm trong scroll region
  (popover `absolute top-full` sẽ bị clip) — tách sibling ngoài region hoặc
  portal. Chọn: IssuesPanel ngoài scroll region, text editor cuộn riêng.
- Test: text dài → region có overflow, page không tràn; popover render
  không bị clip (assert ngoài container có overflow).

## Ràng buộc
- Testid: giữ nguyên các id cũ; testid MỚI cho phép thêm (`btn-toggle-layout`).
- i18n: mọi string mới → t() en+vi; `jd.layout` heading hardcoded → key mới.
- Default-open Original/Info → mount eager (double-fetch chấp nhận, perf note).
- Không sửa server.
