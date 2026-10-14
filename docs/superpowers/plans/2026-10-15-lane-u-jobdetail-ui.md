# Plan: Lane U — JobDetail UI rework (2026-10-15) — rev3

Spec: `docs/superpowers/specs/2026-10-15-lane-u-jobdetail-ui-design.md` (rev2).
Base `cb70a8f`. Worktree `lane-u-ui`. Web: `npx tsc -b --force` + targeted vitest. Commit mỗi task. TDD.
Rev3: fix plan-review (P0 popover, P1 state list/order, P2 wiring).

## Task 1 — U7: xóa TOÀN BỘ switch MD/Word (2 chỗ) — TRƯỚC Task2
- Test đỏ: `fmt-md-layout`/`fmt-docx-layout`/`preview-mode-md`/`preview-mode-word` = 0 trong DOM sau khi gỡ (JobDetail + LayoutPreview render, tsc pass với prop types gỡ).
- Fix: xóa header switch (JobDetail ~282-292) + preview toggle (LayoutPreview ~111-126) + `onFmtChange` + `layoutFmtOverride`/`switchLayoutFmt` (JobDetail ~59,121,287,297) + `key={layoutFmt}` crossfade (~497-498). `fmt` fixed init `job.output_format`.
- GIỮ: UnifiedEditor `switch-mode-md/word`.
- Dead cleanup: i18n `jd.layoutFmtAria`/`jd.layoutFmtChanged` (en/vi.json:164-165), `layout-crossfade` (index.css:106), toast `switchLayoutFmt`.
- Note: KHÔNG có test assert fmt-* sẵn (empty set) → test mới assert vắng.

## Task 2 — U1 P0: state reset theo job.id — SAU Task1
- Test đỏ: navigate A→B → fetch gọi id=2, mdHtml là của B (không html A).
- Fix: `key={job.id}` grid/section wrap (JobDetail ~469-500) + LayoutPreview null-reset effect (`setMdHtml(null);setWordHtml(null)` deps `[mode, job.id]` — thêm deps KHÔNG đủ vì `load()` early-return).
- JobDetail states (reset effect `[id]`, local states KHÔNG remount): `confirmDelete, editing, downloadOpen, retryingLayout, confirmRetry, showHistory, originalOpen, infoOpen, retryError` (— `layoutFmtOverride` đã xóa Task1; `anchorEls` nằm TextSection useRef Map, ref không cần reset).

## Task 3 — U2+U8: Edit buttons vào headings — TRƯỚC Task4 (cùng region TextSection)
- Test đỏ: `btn-edit-text` trong Text header row (heading → edit, Text KHÔNG chevron/collapsible); Edit panel → Layout header row (heading → edit → chevron).
- Fix: lift `editingText` lên JobDetail → TextSection props `{editingText, onEditingTextChange}`; **`saveFullText` nội bộ gọi `setEditingText(false)` → đổi gọi prop callback**. Nút `btn-edit-doc` move: GIỮ behavior (`disabled={job.status!=="done"}`, `aria-pressed`, scroll → `panel-editor`).

## Task 4 — U9: section Text cuộn + suggestion popover không clip
- Test đỏ: text inner container có `max-h-[75vh] overflow-y-auto`; **suggestion popover** (`suggestion-popover-*`, `absolute top-full` trong `article[data-testid=extraction-text]`) render NGOÀI overflow ancestor (portal hoặc container khác — assert không có overflow ancestor clip); IssuesPanel giữ sibling (đã OK).
- Fix: scroll wrap chỉ bọc inner text content; popover → portal ra ngoài (createPortal → document.body) hoặc tách row.

## Task 5 — U3: Layout collapsible
- Test đỏ: `btn-toggle-layout` toggle `aria-expanded` + `aria-controls="layout-panel-wrap"`, default mở, chevron rotate. GIỮ scroll region Layout hiện tại.
- Fix: header row `heading | edit (Task3) | chevron` + `useState(true)`.

## Task 6 — U4+U5: Original/Info justify-between + default open
- Test đỏ: default render cả panel, label trái / chevron phải.
- Fix: `useState(true)` ×2 + `justify-between`.

## Task 7 — U6: sticky `lg:top-32`
- Test đỏ: sidebar className `lg:sticky lg:top-32` (AppNav 4rem + job-header 4rem, tránh chồng job-header sticky top-16).
- Fix.

## Task 8 — sweep
- i18n parity + key `jd.layout` (thay hardcoded `<h2>Layout</h2>`), grep dead keys/testids, tsc + vitest full + vite build.
