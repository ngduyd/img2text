# Plan Y — Landing page + App UI polish (dual lane)

Specs: docs/superpowers/specs/2026-10-05-plan-Y-landing-app-polish.md
Lanes: A = landing (worktree plan-landing, base 59ba16a); B = app polish (worktree plan-app-polish, base 59ba16a). Parallel OK — disjoint file ownership (A: App.tsx route, pages/Landing*, package.json+motion dep; B: pages/{Jobs,JobDetail,Login,Profile}, components/*, index.css — NOT App.tsx, NOT package.json). Merge order: A then B.

## Lane A — Landing page (design-taste-frontend skill binding)
Route: `/landing` (root stays Jobs; promotion to root = post-launch decision). Vietnamese copy.
Sections (exact, no more): 
1. Hero — asymmetric split: left = H1 (≤2 lines) + subtext (≤20 words) + 1 CTA "Bắt đầu" (link /login, SAME label everywhere) + secondary text link "Xem cách hoạt động" (#how anchor); right = REAL mini-preview component (actual Jobs-list + status-badge styling reused, not div-fake). Eyebrow max 1 trên toàn trang.
2. (#how) Cách hoạt động — 3 việc, verb-noun labels (Chụp/Tải lên, Chỉnh sửa, Xuất file — KHÔNG "Bước 1/2/3"), layout family: numbered horizontal rail hoặc stacked list, KHÔNG 3 card equal.
3. Tính năng — bento grid exact cell count (chọn 5 features → 5 cells, 2-3 cells có visual variation: gradient token tint hoặc real picsum seed image), features: wizard chọn trang+xoay, crop ảnh trước khi gửi, preview MD/PDF/DOCX, chỉnh sửa từng vùng (region), xuất DOCX/PDF/HTML.
4. Định dạng + free-tier strip — supported formats badges + "Chạy miễn phí trên Google Colab" note (honest, không hype).
5. CTA cuối — lặp label "Bắt đầu".
Motion: `motion/react` (dep mới) — hero entry + whileInView reveals (RevealStagger pattern 5.C), reduced-motion respect (useReducedMotion), isolate client leaves. MOTION_INTENSITY 5 = page THẬT có chuyển động.
Rules: ZERO em-dash visible; theme auto (respect .dark class của ThemeToggle — dual mode tested both); icons lucide-react (project đã có, skill override allowed); fonts = hiện tại của project (Inter-family acceptable — project already depends); no scroll cues, no version labels, no dots, no pills-on-images; nav: link "Đăng nhập" (label trùng intent "Bắt đầu"? — nav = auth intent, dùng "Đăng nhập" cho nav, "Bắt đầu" cho CTA — 2 intent khác nhau, OK; NO duplicate CTA intent).
Tests: Landing.test.tsx — renders H1/CTA "Bắt đầu" href /login, bento features count, formats strip, motion reduced-motion path (mock useReducedMotion true → no transform props or static), no em-dash assertion (grep render output for "—"). data-testid: landing, landing-hero, landing-cta, landing-how, landing-features, landing-formats.
Commit: "feat(web): landing page /landing (marketing)".

## Lane B — App UI polish (ui-ux-dev skill checklist binding)
Audit-first: read skill file /home/ngduyd/.pi/agent/skills/ui-ux-dev/SKILL.md; produce audit table (page → issues → fix) IN report.
Scope (pages/components, NOT App.tsx): Jobs (row hierarchy, status badge consistency JobRow, filter chips, empty state), JobDetail (header layout, section spacing, breadcrumbs/back link), Login (form pattern: label above input, helper/error below, contrast), Profile (same form pattern), AppNav (single line desktop, active state, focus-visible, token spacing), index.css (token gaps: focus-visible ring global, contrast fixes if any <4.5).
Hard rules: preserve ALL testids (R51); dark default; tokens only (no hardcoded colors); 320px; a11y labels; no layout logic changes; tests adjust ONLY if queries break, never delete assertions.
Tests: existing suites green (135+); new cheap assertions only if behavior added.
Commit: "polish(web): app UI pass per ui-ux-dev checklist".

## Gate (after both merged)
web full suite + tsc + build + oxlint; manual: /landing both modes + 320px; e2e-checklist Section F: F1 landing CTA → /login; F2 landing both themes OK; F3 app pages pass focus-visible/contrast spot-check.
