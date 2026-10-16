# SPEC restyle đồng nhất design — web/

## 1. Mục tiêu + phạm vi + ràng buộc

- Mục tiêu: 1 shell, 1 header, 1 bộ components, hết hex/font cấm, hết lệch a11y.
- Phạm vi: `web/src/**`, `web/tests/**` (chỉ C5+C6). Chỉ classes/JSX trình bày. Không đụng `index.html`, `lib/status.ts`.
- R51: giữ `data-testid`, behavior, logic, routes, copy/i18n keys.
- R51 exceptions EXPLICIT (toàn bộ, không thêm):
  - E1 copy: new keys `auth.forgot.subtitle`, `auth.reset.subtitle`, `auth.forgot.backToSignin`, `auth.reset.backToSignin` (en+vi) — AuthLayout bắt `subtitle: string` (AuthLayout.tsx:8,30); keys cũ không tồn tại (forgot chỉ title/sent/submit/enterCode; reset không subtitle).
  - E2 behavior: xóa `<QuotaBadge/>` khỏi Jobs.tsx:149 (quota vẫn hiện ở nav).
  - E3 test: `Storage.test.tsx` 1 dòng max-w (C6).
  - E4 copy: Storage pagination glyphs `‹ ›`→text labels `t("storage.prevPage")/t("storage.nextPage")` (C3 Storage; giữ testids+aria-label).
  - E5 display: Profile joined row thêm `<time>{me.created_at}</time>` (C3 Profile; data đã có trong type `created_at?`).
- Tokens thật duy nhất (`tokens.css` + `index.css` `@theme`): `bg-bg/surface/surface-2`, `text-text/muted/accent-text/accent-contrast/success/warning/error`, `bg-accent`, `border-border`, `shadow-card`, `rounded-sm/md/card`, `.skeleton`. Cấm hex cứng.
- Gates (`web/`): `npm test`, `npx tsc --noEmit`, `npm run build`, `npx oxlint`.
- oxlint "sạch" = exit 0, KHÔNG phải 0 warnings (baseline đã có warnings; move Stat/fmtBytes/pageWindow sang `ui/` thêm `only-export-components` warnings — chấp nhận).
- Signup/Signin exempt (đã AuthLayout: Signin.tsx:37, Signup.tsx:43).
- `index.html` giữ `lang="en"` — default locale "en" (i18n/index.tsx:10-12); lang=vi out of scope pending default-locale change.

## 2. Quyết định thiết kế

### 2.1 PageShell — ladder 2 widths + REPLACE rule
- Tạo `src/components/PageShell.tsx`:
```tsx
import type { ReactNode } from "react";
const W = { content: "max-w-3xl", wide: "max-w-6xl" } as const;
export default function PageShell({ width = "content", testid, children }: { width?: keyof typeof W; testid?: string; children: ReactNode }) {
  return <main id="main" data-testid={testid} className={`mx-auto ${W[width]} px-4 py-6 sm:px-6`}>{children}</main>;
}
```
- 12 root `<main id="main">` hiện có (10 instances PageShell + Forgot:30/Reset:46 → AuthLayout) → REPLACE (không bọc lồng, tránh duplicate id): Jobs:143, Storage:70, JobDetail:136/181, ExtractionPage:48, Profile:36/89, Feedback:36, Features:20 (pass `testid="features-page"`), Admin:52, Forgot:30/Reset:46 (→ AuthLayout, không phải PageShell).
- `wide`: Storage (`max-w-7xl`→wide), Admin (`max-w-5xl`→wide), Features (`max-w-5xl`→wide), JobDetail loaded (`max-w-[1400px]`→wide).
- `content`: Jobs, ExtractionPage (`max-w-4xl`→content), Profile/Feedback (`max-w-md`→content), JobDetail loading.
- Landing KHÔNG dùng PageShell (giữ custom root): `div[data-testid=landing]` (Landing.tsx:147) → `<main id="main" data-testid="landing">` (skip-link fix duy nhất).
- Exempt: `AuthLayout` giữ `max-w-sm`. `AppNav` inner + `SiteFooter` inner `max-w-5xl`→`max-w-6xl`.
- Padding trang: `px-4 py-6 sm:px-6`. Section `mb-6`, gap scale 4/8.

### 2.2 PageHeader — API duy nhất
- Tạo `src/components/PageHeader.tsx`:
```tsx
import type { ReactNode } from "react";
export default function PageHeader({ title, subtitle, actions, testid, beforeTitle }: { title: string; subtitle?: string; actions?: ReactNode; testid?: string; beforeTitle?: ReactNode }) {
  return (
    <header data-testid={testid} className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {beforeTitle ? (
          <div className="flex items-center gap-3">{beforeTitle}<h1 className="text-2xl font-bold tracking-tight">{title}</h1></div>
        ) : (
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        )}
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
```
- h1 chuẩn `text-2xl font-bold tracking-tight`. Ngoại lệ giữ: Landing hero `clamp()`, Features hero `text-3xl md:text-4xl`.
- ExtractionPage: back link `link-back-job` → `beforeTitle` (giữ layout hiện tại: link TRÁI h1 inline, ExtractionPage.tsx:53-60; PageHeader không có left slot khác).
- Dùng cho: Jobs (stats `dl`→`actions`), Storage, ExtractionPage (`testid="extraction-header"`), Profile (`LangSwitch`→`actions`), Feedback (thêm h1 mới), Admin. Forgot/Reset dùng `AuthLayout title`, không dùng PageHeader.

### 2.3 Components tạo/gom
| Tên | Path | Props | Consumers |
|---|---|---|---|
| `EmptyState` | `src/components/ui/EmptyState.tsx` | `{icon:LucideIcon;title?:string;body:string;extra?:ReactNode;action?:ReactNode;testid?:string}` → `div.flex.flex-col.items-center.px-2.py-6.text-center`, icon `h-10 w-10 text-muted`, title `h2.mt-3.text-base.font-semibold` (optional — fb-empty không title), body `p.mt-1.max-w-sm.text-sm.text-muted`, extra sát sau body, action `div.mt-4` | Jobs (`empty-state`: title=jobs.emptyTitle, body=jobs.emptyBody, extra=`<><p>{jobs.emptyWorker}</p><p cta/></>`), Storage (`storage-own-empty`), AdminStorage, AdminUsers (`users-empty`: Users icon + admin.users.emptyTitle), AdminLogs (`logs-empty`: FileText + admin.logs.emptyTitle), AdminFeedbacks (`fb-empty`: MessageSquare, không title) |
| `Pagination` | `src/components/ui/Pagination.tsx` | `{page,totalPages,onChange,prevTestid,nextTestid,pageTestid? (prefix → `data-testid={`${pageTestid}-${n}`}` cho Jobs `btn-page-*`),numbers?,info?,navTestid?,ariaLabel}` → `nav.mt-4.flex.flex-wrap.items-center.justify-center.gap-2`, nút `Button secondary sm` | Jobs (numbers, `btn-page-*`, nav `pagination`), Storage (`storage-own-prev/next`+info), AdminStorage (`storage-prev/next`+info). Move `pageWindow` từ `Jobs.tsx` sang đây + export |
| `Select` | `src/components/ui/Select.tsx` | `{label:string;testid?}+SelectHTMLAttributes` → label-above, `select.h-10.rounded-sm.border.border-border.bg-surface.px-2.text-sm.text-text` | Jobs sort `jobs-sort` |
| `Textarea` | `src/components/ui/Textarea.tsx` | `{label:string;testid?;error?}+TextareaHTMLAttributes`, mirror `Input.tsx` (error `role=alert`) | Feedback `feedback-content` |
| `Stat` | `src/components/ui/Stat.tsx` | move `Stat`+`fmtBytes` từ `AdminStorage.tsx` (giữ markup/classes), thêm `valueClassName?` | Storage, AdminStorage, Jobs stats (`stats-total/pending/done`, tone qua `valueClassName:text-warning/text-success`; GIỮ `dl>dd` semantics — Stat render bên trong `dd`, không thay `dl` bằng div) |
- Skeleton rule: mọi loading = `Skeleton`, cấm text bare. Profile (`profile-loading`), Admin (`admin-loading`), AdminFeedbacks (`fb-loading`, :35), AdminSettings (`settings-loading`, :243), AdminKaggleQuota (`kaggle-quota-loading`, :55) — giữ testid, đổi sang Skeleton rows. AdminUsers `users-loading` / AdminLogs `logs-loading` đã skeleton rows — không đụng.

## 3. Per-file change list (commit order)

### C1 shared mới (không đụng pages)
- `components/PageShell.tsx`, `components/PageHeader.tsx`, `components/ui/EmptyState.tsx` (có `extra?`, `title?`), `components/ui/Pagination.tsx`, `components/ui/Select.tsx`, `components/ui/Textarea.tsx`, `components/ui/Stat.tsx`: tạo mới theo §2.

### C2 tokens/banned/a11y nền
- `lib/docStyle.ts` `buildPreviewDocCss`: `Inter, system-ui, sans-serif`→`system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; `color: #2563eb`→`color: var(--accent-text)`; `FONT_FAMILIES` xóa `"Times New Roman"`,`"Georgia"` → `["system-ui","Arial","Courier New"]`.
- Iframe fix (LayoutPreview.tsx:142 srcDoc chỉ có `<style>`, tokens không inherit → link color mất): inject `:root` token block vào srcDoc trước wordBase — exact props: `--accent-text:#58a6ff` (dark, tokens.css:12) + `@media (prefers-color-scheme: light) { :root { --accent-text:#0861cf } }` (light token — tokens.css:43 là source-of-truth; DESIGN.md §2 ghi #0969da là stale) — tránh fail contrast 2.9:1 khi preview render light. Prop duy nhất mà doc css reference sau đổi. Không giữ hex riêng cho iframe.
- `index.html`: KHÔNG đổi (giữ `lang="en"`, xem §1).
- `components/ConfirmDialog.tsx`: nút `confirm-accept` xóa `className="border border-error/40 bg-error/10"` (đúng variant `danger` text-only).
- `pages/admin/AdminStorage.tsx`: import `Stat,fmtBytes` từ `ui/Stat`, xóa local; nút `storage-purge-due` xóa classes bordered-fill thừa.
- `pages/Signin.tsx:~60`: `span` password → `<label htmlFor="input-password" className="text-sm text-muted">`.
- `pages/Forgot.tsx`: error `p` thêm `role="alert"`.

### C3 pages (REPLACE root main bằng PageShell/AuthLayout — không bọc lồng)
- `App.tsx`: nav inner `max-w-5xl`→`max-w-6xl`. Giữ `QuotaBadge` nav, giữ `after:w-0.5`.
- `components/SiteFooter.tsx`: inner `max-w-5xl`→`max-w-6xl`.
- `pages/Landing.tsx`: root `div[data-testid=landing]`→`main id="main"` (giữ testid, fix skip-link; KHÔNG PageShell); xóa mọi `delay=` (giữ component `Reveal`, hero `motion.div` 1 lần, list items render thường).
- `pages/Features.tsx`: REPLACE root main → `PageShell wide testid="features-page"`; grid `md:grid-cols-3`→`md:grid-cols-2`, card 3 `md:col-span-2`; thêm CTA cuối `Link to="/jobs"` primary, label `t("landing.cta")` (reuse key hiện có, không new key).
- `pages/Jobs.tsx`: REPLACE root main → `PageShell content`; header→`PageHeader` (giữ `dl>dd` semantics + stats testids; Stat value/tone nằm trong `dd`); search input `rounded-md`→`rounded-sm` + `h-10`; sort→`Select`; pagination→`Pagination numbers` (giữ testids); empty→`EmptyState` (extra=`<p>{jobs.emptyWorker}</p>`, action=CTA jobs.emptyCta — GIỮ `dl` stats testids; giữ Jobs.test.tsx:240-242 assert "Jobs wait for the Colab worker to connect"); xóa import + `<QuotaBadge/>` (E2, giữ ở nav); bulk-bar (`fixed bottom`, :457) spacer = last child `<div aria-hidden className="h-16"/>` INSIDE page main (không phải sau nav).
- `pages/JobDetail.tsx`: loading/loaded REPLACE root main → `PageShell` (loaded `wide`); header actions mỗi `Button` thêm `min-h-11`.
- `pages/Storage.tsx`: REPLACE root main → `PageShell wide`; header→`PageHeader`; empty→`EmptyState` (giữ testid+CTA `/jobs`); glyphs `‹ ›`→text `t("storage.prevPage")/t("storage.nextPage")` (E4 copy exception; giữ testids+aria-label) hoặc `Pagination info`; import `Stat` từ `ui/Stat`.
- `pages/ExtractionPage.tsx`: REPLACE root main → `PageShell content`; header→`PageHeader testid="extraction-header" beforeTitle={back link link-back-job}`.
- `pages/Profile.tsx`: REPLACE root main → `PageShell content`; header→`PageHeader actions=<LangSwitch/>`; loading→Skeleton (giữ `profile-loading`); joined row thêm `{me.created_at && <time dateTime={me.created_at}>{new Date(me.created_at).toLocaleDateString(t("i18n.locale"))}</time>}` (type đã có `created_at?`; E5 display exception).
- `pages/Feedback.tsx`: REPLACE root main → `PageShell content`; thêm `PageHeader title`; Card bỏ prop `title` (giữ `testid`), `textarea`→`Textarea` (giữ id/testids/maxLength/count).
- `pages/Forgot.tsx`, `pages/Reset.tsx`: REPLACE root `<main className="mx-auto max-w-sm p-6">` (Forgot:30, Reset:46) bằng `AuthLayout` — title=t(auth.forgot/reset.title), subtitle=new key E1, footer=Link `/signin` (new key `backToSignin` E1); form inner giữ nguyên testids. (E1 copy exception.)

### C4 admin
- `pages/Admin.tsx`: REPLACE root main → `PageShell wide`; rail `after:w-1`→`after:w-0.5`; loading→Skeleton (giữ `admin-loading`).
- `pages/admin/AdminStats.tsx`, `pages/admin/AdminApi.tsx`, `pages/admin/AdminStorage.tsx`: `th` thêm `scope="col"` + `className="sticky top-0 z-10 border-b border-border bg-surface-2 px-3 py-2 font-medium text-muted"` (AdminStorage:122-127 hiện thiếu scope; Stats/Api cũng thiếu), bọc `div.overflow-x-auto`, số `font-mono tabular-nums`.
- `pages/admin/AdminStorage.tsx` (tiếp C2): empty bare `p`→`EmptyState`; pagination→`Pagination info` text labels.
- `pages/admin/AdminFeedbacks.tsx`, `AdminSettings.tsx`, `AdminKaggleQuota.tsx`: loading bare-text → Skeleton (giữ `fb-loading`/`settings-loading`/`kaggle-quota-loading`).

### C5 cleanup
- Xóa 7 src: `pages/Register.tsx` (không import nào trỏ tới), `components/Dropzone.tsx`, `components/wizard/ImageCropWizard.tsx`, `components/wizard/PdfWizard.tsx`, `components/PreviewTabs.tsx`, `components/panels/ResultPanel.tsx`, `components/MarkdownEditor.tsx`.
- Xóa 6 tests import trực tiếp (tsconfig.app.json include `["src","tests"]` nên phải xóa cùng, không sẽ fail tsc): `tests/components/Dropzone.test.tsx:7`, `tests/components/MarkdownEditor.test.tsx:7`, `tests/components/PreviewTabs.test.tsx:7`, `tests/components/panels/ResultPanel.test.tsx:7`, `tests/wizard/PdfWizard.test.tsx:5`, `tests/wizard/ImageCropWizard.test.tsx:5`.
- Giữ: `tests/pages/Jobs.upload.test.tsx` (file ở lại; comment :8 đã ghi "(Dropzone đã xóa)" — historical, không sửa).
- Verify trước xóa — filter by import paths ONLY (comment "Reuse Dropzone lane", Jobs.tsx:112, không match):
```
grep -rn "components/Dropzone\|components/wizard/PdfWizard\|components/wizard/ImageCropWizard\|components/PreviewTabs\|components/panels/ResultPanel\|components/MarkdownEditor\|pages/Register\|\./wizard/\|\./Dropzone\|\./PreviewTabs\|\./MarkdownEditor" web/src web/tests --include='*.tsx' --include='*.ts'
```
chỉ còn import trong chính 13 files trên mới xóa. Sau xóa `npx tsc --noEmit`.

### C6 tests
- `pages/Storage.test.tsx:~107`: `max-w-7xl`→`max-w-6xl` (E3 — dòng duy nhất được vỡ có chủ ý). Còn lại giữ.

## 4. Cleanup
- File xóa chốt §3 C5 (13 files). Lệnh verify như trên.

## 5. Test impact
- `Storage.test.tsx`: 1 dòng max-w vỡ có chủ ý (E3); các assert pagination/skeleton/empty/testids không được vỡ.
- `Jobs.test.tsx`: `empty-state` assert Colab line (:240-242) — EmptyState `extra` phải giữ nguyên text.
- `Features.test.tsx`: giữ `features-page` (:21) qua PageShell testid.
- `Landing.test.tsx`: giữ testids `landing*` — file dùng `getByTestId("landing")`, KHÔNG assert tag → div→main không vỡ.
- `App.test.tsx`: nav max-w change; giữ testids.
- `Auth.test.tsx`: Signin/Signup untouched; Forgot/Reset chuyển AuthLayout — check asserts wrapper, giữ testids form.
- `ExtractionPage.test.tsx`: giữ `link-back-job`, `extraction-loading`; header testid giữ.
- `Profile.test.tsx`: giữ `profile-loading` (giờ Skeleton).
- `Jobs.upload.test.tsx`: ở lại, không vỡ (comment Dropzone historical).
- `admin/AdminWorkers.test.tsx`, `Admin.test.tsx` (8 tabs rail, giữ testids rail), `AdminStorage/AdminUsers/AdminSettings/AdminFeedbacks/AdminKaggleQuota/VerifyModal tests`: testid-based, giữ testids.
- `pages/Feedback.test.tsx` (co-located trong src/pages, không phải tests/): testids-only, an toàn nếu giữ testids/id.
- `tokens.test.ts`: không đụng tokens, phải pass.

## 6. Verification checklist
```
cd web
npm test             # pass, không regress (baseline 67 files)
npx tsc --noEmit     # sạch, nhất là sau C5
npm run build        # success
npx oxlint           # exit 0 (= sạch; warnings baseline + only-export-components mới chấp nhận)
```
- Manual 320/768/1024/1440: không overflow ngang; bulk-bar không che pagination; JobDetail actions wrap mobile đủ 44px; skip-link/focus-ring/`aria-expanded`; reduced-motion tắt shimmer.

## Task list
- [ ] C1 shared: PageShell (+testid), PageHeader (+testid, +beforeTitle), EmptyState (+extra, title?, action dùng cho Jobs CTA), Pagination (+move pageWindow, pageTestid=prefix), Select, Textarea, Stat (+move fmtBytes; oxlint exit-0)
- [ ] C2 nền: docStyle + iframe :root --accent-text 2 themes (dark+light media), ConfirmDialog/AdminStorage danger, Signin label, Forgot role=alert (KHÔNG đụng index.html lang)
- [ ] C3 pages: REPLACE root main (9 mains) — nav/footer max-w, Landing div→main (no PageShell), Features 2-col+CTA landing.cta, Jobs E2+extra+spacer-in-main, JobDetail, Storage, Extraction beforeTitle, Profile, Feedback, Forgot/Reset AuthLayout + E1 keys
- [ ] C4 admin: shell+rail+skeleton (+3 bare-text loadings), Stats/Api/AdminStorage th scope=col, Storage empty+pagination
- [ ] C5 xóa 7 src + 6 tests + import-path grep verify + tsc (Jobs.upload.test ở lại)
- [ ] C6 update Storage.test 1 dòng (E3) + full gates pass-không-regress
