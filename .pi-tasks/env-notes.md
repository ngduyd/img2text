passes — 60 files / 450 tests, vitest 5.0.3.	TASK_0001	mw0w9l1s-apoqh42w	web npm test
6 failed, 938 passed — pre-existing, server/ untouched by task.	TASK_0001	mw0w9l1s-apoqh42w	server pytest
exit 2 collection error — pre-existing.	TASK_0001	mw0w9l1s-apoqh42w	worker pytest
exit 1 (login 401); `web/scripts/audit-a11y.mjs` has no `process.exit`, matching MEMORY.md's "always exit 0" note.	TASK_0001	mw0w9l1s-apoqh42w	web audit:a11y
repo-root `AGENTS.md` exists (§0–§5 incl. "UI gate", "Playwright MCP"); no `web/AGENTS.md`.	TASK_0001	mw0w9l1s-apoqh42w	AGENTS.md
`cd web && npm run audit:a11y` exits 1 here — throws `Error: login 429` at `web/scripts/audit-a11y.mjs:38`; script has no `process.exit`.	TASK_0001	mw0w9l1s-apoqh42w	audit:a11y
`web/src/components/LayoutPreview.tsx:3` imports `markdown-it`, resolves via `web/node_modules/markdown-it` though not declared in `web/package.json`.	TASK_0001	mw0w9l1s-apoqh42w	markdown-it
