# Design System: img2text (web/)

Single source of truth for Tasks 2–4 restyle and future Stitch use.
Binding skills: stitch-design-taste (semantic language) + ui-ux-dev (a11y gate).
Hex/px values below are pinned from the ACTUAL shipped tokens
(`src/styles/tokens.css`, mapped into utilities via `src/index.css` `@theme`).
Do not invent a parallel palette. Dark theme is DEFAULT; light flips by removing
`.dark` from `<html>` (ThemeToggle, key `img2text-theme`).

## 1. Visual Theme & Atmosphere

A restrained, "Daily App Balanced" product tool — Density 5–6, Variance 4,
Motion 4. Clinical yet warm: a well-lit workshop bench, not a showroom.
Dark-first zinc canvas (#0d1117) with a light-mode token flip, one confident
blue accent, whisper-thin borders, and calm feedback motion. Functional offset
is allowed in product UI (asymmetric header rows, wrapped metadata) — never
chaotic stacking. Tool UI: quiet while working, tactile at the moment of touch.

## 2. Color Palette & Roles

Dark (`:root`) — Light (`html:not(.dark)`):

- **Canvas** (`--bg`) — page background: `#0d1117` / `#ffffff`
- **Surface** (`--surface`) — card/container fill: `#161b22` / `#f6f8fa`
- **Surface-2** (`--surface-2`) — subtle raise: hover fills, skeleton base: `#1c2128` / `#eaeef2`
- **Charcoal Ink** (`--text`) — primary text: `#e6edf3` / `#1f2328`
- **Muted Steel** (`--muted`, alias `--text-muted`) — secondary text, metadata, helpers: `#8b949e` / `#59636e`
- **Whisper Border** (`--border`) — 1px structural lines, table dividers: `#30363d` / `#d0d7de`
- **Accent Fill** (`--accent`) — primary buttons, active states, focus ring: `#1c64e4` / `#0969da`
- **Accent Text** (`--accent-text`) — links and text accents (contrast-safe): `#58a6ff` / `#0969da`
- **Accent Contrast** (`--accent-contrast`) — label text ON accent fill: `#ffffff` / `#ffffff` (≥4.5:1, gated by `tokens.test.ts`)
- **Success** (`--success`): `#3fb950` / `#1a7f37` — done states, success badges
- **Warning** (`--warning`): `#d29922` / `#9a6700` — caution badges, warnings
- **Error** (`--error`): `#f85149` / `#cf222e` — failed states, error borders/text, danger buttons
- **Shadow Card** (`--shadow-card`) — tinted elevation, canvas-hue matched: `0 1px 2px rgba(1,4,9,0.6)` dark / soft double-layer light
- **Focus Ring** (`--focus-ring`) — accent hue, 2px outline, 2px offset (global `:focus-visible`)

Rules: single accent (blue `#58a6ff` family, saturation ≤80%); semantic tokens
only for status; no new hues outside this set. `--accent` (#1c64e4) is the FILL;
use `--accent-text` (#58a6ff) for accent-colored text on dark surfaces
(#1c64e4 = 3.3:1 on --surface — too low for text). No pure black; canvas is
never `#000000`. `--muted` remains the shipped token; `--text-muted` is a
semantic alias — both stay valid (lazy aliasing, no rename).

## 3. Typography Rules

- **Display/Body:** `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (KEEP — satisfies anti-Inter; no web fonts, no network dependency)
- **Mono:** `ui-monospace, "Cascadia Code", "JetBrains Mono", monospace` (system mono pair; `font-mono` utility)
- **Hierarchy:** weight + color, never scale-screaming. Body line-height 1.5, headings 1.2, `-0.02em` tracking on large headings. Max ~65ch line width for prose.
- **Dashboard constraint:** sans-serif exclusively; NO serifs anywhere in product UI.
- **High-density rule:** all numbers in admin tables, logs, timestamps, IDs, IPs use the mono family (`font-mono`, tabular where columns align).
- **Copy:** Vietnamese product copy, single spelling per concept (`STATUS_TEXT` in `lib/status.ts` is the canonical status wording — do not paraphrase).

## 4. Component Stylings

- **Buttons:** flat, no outer glow, no custom cursor. Tactile push: `active:-translate-y-px` + `active:brightness-110`. Radius 8px (`rounded-md`). Variants: `primary` (accent fill, `--accent-contrast` label), `secondary` (the outline role: 1px border + surface fill), `ghost` (text, hover surface-2), `danger` (error text, error/10 hover). Focus = global accent ring. `loading` = `aria-busy` + disabled (skeleton-safe: no spinner animation inside buttons).
- **Cards:** radius 8px (`rounded-card` = `--radius-md`), 1px whisper border, `shadow-card` tinted elevation. Use ONLY when elevation communicates hierarchy; high-density areas (admin tables) use border-top/divider rows instead. No card-in-card nesting.
- **Inputs:** label ABOVE, helper below (optional), error below (role=alert, wins over helper). Height rhythm 40px (`h-10`), radius 6px (`rounded-sm`), surface fill. Focus: accent 2px ring + border → accent. Error: `--error` border + `--error` text. No floating labels.
- **Badges:** pill (`rounded-full`), semantic tones via tokens — success/error/warning use tone/10 fill + tone/40 border + tone text; `info` uses accent/10 + `--accent-text`; `neutral` uses border/surface/muted. Tone map stays aligned with `STATUS_TONE` in `lib/status.ts` (file untouched by styling work).
- **Loaders:** `Skeleton` component — shimmer matching the layout's exact dimensions (`.skeleton`, `@keyframes skeleton`, 1.4s ease-in-out). This is the ONLY sanctioned loop in tool UI. No circular spinners.
- **Empty states:** composed (icon + title + one line of guidance + optional action) — never bare "No data".

## 5. Layout Principles

- CSS Grid for structure, Flexbox for alignment; `gap` over margins between siblings. No `calc()` percentage hacks.
- Contain layouts with max-width constraints (forms: `max-w-sm`/`max-w-md` centered; page content max ~1400px).
- Full-height sections: `min-h-dvh`, never `h-screen` (iOS Safari jump).
- Every element owns its clean spatial zone — no overlapping/stacked absolutes.
- No centered-hero compulsion; functional offset OK in product headers (title left, actions right, wrap on mobile).
- Admin density 6: sticky `thead`, divider rows (no zebra rainbow), mono numbers, truncated IP/UA, icon action buttons with tooltips + `aria-label`.
- Spacing rhythm on the 4/8 scale: 4/8/16/24/32/48/64px. Section gaps `clamp(2rem, 6vw, 4rem)`.

## 6. Motion & Interaction

Motion 4 — CSS transitions + immediate feedback ONLY.

- Interactive feedback: 150ms `ease-out` on `transform`/`opacity`/`filter`/colors. Buttons get tactile `-1px` push on active.
- NO perpetual loops in tool UI. Sole exception: Skeleton shimmer while a section is loading (the loading state itself).
- Animate only `transform` and `opacity` (shimmer background-position on skeletons is the documented exception). Never animate `top/left/width/height`.
- No spring choreography, no staggered cascades, no entrance theater in product screens.
- `prefers-reduced-motion: reduce` → all animations/transitions clamped to ~0 (global rule in `index.css`); skeletons render as static surface-2 blocks.

## 7. Responsive Rules

- Mobile-first: base = mobile; `@media (min-width: 768px)` tablet, `(min-width: 1024px)` desktop. Test at 320/768/1024/1440.
- All multi-column layouts collapse to single column below 768px — no exceptions.
- Horizontal overflow on mobile = critical failure (320px gate): media/canvases `max-width: 100%`; tables scroll inside their own container, never the page.
- Touch targets ≥ 44px for primary interactive elements.
- Headlines scale via `clamp()`; body text ≥ 14px/1rem.
- AppNav: single line ~56–64px desktop; below 768px collapses to hamburger → panel (`aria-expanded`/`aria-controls`/`aria-label="Menu"`), close on link + outside click.
- Job/panel action rows wrap on mobile; JobDetail header = 1 row desktop / wrap mobile.

## 8. Anti-Patterns (Banned)

NEVER:

- Emojis anywhere in UI or copy.
- Inter font, or any serif (Times/Georgia/Garamond/Palatino) in product UI.
- Pure black `#000000`, neon/outer-glow shadows, oversaturated accents.
- Purple/AI-blue-neon aesthetics, gradient text on headers, gradient button fills.
- Custom mouse cursors.
- 3 equal cards in a row as a feature layout.
- Circular spinners (use Skeleton) — and no perpetual loops in tool UI besides skeleton shimmer.
- Floating labels, label-below inputs, placeholder-as-label.
- Card nesting (card inside card).
- Zebra-rainbow table striping; rainbow status colors outside the semantic token set.
- Generic placeholder names (John Doe, Acme, Nexus), fake round numbers (99.99%, 50%).
- AI copywriting clichés ("Elevate", "Seamless", "Unleash", "Next-Gen", "nâng tầm", "bậc nhất").
- Filler UI text: "Scroll to explore", "Swipe down", scroll arrows, bouncing chevrons.
- Hardcoded hex in components — every color from tokens/utilities.
- Deleting or renaming `data-testid`s (R51) during restyles; styling changes classes only.

## Governance (for Tasks 2–4)

- Behavior + testids UNCHANGED (R51). Restyle = classes/JSX structure only.
- Token names already in use keep working (`--muted`, `--accent-text`, `rounded-card`); new roles are aliases/added tokens, never renames.
- Status wording lives only in `lib/status.ts` (`STATUS_TEXT`/`STATUS_TONE`).
- Gate per task: `npm test` (142+), `npx tsc --noEmit`, `npm run build`, oxlint clean.
