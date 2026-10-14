# Spec: Lane U — JobDetail UI rework + P0 state reset (2026-10-15)

Base: master `cb70a8f`. Web-only. TDD. i18n keys mới → en+vi parity.

## U1 — P0: state trộn content giữa các job

**Bug**: `LayoutPreview` state `mdHtml/wordHtml` + UnifiedEditor không reset khi
đổi job (React Router đổi `:id` KHÔNG remount) → job1 word hiện html job2;
"Lưu layout" PUT `exports/1/docx.html` với html job2 (evidence: exports/1/docx.html
= content đề Hóa của job2, docx-layout/md-layout job1 = UNIT1 đúng).

**Fix**: `key={job.id}` tại mọi mount point trong JobDetail (`<LayoutPreview
key={job.id} …>`, UnifiedEditor mount, editor containers) + reset state trong
`useEffect` deps `[job.id]` cho component giữ cache cục bộ. TDD: test render
job A → job B → mdHtml/wordHtml của B là fetch của B (mock đếm call đúng id).

## U2 — Nút "Edit text" vào heading section Text

Nút `btn-edit-text` chuyển từ vị trí hiện tại vào header row của section
"Text/Văn bản" (bên phải heading, trái chevron). Không đổi testid.

## U3 — Section Layout = collapsible

Section Layout có heading row (text-trái + chevron-phải) click toggle
mở/đóng, `aria-expanded`. **Mặc định mở**. Nội dung: ExportBar + preview/editor
(behavior giữ nguyên). Testid toggle mới `btn-toggle-layout`.

## U4+U5 — Original + Info: text trái, chevron phải, mặc định mở

Header row `File gốc`/`Thông tin`: label trái, chevron `rotate-180` phải.
`useState(true)` cả hai (mặc định mở). Testid giữ nguyên.

## U6 — Original + Info sticky

Sidebar ≥lg: `lg:sticky lg:top-16` (dưới AppNav) — hiện trong lúc cuộn qua
Layout/Text. Không sticky <md.

## U7 — Bỏ switch MD/Word trong Layout section

Xóa `fmt-md-layout`/`fmt-docx-layout` buttons + `onFmtChange` prop wiring ở
JobDetail. `LayoutPreview` nhận `fmt` fixed từ parent (init từ
`job.output_format`) — bỏ controlled switch, giữ nội bộ (mode word/md theo
fmt). Update tests có assert 2 testid này.

## U8 — Nút Edit panel chung → xuống section Layout

Nút edit chung (hiện ở panel trên) dời vào heading row của section Layout
(bên phải heading). Thống nhất với U2 pattern (heading trái, edit, chevron phải).

## U9 — Section Text cuộn được

Vùng nội dung section Text (editor + suggestions) = scroll region:
`max-h` hợp lý + `overflow-y-auto` (pattern section Layout đang dùng). Text
dài cuộn trong section, không tràn trang.

## Ràng buộc
- Testid không đổi (R51) trừ phần xóa (U7).
- i18n: mọi string mới → t() en+vi.
- Không sửa server.
