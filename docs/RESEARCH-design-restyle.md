# RESEARCH trinh sát — web/ (master 59fda16, restart design-restyle)

Nguồn: lane researcher (read-only). Facts + file:line. Context cho implementer; SPEC là authority.

## 1. Shell chung (App.tsx:354-393)
`div.min-h-dvh` → skip-link `a[href=#main].skip-link` (:355) → AppNav (:358) → Toaster (:361) → Routes (:366-388) → SiteFooter (:390) → VerifyGate (:392).

## 2. Route map
| Route | Root | h1 | Ghi chú |
|---|---|---|---|
| /signin, /signup | AuthLayout `<main id=main>` flex min-h-dvh + `max-w-sm` | AuthLayout:29 `text-xl` | subtitle có (`auth.signin/signup.subtitle`) |
| /forgot | Forgot:30 `<main id=main max-w-sm p-6>` | :31 `text-xl` (không text-text) | KHÔNG subtitle key trong dict |
| /reset | Reset:46 `<main max-w-sm p-6>` | :47 `text-xl` | KHÔNG subtitle key |
| /profile | Profile:36/89 (`max-w-md p-4 sm:p-6`, 2 nhánh) | :91 `text-2xl` | loading text bare (:37 `profile-loading`); joined row thiếu date |
| /feedback | Feedback:36 (`max-w-md`) | KHÔNG h1 (Card title→h2, Card.tsx:18) | |
| / (Landing) | Landing:147 `div[data-testid=landing] max-w-6xl px-4 pb-0` | :158 clamp() | KHÔNG `id=main` → skip-link chết trên trang chủ |
| /jobs | Jobs:143 (`max-w-3xl`) | :147 `text-2xl` | header asymmetric + `dl` stats; QuotaBadge :149 (trùng nav App:266); bulk-bar fixed :457 |
| /jobs/:id | JobDetail:136 (loading `max-w-3xl`) / :181 (`max-w-[1400px]`) | :196 `text-xl sm:text-2xl` | header sticky bordered; actions conditional |
| /jobs/:id/extraction | Extraction:48 (`max-w-4xl`) | :61 `text-xl sm:text-2xl` | header :49-52 back-link + h1 |
| /admin | Admin:52 (`max-w-5xl p-4`) | :53 `text-xl` trần, KHÔNG `<header>` | rail Admin:54-57; loading text (:85); 8 tabs (:19-31) nhưng Admin.test:70 assert 7 tabs |
| /features | Features:20 (`max-w-5xl px-4 py-12 md:py-16`, testid=features-page) | :24 `text-3xl md:text-4xl` | 3 equal cards md:grid-cols-3 (:33) |
| /storage | Storage:70 (`max-w-7xl px-4 py-6`) | :73 `text-2xl` | header plain; pagination glyphs ‹ › (:275/285) |

## 3. ui/ inventory (Button/VariantSize/data-attrs, Badge/tone, Card/title→h2, Input/label-required+error-role, Skeleton/.skeleton+aria-hidden, useDialogA11y stack)
Props tiêu biểu: Button `variant? size? loading? testid?`; Card `title? testid? actions?`; Input `label` required, `error? helper?`, `id = id ?? testid`; Skeleton `testid? className?`.

## 4. Tokens (tokens.css 46 dòng; index.css @theme inline :15-34)
Dark=default. `--accent-text` dark `#58a6ff` (:12) / light `#0861cf` (:40). `rounded-card ≡ rounded-md = 8px`. body font = system-ui stack (:35). focus-visible 2px accent ring (:49-52). `.skip-link` left:-9999px (:55-70). `.skeleton` 1.4s shimmer (:76-93). reduced-motion kill-all (:95-102). KHÔNG có `dark:` utility nào trong src; responsive 100% qua sm:/md:/lg:.
LƯU Ý: DESIGN.md khai mono stack nhưng code KHÔNG có `--font-mono` (font-mono = Tailwind default); `--paper` không có trong DESIGN.md §2 nhưng code dùng 1 lần (PageSelectDialog:98).

## 5. i18n
en.json + vi.json 529 keys, set IDENTICAL (i18n.test:32-34). Default `readLang()` = "en" trừ khi localStorage lang=vi (index.tsx:10-12). `index.html:2` giữ `lang="en"`.

## 6. Tests (67 files / 468, baseline PASS)
- tokens.test.ts đọc file trực tiếp (contrast gates) — không đụng tokens.
- Class asserts duy nhất liên quan spec: Storage.test:107 `max-w-7xl` (E3, co-located src/pages/). ExtractionPage.test:301 `max-w-[calc(100vw-2rem)]` (popover, ngoài spec).
- LayoutPreview.test:73-79 assert style text chứa "Times New Roman"/"Inter"/"#2563eb" → SẼ VỠ khi C2 đổi docStyle (update per spec intent).
- Button.test assert `rounded-md`, `active:-translate-y-px` — không đụng spec.

## 7. Dead code (grep full-path confirmed)
Xóa 7 src + 6 tests theo SPEC C5 (Dropzone, MarkdownEditor, PreviewTabs, MarkdownPreview-transitive, ResultPanel, wizard×2, Register). LƯU Ý import relative: Dropzone:6-7 `from "./wizard/..."` → grep spec phải thêm pattern relative.
GIỮ: tests/pages/Jobs.upload.test.tsx (comment Dropzone historical).

## 8. Risks ngoài phạm vi SPEC (KHÔNG sửa lần này — ghi nhận)
- `bg-black/50` ở 5 file (ConfirmDialog:31, SubmitModal:28, CropDialog:121, PageSelectDialog:64, TextSection:513) — DESIGN.md cấm pure black nhưng không token overlay → không đụng.
- `motion/react` entrance ở Landing:1,26-28 (useReducedMotion chỉ tắt initial, không tắt whileInView) — SPEC chỉ xóa delay, giữ component Reveal.
- Hardcode VI không i18n ở các file dead + IrViewer/ExportBar/UnifiedEditor/JobRow/AdminApi/AdminUsers/AdminWorkers — ngoài scope.
- AdminLogs:154 `toLocaleString("vi-VN")` hardcode vs `t("i18n.locale")` ở nơi khác — ngoài scope.
- AuthLayout `min-h-dvh` lồng trong App `min-h-dvh` — ngoài scope.
- client.ts:401 tự navigate("/signin") — ngoài scope.
- query key ["me"] shared 5 nơi; queryClient module singleton (App:36) — ngoài scope.
