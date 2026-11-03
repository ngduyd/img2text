# Spec: JobDetail route split (layout md/word) + Overview column ratio

Date: 2026-11-03
Status: approved by user — Q1 = split into real routes, Q2 = no image panel on `/text` (declined), Q3 = narrow Overview right column now
Path: bounded — 2 independent surfaces, no schema/API change

## Problem

1. **Layout mode is not addressable.** `/jobs/:id/layout` renders one page whose md↔word
   mode lives in `UnifiedEditor` state (`web/src/components/UnifiedEditor.tsx:52-53`:
   `useState<Mode>(job.output_format === "docx" ? "word" : "md")`). Consequences: no deep link
   into Word mode, the switch is lost on reload, and the mode cannot be tested at route level —
   only by clicking `switch-mode-md`/`switch-mode-word`.
2. **Overview right column is wider than it should be.** `/jobs/:id` uses
   `PageShell width="data"` (`JobDetail.tsx:206`) and the right column runs longer/wider than the
   left, so the summary block dominates the page.

Declined in the same decision round (do not implement): an original-image panel on `/text`
(`/layout` already has `btn-toggle-original-layout`).

## Intent

1. Make layout mode part of the URL: `/jobs/:id/layout/md`, `/jobs/:id/layout/word`. Keep
   `/jobs/:id/layout` working as the entry point (backward compat for bookmarks/exports/tests)
   and let it resolve to the mode implied by `output_format`, same rule as today.
2. Narrow the Overview right column. Visual change only — no data, no API, no behaviour change.

## Acceptance criteria

| # | AC | Verify |
|---|---|---|
| AC1 | `/jobs/:id/layout/md` renders md mode, `/jobs/:id/layout/word` renders word mode, without a click | route tests: mount at each URL, assert the mode-specific container is present (`md-editor` vs `preview-docx-frame`) |
| AC2 | Switching mode navigates the URL (md ↔ word), so reload keeps the mode and back/forward works | test: click `switch-mode-word` → URL becomes `/jobs/:id/layout/word` |
| AC3 | `/jobs/:id/layout` still works and resolves to `output_format` (`docx` → word, else md) | existing JobDetail tests keep passing unchanged for that URL |
| AC4 | Must be a **fake** failure: `/jobs/:id/layout` must not loop-redirect | test asserts no `Navigate` on that path |
| AC5 | Overview right column is narrower than before at 1440 and does not overflow at 320 | screenshots before/after at 1440 + 320 (`web/scripts/audit-shots.mjs`), `npm run audit:a11y` → `DONE 0 routes with findings` |

AC5 is a UI change and falls under the repo gate in `AGENTS.md`: no "đã sửa xong" without a
before/after screenshot at the same viewport plus `audit:a11y` at 0 findings.

## Constraints

- `UnifiedEditor` stays the only owner of export/render logic; the route only supplies the initial
  mode. Do not duplicate the export flow per mode.
- Do not touch `/text` or `/extraction`.
- `web/src/App.tsx` route additions only — no router upgrade, no nested layout routes.
