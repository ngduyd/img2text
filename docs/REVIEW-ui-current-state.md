# Review — trạng thái UI `img2text` hiện tại (góc nhìn end user)

Ngày: 2026-11-04 · Phạm vi: `web/` (React 19 + Vite + Tailwind 4 + Tiptap + `@uiw/react-md-editor`)
· Kiểu: **review-only**, không sửa file nào trong `web/`, `server/`, `worker/`.
Baseline đánh giá: `docs/SPEC-ui-redesign.md` (D1–D11, phase P0–P5) là nguồn ý định chính thức,
bổ sung `web/DESIGN.md`, `web/nginx.conf`, `web/vite.config.ts`, `docs/superpowers/specs/*`.

Quy ước tag mỗi finding:

- **spec-backed** — có căn cứ trong `SPEC-ui-redesign.md` (`§n`, `D#`, phase P#) hoặc
  `web/DESIGN.md` (`§n`) hoặc spec con trong `docs/superpowers/specs/`.
- **observed-only** — chỉ quan sát được từ source, tài liệu không nói tới.

Mọi `file:line` dưới đây đọc trực tiếp từ source trong session này (không suy từ tài liệu).
Số liệu lấy từ `MEMORY.md` được ghi rõ nguồn và đánh dấu **chưa xác minh lại**.

---

## Observed facts

### A. Shell, nav, container

| # | Fact | Tag |
|---|---|---|
| A1 | `AppNav` render brand + Jobs + Storage + (Admin nếu role admin) + auth zone; `VI/EN`, theme, OCR đã vào menu avatar. Khớp D2. | spec-backed (D2) |
| A2 | Nav bar dùng `max-w-6xl` (1152px) trong khi `PageShell width="data"` dùng `max-w-[1200px]` → mép trái nav và mép trái nội dung lệch nhau 24px mỗi bên. `web/src/App.tsx:249` vs `web/src/components/PageShell.tsx:11`. | observed-only |
| A3 | Footer cũng dùng `max-w-6xl` → 3 mép dọc khác nhau (nav 1152, content 1200, footer 1152). `web/src/components/SiteFooter.tsx:12`. | observed-only |
| A4 | `PageShell` không set `min-h`, `SiteFooter` render ngay sau `<Routes>` không có wrapper `flex-1` → trang ngắn (Signin, Forgot, Feedback) đẩy footer lên giữa màn hình. `web/src/App.tsx:413`. | observed-only |
| A5 | D1 nói container `form` = 720px nhưng `AuthLayout` dùng `max-w-sm` (384px) và không dùng `PageShell`. `web/src/components/AuthLayout.tsx:17`. | spec-backed (D1) |

### B. `/jobs/:id` — 3 route nhưng 1 component (deviation đã ghi trong spec)

| # | Fact | Tag |
|---|---|---|
| B1 | 3 route `/jobs/:id`, `/jobs/:id/text`, `/jobs/:id/layout` đều render `JobDetail` qua prop `section`; không có `JobOverview` / `JobText` / `JobLayout`. `web/src/App.tsx:390`, `web/src/App.tsx:392`, `web/src/App.tsx:393`. | spec-backed (D3, §10 đã ghi deviation) |
| B2 | Hệ quả trực tiếp: `JobDetail.tsx` = 758 dòng, giữ state của **cả 3 màn** (editing, editingText, proofreading, downloadOpen, zen, showHistory, originalOpen, infoOpen, showOriginal, retryError…). `web/src/pages/JobDetail.tsx:71`–`web/src/pages/JobDetail.tsx:112`. | observed-only |
| B3 | Chuyển section **không remount**: `/jobs/5` → `/jobs/5/text` giữ nguyên state (vd. `editing=true` của layout) vì cùng element. Reset chỉ xảy ra khi `id` đổi. `web/src/pages/JobDetail.tsx:114`. | observed-only |
| B4 | Hai route `/jobs/:id/layout/md` và `/jobs/:id/layout/word` là **layout mode addressable**, shipped 2026-11-03, ngoài SPEC D3. `web/src/App.tsx:396`, `web/src/App.tsx:397`. | spec-backed (`docs/superpowers/specs/2026-11-03-jobdetail-layout-route-split-design.md`) |
| B5 | Sticky header giữ đúng 1 thanh (back · `#id` + filename · badge · subnav · actions · `⋯`). Đúng D11. `web/src/pages/JobDetail.tsx:215`. | spec-backed (D11) |
| B6 | Header có thể vượt 3 control khi section=layout: `btn-toggle-original-layout`, `btn-zen`, `btn-edit-doc` + `btn-version-history` + `btn-download` + `⋯` = **6**. `web/src/pages/JobDetail.tsx:301`–`web/src/pages/JobDetail.tsx:349`. | spec-backed (D4 nói tối đa 1 primary + 2 secondary) |

### C. `/jobs/:id` — Overview

| # | Fact | Tag |
|---|---|---|
| C1 | `PageShell width="data"`, grid `lg:grid-cols-[minmax(0,1fr)_22rem]`, cột phải = rail metadata. Đúng D12/§3.2. `web/src/pages/JobDetail.tsx:554`. | spec-backed (§3.2) |
| C2 | `data-testid="panel-original"` do spec §3.2 liệt là "giữ" **không tồn tại** trong DOM. `OriginalFilePanel` nhận `testid` mặc định `"panel-original"` nhưng mount với `bare` nên `Card bare` render `<div data-testid="panel-original">`… rồi bị `JobDetail` bọc thêm một `<section>` riêng; testid `panel-original` chỉ nằm trên `<div>` rỗng-vỏ bên trong. `web/src/components/panels/OriginalFilePanel.tsx:18`, `web/src/components/panels/OriginalFilePanel.tsx:62`, `web/src/components/ui/Card.tsx:17`. | spec-backed (§3.2) |
| C3 | `data-testid="panel-export"` mà §3.2 liệt "giữ" **không còn tồn tại**; export chuyển vào `DownloadDropdown` (`btn-download`, `download-formats`). `web/src/components/DownloadDropdown.tsx:65`. | spec-backed (§3.2 — spec chưa cập nhật sau Lane I Task 5/6) |
| C4 | Overview vẫn có "LinkCard" trỏ sang `/text` và `/layout` trong rail thay vì mô tả đúng trạng thái job (`Queued` → "Hủy", `Done` → "Mở văn bản", `Failed` → "Thử lại" như §3.2). `web/src/pages/JobDetail.tsx:578`–`web/src/pages/JobDetail.tsx:593`. | spec-backed (§3.2) |
| C5 | Overview **không** render editor/TextSection — khớp yêu cầu §3.2. | spec-backed (§3.2) |
| C6 | `OriginalFilePanel` không có zoom, không có page-nav cho PDF (chỉ `<iframe>` cao `75vh` + link "mở tab mới"). §3.3 yêu cầu "ẢNH GỐC (zoom, page nav)". `web/src/components/panels/OriginalFilePanel.tsx:95`. | spec-backed (§3.3) |

### D. `/jobs/:id/text` — Văn bản

| # | Fact | Tag |
|---|---|---|
| D1 | `SplitPane` (§8, D8) **không tồn tại** trong repo — không có `web/src/components/SplitPane.tsx`, không chỗ nào import. `/text` là 1 cột dọc. `web/src/pages/JobDetail.tsx:634`. | spec-backed (§8, D8) |
| D2 | Không có pane ảnh gốc trong `/text` cạnh văn bản để "click lỗi: highlight cả 2 phía" — `IssuesPanel` chỉ hiện crop nhỏ (`max-w-40`) khi `fileType === "image"`. `web/src/components/IssuesPanel.tsx:30`, `web/src/components/IssuesPanel.tsx:93`. Lý do **đã chốt là declined** trong spec route-split (Q2), nhưng §3.3 của SPEC gốc vẫn vẽ pane trái. | spec-backed (D8/§3.3) + spec-backed (`docs/superpowers/specs/2026-11-03-jobdetail-layout-route-split-design.md` §Declined) |
| D3 | §3.3 yêu cầu "Lỗi gom 1 panel phải, N lỗi = N block, thay vì 3N nút rải trong văn bản". Hiện tại có **hai** nơi sửa lỗi: popover portaled gắn vào `<mark>` + section "Đề xuất" bên dưới. `web/src/components/TextSection.tsx:408`, `web/src/components/TextSection.tsx:514`. | spec-backed (§3.3) |
| D4 | Vẫn còn toggle `btn-edit-text`. §3.3 nói "Bỏ toggle `btn-edit-text` (luôn editable)". `web/src/pages/JobDetail.tsx:264`, `web/src/components/TextSection.tsx:346`. | spec-backed (§3.3) |
| D5 | §3.3 nói "Save: 1 nút + autosave debounce" — hiện không có autosave; save chỉ xảy ra khi bấm `btn-save-text`. `web/src/components/TextSection.tsx:120`. | spec-backed (§3.3) |
| D6 | Xác nhận ghi đè layout đang dùng `window.confirm()` (modal native, không style, không i18n-able, chặn string script, không a11y-consistent với `ConfirmDialog`). `web/src/components/TextSection.tsx:251`. | observed-only |
| D7 | Save text rỗng không bị chặn: `saveFullText` POST thẳng `text` người dùng gõ, không kiểm tra rỗng; trong khi popover custom thì có validate (`editor.emptyContent`). `web/src/components/TextSection.tsx:306`. | observed-only |

### E. `/jobs/:id/layout` — Dựng layout (editor)

| # | Fact | Tag |
|---|---|---|
| E1 | §4.3 yêu cầu `LayoutPagePreview` (paged.js) **song song** với editor md. Trên thực tế md mode chỉ render `@uiw/react-md-editor` với preview của chính nó; không có trang A4. `web/src/components/UnifiedEditor.tsx:278`. | spec-backed (§4.3, D7) |
| E2 | Word mode có `PagePreview` (paged.js) chạy đúng D7 — grid 2 cột ≥lg. `web/src/components/editor/WordEditor.tsx:43`, `web/src/components/editor/WordEditor.tsx:51`. | spec-backed (D7) |
| E3 | §3.4 yêu cầu **bỏ tab MD/Word**, Markdown chuyển vào `⋯` → "Xem Markdown". Hai nút `switch-mode-md` / `switch-mode-word` vẫn render; đây là chủ ý của spec route-split (AC1–AC2: mode phải addressable), tức **SPEC §3.4 và spec route-split mâu thuẫn nhau**. `web/src/components/UnifiedEditor.tsx:211`, `web/src/components/UnifiedEditor.tsx:221`. | spec-backed (§3.4) vs spec-backed (`docs/superpowers/specs/2026-11-03-jobdetail-layout-route-split-design.md` AC1–AC2) — **cần user chốt** |
| E4 | §3.4 yêu cầu "1 nút Lưu (nội dung + style cùng lúc)… xóa `btn-save-style` khỏi UI". Thực tế word mode có **3** nút lưu: `btn-save-layout-word` (trong `WordEditor`), `btn-save-style` (trong `UnifiedEditor`), và `btn-save-layout` (md mode). `web/src/components/editor/WordEditor.tsx:54`, `web/src/components/UnifiedEditor.tsx:310`, `web/src/components/UnifiedEditor.tsx:286`. | spec-backed (§3.4) |
| E5 | 3 nút lưu trên gọi 3 endpoint khác nhau (`putDocxHtml`, `putLayoutStyle`, `patchLayoutContent`), không có nút nào cảnh báo "thay đổi chưa lưu" khi rời trang. `web/src/components/UnifiedEditor.tsx:162`, `web/src/components/UnifiedEditor.tsx:174`, `web/src/components/UnifiedEditor.tsx:184`. | observed-only |
| E6 | `btn-save-style` mang nhãn `common.saveLayout` (dịch "Lưu layout") trong khi thực chất chỉ lưu **style**, gây nhầm với `btn-save-layout`. `web/src/components/UnifiedEditor.tsx:311`. | observed-only |
| E7 | D9 yêu cầu toolbar 1 hàng + `▾`. `WordToolbar` đúng 1 hàng + `word-tb-more`, nhưng khi con trỏ trong bảng nó **render thêm hàng 2** `word-tb-table-controls` → toolbar nhảy chiều cao, đẩy nội dung. `web/src/components/editor/WordToolbar.tsx:457`. | spec-backed (D9) |
| E8 | Heading chỉ H1–H3 (§4.1 yêu cầu Heading levels 1–6). `web/src/components/editor/WordToolbar.tsx:410`, `web/src/components/editor/WordToolbar.tsx:406`. | spec-backed (§4.1) |
| E9 | Thiếu toàn bộ nhóm 2 của §4.1: Highlight, Color, Subscript, Superscript, Link, TaskList/TaskItem, Image, CharacterCount, CodeBlockLowlight, Placeholder, `pageBreak`, Find & replace, Zoom. `wordExtensions` chỉ có StarterKit/Underline/TextAlign/TextStyle/FontFamily/FontSize/Table*/Indent/LineHeight. `web/src/lib/wordEditor.ts:106`. | spec-backed (§4.1, phase P2 đánh dấu `[x]` — **sai so với code**) |
| E10 | Toolbar không có Toggle button cho bullet/ordered list hiển thị trạng thái `aria-pressed`? Có — `CMD_GROUPS[3]` toggle đúng. Không phải finding. | spec-backed (D9) |

### F. Upload → processing → export

| # | Fact | Tag |
|---|---|---|
| F1 | 1 CTA duy nhất: hàng "Gửi" chỉ hiện khi đã có file; dropzone là CTA khi rỗng. Đúng D5. `web/src/components/MultiFileUpload.tsx:209`. | spec-backed (D5) |
| F2 | Dropzone dùng `<Button testid="muf-pick">` **bên trong** một `<div onDrop>`. Cả vùng dropzone không phải `<button>`/`<label>` → bàn phím chỉ chạm được nút "Chọn file", kéo-thả không có phương án tương đương bàn phím ngoài nút đó; `aria` không mô tả vùng là dropzone. `web/src/components/MultiFileUpload.tsx:225`, `web/src/components/MultiFileUpload.tsx:231`. | observed-only |
| F3 | `input type="file"` có `accept` nhưng **không** `aria-label`/`label` — chỉ có `data-testid="muf-input"`; `hidden` nên screen reader không gặp, nhưng `audit-a11y.mjs` bỏ qua input `display:none`. Rủi ro thấp. `web/src/components/MultiFileUpload.tsx:235`. | observed-only |
| F4 | Job row: click = mở `/jobs/:id`, `⋯` = menu phụ. Đúng §5. `web/src/components/JobRow.tsx:128`, `web/src/components/JobRow.tsx:148`. | spec-backed (§5) |
| F5 | Stats `/jobs` là 3 khối `Stat` trên grid riêng, **không** inline 1 hàng như §5 vẽ (`[3 Tổng] [3 Chờ] [0 Xong]`). `web/src/pages/Jobs.tsx:140`. | spec-backed (§5, D10) |
| F6 | "Select all" nằm **dưới** toolbar upload và **trên** danh sách, không phải header checkbox của list như §5 yêu cầu. `web/src/pages/Jobs.tsx:302`. | spec-backed (§5) |
| F7 | Bulk bar dùng `max-w-3xl` trong khi list `max-w-[1200px]` → thanh bulk lệch tâm so với danh sách. `web/src/pages/Jobs.tsx:395`. | observed-only |
| F8 | `DownloadDropdown` mở link bằng `window.open("", "_blank")` **trước** khi có URL rồi gán `w.location`; khi popup bị chặn (`w === null`) thì vẫn `toast.success` "đã tạo". `web/src/components/DownloadDropdown.tsx:43`, `web/src/components/DownloadDropdown.tsx:45`. | observed-only |
| F9 | Export md/docx layout đi qua `api.exportJob` → tạo file mới mỗi lần, không có trạng thái tiến trình; người dùng không biết job đang render hay lỗi cho tới khi toast. | observed-only |
| F10 | `useJobDoneToasts` chỉ bắn toast khi status **đổi trong lúc mount**; vào trang khi job đã `done` không có toast — đúng thiết kế, không phải finding. `web/src/hooks/useJobDoneToasts.ts:52`. | spec-backed (`docs/superpowers/specs/2026-10-09-job-phases-retry-design.md`) |

### G. Admin

| # | Fact | Tag |
|---|---|---|
| G1 | Rail 3 cụm (overview / data / system), 8 tab, `md:w-52` sticky. Đúng D10. `web/src/pages/Admin.tsx:24`, `web/src/pages/Admin.tsx:76`. | spec-backed (D10) |
| G2 | 7 stat với `xl:grid-cols-7`, mỗi stat vẫn là **card có border + shadow** thay vì "1 hàng compact (số + label cùng dòng, cao 56px, gap 8)" của §6. `web/src/pages/admin/AdminOverview.tsx:77`, `web/src/pages/admin/AdminOverview.tsx:83`. | spec-backed (§6) |
| G3 | §6 yêu cầu format số GPU `0 s`, cost `$0.00`; hiện in `String(sum)` thô (giây lẻ, USD không định dạng). `web/src/pages/admin/AdminOverview.tsx:85`. | spec-backed (§6) |
| G4 | Admin là in-page state, không phải route (`/admin?tab=` không tồn tại) → không deep-link, không back/forward, không reload giữ tab. `web/src/pages/Admin.tsx:55`. SPEC không nói rõ nhưng D11/§2 tinh thần "URL là nguồn sự thật" bị vi phạm ở đây. | observed-only |
| G5 | `AdminLogs` hard-code `toLocaleString("vi-VN")` thay vì `translate("i18n.locale")` → log không đổi theo ngôn ngữ, lệch với mọi màn khác. `web/src/pages/admin/AdminLogs.tsx:153`. | observed-only |

### H. Profile / Storage / Landing / auth

| # | Fact | Tag |
|---|---|---|
| H1 | Profile vẫn **2 form mở đồng thời** (password + email), cả hai đều có input nhãn "Mật khẩu hiện tại". §7 yêu cầu tab/accordion, chỉ 1 form mở. `web/src/pages/Profile.tsx:141`, `web/src/pages/Profile.tsx:185`, `web/src/pages/Profile.tsx:188`. | spec-backed (§7) |
| H2 | Info card Profile dùng `flex items-center gap-2` — label không có cột trái cố định 96px như §7. `web/src/pages/Profile.tsx:110`. | spec-backed (§7) |
| H3 | Storage: 3 stat trên `sm:grid-cols-3` (grid riêng, không 1 hàng compact §7); nút "Delete N file(s)" nằm **trái** toolbar, không phải phải. `web/src/pages/Storage.tsx:109`, `web/src/pages/Storage.tsx:139`. | spec-backed (§7) |
| H4 | Landing hero `md:grid-cols-[3fr_2fr]` (60/40) — §7 yêu cầu "cân lại 60/40 có visual", đã đạt; roadmap section + ảnh thật đã thay khung rỗng. `web/src/pages/Landing.tsx:83`. | spec-backed (§7) |
| H5 | Signin tự dựng label + input + nút "Hiện" thay vì dùng `components/ui/Input` như mọi form khác → pattern/chiều cao/focus ring khác `Input`. `web/src/pages/Signin.tsx:60`, `web/src/pages/Signin.tsx:75`. | observed-only |
| H6 | Signin dùng id cố định `input-password` (không theo `testid` như `Input`), nên khó tái sử dụng; nhưng chỉ 1 form/trang nên chưa gây trùng id. `web/src/pages/Signin.tsx:69`. | observed-only |
| H7 | `AuthLayout` không dùng `PageShell` + `max-w-sm` (xem A5). | spec-backed (D1) |

### I. Hạ tầng / contract API

| # | Fact | Tag |
|---|---|---|
| I1 | Không có UI call nào bypass `/api`. `fetch` duy nhất trong `api/client.ts` dùng path tương đối; dev proxy `/api` → `http://localhost:8010` (`web/vite.config.ts:13`), prod nginx `try_files` + edge nginx lo `/api/` (`web/nginx.conf:7`). | spec-backed (constraint API base) |
| I2 | `web/nginx.conf` chỉ có SPA fallback, **không** có `location /api/`; `/api` ở prod do `deploy/nginx.conf` (edge) xử lý. Comment trong `web/nginx.conf:1` nói rõ. Không phải finding. | spec-backed |

### J. a11y / target size (theo công cụ sẵn có)

| # | Fact | Tag |
|---|---|---|
| J1 | `audit-a11y.mjs` phủ 8 route × {1440, 320} và kiểm contrast / target <24px / alt / control không tên / >1 h1 / overflow-x. `web/scripts/audit-a11y.mjs:11`, `web/scripts/audit-a11y.mjs:12`. | spec-backed (`web/AGENTS.md` §1) |
| J2 | `audit-a11y.mjs` **luôn exit 0** kể cả khi có finding → gate phải đọc dòng `DONE N routes with findings`. Xác nhận 2026-11-04: script in finding rồi vẫn exit 0. | observed-only |
| J3 | Chạy lại 2026-11-04 **sau khi sửa checker**: **`DONE 2 routes with findings`** — cả 2 là `/jobs/5/text` @1440 và @320, cùng một lỗi: nút `<mark>` gợi ý sửa OCR cao **23,8px** < 24px (`small targets: 88x24 BUTTON "precifications" | …`). Không phải lỗi label như run trước. `web/src/components/TextSection.tsx:393`. | observed-only |
| J4 | 4 dòng "unlabeled" của run trước là **false positive của script**, không phải lỗi a11y thật: accessible name kiểm bằng `locator.ariaSnapshot()` trong Chromium trả `searchbox "Search by filename"` và `textbox "Current password"`. Nguyên nhân: checker lấy tên bằng `aria-label \|\| textContent`, `<input>` có `textContent` rỗng → input gắn `<label>` vẫn bị báo "unlabeled". Đã sửa 2026-11-04: dùng `el.labels`. `web/scripts/audit-a11y.mjs:95`, `web/src/pages/Jobs.tsx:150`, `web/src/components/ui/Input.tsx:18`. | observed-only |
| J4b | ~~Nút `<mark>` gợi ý sửa OCR cao 23,8px~~ **đã sửa 2026-11-04**: thêm `py-0.5` → đo lại trong Chromium **27,80px**, audit về `DONE 0 routes`. Vẫn dưới 44px của `web/DESIGN.md` §7 nhưng đạt 24px của WCAG 2.5.8 vì là control inline trong câu văn. `web/src/components/TextSection.tsx:393`. | observed-only |
| J5 | Nhiều nút `size="sm"` cao ~28px (`py-1` + text-sm) < 44px mà `web/DESIGN.md` §7 yêu cầu cho "primary interactive elements"; chỉ Storage/admin icon-button có `min-h-11`. `web/src/components/ui/Button.tsx:18`. | spec-backed (`web/DESIGN.md` §7) |
| J6 | `role="alertdialog"` + `aria-modal` ở `ConfirmDialog` (đúng), nhưng `useDialogA11y` **không trap focus** — Tab đi được ra sau dialog. `web/src/components/ui/useDialogA11y.ts:26`. | observed-only |

---

## Missing / incomplete functional requirements

Sắp theo mức chặn luồng người dùng.

| # | Requirement thiếu / dở | Trạng thái spec | Tag |
|---|---|---|---|
| M1 | **`SplitPane` 3 trạng thái (Ảnh / Chia đôi / Văn bản) + drag divider + `localStorage: split-mode`** chưa được implement. `/text` hiện là 1 cột; người dùng không thể vừa nhìn ảnh gốc vừa sửa text. | D8, §3.3, §8 — chưa ship | spec-backed (D8) |
| M2 | **Panel lỗi gom 1 chỗ** (§3.3) chưa đạt: lỗi nằm ở 2 nơi (popover trên mark + section "Đề xuất"), text vẫn chứa N mark phải bấm từng cái. | §3.3 — chưa ship | spec-backed (§3.3) |
| M3 | **Preview A4 cho md mode** (`LayoutPagePreview`) không có; chỉ word mode có. Người dùng chọn output md không bao giờ thấy bản dựng trang. | §4.3, D7 — chưa ship cho md | spec-backed (§4.3) |
| M4 | **1 nút Lưu duy nhất** cho layout: hiện 3 nút, 3 endpoint, không có "dirty state", không cảnh báo khi rời trang. Rời trang = mất chỉnh sửa im lặng. | §3.4 — chưa ship | spec-backed (§3.4) |
| M5 | **Editor tier B** gần như không có: thiếu Highlight/Color/Sub/Sup/Link/TaskList/Image/CharacterCount/CodeBlock/Placeholder/pageBreak/Find&Replace/Zoom, heading chỉ H1–H3. | §4.1, phase P2 đánh dấu `[x]` nhưng code không khớp | spec-backed (§4.1) |
| M6 | **Overview theo trạng thái job**: không có primary duy nhất đổi theo `Queued` / `Done` / `Failed`; thay vào đó là 2 LinkCard luôn giống nhau. | §3.2 — chưa ship | spec-backed (§3.2) |
| M7 | **`JobOverview` / `JobText` / `JobLayout`** là component riêng — chưa tách, gây state rò giữa 3 màn. | D3, §3.1, §10 — deviation đã ghi | spec-backed (D3) |
| M8 | **Autosave text** (§3.3 "1 nút + autosave debounce") — không có. | §3.3 — chưa ship | spec-backed (§3.3) |
| M9 | **Profile gộp tab/accordion** — chưa; 2 form song song. | §7 — chưa ship | spec-backed (§7) |
| M10 | **Jobs list compact**: stats 1 hàng inline, select-all thành header checkbox của list. | §5 — chưa ship | spec-backed (§5) |
| M11 | **Admin stat 1 hàng compact + format số (`0 s`, `$0.00`)** — chưa; vẫn 7 card có viền, số thô. | §6 — chưa ship | spec-backed (§6) |
| M12 | **Zoom + page nav cho ảnh gốc/PDF** ("Ảnh gốc (zoom, page nav)") — chỉ có iframe tĩnh. | §3.3 — chưa ship | spec-backed (§3.3) |
| M13 | **Warning rời trang khi có thay đổi chưa lưu** ở editor — không tồn tại (beforeunload / route guard). Không có trong SPEC, nhưng là hệ quả trực tiếp của M4. | không có trong SPEC | observed-only |
| M14 | **Admin tab addressable qua URL** — không có; F5/reload mất tab. | không có trong SPEC | observed-only |

---

## Prioritized remediation

Mỗi mục: file đích cụ thể, chỉ dùng dependency đã có trong `web/package.json`.

### P0 — chặn mất dữ liệu / sai nghiệp vụ

1. **Gộp 3 nút lưu layout thành 1 primary + dirty-state** (M4, E4, E5, E6).
   - `web/src/components/UnifiedEditor.tsx` — một handler `saveAll()` gọi `putDocxHtml` + `putLayoutStyle` + `patchLayoutContent` theo mode; 1 nút `btn-save-layout` (giữ testid), ẩn `btn-save-style` khỏi UI (giữ i18n key, đúng §3.4).
   - `web/src/components/editor/WordEditor.tsx` — bỏ `btn-save-layout-word` khỏi UI, đẩy `onSave` lên `UnifiedEditor`.
   - `web/src/pages/JobDetail.tsx` — `beforeunload` + confirm khi `dirty` và người dùng bấm back/subnav.
2. **Cảnh báo rời trang khi có thay đổi chưa lưu** (M13): cùng file trên; dùng `window.beforeunload` (native, không cần lib) + `useBlocker` của `react-router-dom` (đã có).
3. **Thay `window.confirm()` bằng `ConfirmDialog`** trong luồng sync text (D6): `web/src/components/TextSection.tsx:251` → reuse `web/src/components/ConfirmDialog.tsx`.
4. **Chặn lưu text rỗng** (D7): `web/src/components/TextSection.tsx:306` — reuse `editor.emptyContent` + `role="alert"` sẵn có.

### P1 — hoàn tất deviation P1 / hợp nhất JobDetail

5. **Tách `JobOverview` / `JobText` / `JobLayout`** (M7, B1, B3): tạo `web/src/pages/job/JobOverview.tsx`, `web/src/pages/job/JobText.tsx`, `web/src/pages/job/JobLayout.tsx`; `web/src/pages/JobDetail.tsx` giữ phần dùng chung (query job, header, `⋯` menu, version history) và render theo `section`. `web/src/App.tsx:392` trỏ vào component mới.
6. **Overview primary theo trạng thái** (M6, C4): `web/src/pages/job/JobOverview.tsx` — 1 primary đổi theo `job.status`, dùng `Button` sẵn có; giữ `link-open-text` / `link-open-layout` làm secondary.
7. **Khôi phục testid `panel-original` / `panel-export`** (C2, C3): `web/src/pages/job/JobOverview.tsx` bọc `OriginalFilePanel` bằng `<section data-testid="panel-original">`; thêm `data-testid="panel-export"` quanh `DownloadDropdown` trong `web/src/components/DownloadDropdown.tsx:63`.

### P2 — phần thiếu rõ ràng nhất của trải nghiệm

8. **`SplitPane`** (M1): tạo `web/src/components/SplitPane.tsx` đúng props §8, dùng `role="separator"` + `aria-orientation="vertical"` + `aria-valuenow`, ←/→ ±1%, dblclick reset 55/45, `localStorage: split-mode`; mount trong `web/src/pages/job/JobText.tsx` (hoặc `web/src/pages/JobDetail.tsx:634` nếu chưa tách).
9. **Preview A4 cho md mode** (M3): `web/src/components/UnifiedEditor.tsx:278` — tái dùng `web/src/components/editor/PagePreview.tsx` cho nhánh md (`marked` + `DOMPurify` đã có, hoặc `markdown-it` đã dùng ở `web/src/components/LayoutPreview.tsx:3`), debounce 500ms như `PagePreview` đang làm.
10. **Zoom + page nav cho file gốc** (M12): `web/src/components/panels/OriginalFilePanel.tsx:87` — zoom bằng `transform: scale()` trên `<img>`; PDF đã có `pdfjs-dist` (`web/src/lib/pdfjs.ts`) để render trang + nút trang trước/sau thay vì `<iframe>`.
11. **Panel lỗi gom 1 chỗ** (M2): `web/src/components/TextSection.tsx:514` — mở rộng section "Đề xuất" thành panel phải theo §3.3, giữ testid `btn-apply-{sid}` / `btn-reject-{sid}` / `btn-save-custom-{sid}`; bỏ popover portaled (`web/src/components/TextSection.tsx:411`).

### P3 — mật độ / nhất quán

12. **Nav + footer cùng container với content** (A2, A3): `web/src/App.tsx:249` và `web/src/components/SiteFooter.tsx:12` đổi `max-w-6xl` → `max-w-[1200px]`.
13. **Footer luôn ở đáy** (A4): `web/src/App.tsx:367` thêm `flex min-h-dvh flex-col` + `flex-1` quanh `<Routes>`.
14. **D4 ở header job** (B6): `web/src/pages/JobDetail.tsx:301`–`web/src/pages/JobDetail.tsx:321` — dồn `btn-zen` và `btn-toggle-original-layout` vào `⋯` (`job-more-panel`), giữ tối đa `btn-edit-doc` + `btn-download` ngoài thanh.
15. **Jobs list compact** (F5, F6): `web/src/pages/Jobs.tsx:140` — chuyển 3 `Stat` thành 1 hàng inline; `web/src/pages/Jobs.tsx:302` — đưa select-all thành header checkbox của `<ul>` danh sách.
16. **Bulk bar canh đúng list** (F7): `web/src/pages/Jobs.tsx:395` — `max-w-3xl` → `max-w-[1200px]`.
17. **Profile gộp tab** (H1, H2): `web/src/pages/Profile.tsx:141`–`web/src/pages/Profile.tsx:185` — accordion/tab (state `useState`, không cần lib); info card label `w-24`.
18. **Storage stat 1 hàng + nút phải** (H3): `web/src/pages/Storage.tsx:109`, `web/src/pages/Storage.tsx:139`.
19. **Admin stat 1 hàng + format số** (G2, G3): `web/src/pages/admin/AdminOverview.tsx:77` — bỏ `rounded-card border shadow-card` khi đã ở 1 hàng; `web/src/pages/admin/AdminOverview.tsx:85` — format `gpu` → `X s`, `cost` → `$Y.YY`.
20. **`AdminLogs` dùng locale chung** (G5): `web/src/pages/admin/AdminLogs.tsx:153` — `translate("i18n.locale")`.
21. **Signin dùng `Input` chung** (H5): `web/src/pages/Signin.tsx:60` — thay block tự dựng bằng `web/src/components/ui/Input.tsx` + một `error` prop cho `role="alert"`.
22. **Admin tab trong URL** (M14): `web/src/pages/Admin.tsx:55` — `useSearchParams` của `react-router-dom` thay `useState`.

### P4 — editor năng lực (lớn, cần user duyệt phạm vi)

23. **Heading H1–H6** (E8): `web/src/components/editor/WordToolbar.tsx:410` thêm `<option value="4..6">`; `StarterKit` đã hỗ trợ.
24. **Nhóm extension tier B** (E9): `web/src/lib/wordEditor.ts:106`. Chỉ làm được phần dùng dependency hiện có: `Color` qua `TextStyle` (đã cài), `pageBreak` custom node, zoom CSS, `CharacterCount` tự viết bằng handler `onUpdate`. Phần Highlight / Link / TaskList / Image / CodeBlockLowlight / Placeholder / Find&Replace **không thể làm trọn §4.1** vì thiếu package tương ứng — ghi nhận là finding, không đề xuất cài thêm.
25. **Toolbar không nhảy chiều cao khi ở trong bảng** (E7): `web/src/components/editor/WordToolbar.tsx:457` — đưa `word-tb-table-controls` vào panel `word-tb-more` thay vì hàng 2.
26. **Focus trap cho dialog** (J6): `web/src/components/ui/useDialogA11y.ts:26` — thêm vòng Tab trong `panelRef` (native DOM, không cần lib).
27. ~~Nút gợi ý sửa OCR cao 23,8px~~ (J4b) **đã làm 2026-11-04**: `web/src/components/TextSection.tsx:393` thêm `py-0.5` → 27,80px. Không còn trong danh sách remediation.

---

## unspecified — observed only

Các điểm **không** được `SPEC-ui-redesign.md`, `web/DESIGN.md` hay `docs/superpowers/specs/*` nói tới.
Không suy đoán ý định; chỉ ghi nhận.

1. **Nav `max-w-6xl` lệch `PageShell` 1200px và footer lệch cả hai** — 3 mép dọc khác nhau trên cùng một trang. `web/src/App.tsx:249`, `web/src/components/SiteFooter.tsx:12`, `web/src/components/PageShell.tsx:11`. Không tài liệu nào chốt bề rộng nav/footer.
2. **Trang ngắn đẩy footer lên giữa màn hình** (không có sticky-footer layout). `web/src/App.tsx:413`.
3. **`AuthLayout` không dùng `PageShell`** — tồn tại song song 2 hệ container. `web/src/components/AuthLayout.tsx:17`.
4. **`OriginalFilePanel` không có zoom/page-nav** — §3.3 vẽ "Ảnh gốc (zoom, page nav)" nhưng không nói component nào sở hữu, và spec route-split đã *declined* panel ảnh ở `/text`. Hiện chỉ `<iframe>` tĩnh. `web/src/components/panels/OriginalFilePanel.tsx:95`.
5. **`DownloadDropdown` báo thành công dù popup bị chặn** — không tài liệu nào mô tả hành vi khi `window.open` trả `null`. `web/src/components/DownloadDropdown.tsx:43`.
6. **3 endpoint lưu layout khác nhau, không có nút lưu hợp nhất** — SPEC §3.4 nói 1 nút nhưng không nói gộp ở client hay server. Hiện tách rời. `web/src/components/UnifiedEditor.tsx:162`, `web/src/components/UnifiedEditor.tsx:174`, `web/src/components/UnifiedEditor.tsx:184`.
7. **Nhãn `common.saveLayout` trên nút lưu style** — SPEC §3.4 yêu cầu xóa nút nhưng không nói nhãn nếu giữ. `web/src/components/UnifiedEditor.tsx:311`.
8. **Admin là in-page state, không route** — không tài liệu nào nói tab Admin phải addressable qua URL. `web/src/pages/Admin.tsx:55`.
9. **`AdminLogs` hard-code `"vi-VN"`** — SPEC và DESIGN đều nói một locale chung nhưng không có rule chặn hard-code locale. `web/src/pages/admin/AdminLogs.tsx:153`.
10. **`audit-a11y.mjs` luôn exit 0** — nguồn `MEMORY.md` 2026-11-03, **chưa xác minh lại**. Script không kiểm focus-visible bằng bàn phím, không kiểm aria-state sau tương tác, không kiểm click flow nhiều bước (đã ghi ở `web/AGENTS.md` §Playwright MCP).
11. **Finding a11y `/jobs` `jobs-search` + `/profile` `input-current-password` thiếu label** — run 2026-11-04 in 4 dòng (`DONE 4 routes with findings`) nhưng `ariaSnapshot()` cho thấy cả hai **có** accessible name → lỗi của checker, **đã sửa** (`web/scripts/audit-a11y.mjs:95` dùng `el.labels`). Sửa xong lộ ra J4b (nút inline 23,8px), **cũng đã sửa**. Gate hiện tại: `DONE 0 routes with findings`.
12. **Nút `size="sm"` cao ~28px dưới ngưỡng 44px của `web/DESIGN.md` §7** — DESIGN nói "primary interactive elements", không định nghĩa "primary"; `audit-a11y.mjs` chỉ gate 24px nên lọt. `web/src/components/ui/Button.tsx:18`.
13. **`useDialogA11y` không trap focus** — `CropDialog`, `PageSelectDialog`, `SubmitModal`, `ConfirmDialog` dùng chung hook này; không tài liệu nào yêu cầu focus trap tường minh. `web/src/components/ui/useDialogA11y.ts:26`.
14. **State rò giữa 3 section của `JobDetail`** — route đổi không remount nên `editing`/`editingText` sống qua điều hướng. Đây là hệ quả của deviation P1, nhưng *hành vi mong muốn* (giữ hay reset) không được spec nào định nghĩa. `web/src/pages/JobDetail.tsx:114`.
15. **`text-editor` (Tiptap) không có auto-save, chỉ có nút `btn-save-text`** — §3.3 nói "1 nút + autosave debounce" nhưng không nói debounce ở đâu hay hành vi khi đóng tab.
16. **Word mode không có dirty indicator khi `DocStyleTools` đổi style** — style chỉ được ghi khi bấm `btn-save-style`; không tài liệu nào mô tả.
