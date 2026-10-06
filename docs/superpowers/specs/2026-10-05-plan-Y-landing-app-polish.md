# Plan Y — Landing page + App UI polish (Design Spec)

## Decisions
- Landing route `/landing` (root `/` = Jobs giữ nguyên; promote sau launch). VN copy. 5 sections: hero asymmetric split (real mini-preview component, 1 CTA "Bắt đầu" → /login), how-it-works (verb-noun, không "Bước 1/2/3", không 3-equal-cards), features bento exact 5 cells (2-3 cells visual variation), formats + Colab free strip, final CTA lặp "Bắt đầu". Eyebrow ≤1 toàn trang. Zero em-dash. Motion via `motion/react` (dep mới, MOTION_INTENSITY 5: hero entry + whileInView RevealStagger + useReducedMotion respect). Dual-mode theo prefers-color-scheme + html .dark class (ThemeToggle hiện có). Icons lucide-react (đã có).
- App polish (Lane B) theo ui-ux-dev checklist: audit-first, Jobs/JobDetail/Login/Profile/AppNav/index.css — tokens, form pattern (label trên, helper/error dưới), focus-visible global, contrast ≥4.5, 320px, badge consistency. Giữ nguyên test logic + testids (R51), tests adjust-only.

## Non-goals
Root-route promotion; stats; real Colab billing pages; font swap (project font giữ nguyên — Inter-family acceptable override 4.1); Next.js/RSC (project = Vite SPA).

## File ownership (parallel lanes)
Lane A: web/src/App.tsx (route), web/src/pages/Landing*, package.json (motion), Landing.test.tsx.
Lane B: web/src/pages/{Jobs,JobDetail,Login,Profile}* , web/src/components/* (trừ App.tsx), web/src/index.css.
Merge order A → B.
