# Plan: Lane U — JobDetail UI rework (2026-10-15)

Spec: `docs/superpowers/specs/2026-10-15-lane-u-jobdetail-ui-design.md`.
Base `cb70a8f`. Worktree `lane-u-ui`. Web: `npx tsc -b --force` + targeted vitest. Commit mỗi task. TDD red→green.

## Task 1 — P0 U1: state reset theo job.id
- Test đỏ: `JobDetail state test` — render job A (mock md fetch id=1), navigate → job B (id=2), assert `api.exportJob` được gọi với id=2 + mdHtml re-render của B (không còn html A). Pattern: mock client, `key`/deps.
- Fix: `<LayoutPreview key={job.id}>` + `<UnifiedEditor key={job.id}>` (JobDetail ~497); LayoutPreview `useEffect(..., [mode])` → thêm `job.id` reset `mdHtml/wordHtml/loading`. UnifiedEditor check cache load deps similar.
- Green: test pass, toàn bộ existing JobDetail/LayoutPreview tests pass.

## Task 2 — U9: section Text cuộn
- Test đỏ: TextSection wrapper có class scroll (`overflow-y-auto` + max-h) — assert className.
- Fix: bọc vùng nội dung text section (editor + suggestions) scroll container.

## Task 3 — U2 + U8: Edit buttons vào headings
- Test đỏ: `btn-edit-text` nằm trong section Text header (container assert); nút Edit panel → section Layout header.
- Fix: move buttons, layout row: heading trái → edit button → chevron phải.

## Task 4 — U3: Layout collapsible
- Test đỏ: `btn-toggle-layout` toggle `aria-expanded`, content ẩn khi đóng, mặc định mở.
- Fix: heading row + `useState(true)` + chevron rotate.

## Task 5 — U4+U5: Original/Info text-trái-chevron-phải + default open
- Test đỏ: initial render OriginalFilePanel + InfoPanel present (default open); chevron vị trí phải (flex justify-between).
- Fix: `useState(true)` ×2, header row `justify-between`.

## Task 6 — U6: sticky sidebar
- Test đỏ: sidebar wrapper className có `lg:sticky lg:top-16`.
- Fix: apply (≥lg only).

## Task 7 — U7: bỏ switch MD/Word
- Test đỏ: existing tests assert `fmt-md-layout`/`fmt-docx-layout` → xóa assertion (green sau xóa UI).
- Fix: gỡ 2 buttons + wiring `onFmtChange`; `fmt` init `job.output_format` fixed ở parent. Check `switchLayoutFmt` + `layoutFmtOverride` còn cần cho preview không — giữ internal mode nếu unified editor cần; chỉ XÓA button switch.

## Task 8 — sweep
- i18n parity, grep testid mới/cũ, tsc + vitest full + vite build.

## Rollout
Đơn giản — 1 worker, commit/task. Report: git log + red-green.
