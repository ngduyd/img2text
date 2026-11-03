# MEMORY

## Now
- 2026-11-03 · Xong spec+plan+implement+2 vòng review cho audit drift (xem
  `docs/superpowers/specs/2026-11-03-audit-drift-hardening-design.md` +
  `plans/2026-11-03-plan-audit-drift-hardening.md`). 5 lane song song bằng subagent,
  2 real defect đã sửa sau review. Chờ user duyệt G1–G6 (plan §Approval-gated).
- 2026-11-03 · agentmemory **đang tắt** cho repo này qua `.pi/mcp.json` (`enabled: false`) —
  verify bằng `pi mcp list` → `agentmemory: disabled (codemode, global) / project override`.
- 2026-11-03 · Tạo `AGENTS.md` ở root img2text: gate UI review = Playwright làm bằng chứng
  (`scripts/audit-shots.mjs` + `npm run audit:a11y`) → `ui-ux-review` ra finding →
  `design-taste-frontend` định hướng fix + §14 pre-flight → chụp lại so before/after.

## Decisions
- 2026-11-03 · Tắt agentmemory bằng project override `.pi/mcp.json` thay vì sửa `~/.pi/agent/mcp.json`
  · chỉ ảnh hưởng repo này, bật lại bằng cách đổi `enabled: true` hoặc xoá file.
- 2026-11-03 · Thêm `typescript` vào `.serena/project.yml` (trước chỉ `python`) · web/ có 144 file
  .ts/.tsx, thiếu TS server thì serena mù nửa repo; đã verify `get_symbols_overview` trên
  `web/src/api/types.ts` chạy được.

## Measured
- 2026-11-03 · jobdetail route split · vitest **450 pass/60 file** (+6 test mới), tsc + oxlint sạch
- 2026-11-03 · Overview rail · `gridTemplateColumns` @1440 **564px+564px → 776px+352px**;
  320 giữ nguyên (ảnh before/after byte-identical)
- 2026-11-03 · audit:a11y trước/sau đổi rail · **5 route → 4 route** có finding (không phát sinh mới).
  Finding còn lại: `jobs-search` (/jobs) và `input-current-password` (/profile) thiếu label — pre-existing.
- 2026-11-03 · AC7 · `pytest tests/test_preview_layout_html.py` = **3 passed** (Postgres test :5433 bật)
- 2026-11-03 · AC1 · migration apply 2 lần trên schema `create_all` → OK idempotent; simulate legacy
  (drop 11 cột + bảng) → apply → `text_version`/`rerender_requested`/`ocr_enabled` **null=NO**
  đúng model, `mode`/`output_format` có default, `worker_heartbeats` 4 cột đúng → **VERIFIED**
- 2026-11-03 · sau AC1 · `pytest test_preview_layout_html.py + test_models.py` = 4 passed (không vỡ)
- 2026-11-03 · G1 · `pw_watch_trg`/`pw_watch_fn`/`pw_watch` đã drop khỏi `img2text_dev`, users vẫn 4 row
- 2026-11-03 · G3 · xoá 23 branch đã merge (giữ `lane-deps` vì đang checkout trong worktree)
- 2026-11-03 · G4 · `.worktrees/plan-auth`, `.worktrees/plan-pr` là thư mục **rỗng** → rmdir
- 2026-11-03 · CI chạy test cần DB thế nào: service `postgres:16-alpine` publish **:5436**
  (`.github/workflows/ci.yml:21`), `DATABASE_URL` (:26) → create_all → `psql docs/migrations/*.sql` → pytest
- 2026-11-03 · codegraph index · 332 files / 5.527 nodes / 13.296 edges (DB 15,84 MB)
- 2026-11-03 · size repo · 162 file .py (server+worker, trừ .venv) / 144 file .ts,.tsx (web/src, web/tests)

## Facts (stack + lệnh chạy)
- Kiến trúc: Browser SPA → Nginx → FastAPI (:8010) + Postgres 16 + Cloudflare R2 →
  worker Kaggle/Colab pull `GET /api/jobs/next` (Bearer RUNNER_KEY).
- dev: `cp deploy/.env.dev.example deploy/.env.dev` → `docker compose -f deploy/docker-compose.dev.yml up -d --build`
  (Postgres :5433, LocalStack :4566, API :8010); web: `cd web && npm run dev` (:5173, proxy /api).
- test: `cd server && .venv/bin/pytest -v` (cần Postgres :5433 qua docker-compose.test.yml) ·
  `cd worker && .venv/bin/pytest -v` · `cd web && npm test` · lint `cd web && npm run lint` (oxlint).

- 2026-11-03 · playwright ^1.64.0 đã có sẵn trong `web` devDependencies; scripts UI đã tồn tại:
  `audit-a11y.mjs` (8 route × 1440/320), `audit-shots.mjs` (4 width → /tmp/audit),
  `landing-shots.mjs` (→ web/public/shots), `capture.mjs` → không cần cài thêm gì.
- 2026-11-03 · `audit-a11y.mjs` luôn exit 0 — gate phải đọc dòng `DONE N routes with findings`.
- 2026-11-03 · route "/" là `Landing`; a11y audit phủ "/", /jobs, /jobs/5, /jobs/5/text,
  /jobs/5/layout, /storage, /profile, /admin (8 route).

## Dead ends
- 2026-11-03 · `audit-shots.mjs shoot` không chụp `/jobs/:id` (chỉ 8 route list) → phải viết script
  riêng; và `audit-a11y.mjs` login bị **429** sau ~3 lần chạy (limiter RAM trong container API) →
  fix: `docker compose -f deploy/docker-compose.dev.yml restart server`.
- 2026-11-03 · Docker: container tạo trước khi daemon restart giữ network cũ đã mất →
  `up -d` fail "network … not found"; fix: `up -d --force-recreate` (data trong named volume nên an toàn).
- 2026-11-03 · G2 (xoá Kaggle dataset `jhandf/img2text-wheelbuild-env` + 2 kernel) · **không làm được
  trên máy này**: không có `kaggle` CLI lẫn `~/.kaggle/kaggle.json`. Cần token hoặc làm trên web UI.
- 2026-11-03 · subagent `reviewer` mặc định (`bench/opencode/muse-spark-1.3-contributor-free`)
  → HTTP 400 "Model is unavailable" trên cả 3 reviewer. Dùng `model: "9router/KG/claude-sonnet-4.5"`
  (verify bằng curl). `9router/role-reviewer` → resolve ra `reflection/beam:free`, trả content rỗng
  khi `max_tokens` nhỏ.
- 2026-11-03 · `pi mcp list` không in gì khi chạy trong pipe có timeout sớm; phải redirect file
  rồi cat.

## Next
- Serena onboarding chưa chạy (`.serena/memories/` rỗng) — chạy nếu muốn serena tự ghi memory dài hạn.
- 2026-11-03 audit: 8 bảng + 3 cột trong `models.py` không có file `.sql` (users.ocr_enabled,
  jobs.preprocess/output_format/layout_style, worker_heartbeats chỉ có .md) → DB cũ thiếu.
- 2026-11-03 audit: CI thiếu `worker pytest` + `npm run lint` (README.md:66-68 nói có).
- 2026-11-03 audit: `docs/e2e-checklist.md` 0/69 box, section J retired nhưng còn đó; I5/K2 còn
  nhắc route `/edit` đã gỡ; M3-web (iframe) obsolete từ khi có Tiptap.
- 2026-11-03 audit: `.worktrees/plan-auth`, `.worktrees/plan-pr` là thư mục mồ côi (không còn
  trong `git worktree list`) — chỉ `lane-deps` là worktree thật.
- 2026-11-03 audit: item "mất dấu xuống dòng" đã sửa trong `layout_spec.py` (~dòng 370) — test
  chưa chạy được vì Postgres :5433 down (pytest cần test DB).
- Branch: 24/24 branch đều đã merge vào master → dọn được, không mất việc.
